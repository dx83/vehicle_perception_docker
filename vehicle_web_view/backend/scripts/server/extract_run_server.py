"""Run one GPU-owning process. Options are edited here, not CLI flags."""
from pathlib import Path
import sys

# ============================================================
# 옵션 항목
host = "0.0.0.0"
port = 8000
config_file = "config.yaml"
# ============================================================

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root / "src"))

from vehicle_web.api.engine_app import create_app
from vehicle_web.common.engine_paths import load_settings
from vehicle_web.common.engine_server_options import read_server_port
import uvicorn


def main():
    settings = load_settings(backend_root / config_file)
    selected_port = read_server_port(default=port)
    uvicorn.run(create_app(settings), host=host, port=selected_port, workers=1,
                access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
