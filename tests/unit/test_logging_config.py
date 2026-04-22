from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import logging_config


class LoggingConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = tempfile.mkdtemp(prefix="logging-config-")
        self._saved_handlers = list(logging.getLogger().handlers)
        for handler in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        logging_config._SESSION_LOG_PATH = ""
        logging_config._SESSION_LOG_READY = False
        os.environ.pop("APP_SESSION_LOG_PATH", None)

    def tearDown(self) -> None:
        for handler in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        for handler in self._saved_handlers:
            logging.getLogger().addHandler(handler)
        shutil.rmtree(self.temp_root, ignore_errors=True)
        logging_config._SESSION_LOG_PATH = ""
        logging_config._SESSION_LOG_READY = False
        os.environ.pop("APP_SESSION_LOG_PATH", None)

    def test_setup_logging_creates_single_session_file_and_is_idempotent(self) -> None:
        with patch.object(logging_config, "_session_log_dir", return_value=self.temp_root):
            first_path = logging_config.setup_logging()
            second_path = logging_config.setup_logging()

        self.assertEqual(first_path, second_path)
        self.assertTrue(os.path.exists(first_path))
        self.assertTrue(os.path.basename(first_path).startswith("app_"))
        self.assertTrue(os.path.basename(first_path).endswith(".log"))
        self.assertEqual(os.environ.get("APP_SESSION_LOG_PATH"), first_path)

    def test_prune_session_logs_keeps_latest_count(self) -> None:
        created_paths: list[str] = []
        now = time.time()
        for idx in range(35):
            path = os.path.join(self.temp_root, f"app_20260416-100000_{idx}.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(str(idx))
            os.utime(path, (now + idx, now + idx))
            created_paths.append(path)

        logging_config._prune_session_logs(self.temp_root, keep_latest=30)

        remaining = sorted(
            [name for name in os.listdir(self.temp_root) if name.startswith("app_") and name.endswith(".log")]
        )
        self.assertEqual(len(remaining), 30)
        self.assertFalse(os.path.exists(created_paths[0]))
        self.assertTrue(os.path.exists(created_paths[-1]))


if __name__ == "__main__":
    unittest.main()
