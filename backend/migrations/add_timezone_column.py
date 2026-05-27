#!/usr/bin/env python3
"""Add timezone column to tenants table."""

import sys
sys.path.insert(0, '/home/sudhakar/New-Projects/centralized-llm-platform/backend')

from app.database import engine
from sqlalchemy import text

def migrate():
    """Add timezone column with default Asia/Singapore."""
    with engine.connect() as conn:
        # Check if column exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'tenants' AND column_name = 'timezone'
        """))
        
        if result.fetchone():
            print("✅ timezone column already exists")
            return
        
        # Add timezone column
        conn.execute(text("""
            ALTER TABLE tenants 
            ADD COLUMN timezone VARCHAR(50) DEFAULT 'Asia/Singapore'
        """))
        
        conn.commit()
        print("✅ Added timezone column with default 'Asia/Singapore'")
        
        # Update existing tenants
        conn.execute(text("""
            UPDATE tenants 
            SET timezone = 'Asia/Singapore' 
            WHERE timezone IS NULL
        """))
        conn.commit()
        print("✅ Updated existing tenants with default timezone")

if __name__ == "__main__":
    migrate()
