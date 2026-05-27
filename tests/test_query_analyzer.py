"""Tests for unanswered query analyzer quality filters."""

import uuid

from app.models import ChatMessage, ChatSession, Tenant, UnansweredQuery
from app.services.query_analyzer import _is_small_talk_query, scan_and_populate_unanswered_queries


def test_is_small_talk_query_classifies_greetings():
    assert _is_small_talk_query("hi")
    assert _is_small_talk_query("Good morning")
    assert _is_small_talk_query("hello!!!")
    assert not _is_small_talk_query("what services do you offer")


def test_scan_skips_small_talk_unanswered(test_client, db):
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Analyzer Tenant",
        slug="analyzer-tenant",
        domain="analyzer.example.com",
        is_active=True,
    )
    db.add(tenant)
    db.flush()

    session = ChatSession(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        user_id="user-1",
    )
    db.add(session)
    db.flush()

    # Greeting pair should be skipped even with a low-confidence assistant reply.
    db.add(
        ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tenant_id=tenant.id,
            role="user",
            content="Hi",
        )
    )
    db.add(
        ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tenant_id=tenant.id,
            role="assistant",
            content="Could you please provide more context?",
        )
    )

    # Business query pair should still be flagged if confidence is low.
    db.add(
        ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tenant_id=tenant.id,
            role="user",
            content="what are your services",
        )
    )
    db.add(
        ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tenant_id=tenant.id,
            role="assistant",
            content="Could you please provide more context?",
        )
    )

    db.commit()

    import asyncio

    stats = asyncio.run(
        scan_and_populate_unanswered_queries(days_lookback=7, confidence_threshold=0.8, db=db)
    )

    assert stats["processed"] == 2
    assert stats["flagged"] == 1

    rows = db.query(UnansweredQuery).filter(UnansweredQuery.tenant_id == tenant.id).all()
    assert len(rows) == 1
    assert rows[0].query == "what are your services"
