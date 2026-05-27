"""
Background service to analyze conversations and flag unanswered queries
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ChatSession, ChatMessage, Tenant
from app.models.knowledge import UnansweredQuery

logger = logging.getLogger(__name__)


# Patterns that indicate low-confidence or unanswered responses
UNANSWERED_PATTERNS = [
    "I couldn't find any information",
    "haven't asked a specific question",
    "Could you please remind me",
    "Could you please provide more context",
    "I don't have enough information",
    "I'm not sure I understand",
    "Could you clarify",
    "I don't have access to",
]

GENERIC_PATTERNS = [
    "as an ai",
    "i can help",
    "please provide more details",
    "please provide more context",
]

USEFUL_INFO_PATTERNS = [
    r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
    r'\b[\w.-]+@[\w.-]+\.\w+\b',
    r'\b\d+\s+(street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|place|pl)\b',
    r'\b(suite|floor|building|bldg)\s+[a-z0-9]+\b',
    r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
    r'\b(am|pm|hours|open|closed|close)\b',
    r'\$(?:\d+(?:,\d{3})*(?:\.\d{2})?)',
    r'\b\d+(?:\.\d+)?\s*(?:dollars|usd)\b',
    r'\b(appointment|consultation|service|support|help)\b',
    r'\b(website|www\.)[\w.-]+\b',
]

USEFUL_INFO_KEYWORDS = [
    "contact", "phone", "email", "address", "location", "hours", "open", "closed",
    "price", "cost", "fee", "payment", "book", "appointment", "schedule",
    "service", "support", "help", "available", "call", "visit", "email", "website",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "weekday", "weekend", "am", "pm", "dollar", "rupee", "usd", "price",
    "appointment", "consultation", "booking", "reservation",
]

SMALL_TALK_QUERIES = {
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
    "thanks", "thank you", "ok", "okay", "yes", "no", "how are you",
    "how you doing", "how u doing"
}


def _is_small_talk_query(text: str) -> bool:
    query = (text or "").strip().lower()
    if not query:
        return True

    compact = " ".join(query.split())
    if compact in SMALL_TALK_QUERIES:
        return True

    tokens = re.findall(r"[a-z0-9]+", compact)
    if len(tokens) <= 2 and " ".join(tokens) in {"hi", "hello", "hey", "ok", "yes", "no"}:
        return True
    return False


def _contains_useful_info(text: str) -> bool:
    """Check if text contains useful contact/service information."""
    if not text:
        return False
    text_lower = text.lower()
    for pattern in USEFUL_INFO_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    for keyword in USEFUL_INFO_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


def _tokenize(text: str) -> set:
    """Lowercase alphanumeric tokens for simple lexical relevance checks."""
    if not text:
        return set()
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _relevance_score(user_query: str, response_content: str) -> float:
    """
    Lexical overlap between user query and response.
    Returns value in range [0.0, 1.0].
    """
    query_tokens = _tokenize(user_query)
    response_tokens = _tokenize(response_content)

    if not query_tokens or not response_tokens:
        return 0.0

    overlap = len(query_tokens.intersection(response_tokens))
    # Prefer precision on query-side coverage.
    return min(1.0, overlap / max(1, len(query_tokens)))


def calculate_confidence_score(user_query: str, response_content: str) -> float:
    """
    Weighted confidence score (0.0 = lowest, 1.0 = highest).

    Factors:
    - fallback / refusal patterns
    - lexical relevance to user query
    - too many clarification questions
    - length fit and generic filler penalties
    - useful information bonus
    """
    if not response_content:
        return 0.0
  
    content_lower = response_content.lower()

    # Strong fallback signals get immediate low confidence.
    for pattern in UNANSWERED_PATTERNS:
        if pattern.lower() in content_lower:
            return 0.25

    relevance = _relevance_score(user_query, response_content)
    response_len = len(response_content.strip())
    question_marks = response_content.count("?")
    generic_hits = sum(1 for pattern in GENERIC_PATTERNS if pattern in content_lower)

    # Length fitness: avoid over-penalizing concise answers while catching near-empty replies.
    if response_len < 40:
        length_fit = 0.25
    elif response_len <= 260:
        length_fit = 0.9
    elif response_len <= 480:
        length_fit = 0.75
    else:
        length_fit = 0.55

    clarification_penalty = 0.2 if question_marks >= 2 else 0.0
    generic_penalty = min(0.2, generic_hits * 0.07)

    # Useful info bonus - responses with contact/service info are more likely to be valid
    useful_info_bonus = 0.15 if _contains_useful_info(response_content) else 0.0

    score = (0.6 * relevance) + (0.4 * length_fit) - clarification_penalty - generic_penalty + useful_info_bonus
    return max(0.0, min(1.0, round(score, 2)))


def calculate_confidence_with_feedback(user_query: str, response_content: str, feedback_score: int = None) -> float:
    """
    Confidence score adjusted with explicit user feedback when available.
    """
    base_score = calculate_confidence_score(user_query, response_content)
    if feedback_score == -1:
        return max(0.0, round(base_score - 0.35, 2))
    if feedback_score == 1:
        return min(1.0, round(base_score + 0.1, 2))
    return base_score


def detect_unanswered_reason(user_query: str, response_content: str) -> str:
    """
    Detect the reason why a query was flagged as unanswered
    """
    if not response_content:
        return "Empty response"
    
    content_lower = response_content.lower()
    
    for pattern in UNANSWERED_PATTERNS:
        if pattern.lower() in content_lower:
            if "couldn't find" in content_lower:
                return "Information not found in knowledge base"
            elif "haven't asked" in content_lower:
                return "No specific question detected"
            elif "remind me" in content_lower or "clarify" in content_lower or "provide more context" in content_lower:
                return "Insufficient context or clarity"
            elif "don't have access" in content_lower:
                return "Data not available"
            else:
                return "Low confidence response"

    relevance = _relevance_score(user_query, response_content)
    if relevance < 0.2:
        return "Low relevance to user question"

    if response_content.count("?") >= 2:
        return "Excessive clarification questions"

    if len(response_content.strip()) < 50:
        return "Very short response"

    return "Low confidence detected"


def detect_unanswered_reason_with_feedback(user_query: str, response_content: str, feedback_score: int = None) -> str:
    """Return explicit feedback reason first when present, otherwise fallback to content analysis."""
    if feedback_score == -1:
        return "Negative user feedback"
    return detect_unanswered_reason(user_query, response_content)


async def scan_and_populate_unanswered_queries(
    days_lookback: int = 7,
    confidence_threshold: float = 0.5,
    db: Session = None
) -> Dict[str, int]:
    """
    Scan recent conversations and populate UnansweredQuery table for low-confidence responses.
    
    Args:
        days_lookback: Number of days to look back for conversations
        confidence_threshold: Responses below this score are flagged (0.0-1.0)
        db: Database session (optional, will create if not provided)
    
    Returns:
        Dictionary with statistics: processed, flagged, skipped, errors
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    
    try:
        stats = {
            "processed": 0,
            "flagged": 0,
            "skipped": 0,
            "errors": 0
        }
        
        # Get cutoff date
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_lookback)
        
        logger.info(f"Starting unanswered query scan (lookback: {days_lookback} days, threshold: {confidence_threshold})")
        
        # Get all active tenants
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        
        for tenant in tenants:
            try:
                # Get recent sessions for this tenant
                sessions = db.query(ChatSession).filter(
                    and_(
                        ChatSession.tenant_id == tenant.id,
                        ChatSession.created_at >= cutoff_date
                    )
                ).order_by(desc(ChatSession.created_at)).all()
                
                for session in sessions:
                    try:
                        # Get all messages in this session
                        messages = db.query(ChatMessage).filter(
                            ChatMessage.session_id == session.id
                        ).order_by(ChatMessage.created_at).all()
                        
                        # Process message pairs (user query + assistant response)
                        for i in range(len(messages) - 1):
                            current_msg = messages[i]
                            next_msg = messages[i + 1]
                            
                            # Look for user query followed by assistant response
                            if current_msg.role == "user" and next_msg.role == "assistant":
                                stats["processed"] += 1

                                if _is_small_talk_query(current_msg.content or ""):
                                    stats["skipped"] += 1
                                    continue
                                
                                # Calculate confidence score
                                confidence = calculate_confidence_with_feedback(
                                    current_msg.content or "",
                                    next_msg.content or "",
                                    next_msg.feedback_score
                                )
                                
                                # Flag if below threshold
                                if confidence < confidence_threshold:
                                    # Check if already exists
                                    existing = db.query(UnansweredQuery).filter(
                                        and_(
                                            UnansweredQuery.session_id == session.id,
                                            UnansweredQuery.query == current_msg.content
                                        )
                                    ).first()
                                    
                                    if existing:
                                        stats["skipped"] += 1
                                        continue
                                    
                                    # Create new unanswered query record
                                    reason = detect_unanswered_reason_with_feedback(
                                        current_msg.content or "",
                                        next_msg.content or "",
                                        next_msg.feedback_score
                                    )
                                    
                                    unanswered_query = UnansweredQuery(
                                        tenant_id=tenant.id,
                                        session_id=session.id,
                                        query=current_msg.content or "",
                                        response=next_msg.content or "",
                                        confidence_score=confidence,
                                        reason=reason,
                                        is_resolved=False,
                                        is_used_for_training=False
                                    )
                                    
                                    db.add(unanswered_query)
                                    stats["flagged"] += 1
                                    
                                    logger.debug(
                                        f"Flagged query for {tenant.name}: '{current_msg.content[:50]}...' "
                                        f"(confidence: {confidence:.2f}, reason: {reason})"
                                    )
                    
                    except Exception as e:
                        logger.error(f"Error processing session {session.id}: {str(e)}")
                        stats["errors"] += 1
                        continue
            
            except Exception as e:
                logger.error(f"Error processing tenant {tenant.name}: {str(e)}")
                stats["errors"] += 1
                continue
        
        # Commit all changes
        db.commit()
        
        logger.info(
            f"Unanswered query scan complete: "
            f"{stats['processed']} processed, {stats['flagged']} flagged, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )
        
        return stats
    
    except Exception as e:
        logger.error(f"Critical error in scan_and_populate_unanswered_queries: {str(e)}")
        db.rollback()
        raise
    
    finally:
        if close_db:
            db.close()


def run_background_scan():
    """
    Entry point for the scheduled background job.
    Scans last 7 days, flags responses below 0.7 confidence.
    
    Note: BackgroundScheduler runs in a separate thread, so we use 
    synchronous database operations here.
    """
    try:
        logger.info("=== Starting scheduled unanswered query scan ===")
        
        db = SessionLocal()
        try:
            stats = {
                "processed": 0,
                "flagged": 0,
                "skipped": 0,
                "errors": 0
            }
            
            # Get cutoff date
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
            confidence_threshold = 0.5
            
            logger.info(f"Scanning conversations from last 7 days (threshold: {confidence_threshold})")
            
            # Get all active tenants
            tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
            
            for tenant in tenants:
                try:
                    # Get recent sessions for this tenant
                    sessions = db.query(ChatSession).filter(
                        and_(
                            ChatSession.tenant_id == tenant.id,
                            ChatSession.created_at >= cutoff_date
                        )
                    ).order_by(desc(ChatSession.created_at)).all()
                    
                    for session in sessions:
                        try:
                            # Get all messages in this session
                            messages = db.query(ChatMessage).filter(
                                ChatMessage.session_id == session.id
                            ).order_by(ChatMessage.created_at).all()
                            
                            # Process message pairs (user query + assistant response)
                            for i in range(len(messages) - 1):
                                current_msg = messages[i]
                                next_msg = messages[i + 1]
                                
                                # Look for user query followed by assistant response
                                if current_msg.role == "user" and next_msg.role == "assistant":
                                    stats["processed"] += 1

                                    if _is_small_talk_query(current_msg.content or ""):
                                        stats["skipped"] += 1
                                        continue
                                    
                                    # Calculate confidence score
                                    confidence = calculate_confidence_with_feedback(
                                        current_msg.content or "",
                                        next_msg.content or "",
                                        next_msg.feedback_score
                                    )
                                    
                                    # Flag if below threshold
                                    if confidence < confidence_threshold:
                                        # Check if already exists
                                        existing = db.query(UnansweredQuery).filter(
                                            and_(
                                                UnansweredQuery.session_id == session.id,
                                                UnansweredQuery.query == current_msg.content
                                            )
                                        ).first()
                                        
                                        if existing:
                                            stats["skipped"] += 1
                                            continue
                                        
                                        # Create new unanswered query record
                                        reason = detect_unanswered_reason_with_feedback(
                                            current_msg.content or "",
                                            next_msg.content or "",
                                            next_msg.feedback_score
                                        )
                                        
                                        unanswered_query = UnansweredQuery(
                                            tenant_id=tenant.id,
                                            session_id=session.id,
                                            query=current_msg.content or "",
                                            response=next_msg.content or "",
                                            confidence_score=confidence,
                                            reason=reason,
                                            is_resolved=False,
                                            is_used_for_training=False
                                        )
                                        
                                        db.add(unanswered_query)
                                        stats["flagged"] += 1
                                        
                                        logger.debug(
                                            f"Flagged query for {tenant.name}: '{current_msg.content[:50]}...' "
                                            f"(confidence: {confidence:.2f}, reason: {reason})"
                                        )
                        
                        except Exception as e:
                            logger.error(f"Error processing session {session.id}: {str(e)}")
                            stats["errors"] += 1
                            continue
                
                except Exception as e:
                    logger.error(f"Error processing tenant {tenant.name}: {str(e)}")
                    stats["errors"] += 1
                    continue
            
            # Commit all changes
            db.commit()
            
            logger.info(
                f"=== Scheduled scan completed: "
                f"{stats['processed']} processed, {stats['flagged']} flagged, "
                f"{stats['skipped']} skipped, {stats['errors']} errors ==="
            )
            
        finally:
            db.close()
        
    except Exception as e:
        logger.error(f"Background scan failed: {str(e)}", exc_info=True)
