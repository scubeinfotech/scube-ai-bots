"""
Response formatter service - formats LLM responses for WhatsApp
Keeps replies concise, transactional, and optimized for mobile platforms
"""
import logging
import re
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ResponseFormatter:
    """Formats long-form LLM responses for WhatsApp's constraints"""
    
    # WhatsApp text message limits
    MAX_MESSAGE_LENGTH = 4096  # WhatsApp's technical limit
    SHORT_RESPONSE_TARGET = 300  # Target for short-form replies
    MEDIUM_RESPONSE_TARGET = 800  # Target for medium-form replies
    
    # Sentence terminator patterns
    SENTENCE_TERMINATORS = {'.', '!', '?'}
    
    # Abbreviations to avoid splitting on periods
    ABBREVIATIONS = {
        'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr',
        'inc', 'ltd', 'corp', 'co', 'etc', 'i.e', 'e.g',
        'am', 'pm', 'usa', 'uk'
    }
    
    def __init__(self, target_length: int = SHORT_RESPONSE_TARGET):
        """
        Initialize response formatter
        
        Args:
            target_length: Target length for formatted response (chars)
        """
        self.target_length = target_length
    
    def format_for_whatsapp(
        self,
        response: str,
        include_metadata: bool = False
    ) -> Dict[str, Any]:
        """
        Format LLM response for WhatsApp
        
        Args:
            response: Original LLM response
            include_metadata: Whether to include formatting metadata
            
        Returns:
            Dict with formatted text and metadata
        """
        if not response:
            return {"formatted_text": "", "truncated": False, "original_length": 0}
        
        original_length = len(response)
        formatted = self._clean_text(response)
        
        # Check if response exceeds target
        if len(formatted) <= self.target_length:
            result = {
                "formatted_text": formatted,
                "truncated": False,
                "original_length": original_length,
                "formatted_length": len(formatted)
            }
        else:
            # Truncate to target length while preserving structure
            formatted, was_truncated = self._truncate_intelligently(
                formatted,
                self.target_length
            )
            result = {
                "formatted_text": formatted,
                "truncated": was_truncated,
                "original_length": original_length,
                "formatted_length": len(formatted)
            }
        
        if include_metadata:
            result["formatting_applied"] = self._get_formatting_log(response, formatted)
        
        logger.debug(f"[ResponseFormatter] Formatted response: {result.get('formatted_length')} chars, "
                    f"truncated={result.get('truncated')}")
        
        return result
    
    def format_transaction_response(
        self,
        action: str,
        status: str,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format transaction/booking response for WhatsApp
        
        Args:
            action: Action type (e.g., "booking_confirmation")
            status: Status (e.g., "success", "pending")
            details: Additional details to include
            
        Returns:
            Formatted transaction response
        """
        templates = {
            "booking_confirmation": {
                "success": "✅ Booking Confirmed!\n\n{details}",
                "pending": "⏳ Booking Request Received\n\n{details}",
                "failed": "❌ Booking Failed\n\n{details}"
            },
            "quote_request": {
                "success": "📋 Quote Generated\n\n{details}",
                "pending": "⏳ Processing Your Quote\n\n{details}",
                "failed": "❌ Unable to Generate Quote\n\n{details}"
            },
            "support_ticket": {
                "success": "🎫 Ticket #12345 Created\n\n{details}",
                "pending": "⏳ Creating Support Ticket\n\n{details}",
                "failed": "❌ Unable to Create Ticket\n\n{details}"
            }
        }
        
        template = templates.get(action, {}).get(status, "")
        if not template:
            return f"{action.replace('_', ' ').title()}: {status}"
        
        # Format details section
        details_text = ""
        if details:
            details_lines = [f"• {k.replace('_', ' ').title()}: {v}" 
                           for k, v in details.items()]
            details_text = "\n".join(details_lines)
        
        return template.format(details=details_text)
    
    def create_interactive_buttons(
        self,
        title: str,
        buttons: list,
        footer_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create interactive button structure for WhatsApp
        
        Args:
            title: Button section title
            buttons: List of button definitions [{"text": "...", "id": "..."}, ...]
            footer_text: Optional footer text
            
        Returns:
            Interactive button payload
        """
        # Validate button count (WhatsApp limit is 3)
        if len(buttons) > 3:
            logger.warning(f"Truncating buttons from {len(buttons)} to 3 (WhatsApp limit)")
            buttons = buttons[:3]
        
        payload = {
            "type": "button",
            "body": {
                "text": title
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn.get("id", f"btn_{i}"),
                            "title": self._truncate_text(btn.get("text", ""), 20)
                        }
                    }
                    for i, btn in enumerate(buttons)
                ]
            }
        }
        
        if footer_text:
            payload["footer"] = {
                "text": self._truncate_text(footer_text, 60)
            }
        
        return payload
    
    def create_list_message(
        self,
        title: str,
        sections: list,
        footer_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create list message structure for WhatsApp
        
        Args:
            title: Message title
            sections: List of sections [{"title": "...", "rows": [...]}, ...]
            footer_text: Optional footer text
            
        Returns:
            List message payload
        """
        payload = {
            "type": "list",
            "body": {
                "text": title
            },
            "action": {
                "button": "Menu",
                "sections": []
            }
        }
        
        # Add sections with row count limit
        for section in sections:
            section_obj = {
                "title": section.get("title", ""),
                "rows": []
            }
            
            # WhatsApp limit: 10 rows per section
            rows = section.get("rows", [])[:10]
            for row in rows:
                section_obj["rows"].append({
                    "id": row.get("id", ""),
                    "title": self._truncate_text(row.get("title", ""), 28),
                    "description": self._truncate_text(
                        row.get("description", ""),
                        72
                    )
                })
            
            payload["action"]["sections"].append(section_obj)
        
        if footer_text:
            payload["footer"] = {
                "text": self._truncate_text(footer_text, 60)
            }
        
        return payload
    
    def _clean_text(self, text: str) -> str:
        """Clean text for WhatsApp"""
        if not text:
            return ""
        
        # Remove multiple consecutive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove HTML tags if present
        text = re.sub(r'<[^>]+>', '', text)
        
        # Remove markdown-style formatting (preserve structure)
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Bold
        text = re.sub(r'__(.*?)__', r'\1', text)      # Underline
        text = re.sub(r'\*(.*?)\*', r'\1', text)      # Italic
        
        # Remove code blocks, keep content
        text = re.sub(r'```.*?\n(.*?)```', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'`(.*?)`', r'\1', text)
        
        # Clean up extra spaces
        text = re.sub(r'  +', ' ', text)
        text = text.strip()
        
        return text
    
    def _truncate_intelligently(
        self,
        text: str,
        max_length: int
    ) -> tuple:
        """
        Truncate text intelligently (by sentence, not mid-word)
        
        Returns:
            (truncated_text, was_truncated)
        """
        if len(text) <= max_length:
            return text, False
        
        # Try to end at sentence boundary
        truncated = text[:max_length]
        
        # Find last sentence terminator
        for terminator in self.SENTENCE_TERMINATORS:
            last_pos = truncated.rfind(terminator)
            if last_pos > max_length * 0.7:  # At least 70% of target
                truncated = text[:last_pos + 1]
                break
        else:
            # No sentence terminator found, try word boundary
            last_space = truncated.rfind(' ')
            if last_space > max_length * 0.7:
                truncated = text[:last_space]
        
        # Add ellipsis indicator
        if len(truncated) < len(text):
            truncated = truncated.rstrip() + "..."
        
        return truncated, True
    
    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate single line of text"""
        if len(text) <= max_length:
            return text
        
        return text[:max_length - 3] + "..."
    
    def _get_formatting_log(self, original: str, formatted: str) -> Dict[str, Any]:
        """Get log of formatting operations applied"""
        return {
            "original_length": len(original),
            "formatted_length": len(formatted),
            "reduction_percent": int((1 - len(formatted) / max(len(original), 1)) * 100),
            "cleaned": "markdown_removed" in str(original) or "<" in original,
            "truncated": len(formatted) < len(original)
        }
