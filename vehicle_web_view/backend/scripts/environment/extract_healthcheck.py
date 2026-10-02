"""Probe the configured HTTP port; no files or GPU initialization."""
import json
from pathlib import Path
import sys
from urllib.request import urlopen

# ============================================================
# 옵션 항목
default_port = 8000
timeout_sec = 3
# ============================================================

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root / "src"))
from vehicle_web.common.engine_server_options import read_server_port


def main():
    port = read_server_port(default=default_port)
    with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout_sec) as response:
        body = json.load(response)
    if body.get("status") != "ok":
        raise RuntimeError("HTTP healthcheck failed")


if __name__ == "__main__":
    main()
