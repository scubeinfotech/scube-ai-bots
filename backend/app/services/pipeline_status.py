import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_status = {
    "state": "idle",
    "started_at": None,
    "completed_at": None,
    "message": "",
    "tenants_processed": 0,
    "total_scored": 0,
    "total_patterns": 0,
    "total_candidates": 0,
}


def mark_running():
    _status["state"] = "running"
    _status["started_at"] = time.time()
    _status["completed_at"] = None
    _status["message"] = "Pipeline is running..."
    _status["tenants_processed"] = 0
    _status["total_scored"] = 0
    _status["total_patterns"] = 0
    _status["total_candidates"] = 0
    logger.info("[PipelineStatus] Marked running")


def mark_completed(result: dict):
    _status["state"] = "completed"
    _status["completed_at"] = time.time()
    _status["message"] = "Pipeline completed"
    _status["tenants_processed"] = result.get("tenants_processed", 0)
    _status["total_scored"] = result.get("total_scored", 0)
    _status["total_patterns"] = result.get("total_patterns", 0)
    _status["total_candidates"] = result.get("total_candidates", 0)
    elapsed = _status["completed_at"] - (_status["started_at"] or _status["completed_at"])
    logger.info(f"[PipelineStatus] Completed in {elapsed:.1f}s: {result.get('status')}")


def mark_failed(error: str):
    _status["state"] = "failed"
    _status["completed_at"] = time.time()
    _status["message"] = f"Failed: {error}"
    logger.error(f"[PipelineStatus] Failed: {error}")


def get_status() -> dict:
    elapsed = None
    if _status["started_at"]:
        end = _status["completed_at"] or time.time()
        elapsed = round(end - _status["started_at"], 1)
    return {
        "state": _status["state"],
        "message": _status["message"],
        "started_at": _status["started_at"],
        "completed_at": _status["completed_at"],
        "elapsed_seconds": elapsed,
        "tenants_processed": _status["tenants_processed"],
        "total_scored": _status["total_scored"],
        "total_patterns": _status["total_patterns"],
        "total_candidates": _status["total_candidates"],
    }
