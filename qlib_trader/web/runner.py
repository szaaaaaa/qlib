"""One isolated, real Qlib job. No Qlib imports occur when this module is imported.

The web server owns scheduling/state; this worker only creates safe exports and an
atomic result.json after success. Pickled Qlib artifacts stay in the private,
local MLflow store and are never accepted as request input or offered for download.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import threading
import sys
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

KINDS = {"train", "pipeline", "backtest", "inspect", "features"}
PREVIEW_ROWS = 100
SOURCE_FIELDS = (
    "region",
    "provider_uri",
    "market",
    "model",
    "handler",
    "train_start",
    "train_end",
    "valid_start",
    "valid_end",
    "test_start",
    "test_end",
    "model_kwargs",
    "handler_kwargs",
)


class JobError(RuntimeError):
    """An actionable worker failure displayed in the job log."""


def _uuid(value: Any) -> str:
    # The manager uses uuid4().hex, never a user-selected filesystem name.
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise JobError("Job identifier must be a 32-character lowercase UUID.")
    return value


def _contained(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise JobError("Job or artifact path escapes the console's private storage directory.") from exc
    return resolved


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise JobError(f"Missing or invalid console metadata: {path.name}")
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise JobError(f"Invalid console metadata: {path.name}")
    return value


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    # No state transition happens here; a successful rename is the completion marker.
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _validate_config(raw: dict):
    from qlib_trader.web.schema import WorkflowConfig

    return WorkflowConfig.model_validate(raw)


def _dump_config(config) -> dict:
    return config.model_dump(mode="json")


def _validate_query(query: Any, config) -> dict:
    """Apply the same AST/operator whitelist as the API before D.features."""
    from qlib_trader.web.schema import FeatureQuery

    if not isinstance(query, dict):
        raise JobError("Feature query requires instruments, fields, start_time and end_time.")
    validated = FeatureQuery.model_validate(query).model_dump(mode="json")
    validated["instruments"] = list(dict.fromkeys(validated["instruments"]))
    validated["fields"] = list(dict.fromkeys(validated["fields"]))
    return validated


def _initialize_qlib(workflow: dict, config, storage_dir: Path):
    provider = Path(config.provider_uri).expanduser().resolve()
    if not provider.is_dir():
        raise JobError(
            f"Qlib data directory does not exist: {provider}. Prepare Qlib binary market data first, then select its directory in the console."
        )
    if not (provider / "calendars" / "day.txt").is_file() or not (provider / "features").is_dir():
        raise JobError(
            f"Incomplete Qlib daily data in {provider}: calendars/day.txt and features/ are required. A directory of ordinary CSV prices is not a Qlib data bundle."
        )
    # A fixed exp_manager prevents environment variables / user config from sending
    # predictions, models, or labels to a remote tracking server.
    mlruns = _contained(storage_dir / "mlruns", storage_dir)
    mlruns.mkdir(parents=True, exist_ok=True)
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
    os.environ["MLFLOW_ENABLE_ASYNC_LOGGING"] = "false"
    os.environ["MLFLOW_TRACKING_URI"] = mlruns.as_uri()
    os.environ["MLFLOW_REGISTRY_URI"] = mlruns.as_uri()
    # An inherited MLflow run ID can otherwise make start_run resume another run.
    for key in ("MLFLOW_RUN_ID", "MLFLOW_EXPERIMENT_ID", "MLFLOW_EXPERIMENT_NAME"):
        os.environ.pop(key, None)
    import qlib
    from qlib.data import D
    from qlib.workflow import R

    init = dict(workflow["qlib_init"])
    init.update(
        provider_uri=str(provider),
        expression_cache=None,
        dataset_cache=None,
        kernels=1,
        auto_mount=False,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": mlruns.as_uri(), "default_exp_name": "qlib-console"},
        },
    )
    qlib.init(**init)
    R.set_uri(mlruns.as_uri())
    return D, R


def _calendar(D, start=None, end=None):
    values = D.calendar(start_time=start, end_time=end, freq="day")
    if len(values) == 0:
        raise JobError("No trading dates are available for this interval. Check provider_uri and the configured dates.")
    return values


def _preflight(D, config, kind: str) -> None:
    import pandas as pd

    dates = _calendar(D)
    segments = (
        ("train", config.train_start, config.train_end),
        ("valid", config.valid_start, config.valid_end),
        ("test", config.test_start, config.test_end),
    )
    if kind == "backtest":
        segments = segments[-1:]
    for name, start, end in segments:
        _calendar(D, start, end)
        if pd.Timestamp(start) < pd.Timestamp(dates[0]) or pd.Timestamp(end) > pd.Timestamp(dates[-1]):
            print(
                f"WARNING: {name} interval extends beyond available calendar {dates[0]}–{dates[-1]}; Qlib will use overlapping dates.",
                flush=True,
            )
    if kind in {"pipeline", "backtest"}:
        test_calendar = _calendar(D, config.test_start, config.test_end)
        if pd.Timestamp(test_calendar[-1]) >= pd.Timestamp(dates[-1]):
            raise JobError(
                "Backtesting requires one extra trading-calendar date after the final test date. Choose an earlier test_end or update the Qlib data bundle."
            )
    universe = D.list_instruments(
        D.instruments(config.market), start_time=config.test_start, end_time=config.test_end, freq="day", as_list=True
    )
    if not universe:
        raise JobError(
            f"No instruments in market {config.market!r} for the test interval. Check instruments/{config.market}.txt and the dates."
        )


def _flat_frame(value):
    import pandas as pd

    if isinstance(value, pd.Series):
        value = value.to_frame(value.name or "value")
    if not isinstance(value, pd.DataFrame):
        raise JobError("A required Qlib artifact is not a table. The run did not produce usable output.")
    frame = value.copy()
    frame.columns = [" / ".join(map(str, x)) if isinstance(x, tuple) else str(x) for x in frame.columns]
    # The index contains trading dates and instrument codes and belongs in exports.
    return frame.reset_index()


def _preview(value) -> dict:
    frame = _flat_frame(value)
    return {
        "columns": list(frame.columns),
        "rows": json.loads(frame.head(PREVIEW_ROWS).to_json(orient="records", date_format="iso")),
    }


def _csv(value, path: Path) -> None:
    _flat_frame(value).to_csv(path, index=False)


def _metrics(recorder) -> tuple[dict, list]:
    metrics, omitted = {}, []
    for key, value in recorder.list_metrics().items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            omitted.append(str(key))
            continue
        if math.isfinite(number):
            metrics[str(key)] = number
        else:
            omitted.append(str(key))
    return metrics, omitted


def _series(report) -> list:
    import pandas as pd
    import numpy as np

    if not isinstance(report, pd.DataFrame) or report.empty or not {"return", "bench", "cost"}.issubset(report.columns):
        raise JobError("Qlib did not produce a non-empty daily portfolio report with return, bench and cost columns.")
    report = report.sort_index()
    daily = report[["return", "bench", "cost"]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(daily.to_numpy()).all():
        raise JobError(
            "The daily report contains missing/non-finite returns, costs or benchmark prices. Check benchmark/data coverage; no performance curve was fabricated."
        )
    net = (daily["return"] - daily["cost"]).cumsum()
    benchmark = daily["bench"].cumsum()
    # Follow Qlib's arithmetic accumulation convention, after transaction costs.
    drawdown = net - net.cummax().clip(lower=0)
    return [
        {
            "date": pd.Timestamp(day).strftime("%Y-%m-%d"),
            "return": float(net.loc[day]),
            "benchmark": float(benchmark.loc[day]),
            "excess": float(net.loc[day] - benchmark.loc[day]),
            "drawdown": float(drawdown.loc[day]),
        }
        for day in report.index
    ]


def _trusted_recorder(recorder, storage_dir: Path) -> None:
    uri = urlparse(recorder.get_artifact_uri())
    if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
        raise JobError("Only recorder artifacts in this console's local MLflow store can be read.")
    _contained(Path(unquote(uri.path)), storage_dir / "mlruns")


def _collect(recorder, experiment_name: str, artifacts: Path, storage_dir: Path, include_backtest: bool) -> dict:
    import pandas as pd
    import numpy as np

    _trusted_recorder(recorder, storage_dir)
    pred = recorder.load_object("pred.pkl")
    label = recorder.load_object("label.pkl")
    if not isinstance(pred, (pd.DataFrame, pd.Series)) or pred.empty:
        raise JobError("Training produced no predictions. Check the test interval, instruments and model logs.")
    if not np.isfinite(pred.to_numpy(dtype=float)).any():
        raise JobError("All generated predictions are missing or non-finite. Check the model and data.")
    if not isinstance(label, pd.DataFrame) or label.empty:
        raise JobError(
            "Qlib produced no test labels. Check price coverage and allow future dates for the forward-return label."
        )
    _csv(pred, artifacts / "predictions.csv")
    _csv(label, artifacts / "labels.csv")
    for name, output in (("sig_analysis/ic.pkl", "signal_ic.csv"), ("sig_analysis/ric.pkl", "signal_rank_ic.csv")):
        _csv(recorder.load_object(name), artifacts / output)
    metrics, omitted = _metrics(recorder)
    result = {
        "recorder_id": recorder.id,
        "experiment_name": experiment_name,
        "metrics": metrics,
        "preview": _preview(pred),
        "series": [],
        "summary": {"prediction_rows": len(pred), "label_rows": len(label), "omitted_nonfinite_metrics": omitted},
    }
    if include_backtest:
        report = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
        risk = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")
        result["series"] = _series(report)
        _csv(report, artifacts / "portfolio_report.csv")
        _csv(risk, artifacts / "risk_analysis.csv")
        pd.DataFrame(result["series"]).to_csv(artifacts / "performance.csv", index=False)
        result["summary"].update(
            {
                "backtest_days": len(report),
                "return_convention": "Qlib arithmetic cumulative returns after transaction costs; excess subtracts benchmark. Drawdown is net strategy return below its running maximum, including the starting zero baseline.",
                "start_date": result["series"][0]["date"],
                "end_date": result["series"][-1]["date"],
            }
        )
    _atomic_json(artifacts / "metrics.json", metrics)
    return result


def _source_metadata(source_job_id: Any, config, job_dir: Path, storage_dir: Path) -> dict:
    source_id = _uuid(source_job_id)
    if source_id == job_dir.name:
        raise JobError("A backtest cannot use itself as its prediction source.")
    source_dir = _contained(storage_dir / "jobs" / source_id, storage_dir / "jobs")
    state = _read_json(source_dir / "state.json")
    request = _read_json(source_dir / "request.json")
    result = _read_json(source_dir / "result.json")
    if state.get("status") != "completed" or request.get("kind") not in {"train", "pipeline", "backtest"}:
        raise JobError("Backtests require a completed console job with saved predictions.")
    original = _validate_config(request["config"])
    for field in SOURCE_FIELDS:
        left, right = getattr(original, field), getattr(config, field)
        if field == "provider_uri":
            left, right = Path(left).expanduser().resolve(), Path(right).expanduser().resolve()
        if left != right:
            raise JobError(f"Source predictions do not match {field}; use the same source data and test interval.")
    if result.get("experiment_name") != f"console-{source_id}" or not re.fullmatch(
        r"[a-fA-F0-9]{32}", str(result.get("recorder_id", ""))
    ):
        raise JobError("Invalid recorder reference in the source console job.")
    return result


def _synchronous_recorder(recorder) -> None:
    """Drain Qlib's startup logger, then perform subsequent writes synchronously.

    Qlib's AsyncCaller decorator explicitly falls back to synchronous calls when
    async_log is None. Its wait() closes and joins the existing queue. File-store
    metric writes otherwise race with MLflow artifact checks, which read all run
    metrics and can see an empty, newly created metric file. Avoid that race at
    its source rather than retrying or discarding a malformed metric.
    """
    pending = getattr(recorder, "async_log", None)
    if pending is not None:
        pending.wait()
        recorder.async_log = None


def _train(workflow, config, R, experiment_name: str):
    # These are the repository's exact task_train implementation helpers. The
    # explicit recorder context provides the synchronous logging boundary before
    # model fitting and each SignalRecord/SigAnaRecord/PortAnaRecord is generated.
    from qlib.model.trainer import _log_task_info, _exe_task

    with R.start(experiment_name=experiment_name, recorder_name=config.name):
        recorder = R.get_recorder()
        _synchronous_recorder(recorder)
        _log_task_info(workflow["task"])
        _exe_task(workflow["task"])
    return recorder


def _backtest(workflow, config, source, R, experiment_name: str, storage_dir: Path):
    from qlib.workflow.record_temp import SigAnaRecord, PortAnaRecord

    records = workflow["task"]["record"]
    port_config = next((item.get("kwargs", {}) for item in records if item.get("class") == "PortAnaRecord"), None)
    if port_config is None:
        raise JobError("The validated workflow has no portfolio-analysis configuration.")
    old = R.get_recorder(recorder_id=source["recorder_id"], experiment_name=source["experiment_name"])
    _trusted_recorder(old, storage_dir)
    # Only locally generated predictions and labels are read. Never load a supplied
    # checkpoint, serialized dataset, user pickle, or arbitrary recorder path.
    pred, label = old.load_object("pred.pkl"), old.load_object("label.pkl")
    with R.start(experiment_name=experiment_name, recorder_name=config.name):
        recorder = R.get_recorder()
        _synchronous_recorder(recorder)
        recorder.save_objects(**{"pred.pkl": pred, "label.pkl": label})
        recorder.log_params(source_recorder_id=source["recorder_id"], source_experiment=source["experiment_name"])
        SigAnaRecord(recorder=recorder).generate()
        PortAnaRecord(recorder=recorder, **port_config).generate()
    return recorder


def _inspect(D, config, artifacts: Path) -> dict:
    import pandas as pd

    calendar = _calendar(D)
    instruments = D.list_instruments(D.instruments(config.market), freq="day", as_list=False)
    rows = [
        {"instrument": str(code), "start_date": str(start)[:10], "end_date": str(end)[:10]}
        for code, intervals in instruments.items()
        for start, end in intervals
    ]
    table = pd.DataFrame(rows, columns=["instrument", "start_date", "end_date"])
    table.to_csv(artifacts / "instruments.csv", index=False)
    pd.DataFrame({"date": [str(x)[:10] for x in calendar]}).to_csv(artifacts / "calendar.csv", index=False)
    return {
        "metrics": {},
        "series": [],
        "preview": _preview(table),
        "summary": {
            "calendar_count": len(calendar),
            "instrument_count": len(instruments),
            "start_date": str(calendar[0])[:10],
            "end_date": str(calendar[-1])[:10],
            "market": config.market,
            "provider_uri": str(Path(config.provider_uri).expanduser().resolve()),
            "warnings": [] if instruments else ["The selected market has no instruments."],
        },
    }


def _features(D, config, query: dict, artifacts: Path) -> dict:
    query = _validate_query(query, config)
    _calendar(D, query["start_time"], query["end_time"])
    frame = D.features(**query, freq="day", disk_cache=0)
    if frame.empty or frame.dropna(how="all").empty:
        raise JobError(
            "Feature query returned no observations. Check instrument codes, requested fields, and available dates."
        )
    _csv(frame, artifacts / "features.csv")
    return {
        "metrics": {},
        "series": [],
        "preview": _preview(frame),
        "summary": {
            "row_count": len(frame),
            "query": query,
            "preview_limit": PREVIEW_ROWS,
            "missing_values": int(frame.isna().sum().sum()),
        },
    }


def run_job(job_dir: Path, storage_dir: Path) -> dict:
    from qlib_trader.web.schema import build_workflow
    import yaml

    storage_dir = storage_dir.expanduser().resolve()
    supplied_job_dir = job_dir.expanduser()
    if supplied_job_dir.is_symlink():
        raise JobError("Symbolic-link job directories are not accepted.")
    job_dir = _contained(supplied_job_dir, storage_dir / "jobs")
    _uuid(job_dir.name)
    if job_dir.parent != (storage_dir / "jobs").resolve():
        raise JobError("Job directory must be a direct child of the console jobs directory.")
    if (job_dir / "result.json").exists():
        raise JobError("This job already has a result. Submit a new job rather than overwriting it.")
    request = _read_json(job_dir / "request.json")
    kind = request.get("kind")
    if kind not in KINDS:
        raise JobError("Unknown job kind.")
    config = _validate_config(request["config"])
    query = _validate_query(request.get("query"), config) if kind == "features" else None
    source = (
        _source_metadata(request.get("source_job_id"), config, job_dir, storage_dir) if kind == "backtest" else None
    )
    workflow = build_workflow(config, include_backtest=kind in {"pipeline", "backtest"})
    artifacts = _contained(job_dir / "artifacts", job_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    _atomic_json(artifacts / "config.json", _dump_config(config))
    (artifacts / "workflow.yaml").write_text(
        yaml.safe_dump(workflow, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"Starting real Qlib {kind} job {job_dir.name}", flush=True)
    D, R = _initialize_qlib(workflow, config, storage_dir)
    if kind == "inspect":
        result = _inspect(D, config, artifacts)
    elif kind == "features":
        result = _features(D, config, query, artifacts)
    else:
        _preflight(D, config, kind)
        experiment = f"console-{job_dir.name}"
        if kind == "backtest":
            recorder = _backtest(workflow, config, source, R, experiment, storage_dir)
        else:
            recorder = _train(workflow, config, R, experiment)
        result = _collect(recorder, experiment, artifacts, storage_dir, kind != "train")
        if source:
            result["summary"]["source_job_id"] = request["source_job_id"]
    _atomic_json(job_dir / "result.json", result)
    print(f"Completed {kind} job. Safe CSV/JSON/YAML exports are in {artifacts}.", flush=True)
    return result


def _start_parent_watchdog(parent_pid: int | None):
    """Stop an orphaned worker before a restarted manager can run another job.

    POSIX workers are session leaders, so termination includes their process group.
    On Windows an opened process handle pins the parent's identity across PID
    reuse; worker exit is guaranteed, but descendant-tree cleanup is best effort.
    """
    stop = threading.Event()
    if parent_pid is None:
        return stop
    if parent_pid <= 0 or parent_pid == os.getpid():
        raise JobError("Invalid parent process ID.")
    close_handle = lambda: None
    if os.name == "posix":
        alive = lambda: os.getppid() == parent_pid
    elif os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE
        if not handle:
            raise JobError("Cannot monitor the console parent process; refusing an unmonitored worker.")
        alive = lambda: kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        close_handle = lambda: kernel.CloseHandle(handle)
    else:
        raise JobError("Parent monitoring is unsupported on this operating system.")

    def watch():
        try:
            while not stop.is_set():
                if not alive():
                    print("Console parent exited; terminating this isolated worker.", file=sys.stderr, flush=True)
                    if os.name == "posix" and os.getpgrp() == os.getpid():
                        os.killpg(os.getpgrp(), signal.SIGTERM)
                    os._exit(1)
                stop.wait(0.5)
        finally:
            close_handle()

    threading.Thread(target=watch, name="console-parent-watchdog", daemon=True).start()
    return stop


def _run_locked(job_dir: Path, storage_dir: Path) -> dict:
    from filelock import FileLock, Timeout

    storage_dir = storage_dir.expanduser().resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(storage_dir / ".worker.lock"), timeout=15)
    try:
        lock.acquire()
    except Timeout as exc:
        raise JobError(
            "Another Qlib worker still owns this storage directory. Wait for it to stop before retrying; this job was not started concurrently."
        ) from exc
    try:
        return run_job(job_dir, storage_dir)
    finally:
        lock.release()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--storage-dir", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, help="Console process to monitor; omitted for standalone execution")
    args = parser.parse_args(argv)
    watchdog = None
    try:
        watchdog = _start_parent_watchdog(args.parent_pid)
        _run_locked(args.job_dir, args.storage_dir)
    except (ImportError, ModuleNotFoundError) as exc:
        print(
            f"Dependency error: {exc}. Install the repository's Qlib runtime dependencies in the same Python environment as this console (for a source checkout: python -m pip install -e '.[web]'). Some models need their optional package; choose Linear for a lighter baseline. If qlib.data._libs is missing, build/install the Qlib package first.",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        return 1
    except Exception as exc:
        print(f"Job failed: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1
    finally:
        if watchdog is not None:
            watchdog.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
