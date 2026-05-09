"""
JSON-based state management for error tracking.

Provides persistence for error signatures and mutes without requiring
a database. State is stored in JSON files in the data/ directory.

Uses file locking to handle concurrent access safely.
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

try:
    from filelock import FileLock
except ImportError:
    # Fallback if filelock not installed
    class FileLock:
        def __init__(self, path):
            self.path = path
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

from schemas import PreviousErrorState

logger = logging.getLogger(__name__)

# Default data directory
DATA_DIR = Path(__file__).parent / "data"


class StateManager:
    """
    JSON-based state persistence for error monitoring.
    
    Manages two files:
    - error_signatures.json: Tracks error patterns and their history
    - mutes.json: Tracks active mutes
    
    Thread-safe through file locking.
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize state manager.
        
        Args:
            data_dir: Directory to store state files (defaults to backend/data/)
        """
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.signatures_file = self.data_dir / "error_signatures.json"
        self.mutes_file = self.data_dir / "mutes.json"
        self.kv_file = self.data_dir / "kv_store.json"
        
        self._ensure_files()
        logger.info(f"State manager initialized with data dir: {self.data_dir}")
    
    def _ensure_files(self):
        """Ensure state files exist with valid JSON."""
        for file_path in [self.signatures_file, self.mutes_file]:
            if not file_path.exists():
                file_path.write_text("{}")
                logger.info(f"Created state file: {file_path}")
        if not self.kv_file.exists():
            self.kv_file.write_text("{}")
            logger.info(f"Created kv store file: {self.kv_file}")
    
    def _read_json(self, path: Path) -> dict:
        """Read JSON file with locking."""
        lock_path = f"{path}.lock"
        with FileLock(lock_path):
            try:
                content = path.read_text()
                return json.loads(content) if content.strip() else {}
            except (json.JSONDecodeError, FileNotFoundError) as e:
                logger.warning(f"Error reading {path}: {e}, attempting recovery")
                # Backup corrupted file
                try:
                    bak = path.with_suffix(path.suffix + f".bak.{datetime.utcnow().timestamp()}")
                    path.replace(bak)
                    logger.warning(f"Backed up corrupted state to {bak}")
                except Exception:
                    logger.exception("Failed to backup corrupted state file")
                # Create a fresh empty file
                try:
                    path.write_text("{}")
                except Exception:
                    logger.exception("Failed to create fresh state file after corruption")
                return {}
    
    def _write_json(self, path: Path, data: dict):
        """Write JSON file with locking."""
        lock_path = f"{path}.lock"
        with FileLock(lock_path):
            # Atomic write: write to temp file then replace
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            try:
                tmp.replace(path)
            except Exception:
                # Fallback to overwrite
                path.write_text(json.dumps(data, indent=2, default=str))

    # =========================================================================
    # Generic KV store helpers (for tests/compatibility)
    # =========================================================================

    def update(self, key: str, value: Dict[str, Any]):
        """Generic key/value update persisted to kv_store.json."""
        data = self._read_json(self.kv_file)
        data[key] = value
        self._write_json(self.kv_file, data)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        data = self._read_json(self.kv_file)
        return data.get(key)

    def persist(self):
        """Ensure all state files are flushed and consistent (noop for JSON store)."""
        # Files are written synchronously; this is a semantic hook for interfaces
        for p in [self.signatures_file, self.mutes_file, self.kv_file]:
            if not p.exists():
                p.write_text("{}")
    
    # =========================================================================
    # Error Signatures
    # =========================================================================
    
    def get_signature(self, signature: str) -> Optional[PreviousErrorState]:
        """
        Get previous state for an error signature.
        
        Args:
            signature: The error signature to look up
            
        Returns:
            PreviousErrorState or None if not found
        """
        data = self._read_json(self.signatures_file)
        
        if signature not in data:
            return None
        
        try:
            entry = data[signature]
            return PreviousErrorState(
                signature=signature,
                first_seen=self._parse_datetime(entry.get("first_seen")),
                last_seen=self._parse_datetime(entry.get("last_seen")),
                last_alerted=self._parse_datetime(entry.get("last_alerted")),
                times_seen=entry.get("times_seen", 0),
                linear_issue_id=entry.get("linear_issue_id"),
                linear_issue_status=entry.get("linear_issue_status"),
                linear_issue_url=entry.get("linear_issue_url"),
                slack_thread_ts=entry.get("slack_thread_ts"),
                muted_until=self._parse_datetime(entry.get("muted_until")),
                muted_by=entry.get("muted_by"),
                mute_reason=entry.get("mute_reason"),
                last_severity=entry.get("last_severity"),
                last_summary=entry.get("last_summary"),
            )
        except Exception as e:
            logger.error(f"Error parsing signature state: {e}")
            return None
    
    def upsert_signature(self, signature: str, updates: Dict[str, Any]):
        """
        Create or update an error signature.
        
        Args:
            signature: The error signature
            updates: Fields to update
        """
        data = self._read_json(self.signatures_file)
        now = datetime.utcnow().isoformat()
        
        if signature not in data:
            data[signature] = {
                "signature": signature,
                "first_seen": now,
                "times_seen": 0,
            }
            logger.debug(f"Created new signature: {signature[:50]}...")
        
        # Update fields
        data[signature].update(updates)
        data[signature]["last_seen"] = now
        data[signature]["times_seen"] = data[signature].get("times_seen", 0) + 1
        
        self._write_json(self.signatures_file, data)
        logger.debug(f"Updated signature: {signature[:50]}...")
    
    def record_alert(self, signature: str, severity: str, summary: Dict[str, Any] = None):
        """
        Record that an alert was sent for this signature.
        
        Args:
            signature: The error signature
            severity: Severity level
            summary: Analysis summary
        """
        self.upsert_signature(signature, {
            "last_alerted": datetime.utcnow().isoformat(),
            "last_severity": severity,
            "last_summary": summary,
        })
    
    def update_linear_ticket(
        self, 
        signature: str, 
        issue_id: str, 
        status: str,
        url: Optional[str] = None
    ):
        """
        Update Linear ticket tracking for a signature.
        
        Args:
            signature: The error signature
            issue_id: Linear issue ID
            status: Ticket status
            url: Ticket URL
        """
        updates = {
            "linear_issue_id": issue_id,
            "linear_issue_status": status,
        }
        if url:
            updates["linear_issue_url"] = url
        
        self.upsert_signature(signature, updates)
        logger.info(f"Updated Linear ticket for {signature[:30]}...: {issue_id} ({status})")
    
    def update_slack_thread(self, signature: str, thread_ts: str):
        """
        Update Slack thread tracking for a signature.
        
        Args:
            signature: The error signature
            thread_ts: Slack thread timestamp
        """
        self.upsert_signature(signature, {"slack_thread_ts": thread_ts})
    
    def get_all_signatures(self) -> Dict[str, Dict[str, Any]]:
        """Get all stored signatures (for debugging/admin)."""
        sig_repo, session = self._get_repo(SignatureStateRepository)
        try:
            all_sigs = sig_repo.get_all() or []
            return {s.signature: s.data for s in all_sigs}
        finally:
            session.close()
    
    # =========================================================================
    # Mutes
    # =========================================================================
    
    def get_active_mutes(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all currently active mutes.
        
        Returns:
            Dict mapping signature patterns to mute info
        """
        data = self._read_json(self.mutes_file)
        now = datetime.utcnow()
        
        active = {}
        for sig, mute_info in data.items():
            muted_until = self._parse_datetime(mute_info.get("muted_until"))
            if muted_until and muted_until > now:
                active[sig] = mute_info
        
        return active
    
    def add_mute(
        self, 
        signature: str, 
        duration_hours: int, 
        muted_by: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """
        Mute an error signature for a duration.
        
        Args:
            signature: The error signature (or pattern) to mute
            duration_hours: How long to mute
            muted_by: Who initiated the mute
            reason: Why it was muted
        """
        data = self._read_json(self.mutes_file)
        
        muted_until = datetime.utcnow() + timedelta(hours=duration_hours)
        
        data[signature] = {
            "signature": signature,
            "muted_until": muted_until.isoformat(),
            "muted_at": datetime.utcnow().isoformat(),
            "muted_by": muted_by,
            "reason": reason,
            "duration_hours": duration_hours,
        }
        
        self._write_json(self.mutes_file, data)
        logger.info(f"Muted error for {duration_hours}h: {signature[:50]}...")
        
        # Also update the signature record
        self.upsert_signature(signature, {
            "muted_until": muted_until.isoformat(),
            "muted_by": muted_by,
            "mute_reason": reason,
        })
    
    def remove_mute(self, signature: str):
        """
        Remove a mute for a signature.
        
        Args:
            signature: The error signature to unmute
        """
        data = self._read_json(self.mutes_file)
        
        if signature in data:
            del data[signature]
            self._write_json(self.mutes_file, data)
            logger.info(f"Removed mute: {signature[:50]}...")
        
        # Also update signature record
        self.upsert_signature(signature, {
            "muted_until": None,
            "muted_by": None,
            "mute_reason": None,
        })
    
    def is_muted(self, signature: str) -> bool:
        """
        Check if a signature is currently muted.
        
        Note: This is an exact match. For semantic matching,
        use the semantic_matcher module.
        
        Args:
            signature: The error signature to check
            
        Returns:
            True if muted
        """
        active_mutes = self.get_active_mutes()
        return signature in active_mutes
    
    def get_mute_info(self, signature: str) -> Optional[Dict[str, Any]]:
        """
        Get mute information for a signature.
        
        Args:
            signature: The error signature
            
        Returns:
            Mute info dict or None
        """
        active_mutes = self.get_active_mutes()
        return active_mutes.get(signature)
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from string or return None."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            # Handle ISO format with or without timezone
            if isinstance(value, str):
                # Remove 'Z' suffix if present
                value = value.replace('Z', '+00:00')
                # Try parsing
                if '+' in value or value.endswith('Z'):
                    return datetime.fromisoformat(value.replace('+00:00', ''))
                return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
        return None
    
    def clear_all(self):
        """Clear all state (for testing)."""
        self._write_json(self.signatures_file, {})
        self._write_json(self.mutes_file, {})
        logger.warning("Cleared all state data")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored state."""
        signatures = self._read_json(self.signatures_file)
        mutes = self.get_active_mutes()
        
        return {
            "total_signatures": len(signatures),
            "active_mutes": len(mutes),
            "signatures_with_tickets": sum(
                1 for s in signatures.values() 
                if s.get("linear_issue_id")
            ),
            "data_dir": str(self.data_dir),
        }


# -----------------------------------------------------------------------------
# DB-backed State Manager (Phase 2 compatibility)
# -----------------------------------------------------------------------------
try:
    from config import get_config
    from database.client import get_database_client
    from database.repositories.entities import SignatureStateRepository, ErrorClusterRepository, MuteRepository
    DB_SUPPORT = True
except Exception:
    DB_SUPPORT = False


class DBStateManager:
    """A compatibility state manager that stores signature state in the database.

    This implements the same interface as `StateManager` used across the codebase,
    but persists signature data in `signature_states` table when Supabase/DB is
    configured. It falls back to JSON-based `StateManager` for any unsupported
    operations or when DB is not available.
    """

    def __init__(self):
        if not DB_SUPPORT:
            raise RuntimeError("Database support not available in this environment")
        self.config = get_config()
        self.db_client = get_database_client()
        # session per operation

    def _get_repo(self, repo_cls):
        session = self.db_client.get_session()
        return repo_cls(session), session

    def get_signature(self, signature: str) -> Optional[PreviousErrorState]:
        repo, session = self._get_repo(SignatureStateRepository)
        try:
            data = repo.get(signature)
            if not data:
                return None
            # Build PreviousErrorState from stored JSON
            return PreviousErrorState(**data)
        finally:
            session.close()

    def upsert_signature(self, signature: str, updates: Dict[str, Any]):
        repo, session = self._get_repo(SignatureStateRepository)
        try:
            existing = repo.get(signature) or {}
            existing.update(updates)
            logger.info(f"DBStateManager.upsert_signature: upserting signature={signature} updates={updates}")
            result = repo.upsert(signature, existing)
            logger.info(f"DBStateManager.upsert_signature: upsert complete for signature={signature}")
            return result
        finally:
            session.close()

    def get_active_mutes(self) -> Dict[str, Any]:
        repo, session = self._get_repo(MuteRepository)
        try:
            active = repo.get_active()
            # Convert list of Mute ORM into dict keyed by cluster_id/signature if available
            return {str(m.cluster_id): m.to_dict() for m in active}
        finally:
            session.close()

    def get_mute_info(self, signature: str) -> Optional[Dict[str, Any]]:
        # Signature-based mute lookup stored in signature_states, fall back to mutes
        sig_repo, session = self._get_repo(SignatureStateRepository)
        try:
            data = sig_repo.get(signature)
            if data and data.get("muted_until"):
                return data
        finally:
            session.close()
        # Fallback: try mutes by cluster id
        return None

    def is_muted(self, signature: str) -> bool:
        """Check if a signature is currently muted."""
        active_mutes = self.get_active_mutes()
        # Check both signature-based and cluster_id-based mutes
        if signature in active_mutes:
            return True
        # Also check if mute_until is in the signature data
        mute_info = self.get_mute_info(signature)
        if mute_info:
            muted_until_str = mute_info.get("muted_until")
            if muted_until_str:
                try:
                    muted_until = datetime.fromisoformat(muted_until_str.replace('Z', '+00:00').replace('+00:00', ''))
                    if muted_until > datetime.utcnow():
                        return True
                except (ValueError, TypeError):
                    pass
        return False

    def add_mute(self, signature: str, duration_hours: int, muted_by: Optional[str] = None, reason: Optional[str] = None):
        """Mute a signature for a duration."""
        muted_until = datetime.utcnow() + timedelta(hours=duration_hours)
        self.upsert_signature(signature, {
            "muted_until": muted_until.isoformat(),
            "muted_by": muted_by,
            "mute_reason": reason,
        })

    def remove_mute(self, signature: str):
        """Remove mute from a signature."""
        self.upsert_signature(signature, {
            "muted_until": None,
            "muted_by": None,
            "mute_reason": None,
        })

    def record_alert(self, signature: str, severity: str, summary: Dict[str, Any] = None):
        """Record that an alert was sent for this signature."""
        self.upsert_signature(signature, {
            "last_alerted": datetime.utcnow().isoformat(),
            "last_severity": severity,
            "last_summary": summary,
        })

    def update_linear_ticket(self, signature: str, issue_id: str, status: str, url: Optional[str] = None):
        """Update Linear ticket tracking for a signature."""
        updates = {
            "linear_issue_id": issue_id,
            "linear_issue_status": status,
        }
        if url:
            updates["linear_issue_url"] = url
        self.upsert_signature(signature, updates)

    def update_slack_thread(self, signature: str, thread_ts: str):
        """Update Slack thread tracking for a signature."""
        self.upsert_signature(signature, {"slack_thread_ts": thread_ts})

    def get_all_signatures(self) -> Dict[str, Dict[str, Any]]:
        """Get all stored signatures."""
        sig_repo, session = self._get_repo(SignatureStateRepository)
        try:
            all_sigs = sig_repo.get_all()
            return {s.id: s.to_dict() for s in all_sigs}
        finally:
            session.close()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Generic key/value get."""
        sig_repo, session = self._get_repo(SignatureStateRepository)
        try:
            data = sig_repo.get(key)
            return data
        finally:
            session.close()

    def update(self, key: str, value: Dict[str, Any]):
        # Generic KV update stored in signature_states
        repo, session = self._get_repo(SignatureStateRepository)
        try:
            repo.upsert(key, value)
        finally:
            session.close()

    def persist(self):
        # DB is durable; no-op
        return

    def clear_all(self):
        # For safety, not implemented
        logger.warning("DBStateManager.clear_all() called — operation not supported")

    def get_stats(self) -> Dict[str, Any]:
        # Provide minimal stats
        ec_repo, session = self._get_repo(ErrorClusterRepository)
        try:
            total = ec_repo.count()
        finally:
            session.close()
        return {"total_clusters": total}


# Singleton instance for easy access
_state_manager: Optional[object] = None


def get_state_manager():
    """Return either a DB-backed state manager (when configured) or the JSON-based one."""
    global _state_manager
    if _state_manager is not None:
        return _state_manager

    # Prefer DB-backed state manager when Supabase/DB is configured
    try:
        logger.info(f"get_state_manager: DB_SUPPORT={DB_SUPPORT}")
        if DB_SUPPORT:
            cfg = get_config()
            logger.info(f"get_state_manager: supabase configured={getattr(cfg, 'supabase', None) is not None}, use_supabase={cfg.supabase.use_supabase}")
            if getattr(cfg, "supabase", None) and cfg.supabase.use_supabase:
                try:
                    client = get_database_client()
                    healthy = False
                    try:
                        healthy = client.health_check()
                    except Exception as he:
                        logger.warning(f"get_state_manager: health_check threw: {he}")
                    logger.info(f"get_state_manager: db health_check={healthy}")
                    if healthy:
                        _state_manager = DBStateManager()
                        logger.info("Using DBStateManager for persistence")
                        return _state_manager
                except Exception as e:
                    logger.warning(f"DBStateManager init failed, falling back to JSON: {e}")
    except Exception:
        # Ignore any config/db errors and fallback
        pass

    _state_manager = StateManager()
    return _state_manager
