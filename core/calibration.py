from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_PROFILE_DIR = Path("calibration_profiles")

# 健康度评分门槛（可根据实际使用调整）
HEALTH_MIN_SAMPLES = 6000          # 建议至少 3 秒 * 2000Hz，低于此明显不足
HEALTH_TARGET_SAMPLES = 40000      # >=20 秒 2000Hz 视为完全充足
HEALTH_MIN_COVERAGE = 0.35         # 姿态球面覆盖比例下限
HEALTH_TARGET_COVERAGE = 0.75      # 姿态球面覆盖比例满分线
HEALTH_MAX_REL_RMS_PERCENT = 3.0   # 残差比例 >3% 视为差
HEALTH_TARGET_REL_RMS_PERCENT = 0.5
HEALTH_MAX_CONDITION_NUMBER = 8.0  # 矩阵条件数上限（越大越畸形）
HEALTH_TARGET_CONDITION_NUMBER = 2.0
HEALTH_ACCEPTABLE_SCORE = 60.0
HEALTH_HEALTHY_SCORE = 80.0


@dataclass
class CalibrationMetrics:
    mean_magnitude_ut: float
    rms_residual_ut: float
    max_abs_residual_ut: float
    relative_rms_percent: float
    sample_count: int


@dataclass
class CalibrationHealth:
    score: float
    grade: str
    verdict: str
    sample_count: int
    sample_score: float
    coverage_ratio: float
    coverage_score: float
    residual_percent: float
    residual_score: float
    condition_number: float
    condition_score: float
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class MagnetometerCalibration:
    name: str
    created_at: str
    bias_ut: list[float]
    matrix: list[list[float]]
    channels: list[int]
    sensitivity_mv_per_ut: list[float]
    target_magnitude_ut: float | None = None
    metrics: dict[str, float | int] | None = None
    health: dict[str, Any] | None = None
    notes: str = ""
    version: int = 1

    def apply(self, magnetic_ut: np.ndarray) -> np.ndarray:
        arr = _as_2d_float(magnetic_ut)
        if arr.shape[1] != 3:
            raise ValueError("九参数标定仅支持三轴数据")
        bias = np.asarray(self.bias_ut, dtype=np.float64)
        matrix = np.asarray(self.matrix, dtype=np.float64)
        if bias.shape != (3,) or matrix.shape != (3, 3):
            raise ValueError("标定参数尺寸无效")
        return (arr - bias) @ matrix.T

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "MagnetometerCalibration":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)


def voltage_to_magnetic_field(voltage: np.ndarray, sensitivity_mv_per_ut: list[float]) -> np.ndarray:
    arr = _as_2d_float(voltage)
    if not sensitivity_mv_per_ut:
        raise ValueError("sensitivity_mv_per_ut 不能为空")
    if any(v <= 0 for v in sensitivity_mv_per_ut):
        raise ValueError("sensitivity_mv_per_ut 中每个值必须为正数")
    sens = np.array(
        [sensitivity_mv_per_ut[i % len(sensitivity_mv_per_ut)] for i in range(arr.shape[1])],
        dtype=np.float64,
    )
    return arr / (sens / 1000.0)


def apply_calibration(
    magnetic_ut: np.ndarray,
    calibration: MagnetometerCalibration | None,
    enabled: bool = True,
) -> np.ndarray:
    if calibration is None or not enabled:
        return _as_2d_float(magnetic_ut)
    return calibration.apply(magnetic_ut)


def evaluate_calibration(magnetic_ut: np.ndarray) -> CalibrationMetrics:
    arr = _as_2d_float(magnetic_ut)
    magnitude = np.linalg.norm(arr, axis=1)
    mean_mag = float(np.mean(magnitude))
    residual = magnitude - mean_mag
    rms = float(np.sqrt(np.mean(residual**2)))
    return CalibrationMetrics(
        mean_magnitude_ut=mean_mag,
        rms_residual_ut=rms,
        max_abs_residual_ut=float(np.max(np.abs(residual))),
        relative_rms_percent=float(100.0 * rms / max(abs(mean_mag), 1e-12)),
        sample_count=int(arr.shape[0]),
    )


