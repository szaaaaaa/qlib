"""Keep the existing core-Qlib matrix independent of optional console packages."""

import importlib.util

# Existing `pip install -e .[dev]` jobs need not install the web extra. The
# dedicated visual-console CI installs it and collects this complete suite.
if any(importlib.util.find_spec(name) is None for name in ("fastapi", "httpx", "pydantic", "filelock")):
    collect_ignore_glob = ["test_*.py"]
