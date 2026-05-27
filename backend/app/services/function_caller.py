"""
Function Calling Service - Enables AI to execute actions
This is a pure addition - no modifications to existing code.
"""
import json
import logging
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class FunctionDefinition:
    """Represents a callable function"""
    
    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable,
        requires_auth: bool = False
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.requires_auth = requires_auth


class FunctionCallResult:
    """Result of a function call"""
    
    def __init__(self, success: bool, result: Any = None, error: str = None):
        self.success = success
        self.result = result
        self.error = error
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "timestamp": self.timestamp.isoformat()
        }


class FunctionCallingService:
    """
    Manages function calling capabilities for the AI agent.
    Allows the AI to execute real actions (calendar, CRM, etc.)
    
    Usage (in chat_service.py):
        from app.services.function_caller import function_calling_service
        
        # Get available functions
        schemas = function_calling_service.get_function_schemas()
        
        # Execute a function
        result = await function_calling_service.execute_function(
            "book_appointment",
            {"date": "2026-04-21", "time": "14:00", "title": "Demo"}
        )
    """
    
    def __init__(self):
        self._functions: Dict[str, FunctionDefinition] = {}
        # Read global enable flag from environment
        import os
        self._enabled = os.getenv("FUNCTION_CALLING_ENABLED", "false").lower() == "true"
        self._register_builtin_functions()
        status = "enabled" if self._enabled else "disabled by default"
        logger.info(f"FunctionCallingService initialized ({status})")
    
    def _register_builtin_functions(self):
        """Register built-in functions"""
        
        # Check availability function
        self.register_function(FunctionDefinition(
            name="check_calendar_availability",
            description="Check if a time slot is available for booking a meeting",
            parameters={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "time": {"type": "string", "description": "Time in HH:MM format"},
                    "duration_minutes": {"type": "integer", "description": "Meeting duration in minutes"}
                },
                "required": ["date", "time", "duration_minutes"]
            },
            handler=self._check_calendar_availability
        ))
        
        # Book appointment function
        self.register_function(FunctionDefinition(
            name="book_appointment",
            description="Book an appointment/meeting on the calendar",
            parameters={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "time": {"type": "string", "description": "Time in HH:MM format"},
                    "duration_minutes": {"type": "integer", "description": "Meeting duration"},
                    "title": {"type": "string", "description": "Meeting title"},
                    "attendee_email": {"type": "string", "description": "Attendee email"},
                    "attendee_name": {"type": "string", "description": "Attendee name"},
                    "notes": {"type": "string", "description": "Meeting notes"}
                },
                "required": ["date", "time", "title"]
            },
            handler=self._book_appointment
        ))
        
        # Create lead function
        self.register_function(FunctionDefinition(
            name="create_lead",
            description="Create a new lead in the CRM system",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Lead name"},
                    "email": {"type": "string", "description": "Lead email"},
                    "phone": {"type": "string", "description": "Lead phone"},
                    "company": {"type": "string", "description": "Company name"},
                    "interest": {"type": "string", "description": "What they're interested in"}
                },
                "required": ["name", "email"]
            },
            handler=self._create_lead
        ))
        
        # Get CRM data function
        self.register_function(FunctionDefinition(
            name="get_customer_data",
            description="Retrieve customer information from CRM",
            parameters={
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Customer email"}
                },
                "required": ["email"]
            },
            handler=self._get_customer_data
        ))
        
        # Send email function
        self.register_function(FunctionDefinition(
            name="send_email",
            description="Send an email to the customer",
            parameters={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"}
                },
                "required": ["to", "subject", "body"]
            },
            handler=self._send_email
        ))
        
        # Escalate to human function
        self.register_function(FunctionDefinition(
            name="escalate_to_human",
            description="Escalate the conversation to a human agent",
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Reason for escalation"},
                    "priority": {"type": "string", "description": "Priority: low, medium, high"},
                    "notes": {"type": "string", "description": "Additional notes"}
                },
                "required": ["reason"]
            },
            handler=self._escalate_to_human
        ))
        
        logger.info(f"Registered {len(self._functions)} built-in functions")
    
    def register_function(self, func: FunctionDefinition):
        """Register a new function"""
        self._functions[func.name] = func
        logger.info(f"Registered function: {func.name}")
    
    def enable(self):
        """Enable function calling"""
        self._enabled = True
        logger.info("Function calling enabled")
    
    def disable(self):
        """Disable function calling"""
        self._enabled = False
        logger.info("Function calling disabled")
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
    
    def get_function_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAI-style function schemas for LLM"""
        if not self._enabled:
            return []
        schemas = []
        for func in self._functions.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": func.name,
                    "description": func.description,
                    "parameters": func.parameters
                }
            })
        return schemas
    
    async def execute_function(
        self,
        function_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> FunctionCallResult:
        """Execute a function by name with given arguments"""
        
        if not self._enabled:
            return FunctionCallResult(False, error="Function calling is disabled")
        
        if function_name not in self._functions:
            return FunctionCallResult(False, error=f"Function '{function_name}' not found")
        
        func = self._functions[function_name]
        
        try:
            # Add context to arguments
            if context:
                arguments["_context"] = context
            
            # Execute handler
            if asyncio.iscoroutinefunction(func.handler):
                result = await func.handler(**arguments)
            else:
                result = func.handler(**arguments)
            
            return FunctionCallResult(success=True, result=result)
            
        except Exception as e:
            logger.error(f"Function call error: {function_name} - {str(e)}")
            return FunctionCallResult(success=False, error=str(e))
    
    # Built-in function handlers
    
    def _check_calendar_availability(self, date: str, time: str, duration_minutes: int = 30) -> Dict[str, Any]:
        """Check if a time slot is available"""
        # TODO: Integrate with actual Google Calendar API
        return {
            "available": True,
            "slot": f"{date} {time}",
            "duration": duration_minutes,
            "message": "Time slot is available for booking"
        }
    
    def _book_appointment(self, date: str, time: str, title: str, duration_minutes: int = 30,
                      attendee_email: str = None, attendee_name: str = None, notes: str = None) -> Dict[str, Any]:
        """Book an appointment"""
        # TODO: Integrate with actual Google Calendar API
        booking_id = f"BK-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return {
            "booking_id": booking_id,
            "status": "confirmed",
            "meeting": {"title": title, "date": date, "time": time, "duration": duration_minutes},
            "message": f"Appointment '{title}' booked for {date} at {time}"
        }
    
    def _get_customer_data(self, email: str) -> Dict[str, Any]:
        """Get customer data from CRM"""
        # TODO: Integrate with actual CRM (Pipedrive/HubSpot)
        return {"found": False, "message": f"No customer found with email {email}"}
    
    def _create_lead(self, name: str, email: str, phone: str = None, company: str = None, interest: str = None) -> Dict[str, Any]:
        """Create a new lead"""
        # TODO: Integrate with actual CRM
        lead_id = f"LEAD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return {"lead_id": lead_id, "status": "created", "message": f"Lead created for {name}"}
    
    def _send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Send an email"""
        # TODO: Integrate with email service
        return {"email_id": f"EMAIL-{datetime.now().strftime('%Y%m%d%H%M%S')}", "status": "sent"}
    
    def _escalate_to_human(self, reason: str, priority: str = "medium", notes: str = None) -> Dict[str, Any]:
        """Escalate to human agent"""
        return {"escalation_id": f"ESC-{datetime.now().strftime('%Y%m%d%H%M%S')}", "status": "queued", "message": "Conversation escalated"}


# Singleton instance
function_calling_service = FunctionCallingService()