def _sphere_coverage_ratio(corrected: np.ndarray, n_bins: int = 24) -> float:
    """把三维方向单位向量投影到 n_bins × n_bins 的等经纬网格，统计非空格子占比。

    覆盖比例反映"传感器姿态是否覆盖到完整球面"。0 = 单一方向；1 = 覆盖所有网格。
    """
    if corrected.shape[0] < 30:
        return 0.0
    norms = np.linalg.norm(corrected, axis=1)
    valid = norms > 1e-9
    if not np.any(valid):
        return 0.0
    unit = corrected[valid] / norms[valid, None]
    # 将 (x,y,z) 单位向量映射到 (theta ∈ [0, pi], phi ∈ [-pi, pi]) 网格
    theta = np.arccos(np.clip(unit[:, 2], -1.0, 1.0))
    phi = np.arctan2(unit[:, 1], unit[:, 0])
    t_idx = np.clip((theta / np.pi * n_bins).astype(int), 0, n_bins - 1)
    p_idx = np.clip(((phi + np.pi) / (2 * np.pi) * n_bins).astype(int), 0, n_bins - 1)
    grid = np.zeros((n_bins, n_bins), dtype=bool)
    grid[t_idx, p_idx] = True
    return float(grid.sum()) / float(n_bins * n_bins)


def _lerp_score(value: float, worst: float, best: float, lower_is_better: bool = False) -> float:
    """线性打分，返回 [0, 100]。lower_is_better 表示 value 越低越好。"""
    if lower_is_better:
        if value <= best:
            return 100.0
        if value >= worst:
            return 0.0
        return float(100.0 * (worst - value) / (worst - best))
    if value >= best:
        return 100.0
    if value <= worst:
        return 0.0
    return float(100.0 * (value - worst) / (best - worst))


def compute_calibration_health(
    corrected_ut: np.ndarray,
    calibration_matrix: np.ndarray,
    metrics: CalibrationMetrics,
) -> CalibrationHealth:
    """综合评估本次标定所依据的数据是否充足。

    - sample_score: 样本数是否 >= 目标；
    - coverage_score: 姿态是否均匀覆盖三维球面（八字画得是否够全）；
    - residual_score: 标定后 |B| RMS 残差比例（越小越好）；
    - condition_score: 标定矩阵条件数（越接近 1 越正交）。
    """
    corrected = _as_2d_float(corrected_ut)
    matrix = np.asarray(calibration_matrix, dtype=np.float64)

    sample_score = _lerp_score(
        float(metrics.sample_count), HEALTH_MIN_SAMPLES, HEALTH_TARGET_SAMPLES
    )
    coverage_ratio = _sphere_coverage_ratio(corrected)
    coverage_score = _lerp_score(
        coverage_ratio, HEALTH_MIN_COVERAGE, HEALTH_TARGET_COVERAGE
    )
    residual_score = _lerp_score(
        metrics.relative_rms_percent,
        HEALTH_MAX_REL_RMS_PERCENT,
        HEALTH_TARGET_REL_RMS_PERCENT,
        lower_is_better=True,
    )
    condition_number = float(np.linalg.cond(matrix)) if matrix.size == 9 else float("inf")
    condition_score = _lerp_score(
        condition_number,
        HEALTH_MAX_CONDITION_NUMBER,
        HEALTH_TARGET_CONDITION_NUMBER,
        lower_is_better=True,
    )

    # 加权总分：覆盖和残差最能反映"数据是否够用"，权重更高
    score = (
        0.20 * sample_score
        + 0.35 * coverage_score
        + 0.30 * residual_score
        + 0.15 * condition_score
    )
    score = float(np.clip(score, 0.0, 100.0))

    if score >= HEALTH_HEALTHY_SCORE:
        grade = "healthy"
        verdict = "健康度良好，可直接加载使用。"
    elif score >= HEALTH_ACCEPTABLE_SCORE:
        grade = "acceptable"
        verdict = "健康度合格但不理想，建议在关键场景下重新采集。"
    else:
        grade = "poor"
        verdict = "健康度不足，本次数据不足以支撑可靠标定，建议重新采集。"

    issues: list[str] = []
    suggestions: list[str] = []
    if sample_score < 80.0:
        issues.append(
            f"样本数偏少 ({metrics.sample_count} < 目标 {HEALTH_TARGET_SAMPLES})"
        )
        suggestions.append("延长采集时长，至少 20 秒 @ 2000 Hz")
    if coverage_score < 80.0:
        issues.append(
            f"姿态球面覆盖率偏低 ({coverage_ratio * 100:.1f}% < 目标 {HEALTH_TARGET_COVERAGE * 100:.0f}%)"
        )
        suggestions.append("旋转轨迹更完整地覆盖球面：横 8 字 + 立 8 字 + 对角翻转")
    if residual_score < 80.0:
        issues.append(
            f"|B| 残差偏大 ({metrics.relative_rms_percent:.2f}% > 目标 {HEALTH_TARGET_REL_RMS_PERCENT:.1f}%)"
        )
        suggestions.append("检查采集环境是否存在铁磁物或强电磁干扰")
    if condition_score < 80.0:
        issues.append(f"标定矩阵条件数偏大 ({condition_number:.2f})")
        suggestions.append("增加姿态多样性，避免仅沿单一轴旋转导致矩阵接近奇异")

    return CalibrationHealth(
        score=score,
        grade=grade,
        verdict=verdict,
        sample_count=int(metrics.sample_count),
        sample_score=float(sample_score),
        coverage_ratio=float(coverage_ratio),
        coverage_score=float(coverage_score),
        residual_percent=float(metrics.relative_rms_percent),
        residual_score=float(residual_score),
        condition_number=float(condition_number),
        condition_score=float(condition_score),
        issues=issues,
        suggestions=suggestions,
    )


