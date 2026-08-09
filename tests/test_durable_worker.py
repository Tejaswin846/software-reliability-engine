from __future__ import annotations

from pathlib import Path

import pytest

from ai_execution import storage
from ai_execution.control_plane import SQLiteExecutionControlPlane
from ai_execution.worker import DurableOutboxWorker


@pytest.fixture()
def control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SQLiteExecutionControlPlane:
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "worker.db")
    storage._INITIALIZED_STORAGE.clear()
    return SQLiteExecutionControlPlane()


def _start(control: SQLiteExecutionControlPlane, step: str) -> None:
    control.start(user_id="user-1", workflow_id="workflow-1", step_id=step)


def _event_types() -> list[str]:
    with storage.connect() as db:
        return [
            row["event_type"]
            for row in db.execute(
                "SELECT DISTINCT event_type FROM execution_outbox WHERE status = 'pending'"
            ).fetchall()
        ]


def test_worker_acknowledges_claimed_batch(
    control: SQLiteExecutionControlPlane,
) -> None:
    _start(control, "step-1")
    received: list[dict] = []
    handlers = {event_type: received.append for event_type in _event_types()}
    worker = DurableOutboxWorker(
        handlers=handlers, control_plane=control, worker_id="worker-1", batch_size=20
    )
    result = worker.run_once()
    assert result["delivered"] == result["claimed"]
    assert len(received) == result["claimed"]
    with storage.connect() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM execution_outbox WHERE status <> 'delivered'"
            ).fetchone()[0]
            == 0
        )


def test_worker_retries_and_gracefully_drains_claimed_batch(
    control: SQLiteExecutionControlPlane,
) -> None:
    _start(control, "step-1")
    _start(control, "step-2")
    event_types = _event_types()
    calls = 0
    worker: DurableOutboxWorker

    def handler(_: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worker.stop()

    worker = DurableOutboxWorker(
        handlers={event_type: handler for event_type in event_types},
        control_plane=control,
        worker_id="worker-1",
        batch_size=20,
    )
    result = worker.run_once()
    assert result["stopping"] is True
    assert result["delivered"] == result["claimed"]

    _start(control, "step-3")

    def fail(_: dict) -> None:
        raise RuntimeError("temporary")

    failing = DurableOutboxWorker(
        handlers={event_type: fail for event_type in _event_types()},
        control_plane=control,
        worker_id="worker-2",
    )
    retried = failing.run_once()
    assert retried["retried"] == retried["claimed"]
