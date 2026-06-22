from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict


@dataclass
class ReliabilityMetrics:
    model: str
    benchmark_status: str
    total_workflows: int = 0
    successful_workflows: int = 0
    failed_workflows: int = 0
    retries: int = 0
    rollbacks: int = 0
    escalations: int = 0
    stops: int = 0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    retry_rate: float = 0.0
    recovery_rate: float = 0.0
    retry_success_rate: float = 0.0
    tool_reliability: float = 0.0
    timeout_rate: float = 0.0
    timeout_score: float = 0.0
    average_confidence: float = 0.0
    confidence_accuracy: float = 0.0
    average_execution_time_ms: float = 0.0
    execution_time_score: float = 0.0
    escalation_rate: float = 0.0
    workflow_completion_rate: float = 0.0
    simulation_success_rate: float = 0.0
    simulation_gap: float = 0.0
    reliability_score_v1: float = 0.0
    reliability_band_v1: str = "Unavailable"
    reliability_score_v2: float = 0.0
    reliability_band_v2: str = "Unavailable"
    data_completeness: float = 0.0
    notes: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def rate(part: float, whole: float) -> float:
    return (part / whole) * 100.0 if whole else 0.0


def reliability_band(score: float) -> str:
    if score >= 90:
        return "Production Ready"
    if score >= 80:
        return "Stable"
    if score >= 60:
        return "Experimental"
    return "Unreliable"


def execution_time_score(average_execution_time_ms: float, target_ms: float = 10000.0) -> float:
    if average_execution_time_ms <= 0:
        return 0.0
    if average_execution_time_ms <= target_ms:
        return 100.0
    return clamp(100.0 - ((average_execution_time_ms - target_ms) / target_ms * 100.0))


def confidence_accuracy_score(average_confidence: float, success_rate_percent: float) -> float:
    confidence = clamp(average_confidence, 0.0, 1.0)
    actual_success = clamp(success_rate_percent, 0.0, 100.0) / 100.0
    return clamp((1.0 - abs(confidence - actual_success)) * 100.0)


def score_v1(metrics: ReliabilityMetrics) -> float:
    failure_rate_score = 100.0 - metrics.failure_rate
    timeout_score_value = 100.0 - metrics.timeout_rate
    escalation_score = 100.0 - metrics.escalation_rate
    score = (
        metrics.success_rate * 0.20
        + failure_rate_score * 0.10
        + metrics.recovery_rate * 0.12
        + metrics.retry_success_rate * 0.08
        + metrics.tool_reliability * 0.12
        + timeout_score_value * 0.10
        + metrics.confidence_accuracy * 0.08
        + metrics.execution_time_score * 0.08
        + escalation_score * 0.05
        + metrics.workflow_completion_rate * 0.07
    )
    return round(clamp(score), 2)


def score_v2(metrics: ReliabilityMetrics) -> float:
    """Validation-adjusted formula.

    V2 reduces overconfidence when some metrics are inferred from aggregate reports
    rather than measured from per-workflow traces. It also penalizes simulation gap.
    """
    failure_rate_score = 100.0 - metrics.failure_rate
    timeout_score_value = 100.0 - metrics.timeout_rate
    escalation_score = 100.0 - metrics.escalation_rate
    base_score = (
        metrics.success_rate * 0.30
        + failure_rate_score * 0.12
        + metrics.recovery_rate * 0.12
        + metrics.retry_success_rate * 0.08
        + metrics.tool_reliability * 0.10
        + timeout_score_value * 0.10
        + metrics.confidence_accuracy * 0.06
        + metrics.execution_time_score * 0.05
        + escalation_score * 0.03
        + metrics.workflow_completion_rate * 0.04
    )
    gap_penalty = min(abs(metrics.simulation_gap) * 1.5, 15.0)
    completeness_multiplier = 0.85 + (clamp(metrics.data_completeness) / 100.0 * 0.15)
    score = (base_score - gap_penalty) * completeness_multiplier
    if metrics.data_completeness < 70:
        score = min(score, 89.0)
    return round(clamp(score), 2)


def build_metrics_from_summary(
    model: str,
    benchmark_status: str,
    total_workflows: int,
    successful_workflows: int,
    failed_workflows: int,
    retries: int,
    rollbacks: int,
    escalations: int,
    stops: int,
    average_execution_time_seconds: float,
    average_confidence: float,
    simulation_success_rate: float,
    tool_reliability: float = 100.0,
    timeout_rate: float = 0.0,
    data_completeness: float = 65.0,
    notes: str = "",
) -> ReliabilityMetrics:
    success = rate(successful_workflows, total_workflows)
    failure = rate(failed_workflows, total_workflows)
    retry_rate = rate(retries, total_workflows)
    interventions = retries + rollbacks + escalations + stops
    recovered_interventions = max(0, retries + rollbacks - escalations - stops)
    recovery_rate = rate(recovered_interventions, interventions) if interventions else 100.0
    retry_success_rate = rate(max(0, retries - escalations), retries) if retries else (100.0 if successful_workflows else 0.0)
    escalation_rate = rate(escalations, total_workflows)
    completion_rate = rate(total_workflows - stops, total_workflows)
    avg_ms = average_execution_time_seconds * 1000.0
    confidence_accuracy = confidence_accuracy_score(average_confidence, success)
    simulation_gap = simulation_success_rate - success
    metrics = ReliabilityMetrics(
        model=model,
        benchmark_status=benchmark_status,
        total_workflows=total_workflows,
        successful_workflows=successful_workflows,
        failed_workflows=failed_workflows,
        retries=retries,
        rollbacks=rollbacks,
        escalations=escalations,
        stops=stops,
        success_rate=round(success, 2),
        failure_rate=round(failure, 2),
        retry_rate=round(retry_rate, 2),
        recovery_rate=round(recovery_rate, 2),
        retry_success_rate=round(retry_success_rate, 2),
        tool_reliability=round(clamp(tool_reliability), 2),
        timeout_rate=round(clamp(timeout_rate), 2),
        timeout_score=round(100.0 - clamp(timeout_rate), 2),
        average_confidence=round(average_confidence, 3),
        confidence_accuracy=round(confidence_accuracy, 2),
        average_execution_time_ms=round(avg_ms, 2),
        execution_time_score=round(execution_time_score(avg_ms), 2),
        escalation_rate=round(escalation_rate, 2),
        workflow_completion_rate=round(completion_rate, 2),
        simulation_success_rate=round(simulation_success_rate, 2),
        simulation_gap=round(simulation_gap, 2),
        data_completeness=round(clamp(data_completeness), 2),
        notes=notes,
    )
    metrics.reliability_score_v1 = score_v1(metrics)
    metrics.reliability_band_v1 = reliability_band(metrics.reliability_score_v1)
    metrics.reliability_score_v2 = score_v2(metrics)
    metrics.reliability_band_v2 = reliability_band(metrics.reliability_score_v2)
    return metrics


def unavailable_metrics(model: str, notes: str) -> ReliabilityMetrics:
    return ReliabilityMetrics(
        model=model,
        benchmark_status="not_run",
        notes=notes,
    )
