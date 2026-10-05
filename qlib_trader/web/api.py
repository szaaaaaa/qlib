"""Loopback-only JSON API and static assets for the local research console."""

import importlib.metadata
import json
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .jobs import ACTIVE, JobStore, now, write_json
from .schema import (
    DEPENDENCIES,
    JOB_ID,
    SOURCE_FIELDS,
    JobRequest,
    WorkflowConfig,
    available,
    build_workflow,
    catalog,
    config_warnings,
)

STATIC = Path(__file__).parent / "static"
HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
CORE_MODULES = [
    "setuptools_scm",
    "ruamel.yaml",
    "redis",
    "redis_lock",
    "dill",
    "fire",
    "pymongo",
    "mlflow",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "pyarrow",
    "filelock",
    "loguru",
    "joblib",
    "tqdm",
    "matplotlib",
]


def data_status(provider_uri, region="cn"):
    config = WorkflowConfig(provider_uri=provider_uri, region=region)
    path = Path(config.provider_uri).expanduser().resolve()
    result = {
        "provider_uri": str(path),
        "exists": path.is_dir(),
        "ready": False,
        "calendar_count": 0,
        "instrument_count": 0,
        "feature_count": 0,
        "start_date": None,
        "end_date": None,
        "warnings": [],
    }
    if not path.is_dir():
        result["warnings"].append("数据目录不存在。请先准备 Qlib 二进制数据，再指定其本地目录。")
        return result

    def read_lines(file):
        if not file.is_file() or file.is_symlink():
            return []
        if file.stat().st_size > 16 * 1024 * 1024:
            result["warnings"].append(f"{file.name} 超过检查大小限制")
            return []
        return [
            line.strip() for line in file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()
        ]

    calendar = read_lines(path / "calendars" / "day.txt")
    if calendar:
        result.update(calendar_count=len(calendar), start_date=calendar[0], end_date=calendar[-1])
    universe = read_lines(path / "instruments" / "all.txt")
    result["instrument_count"] = len(universe)
    features = path / "features"
    if features.is_dir() and not features.is_symlink():
        result["feature_count"] = sum(1 for entry in features.iterdir() if entry.is_dir() and not entry.is_symlink())
    result["ready"] = bool(calendar and universe and result["feature_count"])
    if not result["ready"]:
        result["warnings"].append("缺少日历、all.txt 证券列表或 features 目录；结构检查尚未通过。")
    result["warnings"].append("这是结构检查；数据内容、所选股票池及时间覆盖由“深度检查”验证。")
    return result


