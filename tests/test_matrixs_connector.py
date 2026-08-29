from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from matrixs.cli import _discover_or_prompt, main
from matrixs.connector.analyzer import analyze_project
from matrixs.connector.discover import discover_projects
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


if __name__ == "__main__":
    unittest.main()
