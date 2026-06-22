import os

from software_sdk import ReliabilityMonitor


def main() -> None:
    monitor = ReliabilityMonitor(
        project_name=os.getenv("SOFTWARE_PROJECT_NAME", "simple-agent"),
        api_url=os.getenv("SOFTWARE_API_URL", "http://127.0.0.1:8300"),
        api_key=os.getenv("SOFTWARE_API_KEY", "sw_replace_me"),
        raise_on_error=True,
    )

    with monitor.track_workflow("simple-answer") as workflow:
        workflow.track_stage("generation", status="completed", success=True, latency_ms=850, confidence=0.94)
        workflow.log_model_call("demo-model", success=True, latency_ms=850, confidence=0.94)
        workflow.complete(success=True, confidence=0.94)

    print("Simple workflow sent to Software.")


if __name__ == "__main__":
    main()
