"""Reusable vector-health diagnostic probe for tenant docs/chunks.

Usage:
  PYTHONPATH=backend .venv/bin/python tests/tools/probe_vector_health.py
"""

from sqlalchemy import func

from app.database import SessionLocal
from app.models import Document, DocumentChunk, Tenant


def main() -> None:
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        print(f"ACTIVE_TENANTS={len(tenants)}")

        for tenant in tenants:
            docs_total = (
                db.query(func.count(Document.id))
                .filter(Document.tenant_id == tenant.id, Document.is_active == True)
                .scalar()
                or 0
            )
            docs_nonlearned = (
                db.query(func.count(Document.id))
                .filter(
                    Document.tenant_id == tenant.id,
                    Document.is_active == True,
                    Document.document_type != "learned",
                )
                .scalar()
                or 0
            )
            docs_learned = (
                db.query(func.count(Document.id))
                .filter(
                    Document.tenant_id == tenant.id,
                    Document.is_active == True,
                    Document.document_type == "learned",
                )
                .scalar()
                or 0
            )
            docs_processed = (
                db.query(func.count(Document.id))
                .filter(
                    Document.tenant_id == tenant.id,
                    Document.is_active == True,
                    Document.is_processed == True,
                )
                .scalar()
                or 0
            )
            chunks = (
                db.query(func.count(DocumentChunk.id))
                .join(Document, DocumentChunk.document_id == Document.id)
                .filter(Document.tenant_id == tenant.id, Document.is_active == True)
                .scalar()
                or 0
            )

            print(f"TENANT={tenant.name} | id={tenant.id}")
            print(
                "  docs_total={} nonlearned={} learned={} processed={} chunks={}".format(
                    docs_total,
                    docs_nonlearned,
                    docs_learned,
                    docs_processed,
                    chunks,
                )
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()
