from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from .settings import AppConfig, app_config_from_dict


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("配置文件顶层必须是字典")
    return app_config_from_dict(data)


def load_merged_config(default_path: str | Path, user_path: str | Path | None = None) -> AppConfig:
    base = load_config_dict(default_path)
    if user_path is not None and Path(user_path).exists():
        override = load_config_dict(user_path)
        base = _deep_merge_dict(base, override)
    return app_config_from_dict(base)

def save_config(config: AppConfig, path: str | Path) -> None:
    config.validate()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(asdict(config), f, allow_unicode=True, sort_keys=False)

def validate_config(config: AppConfig) -> None:
    config.validate()


def load_config_dict(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("配置文件顶层必须是字典")
    return data


def _deep_merge_dict(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged
