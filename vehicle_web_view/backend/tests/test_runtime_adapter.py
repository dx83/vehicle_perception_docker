from types import SimpleNamespace
import sys

from vehicle_web.runtime.engine_adapter import create_engine


def test_adapter_imports_sibling_package_and_enables_masks(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "_vehicle_live_runtime", raising=False)
    root = tmp_path / "runtime"; root.mkdir()
    (root / "__init__.py").write_text("from .engine import PerceptionEngine\n")
    (root / "engine.py").write_text(
        "class PerceptionEngine:\n    def __init__(self, config, return_masks=False):\n"
        "        self.config=config; self.return_masks=return_masks\n")
    config = tmp_path / "phone.yaml"
    settings = SimpleNamespace(runtime_root=root, runtime_config=config)
    try:
        engine = create_engine(settings)
        assert engine.config == config and engine.return_masks
    finally:
        sys.modules.pop("_vehicle_live_runtime", None)
        sys.modules.pop("_vehicle_live_runtime.engine", None)
