#!/usr/bin/env python3
"""
Safe WhatsApp Schema Fix Script
Adds missing columns to whatsapp_configurations table if they don't exist.
Idempotent - safe to run multiple times.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text, inspect
from app.database import engine, Base

def fix_whatsapp_schema():
    """Add missing columns to whatsapp_configurations table"""
    
    print("=" * 60)
    print("WhatsApp Schema Fix - Adding Missing Columns")
    print("=" * 60)
    
    columns_to_add = [
        ("rate_limit_max_per_minute", "INTEGER", "5"),
        ("cooldown_seconds", "INTEGER", "2"),
        ("response_target_chars", "INTEGER", "300"),
    ]
    
    with engine.connect() as conn:
        # Get existing columns
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'whatsapp_configurations'
        """))
        existing_columns = {row[0] for row in result}
        
        print(f"\nExisting columns: {len(existing_columns)}")
        
        added = 0
        for col_name, col_type, default_val in columns_to_add:
            if col_name in existing_columns:
                print(f"  ✓ Already exists: {col_name}")
            else:
                print(f"  + Adding: {col_name} ({col_type} DEFAULT {default_val})")
                conn.execute(text(f"""
                    ALTER TABLE whatsapp_configurations 
                    ADD COLUMN {col_name} {col_type} DEFAULT {default_val}
                """))
                added += 1
        
        conn.commit()
        
        print(f"\n{'='*60}")
        if added > 0:
            print(f"✓ Fix complete! Added {added} new column(s).")
        else:
            print("✓ All columns already exist. No changes needed.")
        print("=" * 60)
        
        # Verify
        result = conn.execute(text("""
            SELECT column_name, data_type, column_default 
            FROM information_schema.columns 
            WHERE table_name = 'whatsapp_configurations'
            ORDER BY ordinal_position
        """))
        
        print("\nCurrent columns in whatsapp_configurations:")
        for row in result:
            col, dtype, default = row
            default_str = f" DEFAULT {default}" if default else ""
            print(f"  - {col}: {dtype}{default_str}")
        
        return added

if __name__ == "__main__":
    try:
        added = fix_whatsapp_schema()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
