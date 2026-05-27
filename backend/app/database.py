"""
Database connection and session management
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from app.config import settings


def _is_sql_echo_enabled() -> bool:
    """SQL echo should be opt-in to avoid high-volume logs in normal operation."""
    return os.getenv("SQL_ECHO", "false").strip().lower() == "true"


# Create engine with connection pooling
# Using QueuePool with sensible defaults for production
# pool_size: number of connections to keep open
# max_overflow: additional connections allowed when pool is full
# pool_timeout: seconds to wait before giving up on getting connection
# pool_recycle: seconds after which connections are recycled (prevents stale connections)
engine = create_engine(
    settings.database_url,
    echo=_is_sql_echo_enabled(),
    poolclass=QueuePool,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
    pool_pre_ping=True,  # Check connection validity before using
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Get database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
