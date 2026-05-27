"""
WhatsApp service - business logic for WhatsApp integration
Handles incoming messages, LLM forwarding, formatting, and response delivery
"""
import logging
import asyncio
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.whatsapp import (
    WhatsAppContact, WhatsAppMessage, WhatsAppSession, 
    WhatsAppConfiguration, WhatsAppMetrics, WhatsAppTentativeBooking,
    ContactActivity
)
from app.models import ChatSession, Tenant
from app.services.chat_service import ChatService
from app.services.response_formatter import ResponseFormatter
from app.services.intent_middleware import (
    IntentDetectionMiddleware,
    BOOKING_INTENT,
    BOOKING_LOOKUP_INTENT,
    CALLBACK_INTENT,
    DEMO_SCHEDULING_INTENT,
)
from app.adapters.whatsapp import WhatsAppProvider, get_whatsapp_provider
from app.config import settings
from app.services.booking_conversation import BookingConversationManager
from app.services.analytics_logger import (
    log_analytics_event,
    INTENT_DETECTED,
    BOOKING_CREATED,
)
from app.services.followup_scheduler import schedule_follow_up

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Service for managing WhatsApp integration"""
    
    def __init__(
        self,
        db: Session,
        llm_provider: Optional[str] = None
    ):
        """
        Initialize WhatsApp service
        
        Args:
            db: Database session
            llm_provider: LLM provider type (defaults to settings.llm_provider)
        """
        self.db = db
        self.chat_service = ChatService(db, llm_provider or settings.llm_provider)
        self.response_formatter = ResponseFormatter()
        self.intent_middleware = IntentDetectionMiddleware()
        self.booking_conversation = BookingConversationManager()
    
    def _normalize_webhook_messages(
        self,
        webhook_payload: Dict[str, Any]
    ) -> list:
        """Extract and normalize message list from Meta or MSG91 webhook formats."""
        # Format 1: Meta Cloud API
        # {object, entry: [{changes: [{value: {messages: [{from, id, text: {body}}]}}]}]}
        try:
            entry = webhook_payload.get("entry", [])
            if entry:
                changes = entry[0].get("changes", [])
                if changes:
                    messages = changes[0].get("value", {}).get("messages", [])
                    if messages:
                        return messages
        except Exception:
            pass

        # Format 2: MSG91 inbound webhook
        # {customerNumber, integratedNumber, text, content, eventName, ...}
        if webhook_payload.get("customerNumber") or webhook_payload.get("eventName") == "message.received":
            ts = webhook_payload.get("ts") or webhook_payload.get("requestedAt", "")
            return [{
                "from": webhook_payload.get("customerNumber", ""),
                "id": webhook_payload.get("uuid") or webhook_payload.get("crqid") or webhook_payload.get("requestId", ""),
                "timestamp": ts,
                "type": "text",
                "text": {
                    "body": webhook_payload.get("text") or webhook_payload.get("content", "")
                }
            }]

        # Format 3: MSG91 may send array under "messages" key directly
        if "messages" in webhook_payload and isinstance(webhook_payload["messages"], list):
            return webhook_payload["messages"]

        return []

    def _extract_profile_name(
        self,
        webhook_payload: Dict[str, Any]
    ) -> Optional[str]:
        """Extract user's WhatsApp profile name from webhook payload."""
        try:
            # Meta Cloud API format: entry[0].changes[0].value.contacts[0].profile.name
            entry = webhook_payload.get("entry", [])
            if entry:
                changes = entry[0].get("changes", [])
                if changes:
                    contacts = changes[0].get("value", {}).get("contacts", [])
                    if contacts:
                        profile = contacts[0].get("profile", {})
                        return profile.get("name")
        except Exception:
            pass
        return None

    async def process_incoming_webhook(
        self,
        tenant_id: str,
        webhook_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process incoming WhatsApp webhook message
        
        Args:
            tenant_id: Tenant ID
            webhook_payload: Raw webhook payload from WhatsApp
            
        Returns:
            Processing result
        """
        try:
            messages = self._normalize_webhook_messages(webhook_payload)
            if not messages:
                return {"success": False, "error": "No messages in webhook"}
            
            results = []
            for msg_payload in messages:
                result = await self._process_single_message(tenant_id, msg_payload)
                results.append(result)
            
            return {
                "success": True,
                "messages_processed": len(results),
                "results": results
            }
        
        except Exception as e:
            logger.exception(f"[WhatsApp] Webhook processing failed: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def _process_single_message(
        self,
        tenant_id: str,
        message_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single incoming WhatsApp message
        
        Args:
            tenant_id: Tenant ID
            message_payload: WhatsApp message payload
            
        Returns:
            Processing result
        """
        try:
            # Verify tenant exists
            tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if not tenant:
                return {"success": False, "error": f"Tenant {tenant_id} not found"}
            
            # Extract message details
            from_number = message_payload.get("from")
            message_id = message_payload.get("id")
            raw_ts = message_payload.get("timestamp", 0)
            try:
                timestamp = int(raw_ts)
            except (ValueError, TypeError):
                timestamp = 0
            
            # Get message content (support multiple types)
            message_text = self._extract_message_text(message_payload)
            message_type = message_payload.get("type", "text")
            
            if not message_text:
                return {"success": False, "error": "No message content"}

            # Dedup check: skip if this Message ID was already processed
            if message_id:
                existing = self.db.query(WhatsAppMessage).filter(
                    WhatsAppMessage.whatsapp_message_id == message_id
                ).first()
                if existing:
                    logger.warning(
                        f"[WhatsApp] Duplicate webhook ignored. "
                        f"Message {message_id[:30]}... already processed "
                        f"(contact={from_number})"
                    )
                    return {
                        "success": True,
                        "duplicate": True,
                        "message_id": existing.id,
                        "whatsapp_message_id": message_id,
                    }

            # Get or create contact - capture WhatsApp profile name if available
            profile_name = self._extract_profile_name(message_payload)
            contact = self._get_or_create_contact(tenant_id, from_number, profile_name)
            
            # Store incoming message
            wa_msg = WhatsAppMessage(
                tenant_id=tenant_id,
                contact_id=contact.id,
                whatsapp_message_id=message_id,
                direction="inbound",
                message_type=message_type,
                content=message_text,
                msg_metadata=message_payload,
                delivery_status="received"
            )
            self.db.add(wa_msg)
            self.db.commit()
            
            # Log activity timeline entry
            self.db.add(ContactActivity(
                tenant_id=tenant_id,
                contact_id=contact.id,
                activity_type="message_in",
                description=message_text[:200],
                ref_type="whatsapp_message",
                ref_id=wa_msg.id,
            ))
            self.db.commit()

            # AI auto-enrichment on 3rd message (fire-and-forget)
            if contact.total_messages == 3 and not contact.company:
                asyncio.ensure_future(self._enrich_contact_from_history(tenant_id, contact))

            # Personalized welcome for first-time contacts (instant response, no LLM latency)
            if contact.total_messages == 1 and contact.contact_name:
                welcome_msg = self._generate_welcome_message(contact.contact_name, tenant)
                if welcome_msg:
                    # Send welcome immediately
                    bf_config = self.db.query(WhatsAppConfiguration).filter(
                        WhatsAppConfiguration.tenant_id == tenant_id
                    ).first()
                    if bf_config and bf_config.is_active:
                        asyncio.ensure_future(
                            self._send_whatsapp_message(
                                wa_config=bf_config,
                                recipient_phone=contact.phone_number,
                                message_text=welcome_msg
                            )
                        )
                        # Store outgoing welcome message
                        outgoing = WhatsAppMessage(
                            tenant_id=tenant_id,
                            contact_id=contact.id,
                            direction="outbound",
                            message_type="text",
                            content=welcome_msg,
                            delivery_status="sent",
                        )
                        self.db.add(outgoing)
                        self.db.commit()
            
            # Get or create WhatsApp session
            wa_session = self._get_or_create_whatsapp_session(
                tenant_id, contact.id
            )

            # Step 2: Detect intent and persist tentative bookings when relevant.
            intent_result = self.intent_middleware.analyze(message_text)
            self._apply_intent_to_session(wa_session, intent_result)
            log_analytics_event(
                self.db,
                tenant_id=tenant_id,
                event_type=INTENT_DETECTED,
                intent=intent_result.get("intent"),
                confidence_score=intent_result.get("confidence"),
                session_id=wa_session.id,
                contact_id=contact.id,
            )

            # Check if contact already has upcoming bookings
            existing_reply = self._handle_existing_bookings(intent_result, contact.id, tenant_id)
            if existing_reply:
                tentative_booking = None
                booking_reply = existing_reply
                self.db.commit()
            else:
                tentative_booking = self._create_tentative_booking_if_needed(
                    tenant_id=tenant_id,
                    contact_id=contact.id,
                    wa_session_id=wa_session.id,
                    wa_message_id=wa_msg.id,
                    message_text=message_text,
                    intent_result=intent_result,
                )

                # Step 3: Multi-step conversation flow – ask follow-up questions
                # when booking fields are missing, or collect confirmations.
                # WhatsApp: Phone already known via contact, pass it for closure message.
                # Pass tenant_id for calendar validation (working hours, conflicts).
                booking_reply = self.booking_conversation.handle(
                    message_text=message_text,
                    session=wa_session,
                    intent_result=intent_result,
                    contact_phone=contact.phone_number,
                    tenant_id=tenant_id,
                )
                self.db.commit()

                # Sync conversation-collected fields back to the booking record on
                # every turn so tentative bookings show date/time in the CRM leads table,
                # even before the user confirms.  When the intent is not "booking" the
                # tentative_booking ref is None — find the existing booking by session.
                booking = tentative_booking
                if not booking:
                    booking = db.query(WhatsAppTentativeBooking).filter(
                        WhatsAppTentativeBooking.whatsapp_session_id == wa_session.id,
                        WhatsAppTentativeBooking.status.in_(["tentative", "confirmed"]),
                    ).first()
                if booking:
                    bd = wa_session.booking_data or {}
                    raw_date = bd.get("date")
                    if raw_date:
                        normalized = self.booking_conversation._normalize_date(raw_date)
                        if normalized:
                            booking.requested_date = normalized
                    raw_time = bd.get("time")
                    if raw_time:
                        normalized = self.booking_conversation._normalize_time(raw_time)
                        if normalized:
                            booking.requested_time = normalized
                    if bd.get("persons"):
                        booking.requested_persons = bd["persons"]
                    if bd.get("type"):
                        booking.requested_type = bd["type"]
                    ef = dict(booking.extracted_fields or {})
                    if booking.requested_date:
                        ef["date"] = booking.requested_date
                    if booking.requested_time:
                        ef["time"] = booking.requested_time
                    if booking.requested_persons:
                        ef["persons"] = booking.requested_persons
                    if booking.requested_type:
                        ef["type"] = booking.requested_type
                    booking.extracted_fields = ef
                    tentative_booking = booking
                    self.db.commit()

                    # Append .ics download link to the confirmation reply
                    if booking_reply and self.booking_conversation.is_completed(wa_session):
                        api_base = (os.getenv("API_BASE_URL") or "").strip().rstrip("/") or "http://localhost:8001"
                        ics_url = f"{api_base}/api/ics/{booking.id}.ics"
                        booking_reply += f"\n\n📅 Add to calendar: {ics_url}"

            if tentative_booking:
                log_analytics_event(
                    self.db,
                    tenant_id=tenant_id,
                    event_type=BOOKING_CREATED,
                    intent=intent_result.get("intent"),
                    session_id=wa_session.id,
                    contact_id=contact.id,
                    booking_id=tentative_booking.id,
                )
                # Schedule CRM follow-up for lead_created
                asyncio.ensure_future(
                    self._schedule_follow_up_async(
                        tenant_id, contact.id, "lead_created", tentative_booking
                    )
                )
                # Email notification to tenant (if enabled)
                asyncio.ensure_future(
                    self._notify_tenant_of_booking(
                        tenant_id, contact, tentative_booking
                    )
                )
            if booking_reply:
                # Bot handles this turn; bypass LLM and reply directly.
                logger.info(f"[WhatsApp] Booking flow reply to {contact.phone_number}: {booking_reply[:60]}")
                # Actually send the reply via WhatsApp (not just return it in HTTP response)
                bf_config = self.db.query(WhatsAppConfiguration).filter(
                    WhatsAppConfiguration.tenant_id == tenant_id
                ).first()
                if bf_config and bf_config.is_active:
                    send_result = await self._send_whatsapp_message(
                        wa_config=bf_config,
                        recipient_phone=contact.phone_number,
                        message_text=booking_reply
                    )
                    if send_result.get("success"):
                        outgoing = WhatsAppMessage(
                            tenant_id=tenant_id,
                            contact_id=contact.id,
                            whatsapp_message_id=send_result.get("message_id"),
                            direction="outbound",
                            message_type="text",
                            content=booking_reply,
                            delivery_status="sent",
                        )
                        self.db.add(outgoing)
                        self.db.commit()
                        wa_session.last_ai_message_at = datetime.utcnow()
                        self.db.commit()
                return {
                    "success": True,
                    "message_id": wa_msg.id,
                    "whatsapp_message_id": message_id,
                    "queued": False,
                    "intent": intent_result.get("intent"),
                    "intent_fields": intent_result.get("fields", {}),
                    "tentative_booking_id": tentative_booking.id if tentative_booking else None,
                    "booking_flow_reply": booking_reply,
                }

            # Step 4: Response controls — cooldown, rate limit, conversation stage
            wa_config = self.db.query(WhatsAppConfiguration).filter(
                WhatsAppConfiguration.tenant_id == tenant_id
            ).first()

            stage = self._get_conversation_stage(wa_session, message_text, intent_result.get("intent", ""))
            meta = wa_session.session_metadata or {}
            meta["stage"] = stage
            wa_session.session_metadata = meta
            self.db.commit()

            cooldown = self._check_cooldown(contact.id, wa_config) if wa_config else None
            rate = self._check_rate_limit(contact.id, wa_config) if wa_config else None
            if cooldown or rate:
                logger.warning(f"[WhatsApp] Throttled for {contact.phone_number}: cooldown={cooldown}, rate={rate}")
                return {
                    "success": True,
                    "message_id": wa_msg.id,
                    "whatsapp_message_id": message_id,
                    "queued": True,
                    "intent": intent_result.get("intent"),
                    "skip_reason": cooldown or rate,
                }

            # Process message through LLM synchronously
            llm_result = await self._process_message_to_llm(
                tenant_id=tenant_id,
                contact_id=contact.id,
                wa_session_id=wa_session.id,
                wa_message_id=wa_msg.id,
                message_text=message_text,
                wa_config=wa_config,
                conversation_stage=stage,
            )
            
            return {
                "success": llm_result.get("success", False),
                "message_id": wa_msg.id,
                "whatsapp_message_id": message_id,
                "queued": False,
                "intent": intent_result.get("intent"),
                "intent_fields": intent_result.get("fields", {}),
                "tentative_booking_id": tentative_booking.id if tentative_booking else None,
            }
        
        except Exception as e:
            logger.exception(f"[WhatsApp] Message processing failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def _apply_intent_to_session(
        self,
        wa_session: WhatsAppSession,
        intent_result: Dict[str, Any],
    ) -> None:
        """Persist lightweight intent context on the active WhatsApp session."""
        wa_session.current_intent = intent_result.get("intent")

        extracted_fields = intent_result.get("fields", {})
        if extracted_fields:
            existing_data = wa_session.booking_data or {}
            wa_session.booking_data = {
                **existing_data,
                **extracted_fields,
            }

    def _create_tentative_booking_if_needed(
        self,
        tenant_id: str,
        contact_id: str,
        wa_session_id: str,
        wa_message_id: str,
        message_text: str,
        intent_result: Dict[str, Any],
    ) -> Optional[WhatsAppTentativeBooking]:
        """Create tentative booking records for booking/callback/demo intents.
        Only creates one booking per session — reuses existing if already created.
        """
        supported_intents = {
            BOOKING_INTENT,
            CALLBACK_INTENT,
            DEMO_SCHEDULING_INTENT,
        }
        detected_intent = intent_result.get("intent")
        if detected_intent not in supported_intents:
            return None

        # Reuse existing booking for this session to avoid duplicate rows with NULL dates
        existing = self.db.query(WhatsAppTentativeBooking).filter(
            WhatsAppTentativeBooking.whatsapp_session_id == wa_session_id,
            WhatsAppTentativeBooking.status.in_(["tentative", "confirmed"]),
        ).first()
        if existing:
            return existing

        extracted_fields = intent_result.get("fields", {})

        # Normalize relative date/time strings to absolute values
        bcm = self.booking_conversation
        raw_date = extracted_fields.get("date")
        if raw_date:
            normalized = bcm._normalize_date(raw_date)
            if normalized:
                extracted_fields["date"] = normalized
        raw_time = extracted_fields.get("time")
        if raw_time:
            normalized = bcm._normalize_time(raw_time)
            if normalized:
                extracted_fields["time"] = normalized

        tentative_booking = WhatsAppTentativeBooking(
            tenant_id=tenant_id,
            contact_id=contact_id,
            whatsapp_session_id=wa_session_id,
            source_message_id=wa_message_id,
            intent_type=detected_intent,
            requested_date=extracted_fields.get("date"),
            requested_time=extracted_fields.get("time"),
            requested_persons=extracted_fields.get("persons"),
            requested_type=extracted_fields.get("type"),
            raw_text=message_text,
            extracted_fields=extracted_fields,
        )
        self.db.add(tentative_booking)
        return tentative_booking

    def _handle_existing_bookings(self, intent_result: dict, contact_id: str, tenant_id: str) -> Optional[str]:
        """Check for existing upcoming bookings and return a formatted reply.
        Returns a reply string if user has bookings (or booking_lookup with none),
        or None to proceed with normal booking flow.

        If an existing booking is incomplete (missing time), it is auto-cancelled
        so the user can create a replacement with full details.
        """
        intent = intent_result.get("intent")
        if intent not in (BOOKING_INTENT, BOOKING_LOOKUP_INTENT):
            return None
        today = datetime.utcnow().strftime("%Y-%m-%d")
        existing = self.db.query(WhatsAppTentativeBooking).filter(
            WhatsAppTentativeBooking.contact_id == contact_id,
            WhatsAppTentativeBooking.status.in_(["tentative", "confirmed"]),
            WhatsAppTentativeBooking.requested_date >= today,
        ).order_by(WhatsAppTentativeBooking.requested_date.asc()).all()
        if existing:
            complete = []
            for b in existing:
                extracted = b.extracted_fields or {}
                date_val = b.requested_date or extracted.get("date") or extracted.get("requested_date")
                time_val = b.requested_time or extracted.get("time") or extracted.get("requested_time")
                type_val = b.requested_type or extracted.get("type") or extracted.get("requested_type")
                persons_val = b.requested_persons or extracted.get("persons")
                if date_val and time_val:
                    complete.append((b, date_val, time_val, type_val, persons_val))
                else:
                    b.status = "cancelled"
                    logger.info(f"[BookingDedup] Auto-cancelled incomplete booking {b.id} for contact {contact_id}")
            self.db.commit()
            if complete:
                lines = ["Here are your upcoming bookings:\n"]
                for b, d, t, tp, _ in complete:
                    icon = "✅" if b.status == "confirmed" else "⏳"
                    info = f" ({tp})" if tp else ""
                    lines.append(f"{icon} {d} at {t}{info}")
                lines.append("\nNeed changes? Let me know!")
                return "\n".join(lines)
        if intent == BOOKING_LOOKUP_INTENT:
            return "You have no upcoming bookings. Would you like to make one? Just say 'book' and I'll help!"
        return None

    async def _process_message_to_llm(
        self,
        tenant_id: str,
        contact_id: str,
        wa_session_id: str,
        wa_message_id: str,
        message_text: str,
        wa_config: WhatsAppConfiguration = None,
        conversation_stage: str = "opening"
    ) -> Dict[str, Any]:
        """
        Process message through LLM and send response
        """
        try:
            # Get WhatsApp session and contact
            wa_session = self.db.query(WhatsAppSession).filter(
                WhatsAppSession.id == wa_session_id
            ).first()
            
            contact = self.db.query(WhatsAppContact).filter(
                WhatsAppContact.id == contact_id
            ).first()
            
            if not contact or not wa_session:
                return {"success": False, "error": "Contact or session not found"}
            
            # Get or create LLM chat session
            llm_session_id = wa_session.llm_session_id
            if not llm_session_id:
                llm_session = ChatSession(
                    tenant_id=tenant_id,
                    user_id=contact.phone_number,
                    lead_name=None,
                    lead_email=None,
                    lead_phone=None,
                    lead_collected_at=None,
                    lead_prompt_count=0,
                    session_data={"lead_collected": False, "gate_prompted": False},
                )
                self.db.add(llm_session)
                self.db.commit()
                llm_session_id = llm_session.id
                
                # Link to WhatsApp session
                wa_session.llm_session_id = llm_session_id
                self.db.commit()
            
            # Get config if not provided
            if not wa_config:
                wa_config = self.db.query(WhatsAppConfiguration).filter(
                    WhatsAppConfiguration.tenant_id == tenant_id
                ).first()
            
            target_chars = (wa_config.response_target_chars or 300) if wa_config else 300
            short_mode = (wa_config.short_response_mode or True) if wa_config else True
            
            # Re-initialize formatter with tenant's target length
            self.response_formatter = ResponseFormatter(target_length=target_chars)
            
            # Call LLM via ChatService with conversation context
            extra_context = {
                "channel": "whatsapp",
                "conversation_stage": conversation_stage,
                "short_response_mode": short_mode,
                "target_chars": target_chars,
            }
            llm_response = await self.chat_service.send_message(
                tenant_id=tenant_id,
                content=message_text,
                session_id=llm_session_id,
                user_id=contact.phone_number,
                extra_context=extra_context,
            )

            # Format response for WhatsApp
            assistant_content = llm_response.get("content", "")
            format_result = self.response_formatter.format_for_whatsapp(
                response=assistant_content,
                include_metadata=True
            )
            
            formatted_text = format_result["formatted_text"]
            
            if not wa_config or not wa_config.is_active:
                logger.error(f"[WhatsApp] Configuration not found for tenant {tenant_id}")
                return {"success": False, "error": "WhatsApp not configured"}
            
            # Send response via WhatsApp API
            send_result = await self._send_whatsapp_message(
                wa_config=wa_config,
                recipient_phone=contact.phone_number,
                message_text=formatted_text
            )
            
            if send_result.get("success"):
                # Store outgoing message
                outgoing_msg = WhatsAppMessage(
                    tenant_id=tenant_id,
                    contact_id=contact.id,
                    chat_session_id=llm_session_id,
                    whatsapp_message_id=send_result.get("message_id"),
                    direction="outbound",
                    message_type="text",
                    content=formatted_text,
                    delivery_status="sent",
                    msg_metadata={
                        "llm_response_id": llm_response.get("id"),
                        "formatting": format_result
                    }
                )
                self.db.add(outgoing_msg)
                
                # Update WhatsApp session
                wa_session.last_ai_message_at = datetime.utcnow()
                wa_session.message_count += 1
                
                self.db.commit()
                
                logger.info(f"[WhatsApp] Message sent to {contact.phone_number}")
                return {"success": True, "message_id": send_result.get("message_id")}
            else:
                logger.error(f"[WhatsApp] Failed to send response: {send_result}")
                return {"success": False, "error": send_result.get("error")}
        
        except Exception as e:
            logger.exception(f"[WhatsApp] LLM processing failed: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def _send_whatsapp_message(
        self,
        wa_config: WhatsAppConfiguration,
        recipient_phone: str,
        message_text: str
    ) -> Dict[str, Any]:
        """Send message via WhatsApp Business API or MSG91"""
        try:
            meta = wa_config.config_metadata or {}
            msg91_auth_key = meta.get("msg91_auth_key") or os.getenv("MSG91_AUTH_KEY", "")

            if msg91_auth_key:
                integrated_number = meta.get("msg91_integrated_number", "") or wa_config.phone_number_id
                base_url = meta.get("msg91_api_endpoint", "") or "https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/"
                provider = get_whatsapp_provider(
                    provider_type="msg91",
                    auth_key=msg91_auth_key,
                    integrated_number=integrated_number,
                    base_url=base_url
                )
                logger.info(f"[WhatsApp] Sending via MSG91 to {recipient_phone}")
            else:
                provider = get_whatsapp_provider(
                    provider_type="cloud_api",
                    phone_number_id=wa_config.phone_number_id,
                    business_account_id=wa_config.business_account_id,
                    access_token=wa_config.access_token,
                    api_version=wa_config.api_version
                )
            
            result = await provider.send_message(
                recipient_phone=recipient_phone,
                message_text=message_text
            )
            
            return result
        
        except Exception as e:
            logger.exception(f"[WhatsApp] Send message error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _get_conversation_stage(self, session: WhatsAppSession, message_text: str, intent: str) -> str:
        meta = session.session_metadata or {}
        stage = meta.get("stage", "opening")
        msg_count = session.message_count or 0
        if intent in ("booking", "callback", "demo_scheduling"):
            return "action"
        if stage == "completed" or session.status == "closed":
            return "closed"
        if msg_count >= 8:
            return "resolving"
        if msg_count >= 4:
            return "info_gathering"
        return "opening"

    def _check_cooldown(self, contact_id: str, wa_config: WhatsAppConfiguration) -> Optional[str]:
        if not wa_config.cooldown_seconds:
            return None
        last = self.db.query(WhatsAppMessage).filter(
            WhatsAppMessage.contact_id == contact_id,
            WhatsAppMessage.direction == "outbound"
        ).order_by(WhatsAppMessage.created_at.desc()).first()
        if last and last.created_at:
            elapsed = (datetime.utcnow() - last.created_at).total_seconds()
            if elapsed < wa_config.cooldown_seconds:
                remaining = round(wa_config.cooldown_seconds - elapsed, 1)
                logger.info(f"[WhatsApp] Cooldown active for {contact_id}: {remaining}s remaining")
                return f"Cooldown: {remaining}s"
        return None

    def _check_rate_limit(self, contact_id: str, wa_config: WhatsAppConfiguration) -> Optional[str]:
        if not wa_config.rate_limit_max_per_minute:
            return None
        cutoff = datetime.utcnow() - timedelta(seconds=60)
        recent = self.db.query(WhatsAppMessage).filter(
            WhatsAppMessage.contact_id == contact_id,
            WhatsAppMessage.direction == "outbound",
            WhatsAppMessage.created_at >= cutoff
        ).count()
        if recent >= wa_config.rate_limit_max_per_minute:
            logger.info(f"[WhatsApp] Rate limit hit for {contact_id}: {recent}/{wa_config.rate_limit_max_per_minute} per min")
            return f"Rate limit: {recent}/{wa_config.rate_limit_max_per_minute}"
        return None

    def _get_or_create_contact(
        self,
        tenant_id: str,
        phone_number: str,
        profile_name: Optional[str] = None
    ) -> WhatsAppContact:
        """Get or create WhatsApp contact. Store profile name from WhatsApp if available."""
        contact = self.db.query(WhatsAppContact).filter(
            WhatsAppContact.tenant_id == tenant_id,
            WhatsAppContact.phone_number == phone_number
        ).first()
        
        if not contact:
            contact = WhatsAppContact(
                tenant_id=tenant_id,
                phone_number=phone_number,
                contact_name=profile_name,  # Store WhatsApp profile name
                first_message_at=datetime.utcnow(),
                total_messages=1
            )
            self.db.add(contact)
            self.db.commit()
            logger.info(f"[WhatsApp] New contact: {phone_number} ({profile_name or 'no name'})")
        else:
            contact.last_message_at = datetime.utcnow()
            contact.total_messages += 1
            # Update name if we have it and they don't
            if profile_name and not contact.contact_name:
                contact.contact_name = profile_name
            self.db.commit()
        
        return contact

    def _generate_welcome_message(self, name: str, tenant: Tenant) -> Optional[str]:
        """Generate personalized welcome message for first-time WhatsApp contact."""
        if not name:
            return None
        
        # Get business name from tenant
        business_name = tenant.tenant_name if tenant else "our business"
        
        # Crisp, friendly welcome with clear call-to-action
        return (
            f"Hi {name}! 👋 Welcome to {business_name}.\n\n"
            f"I can help you:\n"
            f"• Book an appointment\n"
            f"• Request a callback\n"
            f"• Answer questions\n\n"
            f"What would you like to do?"
        )
    
    async def _enrich_contact_from_history(
        self,
        tenant_id: str,
        contact: WhatsAppContact
    ) -> None:
        """AI auto-enrichment: extract company, interest, sentiment from conversation history.
        Uses a dedicated DB session to avoid racing with the main request's session."""
        from app.database import SessionLocal
        session = SessionLocal()
        try:
            messages = session.query(WhatsAppMessage).filter(
                WhatsAppMessage.contact_id == contact.id,
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.direction == "inbound"
            ).order_by(WhatsAppMessage.created_at.asc()).limit(10).all()

            conversation = "\n".join(
                f"Customer: {m.content[:300]}" for m in messages
            )
            if not conversation:
                return

            prompt = (
                "From the following WhatsApp conversation, extract:\n"
                "- company (company name mentioned, if any)\n"
                "- interest (what the customer is looking for, 1 phrase)\n"
                "- sentiment (positive, neutral, or negative)\n\n"
                f"Conversation:\n{conversation}\n\n"
                "Respond with JSON only: {\"company\": \"...\", \"interest\": \"...\", \"sentiment\": \"...\"}"
            )

            tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
            llm_provider = getattr(tenant, "llm_provider", None) or self.chat_service.llm_adapter

            from app.adapters.llm import get_llm_adapter
            adapter = get_llm_adapter(llm_provider) if isinstance(llm_provider, str) else llm_provider

            response = await adapter.generate(prompt, max_tokens=200)
            import json
            try:
                data = json.loads(response)
                db_contact = session.query(WhatsAppContact).filter(
                    WhatsAppContact.id == contact.id
                ).first()
                if db_contact:
                    meta = db_contact.contact_metadata or {}
                    if data.get("company"):
                        db_contact.company = data["company"][:255]
                    if data.get("interest"):
                        meta["interest"] = data["interest"]
                    if data.get("sentiment"):
                        meta["sentiment"] = data["sentiment"]
                    db_contact.contact_metadata = meta
                    session.commit()
                    logger.info(f"[CRM] Auto-enriched contact {contact.id}: company={data.get('company')}")
            except (json.JSONDecodeError, KeyError):
                logger.debug(f"[CRM] Enrichment parse failed for {contact.id}: {response[:100]}")
        except Exception as e:
            logger.debug(f"[CRM] Enrichment error for {contact.id}: {e}")
        finally:
            session.close()
    
    async def _schedule_follow_up_async(
        self,
        tenant_id: str,
        contact_id: str,
        trigger_event: str,
        booking: Optional[WhatsAppTentativeBooking] = None,
    ) -> None:
        """Fire-and-forget: schedule a CRM follow-up message.
        Uses a dedicated DB session to avoid racing with the main request's session."""
        from app.database import SessionLocal
        session = SessionLocal()
        try:
            # Re-attach booking to the dedicated session if needed
            b = None
            if booking:
                b = session.query(WhatsAppTentativeBooking).filter(
                    WhatsAppTentativeBooking.id == booking.id
                ).first()
            schedule_follow_up(session, tenant_id, contact_id, trigger_event, b)
        except Exception as e:
            logger.debug(f"[CRM] Follow-up schedule error: {e}")
        finally:
            session.close()

    async def _notify_tenant_of_booking(
        self,
        tenant_id: str,
        contact: WhatsAppContact,
        booking: WhatsAppTentativeBooking,
    ) -> None:
        """Fire-and-forget: send email notification to tenant when new booking created.
        Respects tenant notification preferences (enable/disable)."""
        from app.database import SessionLocal
        from app.services.email_service import send_email
        
        session = SessionLocal()
        try:
            tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
            if not tenant:
                return
            
            # Check if email notifications are enabled (default: enabled)
            notify_enabled = tenant.notify_on_booking if hasattr(tenant, 'notify_on_booking') else True
            
            if not notify_enabled:
                logger.debug(f"[BookingNotify] Notifications disabled for tenant {tenant_id}")
                return
            
            # Get notification email (custom or fallback to daily report email)
            notification_email = tenant.notification_email if hasattr(tenant, 'notification_email') else None
            if not notification_email:
                notification_email = tenant.daily_report_email
            if not notification_email:
                # Fallback to tenant's primary contact email if available
                notification_email = tenant.contact_email
            
            if not notification_email:
                logger.debug(f"[BookingNotify] No notification email for tenant {tenant_id}")
                return
            
            # Build notification content
            intent_type = booking.intent_type or "booking"
            contact_name = contact.contact_name or contact.phone_number
            date_str = booking.requested_date or "TBD"
            time_str = booking.requested_time or "TBD"
            
            subject = f"🔔 New {intent_type.title()} Request - {contact_name}"
            
            dashboard_url = f"https://chat.scubeinfotech.com.sg/public/dashboard"
            
            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #4F46E5;">🔔 New {intent_type.title()} Request</h2>
                
                <div style="background: #F3F4F6; padding: 16px; border-radius: 8px; margin: 16px 0;">
                    <p><strong>Customer:</strong> {contact_name}</p>
                    <p><strong>Phone:</strong> {contact.phone_number}</p>
                    <p><strong>Date:</strong> {date_str}</p>
                    <p><strong>Time:</strong> {time_str}</p>
                    <p><strong>Status:</strong> ⏳ Tentative (pending your confirmation)</p>
                </div>
                
                <p><strong>What they said:</strong></p>
                <blockquote style="border-left: 4px solid #4F46E5; padding-left: 12px; color: #374151;">
                    {booking.raw_text[:200]}
                </blockquote>
                
                <div style="margin-top: 24px; text-align: center;">
                    <a href="{dashboard_url}" 
                       style="background: #4F46E5; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 6px; display: inline-block;">
                        Confirm or Cancel in Dashboard →
                    </a>
                </div>
                
                <p style="font-size: 12px; color: #6B7280; margin-top: 24px;">
                    To disable these notifications, update your settings in the dashboard.<br>
                    Booking ID: {booking.id}
                </p>
            </div>
            """
            
            text_body = f"""🔔 New {intent_type.title()} Request

Customer: {contact_name}
Phone: {contact.phone_number}
Date: {date_str}
Time: {time_str}
Status: Tentative (pending confirmation)

What they said: {booking.raw_text[:200]}

Confirm or Cancel: {dashboard_url}

Booking ID: {booking.id}
            """
            
            result = await send_email(
                to=notification_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body
            )
            
            if result:
                logger.info(f"[BookingNotify] Email sent to {notification_email} for booking {booking.id}")
            else:
                logger.warning(f"[BookingNotify] Failed to send email for booking {booking.id}")
                
        except Exception as e:
            logger.error(f"[BookingNotify] Error sending notification: {e}")
        finally:
            session.close()
    
    def _get_or_create_whatsapp_session(
        self,
        tenant_id: str,
        contact_id: str
    ) -> WhatsAppSession:
        """Get or create WhatsApp session"""
        session = self.db.query(WhatsAppSession).filter(
            WhatsAppSession.tenant_id == tenant_id,
            WhatsAppSession.contact_id == contact_id,
            WhatsAppSession.status == "active"
        ).order_by(WhatsAppSession.updated_at.desc()).first()
        
        if not session:
            session = WhatsAppSession(
                tenant_id=tenant_id,
                contact_id=contact_id,
                status="active"
            )
            self.db.add(session)
            self.db.commit()
        
        return session
    
    def _extract_message_text(self, message_payload: Dict[str, Any]) -> str:
        """Extract text content from WhatsApp message payload"""
        msg_type = message_payload.get("type", "text")
        
        if msg_type == "text":
            return message_payload.get("text", {}).get("body", "")
        elif msg_type == "button":
            return message_payload.get("button", {}).get("text", "")
        elif msg_type == "interactive":
            interactive = message_payload.get("interactive", {})
            return interactive.get("button_reply", {}).get("title", "") or \
                   interactive.get("list_reply", {}).get("title", "")
        else:
            # For media types, extract caption
            return message_payload.get(msg_type, {}).get("caption", "")
    
    def verify_webhook(
        self,
        challenge: str,
        verify_token: str,
        tenant_id: str
    ) -> Optional[str]:
        """
        Verify WhatsApp webhook token

        Args:
            challenge: Challenge from WhatsApp
            verify_token: Token provided by WhatsApp
            tenant_id: Tenant ID

        Returns:
            Challenge if verified, None otherwise
        """
        logger.info(f"[WhatsApp] Verification attempt - tenant: {tenant_id}, token received: {verify_token[:20] if verify_token else 'None'}...")

        wa_config = self.db.query(WhatsAppConfiguration).filter(
            WhatsAppConfiguration.tenant_id == tenant_id
        ).first()

        if not wa_config:
            logger.warning(f"[WhatsApp] No config for tenant {tenant_id}")
            return None

        logger.info(f"[WhatsApp] Config token: {wa_config.webhook_verify_token[:20] if wa_config.webhook_verify_token else 'None'}...")

        if verify_token == wa_config.webhook_verify_token:
            logger.info(f"[WhatsApp] Webhook verified for tenant {tenant_id}")
            return challenge

        logger.warning(f"[WhatsApp] Webhook verification failed for tenant {tenant_id} - token mismatch")
        return None
