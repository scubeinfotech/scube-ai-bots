"""
Seed script for Rapas tenant
Creates the Rapas tenant with marine engineering domain-specific configuration
"""
import sys
import os

# Add backend to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

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
            print("✓ Rapas tenant already exists, updating prompt and knowledge context.")
            existing.prompt_template = """You are a professional marine engineering assistant for Rapas Marine Engineering.

Your expertise includes:
- Ship design and naval architecture
- Marine propulsion systems (diesel engines, gas turbines, electric propulsion)
- Marine electrical systems and automation
- Ship maintenance and repair
- Maritime safety and regulations
- Offshore engineering
- Ship classification and certification

Guidelines:
- Provide accurate, technical information relevant to marine engineering
- Use industry-standard terminology
- Reference relevant maritime regulations (IMO, SOLAS, MARPOL) when applicable
- Be professional and helpful
- If unsure, acknowledge limitations and suggest consulting certified professionals
- Prioritize safety in all recommendations

Always maintain a professional, knowledgeable tone suitable for maritime industry professionals."""
            existing.knowledge_context = """Rapas Marine Engineering specializes in:
- Comprehensive marine engineering services
- Ship design and consultation
- Marine system installation and commissioning
- Vessel maintenance and repair services
- Technical support for shipowners and operators
- Marine electrical and automation systems
- Propulsion system optimization
- Energy efficiency solutions for vessels
- Maritime safety and compliance consulting

Service areas: Commercial shipping, offshore vessels, naval ships, and specialized marine equipment.
Operating globally with expertise in modern and legacy marine systems."""
            db.commit()
            print("✓ Rapas prompt and knowledge context updated.")
            return existing
        
        # Create Rapas tenant
        rapas = Tenant(
            id=str(uuid.uuid4()),
            name="Rapas Marine Engineering",
            slug="rapas",
            domain="rapas.com",
            
            # Marine engineering specific prompt
            prompt_template="""You are a professional marine engineering assistant for Rapas Marine Engineering.

Your expertise includes:
- Ship design and naval architecture
- Marine propulsion systems (diesel engines, gas turbines, electric propulsion)
- Marine electrical systems and automation
- Ship maintenance and repair
- Maritime safety and regulations
- Offshore engineering
- Ship classification and certification

Guidelines:
- Provide accurate, technical information relevant to marine engineering
- Use industry-standard terminology
- Reference relevant maritime regulations (IMO, SOLAS, MARPOL) when applicable
- Be professional and helpful
- If unsure, acknowledge limitations and suggest consulting certified professionals
- Prioritize safety in all recommendations

Always maintain a professional, knowledgeable tone suitable for maritime industry professionals.""",
            
            # Domain knowledge context
            knowledge_context="""Rapas Marine Engineering specializes in:
- Comprehensive marine engineering services
- Ship design and consultation
- Marine system installation and commissioning
- Vessel maintenance and repair services
- Technical support for shipowners and operators
- Marine electrical and automation systems
- Propulsion system optimization
- Energy efficiency solutions for vessels
- Maritime safety and compliance consulting

Service areas: Commercial shipping, offshore vessels, naval ships, and specialized marine equipment.
Operating globally with expertise in modern and legacy marine systems.""",
            
            # Safety guardrails
            guardrails={
                "max_response_length": 1500,
                "forbidden_topics": [
                    "medical advice",
                    "legal advice without disclaimer",
                    "unauthorized modifications that violate safety standards"
                ],
                "required_disclaimers": [
                    "For critical safety decisions, always consult certified marine engineers",
                    "Comply with local maritime regulations and classification society rules"
                ]
            },
            
            # LLM configuration - optimized for technical responses
            model_name="llama-3.1-8b-instant",  # Groq free tier model
            temperature=0.3,  # Lower temperature for more precise technical responses
            max_tokens=800,  # Adequate for detailed technical explanations
            
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
        print(f"  Model: {rapas.model_name}")
        print(f"  Temperature: {rapas.temperature}")
        print(f"  Max Tokens: {rapas.max_tokens}")
        print("\n✓ Rapas is ready to use!")
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
