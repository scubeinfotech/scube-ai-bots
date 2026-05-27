"""
Quality Scorer Service

LLM-as-judge that evaluates every bot response across 5 dimensions:
  Relevance, Accuracy, Completeness, Conciseness, Tone

Runs asynchronously after the response is delivered — zero impact on production latency.
Uses a lightweight judge model (Gemini Flash by default) for cost efficiency.

Scoring rubric (0.0 - 1.0 per dimension):
  0.0-0.3: Poor    |  0.3-0.5: Below Avg  |  0.5-0.7: Acceptable
  0.7-0.9: Good    |  0.9-1.0: Excellent

Overall = weighted average: relevance:0.25, accuracy:0.30, completeness:0.20,
                              conciseness:0.10, tone:0.15
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.quality import QualityScore, QualityMetric
from app.models.chat import ChatMessage, ChatSession
from app.models.tenant import Tenant
from app.adapters.llm import get_llm_adapter

logger = logging.getLogger(__name__)

# Dimension weights for overall score calculation
DIMENSION_WEIGHTS = {
    "relevance": 0.25,
    "accuracy": 0.30,
    "completeness": 0.20,
    "conciseness": 0.10,
    "tone": 0.15,
}

# Score thresholds
EXCELLENT_THRESHOLD = 0.90
GOOD_THRESHOLD = 0.70
ACCEPTABLE_THRESHOLD = 0.50
LOW_SCORE_THRESHOLD = 0.50

# Default judge model: cheap & fast
JUDGE_MODEL = "gemini-1.5-flash"
JUDGE_PROVIDER = "gemini"

JUDGE_SYSTEM_PROMPT = """You are an expert AI response quality evaluator. Your task is to score a chatbot's response to a user query across 5 dimensions.

Rate each dimension on a scale of 0.0 to 1.0:

1. **Relevance**: How well does the response address the user's actual question?
2. **Accuracy**: Is the information factually correct (based on the provided context)?
3. **Completeness**: Does the response fully answer the query, or does it miss important aspects?
4. **Conciseness**: Is the response appropriately brief without being too short or unnecessarily verbose?
5. **Tone**: Is the tone appropriate, professional, and helpful for the context?

If a knowledge context is provided, use it to judge accuracy. If no context is provided, judge based on general knowledge.

Respond ONLY with a valid JSON object (no markdown, no backticks):
{
  "relevance": 0.0-1.0,
  "accuracy": 0.0-1.0,
  "completeness": 0.0-1.0,
  "conciseness": 0.0-1.0,
  "tone": 0.0-1.0,
  "flaws": ["list", "of", "identified", "flaws"],
  "suggestions": "brief suggestion for improvement"
}

Possible flaws: hallucination, off_topic, incomplete, too_vague, too_verbose,
incorrect, irrelevant, unhelpful, generic, contradictory, missing_context,
not_using_knowledge, inappropriate_tone

