#!/usr/bin/env python
"""Compatibility wrapper for tests/tools/seed_rapas_tenant.py."""

import os
import runpy


if __name__ == "__main__":
    backend_dir = os.path.dirname(__file__)
    repo_root = os.path.dirname(backend_dir)
    target = os.path.join(repo_root, "tests", "tools", "seed_rapas_tenant.py")
    runpy.run_path(target, run_name="__main__")
"""
Seed script for Rapas tenant
Creates the Rapas tenant with marine engineering domain-specific configuration
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app.models import Tenant
import uuid


def seed_rapas_tenant():
    """Create Rapas tenant with marine engineering configuration"""
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Check if Rapas already exists
        existing = db.query(Tenant).filter(Tenant.slug == "rapas").first()
        if existing:
            print("✓ Rapas tenant already exists.")
            print("  To update knowledge, use the admin dashboard to trigger a website re-crawl.")
            return existing
        
        # Create Rapas tenant
        rapas = Tenant(
            id=str(uuid.uuid4()),
            name="Rapas Engineering Services Pte Ltd",
            slug="rapas",
            domain="rapas.com.sg",
            website_url="https://rapas.com.sg",
            industry="services",
            
            # No hardcoded prompt_template or knowledge_context — 
            # knowledge should come from website crawl, not seed data
            prompt_template=None,
            knowledge_context={},
            
            # LLM configuration
            model_name="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=1024,
            
            is_active=True
        )
        
        db.add(rapas)
        db.commit()
        db.refresh(rapas)
        
        print("✓ Successfully created Rapas tenant!")
        print(f"  ID: {rapas.id}")
        print(f"  Name: {rapas.name}")
        print(f"  Slug: {rapas.slug}")
        print(f"  Domain: {rapas.domain}")
        print(f"  Website: {rapas.website_url}")
        print(f"  Model: {rapas.model_name}")
        print(f"  Temperature: {rapas.temperature}")
        print(f"  Max Tokens: {rapas.max_tokens}")
        print("\n✓ Next: Trigger website crawl via admin dashboard to populate knowledge.")
        print(f"  Tenant ID for API calls: {rapas.id}")
        
        return rapas
        
    except Exception as e:
        db.rollback()
        print(f"✗ Error creating Rapas tenant: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Rapas Tenant Seeding Script")
    print("=" * 60)
    print()
    
    tenant = seed_rapas_tenant()
    
    print()
    print("=" * 60)
    print("Next Steps:")
    print("=" * 60)
    print("1. Set environment variable: export LLM_PROVIDER=groq")
    print("2. Get free Groq API key: https://console.groq.com")
    print("3. Set API key: export GROQ_API_KEY=your_key_here")
    print("4. Start backend: uvicorn app.main:app --reload")
    print(f"5. Test with tenant ID: {tenant.id}")
    print()
