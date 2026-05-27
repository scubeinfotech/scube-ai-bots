"""
Self-Learning Service

Daily job that reads yesterday's conversations, extracts high-quality Q&A pairs,
and feeds them back into the tenant's vector knowledge base — purely dynamic,
no hardcoding, per-tenant isolated.

Learning criteria (a conversation pair qualifies if ANY of these are true):
  - feedback_score == 1 (explicit thumbs up from user)
  - confidence_score >= CONFIDENCE_THRESHOLD (high-quality detected-response pair)

Deduplication: a Q&A pair is skipped if a "learned" document already exists for
the same tenant containing the identical query.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChatMessage, ChatSession, Document, Tenant
from app.services.query_analyzer import calculate_confidence_with_feedback, _contains_useful_info
from app.services.vector_knowledge import VectorKnowledgeService

logger = logging.getLogger(__name__)

# Minimum confidence score to qualify as a learned pair (when no explicit feedback)
CONFIDENCE_THRESHOLD = 0.60
# Confidence threshold to auto-learn without thumbs-up (relaxed gate)
HIGH_CONFIDENCE_LEARN_THRESHOLD = 0.80
# Minimum response length to be worth learning (avoid very short "ok" replies)
MIN_RESPONSE_WORDS = 12
# Document type tag for auto-learned documents
LEARNED_DOC_TYPE = "learned"
LEARNED_CATEGORY = "auto-learned"
# Lookback window in hours for the daily job
LOOKBACK_HOURS = 24
SMALL_TALK_QUERIES = {
    "hi", "hello", "hey", "how are you", "how you doing", "how u doing", "good morning",
    "good afternoon", "good evening", "thanks", "thank you", "ok", "okay", "yes", "no"
}


def _is_too_short(text: str) -> bool:
    return len((text or "").split()) < MIN_RESPONSE_WORDS


def _is_small_talk_query(text: str) -> bool:
    query = (text or "").strip().lower()
    if not query:
        return True
    compact = " ".join(query.split())
    if compact in SMALL_TALK_QUERIES:
        return True
    tokens = compact.split()
    if len(tokens) <= 2 and compact in {"hi", "hello", "hey", "ok", "yes", "no"}:
        return True
    return False


def _make_document_content(user_query: str, assistant_response: str) -> str:
    """Format a Q&A pair as a knowledge document for vector indexing."""
    return f"Q: {user_query.strip()}\nA: {assistant_response.strip()}"


def _normalize_query_key(text: str) -> str:
    return (text or "").strip().lower()[:400]


def _extract_query_from_learned_doc(content: str) -> str:
    """Extract original query from learned doc format: Q: ...\nA: ..."""
    body = content or ""
    if not body.startswith("Q:"):
        return ""
    line = body.split("\n", 1)[0]
    return line[2:].strip()


def _promote_to_structured_faq(
    tenant: Tenant,
    user_query: str,
    assistant_response: str,
    confidence: float,
    explicit_thumbs_up: bool,
) -> bool:
    """Promote high-signal learned Q&A into tenant FAQ knowledge for structured retrieval."""
    if not explicit_thumbs_up and confidence < 0.92:
        return False

    knowledge = dict(tenant.knowledge_context) if isinstance(tenant.knowledge_context, dict) else {}
    faqs = list(knowledge.get("faqs") or []) if isinstance(knowledge.get("faqs"), list) else []
    normalized_query = _normalize_query_key(user_query)

    for faq in faqs:
        if not isinstance(faq, dict):
            continue
        existing_query = _normalize_query_key(str(faq.get("question") or ""))
        if existing_query == normalized_query:
            return False

    faqs.append(
        {
            "question": user_query.strip(),
            "answer": assistant_response.strip(),
            "source": "daily-learning",
            "confidence": round(confidence, 2),
            "verified": bool(explicit_thumbs_up),
        }
    )
    knowledge["faqs"] = faqs[-40:]
    tenant.knowledge_context = knowledge
    return True


def _load_existing_learned_queries(db: Session, tenant_id: str) -> Set[str]:
    """Load existing learned query keys for a tenant once per run for fast dedup."""
    docs = (
        db.query(Document)
        .filter(
            Document.tenant_id == tenant_id,
            Document.document_type == LEARNED_DOC_TYPE,
            Document.is_active == True,
        )
        .all()
    )
    keys: Set[str] = set()
    for doc in docs:
        query = _extract_query_from_learned_doc(doc.content or "")
        if query:
            keys.add(_normalize_query_key(query))
    return keys


def _init_tenant_bucket(stats: Dict[str, Any], tenant: Tenant) -> Dict[str, Any]:
    bucket = stats["per_tenant"].get(tenant.id)
    if bucket:
        return bucket
    bucket = {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "processed": 0,
        "learned": 0,
        "skipped": 0,
        "errors": 0,
        "skip_reasons": {},
    }
    stats["per_tenant"][tenant.id] = bucket
    return bucket


def _track_skip(stats: Dict[str, Any], bucket: Dict[str, Any], reason: str) -> None:
    stats["skipped"] += 1
    bucket["skipped"] += 1
    stats["skip_reasons"][reason] = stats["skip_reasons"].get(reason, 0) + 1
    bucket["skip_reasons"][reason] = bucket["skip_reasons"].get(reason, 0) + 1


def run_daily_learning_job() -> Dict[str, Any]:
    """
    Entry point for the scheduled daily self-learning job.
    Scans last 24 hours of conversations across all active tenants,
    extracts qualifying Q&A pairs, and indexes them as new knowledge.

    Returns stats dict with totals, per-tenant breakdown, and skip reasons.
    """
    db = SessionLocal()
    stats: Dict[str, Any] = {
        "processed": 0,
        "learned": 0,
        "skipped": 0,
        "errors": 0,
        "cutoff_hours": LOOKBACK_HOURS,
        "per_tenant": {},
        "skip_reasons": {},
    }
    try:
        _run_learning(db, stats)
    except Exception as e:
        logger.error(f"[SelfLearning] Fatal error in daily learning job: {e}")
        stats["errors"] += 1
    finally:
        db.close()

    # Convert per_tenant map to sorted list for API/UI friendliness.
    stats["per_tenant"] = sorted(
        list(stats["per_tenant"].values()),
        key=lambda t: t.get("tenant_name", "")
    )

    logger.info(
        f"[SelfLearning] Daily job complete — "
        f"processed={stats['processed']}, learned={stats['learned']}, "
        f"skipped={stats['skipped']}, errors={stats['errors']}"
    )
    return stats


def _run_learning(db: Session, stats: Dict[str, Any]) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    tenants: List[Tenant] = db.query(Tenant).filter(Tenant.is_active == True).all()
    if not tenants:
        logger.info("[SelfLearning] No active tenants found.")
        return

    for tenant in tenants:
        try:
            _learn_for_tenant(db, tenant, cutoff, stats)
        except Exception as e:
            logger.error(f"[SelfLearning] Error processing tenant {tenant.id} ({tenant.name}): {e}")
            stats["errors"] += 1
            continue

    db.commit()


def _learn_for_tenant(
    db: Session, tenant: Tenant, cutoff: datetime, stats: Dict[str, Any]
) -> None:
    bucket = _init_tenant_bucket(stats, tenant)
    existing_learned_keys = _load_existing_learned_queries(db, tenant.id)
    learned_this_run: Set[str] = set()

    # Message-level cutoff ensures recent activity in older sessions is included.
    recent_user_messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.tenant_id == tenant.id,
            ChatMessage.role == "user",
            ChatMessage.created_at >= cutoff,
        )
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    for user_msg in recent_user_messages:
        assistant_msg = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == user_msg.session_id,
                ChatMessage.role == "assistant",
                ChatMessage.created_at >= user_msg.created_at,
            )
            .order_by(ChatMessage.created_at.asc())
            .first()
        )

        if not assistant_msg:
            _track_skip(stats, bucket, "no_assistant_reply")
            continue

        stats["processed"] += 1
        bucket["processed"] += 1

        user_query = (user_msg.content or "").strip()
        assistant_response = (assistant_msg.content or "").strip()

        if not user_query:
            _track_skip(stats, bucket, "empty_user_query")
            continue

        if not assistant_response:
            _track_skip(stats, bucket, "empty_assistant_response")
            continue

        if _is_small_talk_query(user_query):
            _track_skip(stats, bucket, "small_talk_query")
            continue

        # Skip very short responses — usually weak/noisy for long-term learning.
        if _is_too_short(assistant_response):
            _track_skip(stats, bucket, "response_too_short")
            continue

        confidence = calculate_confidence_with_feedback(
            user_query,
            assistant_response,
            assistant_msg.feedback_score,
        )
        explicit_thumbs_up = assistant_msg.feedback_score == 1

        # Only learn if user explicitly gave thumbs-up (requires human approval)
        # Learn if user gave thumbs-up OR high confidence response (no thumbs-up needed)
        if not explicit_thumbs_up and confidence < HIGH_CONFIDENCE_LEARN_THRESHOLD:
            _track_skip(stats, bucket, "low_confidence_no_feedback")
            continue

        query_key = _normalize_query_key(user_query)
        if query_key in learned_this_run:
            _track_skip(stats, bucket, "duplicate_within_current_run")
            continue
        if query_key in existing_learned_keys:
            _track_skip(stats, bucket, "duplicate_already_learned")
            continue

        try:
            content = _make_document_content(user_query, assistant_response)
            doc_name = (
                f"Auto-learned: {user_query[:60]}..."
                if len(user_query) > 60
                else f"Auto-learned: {user_query}"
            )
            document = Document(
                tenant_id=tenant.id,
                name=doc_name,
                content=content,
                document_type=LEARNED_DOC_TYPE,
                category=LEARNED_CATEGORY,
                is_active=True,
            )
            db.add(document)
            db.flush()

            VectorKnowledgeService.index_document(db, document)
            _promote_to_structured_faq(
                tenant,
                user_query,
                assistant_response,
                confidence,
                explicit_thumbs_up,
            )

            learned_this_run.add(query_key)
            existing_learned_keys.add(query_key)
            stats["learned"] += 1
            bucket["learned"] += 1

            logger.info(
                f"[SelfLearning] Tenant={tenant.name} | "
                f"Learned: '{user_query[:60]}' | "
                f"confidence={confidence:.2f} | thumbs_up={explicit_thumbs_up}"
            )
        except Exception as e:
            logger.error(
                f"[SelfLearning] Failed to index learned pair for tenant {tenant.id}: {e}"
            )
            stats["errors"] += 1
            bucket["errors"] += 1
