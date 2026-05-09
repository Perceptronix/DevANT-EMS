from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any


class JobState(Enum):
    PENDING = 'PENDING'
    INITIALIZING = 'INITIALIZING'
    INGESTING = 'INGESTING'
    ANALYZING = 'ANALYZING'
    SCORING = 'SCORING'
    FINALIZING = 'FINALIZING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'


# Allowed immutable transitions
_ALLOWED = {
    JobState.PENDING: {JobState.INITIALIZING, JobState.CANCELLED, JobState.FAILED},
    JobState.INITIALIZING: {JobState.INGESTING, JobState.FAILED, JobState.CANCELLED},
    JobState.INGESTING: {JobState.ANALYZING, JobState.FAILED, JobState.CANCELLED},
    JobState.ANALYZING: {JobState.SCORING, JobState.FAILED, JobState.CANCELLED},
    JobState.SCORING: {JobState.FINALIZING, JobState.FAILED, JobState.CANCELLED},
    JobState.FINALIZING: {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED},
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initial_job_record(run_id: str, repo_url: str) -> Dict[str, Any]:
    return {
        'run_id': run_id,
        'repo_url': repo_url,
        'state': JobState.PENDING.value,
        'transitions': [{'state': JobState.PENDING.value, 'at': _now_iso()}],
        'result_snapshot': None,
        'error': None,
    }


def validate_transition(current: str, target: str) -> bool:
    try:
        cur = JobState(current)
        tgt = JobState(target)
    except Exception:
        return False
    return tgt in _ALLOWED.get(cur, set())


def transition(record: Dict[str, Any], target: str, note: str | None = None) -> Dict[str, Any]:
    """Return new record dict with transition applied immutably.
    Raises ValueError on invalid transition.
    """
    cur = record.get('state')
    if not validate_transition(cur, target):
        raise ValueError(f'invalid transition {cur} -> {target}')

    new = dict(record)
    new['state'] = target
    trans = list(new.get('transitions', []))
    t = {'state': target, 'at': _now_iso()}
    if note:
        t['note'] = note
    trans.append(t)
    new['transitions'] = trans
    return new


def finalize_with_result(record: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Immutable finalize: set COMPLETED and snapshot result."""
    new = dict(record)
    new['state'] = JobState.COMPLETED.value
    trans = list(new.get('transitions', []))
    trans.append({'state': JobState.COMPLETED.value, 'at': _now_iso()})
    new['transitions'] = trans
    # store immutable snapshot (deep copy by serializing)
    import json
    new['result_snapshot'] = json.loads(json.dumps(result))
    return new


def fail_with_error(record: Dict[str, Any], error: str) -> Dict[str, Any]:
    new = dict(record)
    new['state'] = JobState.FAILED.value
    trans = list(new.get('transitions', []))
    trans.append({'state': JobState.FAILED.value, 'at': _now_iso(), 'error': error})
    new['transitions'] = trans
    new['error'] = error
    return new


def cancel(record: Dict[str, Any], reason: str | None = None) -> Dict[str, Any]:
    new = dict(record)
    new['state'] = JobState.CANCELLED.value
    trans = list(new.get('transitions', []))
    t = {'state': JobState.CANCELLED.value, 'at': _now_iso()}
    if reason:
        t['reason'] = reason
    trans.append(t)
    new['transitions'] = trans
    return new
