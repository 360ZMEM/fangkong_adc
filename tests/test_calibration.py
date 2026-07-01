import numpy as np

from core.calibration import (
    MagnetometerCalibration,
    apply_calibration,
    compute_calibration_health,
    evaluate_calibration,
    fit_ellipsoid_calibration,
    voltage_to_magnetic_field,
)


def test_voltage_to_magnetic_field_uses_per_axis_sensitivity():
    voltage = np.array([[0.02002, 0.01998, 0.03992]], dtype=np.float64)
    magnetic = voltage_to_magnetic_field(voltage, [20.02, 19.98, 19.96])
    assert np.allclose(magnetic[0], [1.0, 1.0, 2.0])


def test_calibration_apply_bias_and_matrix_roundtrip(tmp_path):
    profile = MagnetometerCalibration(
        name="unit_test",
        created_at="2026-01-01T00:00:00",
        bias_ut=[1.0, 2.0, 3.0],
        matrix=[[2.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 4.0]],
        channels=[0, 1, 2],
        sensitivity_mv_per_ut=[20.02, 19.98, 19.96],
    )
    corrected = profile.apply(np.array([[2.0, 3.0, 4.0]], dtype=np.float64))
    assert np.allclose(corrected[0], [2.0, 3.0, 4.0])

    path = tmp_path / "profile.json"
    profile.save(path)
    loaded = MagnetometerCalibration.load(path)
    assert loaded.name == "unit_test"
    assert np.allclose(loaded.apply([[2.0, 3.0, 4.0]])[0], [2.0, 3.0, 4.0])


def test_apply_calibration_can_be_disabled():
    profile = MagnetometerCalibration(
        name="unit_test",
        created_at="2026-01-01T00:00:00",
        bias_ut=[1.0, 0.0, 0.0],
        matrix=np.eye(3).tolist(),
        channels=[0, 1, 2],
        sensitivity_mv_per_ut=[20.0, 20.0, 20.0],
    )
    data = np.array([[2.0, 3.0, 4.0]], dtype=np.float64)
    assert np.allclose(apply_calibration(data, profile, enabled=False), data)
    assert np.allclose(apply_calibration(data, profile, enabled=True), [[1.0, 3.0, 4.0]])


def test_evaluate_calibration_reports_zero_residual_for_constant_radius():
    data = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    metrics = evaluate_calibration(data)
    assert metrics.sample_count == 3
    assert metrics.rms_residual_ut == 0.0


def _fibonacci_sphere(n: int, coverage: float = 1.0) -> np.ndarray:
    indices = np.arange(0, n, dtype=np.float64) + 0.5
    z = (1.0 - 2.0 * indices / n) * float(np.clip(coverage, 1e-3, 1.0))
    phi = np.arccos(np.clip(z, -1.0, 1.0))
    theta = np.pi * (1.0 + 5.0**0.5) * indices
    x = np.sin(phi) * np.cos(theta)
    y = np.sin(phi) * np.sin(theta)
    return np.column_stack([x, y, z])


def _synthetic_recording(coverage: float, n_samples: int, radius: float = 50.0) -> np.ndarray:
    poses = _fibonacci_sphere(max(n_samples // 8, 100), coverage=coverage)
    src = np.linspace(0.0, 1.0, poses.shape[0])
    tgt = np.linspace(0.0, 1.0, n_samples)
    interp = np.column_stack([np.interp(tgt, src, poses[:, k]) for k in range(3)])
    norms = np.linalg.norm(interp, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    return radius * interp / norms


def test_calibration_health_healthy_for_full_sphere():
    magnetic = _synthetic_recording(coverage=1.0, n_samples=50000)
    profile = fit_ellipsoid_calibration(
        magnetic,
        channels=[0, 1, 2],
        sensitivity_mv_per_ut=[20.0, 20.0, 20.0],
        name="health_full_sphere",
    )
    assert profile.health is not None
    assert profile.health["grade"] == "healthy"
    assert profile.health["score"] >= 80.0
    assert profile.health["coverage_ratio"] > 0.7
    assert profile.health["condition_number"] < 3.0


def test_calibration_health_poor_for_narrow_pose_coverage():
    magnetic = _synthetic_recording(coverage=0.05, n_samples=8000)
    corrected = magnetic  # 直接把姿态数据当作校正后结果做纯健康度测试
    metrics = evaluate_calibration(corrected)
    health = compute_calibration_health(corrected, np.eye(3), metrics)
    assert health.grade == "poor"
    assert health.score < 60.0
    assert any("覆盖率" in issue for issue in health.issues)
    assert health.suggestions
