"""Queue lifecycle, durable state and subprocess boundaries."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from qlib_trader.web.jobs import JobStore, write_json
from qlib_trader.web.schema import WorkflowConfig


def request():
    return {
        "kind": "inspect",
        "config": WorkflowConfig(provider_uri="/definitely-not-a-qlib-bundle").model_dump(mode="json"),
    }


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(self.temp.name)

    def tearDown(self):
        if self.store.started:
            self.store.close()
        self.temp.cleanup()

    def test_restart_marks_unfinished_interrupted(self):
        job = self.store.create(request())
        self.store.start()
        current = self.store.get(job["id"])
        self.assertEqual(current["status"], "interrupted")
        self.assertIsNotNone(current["finished_at"])

    def test_duplicate_server_is_rejected(self):
        self.store.start()
        another = JobStore(self.temp.name)
        with self.assertRaisesRegex(RuntimeError, "已有控制台"):
            another.start()

    def test_queue_limit_and_cancel(self):
        ids = [self.store.create(request())["id"] for _ in range(32)]
        with self.assertRaises(ValueError):
            self.store.create(request())
        self.store.cancel(ids[0])
        self.store.create(request())
        self.assertEqual(len(self.store.list()), 33)

    def test_successful_process_commits_result_and_never_uses_shell(self):
        job = self.store.create(request())
        store = self.store

        class Process:
            returncode = 0

            def __init__(self, args, **kwargs):
                self.args, self.kwargs = args, kwargs
                write_json(store.path(job["id"]) / "result.json", {"metrics": {"IC": 0.1}})

            def poll(self):
                return 0

        with patch("qlib_trader.web.jobs.subprocess.Popen", side_effect=Process) as create:
            self.store._run(job["id"])
        result = self.store.get(job["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["metrics"]["IC"], 0.1)
        args, kwargs = create.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(args[0][2], "qlib_trader.web.runner")

    def test_process_launch_failure_does_not_claim_success(self):
        job = self.store.create(request())
        with patch("qlib_trader.web.jobs.subprocess.Popen", side_effect=OSError("cannot start")):
            self.store._run(job["id"])
        result = self.store.get(job["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("cannot start", result["error"])
        self.assertIsNone(result["result"])

    def test_real_subprocess_missing_data_is_failed_and_logged(self):
        self.store.start()
        job = self.store.create(request())
        deadline = time.monotonic() + 20
        while self.store.get(job["id"])["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
        result = self.store.get(job["id"])
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("does not exist", self.store.logs(job["id"])["text"])
        self.assertIsNone(result["result"])

    def test_log_offsets_and_artifact_traversal(self):
        job = self.store.create(request())
        (self.store.path(job["id"]) / "logs.txt").write_text("first\nsecond\n", encoding="utf-8")
        log = self.store.logs(job["id"], 6)
        self.assertEqual(log["text"], "second\n")
        self.assertEqual(self.store.logs(job["id"], log["next_offset"])["text"], "")
        for name in ("../state.json", ".hidden.json", "test.pkl", "nested/report.csv"):
            with self.subTest(name=name), self.assertRaises(KeyError):
                self.store.artifact(job["id"], name)

    def test_state_atomic_json_has_no_nan(self):
        destination = Path(self.temp.name) / "state.json"
        write_json(destination, {"test": 1})
        self.assertEqual(json.loads(destination.read_text()), {"test": 1})
        self.assertFalse(destination.with_suffix(".json.tmp").exists())
        with self.assertRaises(ValueError):
            write_json(destination, {"invalid": float("nan")})
