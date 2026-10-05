"""Durable single-worker job queue with per-task process isolation."""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from .schema import JOB_ID

ACTIVE = {"queued", "running"}
MAX_LOG_BYTES = 32 * 1024 * 1024
MAX_RUNTIME = 6 * 60 * 60


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class JobStore:
    """One queue per storage directory. Never share a store across Uvicorn workers."""

    def __init__(self, storage_dir, python_executable=None):
        self.root = Path(storage_dir).expanduser().resolve()
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.python = python_executable or sys.executable
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.worker = None
        self.process = None
        self.process_id = None
        self.owner = FileLock(str(self.root / ".console.lock"))
        self.started = False

    def start(self):
        try:
            self.owner.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError("此存储目录已有控制台运行；请关闭它或使用不同的 --storage-dir") from exc
        self.started = True
        with self.lock:
            for job in self.list():
                if job["status"] in ACTIVE:
                    job.update(
                        status="interrupted",
                        finished_at=now(),
                        error="上次服务停止，任务未完成；请检查日志后重新运行。",
                    )
                    self._save(job)
        self.worker = threading.Thread(target=self._loop, name="qlib-console-queue", daemon=True)
        self.worker.start()

    def close(self):
        self.stopping.set()
        self.wake.set()
        with self.lock:
            if self.process is not None:
                self._terminate(self.process)
        if self.worker:
            self.worker.join(timeout=10)
        with self.lock:
            for job in self.list():
                if job["status"] in ACTIVE:
                    job.update(status="interrupted", finished_at=now(), error="控制台已关闭，任务已停止。")
                    self._save(job)
        if self.started:
            self.owner.release()
            self.started = False

    def path(self, job_id):
        if not JOB_ID.fullmatch(job_id):
            raise KeyError(job_id)
        path = self.jobs_dir / job_id
        if path.is_symlink():
            raise KeyError(job_id)
        return path

    def _save(self, job):
        write_json(self.path(job["id"]) / "state.json", job)

    def get(self, job_id):
        try:
            with self.lock:
                return json.loads((self.path(job_id) / "state.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            raise KeyError(job_id) from exc

    def list(self):
        jobs = []
        with self.lock:
            for path in self.jobs_dir.glob("*/state.json"):
                if JOB_ID.fullmatch(path.parent.name) and not path.parent.is_symlink():
                    try:
                        jobs.append(json.loads(path.read_text(encoding="utf-8")))
                    except (OSError, json.JSONDecodeError):
                        continue
        return sorted(jobs, key=lambda item: item["created_at"], reverse=True)

    def create(self, request):
        with self.lock:
            if sum(job["status"] in ACTIVE for job in self.list()) >= 32:
                raise ValueError("最多保留 32 个排队/运行任务，请等待完成后重试")
            job_id = uuid.uuid4().hex
            directory = self.path(job_id)
            directory.mkdir()
            (directory / "artifacts").mkdir()
            write_json(directory / "request.json", request)
            job = {
                "id": job_id,
                "name": request["config"]["name"],
                "kind": request["kind"],
                "status": "queued",
                "created_at": now(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "config": request["config"],
                "source_job_id": request.get("source_job_id"),
                "result": None,
            }
            self._save(job)
            self.wake.set()
            return job

    @staticmethod
    def _terminate(process):
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=3)
        except ProcessLookupError:
            pass

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job["status"] not in ACTIVE:
                return job  # idempotent: repeated cancel never rewrites a result
            job.update(status="cancelled", finished_at=now(), error="用户取消了任务")
            self._save(job)
            if self.process_id == job_id and self.process is not None:
                self._terminate(self.process)
            return job

    def _loop(self):
        while not self.stopping.is_set():
            with self.lock:
                waiting = [job for job in reversed(self.list()) if job["status"] == "queued"]
            if not waiting:
                self.wake.wait(timeout=1)
                self.wake.clear()
                continue
            self._run(waiting[0]["id"])

    def _run(self, job_id):
        directory = self.path(job_id)
        try:
            with self.lock:
                job = self.get(job_id)
                if job["status"] != "queued" or self.stopping.is_set():
                    return
                job.update(status="running", started_at=now())
                self._save(job)
                log_file = (directory / "logs.txt").open("ab", buffering=0)
                package_root = str(Path(__file__).resolve().parents[2])
                env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
                env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
                env.setdefault("OMP_NUM_THREADS", "4")
                env.setdefault("MKL_NUM_THREADS", "4")
                try:
                    process = subprocess.Popen(
                        [
                            self.python,
                            "-m",
                            "qlib_trader.web.runner",
                            "--job-dir",
                            str(directory),
                            "--storage-dir",
                            str(self.root),
                            "--parent-pid",
                            str(os.getpid()),
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        cwd=str(self.root),
                        env=env,
                        start_new_session=os.name == "posix",
                    )
                except Exception:
                    log_file.close()
                    raise
                self.process, self.process_id = process, job_id
            started = time.monotonic()
            limit_error = None
            try:
                while process.poll() is None:
                    if time.monotonic() - started > MAX_RUNTIME:
                        limit_error = "任务超过 6 小时运行上限，已停止"
                    elif (directory / "logs.txt").stat().st_size > MAX_LOG_BYTES:
                        limit_error = "任务日志超过 32 MiB 上限，已停止"
                    if limit_error or self.stopping.is_set():
                        self._terminate(process)
                    time.sleep(0.1)
            finally:
                log_file.close()
            with self.lock:
                self.process, self.process_id = None, None
                job = self.get(job_id)
                if job["status"] != "running":
                    return
                if self.stopping.is_set():
                    job.update(status="interrupted", error="控制台已关闭，任务已停止")
                elif process.returncode == 0 and (directory / "result.json").exists() and not limit_error:
                    job.update(
                        status="completed", result=json.loads((directory / "result.json").read_text(encoding="utf-8"))
                    )
                else:
                    job.update(
                        status="failed", error=limit_error or "任务执行失败，请查看日志中的依赖、数据或参数错误。"
                    )
                job["finished_at"] = now()
                self._save(job)
        except Exception as exc:
            with self.lock:
                self.process, self.process_id = None, None
                job = self.get(job_id)
                if job["status"] in ACTIVE:
                    job.update(status="failed", error=f"无法运行任务: {exc}", finished_at=now())
                    self._save(job)

    def logs(self, job_id, offset=0):
        self.get(job_id)
        path = self.path(job_id) / "logs.txt"
        if not path.exists():
            return {"text": "", "next_offset": 0}
        with path.open("rb") as stream:
            stream.seek(min(offset, path.stat().st_size))
            content = stream.read(65536)
            next_offset = stream.tell()
        return {"text": content.decode("utf-8", errors="replace"), "next_offset": next_offset}

    def artifact(self, job_id, name):
        self.get(job_id)
        if (
            Path(name).name != name
            or name.startswith(".")
            or Path(name).suffix not in {".csv", ".json", ".yaml", ".txt"}
        ):
            raise KeyError(name)
        root = self.path(job_id) / "artifacts"
        path = root / name
        if not path.is_file() or path.is_symlink() or path.resolve().parent != root.resolve():
            raise KeyError(name)
        return path

    def artifacts(self, job_id):
        self.get(job_id)
        items = []
        for path in (self.path(job_id) / "artifacts").iterdir():
            try:
                self.artifact(job_id, path.name)
            except KeyError:
                continue
            items.append(
                {"name": path.name, "size": path.stat().st_size, "url": f"/api/jobs/{job_id}/artifacts/{path.name}"}
            )
        return {"items": sorted(items, key=lambda item: item["name"])}
