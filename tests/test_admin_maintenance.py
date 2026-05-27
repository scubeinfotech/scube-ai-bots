"""Tests for admin maintenance endpoints."""

import uuid

from app.models import Document, DocumentChunk, Tenant, UnansweredQuery


def test_tenant_health_returns_vector_metrics(test_client, db):
    """Tenant health endpoint should return real crawl/index metrics used by dashboard."""
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Health Tenant",
        slug="health-tenant",
        domain="health.example.com",
        is_active=True,
        onboarding_stage="ready",
        industry="services",
        tone="friendly",
        compliance_mode="normal",
        out_of_scope_mode="strict_business",
    )
    db.add(tenant)
    db.flush()

    crawled_doc = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name="Website FAQ",
        content="Q: What services do you offer?\nA: We offer consulting.",
        document_type="document",
        is_active=True,
        is_processed=True,
    )
    learned_doc = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name="Auto-learned pair",
        content="Q: hi\nA: Hello!",
        document_type="learned",
        is_active=True,
        is_processed=True,
    )
    db.add(crawled_doc)
    db.add(learned_doc)
    db.flush()

    db.add_all(
        [
            DocumentChunk(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                document_id=crawled_doc.id,
                chunk_index=0,
                content="services we offer",
                embedding=[0.1, 0.2, 0.3],
            ),
            DocumentChunk(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                document_id=learned_doc.id,
                chunk_index=0,
                content="hello greeting",
                embedding=[0.4, 0.5, 0.6],
            ),
            DocumentChunk(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                document_id=learned_doc.id,
                chunk_index=1,
                content="follow-up greeting",
                embedding=[0.7, 0.8, 0.9],
            ),
        ]
    )
    db.commit()

    response = test_client.get(f"/api/admin/maintenance/tenant-health/{tenant.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["tenant_id"] == tenant.id
    assert data["onboarding_stage"] == "ready"
    assert data["crawled_docs"] == 1
    assert data["indexed_docs"] == 2
    assert data["indexed_chunks"] == 3
    assert data["persona"]["label"] == "Aligned"


def test_unanswered_queries_returns_clusters(test_client, db):
    """Unanswered endpoint should cluster similar intents for faster training triage."""
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Cluster Tenant",
        slug="cluster-tenant",
        domain="cluster.example.com",
        is_active=True,
    )
    db.add(tenant)
    db.flush()

    db.add_all(
        [
            UnansweredQuery(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                query="Services offered",
                response="Could you please provide more context?",
                confidence_score=0.6,
                reason="Low confidence detected",
                is_resolved=False,
            ),
            UnansweredQuery(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                query="what are all services",
                response="Could you please provide more context?",
                confidence_score=0.55,
                reason="Low confidence detected",
                is_resolved=False,
            ),
            UnansweredQuery(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                query="pricing details",
                response="Could you please provide more context?",
                confidence_score=0.58,
                reason="Low confidence detected",
                is_resolved=False,
            ),
        ]
    )
    db.commit()

    response = test_client.get(f"/api/admin/unanswered-queries/{tenant.id}?limit=100&resolved_only=false")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 3
    assert isinstance(data.get("clusters"), list)
    assert len(data["clusters"]) >= 1

    top = data["clusters"][0]
    assert top["count"] >= 2
    assert top["sample_query"] in {"Services offered", "what are all services"}
