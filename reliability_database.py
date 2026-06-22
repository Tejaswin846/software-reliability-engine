from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = Path(os.getenv("RELIABILITY_DB_PATH", DATA_DIR / "reliability.db")).expanduser()

MODEL_REPORT = PROJECT_DIR / "multi_model_reliability_report.md"
TOOL_OUTPUT = DATA_DIR / "tool_reliability_benchmark_output.json"
WORKFLOW_OUTPUT = DATA_DIR / "workflow_reliability_analysis_output.json"
PREDICTION_OUTPUT = DATA_DIR / "reliability_prediction_output.json"
GUARDRAIL_OUTPUT = DATA_DIR / "guardrail_effectiveness_output.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def row_to_dict(row: sqlite3.Row | None) -> Dict[str, Any] | None:
    return dict(row) if row is not None else None


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS benchmark_runs (
                run_id TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                source_file TEXT,
                generated_at TEXT NOT NULL,
                total_workflows INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                workflow_id TEXT NOT NULL,
                model TEXT,
                confidence REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                prediction_result_json TEXT,
                guardrail_action_json TEXT,
                baseline_success INTEGER,
                final_outcome TEXT NOT NULL,
                failed_stage TEXT,
                retries INTEGER NOT NULL DEFAULT 0,
                rollbacks INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, workflow_id)
            );

            CREATE TABLE IF NOT EXISTS model_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                total_workflows INTEGER NOT NULL,
                successful_workflows INTEGER NOT NULL,
                failed_workflows INTEGER NOT NULL,
                success_rate REAL NOT NULL,
                failure_rate REAL NOT NULL,
                average_execution_time_ms REAL NOT NULL,
                average_confidence REAL NOT NULL,
                retries INTEGER NOT NULL DEFAULT 0,
                rollbacks INTEGER NOT NULL DEFAULT 0,
                escalations INTEGER NOT NULL DEFAULT 0,
                timeout_rate REAL NOT NULL DEFAULT 0,
                tool_reliability REAL NOT NULL DEFAULT 0,
                reliability_score_v2 REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                tool_name TEXT NOT NULL,
                total_workflows INTEGER NOT NULL,
                successful_workflows INTEGER NOT NULL,
                failed_workflows INTEGER NOT NULL,
                success_rate REAL NOT NULL,
                failure_rate REAL NOT NULL,
                average_latency_ms REAL NOT NULL,
                p95_latency_ms REAL NOT NULL DEFAULT 0,
                timeout_rate REAL NOT NULL,
                recovery_rate REAL NOT NULL,
                reliability_score REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                workflow_id TEXT NOT NULL,
                model TEXT,
                probability_of_success REAL NOT NULL,
                probability_of_failure REAL NOT NULL,
                actual_success INTEGER NOT NULL,
                predicted_success INTEGER NOT NULL,
                failed_stage TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guardrail_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                workflow_id TEXT NOT NULL,
                model TEXT,
                probability_of_failure REAL NOT NULL,
                guardrail_action TEXT,
                actions_json TEXT NOT NULL DEFAULT '[]',
                intervention_triggered INTEGER NOT NULL,
                prevented_failure INTEGER NOT NULL,
                recovery_success INTEGER NOT NULL,
                final_outcome TEXT NOT NULL,
                latency_ms REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_benchmark_runs_type
                ON benchmark_runs(run_type);
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow
                ON workflow_runs(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_model_results_score
                ON model_results(reliability_score_v2 DESC);
            CREATE INDEX IF NOT EXISTS idx_tool_results_score
                ON tool_results(reliability_score DESC);
            CREATE INDEX IF NOT EXISTS idx_predictions_workflow
                ON predictions(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_guardrail_events_workflow
                ON guardrail_events(workflow_id);
            """
        )


def save_run(
    run_id: str,
    run_type: str,
    source_file: str = "",
    generated_at: str | None = None,
    total_workflows: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Path = DB_PATH,
) -> str:
    init_db(db_path)
    with connect(db_path) as db:
        db.execute(
            """
            INSERT OR REPLACE INTO benchmark_runs (
                run_id, run_type, source_file, generated_at, total_workflows, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_type,
                source_file,
                generated_at or now_iso(),
                total_workflows,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
    return run_id


def get_run(run_id: str, db_path: Path = DB_PATH) -> Dict[str, Any] | None:
    init_db(db_path)
    with connect(db_path) as db:
        run = row_to_dict(db.execute("SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,)).fetchone())
        if not run:
            return None
        run["model_results"] = [dict(row) for row in db.execute("SELECT * FROM model_results WHERE run_id = ?", (run_id,))]
        run["tool_results"] = [dict(row) for row in db.execute("SELECT * FROM tool_results WHERE run_id = ?", (run_id,))]
        run["workflow_runs"] = [dict(row) for row in db.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,))]
        run["predictions"] = [dict(row) for row in db.execute("SELECT * FROM predictions WHERE run_id = ?", (run_id,))]
        run["guardrail_events"] = [dict(row) for row in db.execute("SELECT * FROM guardrail_events WHERE run_id = ?", (run_id,))]
        return run


def get_leaderboard(limit: int = 10, db_path: Path = DB_PATH) -> Dict[str, List[Dict[str, Any]]]:
    init_db(db_path)
    with connect(db_path) as db:
        model_rows = db.execute(
            """
            SELECT model, reliability_score_v2, success_rate, average_execution_time_ms, average_confidence, run_id
            FROM model_results
            ORDER BY reliability_score_v2 DESC, success_rate DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        tool_rows = db.execute(
            """
            SELECT tool_name, reliability_score, success_rate, average_latency_ms, timeout_rate, run_id
            FROM tool_results
            ORDER BY reliability_score DESC, success_rate DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {
        "models": [dict(row) for row in model_rows],
        "tools": [dict(row) for row in tool_rows],
    }


def get_guardrail_stats(db_path: Path = DB_PATH) -> Dict[str, Any]:
    init_db(db_path)
    with connect(db_path) as db:
        row = db.execute(
            """
            SELECT
                COUNT(*) AS total_events,
                SUM(intervention_triggered) AS interventions,
                SUM(prevented_failure) AS prevented_failures,
                SUM(recovery_success) AS recovery_successes,
                AVG(CASE WHEN intervention_triggered = 1 THEN latency_ms END) AS average_latency_ms
            FROM guardrail_events
            """
        ).fetchone()
        action_rows = db.execute(
            "SELECT actions_json FROM guardrail_events WHERE intervention_triggered = 1"
        ).fetchall()
    total = int(row["total_events"] or 0)
    interventions = int(row["interventions"] or 0)
    prevented = int(row["prevented_failures"] or 0)
    recoveries = int(row["recovery_successes"] or 0)
    return {
        "total_events": total,
        "interventions": interventions,
        "prevented_failures": prevented,
        "recovery_successes": recoveries,
        "intervention_rate": round((interventions / total * 100.0), 2) if total else 0.0,
        "recovery_success_rate": round((recoveries / interventions * 100.0), 2) if interventions else 0.0,
        "average_latency_ms": round(float(row["average_latency_ms"] or 0.0), 2),
        "actions": action_counts(action_rows),
    }


def action_counts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for row in rows:
        try:
            actions = json.loads(row["actions_json"] or "[]")
        except json.JSONDecodeError:
            actions = []
        for action in actions:
            counts[action] = counts.get(action, 0) + 1
    return [
        {"guardrail_action": action, "count": count}
        for action, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def parse_generated_at(text: str) -> str:
    match = re.search(r"\*\*Generated at:\*\*\s*([^\n\r]+)", text)
    return match.group(1).strip() if match else now_iso()


def parse_percent(value: str) -> float:
    return float(value.strip().replace("%", ""))


def parse_seconds(value: str) -> float:
    return float(value.strip().replace("s", "")) * 1000.0


def migrate_model_report(db_path: Path = DB_PATH) -> None:
    if not MODEL_REPORT.exists():
        return
    text = MODEL_REPORT.read_text(encoding="utf-8")
    generated_at = parse_generated_at(text)
    run_id = save_run(
        "phase4_multi_model_reliability",
        "model_benchmark",
        str(MODEL_REPORT),
        generated_at,
        0,
        {"phase": 4},
        db_path,
    )
    pattern = re.compile(
        r"^\| (?P<model>[^|]+) \| (?P<total>\d+) \| (?P<successful>\d+) \| (?P<failed>\d+) \| "
        r"(?P<success_rate>[0-9.]+)% \| (?P<failure_rate>[0-9.]+)% \| (?P<recovery_rate>[0-9.]+)% \| "
        r"(?P<avg_time>[0-9.]+)s \| (?P<avg_confidence>[0-9.]+) \| (?P<confidence_accuracy>[0-9.]+)% \| "
        r"(?P<retries>\d+) \| (?P<rollbacks>\d+) \| (?P<escalations>\d+) \| "
        r"(?P<timeout_rate>[0-9.]+)% \| (?P<tool_reliability>[0-9.]+)% \| (?P<score>[0-9.]+) \|$"
    )
    rows = []
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        rows.append(match.groupdict())

    with connect(db_path) as db:
        db.execute("DELETE FROM model_results WHERE run_id = ?", (run_id,))
        for item in rows:
            db.execute(
                """
                INSERT INTO model_results (
                    run_id, model, total_workflows, successful_workflows, failed_workflows,
                    success_rate, failure_rate, average_execution_time_ms, average_confidence,
                    retries, rollbacks, escalations, timeout_rate, tool_reliability,
                    reliability_score_v2, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["model"].strip("` "),
                    int(item["total"]),
                    int(item["successful"]),
                    int(item["failed"]),
                    float(item["success_rate"]),
                    float(item["failure_rate"]),
                    parse_seconds(item["avg_time"]),
                    float(item["avg_confidence"]),
                    int(item["retries"]),
                    int(item["rollbacks"]),
                    int(item["escalations"]),
                    float(item["timeout_rate"]),
                    float(item["tool_reliability"]),
                    float(item["score"]),
                    generated_at,
                ),
            )


def migrate_tool_results(db_path: Path = DB_PATH) -> None:
    if not TOOL_OUTPUT.exists():
        return
    payload = json.loads(TOOL_OUTPUT.read_text(encoding="utf-8"))
    run_id = save_run(
        "phase5_tool_reliability",
        "tool_benchmark",
        str(TOOL_OUTPUT),
        payload.get("generated_at") or now_iso(),
        int(payload.get("workflows_per_tool", 0)) * len(payload.get("tool_summaries", [])),
        {"phase": 5},
        db_path,
    )
    with connect(db_path) as db:
        db.execute("DELETE FROM tool_results WHERE run_id = ?", (run_id,))
        for item in payload.get("tool_summaries", []):
            db.execute(
                """
                INSERT INTO tool_results (
                    run_id, tool_name, total_workflows, successful_workflows, failed_workflows,
                    success_rate, failure_rate, average_latency_ms, p95_latency_ms,
                    timeout_rate, recovery_rate, reliability_score, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["tool_name"],
                    item["total_workflows"],
                    item["successful_workflows"],
                    item["failed_workflows"],
                    item["success_rate"],
                    item["failure_rate"],
                    item["average_latency_ms"],
                    item.get("p95_latency_ms", 0),
                    item["timeout_rate"],
                    item["recovery_rate"],
                    item["reliability_score"],
                    payload.get("generated_at") or now_iso(),
                ),
            )


def aggregate_workflow_metrics(workflow: Dict[str, Any]) -> Dict[str, Any]:
    events = workflow.get("events", [])
    confidence_values = [float(event.get("confidence", 0) or 0) for event in events]
    latency_ms = sum(float(event.get("latency_ms", 0) or 0) for event in events)
    retries = sum(int(event.get("retries", 0) or 0) for event in events)
    return {
        "confidence": sum(confidence_values) / len(confidence_values) if confidence_values else 0.0,
        "latency_ms": latency_ms,
        "retries": retries,
    }


def migrate_workflow_runs(db_path: Path = DB_PATH) -> None:
    if not WORKFLOW_OUTPUT.exists():
        return
    payload = json.loads(WORKFLOW_OUTPUT.read_text(encoding="utf-8"))
    run_id = save_run(
        "phase6_workflow_reliability",
        "workflow_benchmark",
        str(WORKFLOW_OUTPUT),
        payload.get("generated_at") or now_iso(),
        int(payload.get("total_workflows", 0)),
        {
            "phase": 6,
            "models": payload.get("models", []),
            "overall": payload.get("overall", {}),
            "stages": payload.get("stages", []),
        },
        db_path,
    )
    with connect(db_path) as db:
        db.execute("DELETE FROM workflow_runs WHERE run_id = ?", (run_id,))
        for workflow in payload.get("workflow_results", []):
            metrics = aggregate_workflow_metrics(workflow)
            db.execute(
                """
                INSERT OR REPLACE INTO workflow_runs (
                    run_id, workflow_id, model, confidence, latency_ms, prediction_result_json,
                    guardrail_action_json, baseline_success, final_outcome, failed_stage,
                    retries, rollbacks, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow["workflow_id"],
                    workflow.get("model"),
                    metrics["confidence"],
                    metrics["latency_ms"],
                    None,
                    None,
                    1 if workflow.get("successful") else 0,
                    "success" if workflow.get("successful") else "failed",
                    workflow.get("failed_stage"),
                    metrics["retries"],
                    0,
                    payload.get("generated_at") or now_iso(),
                ),
            )


def migrate_predictions(db_path: Path = DB_PATH) -> None:
    if not PREDICTION_OUTPUT.exists():
        return
    payload = json.loads(PREDICTION_OUTPUT.read_text(encoding="utf-8"))
    run_id = save_run(
        "phase7_reliability_prediction",
        "prediction_benchmark",
        str(PREDICTION_OUTPUT),
        payload.get("generated_at") or now_iso(),
        int(payload.get("training_examples", 0)),
        {"phase": 7, "evaluation": payload.get("evaluation", {})},
        db_path,
    )
    with connect(db_path) as db:
        db.execute("DELETE FROM predictions WHERE run_id = ?", (run_id,))
        for item in payload.get("predictions", []):
            db.execute(
                """
                INSERT INTO predictions (
                    run_id, workflow_id, model, probability_of_success, probability_of_failure,
                    actual_success, predicted_success, failed_stage, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["workflow_id"],
                    item.get("model"),
                    item["probability_of_success"],
                    item["probability_of_failure"],
                    1 if item["actual_success"] else 0,
                    1 if item["predicted_success"] else 0,
                    item.get("failed_stage"),
                    payload.get("generated_at") or now_iso(),
                ),
            )

        for item in payload.get("predictions", []):
            db.execute(
                """
                UPDATE workflow_runs
                SET prediction_result_json = ?
                WHERE workflow_id = ?
                """,
                (json.dumps(item, ensure_ascii=False), item["workflow_id"]),
            )


def migrate_guardrails(db_path: Path = DB_PATH) -> None:
    if not GUARDRAIL_OUTPUT.exists():
        return
    payload = json.loads(GUARDRAIL_OUTPUT.read_text(encoding="utf-8"))
    run_id = save_run(
        "phase8_guardrail_effectiveness",
        "guardrail_benchmark",
        str(GUARDRAIL_OUTPUT),
        payload.get("generated_at") or now_iso(),
        int(payload.get("total_workflows", 0)),
        {"phase": 8, "summary": payload.get("summary", {})},
        db_path,
    )
    with connect(db_path) as db:
        db.execute("DELETE FROM guardrail_events WHERE run_id = ?", (run_id,))
        for item in payload.get("guardrail_results", []):
            actions = item.get("actions", [])
            primary_action = actions[0] if actions else ""
            final_outcome = "success" if item.get("post_guardrail_success") else "failed"
            db.execute(
                """
                INSERT INTO guardrail_events (
                    run_id, workflow_id, model, probability_of_failure, guardrail_action,
                    actions_json, intervention_triggered, prevented_failure, recovery_success,
                    final_outcome, latency_ms, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["workflow_id"],
                    item.get("model"),
                    item.get("probability_of_failure", 0),
                    primary_action,
                    json.dumps(actions, ensure_ascii=False),
                    1 if item.get("guardrail_triggered") else 0,
                    1 if item.get("prevented_failure") else 0,
                    1 if item.get("guardrail_triggered") and item.get("post_guardrail_success") else 0,
                    final_outcome,
                    item.get("recovery_latency_ms", 0),
                    payload.get("generated_at") or now_iso(),
                ),
            )

            db.execute(
                """
                UPDATE workflow_runs
                SET guardrail_action_json = ?, final_outcome = ?
                WHERE workflow_id = ?
                """,
                (
                    json.dumps(item, ensure_ascii=False),
                    final_outcome,
                    item["workflow_id"],
                ),
            )


def migrate_all(db_path: Path = DB_PATH) -> Dict[str, Any]:
    init_db(db_path)
    migrate_model_report(db_path)
    migrate_tool_results(db_path)
    migrate_workflow_runs(db_path)
    migrate_predictions(db_path)
    migrate_guardrails(db_path)
    with connect(db_path) as db:
        counts = {
            table: db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
            for table in [
                "benchmark_runs",
                "workflow_runs",
                "model_results",
                "tool_results",
                "predictions",
                "guardrail_events",
            ]
        }
    return {
        "database": str(db_path),
        "migrated_at": now_iso(),
        "counts": counts,
        "leaderboard": get_leaderboard(db_path=db_path),
        "guardrail_stats": get_guardrail_stats(db_path=db_path),
    }


def main() -> None:
    result = migrate_all()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
