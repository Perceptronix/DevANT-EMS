"""
Temporal Memory Engine — track and learn from recurring incidents.

Maintains operational memory of:
- Historical incident patterns
- Recurring failures and their typical resolution times (MTTR)
- Escalation chains and relationships
- Service-to-service incident propagation patterns
- Rollback success rates post-incident

Answers questions like:
- "Has this error happened before?"
- "How long did it take to fix last time?"
- "Did it lead to cascading failures?"
- "What services did it affect?"
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TemporalIncidentMemory:
    """A single historical incident stored in memory."""
    incident_id: str
    timestamp: str  # ISO-8601 UTC
    error_signatures: List[str]
    root_cause: str
    affected_services: List[str]
    severity: str
    status: str  # "resolved" | "escalated" | "ongoing"
    resolution_time_minutes: Optional[int] = None
    resolution_method: Optional[str] = None
    related_deployments: List[str] = field(default_factory=list)
    cascading_failures: List[str] = field(default_factory=list)
    mttr_minutes: int = 0
    occurrence_count: int = 1  # How many times this pattern recurred
    last_occurrence: str = ""
    confidence: float = 1.0


@dataclass
class IncidentPattern:
    """A recurring incident pattern."""
    pattern_id: str
    error_signature_pattern: str  # Common substring or regex
    affected_service_pattern: str
    occurrence_count: int
    first_seen: str
    last_seen: str
    average_mttr_minutes: float
    success_resolution_rate: float
    known_fixes: List[str] = field(default_factory=list)
    escalation_probability: float = 0.0


class TemporalMemoryEngine:
    """
    Learns operational patterns from historical incidents.
    
    Helps answer:
    - "Is this a repeat incident?"
    - "What's the typical fix time?"
    - "Does this usually escalate?"
    - "Should we escalate now?"
    """

    def __init__(self, memory_file: Optional[str] = None):
        self.memory_file = Path(memory_file or "data/incident_graph.json")
        self._incidents: Dict[str, TemporalIncidentMemory] = {}
        self._patterns: Dict[str, IncidentPattern] = {}
        self._lock = threading.Lock()
        
        # Load existing memory
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_incident(
        self,
        incident: Dict[str, Any],
        resolution_time_minutes: Optional[int] = None,
        resolution_method: Optional[str] = None,
    ) -> str:
        """
        Record a new incident in temporal memory.
        
        Input incident should have:
        {
            incident_id, timestamp, error_signatures, root_cause,
            affected_services, severity, status
        }
        
        Returns incident ID.
        """
        with self._lock:
            incident_id = incident.get("incident_id", f"inc_{datetime.now(timezone.utc).timestamp()}")
            
            # Check for recurrence
            occurrence_count = self._find_recurrence_count(incident)
            
            memory = TemporalIncidentMemory(
                incident_id=incident_id,
                timestamp=incident.get("timestamp", datetime.now(timezone.utc).isoformat()),
                error_signatures=incident.get("error_signatures", []),
                root_cause=incident.get("root_cause", "Unknown"),
                affected_services=incident.get("affected_services", []),
                severity=incident.get("severity", "S4"),
                status=incident.get("status", "open"),
                resolution_time_minutes=resolution_time_minutes,
                resolution_method=resolution_method,
                related_deployments=incident.get("related_deployments", []),
                cascading_failures=incident.get("cascading_failures", []),
                occurrence_count=occurrence_count,
                last_occurrence=datetime.now(timezone.utc).isoformat(),
                confidence=incident.get("confidence", 0.9),
            )
            
            self._incidents[incident_id] = memory
            self._save()
            
            logger.info(f"Recorded incident {incident_id} (occurrence #{occurrence_count})")
            
            return incident_id

    def find_similar_historical_incident(
        self,
        cluster: Dict[str, Any],
    ) -> Optional[TemporalIncidentMemory]:
        """
        Find a similar historical incident.
        
        Input cluster should have:
        {
            error_signatures, root_cause, affected_services
        }
        
        Returns the most similar historical incident or None.
        """
        with self._lock:
            current_sigs = set(cluster.get("error_signatures", []))
            current_services = set(cluster.get("affected_services", []))
            
            best_match: Optional[TemporalIncidentMemory] = None
            best_score = 0.0
            
            for incident in self._incidents.values():
                # Calculate similarity
                hist_sigs = set(incident.error_signatures)
                hist_services = set(incident.affected_services)
                
                sig_overlap = len(current_sigs & hist_sigs) / max(len(current_sigs | hist_sigs), 1)
                svc_overlap = len(current_services & hist_services) / max(len(current_services | hist_services), 1)
                
                score = (sig_overlap * 0.6) + (svc_overlap * 0.4)
                
                if score > best_score:
                    best_score = score
                    best_match = incident
            
            if best_score > 0.4:  # Similarity threshold
                return best_match
            return None

    def get_resolution_time_estimate(
        self,
        error_signature: str,
        service: Optional[str] = None,
    ) -> Optional[int]:
        """
        Get typical resolution time (MTTR) for this type of error.
        
        Returns MTTR in minutes or None if no history.
        """
        with self._lock:
            matching_incidents = [
                inc for inc in self._incidents.values()
                if error_signature in inc.error_signatures
                and (not service or service in inc.affected_services)
                and inc.resolution_time_minutes
            ]
            
            if not matching_incidents:
                return None
            
            # Average MTTR
            mttr = sum(
                inc.resolution_time_minutes or 0
                for inc in matching_incidents
            ) / len(matching_incidents)
            
            return int(mttr)

    def get_known_fixes(
        self,
        error_signature: str,
    ) -> List[str]:
        """Get known resolutions for this error."""
        with self._lock:
            fixes = []
            for inc in self._incidents.values():
                if error_signature in inc.error_signatures and inc.resolution_method:
                    fixes.append(inc.resolution_method)
            
            # Deduplicate and return most common
            return list(dict.fromkeys(fixes))  # Preserve order, remove dupes

    def estimate_escalation_probability(
        self,
        cluster: Dict[str, Any],
    ) -> float:
        """
        Estimate probability that this incident will escalate.
        
        Factors:
        - Historical escalation rate for this signature
        - Current severity
        - Service criticality
        """
        with self._lock:
            error_sigs = cluster.get("error_signatures", [])
            
            # Find historical escalations for similar errors
            escalated = [
                inc for inc in self._incidents.values()
                if any(sig in inc.error_signatures for sig in error_sigs)
                and inc.status == "escalated"
            ]
            
            total = [
                inc for inc in self._incidents.values()
                if any(sig in inc.error_signatures for sig in error_sigs)
            ]
            
            if not total:
                # Default: high-severity incidents have higher escalation prob
                severity = cluster.get("severity", "S4")
                return 0.7 if severity == "S1" else 0.4 if severity == "S2" else 0.1
            
            escalation_rate = len(escalated) / len(total)
            
            return min(1.0, escalation_rate + 0.1)  # Add buffer

    def mark_incident_resolved(
        self,
        incident_id: str,
        resolution_time_minutes: int,
        resolution_method: str,
    ):
        """Mark an incident as resolved and update MTTR."""
        with self._lock:
            if incident_id in self._incidents:
                incident = self._incidents[incident_id]
                incident.status = "resolved"
                incident.resolution_time_minutes = resolution_time_minutes
                incident.resolution_method = resolution_method
                incident.mttr_minutes = resolution_time_minutes
                self._save()

    def extract_patterns(self) -> List[IncidentPattern]:
        """
        Extract recurring patterns from incident history.
        
        Returns list of patterns with statistics.
        """
        with self._lock:
            # Group incidents by signature
            sig_groups: Dict[str, List[TemporalIncidentMemory]] = {}
            
            for incident in self._incidents.values():
                # Use first signature as key
                key = incident.error_signatures[0] if incident.error_signatures else "unknown"
                if key not in sig_groups:
                    sig_groups[key] = []
                sig_groups[key].append(incident)
            
            patterns = []
            
            for sig, incidents in sig_groups.items():
                if len(incidents) < 2:
                    continue  # Not a pattern unless it recurred
                
                # Calculate statistics
                resolved = [inc for inc in incidents if inc.status == "resolved"]
                escalated = [inc for inc in incidents if inc.status == "escalated"]
                
                mttr_times = [inc.mttr_minutes for inc in resolved if inc.mttr_minutes > 0]
                avg_mttr = sum(mttr_times) / len(mttr_times) if mttr_times else 0.0
                
                success_rate = len(resolved) / len(incidents) if incidents else 0.0
                escalation_prob = len(escalated) / len(incidents) if incidents else 0.0
                
                # Collect fixes
                fixes = list(set(
                    inc.resolution_method for inc in incidents
                    if inc.resolution_method
                ))
                
                pattern = IncidentPattern(
                    pattern_id=f"pattern_{sig[:20]}",
                    error_signature_pattern=sig,
                    affected_service_pattern=",".join(
                        set(svc for inc in incidents for svc in inc.affected_services)
                    ),
                    occurrence_count=len(incidents),
                    first_seen=min(inc.timestamp for inc in incidents),
                    last_seen=max(inc.timestamp for inc in incidents),
                    average_mttr_minutes=avg_mttr,
                    success_resolution_rate=success_rate,
                    known_fixes=fixes,
                    escalation_probability=escalation_prob,
                )
                
                patterns.append(pattern)
            
            return patterns

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_recurrence_count(self, incident: Dict[str, Any]) -> int:
        """Find how many times this incident has occurred."""
        error_sigs = set(incident.get("error_signatures", []))
        affected_services = set(incident.get("affected_services", []))
        
        count = 1
        for hist_inc in self._incidents.values():
            hist_sigs = set(hist_inc.error_signatures)
            hist_services = set(hist_inc.affected_services)
            
            # Check for overlap
            if error_sigs & hist_sigs and affected_services & hist_services:
                count += 1
        
        return count

    def _save(self):
        """Persist incident memory to disk."""
        try:
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "incidents": {
                    k: asdict(v) for k, v in self._incidents.items()
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            
            with open(self.memory_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save temporal memory: {e}")

    def _load(self):
        """Load incident memory from disk."""
        try:
            if not self.memory_file.exists():
                return
            
            with open(self.memory_file) as f:
                data = json.load(f)
            
            for inc_id, inc_data in data.get("incidents", {}).items():
                self._incidents[inc_id] = TemporalIncidentMemory(**inc_data)
        except Exception as e:
            logger.warning(f"Failed to load temporal memory: {e}")
