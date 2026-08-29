from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from unittest.mock import patch

from matrixs.cli import _discover_or_prompt, main
from matrixs.connector.analyzer import analyze_project
from matrixs.connector.browser_setup import collect_credentials_in_browser
from matrixs.connector.discover import discover_projects
from matrixs.connector.models import Credentials
from matrixs.connector.permissions import ask_yes_no, request_integration_permission


class MatrixsConnectorTests(unittest.TestCase):
    def make_fastapi_project(self, root: Path) -> None:
        (root / "requirements.txt").write_text("fastapi\nopenai\n", encoding="utf-8")
        (root / "main.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n",
            encoding="utf-8",
        )

    def test_discovery_and_analysis_detect_supported_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "agent-project"
            project.mkdir()
            self.make_fastapi_project(project)

            candidates = discover_projects(root)

            self.assertEqual([item.path for item in candidates], [project.resolve()])
            analysis = analyze_project(project)
            self.assertEqual(analysis.framework, "fastapi")
            self.assertEqual(analysis.startup_command, ["python", "-m", "uvicorn", "main:app"])
            self.assertIn("openai", analysis.ai_libraries)
            self.assertEqual(analysis.adapters, ["fastapi", "openai"])

    def test_discovery_handles_multiple_and_manual_missing_project_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "alpha"
            second = root / "beta"
            first.mkdir()
            second.mkdir()
            self.make_fastapi_project(first)
            self.make_fastapi_project(second)

            candidates = discover_projects(root)
            self.assertEqual([item.path for item in candidates], [first.resolve(), second.resolve()])

            empty = root / "empty"
            empty.mkdir()
            answers = iter(["2", str(second)])
            selected = _discover_or_prompt(
                empty,
                max_depth=2,
                selection=None,
                allow_prompt=True,
                input_fn=lambda _: next(answers),
            )
            self.assertIsNotNone(selected)
            self.assertEqual(selected.path, second.resolve())

    def test_yes_no_parser_repeats_invalid_input(self) -> None:
        answers = iter(["perhaps", "YES"])
        self.assertTrue(ask_yes_no("Continue?", input_fn=lambda _: next(answers)))

    def test_permission_no_no_returns_to_original_question(self) -> None:
        answers = iter(["n", "n", "y"])
        opened = []

        allowed = request_integration_permission(
            Path("Nexora"),
            input_fn=lambda _: next(answers),
            open_manual_guide=lambda: opened.append(True),
        )

        self.assertTrue(allowed)
        self.assertEqual(opened, [])

    def test_local_browser_page_collects_credentials_without_putting_secrets_in_url(self) -> None:
        page_html = []
        opened_urls = []

        def open_and_submit(url: str) -> bool:
            opened_urls.append(url)

            def submit() -> None:
                with urlopen(url, timeout=3) as response:
                    page_html.append(response.read().decode("utf-8"))
                parsed = urlsplit(url)
                body = urlencode(
                    {
                        "project_id": "prj_browser_test",
                        "api_key": "mx_browser_secret",
                        "project_name": "Browser Agent",
                        "api_url": "https://matrixs.example/",
                    }
                ).encode("utf-8")
                request = Request(
                    f"http://127.0.0.1:{parsed.port}/connect?{parsed.query}",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                with urlopen(request, timeout=3) as response:
                    response.read()

            threading.Thread(target=submit, daemon=True).start()
            return True

        with tempfile.TemporaryDirectory() as directory:
            credentials = collect_credentials_in_browser(
                Path(directory),
                project_name="Browser Agent",
                timeout=3,
                browser_open=open_and_submit,
            )

        self.assertEqual(credentials.project_id, "prj_browser_test")
        self.assertEqual(credentials.api_key, "mx_browser_secret")
        self.assertEqual(credentials.api_url, "https://matrixs.example")
        self.assertIn('name="project_id"', page_html[0])
        self.assertIn('name="api_key" type="password"', page_html[0])
        self.assertIn("served only on your computer", page_html[0])
        self.assertNotIn("mx_browser_secret", opened_urls[0])
        self.assertNotIn("prj_browser_test", opened_urls[0])

    def test_manual_connect_opens_guide_without_discovering_or_changing_files(self) -> None:
        with patch("matrixs.cli._open_manual_guide") as open_manual:
            result = main(["connect", "--manual"])

        self.assertEqual(result, 0)
        open_manual.assert_called_once_with()

    def test_connect_status_and_disconnect_are_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_fastapi_project(root)
            (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")

            result = main(
                [
                    "connect",
                    "--path",
                    str(root),
                    "--yes",
                    "--project-id",
                    "prj_test",
                    "--project-name",
                    "Nexora",
                    "--api-url",
                    "https://matrixs.example",
                    "--api-key",
                    "secret-test-key",
                    "--no-verify",
                ]
            )

            self.assertEqual(result, 0)
            config_path = root / ".matrixs" / "config.json"
            secret_path = root / ".matrixs" / ".env"
            self.assertTrue(config_path.is_file())
            self.assertTrue(secret_path.is_file())
            config_text = config_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-test-key", config_text)
            config = json.loads(config_text)
            self.assertEqual(config["project_id"], "prj_test")
            self.assertEqual(config["framework"], "fastapi")
            self.assertIn("MATRIXS_API_KEY=secret-test-key", secret_path.read_text(encoding="utf-8"))
            self.assertIn(".matrixs/.env", (root / ".gitignore").read_text(encoding="utf-8"))
            self.assertEqual(main(["status", "--path", str(root), "--offline"]), 0)

            self.assertEqual(main(["disconnect", "--path", str(root)]), 0)
            self.assertFalse(config_path.exists())
            self.assertFalse(secret_path.exists())
            self.assertEqual((root / ".gitignore").read_text(encoding="utf-8"), ".venv/\n")
            self.assertTrue((root / ".matrixs" / "backups").is_dir())

    def test_secret_free_connect_uses_browser_credentials_even_when_local_credentials_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_fastapi_project(root)
            (root / ".matrixs").mkdir()
            (root / ".matrixs" / ".env").write_text(
                "MATRIXS_PROJECT_ID=prj_old\nMATRIXS_API_KEY=mx_old\n",
                encoding="utf-8",
            )
            entered = Credentials(
                project_id="prj_new",
                api_key="mx_new",
                api_url="https://matrixs.example",
                project_name="New Agent",
                installation_id="inst_new",
            )
            with patch("matrixs.cli.collect_credentials_in_browser", return_value=entered) as collect:
                result = main(["connect", "--path", str(root), "--yes", "--no-verify"])

            self.assertEqual(result, 0)
            collect.assert_called_once()
            saved = (root / ".matrixs" / ".env").read_text(encoding="utf-8")
            self.assertIn("MATRIXS_PROJECT_ID=prj_new", saved)
            self.assertIn("MATRIXS_API_KEY=mx_new", saved)


if __name__ == "__main__":
    unittest.main()
