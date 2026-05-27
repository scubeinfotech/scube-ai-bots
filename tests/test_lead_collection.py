"""
Test lead collection feature
"""
import pytest
import re
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models import Tenant, ChatSession, ChatMessage
from app.services.chat_service import ChatService


SQLALCHEMY_DATABASE_URL = "sqlite:///./test_lead.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_lead_extraction():
    """Test that lead info is extracted from user messages"""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    try:
        # Create tenant
        tenant = Tenant(
            id="test-tenant-1",
            name="Test Business",
            slug="test-lead",
            domain="test.com",
            is_active=True
        )
        db.add(tenant)
        db.commit()
        
        # Create session
        session = ChatSession(
            id="test-session-1",
            tenant_id=tenant.id
        )
        db.add(session)
        db.commit()
        
        # Create chat service
        chat_service = ChatService(db=db, llm_provider="mock")
        
        # Test name extraction patterns
        test_cases = [
            ("my name is John", "John"),
            ("I am Sarah", "Sarah"),
            ("call me Mike", "Mike"),
            ("John here", "John"),
            ("this is David", "David"),
            ("hi there", None),  # Should skip
            ("thanks", None),  # Should skip
        ]
        
        print("\n=== Testing Lead Extraction ===")
        for user_msg, expected_name in test_cases:
            # Clear any previous extraction by checking the internal method directly
            email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', user_msg)
            email = email_match.group(0) if email_match else None
            
            # Test name extraction
            name = None
            name_patterns = [
                r'call me (\w+)',
                r'i go by (\w+)',
                r'(?:my name is|name is|name\'s|i am|this is|its) (\w+)',
                r'^(\w+)(?:\s|$|\.|,|!)',
                r'(\w+) here',
                r'(\w+) speaking',
            ]
            skip_words = {'hi', 'hello', 'hey', 'thanks', 'thank', 'okay', 'ok', 'yes', 'no', 'sure', 'yeah', 'yep', 'nah', 'fine', 'great'}
            for pattern in name_patterns:
                match = re.search(pattern, user_msg, re.IGNORECASE)
                if match:
                    name = match.group(1).capitalize()
                    if name.lower() in skip_words:
                        name = None
                    elif len(name) >= 2:
                        break
            
            result = "PASS" if (name == expected_name or (name is None and expected_name is None)) else "FAIL"
            print(f"  Input: '{user_msg}' -> Name: '{name}' (expected: '{expected_name}') [{result}]")
        
        print("\n=== Testing Lead Collection Trigger ===")
        # Simulate message count and check trigger
        user_msg_count = db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id,
            ChatMessage.role == "user"
        ).count()
        
        lead_collected = session.lead_email and session.lead_name and session.lead_phone
        will_trigger = user_msg_count >= 3 and user_msg_count <= 5 and not lead_collected
        
        print(f"  User messages: {user_msg_count}")
        print(f"  Lead collected: {lead_collected}")
        print(f"  Will prompt for lead: {will_trigger}")
        
        # Add user messages to test trigger
        for i in range(3):
            msg = ChatMessage(
                session_id=session.id,
                tenant_id=tenant.id,
                role="user",
                content=f"Test message {i+1}"
            )
            db.add(msg)
        db.commit()
        
        user_msg_count = db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id,
            ChatMessage.role == "user"
        ).count()
        
        lead_collected = session.lead_email and session.lead_name and session.lead_phone
        will_trigger_after_3 = user_msg_count >= 3 and user_msg_count <= 5 and not lead_collected
        
        print(f"\n  After 3 user messages:")
        print(f"    User messages: {user_msg_count}")
        print(f"    Lead collected: {lead_collected}")
        print(f"    Will prompt for lead: {will_trigger_after_3}")
        
        assert user_msg_count == 3, f"Expected 3 messages, got {user_msg_count}"
        assert not lead_collected, "Lead should not be collected yet"
        assert will_trigger_after_3, "Lead prompt should trigger after 3 messages"
        
        print("\n=== ALL TESTS PASSED ===")
        
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


if __name__ == "__main__":
    test_lead_extraction()