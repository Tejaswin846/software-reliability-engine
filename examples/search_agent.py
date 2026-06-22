import os
import random

from software_sdk import ReliabilityMonitor


def fake_search(query: str) -> dict:
    latency_ms = random.randint(300, 1200)
    results = [
        {"title": "Reliability patterns for AI agents", "url": "https://example.com/reliability"},
        {"title": "Agent workflow observability", "url": "https://example.com/observability"},
        {"title": "Guardrails and failure prediction", "url": "https://example.com/guardrails"},
    ]
    return {"query": query, "results": results, "latency_ms": latency_ms}


def main() -> None:
    monitor = ReliabilityMonitor(
        project_name=os.getenv("SOFTWARE_PROJECT_NAME", "search-agent"),
        api_url=os.getenv("SOFTWARE_API_URL", "http://127.0.0.1:8300"),
        api_key=os.getenv("SOFTWARE_API_KEY", "sw_replace_me"),
        raise_on_error=True,
    )

    with monitor.track_workflow("search-task") as workflow:
        workflow.track_stage("search", status="started")
        search = fake_search("AI agent reliability")
        workflow.track_stage("search", status="completed", success=True, latency_ms=search["latency_ms"], confidence=0.92)
        workflow.log_tool_call(
            "fake_search",
            success=True,
            latency_ms=search["latency_ms"],
            result_count=len(search["results"]),
            confidence=0.92,
        )
        prediction = workflow.predict_failure()
        workflow.complete(success=True, confidence=0.92, metadata={"prediction": prediction})

    print("Search workflow sent to Software.")


if __name__ == "__main__":
    main()
