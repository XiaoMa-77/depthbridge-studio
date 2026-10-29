"""Geometry conventions: column vectors, meters, T_destination_from_source."""

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np


def finite_array(value, shape=None, name="数值") -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if (shape is not None and array.shape != shape) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name}的形状或数值无效；不能包含 NaN/Inf")
    return array


@dataclass(frozen=True)
class Intrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    model: str = "none"
    distortion: list[float] = field(default_factory=list)

    def __post_init__(self):
        values = finite_array([self.fx, self.fy, self.cx, self.cy])
        if self.width <= 0 or self.height <= 0 or self.width * self.height > 8_000_000:
            raise ValueError("图像尺寸无效或过大")
        if self.fx <= 0 or self.fy <= 0 or values.shape != (4,):
            raise ValueError("相机焦距必须为正数")
        finite_array(self.distortion)

    @property
    def matrix(self) -> np.ndarray:
        return np.array([[self.fx, 0, self.cx], [0, self.fy, self.cy], [0, 0, 1]], dtype=float)

    def to_dict(self) -> dict:
        return asdict(self)

    def deproject(self, pixels, depth_m) -> np.ndarray:
        pixels = finite_array(pixels).reshape(-1, 2)
        depths = finite_array(depth_m).reshape(-1)
        if len(pixels) != len(depths) or np.any(depths <= 0):
            raise ValueError("像素与有效深度的数量必须一致")
        if self.model == "none":
            rays = (pixels - [self.cx, self.cy]) / [self.fx, self.fy]
        elif self.model in {"brown_conrady", "opencv", "plumb_bob", "rational_polynomial"}:
            distortion = np.asarray(self.distortion, dtype=float)
            if len(distortion) not in {4, 5, 8, 12, 14}:
                raise ValueError("OpenCV 畸变参数必须有 4、5、8、12 或 14 个值")
            rays = cv2.undistortPoints(pixels.reshape(-1, 1, 2), self.matrix, distortion).reshape(-1, 2)
        else:
            raise ValueError(f"畸变模型 {self.model} 需要相机 SDK 的 XYZ 点图，不能按无畸变计算")
        return np.column_stack([rays, np.ones(len(rays))]) * depths[:, None]


def validate_transform(value) -> np.ndarray:
    matrix = finite_array(value, (4, 4), "坐标变换矩阵")
    rotation = matrix[:3, :3]
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-7):
        raise ValueError("变换矩阵最后一行必须为 [0,0,0,1]")
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5):
        raise ValueError("旋转矩阵必须正交；不能包含缩放或剪切")
    if not np.isclose(np.linalg.det(rotation), 1, atol=1e-5):
        raise ValueError("旋转矩阵行列式必须为 +1")
    return matrix.copy()


def apply_transform(matrix, points) -> np.ndarray:
    matrix = validate_transform(matrix)
    points = finite_array(points)
    if points.ndim not in {1, 2} or points.shape[-1] != 3:
        raise ValueError("点坐标必须为三维")
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def make_transform(translation_m, rpy_deg) -> np.ndarray:
    """R = Rz(yaw) @ Ry(pitch) @ Rx(roll); angles are explicitly degrees."""
    translation = finite_array(translation_m, (3,))
    roll, pitch, yaw = np.deg2rad(finite_array(rpy_deg, (3,)))
    cr, cp, cy = np.cos([roll, pitch, yaw])
    sr, sp, sy = np.sin([roll, pitch, yaw])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    result = np.eye(4)
    result[:3, :3] = rz @ ry @ rx
    result[:3, 3] = translation
    return result


def fit_rigid(camera_points, base_points) -> dict:
    """Least-squares rigid fit, without scale or hidden outlier removal."""
    source = finite_array(camera_points)
    target = finite_array(base_points)
    if source.ndim != 2 or source.shape[1] != 3 or source.shape != target.shape or len(source) < 4:
        raise ValueError("至少需要 4 组同名三维点（推荐 8–12 组）")
    a, b = source - source.mean(axis=0), target - target.mean(axis=0)
    for points in (a, b):
        singular = np.linalg.svd(points, compute_uv=False)
        if singular[0] < 1e-6 or singular[1] < max(1e-6, singular[0] * 1e-4):
            raise ValueError("点集共线或过于集中，请在工作区分散选点")
    u, _, vt = np.linalg.svd(a.T @ b)
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(vt.T @ u.T)
    rotation = vt.T @ correction @ u.T
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = target.mean(axis=0) - rotation @ source.mean(axis=0)
    predicted = apply_transform(matrix, source)
    errors_mm = np.linalg.norm(predicted - target, axis=1) * 1000
    return {
        "matrix": matrix.tolist(),
        "rms_mm": float(np.sqrt(np.mean(errors_mm**2))),
        "max_mm": float(errors_mm.max()),
        "errors_mm": errors_mm.tolist(),
        "count": len(source),
        "method": "rigid-point-fit",
        "metric": "training-residual-not-independent-accuracy",
    }


def solve_hand_eye(observations: list[dict], mode: str) -> dict:
    """Input: base_from_tool and camera_from_target, both in meters."""
    if mode not in {"eye_to_hand", "eye_in_hand"}:
        raise ValueError("未知安装方式")
    if len(observations) < 6:
        raise ValueError("手眼求解至少需要 6 组不同位置与朝向的观测，推荐 15–25 组")
    robots = [validate_transform(o["base_from_tool"]) for o in observations]
    boards = [validate_transform(o["camera_from_target"]) for o in observations]
    rot_vectors = [cv2.Rodrigues((np.linalg.inv(robots[0]) @ r)[:3, :3])[0].ravel()
                   for r in robots[1:]]
    singular = np.linalg.svd(np.asarray(rot_vectors), compute_uv=False)
    if singular[1] < 0.05:
        raise ValueError("旋转激励不足：请绕至少两个不同方向改变末端朝向")
    # For eye-to-hand, swap the roles by supplying tool_from_base.
    inputs = robots if mode == "eye_in_hand" else [np.linalg.inv(r) for r in robots]
    rotation, translation = cv2.calibrateHandEye(
        [r[:3, :3] for r in inputs], [r[:3, 3] for r in inputs],
        [b[:3, :3] for b in boards], [b[:3, 3] for b in boards], method=cv2.CALIB_HAND_EYE_PARK,
    )
    matrix = np.eye(4)
    matrix[:3, :3], matrix[:3, 3] = rotation, translation.ravel()
    matrix = validate_transform(matrix)
    constants = [r @ matrix @ b if mode == "eye_in_hand" else np.linalg.inv(r) @ matrix @ b
                 for r, b in zip(robots, boards, strict=True)]
    translations = np.array([c[:3, 3] for c in constants])
    error = np.linalg.norm(translations - translations.mean(axis=0), axis=1) * 1000
    angular_errors = [np.linalg.norm(cv2.Rodrigues(constants[0][:3, :3].T @ c[:3, :3])[0]) * 180 / np.pi
                      for c in constants]
    return {"matrix": matrix.tolist(), "count": len(robots), "method": "hand-eye-park",
            "rms_mm": float(np.sqrt(np.mean(error**2))), "max_mm": float(error.max()),
            "rotation_spread_deg": float(max(angular_errors)),
            "direction": "tool_from_camera" if mode == "eye_in_hand" else "base_from_camera",
            "metric": "observation-consistency-not-independent-accuracy"}
