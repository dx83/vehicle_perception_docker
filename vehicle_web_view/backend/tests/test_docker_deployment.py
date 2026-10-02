from pathlib import Path
import runpy

import pytest
import yaml

from vehicle_web.common.engine_paths import load_settings
from vehicle_web.common.engine_server_options import read_server_port


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("value", ["18000", "18001", "65535", " 19000 "])
def test_custom_port(value):
    assert read_server_port(environ={"VEHICLE_HTTP_PORT": value}) == int(value)


@pytest.mark.parametrize("value", ["", "abc", "0", "-1", "80", "65536", "18000,18001"])
def test_invalid_port(value):
    with pytest.raises(ValueError): read_server_port(environ={"VEHICLE_HTTP_PORT": value})


def test_default_port():
    assert read_server_port(environ={}) == 8000


def test_server_runner_uses_port_environment_and_one_worker(monkeypatch):
    import uvicorn
    calls = []
    monkeypatch.setenv("VEHICLE_HTTP_PORT", "18123")
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: calls.append(options))
    runner = runpy.run_path(str(ROOT / "vehicle_web_view/backend/scripts/server/extract_run_server.py"))
    runner["main"]()
    assert calls[0]["port"] == 18123 and calls[0]["workers"] == 1


def test_healthcheck_uses_same_port(monkeypatch):
    import io
    runner = runpy.run_path(str(ROOT / "vehicle_web_view/backend/scripts/environment/extract_healthcheck.py"))
    calls = []
    monkeypatch.setenv("VEHICLE_HTTP_PORT", "18123")
    def fake_open(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(b'{"status":"ok"}')
    monkeypatch.setitem(runner["main"].__globals__, "urlopen", fake_open)
    runner["main"]()
    assert calls == [("http://127.0.0.1:18123/api/health", 3)]


def test_compose_is_single_gpu_host_network_and_read_only():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    service = compose["services"]["perception"]
    assert service["network_mode"] == "host" and "ports" not in service
    assert service["read_only"] and service["user"] == "10001:10001"
    assert "container_name" not in service
    gpu = service["deploy"]["resources"]["reservations"]["devices"][0]
    assert gpu["capabilities"] == ["gpu"] and len(gpu["device_ids"]) == 1
    assert "count" not in gpu
    for mount in service["volumes"]:
        assert mount["read_only"] and not mount["bind"]["create_host_path"]
        assert (ROOT / mount["source"]).exists()


def test_runtime_and_model_paths_resolve_inside_delivery():
    settings = load_settings()
    assert settings.runtime_root.is_relative_to(ROOT)
    assert settings.runtime_root.joinpath("engine.py").is_file()
    raw = yaml.safe_load(settings.runtime_config.read_text())
    model_root = (settings.runtime_config.parent / raw["paths"]["model_root"]).resolve()
    assert model_root == ROOT / "models"
    assert (model_root / raw["models"]["segmentation"]).is_file()
    for name in ("config.json", "model.safetensors"):
        assert (model_root / raw["models"]["depth"] / name).is_file()
    assert settings.camera_profile["verified"] is False
    assert raw["camera"]["intrinsic"] is None


def test_docker_image_excludes_assets_and_uses_locked_build():
    dockerfile = (ROOT / "Dockerfile").read_text()
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert "models/" in ignore and "vehicle_perception_runtime_fix/" in ignore
    assert "COPY models" not in dockerfile and "COPY . ." not in dockerfile
    assert "uv sync --locked --extra gpu --no-dev" in dockerfile
    assert "npm ci" in dockerfile and "USER 10001:10001" in dockerfile
    assert "python3.12-dev" in dockerfile and "build-essential" in dockerfile


def test_manifest_detects_content_changes(tmp_path):
    namespace = runpy.run_path(str(ROOT / "scripts/deployment/extract_verify_bundle.py"))
    (tmp_path / "code.py").write_text("pass\n")
    namespace["create_manifest"](tmp_path)
    assert namespace["verify_manifest"](tmp_path)["files_excluding_manifest"] == 1
    (tmp_path / "code.py").write_text("raise RuntimeError\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        namespace["verify_manifest"](tmp_path)


def test_manifest_detects_missing_assets_and_blocks_overwrite(tmp_path):
    namespace = runpy.run_path(str(ROOT / "scripts/deployment/extract_verify_bundle.py"))
    (tmp_path / "code.py").write_text("pass\n")
    namespace["create_manifest"](tmp_path)
    with pytest.raises(FileExistsError): namespace["create_manifest"](tmp_path)
    (tmp_path / "code.py").unlink()
    with pytest.raises(ValueError, match="file set mismatch"):
        namespace["verify_manifest"](tmp_path)
