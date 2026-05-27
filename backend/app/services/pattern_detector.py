"""
Pattern Detector Service

Clusters similar low-quality responses to identify systematic issues.
Uses embedding similarity + keyword matching to group failures by topic.

Patterns detected:
  - Topic clusters (e.g., "policy questions", "pricing queries")
  - Failure types (e.g., "hallucination", "off_topic", "too_vague")
  - High-impact patterns (frequent + severe)

Output: FailurePattern records in the database for admin review.
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
import re

from sqlalchemy.orm import Session

from app.models.quality import QualityScore, FailurePattern
from app.models.chat import ChatMessage
from app.models.whatsapp import WhatsAppMessage
from app.services.embedding_provider import EmbeddingService

logger = logging.getLogger(__name__)

# Minimum similarity threshold for grouping two failures
SIMILARITY_THRESHOLD = 0.40
# Minimum messages to form a pattern
MIN_PATTERN_SIZE = 2
# How far back to scan
LOOKBACK_HOURS = 72

# Common failure type keywords for rule-based classification
FAILURE_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "hallucination": [
        "i don't have information", "i couldn't find", "not in my knowledge",
        "i don't have access", "i'm not aware", "no data available",
        "i cannot confirm", "i am not sure",
    ],
    "off_topic": [
        "that's a different topic", "that's not related", "i can't help with that",
        "this is beyond", "out of scope", "i'm not designed",
    ],
    "too_vague": [
        "could you provide more", "can you clarify", "please elaborate",
        "i need more information", "could you be more specific",
        "i don't understand the question",
    ],
    "generic": [
        "as an ai", "i can help", "please feel free", "let me know if",
        "i'm here to help", "is there anything else", "how can i assist",
    ],
    "incomplete": [
        "one of the", "some of the", "partially", "in short",
        "briefly", "for more information",
    ],
}


def _tokenize(text: str) -> Set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _classify_failure_type(user_query: str, bot_response: str, flaws: List[str]) -> str:
    """Classify the primary failure type using flaws from scorer + keyword matching."""
    if flaws:
        flaw = flaws[0]
        if flaw in {"hallucination", "off_topic", "incomplete", "too_vague", "too_verbose", "generic"}:
            return flaw

    response_lower = bot_response.lower()
    for ftype, keywords in FAILURE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in response_lower:
                return ftype

    return "unknown"


def _extract_key_terms(text: str, max_terms: int = 5) -> List[str]:
    """Extract meaningful key terms from user query."""
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "nor", "not", "so", "yet", "both", "either", "neither", "this", "that",
        "these", "those", "i", "me", "my", "we", "our", "you", "your", "it",
        "its", "they", "them", "their", "what", "which", "who", "whom",
        "when", "where", "why", "how", "all", "each", "every", "some", "any",
        "no", "none", "please", "help", "need", "want", "like", "get",
    }
    tokens = _tokenize(text)
    filtered = [t for t in tokens if t not in stop_words and len(t) > 2]
    counts = Counter(filtered)
    return [word for word, _ in counts.most_common(max_terms)]


def _compute_similarity(terms_a: List[str], terms_b: List[str]) -> float:
    """Jaccard similarity between two term sets."""
    set_a = set(terms_a)
    set_b = set(terms_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a.intersection(set_b)
    union = set_a.union(set_b)
    return len(intersection) / len(union) if union else 0.0


class PatternDetector:
    """
    Detects and clusters failure patterns from quality scores.
    """

    def __init__(self, embedding_service: Optional[EmbeddingService] = None):
        self.embedding_service = embedding_service or EmbeddingService.instance()

    def detect_for_tenant(
        self,
        db: Session,
        tenant_id: str,
        lookback_hours: int = LOOKBACK_HOURS,
    ) -> List[FailurePattern]:
        """
        Scan recent low-quality responses and cluster them into patterns.
        Returns newly created/updated FailurePattern records.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        low_scores = (
            db.query(QualityScore)
            .filter(
                QualityScore.tenant_id == tenant_id,
                QualityScore.overall_score < 0.50,
                QualityScore.created_at >= cutoff,
            )
            .order_by(QualityScore.created_at.desc())
            .all()
        )

        if not low_scores:
            logger.info(f"[PatternDetector] No low scores for tenant {tenant_id}")
            return []

        # Enrich with messages
        enriched = self._enrich_scores(db, low_scores, tenant_id)
        if not enriched:
            return []

        # Cluster by similarity
        clusters = self._cluster(enriched)

        # Persist patterns
        patterns = []
        existing = self._load_existing_patterns(db, tenant_id)

        for cluster in clusters:
            if len(cluster["message_ids"]) < MIN_PATTERN_SIZE:
                continue

            pattern = self._upsert_pattern(db, tenant_id, cluster, existing)
            if pattern:
                patterns.append(pattern)

        db.commit()

        # Deactivate stale patterns
        self._cleanup_stale(db, tenant_id, patterns)

        logger.info(
            f"[PatternDetector] Tenant {tenant_id}: "
            f"{len(low_scores)} low scores → {len(clusters)} clusters → {len(patterns)} patterns"
        )
        return patterns

    def _enrich_scores(
        self,
        db: Session,
        scores: List[QualityScore],
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """Join quality scores with actual message content (web + WhatsApp)."""
        # Split scores by channel
        web_ids = [s.message_id for s in scores if s.channel in (None, "", "web_chatbot", "web")]
        wa_ids = [s.message_id for s in scores if s.channel == "whatsapp"]

        # Fetch web messages
        messages = {}
        if web_ids:
            for m in db.query(ChatMessage).filter(ChatMessage.id.in_(web_ids)).all():
                messages[m.id] = m

        # Fetch WhatsApp messages
        wa_messages = {}
        if wa_ids:
            for m in db.query(WhatsAppMessage).filter(WhatsAppMessage.id.in_(wa_ids)).all():
                wa_messages[m.id] = m

        user_queries = {}
        for score in scores:
            msg = messages.get(score.message_id) or wa_messages.get(score.message_id)
            if not msg:
                continue

            if score.channel == "whatsapp":
                # Find preceding inbound WhatsApp message from same contact
                user_msg = (
                    db.query(WhatsAppMessage)
                    .filter(
                        WhatsAppMessage.contact_id == msg.contact_id,
                        WhatsAppMessage.direction == "inbound",
                        WhatsAppMessage.created_at < msg.created_at,
                    )
                    .order_by(WhatsAppMessage.created_at.desc())
                    .first()
                )
                if user_msg:
                    user_queries[score.message_id] = user_msg.content or ""
            else:
                # Web chat: find preceding user message in same session
                user_msg = (
                    db.query(ChatMessage)
                    .filter(
                        ChatMessage.session_id == msg.session_id,
                        ChatMessage.role == "user",
                        ChatMessage.created_at < msg.created_at,
                    )
                    .order_by(ChatMessage.created_at.desc())
                    .first()
                )
                if user_msg:
                    user_queries[score.message_id] = user_msg.content or ""

        enriched = []
        for score in scores:
            msg = messages.get(score.message_id) or wa_messages.get(score.message_id)
            if not msg:
                continue
            user_query = user_queries.get(score.message_id, "")
            enriched.append({
                "score": score,
                "message": msg,
                "user_query": user_query,
                "bot_response": msg.content or "",
                "flaws": score.flaws or [],
                "terms": _extract_key_terms(user_query),
                "failure_type": _classify_failure_type(
                    user_query, msg.content or "", score.flaws or []
                ),
            })

        return enriched

    def _cluster(self, enriched: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group enriched scores into clusters by similarity."""
        clusters = []
        assigned = set()

        for i, item in enumerate(enriched):
            if i in assigned:
                continue

            cluster = {
                "message_ids": [item["score"].message_id],
                "user_queries": [item["user_query"]],
                "terms": item["terms"][:3],
                "failure_type": item["failure_type"],
                "scores": [item["score"].overall_score],
                "flaws_list": [item["flaws"]],
                "channels": [item["score"].channel or "web"],
            }

            for j in range(i + 1, len(enriched)):
                if j in assigned:
                    continue
                other = enriched[j]

                sim = _compute_similarity(item["terms"], other["terms"])
                if sim >= SIMILARITY_THRESHOLD:
                    cluster["message_ids"].append(other["score"].message_id)
                    cluster["user_queries"].append(other["user_query"])
                    cluster["scores"].append(other["score"].overall_score)
                    cluster["flaws_list"].append(other["flaws"])
                    cluster["channels"].append(other["score"].channel or "web")
                    assigned.add(j)

                    # Merge failure_type if conflicts
                    if other["failure_type"] != cluster["failure_type"]:
                        cluster["failure_type"] = "mixed"

            assigned.add(i)
            cluster["avg_score"] = sum(cluster["scores"]) / len(cluster["scores"])
            cluster["impact_score"] = round(
                (1.0 - cluster["avg_score"]) * (len(cluster["message_ids"]) / 10.0),
                4,
            )
            clusters.append(cluster)

        # Sort by impact (highest first)
        clusters.sort(key=lambda c: c["impact_score"], reverse=True)
        return clusters

    def _load_existing_patterns(self, db: Session, tenant_id: str) -> Dict[str, FailurePattern]:
        """Load existing active patterns for matching."""
        patterns = (
            db.query(FailurePattern)
            .filter(
                FailurePattern.tenant_id == tenant_id,
            )
            .all()
        )
        return {p.id: p for p in patterns}

    def _upsert_pattern(
        self,
        db: Session,
        tenant_id: str,
        cluster: Dict[str, Any],
        existing: Dict[str, FailurePattern],
    ) -> FailurePattern:
        """Find existing pattern or create new one to avoid duplicates."""
        keywords = list(dict.fromkeys(
            term for terms in [cluster["terms"]] for term in terms
        ))
        sample_queries = cluster["user_queries"][:5]
        pattern_name = f"{cluster['failure_type'].replace('_', ' ').title()}: {', '.join(keywords[:3])}"

        # Determine dominant channel
        channels = cluster.get("channels", ["web"])
        channel_counts = Counter(c for c in channels if c)
        dominant_channel = channel_counts.most_common(1)[0][0] if channel_counts else "web"

        # Try to match an existing pattern with same type and overlapping keywords
        keyword_set = set(keywords)
        for pat in existing.values():
            if pat.pattern_type != cluster["failure_type"]:
                continue
            existing_kw = set(pat.cluster_keywords or [])
            if keyword_set.intersection(existing_kw):
                # Update in-place
                merged_ids = list(dict.fromkeys((pat.message_ids or []) + cluster["message_ids"]))
                merged_queries = list(dict.fromkeys((pat.sample_queries or []) + sample_queries))[:5]
                pat.message_ids = merged_ids
                pat.pattern_name = pattern_name[:255]
                pat.description = f"Cluster of {len(merged_ids)} low-quality responses with avg score {cluster['avg_score']:.2f}"
                pat.cluster_keywords = list(dict.fromkeys(existing_kw.union(keyword_set)))[:10]
                pat.sample_queries = merged_queries
                pat.message_count = len(merged_ids)
                pat.avg_score = round(cluster["avg_score"], 4)
                pat.impact_score = round(cluster["impact_score"], 4)
                pat.is_actionable = cluster["failure_type"] not in {"unknown", "mixed"}
                pat.channel = dominant_channel
                pat.updated_at = datetime.now(timezone.utc)
                db.flush()
                return pat

        # No match — create new
        pattern = FailurePattern(
            tenant_id=tenant_id,
            channel=dominant_channel,
            pattern_name=pattern_name[:255],
            pattern_type=cluster["failure_type"],
            description=f"Cluster of {len(cluster['message_ids'])} low-quality responses "
                        f"with avg score {cluster['avg_score']:.2f}",
            cluster_keywords=keywords[:10],
            sample_queries=sample_queries,
            message_ids=cluster["message_ids"],
            message_count=len(cluster["message_ids"]),
            avg_score=round(cluster["avg_score"], 4),
            impact_score=round(cluster["impact_score"], 4),
            is_actionable=cluster["failure_type"] not in {"unknown", "mixed"},
        )
        db.add(pattern)
        db.flush()
        return pattern

    def _cleanup_stale(
        self,
        db: Session,
        tenant_id: str,
        current_patterns: List[FailurePattern],
    ):
        """Soft-delete patterns that are no longer relevant."""
        current_ids = {p.id for p in current_patterns}
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        stale = (
            db.query(FailurePattern)
            .filter(
                FailurePattern.tenant_id == tenant_id,
                ~FailurePattern.id.in_(current_ids),
                FailurePattern.created_at < cutoff,
            )
            .all()
        )

        for pattern in stale:
            pattern.message_count = 0
            pattern.impact_score = 0.0
