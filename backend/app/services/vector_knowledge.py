"""
Vector knowledge service.
- Chunks documents
- Generates embeddings via the centralized ``EmbeddingService`` (bge-m3 by
  default; configurable through ``EMBEDDING_PROVIDER`` / ``EMBEDDING_MODEL``)
- Retrieves semantically similar chunks for chat context
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.embedding_provider import EmbeddingService

logger = logging.getLogger(__name__)


class BM25Helper:
    """
    Pure-Python BM25 scorer — no external dependencies required.

    Usage:
        bm25 = BM25Helper(corpus_texts)
        score = bm25.score(query, doc_index)
    """

    K1 = 1.5
    B = 0.75
    AVG_DL = 0  # set after construction

    def __init__(self, documents: List[str]):
        self.documents = documents
        self.N = len(documents)
        self.doc_term_freqs: List[Dict[str, int]] = []
        self.doc_lengths: List[int] = []
        self._idf: Dict[str, float] = {}
        self._build_index()

    def _build_index(self):
        for doc in self.documents:
            tokens = self._tokenize(doc)
            tf: Dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            self.doc_term_freqs.append(tf)
            self.doc_lengths.append(len(tokens))

        if self.N > 0:
            self.AVG_DL = sum(self.doc_lengths) / self.N

        df: Dict[str, int] = {}
        for tf in self.doc_term_freqs:
            for term in tf:
                df[term] = df.get(term, 0) + 1

        for term, df_t in df.items():
            self._idf[term] = math.log(
                (self.N - df_t + 0.5) / (df_t + 0.5) + 1
            )

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", (text or "").lower())

    def score(self, query: str, doc_index: int) -> float:
        if doc_index < 0 or doc_index >= self.N:
            return 0.0
        query_terms = self._tokenize(query)
        tf_map = self.doc_term_freqs[doc_index]
        dl = self.doc_lengths[doc_index]
        score = 0.0
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf.get(term, 0.0)
            tf_component = (tf * (self.K1 + 1)) / (
                tf + self.K1 * (1 - self.B + self.B * (dl / max(self.AVG_DL, 1)))
            )
            score += idf * tf_component
        return score


def _compute_bm25_scores(
    query: str,
    corpus: List[Tuple[str, str]],  # List[(chunk_id, chunk_text)]
    top_k: int = 20,
) -> List[Tuple[float, str, str]]:
    """
    Compute BM25 scores for all chunks. Returns top-k as (score, chunk_id, chunk_text).
    Falls back to lexical-overlap scoring if corpus is empty.
    """
    if not corpus:
        return []

    texts = [c[1] for c in corpus]
    bm25 = BM25Helper(texts)

    scores: List[Tuple[float, str, str]] = []
    for i, (chunk_id, chunk_text) in enumerate(corpus):
        raw = bm25.score(query, i)
        scores.append((raw, chunk_id, chunk_text))

    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[:top_k]


class VectorKnowledgeService:
    """Tenant-isolated vector indexing and retrieval."""

    # ``EMBEDDING_DIM`` is only used by the hashed fallback in
    # ``embedding_provider``. Real provider vectors (bge-m3=1024,
    # text-embedding-3-small=1536, nomic-embed-text=768) carry their own
    # dimension; cosine_similarity() handles mixed dims via min-length.
    CHUNK_WORDS = 140
    CHUNK_OVERLAP = 30
    MIN_HEADING_CHUNK_WORDS = 8
    CHUNK_WORDS_MIN = 60
    CHUNK_WORDS_MAX = 300
    CHUNK_OVERLAP_MIN = 10
    CHUNK_OVERLAP_MAX = 100
    MIN_HEADING_WORDS_MIN = 4
    MIN_HEADING_WORDS_MAX = 40
    TOP_K_DEFAULT = 6
    MAX_PER_DOCUMENT = 3

    @classmethod
    def index_document(cls, db: Session, document: Document) -> int:
        """Rebuild vector chunks for one document. Returns chunk count."""
        if not document or not document.content:
            return 0

        cls._invalidate_bm25_cache(document.tenant_id)
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()

        rag_cfg = cls.get_tenant_rag_config(db, document.tenant_id)
        chunks = cls._split_into_chunks(
            document.content,
            chunk_words=rag_cfg["chunk_words"],
            chunk_overlap=rag_cfg["chunk_overlap"],
            min_heading_chunk_words=rag_cfg["min_heading_chunk_words"],
        )
        count = 0
        # Batch-encode all chunks for a single document. With bge-m3 on CPU
        # this is roughly 5-10x faster than encoding one chunk at a time.
        embeddings = EmbeddingService.instance().embed_batch(chunks) if chunks else []
        for idx, chunk_text in enumerate(chunks):
            embedding = embeddings[idx] if idx < len(embeddings) else cls._embed_text(chunk_text)
            chunk = DocumentChunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                chunk_index=idx,
                content=chunk_text,
                embedding=embedding,
                source_name=document.name,
                source_url=document.file_path,
            )
            db.add(chunk)
            count += 1

        document.is_processed = True
        db.flush()
        return count

    @classmethod
    def get_tenant_rag_config(cls, db: Session, tenant_id: str) -> Dict[str, int]:
        """Resolve effective tenant RAG chunking config with safe bounds."""
        # Fallback defaults first.
        cfg = {
            "chunk_words": cls.CHUNK_WORDS,
            "chunk_overlap": cls.CHUNK_OVERLAP,
            "min_heading_chunk_words": cls.MIN_HEADING_CHUNK_WORDS,
        }

        # Pull tenant config from knowledge_context.rag_profile when available.
        # Delayed import keeps model dependency local and avoids circular imports.
        from app.models import Tenant  # local import

        tenant_row = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant_row:
            return cfg

        knowledge = tenant_row.knowledge_context if isinstance(tenant_row.knowledge_context, dict) else {}
        profile = knowledge.get("rag_profile") if isinstance(knowledge.get("rag_profile"), dict) else {}

        cfg["chunk_words"] = cls._clamp_int(
            profile.get("chunk_words"),
            cls.CHUNK_WORDS,
            cls.CHUNK_WORDS_MIN,
            cls.CHUNK_WORDS_MAX,
        )
        cfg["chunk_overlap"] = cls._clamp_int(
            profile.get("chunk_overlap"),
            cls.CHUNK_OVERLAP,
            cls.CHUNK_OVERLAP_MIN,
            cls.CHUNK_OVERLAP_MAX,
        )
        cfg["min_heading_chunk_words"] = cls._clamp_int(
            profile.get("min_heading_chunk_words"),
            cls.MIN_HEADING_CHUNK_WORDS,
            cls.MIN_HEADING_WORDS_MIN,
            cls.MIN_HEADING_WORDS_MAX,
        )

        # Ensure overlap is always strictly smaller than chunk size.
        cfg["chunk_overlap"] = min(cfg["chunk_overlap"], max(1, cfg["chunk_words"] - 5))
        return cfg

    @classmethod
    def index_tenant_documents(cls, db: Session, tenant_id: str) -> Dict[str, int]:
        """Reindex all active documents for a tenant."""
        documents = db.query(Document).filter(
            Document.tenant_id == tenant_id,
            Document.is_active == True,
        ).all()

        total_chunks = 0
        for doc in documents:
            total_chunks += cls.index_document(db, doc)

        db.commit()
        return {"documents": len(documents), "chunks": total_chunks}

    @classmethod
    def get_index_stats(cls, db: Session, tenant_id: str) -> Dict[str, int]:
        """Get current vector index stats for a tenant."""
        document_count = db.query(Document).filter(
            Document.tenant_id == tenant_id,
            Document.is_active == True,
        ).count()
        chunk_count = db.query(DocumentChunk).filter(
            DocumentChunk.tenant_id == tenant_id,
        ).count()
        return {"documents": document_count, "chunks": chunk_count}

    SEMANTIC_WEIGHT = 0.65
    LEXICAL_WEIGHT = 0.35
    MIN_SCORE = 0.15
    BM25_TOP_K = 20

    # In-memory BM25 cache: tenant_id -> { "signature": str, "bm25": BM25Helper, "max_bm25": float }
    _bm25_cache: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def _corpus_signature(cls, rows: List[DocumentChunk]) -> str:
        """Deterministic hash of chunk IDs to detect corpus changes."""
        return hashlib.md5(
            "|".join(str(row.id) for row in rows).encode()
        ).hexdigest()

    @classmethod
    def _invalidate_bm25_cache(cls, tenant_id: str) -> None:
        cls._bm25_cache.pop(tenant_id, None)

    @classmethod
    def search(cls, db: Session, tenant_id: str, query: str, top_k: int = TOP_K_DEFAULT) -> List[Dict[str, Any]]:
        """
        Hybrid search: BM25 lexical + vector semantic, combined and re-ranked.

        Flow:
        1. Fetch all active chunks for tenant.
        2. Build BM25 index over chunk texts (cached per tenant when corpus unchanged).
        3. Score each chunk with: SEMANTIC_WEIGHT * cosine + LEXICAL_WEIGHT * norm_bm25.
        4. Filter below MIN_SCORE, dedupe by content signature, cap per document.
        5. Return top-k chunks with combined score.
        """
        if not query or not query.strip():
            return []

        rows = db.query(DocumentChunk).join(
            Document, DocumentChunk.document_id == Document.id
        ).filter(
            DocumentChunk.tenant_id == tenant_id,
            Document.is_active == True
        ).all()
        if not rows:
            return []

        query_embedding = cls._embed_text(query)

        # Build or reuse BM25 index from cache.
        sig = cls._corpus_signature(rows)
        cached = cls._bm25_cache.get(tenant_id)
        if cached and cached.get("signature") == sig:
            bm25 = cached["bm25"]
        else:
            texts = [row.content for row in rows]
            bm25 = BM25Helper(texts)
            cls._bm25_cache[tenant_id] = {
                "signature": sig,
                "bm25": bm25,
            }

        bm25_map: Dict[str, float] = {}
        bm25_vals: List[float] = []
        for i, row in enumerate(rows):
            s = bm25.score(query, i)
            bm25_map[str(row.id)] = s
            bm25_vals.append(s)
        max_bm25 = max(bm25_vals, default=1.0)
        max_bm25 = max(max_bm25, 1.0)

        scored: List[Tuple[float, DocumentChunk]] = []
        for row in rows:
            semantic_score = cls._cosine_similarity(query_embedding, row.embedding or [])
            bm25_raw = bm25_map.get(str(row.id), 0.0)
            bm25_norm = bm25_raw / max_bm25
            combined = (cls.SEMANTIC_WEIGHT * semantic_score) + (cls.LEXICAL_WEIGHT * bm25_norm)

            if combined < cls.MIN_SCORE:
                continue

            scored.append((combined, row))

        scored.sort(key=lambda item: item[0], reverse=True)

        per_doc_counts: Dict[str, int] = {}
        seen_signatures = set()
        results = []
        for score, row in scored:
            if len(results) >= max(1, top_k):
                break

            doc_count = per_doc_counts.get(row.document_id, 0)
            if doc_count >= cls.MAX_PER_DOCUMENT:
                continue

            signature = cls._content_signature(row.content)
            if signature in seen_signatures:
                continue

            seen_signatures.add(signature)
            per_doc_counts[row.document_id] = doc_count + 1
            results.append(
                {
                    "score": round(score, 4),
                    "content": row.content,
                    "source_name": row.source_name,
                    "source_url": row.source_url,
                    "document_id": row.document_id,
                }
            )
        return results

    @classmethod
    def _split_into_chunks(
        cls,
        text: str,
        chunk_words: int | None = None,
        chunk_overlap: int | None = None,
        min_heading_chunk_words: int | None = None,
    ) -> List[str]:
        raw_text = (text or "").strip()
        if not raw_text:
            return []

        chunk_words = cls._clamp_int(chunk_words, cls.CHUNK_WORDS, cls.CHUNK_WORDS_MIN, cls.CHUNK_WORDS_MAX)
        chunk_overlap = cls._clamp_int(chunk_overlap, cls.CHUNK_OVERLAP, cls.CHUNK_OVERLAP_MIN, cls.CHUNK_OVERLAP_MAX)
        min_heading_chunk_words = cls._clamp_int(
            min_heading_chunk_words,
            cls.MIN_HEADING_CHUNK_WORDS,
            cls.MIN_HEADING_WORDS_MIN,
            cls.MIN_HEADING_WORDS_MAX,
        )
        chunk_overlap = min(chunk_overlap, max(1, chunk_words - 5))

        # First split by semantic sections to keep heading + local body together.
        # This improves retrieval quality for documents with short business headers.
        sections = cls._split_into_sections(raw_text, min_heading_chunk_words=min_heading_chunk_words)
        chunks: List[str] = []

        for section in sections:
            section_text = " ".join(section.split())
            if not section_text:
                continue

            words = section_text.split(" ")
            if len(words) <= chunk_words:
                chunks.append(section_text)
                continue

            # Long sections still use sliding windows with overlap.
            start = 0
            while start < len(words):
                end = min(len(words), start + chunk_words)
                chunk_words_slice = words[start:end]
                if chunk_words_slice:
                    chunks.append(" ".join(chunk_words_slice))
                if end >= len(words):
                    break
                start = max(0, end - chunk_overlap)

        return chunks

    @classmethod
    def _split_into_sections(cls, text: str, min_heading_chunk_words: int) -> List[str]:
        """Split document into heading-oriented sections before window chunking."""
        lines = [line.strip() for line in text.splitlines()]
        sections: List[str] = []
        current: List[str] = []

        for line in lines:
            if not line:
                continue

            if cls._looks_like_heading(line) and current:
                sections.append("\n".join(current))
                current = [line]
            else:
                current.append(line)

        if current:
            sections.append("\n".join(current))

        # Merge tiny sections so very short headings don't become sparse vectors.
        merged: List[str] = []
        for section in sections:
            words = len(section.split())
            if not merged:
                merged.append(section)
                continue

            if words < min_heading_chunk_words:
                merged[-1] = merged[-1] + "\n" + section
            else:
                merged.append(section)

        return merged

    @staticmethod
    def _looks_like_heading(line: str) -> bool:
        """Heuristic heading detector for bullets, title lines, and markdown headers."""
        if not line:
            return False

        if line.startswith("#"):
            return True
        if re.match(r"^[-*]\s+", line):
            return True
        if re.match(r"^[A-Z][A-Za-z0-9&() /-]{2,80}:$", line):
            return True

        # Short title-case lines without sentence punctuation are likely headings.
        word_count = len(line.split())
        if 1 <= word_count <= 8 and not re.search(r"[.!?]", line):
            alpha_words = re.findall(r"[A-Za-z]+", line)
            if alpha_words:
                titled = sum(1 for w in alpha_words if w[0].isupper())
                if titled >= max(1, int(0.6 * len(alpha_words))):
                    return True

        return False

    @staticmethod
    def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = default
        if parsed < min_value:
            return min_value
        if parsed > max_value:
            return max_value
        return parsed

    @classmethod
    def _embed_text(cls, text: str) -> List[float]:
        """Embed text via the centralized provider (bge-m3 by default).

        All provider selection / fallback / disabling logic now lives in
        ``embedding_provider.EmbeddingService``; this method is just a thin
        shim kept for backward compatibility with existing call sites in
        chat_service and search.
        """
        return EmbeddingService.instance().embed(text)

    @staticmethod
    def _tokenize(text: str) -> set:
        return set(re.findall(r"[a-z0-9]+", (text or "").lower()))

    @classmethod
    def _lexical_overlap_score(cls, query_terms: set, content: str) -> float:
        if not query_terms:
            return 0.0
        content_terms = cls._tokenize(content)
        if not content_terms:
            return 0.0
        overlap = len(query_terms.intersection(content_terms))
        return min(1.0, overlap / max(1, len(query_terms)))

    @classmethod
    def _content_signature(cls, content: str) -> str:
        terms = sorted(list(cls._tokenize((content or "")[:500])))
        return "|".join(terms[:24])

    @classmethod
    def delete_all_vectors_for_tenant(cls, db: Session, tenant_id: str) -> int:
        """Delete all vector chunks for a tenant. Returns count of deleted chunks."""
        cls._invalidate_bm25_cache(tenant_id)
        deleted = db.query(DocumentChunk).filter(
            DocumentChunk.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        db.flush()
        return deleted

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors. Handles different dimensions."""
        if not a or not b:
            return 0.0

        # Use minimum length to handle different embedding dimensions
        length = min(len(a), len(b))
        if length == 0:
            return 0.0

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for i in range(length):
            av = float(a[i])
            bv = float(b[i])
            dot += av * bv
            norm_a += av * av
            norm_b += bv * bv

        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
