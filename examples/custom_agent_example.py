import os
import time

from software_sdk import ReliabilityMonitor


def run_agent() -> None:
    monitor = ReliabilityMonitor(
        project_name="my-agent",
        api_url=os.getenv("SOFTWARE_API_URL", "http://127.0.0.1:8300"),
        api_key=os.getenv("SOFTWARE_API_KEY", "dev-key"),
    )

    with monitor.track_workflow("research-task") as workflow:
        workflow.track_stage("search")
        workflow.log_tool_call(
            "parallel_search",
            success=True,
            latency_ms=1200,
            result_count=5,
            confidence=0.94,
        )

        workflow.track_stage("extraction")
        workflow.log_tool_call(
            "parallel_extract",
            success=True,
            latency_ms=1800,
            result_count=3,
            confidence=0.91,
        )

        workflow.track_stage("generation")
        workflow.log_model_call(
            "llama3.2:3b",
            success=True,
            latency_ms=5000,
            confidence=0.92,
        )

        prediction = workflow.predict_failure()
        guardrail = workflow.apply_guardrail()

        workflow.complete(
            success=True,
            confidence=0.91,
            metadata={
                "prediction": prediction,
                "guardrail": guardrail,
                "example_ran_at": int(time.time()),
            },
        )

    flush_result = monitor.flush()
    print("Workflow sent to Software.")
    print(f"Buffered events remaining: {flush_result['remaining']}")


if __name__ == "__main__":
    run_agent()
