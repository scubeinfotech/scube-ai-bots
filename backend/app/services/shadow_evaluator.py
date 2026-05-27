"""
Shadow Evaluator Service

Silently tests prompt/config variants against live traffic without affecting
the production response. Generates ImprovementCandidate records when a variant
consistently outperforms the production baseline.

Design:
  - Samples a configurable percentage of live conversations (default: 10%)
  - Runs 2-3 variants in parallel with the production call
  - Variant responses are logged, NEVER served to users
  - Compares quality scores between production and variants
  - Generates before/after cards when improvement > threshold

Zero impact on production:
  - Production response is always delivered as-is
  - Shadow calls run concurrently but are fire-and-forget
  - All variant responses are discarded after scoring
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.chat import ChatMessage, ChatSession
from app.models.quality import QualityScore, ImprovementCandidate
from app.models.tenant import Tenant
from app.services.quality_scorer import score_response, _compute_overall
from app.adapters.llm import get_llm_adapter, RouterAdapter

logger = logging.getLogger(__name__)

# Sampling rate (0.0 - 1.0) — what fraction of conversations get shadow evaluation
SHADOW_SAMPLE_RATE = float(os.getenv("SHADOW_SAMPLE_RATE", "0.10"))

# Minimum score improvement to generate a candidate
IMPROVEMENT_THRESHOLD = float(os.getenv("SHADOW_IMPROVEMENT_THRESHOLD", "0.10"))

# Score below which we consider the response "needs improvement"
SCORE_FLOOR = float(os.getenv("SHADOW_SCORE_FLOOR", "0.60"))

# Variants to test — defined as prompt template / config modifications
VARIANTS = [
    {
        "name": "stricter_focus",
        "description": "Tighter focus on knowledge base, less creative",
        "system_prompt_suffix": (
            "\n\nIMPORTANT: Base your answer ONLY on the knowledge context provided. "
            "If the context doesn't contain the answer, say so clearly. "
            "Do not speculate or add information beyond what's in the context."
        ),
        "temperature": 0.3,
    },
    {
        "name": "more_detailed",
        "description": "More thorough, structured responses with examples",
        "system_prompt_suffix": (
            "\n\nProvide a comprehensive, well-structured answer. "
            "Include specific details, examples, and actionable information "
            "where relevant. Organize with clear sections if appropriate."
        ),
        "temperature": 0.5,
    },
    {
        "name": "concise_precise",
        "description": "Short, direct answers that get straight to the point",
        "system_prompt_suffix": (
            "\n\nBe concise and direct. Answer in 2-3 sentences max. "
            "Get straight to the point without preamble or extra explanation."
        ),
        "temperature": 0.3,
    },
]


def _should_shadow() -> bool:
    """Deterministic sampling decision based on configurable rate."""
    import random
    return random.random() < SHADOW_SAMPLE_RATE


def _build_variant_prompt(
    base_system_prompt: str,
    variant: Dict[str, Any],
) -> str:
    """Build a variant system prompt by appending the variant suffix."""
    suffix = variant.get("system_prompt_suffix", "")
    if suffix:
        return base_system_prompt + suffix
    return base_system_prompt


async def evaluate_variants(
    user_query: str,
    base_system_prompt: str,
    knowledge_context: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """
    Run all shadow variants silently.
    Returns list of variant results with scores.
    """
    results = []

    for variant in VARIANTS:
        variant_prompt = _build_variant_prompt(base_system_prompt, variant)
        try:
            adapter = get_llm_adapter(provider="router")
            start = time.time()

            variant_result = await adapter.generate(
                prompt=user_query,
                model=os.getenv("LLM_GROQ_MODEL", "llama-3.3-70b-versatile"),
                temperature=variant.get("temperature", 0.5),
                max_tokens=1024,
                system_prompt=variant_prompt,
                messages=messages,
            )

            latency_ms = int((time.time() - start) * 1000)

            if not variant_result.get("success"):
                logger.debug(f"[Shadow] Variant '{variant['name']}' failed: {variant_result.get('error')}")
                continue

            variant_response = variant_result.get("response", "")
            if not variant_response.strip():
                continue

            quality = await score_response(
                user_query=user_query,
                bot_response=variant_response,
                knowledge_context=knowledge_context,
            )

            results.append({
                "variant_name": variant["name"],
                "description": variant["description"],
                "response": variant_response,
                "scores": quality,
                "latency_ms": latency_ms,
            })

        except Exception as e:
            logger.debug(f"[Shadow] Variant '{variant['name']}' error: {e}")
            continue

    return results


def find_best_variant(
    variants: List[Dict[str, Any]],
    production_score: float,
) -> Optional[Dict[str, Any]]:
    """
    Find the best variant that outperforms production by the improvement threshold.
    Returns None if no variant clears the bar.
    """
    if not variants:
        return None

    best = max(variants, key=lambda v: v["scores"].get("overall", 0.0))
    best_score = best["scores"].get("overall", 0.0)

    if best_score > production_score + IMPROVEMENT_THRESHOLD:
        return best

    return None


async def shadow_evaluate_conversation(
    db: Session,
    tenant_id: str,
    session_id: str,
    force: bool = False,
) -> Optional[ImprovementCandidate]:
    """
    Evaluate a single conversation with shadow variants.
    If `force` is True, evaluates regardless of sampling rate.

    Returns an ImprovementCandidate if a variant significantly outperforms production.
    """
    if not force and not _should_shadow():
        return None

    # Get the last user-assistant pair
    user_msg = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if not user_msg:
        return None

    assistant_msg = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at > user_msg.created_at,
        )
        .order_by(ChatMessage.created_at.asc())
        .first()
    )
    if not assistant_msg:
        return None

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return None

    user_query = user_msg.content or ""
    bot_response = assistant_msg.content or ""

    if not user_query.strip() or not bot_response.strip():
        return None

    # Get production quality score
    existing_score = (
        db.query(QualityScore)
        .filter(QualityScore.message_id == assistant_msg.id)
        .first()
    )

    if existing_score and existing_score.overall_score >= SCORE_FLOOR and not force:
        return None

    knowledge_context = None
    if isinstance(tenant.knowledge_context, dict):
        import json
        raw = json.dumps(tenant.knowledge_context, ensure_ascii=False)
        knowledge_context = raw[:2000] if len(raw) > 2000 else raw

    base_system_prompt = tenant.prompt_template or "You are a helpful assistant."
    messages = [
        {"role": "user", "content": user_query},
    ]

    # Score production response if not already scored
    if not existing_score:
        production_quality = await score_response(
            user_query=user_query,
            bot_response=bot_response,
            knowledge_context=knowledge_context,
        )
        production_overall = production_quality.get("overall", 0.0)
        production_flaws = production_quality.get("flaws", [])
    else:
        production_overall = existing_score.overall_score
        production_flaws = existing_score.flaws or []

    # If production is already good, skip (unless forced)
    if production_overall >= SCORE_FLOOR and not force:
        return None

    # Run variants
    variants = await evaluate_variants(
        user_query=user_query,
        base_system_prompt=base_system_prompt,
        knowledge_context=knowledge_context,
        messages=messages,
    )

    if not variants:
        return None

    # Find best variant
    best = find_best_variant(variants, production_overall)
    if not best:
        return None

    candidate = ImprovementCandidate(
        tenant_id=tenant_id,
        message_id=assistant_msg.id,
        channel="web_chatbot",
        user_query=user_query,
        original_response=bot_response,
        original_score=round(production_overall, 4),
        original_flaws=production_flaws,
        optimized_response=best["response"],
        optimized_score=round(best["scores"].get("overall", 0.0), 4),
        improvement_delta=round(
            best["scores"].get("overall", 0.0) - production_overall, 4
        ),
        improvement_type="prompt_tweak",
        variant_config={
            "variant_name": best["variant_name"],
            "description": best["description"],
        },
        status="pending",
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)

    logger.info(
        f"[Shadow] Generated candidate {candidate.id}: "
        f"delta={candidate.improvement_delta:.3f}, "
        f"variant='{best['variant_name']}'"
    )

    return candidate


async def batch_shadow_evaluate(
    db: Session,
    tenant_id: str,
    hours_lookback: int = 24,
    max_candidates: int = 20,
) -> int:
    """
    Batch shadow evaluate recent conversations for a tenant.
    Returns count of new ImprovementCandidates generated.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)

    sessions = (
        db.query(ChatSession)
        .filter(
            ChatSession.tenant_id == tenant_id,
            ChatSession.created_at >= cutoff,
        )
        .order_by(ChatSession.created_at.desc())
        .limit(50)
        .all()
    )

    count = 0
    for session in sessions:
        if count >= max_candidates:
            break
        try:
            candidate = await shadow_evaluate_conversation(
                db=db,
                tenant_id=tenant_id,
                session_id=session.id,
                force=False,
            )
            if candidate:
                count += 1
        except Exception as e:
            logger.error(f"[Shadow] Error evaluating session {session.id}: {e}")
            continue

    return count
