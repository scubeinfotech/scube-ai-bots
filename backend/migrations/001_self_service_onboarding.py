#!/usr/bin/env python
"""
Migration: Add self-service onboarding tables and trial columns.

Creates:
- invoices table
- subscription_plans table
- support_tickets table
- Adds trial_ends_at, subscription_plan, subscription_status, stripe_customer_id to tenants

Also seeds default subscription plans (starter, growth, enterprise).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, SessionLocal
from app.models import Tenant, SubscriptionPlan
from sqlalchemy import text
from datetime import datetime


def run_migration():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("Migration: Self-Service Onboarding")
        print("=" * 60)

        # 1. Add trial columns to tenants (idempotent)
        print("\n[1/4] Adding trial columns to tenants...")
        columns_to_add = [
            ("trial_ends_at", "TIMESTAMP"),
            ("subscription_plan", "VARCHAR(50) DEFAULT 'trial'"),
            ("subscription_status", "VARCHAR(20) DEFAULT 'active'"),
            ("stripe_customer_id", "VARCHAR(255)"),
        ]
        for col_name, col_type in columns_to_add:
            try:
                db.execute(text(f"ALTER TABLE tenants ADD COLUMN {col_name} {col_type}"))
                print(f"  ✓ Added column: {col_name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"  - Column {col_name} already exists, skipping")
                else:
                    print(f"  ! Error adding {col_name}: {e}")
        db.commit()

        # 2. Create invoices table
        print("\n[2/4] Creating invoices table...")
        try:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id VARCHAR(36) PRIMARY KEY,
                    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
                    amount FLOAT NOT NULL,
                    currency VARCHAR(3) DEFAULT 'SGD',
                    description VARCHAR(500),
                    plan VARCHAR(50),
                    payment_method VARCHAR(20),
                    payment_status VARCHAR(20) DEFAULT 'pending',
                    stripe_payment_intent_id VARCHAR(255),
                    stripe_checkout_session_id VARCHAR(255),
                    paynow_qr_data TEXT,
                    paynow_reference VARCHAR(100),
                    due_date TIMESTAMP,
                    paid_at TIMESTAMP,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            print("  ✓ Created invoices table")
        except Exception as e:
            print(f"  ! Error: {e}")
        db.commit()

        # 3. Create subscription_plans table
        print("\n[3/4] Creating subscription_plans table...")
        try:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS subscription_plans (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(50) UNIQUE NOT NULL,
                    display_name VARCHAR(100) NOT NULL,
                    description TEXT,
                    price_monthly FLOAT NOT NULL,
                    price_annual FLOAT,
                    currency VARCHAR(3) DEFAULT 'SGD',
                    trial_days INTEGER DEFAULT 7,
                    features TEXT,
                    includes_chatbot BOOLEAN DEFAULT TRUE,
                    includes_whatsapp BOOLEAN DEFAULT FALSE,
                    monthly_message_limit INTEGER DEFAULT 1000,
                    max_documents INTEGER DEFAULT 50,
                    priority_support BOOLEAN DEFAULT FALSE,
                    stripe_price_id_monthly VARCHAR(255),
                    stripe_price_id_annual VARCHAR(255),
                    is_active BOOLEAN DEFAULT TRUE,
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            print("  ✓ Created subscription_plans table")
        except Exception as e:
            print(f"  ! Error: {e}")
        db.commit()

        # 4. Create support_tickets table
        print("\n[4/4] Creating support_tickets table...")
        try:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id VARCHAR(36) PRIMARY KEY,
                    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id),
                    tenant_user_id VARCHAR(36) REFERENCES tenant_users(id),
                    subject VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    category VARCHAR(50) DEFAULT 'general',
                    status VARCHAR(20) DEFAULT 'open',
                    priority VARCHAR(20) DEFAULT 'normal',
                    admin_notes TEXT,
                    assigned_to VARCHAR(255),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    resolved_at TIMESTAMP
                )
            """))
            print("  ✓ Created support_tickets table")
        except Exception as e:
            print(f"  ! Error: {e}")
        db.commit()

        # 5. Seed default subscription plans
        print("\n[5/5] Seeding default subscription plans...")
        existing_plans = db.query(SubscriptionPlan).all()
        if existing_plans:
            print(f"  - {len(existing_plans)} plans already exist, skipping seed")
        else:
            plans = [
            SubscriptionPlan(
                name="trial",
                display_name="Free Trial",
                description="15-day free trial with full access to all features",
                price_monthly=0,
                trial_days=15,
                includes_chatbot=True,
                includes_whatsapp=True,
                monthly_message_limit=500,
                max_documents=100,
                is_active=True,
                is_default=True,
            ),
                SubscriptionPlan(
                    name="starter",
                    display_name="Starter",
                    description="Perfect for small businesses getting started with AI chat",
                    price_monthly=15,
                    price_annual=153,
                    trial_days=15,
                    includes_chatbot=True,
                    includes_whatsapp=False,
                    monthly_message_limit=2000,
                    max_documents=50,
                    is_active=True,
                ),
                SubscriptionPlan(
                    name="growth",
                    display_name="Growth",
                    description="Growing businesses that need chat + WhatsApp",
                    price_monthly=59,
                    price_annual=590,
                    trial_days=7,
                    includes_chatbot=True,
                    includes_whatsapp=True,
                    monthly_message_limit=10000,
                    max_documents=200,
                    priority_support=True,
                    is_active=True,
                ),
            ]
            for plan in plans:
                db.add(plan)
            db.commit()
            print(f"  ✓ Seeded {len(plans)} subscription plans")

            # Ensure enterprise plan is inactive (if exists)
            try:
                db.execute(text("UPDATE subscription_plans SET is_active = false WHERE name = 'enterprise'"))
                db.commit()
                print("  ✓ Set enterprise plan to inactive")
            except Exception as e:
                print(f"  ! Error updating enterprise plan: {e}")
                db.rollback()

        # 6. Set existing tenants to trial if no subscription_plan set
        print("\n[6/6] Updating existing tenants...")
        existing_tenants = db.query(Tenant).filter(
            Tenant.subscription_plan == None
        ).all()
        if existing_tenants:
            for t in existing_tenants:
                t.subscription_plan = "trial"
                t.subscription_status = "active"
            db.commit()
            print(f"  ✓ Updated {len(existing_tenants)} existing tenants to trial")
        else:
            print("  - All tenants already have subscription_plan set")

        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"\n✗ Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
