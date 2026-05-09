from __future__ import annotations

import sys
from importlib import util
from pathlib import Path

_engine_path = Path(__file__).parent / "datasets" / "replay_engine.py"
_spec = util.spec_from_file_location("devant_local_replay_engine", _engine_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load replay engine from {_engine_path}")

_module = util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

load_incident_corpus = _module.load_incident_corpus
IncidentReplayEngine = _module.IncidentReplayEngine
ReplayResult = _module.ReplayResult

__all__ = ["load_incident_corpus", "IncidentReplayEngine", "ReplayResult"]