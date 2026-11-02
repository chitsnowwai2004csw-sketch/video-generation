"""Cross-platform worker configuration checks without starting render processes."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WorkerConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {"VIDEO_DATA_DIR": cls.temporary.name}):
            spec = importlib.util.spec_from_file_location("worker_configuration_test", Path(__file__).parent / "video_worker.py")
            cls.worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.worker)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_existing_linux_browser_path(self):
        path = Path(self.temporary.name) / "chromium"
        path.write_text("test executable placeholder")
        self.assertEqual(self.worker.browser_path({"browser_executable": str(path)}), path)

    def test_missing_explicit_browser_does_not_fall_back_or_install(self):
        self.assertIsNone(self.worker.browser_path({"browser_executable": str(Path(self.temporary.name) / "missing-browser")}))

    def test_docker_secret_file_overrides_environment_key(self):
        path = Path(self.temporary.name) / "secret"
        path.write_text("x" * 48 + "\n")
        with patch.dict(os.environ, {"VIDEO_API_KEY_FILE": str(path), "VIDEO_API_KEY": "unused"}):
            self.assertEqual(self.worker.secret(), "x" * 48)

    def test_short_secret_is_rejected(self):
        path = Path(self.temporary.name) / "short-secret"
        path.write_text("short")
        with patch.dict(os.environ, {"VIDEO_API_KEY_FILE": str(path)}):
            with self.assertRaises(RuntimeError):
                self.worker.secret()


if __name__ == "__main__":
    unittest.main()
