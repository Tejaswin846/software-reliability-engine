from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_execution import storage
from ai_execution.risk_adaptive import evaluate_verification


def strong_evidence() -> list[dict]:
    return [
        {
            "event_type": "state",
            "source": f"independent-check-{index}",
            "status": "confirmed",
            "success": True,
            "trusted": True,
            "independent": True,
        }
        for index in range(4)
    ]


class RiskAdaptiveVerificationTests(unittest.TestCase):
    def evaluate(self, **overrides):
        values = {
            "user_id": "user-1",
            "workflow_id": "workflow-1",
            "step_id": "step-1",
            "phase": "pre",
            "action": {"intent": "search_data", "type": "search", "idempotent": True},
            "evidence_events": strong_evidence(),
            "workflow_state": {},
            "metadata": {"original_tokens": 4000},
        }
        values.update(overrides)
        return evaluate_verification(**values)

    def test_low_risk_strong_evidence_uses_code_only_path(self):
        result = self.evaluate()
        self.assertEqual(result["decision"], "ALLOW")
        self.assertEqual(result["verification_level"], "A")
        self.assertEqual(result["verifier"], "deterministic_code")
        self.assertFalse(result["evidence"]["agent_confidence_used_for_routing"])

    def test_cumulative_sensitive_context_makes_external_send_critical(self):
        first = self.evaluate(
            step_id="read-profile",
            action={
                "intent": "search_data",
                "type": "read",
                "idempotent": True,
                "sensitive_data_classes": ["email", "address", "financial"],
            },
        )
        second = self.evaluate(
            step_id="send-profile",
            action={
                "intent": "send_email",
                "type": "send",
                "recipient": "outside@example.com",
                "side_effect": True,
            },
            workflow_state=first["workflow_state"],
        )
        self.assertEqual(second["risk"]["band"], "critical")
        self.assertGreaterEqual(second["risk"]["combined_score"], 92)
        self.assertEqual(second["decision"], "REVIEW")

    def test_false_success_is_blocked_by_independent_tool_failure(self):
        result = self.evaluate(
            phase="post",
            action={"intent": "modify_database", "type": "write", "side_effect": True},
            evidence_events=[
                {
                    "event_type": "agent",
                    "source": "agent",
                    "status": "success",
                    "success": True,
                    "independent": False,
                },
                {
                    "event_type": "tool",
                    "source": "database",
                    "status": "failed",
                    "success": False,
                    "independent": True,
                },
            ],
        )
        self.assertEqual(result["decision"], "BLOCK")
        self.assertTrue(result["deterministic"]["contradiction"])
        self.assertIn(
            "false_success_contradiction", result["deterministic"]["hard_failures"]
        )

    def test_unknown_tools_escalate_instead_of_defaulting_to_safe(self):
        result = self.evaluate(
            action={
                "intent": "external_tool_action",
                "type": "execute",
                "tool_slug": "UNCLASSIFIED_TOOL",
            },
            metadata={
                "original_tokens": 4000,
                "known_tools": ["KNOWN_TOOL"],
                "tool_inventory_complete": True,
            },
        )
        self.assertTrue(result["deterministic"]["unknown_tool"])
        self.assertEqual(result["verification_level"], "C")
        self.assertEqual(result["decision"], "REVIEW")

    def test_unplanned_tool_execution_is_blocked(self):
        result = self.evaluate(
            action={
                "intent": "external_tool_action",
                "type": "execute",
                "tool_slug": "PLANNED_TOOL",
            },
            evidence_events=strong_evidence()
            + [
                {
                    "event_type": "tool",
                    "source": "tool-runtime",
                    "tool_name": "DIFFERENT_TOOL",
                    "status": "success",
                    "success": True,
                    "independent": True,
                }
            ],
            metadata={
                "original_tokens": 4000,
                "known_tools": ["PLANNED_TOOL", "DIFFERENT_TOOL"],
                "tool_inventory_complete": True,
            },
        )
        self.assertEqual(result["decision"], "BLOCK")
        self.assertIn("unexpected_tool", result["deterministic"]["hard_failures"])

    def test_post_action_side_effect_requires_independent_confirmation(self):
        result = self.evaluate(
            phase="post",
            action={
                "intent": "modify_database",
                "type": "write",
                "tool_slug": "DATABASE_UPDATE",
                "side_effect": True,
            },
            evidence_events=[
                {
                    "event_type": "tool",
                    "source": "database",
                    "tool_name": "DATABASE_UPDATE",
                    "status": "success",
                    "success": True,
                    "independent": True,
                }
            ],
            metadata={
                "original_tokens": 4000,
                "known_tools": ["DATABASE_UPDATE"],
                "tool_inventory_complete": True,
            },
        )
        self.assertEqual(result["decision"], "BLOCK")
        self.assertIn(
            "required_external_evidence", result["deterministic"]["hard_failures"]
        )

    def test_cheap_model_confidence_without_support_does_not_allow(self):
        result = self.evaluate(
            evidence_events=[
                {
                    "event_type": "agent",
                    "source": "agent",
                    "status": "success",
                    "success": True,
                    "untrusted_data": "answer",
                },
                {
                    "event_type": "decision",
                    "source": "small_model",
                    "status": "approved",
                    "success": True,
                    "independent": True,
                    "payload": {"confidence": 0.99},
                },
            ],
        )
        self.assertEqual(result["decision"], "REVIEW")
        self.assertFalse(result["evidence"]["agent_confidence_used_for_routing"])

    def test_budget_ceiling_routes_to_review_without_safety_downgrade(self):
        result = self.evaluate(
            action={
                "intent": "external_tool_action",
                "type": "execute",
                "tool_slug": "UNKNOWN",
            },
            metadata={
                "known_tools": [],
                "tool_inventory_complete": True,
                "token_budget": {
                    "original_tokens": 1000,
                    "verification_budget": 100,
                    "verification_tokens_spent": 100,
                },
            },
        )
        self.assertEqual(result["decision"], "REVIEW")
        self.assertTrue(result["budget"]["cost_ceiling_reached"])
        self.assertTrue(result["budget"]["safety_policy_overrides_budget"])

    def test_human_gate_can_approve_a_critical_payment_with_evidence(self):
        events = strong_evidence() + [
            {
                "event_type": "decision",
                "source": "human_reviewer",
                "status": "approved",
                "success": True,
                "trusted": True,
                "independent": True,
            }
        ]
        result = self.evaluate(
            action={
                "type": "pay",
                "action_class": "pay",
                "side_effect": True,
                "irreversible": True,
            },
            evidence_events=events,
        )
        self.assertEqual(result["verification_level"], "S")
        self.assertEqual(result["decision"], "ALLOW")

    def test_transient_idempotent_failure_uses_bounded_retry(self):
        result = self.evaluate(
            action={
                "intent": "search_data",
                "type": "read",
                "idempotent": True,
                "retry_count": 0,
            },
            evidence_events=[
                {
                    "event_type": "tool",
                    "source": "search",
                    "status": "timeout",
                    "success": False,
                    "independent": True,
                }
            ],
            metadata={"retry_limit": 2, "original_tokens": 1000},
        )
        self.assertEqual(result["decision"], "RETRY")


class RiskAdaptiveStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.temp_dir.name) / "risk_adaptive.db",
        )
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_evidence_decisions_audits_and_metrics_are_user_scoped(self):
        sampled = None
        for index in range(200):
            candidate = evaluate_verification(
                user_id="user-1",
                workflow_id="workflow-audit",
                step_id=f"step-{index}",
                phase="pre",
                action={"intent": "search_data", "type": "read", "idempotent": True},
                evidence_events=strong_evidence(),
                workflow_state={},
                metadata={"original_tokens": 4000, "audit_base_rate": 0.25},
            )
            if candidate["semantic_audit"]["sampled"]:
                sampled = candidate
                break
        self.assertIsNotNone(sampled)
        storage.record_verification_evaluation(user_id="user-1", result=sampled)

        pending = storage.pending_semantic_audits(user_id="user-1")
        self.assertEqual(len(pending), 1)
        audit = storage.record_semantic_audit(
            user_id="user-1",
            decision_id=sampled["decision_id"],
            outcome="hidden_error",
            verifier="test-semantic-verifier",
            tokens_used=50,
        )
        self.assertTrue(audit["discovered_error"])

        metrics = storage.verification_metrics(user_id="user-1")
        self.assertEqual(metrics["semantic_audits_completed"], 1)
        self.assertEqual(metrics["hidden_errors_discovered"], 1)
        self.assertGreater(metrics["false_negative_rate"], 0)
        self.assertEqual(
            storage.verification_metrics(user_id="other-user")["decision_count"], 0
        )


if __name__ == "__main__":
    unittest.main()
