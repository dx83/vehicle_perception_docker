"""Generate/verify deployment metadata; unrelated to the inference engine."""
import hashlib
import json
from pathlib import Path

# ============================================================
# 옵션 항목
generate_manifest = False
# ============================================================

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = BUNDLE_ROOT / "manifest.json"
EXCLUDED_DIRS = {".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", ".git"}


def included_files(root):
    return sorted(path for path in root.rglob("*") if path.is_file()
                  and path.relative_to(root).as_posix() != "manifest.json"
                  and not set(path.relative_to(root).parts) & EXCLUDED_DIRS
                  and path.suffix != ".pyc")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create_manifest(root=BUNDLE_ROOT):
    manifest = root / "manifest.json"
    if manifest.exists():
        raise FileExistsError("manifest already exists; do not overwrite an existing delivery")
    files = []
    for path in included_files(root):
        relative = path.relative_to(root).as_posix()
        original = root.parent / relative
        if relative.startswith("models/"):
            original = root.parent / "cp-model" / relative
        source_hash = sha256(original) if original.is_file() else None
        digest = sha256(path)
        files.append({"path": relative, "size_bytes": path.stat().st_size,
                      "sha256": digest, "classification": "NEW",
                      "source_sha256": source_hash,
                      "copy_state": ("EXACT_COPY" if source_hash == digest else
                                     "ADAPTED_COPY" if source_hash else "NEW_FILE")})
    data = {
        "format": 1, "package": "vehicle_perception_docker",
        "delivery_type": "USER_REQUESTED_SELF_CONTAINED_FOLDER",
        "new_files": [item["path"] for item in files], "modified_files": [],
        "files_to_remove": [], "unbundled_required_assets": [],
        "files": files, "file_count_excluding_manifest": len(files),
        "total_bytes_excluding_manifest": sum(item["size_bytes"] for item in files),
        "manifest_self_hash": "excluded to avoid a circular checksum",
    }
    manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def verify_manifest(root=BUNDLE_ROOT):
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in data["files"]}
    actual = {path.relative_to(root).as_posix(): path for path in included_files(root)}
    if set(expected) != set(actual):
        raise ValueError(f"bundle file set mismatch: missing={sorted(set(expected)-set(actual))}, "
                         f"extra={sorted(set(actual)-set(expected))}")
    for name, path in actual.items():
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"bundle path is not self-contained: {name}")
        if path.stat().st_size != expected[name]["size_bytes"] or sha256(path) != expected[name]["sha256"]:
            raise ValueError(f"checksum mismatch: {name}")
    count = len(actual)
    size = sum(path.stat().st_size for path in actual.values())
    if count != data["file_count_excluding_manifest"] or size != data["total_bytes_excluding_manifest"]:
        raise ValueError("manifest totals mismatch")
    return {"status": "BUNDLE_VERIFIED", "files_excluding_manifest": count,
            "bytes_excluding_manifest": size,
            "files_including_manifest": count + 1,
            "bytes_including_manifest": size + (root / "manifest.json").stat().st_size}


def main():
    if generate_manifest:
        create_manifest()
    print(json.dumps(verify_manifest(), indent=2))


if __name__ == "__main__":
    main()
