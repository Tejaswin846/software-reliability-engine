from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_execution import storage
from ai_execution.control_plane import (
    ExecutionCancelled,
    IdempotencyConflict,
    InvalidTransition,
    SQLiteExecutionControlPlane,
)


class ExecutionControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.temp_dir.name) / "control-plane.db",
        )
        self.path_patch.start()
        storage._INITIALIZED_STORAGE.clear()
        self.control = SQLiteExecutionControlPlane()
        self.identity = {
            "user_id": "user-1",
            "workflow_id": "workflow-1",
            "step_id": "step-1",
        }

    def tearDown(self):
        self.path_patch.stop()
        storage._INITIALIZED_STORAGE.clear()
        self.temp_dir.cleanup()

    def start_and_authorize(self):
        self.control.start(**self.identity, risk_score=0.2)
        self.control.record_verification(
            **self.identity,
            decision="ALLOW",
            reason="Independent evidence passed.",
            policy_version="risk-v2",
            risk_score=0.1,
            evidence_ids=["ev-1"],
            auto_authorize=True,
        )

    def test_state_machine_records_complete_append_only_ledger(self):
        self.start_and_authorize()
        lease = self.control.begin_execution(
            **self.identity,
            idempotency_key="idem-1",
            request={"action": "send"},
            owner="worker-1",
        )
        completed = self.control.finalize_execution(
            user_id="user-1",
            lease=lease,
            result={"ok": True, "id": "provider-42"},
            verified=True,
            provider="gmail",
            provider_action_id="provider-42",
            evidence_ids=["post-1"],
        )

        self.assertEqual(completed["state"], "COMPLETED")
        snapshot = self.control.snapshot(**self.identity)
        states = [event["after_state"] for event in snapshot["ledger"]]
        self.assertEqual(
            states,
            [
                "RECEIVED",
                "PLANNED",
                "EVIDENCE_REQUIRED",
                "VERIFYING",
                "ALLOW",
                "AUTHORIZED",
                "EXECUTION_LEASED",
                "EXECUTING",
                "POST_VERIFYING",
                "VERIFIED",
                "COMPLETED",
            ],
        )
        self.assertEqual(len(snapshot["receipts"]), 1)
        with self.assertRaisesRegex(Exception, "append-only"), storage.connect() as db:
            db.execute("UPDATE execution_ledger SET reason = 'tampered'")

    def test_illegal_transition_is_rejected(self):
        self.control.start(**self.identity)
        with self.assertRaises(InvalidTransition):
            self.control.authorize(**self.identity)

    def test_idempotency_replays_completed_result_and_rejects_payload_change(self):
        self.start_and_authorize()
        lease = self.control.begin_execution(
            **self.identity,
            idempotency_key="idem-1",
            request={"action": "send"},
            owner="worker-1",
        )
        self.control.finalize_execution(
            user_id="user-1",
            lease=lease,
            result={"ok": True, "id": "provider-42"},
            verified=True,
            provider="gmail",
        )
        replay = self.control.begin_execution(
            **self.identity,
            idempotency_key="idem-1",
            request={"action": "send"},
            owner="worker-2",
        )
        self.assertTrue(replay.replay)
        self.assertEqual(replay.response["id"], "provider-42")

        with self.assertRaises(IdempotencyConflict):
            self.control.begin_execution(
                **self.identity,
                idempotency_key="idem-1",
                request={"action": "delete"},
                owner="worker-2",
            )

    def test_cancellation_epoch_invalidates_in_flight_worker(self):
        self.start_and_authorize()
        lease = self.control.begin_execution(
            **self.identity,
            idempotency_key="idem-1",
            request={"action": "send"},
            owner="worker-1",
        )
        self.control.cancel(**self.identity, reason="User pressed cancel.")
        with self.assertRaises(ExecutionCancelled):
            self.control.finalize_execution(
                user_id="user-1",
                lease=lease,
                result={"ok": True},
                verified=True,
                provider="gmail",
            )

    def test_outbox_supports_ack_retry_and_dead_letter(self):
        self.start_and_authorize()
        jobs = self.control.claim_outbox(worker_id="worker-1", limit=1)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(
            self.control.acknowledge_outbox(
                event_id=jobs[0]["event_id"],
                worker_id="worker-1",
                lease_token=jobs[0]["lease_token"],
            )
        )

        jobs = self.control.claim_outbox(worker_id="worker-1", limit=1)
        self.assertEqual(
            self.control.reject_outbox(
                event_id=jobs[0]["event_id"],
                worker_id="worker-1",
                lease_token=jobs[0]["lease_token"],
                error="temporary",
                retry_delay_seconds=0,
            ),
            "pending",
        )
        with storage.connect() as db:
            db.execute(
                "UPDATE execution_outbox SET attempts = max_attempts - 1 WHERE event_id = ?",
                (jobs[0]["event_id"],),
            )
        jobs = self.control.claim_outbox(worker_id="worker-2", limit=1)
        self.assertEqual(
            self.control.reject_outbox(
                event_id=jobs[0]["event_id"],
                worker_id="worker-2",
                lease_token=jobs[0]["lease_token"],
                error="permanent",
                retry_delay_seconds=0,
            ),
            "dead_letter",
        )

    def test_worker_watchdog_reports_stale_heartbeats(self):
        self.control.heartbeat_worker(
            worker_id="worker-1",
            instance_id="instance-1",
            active_leases=2,
        )
        with storage.connect() as db:
            db.execute(
                """UPDATE execution_worker_heartbeats
                   SET heartbeat_at = '2000-01-01T00:00:00+00:00'
                   WHERE worker_id = 'worker-1'"""
            )
        stale = self.control.stale_workers(stale_after_seconds=1)
        self.assertEqual([worker["worker_id"] for worker in stale], ["worker-1"])


if __name__ == "__main__":
    unittest.main()