If the response is excellent (all dimensions > 0.9), return flaws as an empty list."""


def _compute_overall(scores: Dict[str, float]) -> float:
    weighted = sum(
        scores.get(dim, 0.0) * weight
        for dim, weight in DIMENSION_WEIGHTS.items()
    )
    return round(min(1.0, max(0.0, weighted)), 4)


def _build_judge_prompt(
    user_query: str,
    bot_response: str,
    knowledge_context: Optional[str] = None,
) -> str:
    parts = [f"User Query: {user_query}", f"Bot Response: {bot_response}"]
    if knowledge_context:
        parts.append(f"Knowledge Context: {knowledge_context[:2000]}")
    return "\n\n".join(parts)


def _parse_judge_response(raw: str) -> Optional[Dict[str, Any]]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None

    required = ["relevance", "accuracy", "completeness", "conciseness", "tone"]
    for key in required:
        if key not in data or not isinstance(data[key], (int, float)):
            return None
        data[key] = min(1.0, max(0.0, float(data[key])))

    data["flaws"] = data.get("flaws") or []
    data["suggestions"] = data.get("suggestions") or ""
    return data


async def score_response(
    user_query: str,
    bot_response: str,
    knowledge_context: Optional[str] = None,
    judge_model: str = JUDGE_MODEL,
) -> Dict[str, Any]:
    """
    Score a single response pair using LLM-as-judge.
    Returns dict with scores, flaws, and suggestions.
    """
    if not bot_response or not bot_response.strip():
        return {
            "relevance": 0.0,
            "accuracy": 0.0,
            "completeness": 0.0,
            "conciseness": 0.0,
            "tone": 0.0,
            "overall": 0.0,
            "flaws": ["empty_response"],
            "suggestions": "Response was empty",
            "judge_model": judge_model,
            "judge_latency_ms": 0,
        }

    prompt = _build_judge_prompt(user_query, bot_response, knowledge_context)

    start = time.time()
    try:
        adapter = get_llm_adapter(provider=JUDGE_PROVIDER)
        result = await adapter.generate(
            prompt=prompt,
            model=judge_model,
            temperature=0.1,
            max_tokens=512,
            system_prompt=JUDGE_SYSTEM_PROMPT,
        )
        latency_ms = int((time.time() - start) * 1000)
    except Exception as e:
        logger.warning(f"[QualityScorer] Judge LLM call failed: {e}")
        return _fallback_scorer(user_query, bot_response, judge_model, 0)

    if not result.get("success"):
        logger.warning(f"[QualityScorer] Judge LLM returned error: {result.get('error')}")
        return _fallback_scorer(user_query, bot_response, judge_model, int((time.time() - start) * 1000))

    parsed = _parse_judge_response(result.get("response", ""))
    if not parsed:
        logger.warning("[QualityScorer] Failed to parse judge response, using fallback")
        return _fallback_scorer(user_query, bot_response, judge_model, latency_ms)

    parsed["overall"] = _compute_overall(parsed)
    parsed["judge_model"] = judge_model
    parsed["judge_latency_ms"] = latency_ms
    return parsed


def _fallback_scorer(
    user_query: str,
    bot_response: str,
    judge_model: str,
    latency_ms: int,
) -> Dict[str, Any]:
    """
    Heuristic fallback when LLM judge is unavailable.
    Provides reasonable estimates using lexical analysis.
    """
    from app.services.query_analyzer import calculate_confidence_score, _relevance_score, _contains_useful_info

    relevance = _relevance_score(user_query, bot_response)
    base_confidence = calculate_confidence_score(user_query, bot_response)

    accuracy = min(1.0, base_confidence + 0.1)
    completeness = min(1.0, base_confidence + 0.05)
    response_len = len(bot_response.split())

    if response_len < 8:
        conciseness = 0.9 if relevance > 0.5 else 0.3
    elif response_len < 15:
        conciseness = 0.7
    elif response_len < 50:
        conciseness = 0.6
    else:
        conciseness = 0.4

    tone = 0.7
    if _contains_useful_info(bot_response):
        tone = 0.8

    flaws = []
    if relevance < 0.3:
        flaws.append("off_topic")
    if base_confidence < 0.4:
        flaws.append("low_confidence")

    scores = {
        "relevance": round(relevance, 4),
        "accuracy": round(accuracy, 4),
        "completeness": round(completeness, 4),
        "conciseness": round(conciseness, 4),
        "tone": round(tone, 4),
    }
    scores["overall"] = _compute_overall(scores)
    scores["flaws"] = flaws
    scores["suggestions"] = "Fallback scorer used — review response quality"
    scores["judge_model"] = f"{judge_model}_fallback"
    scores["judge_latency_ms"] = latency_ms
    return scores


async def score_and_persist(
    db: Session,
    tenant_id: str,
    message_id: str,
    channel: str,
    user_query: str,
    bot_response: str,
    knowledge_context: Optional[str] = None,
) -> QualityScore:
    """
    Score a response and persist the result to the database.
    This is fire-and-forget from the caller's perspective.
    """
    result = await score_response(user_query, bot_response, knowledge_context)

    score_record = QualityScore(
        tenant_id=tenant_id,
        message_id=message_id,
        channel=channel,
        relevance=result.get("relevance"),
        accuracy=result.get("accuracy"),
        completeness=result.get("completeness"),
        conciseness=result.get("conciseness"),
        tone=result.get("tone"),
        overall_score=result.get("overall", 0.0),
        judge_model=result.get("judge_model"),
        judge_latency_ms=result.get("judge_latency_ms"),
        flaws=result.get("flaws"),
        suggestions=result.get("suggestions"),
    )
    db.add(score_record)
    db.commit()
    return score_record


async def score_chat_message(db: Session, message_id: str) -> Optional[QualityScore]:
    """
    Score a specific chat message by its ID.
    Looks up the session to find the preceding user query.
    """
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not msg or msg.role != "assistant":
        return None

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
    if not user_msg:
        return None

    tenant = db.query(Tenant).filter(Tenant.id == msg.tenant_id).first()
    knowledge_context = None
    if tenant and isinstance(tenant.knowledge_context, dict):
        raw = json.dumps(tenant.knowledge_context, ensure_ascii=False)
        knowledge_context = raw[:2000] if len(raw) > 2000 else raw

    return await score_and_persist(
        db=db,
        tenant_id=msg.tenant_id,
        message_id=msg.id,
        channel="web_chatbot",
        user_query=user_msg.content or "",
        bot_response=msg.content or "",
        knowledge_context=knowledge_context,
    )


async def score_recent_messages(
    db: Session,
    tenant_id: str,
    hours_lookback: int = 1,
) -> int:
    """
    Score all unscored assistant messages within the lookback window.
    Returns the count of newly scored messages.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)

    unscored = (
        db.query(ChatMessage)
        .outerjoin(
            QualityScore,
            QualityScore.message_id == ChatMessage.id,
        )
        .filter(
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= cutoff,
            QualityScore.id.is_(None),
        )
        .all()
    )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    knowledge_context = None
    if tenant and isinstance(tenant.knowledge_context, dict):
        raw = json.dumps(tenant.knowledge_context, ensure_ascii=False)
        knowledge_context = raw[:2000] if len(raw) > 2000 else raw

    count = 0
    for msg in unscored:
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
        if not user_msg:
            continue

        try:
            await score_and_persist(
                db=db,
                tenant_id=tenant_id,
                message_id=msg.id,
                channel="web_chatbot",
                user_query=user_msg.content or "",
                bot_response=msg.content or "",
                knowledge_context=knowledge_context,
            )
            count += 1
        except Exception as e:
            logger.error(f"[QualityScorer] Failed to score message {msg.id}: {e}")
            continue

    return count


