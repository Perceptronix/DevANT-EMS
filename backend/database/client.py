"""
Database client for Supabase PostgreSQL connection.

Provides connection pooling, session management, and initialization.
"""
import os
import logging
from typing import Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from functools import lru_cache

from database.models import Base

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Database client for managing Supabase PostgreSQL connections."""

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize database client.

        Args:
            database_url: PostgreSQL connection string
                         (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:password@localhost:5432/postgres"
        )

        # Validate URL
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable not set and no URL provided")

        # Create engine with connection pooling
        self.engine = create_engine(
            self.database_url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,  # Verify connections before using
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        )

        # Enable pgvector
        self._enable_pgvector()

        # Create session factory
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        logger.info(f"Database client initialized: {self._mask_url(self.database_url)}")

    def _enable_pgvector(self):
        """Enable pgvector extension."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
                logger.info("pgvector extension enabled")
        except Exception as e:
            logger.warning(f"Could not enable pgvector: {e}")

    def init_db(self):
        """Create all tables."""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def health_check(self) -> bool:
        """Check if database is accessible."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
                return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def close(self):
        """Close the database connection pool."""
        self.engine.dispose()
        logger.info("Database connections closed")

    @staticmethod
    def _mask_url(url: str) -> str:
        """Mask sensitive parts of database URL for logging."""
        if "@" in url:
            parts = url.split("@")
            return f"{parts[0][:30]}...@{parts[1]}"
        return url[:40] + "..."


@lru_cache(maxsize=1)
def get_database_client() -> DatabaseClient:
    """Get or create the singleton database client."""
    return DatabaseClient()


def get_db_session() -> Session:
    """Get a database session for dependency injection."""
    client = get_database_client()
    session = client.get_session()
    try:
        yield session
    finally:
        session.close()
