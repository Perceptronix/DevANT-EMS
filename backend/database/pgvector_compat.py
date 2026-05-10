"""pgvector compatibility layer.

Expose `Vector(dim)` for models. In Postgres with `pgvector` installed,
return pgvector.sqlalchemy.Vector(dim). In SQLite or when pgvector missing,
fall back to a JSON/Text-backed SQLAlchemy TypeDecorator that stores list[float].

Provides helper `get_vector_type()` for dialect-sensitive construction.
"""
from __future__ import annotations

import json
import typing
from sqlalchemy.types import TypeDecorator, TEXT
import sqlalchemy as sa

try:
    from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB
except Exception:
    _PG_JSONB = None

try:
    from sqlalchemy.dialects.postgresql import UUID as _PG_UUID
except Exception:
    _PG_UUID = None

try:
    import pgvector.sqlalchemy as _pgvector  # type: ignore
    _HAS_PGVECTOR = True
except Exception:
    _pgvector = None
    _HAS_PGVECTOR = False


class _VectorFallback(TypeDecorator):
    impl = TEXT
    cache_ok = True

    def __init__(self, dim: int | None = None, **kw):
        super().__init__(**kw)
        self.dim = dim

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(list(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return json.loads(value)
        except Exception:
            return None

    def copy(self, **kw):
        return _VectorFallback(self.dim)


def Vector(dim: int | None = None):
    """Factory returning appropriate Vector type.

    Use in models: Column(Vector(384))
    """
    if _HAS_PGVECTOR and _pgvector is not None:
        try:
            return _pgvector.Vector(dim)
        except Exception:
            # fall back if pgvector API differs
            return _VectorFallback(dim)
    return _VectorFallback(dim)


def get_vector_type_for_engine(engine, dim: int | None = None):
    """Return a Vector type appropriate for given SQLAlchemy engine.

    Useful when you need to branch on dialect at runtime.
    """
    dialect_name = getattr(engine.dialect, "name", None)
    if dialect_name and dialect_name.startswith("postgres") and _HAS_PGVECTOR:
        return Vector(dim)
    return _VectorFallback(dim)


# JSONB compatibility: TypeDecorator that uses JSONB on Postgres, JSON elsewhere
class JSONBType(TypeDecorator):
    impl = sa.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        name = getattr(dialect, "name", "")
        if name and name.startswith("postgres") and _PG_JSONB is not None:
            return dialect.type_descriptor(_PG_JSONB())
        return dialect.type_descriptor(sa.JSON())


def JSONB():
    return JSONBType()


class UUIDType(TypeDecorator):
    impl = sa.String
    cache_ok = True

    def __init__(self, as_uuid: bool = False, **kw):
        super().__init__(**kw)
        self.as_uuid = as_uuid

    def load_dialect_impl(self, dialect):
        name = getattr(dialect, "name", "")
        if name and name.startswith("postgres") and _PG_UUID is not None:
            return dialect.type_descriptor(_PG_UUID(as_uuid=self.as_uuid))
        return dialect.type_descriptor(sa.String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        # Convert UUID to string for SQLite
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # Return as-is; let the ORM handle UUID conversion if needed
        return value


def UUID(as_uuid: bool = False):
    return UUIDType(as_uuid=as_uuid)
