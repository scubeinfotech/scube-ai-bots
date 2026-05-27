"""
Analytics API tests
"""
from datetime import datetime, timedelta, timezone

from conftest import client
from app.models import Tenant, ChatSession, ChatMessage
from app.models.whatsapp import WhatsAppAnalyticsEvent
from conftest import TestingSessionLocal
from app.services.analytics_logger import (
    INTENT_DETECTED,
    BOOKING_CREATED,
    BOOKING_CONFIRMED,
    HUMAN_INTERVENTION,
    CALENDAR_SYNCED,
    CRM_SYNCED,
)


def test_tenant_dashboard_not_found():
    """Unknown tenant should return 404."""
    response = client.get("/api/analytics/tenant/does-not-exist/dashboard")
    assert response.status_code == 404


def test_tenant_dashboard_metrics_shape():
    """Dashboard should include sales, maintenance, and overview sections."""
    create = client.post("/api/tenants/", json={
        "name": "Analytics Tenant",
        "slug": "analytics-tenant",
        "domain": "analytics.com",
        "knowledge_context": {
            "products": [
                {
                    "name": "ChronoBill",
                    "aliases": ["chronobill", "chrono bill"],
                    "description": "Billing product"
                }
            ]
        }
    })
    tenant_id = create.json()["id"]

    # Create one simple chat turn
    client.post(f"/api/chat/message/{tenant_id}", json={"content": "what is chronobill"})

    response = client.get(f"/api/analytics/tenant/{tenant_id}/dashboard?days=7")
    assert response.status_code == 200

    data = response.json()
    assert data["tenant_id"] == tenant_id
    assert "sales" in data
    assert "maintenance" in data
    assert "overview" in data


def test_tenant_dashboard_sales_signals():
    """Product-intent and CTA metrics should be > 0 for product flow."""
    create = client.post("/api/tenants/", json={
        "name": "Sales Metrics Tenant",
        "slug": "sales-metrics-tenant",
        "domain": "sales-metrics.com",
        "knowledge_context": {
            "products": [
                {
                    "name": "ChronoBill",
                    "aliases": ["chronobill"],
                    "description": "Cloud billing"
                }
            ]
        }
    })
    tenant_id = create.json()["id"]

    # Insert chat turns directly to avoid auth coupling in this analytics test.
    db = TestingSessionLocal()
    try:
        session = ChatSession(tenant_id=tenant_id, title="sales-flow")
        db.add(session)
        db.commit()
        db.refresh(session)

        db.add_all([
            ChatMessage(
                session_id=session.id,
                tenant_id=tenant_id,
                role="user",
                content="i need chronobill",
            ),
            ChatMessage(
                session_id=session.id,
                tenant_id=tenant_id,
                role="assistant",
                content="ChronoBill is our cloud billing platform. Want a demo? Contact sales to get started.",
            ),
            ChatMessage(
                session_id=session.id,
                tenant_id=tenant_id,
                role="user",
                content="yes please",
            ),
        ])
        db.commit()
    finally:
        db.close()

    response = client.get(f"/api/analytics/tenant/{tenant_id}/dashboard?days=7")
    assert response.status_code == 200

    sales = response.json()["sales"]
    assert sales["product_intent_messages"] >= 1
    assert sales["lead_engagement_rate_percent"] > 0


def test_multi_tenant_summary_empty():
    """Summary with no tenants should return empty list."""
    response = client.get("/api/analytics/summary?days=7")
    assert response.status_code == 200
    data = response.json()
    assert data["total_tenants"] == 0
    assert len(data["tenants"]) == 0


def test_multi_tenant_summary_comparison():
    """Summary should compare all active tenants."""
    # Create two tenants with different activity
    tenant1 = client.post("/api/tenants/", json={
        "name": "Tenant High Activity",
        "slug": "tenant-high-activity",
        "domain": "high.com",
        "knowledge_context": {
            "products": [
                {
                    "name": "Product1",
                    "aliases": ["product1"],
                    "description": "First product"
                }
            ]
        }
    }).json()["id"]

    tenant2 = client.post("/api/tenants/", json={
        "name": "Tenant Low Activity",
        "slug": "tenant-low-activity",
        "domain": "low.com",
        "knowledge_context": {
            "products": [
                {
                    "name": "Product2",
                    "aliases": ["product2"],
                    "description": "Second product"
                }
            ]
        }
    }).json()["id"]

    # Add messages to tenant1 (should be higher engagement)
    client.post(f"/api/chat/message/{tenant1}", json={"content": "i need product1"})
    client.post(f"/api/chat/message/{tenant1}", json={"content": "yes"})

    # Add minimal messages to tenant2
    client.post(f"/api/chat/message/{tenant2}", json={"content": "help"})

    response = client.get("/api/analytics/summary?days=7")
    assert response.status_code == 200

    data = response.json()
    assert data["total_tenants"] == 2
    assert len(data["tenants"]) == 2
    assert data["window_days"] == 7
    assert "generated_at" in data

    # Verify schema has required fields
    for tenant in data["tenants"]:
        assert "tenant_id" in tenant
        assert "tenant_name" in tenant
        assert "sessions" in tenant
        assert "total_messages" in tenant
        assert "unanswered_count" in tenant
        assert "unanswered_rate_percent" in tenant
        assert "lead_engagement_rate_percent" in tenant
        assert "conversion_assist_rate_percent" in tenant
        assert "fallback_rate_percent" in tenant
        assert "llm_error_rate_percent" in tenant
        assert "avg_response_latency_ms" in tenant


