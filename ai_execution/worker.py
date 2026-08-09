from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from .control_plane import ControlPlaneError, create_execution_control_plane


class DurableOutboxWorker:
    """Lease-based worker with ACK, retry, DLQ, heartbeat, and graceful stop."""

    def __init__(
        self,
        *,
        handlers: dict[str, Callable[[dict[str, Any]], Any]],
        control_plane: Any | None = None,
        worker_id: str | None = None,
        poll_seconds: float = 1.0,
        batch_size: int = 20,
        lease_seconds: int = 60,
    ) -> None:
        self.control_plane = control_plane or create_execution_control_plane()
        self.handlers = dict(handlers)
        self.worker_id = (
            worker_id
            or os.getenv("RENDER_INSTANCE_ID")
            or f"worker-{socket.gethostname()}"
        )
        self.instance_id = os.getenv("RENDER_SERVICE_ID") or socket.gethostname()
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.batch_size = max(1, min(200, int(batch_size)))
        self.lease_seconds = max(5, int(lease_seconds))
        self._stop = threading.Event()
        self._active = 0
        self._processed = 0
        self._failed = 0

    def stop(self) -> None:
        self._stop.set()

    def heartbeat(self) -> dict[str, Any]:
        return self.control_plane.heartbeat_worker(
            worker_id=self.worker_id,
            instance_id=self.instance_id,
            active_leases=self._active,
            metadata={
                "processed": self._processed,
                "failed": self._failed,
                "stopping": self._stop.is_set(),
            },
        )

    def run_once(self) -> dict[str, Any]:
        self.heartbeat()
        jobs = self.control_plane.claim_outbox(
            worker_id=self.worker_id,
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        delivered = 0
        retried = 0
        dead_lettered = 0
        for job in jobs:
            self._active += 1
            try:
                handler = self.handlers.get(job["event_type"])
                if handler is None:
                    raise LookupError(f"No handler registered for {job['event_type']}.")
                handler(job.get("payload") or {})
                acknowledged = self.control_plane.acknowledge_outbox(
                    event_id=job["event_id"],
                    worker_id=self.worker_id,
                    lease_token=job["lease_token"],
                )
                if not acknowledged:
                    raise ControlPlaneError(
                        "Outbox ACK was rejected because the lease became stale."
                    )
                delivered += 1
                self._processed += 1
            except Exception as error:
                status = self.control_plane.reject_outbox(
                    event_id=job["event_id"],
                    worker_id=self.worker_id,
                    lease_token=job["lease_token"],
                    error=str(error),
                    retry_delay_seconds=min(
                        300, 2 ** max(0, int(job.get("attempts") or 1) - 1)
                    ),
                )
                retried += int(status == "pending")
                dead_lettered += int(status == "dead_letter")
                self._failed += 1
            finally:
                self._active -= 1
        self.heartbeat()
        return {
            "claimed": len(jobs),
            "delivered": delivered,
            "retried": retried,
            "dead_lettered": dead_lettered,
            "stopping": self._stop.is_set(),
        }

    def run_forever(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    result = self.run_once()
                except Exception:
                    self._failed += 1
                    self._stop.wait(self.poll_seconds)
                    continue
                if result["claimed"] == 0:
                    self._stop.wait(self.poll_seconds)
        finally:
            self._active = 0
            with suppress(Exception):
                self.heartbeat()

    def watchdog(self, *, stale_after_seconds: int = 90) -> dict[str, Any]:
        stale = self.control_plane.stale_workers(
            stale_after_seconds=stale_after_seconds
        )
        return {
            "ok": not stale,
            "stale_workers": stale,
            "count": len(stale),
        }


__all__ = ["DurableOutboxWorker"]
