import os
import random

from software_sdk import ReliabilityMonitor


def stage_success(probability: float) -> bool:
    return random.random() < probability


def main() -> None:
    monitor = ReliabilityMonitor(
        project_name=os.getenv("SOFTWARE_PROJECT_NAME", "multi-step-agent"),
        api_url=os.getenv("SOFTWARE_API_URL", "http://127.0.0.1:8300"),
        api_key=os.getenv("SOFTWARE_API_KEY", "sw_replace_me"),
        raise_on_error=True,
    )

    stages = [
        ("planning", "planner-model", 0.97, 700),
        ("search", "fake_search", 0.93, 1100),
        ("extraction", "fake_extract", 0.90, 1500),
        ("generation", "writer-model", 0.94, 2400),
        ("validation", "validator-model", 0.92, 1300),
    ]

    with monitor.track_workflow("multi-step-reliability-check") as workflow:
        confidences = []
        success = True
        for stage_name, dependency, probability, latency_ms in stages:
            ok = stage_success(probability)
            confidence = round(random.uniform(0.72, 0.98) if ok else random.uniform(0.25, 0.69), 3)
            confidences.append(confidence)
            workflow.track_stage(stage_name, status="completed" if ok else "failed", success=ok, latency_ms=latency_ms, confidence=confidence)
            if stage_name in {"search", "extraction"}:
                workflow.log_tool_call(dependency, success=ok, latency_ms=latency_ms, result_count=4 if ok else 0, confidence=confidence)
            else:
                workflow.log_model_call(dependency, success=ok, latency_ms=latency_ms, confidence=confidence)
            if not ok:
                success = False
                workflow.log_error("stage_failure", f"{stage_name} failed", stage_name=stage_name)

        prediction = workflow.predict_failure()
        guardrail = workflow.apply_guardrail()
        average_confidence = round(sum(confidences) / len(confidences), 3)
        workflow.complete(
            success=success,
            confidence=average_confidence,
            metadata={"prediction": prediction, "guardrail": guardrail},
        )

    print("Multi-step workflow sent to Software.")


if __name__ == "__main__":
    main()
