"""Read-only deployment preflight. Never downloads models or installs packages."""
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
import shutil
import sys

# ============================================================
# 옵션 항목
config_file = "config.yaml"
check_gpu = True
# ============================================================

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root / "src"))
from vehicle_web.common.engine_paths import load_settings


def main():
    settings = load_settings(backend_root / config_file)
    required = {"runtime __init__": settings.runtime_root / "__init__.py",
                "runtime engine": settings.runtime_root / "engine.py",
                "phone config": settings.runtime_config,
                "frontend build": settings.frontend_dist / "index.html"}
    for label, path in required.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label}: {path}")
    for name in ("aiortc", "av", "fastapi", "uvicorn", "websockets", "numpy", "opencv-python"):
        print(f"{name}={version(name)}")
    import cv2
    if not hasattr(cv2, "VideoCapture"):
        raise RuntimeError("OpenCV installation is incomplete or shadowed")
    print(f"camera_profile_verified={settings.camera_profile['verified']}")
    if check_gpu:
        import torch
        for name in ("ultralytics", "unidepth", "lap"):
            import_module(name)
            print(f"{name}={version(name)}")
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU unavailable; no CPU fallback enabled")
        print(f"gpu_logical_0={torch.cuda.get_device_name(0)}")
        if sys.platform.startswith("linux") and not (shutil.which("cc") or shutil.which("gcc")):
            raise RuntimeError("torch.compile requires a C compiler; install it manually")
    print("ENVIRONMENT_CHECK_PASSED (not an inference benchmark)")


if __name__ == "__main__":
    main()