async def score_whatsapp_messages(
    db: Session,
    tenant_id: str,
    hours_lookback: int = 24,
) -> int:
    """
    Score all unscored WhatsApp outbound messages within lookback window.
    Pairs each outbound message with the preceding inbound message from the same contact.
    Returns count of newly scored messages.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)

    from app.models.whatsapp import WhatsAppMessage

    unscored = (
        db.query(WhatsAppMessage)
        .outerjoin(
            QualityScore,
            QualityScore.message_id == WhatsAppMessage.id,
        )
        .filter(
            WhatsAppMessage.tenant_id == tenant_id,
            WhatsAppMessage.direction == "outbound",
            WhatsAppMessage.created_at >= cutoff,
            QualityScore.id.is_(None),
        )
        .order_by(WhatsAppMessage.contact_id, WhatsAppMessage.created_at)
        .all()
    )

    if not unscored:
        return 0

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    knowledge_context = None
    if tenant and isinstance(tenant.knowledge_context, dict):
        raw = json.dumps(tenant.knowledge_context, ensure_ascii=False)
        knowledge_context = raw[:2000] if len(raw) > 2000 else raw

    count = 0
    for msg in unscored:
        # Find preceding inbound message from same contact
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
        if not user_msg:
            continue

        try:
            await score_and_persist(
                db=db,
                tenant_id=tenant_id,
                message_id=msg.id,
                channel="whatsapp",
                user_query=user_msg.content or "",
                bot_response=msg.content or "",
                knowledge_context=knowledge_context,
            )
            count += 1
        except Exception as e:
            logger.error(f"[QualityScorer] Failed to score WhatsApp message {msg.id}: {e}")
            continue

    return count


def run_quality_rollup(db: Session, tenant_id: str, metric_date: datetime.date) -> QualityMetric:
    """
    Aggregate daily quality metrics for a tenant.
    Called by the daily scheduler.
    """
    from sqlalchemy import func as sa_func

    day_start = datetime.combine(metric_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    day_end = datetime.combine(metric_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    scores = (
        db.query(QualityScore)
        .filter(
            QualityScore.tenant_id == tenant_id,
            QualityScore.created_at >= day_start,
            QualityScore.created_at <= day_end,
        )
        .all()
    )

    if not scores:
        existing = db.query(QualityMetric).filter(
            QualityMetric.tenant_id == tenant_id,
            QualityMetric.metric_date == metric_date,
            QualityMetric.period == "day",
        ).first()
        if not existing:
            existing = QualityMetric(
                tenant_id=tenant_id,
                metric_date=metric_date,
                period="day",
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing

    n = len(scores)
    avg_relevance = sum(s.relevance or 0.0 for s in scores) / n
    avg_accuracy = sum(s.accuracy or 0.0 for s in scores) / n
    avg_completeness = sum(s.completeness or 0.0 for s in scores) / n
    avg_conciseness = sum(s.conciseness or 0.0 for s in scores) / n
    avg_tone = sum(s.tone or 0.0 for s in scores) / n
    avg_overall = sum(s.overall_score for s in scores) / n

    low_count = sum(1 for s in scores if s.overall_score < LOW_SCORE_THRESHOLD)
    high_count = sum(1 for s in scores if s.overall_score >= GOOD_THRESHOLD)

    feedback_positive = (
        db.query(sa_func.count(ChatMessage.id))
        .filter(
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= day_start,
            ChatMessage.created_at <= day_end,
            ChatMessage.feedback_score == 1,
        )
        .scalar()
        or 0
    )

    feedback_negative = (
        db.query(sa_func.count(ChatMessage.id))
        .filter(
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= day_start,
            ChatMessage.created_at <= day_end,
            ChatMessage.feedback_score == -1,
        )
        .scalar()
        or 0
    )

    metric = db.query(QualityMetric).filter(
        QualityMetric.tenant_id == tenant_id,
        QualityMetric.metric_date == metric_date,
        QualityMetric.period == "day",
    ).first()

    if not metric:
        metric = QualityMetric(
            tenant_id=tenant_id,
            metric_date=metric_date,
            period="day",
        )
        db.add(metric)

    metric.total_messages = n
    metric.avg_overall_score = round(avg_overall, 4)
    metric.avg_relevance = round(avg_relevance, 4)
    metric.avg_accuracy = round(avg_accuracy, 4)
    metric.avg_completeness = round(avg_completeness, 4)
    metric.avg_conciseness = round(avg_conciseness, 4)
    metric.avg_tone = round(avg_tone, 4)
    metric.low_score_count = low_count
    metric.high_score_count = high_count
    metric.feedback_positive = feedback_positive
    metric.feedback_negative = feedback_negative

    db.commit()
    db.refresh(metric)
    return metric
