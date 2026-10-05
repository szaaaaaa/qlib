"""Exercise the real HTTP contract without Qlib installed or external network."""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from qlib_trader.web.api import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name, start_jobs=False)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.headers = {"X-Console-Token": self.client.get("/api/session").json()["csrf_token"]}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers=self.headers)

    def test_health_catalog_and_empty_state(self):
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        self.assertEqual(len(self.client.get("/api/catalog").json()["models"]), 8)
        self.assertEqual(self.client.get("/api/jobs").json(), {"items": []})
        self.assertEqual(self.client.get("/api/experiments").json(), {"items": []})

    def test_config_validate_save_and_reload(self):
        validated = self.post("/api/config/validate", {"name": "测试策略", "model": "linear"})
        self.assertEqual(validated.status_code, 200, validated.text)
        self.assertIn("LinearModel", validated.json()["yaml"])
        saved = self.post("/api/configs", validated.json()["config"])
        self.assertEqual(saved.status_code, 201, saved.text)
        self.assertEqual(self.client.get("/api/configs").json()["items"][0]["name"], "测试策略")

    def test_validation_error_is_actionable(self):
        result = self.post("/api/config/validate", {"n_drop": 100})
        self.assertEqual(result.status_code, 422)
        self.assertIn("topk", result.text)

    def test_csrf_origin_host_and_size_protection(self):
        self.assertEqual(self.client.post("/api/configs", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/session", headers={"Origin": "https://evil.test"}).status_code, 403)
        self.assertEqual(self.client.get("/api/session", headers={"Host": "evil.test"}).status_code, 403)
        self.assertEqual(self.client.get("/api/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        result = self.client.post("/api/configs", content=b"x" * (129 * 1024), headers=self.headers)
        self.assertEqual(result.status_code, 413)
        self.assertEqual(self.client.get("/api/session").headers["X-Frame-Options"], "DENY")

    def test_job_persistence_and_idempotent_cancel(self):
        response = self.post("/api/jobs", {"kind": "train", "config": {"name": "训练测试"}})
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}').json()["name"], "训练测试")
        self.assertEqual(self.post(f'/api/jobs/{job["id"]}/cancel').json()["status"], "cancelled")
        first = self.client.get(f'/api/jobs/{job["id"]}').json()
        self.assertEqual(self.post(f'/api/jobs/{job["id"]}/cancel').json(), first)
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/logs').json(), {"text": "", "next_offset": 0})
        self.assertEqual(
            json.loads((Path(self.temp.name) / "jobs" / job["id"] / "state.json").read_text())["status"], "cancelled"
        )

    def test_artifact_download_containment_and_types(self):
        job = self.post("/api/jobs", {"kind": "train", "config": {}}).json()
        directory = Path(self.temp.name) / "jobs" / job["id"] / "artifacts"
        (directory / "metrics.json").write_text('{"IC": 0.1}')
        (directory / "untrusted.pkl").write_bytes(b"not downloadable")
        (directory / "linked.txt").symlink_to(Path(self.temp.name) / ".console.lock")
        items = self.client.get(f'/api/jobs/{job["id"]}/artifacts').json()["items"]
        self.assertEqual([item["name"] for item in items], ["metrics.json"])
        self.assertEqual(self.client.get(items[0]["url"]).json(), {"IC": 0.1})
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/artifacts/untrusted.pkl').status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/not-an-id").status_code, 404)

    def test_backtest_requires_completed_prediction_source(self):
        source = self.post("/api/jobs", {"kind": "train", "config": {}}).json()
        response = self.post("/api/jobs", {"kind": "backtest", "config": {}, "source_job_id": source["id"]})
        self.assertEqual(response.status_code, 422)
        source.update(status="completed", result={"recorder_id": "a" * 32})
        self.app.state.store._save(source)
        changed = self.post(
            "/api/jobs", {"kind": "backtest", "config": {"market": "csi500"}, "source_job_id": source["id"]}
        )
        self.assertEqual(changed.status_code, 422)
        wrong_model = self.post(
            "/api/jobs", {"kind": "backtest", "config": {"model": "transformer"}, "source_job_id": source["id"]}
        )
        self.assertEqual(wrong_model.status_code, 422)
        self.assertEqual(
            self.post(
                "/api/jobs", {"kind": "backtest", "config": {"topk": 20}, "source_job_id": source["id"]}
            ).status_code,
            202,
        )

    def test_data_missing_and_structural_fixture(self):
        path = Path(self.temp.name) / "data"
        response = self.client.get("/api/data/status", params={"provider_uri": str(path)})
        self.assertFalse(response.json()["ready"])
        for folder in ("calendars", "instruments", "features/sh600000"):
            (path / folder).mkdir(parents=True)
        (path / "calendars/day.txt").write_text("2020-01-01\n2020-01-02\n")
        (path / "instruments/all.txt").write_text("SH600000\t2020-01-01\t2020-01-02\n")
        data = self.client.get("/api/data/status", params={"provider_uri": str(path)}).json()
        self.assertTrue(data["ready"])
        self.assertEqual(data["calendar_count"], 2)
        self.assertTrue(data["warnings"])
