"""
Sentiment Analyzer - Analyze conversation sentiment with auto-escalation.
"""
import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

NEGATIVE_KEYWORDS = {
    "frustrated", "angry", "upset", "disappointed", "terrible", "awful",
    "worst", "hate", "horrible", "bad", "useless", "waste", "stupid",
    "ridiculous", "unacceptable", "complaint", "problem", "issue",
    "not working", "broken", "failed", "refund", "cancel", "never again",
    "poor service", "unhappy", "dissatisfied"
}

POSITIVE_KEYWORDS = {
    "great", "excellent", "amazing", "wonderful", "fantastic", "love",
    "perfect", "awesome", "helpful", "thank", "thanks", "appreciate",
    "happy", "satisfied", "good", "best", "impressed", "brilliant"
}

ESCALATION_KEYWORDS = {
    "speak to manager", "talk to human", "speak to supervisor",
    "complaint", "legal", "lawyer", "court", "sue", "refund",
    "manager", "supervisor", "chargeback", "dispute",
    "not good", "very bad", "terrible service", "worst ever",
}


class SentimentResult:
    """Result of sentiment analysis"""

    def __init__(self, sentiment: str, score: float, keywords: List[str], is_escalation: bool = False):
        self.sentiment = sentiment  # positive, negative, neutral
        self.score = score  # -1 to 1
        self.keywords = keywords
        self.is_escalation = is_escalation
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sentiment": self.sentiment,
            "score": self.score,
            "keywords": self.keywords,
            "is_escalation": self.is_escalation,
            "timestamp": self.timestamp.isoformat()
        }


class SentimentAnalyzer:
    """
    Service for analyzing message sentiment with auto-escalation.

    Usage:
        from app.services.sentiment_analyzer import sentiment_analyzer

        result = sentiment_analyzer.analyze("I'm really frustrated with this service!")
        if result.is_escalation:
            print(f"ESCALATE: {result.keywords}")
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        negative_threshold: float = -0.3,
        consecutive_negative_threshold: int = 2,
    ):
        if enabled is None:
            enabled = os.getenv("SENTIMENT_ANALYSIS_ENABLED", "false").lower() in ("1", "true", "yes")
        self.enabled = enabled
        self.negative_threshold = negative_threshold
        self.consecutive_negative_threshold = consecutive_negative_threshold
        self._tenant_sentiments: Dict[str, List[SentimentResult]] = {}
        logger.info(f"SentimentAnalyzer initialized (enabled={enabled})")

    def enable(self):
        self.enabled = True
        logger.info("Sentiment analysis enabled")

    def disable(self):
        self.enabled = False
        logger.info("Sentiment analysis disabled")

    def analyze(self, text: str) -> SentimentResult:
        """Analyze a single message for sentiment. Returns SentimentResult."""
        if not text:
            return SentimentResult("neutral", 0.0, [], False)

        text_lower = text.lower()

        found_negative = [w for w in NEGATIVE_KEYWORDS if w in text_lower]
        found_positive = [w for w in POSITIVE_KEYWORDS if w in text_lower]
        found_escalation = [w for w in ESCALATION_KEYWORDS if w in text_lower]

        score = 0.0
        if found_positive:
            score = min(1.0, len(found_positive) * 0.2)
        if found_negative:
            score = -min(1.0, len(found_negative) * 0.3)

        if score > 0.2:
            sentiment = "positive"
        elif score < -0.2:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        keywords = found_positive + found_negative
        is_escalation = (
            len(found_escalation) > 0
            or score <= self.negative_threshold
        )

        result = SentimentResult(sentiment, score, keywords, is_escalation)

        if is_escalation:
            logger.warning(
                "[Sentiment] Escalation trigger detected — score=%.2f sentiment=%s keywords=%s",
                score, sentiment, keywords,
            )

        return result

    def analyze_conversation(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze sentiment trend across a message list."""
        if not messages:
            return {"trend": "neutral", "score": 0.0}

        sentiments = []
        for msg in messages:
            content = msg.get("content", "")
            if content:
                result = self.analyze(content)
                sentiments.append(result.score)

        if not sentiments:
            return {"trend": "neutral", "score": 0.0}

        avg_score = sum(sentiments) / len(sentiments)

        if len(sentiments) >= 3:
            recent_avg = sum(sentiments[-3:]) / 3
            if recent_avg < avg_score - 0.2:
                trend = "declining"
            elif recent_avg > avg_score + 0.2:
                trend = "improving"
            else:
                trend = "stable"
        else:
            trend = "stable"

        has_recent_negative = any(s < -0.3 for s in sentiments[-3:])

        return {
            "trend": trend,
            "score": avg_score,
            "has_negative": has_recent_negative,
            "message_count": len(mentiments)
        }

    def store_analysis(self, tenant_id: str, session_id: str, result: SentimentResult):
        """Store per-message sentiment for trend tracking."""
        key = f"{tenant_id}:{session_id}"
        if key not in self._tenant_sentiments:
            self._tenant_sentiments[key] = []
        self._tenant_sentiments[key].append(result)
        if len(self._tenant_sentiments[key]) > 50:
            self._tenant_sentiments[key] = self._tenant_sentiments[key][-50:]

    def should_escalate(self, tenant_id: str, session_id: str) -> bool:
        """Return True if conversation should be escalated to human agent."""
        key = f"{tenant_id}:{session_id}"
        if key not in self._tenant_sentiments:
            return False

        recent = self._tenant_sentiments[key][-5:]
        if not recent:
            return False

        negative_count = sum(1 for r in recent if r.sentiment == "negative")
        if negative_count >= self.consecutive_negative_threshold:
            return True

        if any(r.is_escalation for r in recent):
            return True

        return False

    def get_session_trend(self, tenant_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Return trend analysis for a session."""
        key = f"{tenant_id}:{session_id}"
        if key not in self._tenant_sentiments:
            return None
        msgs = [{"content": ""} for _ in self._tenant_sentiments[key]]
        return self.analyze_conversation(msgs)


# Singleton instance
sentiment_analyzer = SentimentAnalyzer()
