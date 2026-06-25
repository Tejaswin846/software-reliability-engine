from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from software_sdk.client import SoftwareClientError
from software_sdk.monitor import ReliabilityMonitor


class SDKComposioTests(unittest.TestCase):
    def test_tool_execution_network_failure_is_not_buffered(self) -> None:
        monitor = ReliabilityMonitor(
            project_name="test-project",
            api_url="https://software.example",
            api_key="test-key",
        )
        monitor.client = MagicMock()
        monitor.client.execute_tool.side_effect = SoftwareClientError("network unavailable")

        result = monitor.execute_tool(
            "wf_123",
            "GMAIL_SEND_EMAIL",
            {"recipient_email": "person@example.com"},
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["buffered"])
        self.assertEqual(monitor.buffer, [])


if __name__ == "__main__":
    unittest.main()
