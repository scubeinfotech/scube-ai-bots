"""
Delete a tenant and all associated data by email or tenant ID.
Usage: python scripts/delete_tenant.py --email nsinfinityserves@gmail.com
       python scripts/delete_tenant.py --tenant-id <uuid>
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.database import SessionLocal
from app.models import Tenant, TenantUser, APIKey, Document, DocumentChunk, ChatSession, ChatMessage, UnansweredQuery
from app.models.billing import Invoice
from app.models.calendar import CalendarIntegration, TenantAvailability
from app.models.support import SupportTicket
from app.models.whatsapp import (
    WhatsAppConfiguration, WhatsAppMessage, WhatsAppSession, WhatsAppMetrics,
    WhatsAppTentativeBooking, WhatsAppAnalyticsEvent,
)
from app.services.vector_knowledge import VectorKnowledgeService
import argparse


def delete_tenant(db, tenant_id: str) -> dict:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return {"error": "Tenant not found"}

    name = tenant.name
    slug = tenant.slug
    email = tenant.contact_email

    # Billing
    db.query(Invoice).filter(Invoice.tenant_id == tenant_id).delete(synchronize_session=False)
    # Calendar
    db.query(CalendarIntegration).filter(CalendarIntegration.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(TenantAvailability).filter(TenantAvailability.tenant_id == tenant_id).delete(synchronize_session=False)
    # Support tickets
    db.query(SupportTicket).filter(SupportTicket.tenant_id == tenant_id).delete(synchronize_session=False)
    # WhatsApp
    db.query(WhatsAppAnalyticsEvent).filter(WhatsAppAnalyticsEvent.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(WhatsAppTentativeBooking).filter(WhatsAppTentativeBooking.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(WhatsAppMetrics).filter(WhatsAppMetrics.tenant_id == tenant_id).delete(synchronize_session=False)
    wa_session_ids = [s.id for s in db.query(WhatsAppSession).filter(WhatsAppSession.tenant_id == tenant_id).all()]
    if wa_session_ids:
        db.query(WhatsAppMessage).filter(WhatsAppMessage.session_id.in_(wa_session_ids)).delete(synchronize_session=False)
    db.query(WhatsAppSession).filter(WhatsAppSession.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(WhatsAppConfiguration).filter(WhatsAppConfiguration.tenant_id == tenant_id).delete(synchronize_session=False)
    # Unanswered queries (must be before ChatSession due to FK)
    db.query(UnansweredQuery).filter(UnansweredQuery.tenant_id == tenant_id).delete(synchronize_session=False)
    # Chat
    session_ids = [s.id for s in db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).all()]
    if session_ids:
        db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).delete(synchronize_session=False)
    # Documents and chunks
    db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(Document).filter(Document.tenant_id == tenant_id).delete(synchronize_session=False)
    # Vector cleanup
    try:
        VectorKnowledgeService.delete_all_vectors_for_tenant(db, tenant_id)
    except Exception:
        pass
    # API keys and users
    db.query(APIKey).filter(APIKey.tenant_id == tenant_id).delete(synchronize_session=False)
    db.query(TenantUser).filter(TenantUser.tenant_id == tenant_id).delete(synchronize_session=False)
    # Tenant
    db.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)

    db.commit()
    return {"status": "deleted", "name": name, "slug": slug, "email": email}


def main():
    parser = argparse.ArgumentParser(description="Delete a tenant and all associated data")
    parser.add_argument("--email", help="Email of the tenant to delete")
    parser.add_argument("--tenant-id", help="UUID of the tenant to delete")
    parser.add_argument("--dry-run", action="store_true", help="Print matching tenant info without deleting")
    args = parser.parse_args()

    if not args.email and not args.tenant_id:
        parser.print_help()
        sys.exit(1)

    db = SessionLocal()

    if args.email:
        tenant = db.query(Tenant).join(TenantUser).filter(TenantUser.email == args.email).first()
        if not tenant:
            print(f"No tenant found for email: {args.email}")
            db.close()
            sys.exit(1)
    elif args.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == args.tenant_id).first()
        if not tenant:
            print(f"No tenant found with id: {args.tenant_id}")
            db.close()
            sys.exit(1)

    print(f"Tenant found:")
    print(f"  Name:  {tenant.name}")
    print(f"  Slug:  {tenant.slug}")
    print(f"  Email: {tenant.contact_email}")
    print(f"  ID:    {tenant.id}")

    if args.dry_run:
        print("\nDry run — no changes made.")
        db.close()
        return

    confirm = input(f"\nType 'yes' to permanently delete this tenant: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        db.close()
        return

    result = delete_tenant(db, tenant.id)
    print(f"\nDeleted: {result['name']} ({result['slug']})")
    db.close()


if __name__ == "__main__":
    main()
