"""Run with ``python -m qlib_trader.web`` from the repository root."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Qlib 本地可视化研究控制台（不连接实盘）")
    parser.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--storage-dir", type=Path, default=Path.home() / ".qlib" / "console")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port 必须在 1–65535 之间")
    try:
        import uvicorn
        from .api import create_app
    except ImportError as exc:
        parser.exit(1, f"控制台依赖不完整: {exc}\n请运行 python -m pip install -r qlib_trader/web/requirements.txt\n")
    print(f"Qlib 控制台: http://{'[::1]' if args.host == '::1' else args.host}:{args.port}")
    print("仅用于本机量化研究。按 Ctrl+C 停止服务及运行中的任务。")
    uvicorn.run(create_app(args.storage_dir), host=args.host, port=args.port, workers=1, proxy_headers=False)


if __name__ == "__main__":
    main()
