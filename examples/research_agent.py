import os
import random

from software_sdk import ReliabilityMonitor


def fake_extract(source_count: int) -> dict:
    latency_ms = random.randint(700, 1800)
    extracted = [
        "Agents need workflow-level observability.",
        "Tool failures are a major real-world reliability risk.",
        "Guardrails should act before completion when risk rises.",
    ][:source_count]
    return {"items": extracted, "latency_ms": latency_ms}


def main() -> None:
    monitor = ReliabilityMonitor(
        project_name=os.getenv("SOFTWARE_PROJECT_NAME", "research-agent"),
        api_url=os.getenv("SOFTWARE_API_URL", "http://127.0.0.1:8300"),
        api_key=os.getenv("SOFTWARE_API_KEY", "sw_replace_me"),
        raise_on_error=True,
    )

    with monitor.track_workflow("research-brief") as workflow:
        workflow.track_stage("search", status="completed", success=True, latency_ms=900, confidence=0.91)
        workflow.log_tool_call("fake_search", success=True, latency_ms=900, result_count=3, confidence=0.91)

        extract = fake_extract(3)
        workflow.track_stage("extraction", status="completed", success=True, latency_ms=extract["latency_ms"], confidence=0.89)
        workflow.log_tool_call("fake_extract", success=True, latency_ms=extract["latency_ms"], result_count=3, confidence=0.89)

        workflow.track_stage("synthesis", status="completed", success=True, latency_ms=1600, confidence=0.90)
        workflow.log_model_call("demo-research-model", success=True, latency_ms=1600, confidence=0.90)

        guardrail = workflow.apply_guardrail()
        workflow.complete(success=True, confidence=0.90, metadata={"guardrail": guardrail, "notes": extract["items"]})

    print("Research workflow sent to Software.")


if __name__ == "__main__":
    main()
