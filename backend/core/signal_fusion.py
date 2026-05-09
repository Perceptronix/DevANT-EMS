"""Multi-signal fusion engine for evidence convergence calibration.

Combines operational signals without artificial inflation:
- regression similarity (stacktrace, semantics)
- temporal correlation (deployment, recurrence window)
- telemetry convergence (same metrics degrading)
- propagation alignment (same service path failing)
- anomaly alignment (metrics spike timing)
- topology consistency (same dependencies affected)
- historical recurrence (prior remediation)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from enum import Enum


class SignalType(Enum):
    """Operational signal types."""
    REGRESSION_SIMILARITY = "regression_similarity"
    TEMPORAL_CORRELATION = "temporal_correlation"
    TELEMETRY_CONVERGENCE = "telemetry_convergence"
    PROPAGATION_ALIGNMENT = "propagation_alignment"
    ANOMALY_ALIGNMENT = "anomaly_alignment"
    TOPOLOGY_CONSISTENCY = "topology_consistency"
    HISTORICAL_RECURRENCE = "historical_recurrence"
    REMEDIATION_SIMILARITY = "remediation_similarity"


@dataclass
class SignalEvidence:
    """Single operational signal with confidence and provenance."""
    signal_type: SignalType
    strength: float  # [0.0, 1.0]
    evidence_source: str  # What produced this signal
    is_strong: bool = False  # True if strength >= 0.7
    is_weak: bool = False   # True if strength <= 0.3
    uncertainty: float = 0.0  # Uncertainty in measurement


@dataclass
class SignalConflict:
    """Detected conflict between signals."""
    signal_a: SignalType
    signal_b: SignalType
    conflict_reason: str
    severity: float  # [0.0, 1.0] how much this reduces confidence


class SignalFusionEngine:
    """Fuse multiple operational signals into calibrated confidence.
    
    Rules:
    - No single signal dominates confidence
    - Confidence emerges from convergence, not from highest signal
    - Conflicts reduce confidence proportionally
    - Sparse evidence increases uncertainty
    - Missing evidence increases uncertainty
    """

    # Baseline weights (will be adjusted by convergence)
    BASE_WEIGHTS = {
        SignalType.REGRESSION_SIMILARITY: 0.25,
        SignalType.TEMPORAL_CORRELATION: 0.20,
        SignalType.TELEMETRY_CONVERGENCE: 0.20,
        SignalType.PROPAGATION_ALIGNMENT: 0.15,
        SignalType.ANOMALY_ALIGNMENT: 0.10,
        SignalType.TOPOLOGY_CONSISTENCY: 0.05,
        SignalType.HISTORICAL_RECURRENCE: 0.03,
        SignalType.REMEDIATION_SIMILARITY: 0.02,
    }

    def __init__(self):
        self.signals: Dict[SignalType, SignalEvidence] = {}
        self.conflicts: List[SignalConflict] = []

    def add_signal(
        self,
        signal_type: SignalType,
        strength: float,
        evidence_source: str,
        uncertainty: float = 0.0,
    ) -> None:
        """Add a single operational signal."""
        strength = max(0.0, min(1.0, strength))  # Clamp to [0, 1]
        uncertainty = max(0.0, min(0.5, uncertainty))  # Uncertainty in [0, 0.5]

        self.signals[signal_type] = SignalEvidence(
            signal_type=signal_type,
            strength=strength,
            evidence_source=evidence_source,
            is_strong=(strength >= 0.7),
            is_weak=(strength <= 0.3),
            uncertainty=uncertainty,
        )

    def detect_conflicts(self) -> List[SignalConflict]:
        """Detect conflicts between signals."""
        conflicts = []

        # Conflict: High regression similarity but weak temporal correlation
        if (self.signals.get(SignalType.REGRESSION_SIMILARITY, SignalEvidence(SignalType.REGRESSION_SIMILARITY, 0, "")).strength >= 0.8
            and self.signals.get(SignalType.TEMPORAL_CORRELATION, SignalEvidence(SignalType.TEMPORAL_CORRELATION, 0, "")).strength <= 0.3):
            conflicts.append(SignalConflict(
                signal_a=SignalType.REGRESSION_SIMILARITY,
                signal_b=SignalType.TEMPORAL_CORRELATION,
                conflict_reason="High similarity but weak temporal correlation suggests different root cause",
                severity=0.2,
            ))

        # Conflict: High telemetry convergence but weak propagation alignment
        if (self.signals.get(SignalType.TELEMETRY_CONVERGENCE, SignalEvidence(SignalType.TELEMETRY_CONVERGENCE, 0, "")).strength >= 0.8
            and self.signals.get(SignalType.PROPAGATION_ALIGNMENT, SignalEvidence(SignalType.PROPAGATION_ALIGNMENT, 0, "")).strength <= 0.3):
            conflicts.append(SignalConflict(
                signal_a=SignalType.TELEMETRY_CONVERGENCE,
                signal_b=SignalType.PROPAGATION_ALIGNMENT,
                conflict_reason="Same metrics fail but propagation patterns differ",
                severity=0.15,
            ))

        # Conflict: Weak signals across the board suggests insufficient evidence
        weak_signal_count = sum(1 for s in self.signals.values() if s.is_weak)
        if len(self.signals) > 0 and weak_signal_count / len(self.signals) > 0.6:
            conflicts.append(SignalConflict(
                signal_a=SignalType.REGRESSION_SIMILARITY,
                signal_b=SignalType.TEMPORAL_CORRELATION,
                conflict_reason="Majority of signals weak - sparse evidence",
                severity=0.3,
            ))

        self.conflicts = conflicts
        return conflicts

    def fuse(self) -> Dict[str, Any]:
        """Fuse signals into calibrated confidence estimate.

        Returns:
        {
            "confidence": float [0.0, 1.0],
            "signal_strength": float,  # Average of all signals
            "convergence_score": float,  # How well signals align
            "uncertainty": float,  # Estimated confidence range
            "sparse_evidence": bool,  # True if < 4 signals
            "conflict_count": int,
            "dominant_signals": [SignalType],
        }
        """
        if not self.signals:
            return {
                "confidence": 0.0,
                "signal_strength": 0.0,
                "convergence_score": 0.0,
                "uncertainty": 0.5,
                "sparse_evidence": True,
                "conflict_count": 0,
                "dominant_signals": [],
                "reason": "No signals provided",
            }

        # Calculate average signal strength
        signal_strengths = [s.strength for s in self.signals.values()]
        avg_signal_strength = sum(signal_strengths) / len(signal_strengths)

        # Calculate convergence: how well signals agree
        convergence_score = self._calculate_convergence(signal_strengths)

        # Detect conflicts
        conflicts = self.detect_conflicts()
        conflict_penalty = sum(c.severity for c in conflicts)

        # Identify dominant signals (strong and convergent)
        dominant_signals = [
            s.signal_type for s in self.signals.values()
            if s.is_strong and s.signal_type in [SignalType.REGRESSION_SIMILARITY, SignalType.TEMPORAL_CORRELATION]
        ]

        # Check for sparse evidence (< 4 signals is sparse)
        is_sparse = len(self.signals) < 4

        # Calculate uncertainty
        avg_uncertainty = sum(s.uncertainty for s in self.signals.values()) / len(self.signals)
        uncertainty = avg_uncertainty + (0.1 if is_sparse else 0.0) + (0.1 if conflicts else 0.0)

        # Base confidence from signal strength and convergence
        base_confidence = (avg_signal_strength * 0.6) + (convergence_score * 0.4)

        # Apply penalties
        conflict_reduced = base_confidence * (1.0 - conflict_penalty)

        # Apply sparsity penalty
        sparsity_penalty = 0.15 if is_sparse else 0.0
        final_confidence = max(0.0, conflict_reduced - sparsity_penalty)

        return {
            "confidence": min(1.0, final_confidence),
            "signal_strength": avg_signal_strength,
            "convergence_score": convergence_score,
            "uncertainty": min(0.5, uncertainty),
            "sparse_evidence": is_sparse,
            "conflict_count": len(conflicts),
            "dominant_signals": dominant_signals,
            "signal_count": len(self.signals),
            "reason": f"{len(self.signals)} signals, convergence={convergence_score:.2f}, conflicts={len(conflicts)}",
        }

    def _calculate_convergence(self, strengths: List[float]) -> float:
        """Calculate how well signals converge.
        
        Convergence is high when:
        - Multiple strong signals (>= 0.7)
        - No outliers (std dev low)
        - Majority of signals above 0.5
        """
        if len(strengths) < 2:
            return strengths[0] if strengths else 0.0

        # Standard deviation as inverse of convergence
        avg = sum(strengths) / len(strengths)
        variance = sum((x - avg) ** 2 for x in strengths) / len(strengths)
        std_dev = variance ** 0.5

        # Convergence = 1 - normalized_std_dev
        # Normalized to [0, 1] where 0.3 std dev = 0 convergence
        normalized_std = min(1.0, std_dev / 0.3)
        convergence = 1.0 - normalized_std

        # Bonus for majority strong signals
        strong_count = sum(1 for x in strengths if x >= 0.7)
        strong_bonus = (strong_count / len(strengths)) * 0.2

        return min(1.0, convergence + strong_bonus)

    def explain(self) -> str:
        """Generate human-readable explanation of fusion result."""
        result = self.fuse()

        lines = [
            f"Confidence: {result['confidence']:.2f} (±{result['uncertainty']:.2f})",
            f"Signals: {result['signal_count']} ({'sparse' if result['sparse_evidence'] else 'adequate'})",
            f"Convergence: {result['convergence_score']:.2f}",
            f"Conflicts: {result['conflict_count']}",
            "",
            "Signal Breakdown:",
        ]

        for sig_type, evidence in sorted(self.signals.items(), key=lambda x: x[1].strength, reverse=True):
            strength_bar = "█" * int(evidence.strength * 10)
            lines.append(f"  {sig_type.value:30s} {strength_bar:10s} {evidence.strength:.2f}")

        if self.conflicts:
            lines.append("")
            lines.append("Conflicts:")
            for conflict in self.conflicts:
                lines.append(f"  {conflict.signal_a.value} vs {conflict.signal_b.value}: {conflict.conflict_reason}")

        return "\n".join(lines)
