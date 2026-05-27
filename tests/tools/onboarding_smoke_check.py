"""Reusable onboarding smoke check for active tenants.

Checks:
- active tenant count
- non-learned document count per tenant
- indexed chunk count per tenant
- flags tenants that are not onboarding-ready

Usage:
  PYTHONPATH=backend .venv/bin/python tests/tools/onboarding_smoke_check.py
"""

from sqlalchemy import func

from app.database import SessionLocal
from app.models import Document, DocumentChunk, Tenant


def main() -> int:
    db = SessionLocal()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        print(f"ACTIVE_TENANTS={len(tenants)}")

        not_ready = []
        for tenant in tenants:
            crawled_docs = (
                db.query(func.count(Document.id))
                .filter(
                    Document.tenant_id == tenant.id,
                    Document.is_active == True,
                    Document.document_type != "learned",
                )
                .scalar()
                or 0
            )
            indexed_chunks = (
                db.query(func.count(DocumentChunk.id))
                .join(Document, Document.id == DocumentChunk.document_id)
                .filter(
                    Document.tenant_id == tenant.id,
                    Document.is_active == True,
                )
                .scalar()
                or 0
            )

            ready = crawled_docs > 0 and indexed_chunks > 0
            status = "READY" if ready else "NOT_READY"
            print(
                f"{status} | tenant={tenant.name} | stage={tenant.onboarding_stage or 'unknown'} "
                f"| crawled_docs={crawled_docs} | indexed_chunks={indexed_chunks}"
            )

            if not ready:
                not_ready.append(tenant.name)

        if not_ready:
            print("\nTENANTS_NEED_ATTENTION:")
            for name in not_ready:
                print(f"- {name}")
            return 1

        print("\nAll active tenants are onboarding-ready.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
