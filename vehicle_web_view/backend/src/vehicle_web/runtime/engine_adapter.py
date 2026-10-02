"""Load the existing sibling runtime without copying or modifying it."""
import importlib.util
from pathlib import Path
import sys


def create_engine(settings):
    root = settings.runtime_root
    if not all((root / name).is_file() for name in ("__init__.py", "engine.py")):
        raise FileNotFoundError(f"runtime package not found: {root}")
    name = "_vehicle_live_runtime"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, root / "__init__.py", submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    module = sys.modules[name]
    if Path(module.__file__).parent.resolve() != root:
        raise RuntimeError("runtime root changed inside one server process")
    return module.PerceptionEngine(settings.runtime_config, return_masks=True)
