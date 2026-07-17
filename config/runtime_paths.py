from __future__ import annotations

from pathlib import Path


DEFAULT_DEVICE_HOST = "192.168.1.198"
DEFAULT_DEVICE_PORT = 1600
DEFAULT_CALIBRATION_PROFILE = "calibration_profiles/20260705T144937_magnetometer_9param.json"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate
    repo_relative = project_root() / candidate
    if repo_relative.exists():
        return repo_relative
    return repo_relative


def relativize_to_project(path: str | Path | None) -> str:
    resolved = resolve_repo_path(path)
    if resolved is None:
        return ""
    root = project_root()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)