def create_app(storage_dir=None, start_jobs=True):
    """Create a single-user app. ``start_jobs=False`` is for isolated API tests."""
    store = JobStore(storage_dir or Path.home() / ".qlib" / "console")
    csrf_token = secrets.token_urlsafe(32)
    configs_dir = store.root / "configs"
    configs_dir.mkdir(exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        if start_jobs:
            store.start()
        try:
            yield
        finally:
            if start_jobs:
                store.close()

    app = FastAPI(title="QLib Research Console", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store = store

    @app.middleware("http")
    async def protect_local_console(request: Request, call_next):
        # No CORS. A hostile public page cannot discover the token or POST to
        # localhost. Host validation also blocks DNS rebinding.
        host = request.url.hostname
        if host not in HOSTS:
            return JSONResponse({"detail": "控制台只接受 localhost / 127.0.0.1 请求"}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != request.url.netloc:
                return JSONResponse({"detail": "不允许跨站访问本地控制台"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "不允许跨站请求"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 128 * 1024:
            return JSONResponse({"detail": "请求体过大"}, status_code=413)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not secrets.compare_digest(request.headers.get("x-console-token", ""), csrf_token):
                return JSONResponse({"detail": "会话已过期，请刷新页面后重试"}, status_code=403)
            # Chunked bodies do not have content-length. Bound them too.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 128 * 1024:
                    return JSONResponse({"detail": "请求体过大"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.exception_handler(KeyError)
    async def missing_item(request, exc):
        return JSONResponse({"detail": "任务或文件不存在"}, status_code=404)

    @app.get("/api/session")
    def session():
        return {"csrf_token": csrf_token}

    @app.get("/api/catalog")
    def get_catalog():
        return catalog()

    @app.get("/api/health")
    def health():
        dependencies = {module: available(module) for module in set(CORE_MODULES + list(DEPENDENCIES.values()))}
        missing = [module for module in CORE_MODULES if not dependencies[module]]
        try:
            qlib_version = importlib.metadata.version("pyqlib")
        except importlib.metadata.PackageNotFoundError:
            qlib_version = "source checkout"
        # Imports happen in workers, never in this process. Probe compiled modules
        # by path, because find_spec on qlib.* eagerly imports its parent package.
        qlib_package = Path(__file__).resolve().parents[2] / "qlib" / "data" / "_libs"
        has_extensions = bool(list(qlib_package.glob("rolling*.so")) or list(qlib_package.glob("rolling*.pyd")))
        if not has_extensions:
            # An installed Qlib wheel can be located outside this source checkout.
            try:
                spec = __import__("importlib.util", fromlist=["find_spec"]).find_spec("qlib")
                if spec and spec.submodule_search_locations:
                    libs = Path(next(iter(spec.submodule_search_locations))) / "data" / "_libs"
                    has_extensions = bool(list(libs.glob("rolling*.so")) or list(libs.glob("rolling*.pyd")))
            except (ImportError, ValueError):
                pass
        if not has_extensions:
            missing.append("Qlib Cython 扩展 (请安装 pip install -e .)")
        return {
            "status": "ok",
            "version": __version__,
            "python": sys.version.split()[0],
            "qlib_version": qlib_version,
            "qlib_available": not missing,
            "qlib_error": "缺少: " + ", ".join(missing) if missing else None,
            "dependencies": dependencies,
            "active_jobs": sum(job["status"] in ACTIVE for job in store.list()),
            "storage_dir": str(store.root),
        }

    @app.get("/api/data/status")
    def get_data_status(
        provider_uri: str = Query(default="~/.qlib/qlib_data/cn_data", max_length=1024), region: str = "cn"
    ):
        try:
            return data_status(provider_uri, region)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(400, f"无法读取数据目录: {exc}") from exc

    @app.post("/api/config/validate")
    def validate_config(config: WorkflowConfig):
        workflow = build_workflow(config)
        return {
            "config": config.model_dump(mode="json"),
            "workflow": workflow,
            "yaml": yaml.safe_dump(workflow, allow_unicode=True, sort_keys=False),
            "warnings": config_warnings(config),
        }

    @app.get("/api/configs")
    def configs():
        items = []
        for path in configs_dir.glob("*.json"):
            if not path.is_symlink():
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                    WorkflowConfig.model_validate(item["config"])
                    items.append(item)
                except (OSError, ValueError, KeyError):
                    continue
        return {"items": sorted(items, key=lambda item: item["updated_at"], reverse=True)}

    @app.post("/api/configs", status_code=201)
    def save_config(config: WorkflowConfig):
        item = {
            "id": uuid.uuid4().hex,
            "name": config.name,
            "updated_at": now(),
            "config": config.model_dump(mode="json"),
        }
        write_json(configs_dir / (item["id"] + ".json"), item)
        return item

    @app.get("/api/jobs")
    def jobs():
        return {"items": store.list()}

    @app.post("/api/jobs", status_code=202)
    def create_job(request: JobRequest):
        if request.kind == "backtest":
            source = store.get(request.source_job_id)
            if (
                source["status"] != "completed"
                or source["kind"] not in {"train", "pipeline"}
                or not (source.get("result") or {}).get("recorder_id")
            ):
                raise HTTPException(422, "请选择成功完成的训练/流水线实验作为预测源")
            for key in SOURCE_FIELDS:
                if source["config"][key] != request.config.model_dump(mode="json")[key]:
                    raise HTTPException(422, f"回测的 {key} 必须与预测源一致；修改策略和费用后可重新回测")
        try:
            return store.create(request.model_dump(mode="json"))
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return store.get(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return store.cancel(job_id)

    @app.get("/api/jobs/{job_id}/logs")
    def logs(job_id: str, offset: int = Query(default=0, ge=0, le=2**40)):
        return store.logs(job_id, offset)

    @app.get("/api/jobs/{job_id}/artifacts")
    def artifacts(job_id: str):
        return store.artifacts(job_id)

    @app.get("/api/jobs/{job_id}/artifacts/{name}")
    def artifact(job_id: str, name: str):
        path = store.artifact(job_id, name)
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.get("/api/experiments")
    def experiments():
        return {
            "items": [
                job
                for job in store.list()
                if job["status"] == "completed" and (job.get("result") or {}).get("recorder_id")
            ]
        }

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app