def test_step6_tenant_whatsapp_analytics_endpoint():
    """Step 6 tenant endpoint should return intent/conversion/intervention metrics."""
    db = TestingSessionLocal()
    try:
        tenant = Tenant(name="Step6 Tenant", slug="step6-tenant", domain="step6.example")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        now = datetime.now(timezone.utc)
        db.add_all([
            WhatsAppAnalyticsEvent(
                tenant_id=tenant.id,
                event_type=INTENT_DETECTED,
                intent="booking",
                confidence_score=0.92,
                created_at=now - timedelta(days=1),
            ),
            WhatsAppAnalyticsEvent(
                tenant_id=tenant.id,
                event_type=BOOKING_CREATED,
                created_at=now - timedelta(days=1),
            ),
            WhatsAppAnalyticsEvent(
                tenant_id=tenant.id,
                event_type=BOOKING_CONFIRMED,
                created_at=now - timedelta(days=1),
            ),
            WhatsAppAnalyticsEvent(
                tenant_id=tenant.id,
                event_type=HUMAN_INTERVENTION,
                sub_type="claim",
                created_at=now - timedelta(days=1),
            ),
            WhatsAppAnalyticsEvent(
                tenant_id=tenant.id,
                event_type=CALENDAR_SYNCED,
                created_at=now - timedelta(days=1),
            ),
            WhatsAppAnalyticsEvent(
                tenant_id=tenant.id,
                event_type=CRM_SYNCED,
                created_at=now - timedelta(days=1),
            ),
        ])
        db.commit()

        response = client.get(f"/api/analytics/tenant/{tenant.id}/whatsapp?days=7")
        assert response.status_code == 200
        payload = response.json()

        assert payload["tenant_id"] == tenant.id
        assert payload["intent_accuracy"]["total_detected"] == 1
        assert payload["intent_accuracy"]["by_intent"]["booking"] == 1
        assert payload["conversion_funnel"]["bookings_created"] == 1
        assert payload["conversion_funnel"]["bookings_confirmed"] == 1
        assert payload["human_intervention"]["total_interventions"] == 1
        assert payload["automation"]["calendar_synced"] == 1
        assert payload["automation"]["crm_synced"] == 1
        assert isinstance(payload["daily_trend"], list)
    finally:
        db.close()


def test_step6_whatsapp_summary_endpoint():
    """Step 6 summary endpoint should aggregate tenant-level WhatsApp analytics."""
    db = TestingSessionLocal()
    try:
        t1 = Tenant(name="Step6 A", slug="step6-a", domain="step6-a.example")
        t2 = Tenant(name="Step6 B", slug="step6-b", domain="step6-b.example")
        db.add_all([t1, t2])
        db.commit()
        db.refresh(t1)
        db.refresh(t2)

        now = datetime.now(timezone.utc)
        db.add_all([
            WhatsAppAnalyticsEvent(tenant_id=t1.id, event_type=INTENT_DETECTED, intent="booking", confidence_score=0.9, created_at=now),
            WhatsAppAnalyticsEvent(tenant_id=t1.id, event_type=BOOKING_CREATED, created_at=now),
            WhatsAppAnalyticsEvent(tenant_id=t1.id, event_type=BOOKING_CONFIRMED, created_at=now),
            WhatsAppAnalyticsEvent(tenant_id=t2.id, event_type=INTENT_DETECTED, intent="faq", confidence_score=0.6, created_at=now),
            WhatsAppAnalyticsEvent(tenant_id=t2.id, event_type=BOOKING_CREATED, created_at=now),
        ])
        db.commit()

        response = client.get("/api/analytics/whatsapp/summary?days=7")
        assert response.status_code == 200
        payload = response.json()

        assert payload["total_tenants"] == 2
        assert payload["window_days"] == 7
        assert "generated_at" in payload
        assert len(payload["tenants"]) == 2

        for row in payload["tenants"]:
            assert "tenant_id" in row
            assert "tenant_name" in row
            assert "total_intents_detected" in row
            assert "bookings_created" in row
            assert "bookings_confirmed" in row
            assert "conversion_rate_pct" in row
            assert "human_intervention_rate_pct" in row
            assert "calendar_sync_rate_pct" in row
            assert "crm_sync_rate_pct" in row
    finally:
        db.close()
