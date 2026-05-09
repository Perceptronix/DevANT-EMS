"""
Base repository with common CRUD operations.

All specific repositories inherit from this class.
"""
import logging
from typing import TypeVar, Generic, Type, List, Optional, Any, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations."""

    def __init__(self, db: Session, model: Type[T]):
        """
        Initialize repository.

        Args:
            db: SQLAlchemy session
            model: SQLAlchemy model class
        """
        self.db = db
        self.model = model

    def create(self, **kwargs) -> T:
        """Create and save a new record."""
        try:
            record = self.model(**kwargs)
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            logger.debug(f"Created {self.model.__name__}")
            return record
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating {self.model.__name__}: {e}")
            raise

    def get_by_id(self, id: Any) -> Optional[T]:
        """Get record by ID."""
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> List[T]:
        """Get all records with pagination."""
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def update(self, id: Any, **kwargs) -> Optional[T]:
        """Update a record by ID."""
        try:
            record = self.get_by_id(id)
            if not record:
                return None

            for key, value in kwargs.items():
                if hasattr(record, key):
                    setattr(record, key, value)

            self.db.commit()
            self.db.refresh(record)
            logger.debug(f"Updated {self.model.__name__} {id}")
            return record
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating {self.model.__name__}: {e}")
            raise

    def delete(self, id: Any) -> bool:
        """Delete a record by ID."""
        try:
            record = self.get_by_id(id)
            if not record:
                return False

            self.db.delete(record)
            self.db.commit()
            logger.debug(f"Deleted {self.model.__name__} {id}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting {self.model.__name__}: {e}")
            raise

    def count(self) -> int:
        """Count total records."""
        return self.db.query(self.model).count()

    def bulk_create(self, records: List[Dict[str, Any]]) -> List[T]:
        """Create multiple records."""
        try:
            instances = [self.model(**record) for record in records]
            self.db.add_all(instances)
            self.db.commit()
            logger.debug(f"Bulk created {len(instances)} {self.model.__name__} records")
            return instances
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error bulk creating {self.model.__name__}: {e}")
            raise

    def exists(self, id: Any) -> bool:
        """Check if record exists."""
        return self.db.query(self.model).filter(self.model.id == id).first() is not None
