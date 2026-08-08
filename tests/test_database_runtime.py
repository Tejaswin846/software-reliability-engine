from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class DatabaseRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "runtime.db"
        self.path_patch = patch.object(app, "DB_PATH", self.db_path)
        self.path_patch.start()
        app._INITIALIZED_DATABASES.discard(str(self.db_path.resolve()))

    def tearDown(self) -> None:
        app._INITIALIZED_DATABASES.discard(str(self.db_path.resolve()))
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_repeated_initialization_uses_fast_path(self) -> None:
        with patch.object(
            app, "_initialize_database", wraps=app._initialize_database
        ) as initialize:
            app.init_db()
            app.init_db()

        self.assertEqual(initialize.call_count, 1)
        with app.connect() as database:
            self.assertIsNotNone(
                database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                ).fetchone()
            )

    def test_deleted_database_is_initialized_again(self) -> None:
        app.init_db()
        self.db_path.unlink()
        app.init_db()

        with app.connect() as database:
            self.assertIsNotNone(
                database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                ).fetchone()
            )

    def test_connections_enable_concurrency_pragmas(self) -> None:
        app.init_db()
        with app.connect() as database:
            self.assertEqual(database.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(
                database.execute("PRAGMA busy_timeout").fetchone()[0],
                app.SQLITE_BUSY_TIMEOUT_MS,
            )
            self.assertEqual(
                database.execute("PRAGMA journal_mode").fetchone()[0], "wal"
            )
            self.assertEqual(database.execute("PRAGMA synchronous").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