def fit_ellipsoid_calibration(
    magnetic_ut: np.ndarray,
    *,
    channels: list[int],
    sensitivity_mv_per_ut: list[float],
    name: str,
    target_magnitude_ut: float | None = None,
    notes: str = "",
) -> MagnetometerCalibration:
    arr = _as_2d_float(magnetic_ut)
    if arr.shape[1] != 3:
        raise ValueError("九参数标定需要恰好三轴数据")
    if arr.shape[0] < 30:
        raise ValueError("标定样本过少，建议至少数千点")

    try:
        from scipy.optimize import least_squares
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("九参数标定需要 scipy，请先安装 scipy") from exc

    center0 = np.mean(arr, axis=0)
    centered = arr - center0
    target = float(target_magnitude_ut or np.median(np.linalg.norm(centered, axis=1)))
    target = max(target, 1e-9)
    scale0 = target / np.maximum(np.std(centered, axis=0) * np.sqrt(3.0), 1e-9)
    p0 = np.array(
        [
            center0[0],
            center0[1],
            center0[2],
            scale0[0],
            0.0,
            0.0,
            scale0[1],
            0.0,
            scale0[2],
        ],
        dtype=np.float64,
    )

    def unpack(params: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        bias = params[:3]
        matrix = np.array(
            [
                [params[3], params[4], params[5]],
                [params[4], params[6], params[7]],
                [params[5], params[7], params[8]],
            ],
            dtype=np.float64,
        )
        return bias, matrix

    def residual(params: np.ndarray) -> np.ndarray:
        bias, matrix = unpack(params)
        corrected = (arr - bias) @ matrix.T
        return np.linalg.norm(corrected, axis=1) - target

    result = least_squares(residual, p0, loss="soft_l1", f_scale=0.1 * target, max_nfev=5000)
    bias, matrix = unpack(result.x)
    corrected = (arr - bias) @ matrix.T
    metrics = evaluate_calibration(corrected)
    health = compute_calibration_health(corrected, matrix, metrics)
    return MagnetometerCalibration(
        name=name,
        created_at=datetime.now().isoformat(timespec="seconds"),
        bias_ut=[float(x) for x in bias],
        matrix=[[float(x) for x in row] for row in matrix],
        channels=list(channels),
        sensitivity_mv_per_ut=list(sensitivity_mv_per_ut),
        target_magnitude_ut=target,
        metrics=asdict(metrics),
        health=asdict(health),
        notes=notes,
    )


def profile_output_path(name: str, created_at: str | None = None) -> Path:
    stamp = (created_at or datetime.now().isoformat(timespec="seconds")).replace(":", "").replace("-", "")
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name).strip("_")
    return DEFAULT_PROFILE_DIR / f"{stamp}_{safe_name or 'mag_calibration'}.json"


def calibration_summary(calibration: MagnetometerCalibration | None, enabled: bool) -> str:
    if calibration is None:
        return "未加载标定"
    state = "启用" if enabled else "已加载未启用"
    rms = ""
    if calibration.metrics:
        value = calibration.metrics.get("relative_rms_percent")
        if isinstance(value, (int, float)):
            rms = f", RMS={value:.2f}%"
    health = ""
    if calibration.health:
        grade = calibration.health.get("grade")
        score = calibration.health.get("score")
        if isinstance(grade, str) and isinstance(score, (int, float)):
            health = f", 健康度={score:.0f}({grade})"
    return f"{state}: {calibration.name}{rms}{health}"


def _as_2d_float(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.ndim != 2:
        raise ValueError("输入数据必须是一维或二维数组")
    return arr


def calibration_to_npz_metadata(calibration: MagnetometerCalibration | None, enabled: bool) -> dict[str, Any]:
    if calibration is None:
        return {
            "calibration_enabled": np.bool_(False),
            "calibration_name": np.array("", dtype="<U1"),
            "calibration_bias_ut": np.empty(0, dtype=np.float64),
            "calibration_matrix": np.empty((0, 0), dtype=np.float64),
        }
    return {
        "calibration_enabled": np.bool_(enabled),
        "calibration_name": np.array(calibration.name),
        "calibration_bias_ut": np.asarray(calibration.bias_ut, dtype=np.float64),
        "calibration_matrix": np.asarray(calibration.matrix, dtype=np.float64),
    }
