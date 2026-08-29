from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as matrixs_app
from matrixs.connector.credentials import obtain_credentials
from matrixs.connector.models import Credentials
from matrixs.connector.verify import verify_connection


class MatrixsConnectionTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_dir = matrixs_app.DATA_DIR
        self.original_db_path = matrixs_app.DB_PATH
        matrixs_app.DATA_DIR = Path(self.temp_dir.name)
        matrixs_app.DB_PATH = Path(self.temp_dir.name) / "matrixs-connection.db"
        matrixs_app._INITIALIZED_DATABASES.discard(str(matrixs_app.DB_PATH.resolve()))
        matrixs_app.init_db()
        self.client = TestClient(matrixs_app.app)
        access_token = matrixs_app.create_access_token("usr_dev_local")["access_token"]
        self.user_headers = {"Authorization": f"Bearer {access_token}"}

    def tearDown(self) -> None:
        self.client.close()
        matrixs_app._INITIALIZED_DATABASES.discard(str(matrixs_app.DB_PATH.resolve()))
        matrixs_app.DATA_DIR = self.original_data_dir
        matrixs_app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_one_time_token_exchanges_for_matrixs_project_credentials(self) -> None:
        created = self.client.post(
            "/api/projects/prj_dev_local/connection-token",
            headers=self.user_headers,
            json={},
        )
        self.assertEqual(created.status_code, 200)
        connection = created.json()["connection"]
        self.assertIn("matrixs connect --token mxct_", connection["command"])
        self.assertNotIn("--api-key", connection["command"])

        exchanged = self.client.post(
            "/api/sdk/connect/exchange",
            json={
                "token": connection["token"],
                "installation_id": "inst_test_connector",
                "device_label": "Test workstation",
                "operating_system": "Windows",
                "runtime": "Python 3.12",
            },
        )
        self.assertEqual(exchanged.status_code, 200)
        payload = exchanged.json()
        self.assertTrue(payload["api_key"].startswith("mx_"))
        self.assertEqual(payload["project"]["id"], "prj_dev_local")
        self.assertEqual(payload["installation"]["id"], "inst_test_connector")

        status = self.client.get(
            "/api/sdk/status",
            headers={"X-Matrixs-API-Key": payload["api_key"]},
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["project"]["id"], "prj_dev_local")

        reused = self.client.post(
            "/api/sdk/connect/exchange",
            json={"token": connection["token"]},
        )
        self.assertEqual(reused.status_code, 410)

    def test_connector_resolves_credentials_from_cloud_token_exchange(self) -> None:
        fake_response = {
            "ok": True,
            "project": {"id": "prj_cloud", "name": "Cloud Agent"},
            "installation": {"id": "inst_cloud"},
            "api_key": "mx_secret",
        }
        with tempfile.TemporaryDirectory() as directory, patch(
            "matrixs.connector.credentials.MatrixsClient"
        ) as client_class:
            client_class.return_value.post.return_value = fake_response
            credentials = obtain_credentials(
                Path(directory),
                api_url="https://matrixs.example",
                connection_token="mxct_one_time_token_value",
            )

        self.assertEqual(credentials.project_id, "prj_cloud")
        self.assertEqual(credentials.project_name, "Cloud Agent")
        self.assertEqual(credentials.api_key, "mx_secret")
        self.assertEqual(credentials.installation_id, "inst_cloud")
        request_payload = client_class.return_value.post.call_args.args[1]
        self.assertEqual(request_payload["token"], "mxct_one_time_token_value")
        self.assertTrue(request_payload["installation_id"].startswith("inst_"))

    def test_connection_verification_reuses_the_authorized_installation(self) -> None:
        credentials = Credentials(
            project_id="prj_cloud",
            project_name="Cloud Agent",
            api_url="https://matrixs.example",
            api_key="mx_secret",
            installation_id="inst_cloud",
        )
        with patch("matrixs.connector.verify.MatrixsClient") as client_class:
            client_class.return_value.status.return_value = {
                "project": {"id": "prj_cloud"}
            }
            client_class.return_value.post.return_value = {"workflow_id": "wf_test"}
            verify_connection(credentials)

        metadata = client_class.return_value.post.call_args.args[1]["metadata"]
        self.assertEqual(metadata["installation_id"], "inst_cloud")


if __name__ == "__main__":
    unittest.main()
