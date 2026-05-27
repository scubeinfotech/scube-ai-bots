#!/usr/bin/env python
"""
Initialize admin user for testing
"""
import sys
import os

# Add backend to path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from app.database import SessionLocal, Base, engine
from app.models import AdminUser
from app.services.auth_service import hash_password

# Create tables
Base.metadata.create_all(bind=engine)

# Create default admin
db = SessionLocal()

# Check if admin exists
existing = db.query(AdminUser).first()
if existing:
    print("✅ Admin user already exists")
    db.close()
    sys.exit(0)

# Create default admin
admin = AdminUser(
    username="admin",
    email="admin@llmplatform.local",
    hashed_password=hash_password("admin123")
)

db.add(admin)
db.commit()
db.refresh(admin)

print("✅ Default admin created successfully!")
print(f"   Username: admin")
print(f"   Password: admin123")
print(f"   ID: {admin.id}")

db.close()
