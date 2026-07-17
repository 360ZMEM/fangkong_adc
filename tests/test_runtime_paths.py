from __future__ import annotations

from config.runtime_paths import (
    DEFAULT_CALIBRATION_PROFILE,
    DEFAULT_DEVICE_HOST,
    project_root,
    resolve_repo_path,
)
from config.settings import AppConfig
from core.acquisition_controller import AcquisitionController


def test_default_host_stays_standalone_default():
    cfg = AppConfig()
    assert cfg.network.host == DEFAULT_DEVICE_HOST


def test_default_calibration_profile_exists():
    resolved = resolve_repo_path(DEFAULT_CALIBRATION_PROFILE)
    assert resolved is not None
    assert resolved.exists()


def test_controller_loads_relative_default_calibration_profile():
    cfg = AppConfig()
    cfg.calibration.enabled = True
    cfg.calibration.profile_path = DEFAULT_CALIBRATION_PROFILE
    controller = AcquisitionController(cfg)
    try:
        assert controller.calibration_profile is not None
        assert controller.config.calibration.profile_path == DEFAULT_CALIBRATION_PROFILE
    finally:
        controller.client.close()


def test_project_root_points_to_submodule_root():
    assert (project_root() / "api.py").exists()
