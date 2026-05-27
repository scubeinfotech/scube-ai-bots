"""
Learning Pipeline Orchestrator

Ties together the self-learning ecosystem into a cohesive daily pipeline:
  1. Quality Scorer  — scores unscored responses across 5 dimensions
  2. Pattern Detector — clusters similar failures for admin insight
  3. Shadow Evaluator — tests prompt variants silently, generates candidates
  4. Quality Rollup   — aggregates daily metrics for dashboard charts
  5. Existing Self-Learning — ingests high-confidence Q&A into KB

Each stage runs independently — failure in one doesn't block others.
All stages operate asynchronously with zero impact on production.
"""
import asyncio
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.tenant import Tenant
from app.models.quality import QualityMetric
from app.services.self_learning import run_daily_learning_job
from app.services.quality_scorer import (
    score_recent_messages,
    score_whatsapp_messages,
    run_quality_rollup,
)
from app.services.pattern_detector import PatternDetector
from app.services.shadow_evaluator import batch_shadow_evaluate
from app.services.before_after_generator import get_candidate_summary
from app.services.pipeline_status import mark_running, mark_completed, mark_failed

logger = logging.getLogger(__name__)


async def run_quality_scoring_stage(
    db: Session,
    tenant_id: str,
    hours_lookback: int = 24,
) -> Dict[str, Any]:
    """
    Stage 1: Score all unscored messages (web + WhatsApp) within lookback window.
    Uses LLM-as-judge for scoring, runs async.
    """
    try:
        web_count = await score_recent_messages(
            db=db,
            tenant_id=tenant_id,
            hours_lookback=hours_lookback,
        )
        wa_count = await score_whatsapp_messages(
            db=db,
            tenant_id=tenant_id,
            hours_lookback=hours_lookback,
        )
        total = web_count + wa_count
        logger.info(
            f"[LearningPipeline] Stage 1 (Scoring): "
            f"tenant={tenant_id}, web={web_count}, whatsapp={wa_count}, total={total}"
        )
        return {"status": "completed", "scored": total, "web": web_count, "whatsapp": wa_count}
    except Exception as e:
        logger.error(
            f"[LearningPipeline] Stage 1 (Scoring) failed for "
            f"tenant {tenant_id}: {e}"
        )
        return {"status": "failed", "error": str(e)}


def run_pattern_detection_stage(
    db: Session,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Stage 2: Detect and cluster failure patterns from low-quality responses.
    """
    try:
        detector = PatternDetector()
        patterns = detector.detect_for_tenant(db, tenant_id)
        logger.info(
            f"[LearningPipeline] Stage 2 (Patterns): "
            f"tenant={tenant_id}, patterns={len(patterns)}"
        )
        return {
            "status": "completed",
            "patterns_found": len(patterns),
        }
    except Exception as e:
        logger.error(
            f"[LearningPipeline] Stage 2 (Patterns) failed for "
            f"tenant {tenant_id}: {e}"
        )
        return {"status": "failed", "error": str(e)}


async def run_shadow_evaluation_stage(
    db: Session,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Stage 3: Run shadow evaluation on recent conversations.
    Generates ImprovementCandidate records for admin review.
    """
    try:
        count = await batch_shadow_evaluate(
            db=db,
            tenant_id=tenant_id,
            hours_lookback=24,
            max_candidates=20,
        )
        logger.info(
            f"[LearningPipeline] Stage 3 (Shadow): "
            f"tenant={tenant_id}, candidates={count}"
        )
        return {"status": "completed", "candidates_generated": count}
    except Exception as e:
        logger.error(
            f"[LearningPipeline] Stage 3 (Shadow) failed for "
            f"tenant {tenant_id}: {e}"
        )
        return {"status": "failed", "error": str(e)}


def run_quality_rollup_stage(
    db: Session,
    tenant_id: str,
    metric_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Stage 4: Aggregate daily quality metrics for dashboard charts.
    Rolls up today + yesterday to capture scores across the daily boundary.
    """
    try:
        dates = [date.today()]
        if metric_date is not None:
            dates = [metric_date]
        else:
            dates.append(date.today() - timedelta(days=1))

        metrics = []
        for d in dates:
            metric = run_quality_rollup(db, tenant_id, d)
            metrics.append(metric)
            logger.info(
                f"[LearningPipeline] Stage 4 (Rollup): "
                f"tenant={tenant_id}, date={d}, avg_score={metric.avg_overall_score}"
            )
        return {"status": "completed", "metric_count": len(metrics)}
    except Exception as e:
        logger.error(
            f"[LearningPipeline] Stage 4 (Rollup) failed for "
            f"tenant {tenant_id}: {e}"
        )
        return {"status": "failed", "error": str(e)}


async def run_full_pipeline_for_tenant(
    tenant_id: str,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Run all 4 stages of the learning pipeline for a single tenant.
    Stages run independently — one failure doesn't block others.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        stages = {}

        # Stage 1: Quality Scoring
        stages["scoring"] = await run_quality_scoring_stage(db, tenant_id)

        # Stage 2: Pattern Detection (sync, no DB conflict)
        stages["patterns"] = run_pattern_detection_stage(db, tenant_id)

        # Stage 3: Shadow Evaluation
        stages["shadow"] = await run_shadow_evaluation_stage(db, tenant_id)

        # Stage 4: Quality Rollup
        stages["rollup"] = run_quality_rollup_stage(db, tenant_id)

        summary = get_candidate_summary(db, tenant_id)

        return {
            "tenant_id": tenant_id,
            "stages": stages,
            "summary": summary,
        }
    finally:
        if close_db:
            db.close()


async def run_full_daily_pipeline() -> Dict[str, Any]:
    """
    Entry point for the scheduled daily pipeline.
    Runs all stages across all active tenants, then triggers the
    existing self-learning job.
    """
    logger.info("=== Learning Pipeline: Starting daily run ===")
    mark_running()
    db = SessionLocal()

    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        if not tenants:
            logger.info("[LearningPipeline] No active tenants found")
            mark_completed({"status": "no_tenants"})
            return {"status": "no_tenants"}

        pipeline_results = []
        for tenant in tenants:
            try:
                result = await run_full_pipeline_for_tenant(tenant.id, db)
                pipeline_results.append(result)
            except Exception as e:
                logger.error(
                    f"[LearningPipeline] Pipeline failed for "
                    f"tenant {tenant.id} ({tenant.name}): {e}"
                )
                pipeline_results.append({
                    "tenant_id": tenant.id,
                    "error": str(e),
                })
            finally:
                db.commit()

        logger.info("=== Learning Pipeline: Starting self-learning job ===")
        try:
            learning_stats = run_daily_learning_job()
        except Exception as e:
            logger.error(f"[LearningPipeline] Self-learning job failed: {e}")
            learning_stats = {"error": str(e)}

        total_scored = sum(
            r.get("stages", {}).get("scoring", {}).get("scored", 0)
            for r in pipeline_results
            if "stages" in r
        )
        total_patterns = sum(
            r.get("stages", {}).get("patterns", {}).get("patterns_found", 0)
            for r in pipeline_results
            if "stages" in r
        )
        total_candidates = sum(
            r.get("stages", {}).get("shadow", {}).get("candidates_generated", 0)
            for r in pipeline_results
            if "stages" in r
        )

        result = {
            "status": "completed",
            "tenants_processed": len(pipeline_results),
            "total_scored": total_scored,
            "total_patterns": total_patterns,
            "total_candidates": total_candidates,
            "self_learning": learning_stats,
            "per_tenant": pipeline_results,
        }

        mark_completed(result)

        logger.info(
            f"=== Learning Pipeline: Complete — "
            f"{len(pipeline_results)} tenants, "
            f"{total_scored} scored, "
            f"{total_patterns} patterns, "
            f"{total_candidates} candidates ==="
        )
        return result

    except Exception as e:
        logger.error(f"[LearningPipeline] Fatal pipeline error: {e}")
        mark_failed(str(e))
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()
