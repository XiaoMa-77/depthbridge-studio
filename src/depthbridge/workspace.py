"""In-memory measurement sessions, isolated by physical data source."""

import copy
import csv
import hashlib
import io
import json
import threading
import uuid
from collections import OrderedDict

import cv2
import numpy as np

from .cameras import RealSenseCamera
from .frames import Frame, decode_frame, demo_frame, demo_transform
from .geometry import apply_transform, finite_array, fit_rigid, solve_hand_eye, validate_transform


def new_session(source_id: str, synthetic: bool = False) -> dict:
    return {"schema": "depthbridge-session-v1", "source_id": source_id, "synthetic": synthetic,
            "mode": "eye_to_hand", "extrinsic": demo_transform().tolist() if synthetic else None,
            "label": "合成示例变换" if synthetic else "尚未标定", "base_from_tool": None,
            "selections": [], "pairs": [], "observations": [], "fit": None,
            "clearance_mm": 80.0, "surface_offset_mm": 0.0}


class Workspace:
    def __init__(self, initial_source: str = "demo"):
        if initial_source not in {"demo", "idle"}:
            raise ValueError("初始数据源必须为 idle 或 demo")
        self.lock = threading.RLock()
        self.camera: RealSenseCamera | None = None
        self.frames: OrderedDict[int, Frame] = OrderedDict()
        self.counter = 0
        self.capture_namespace = uuid.uuid4().hex
        self.source_id = initial_source
        self.sessions = {initial_source: new_session(initial_source, initial_source == "demo")}
        self.imported: Frame | None = None
        self.source = initial_source
        if initial_source == "demo":
            self.capture()

    @property
    def session(self):
        return self.sessions[self.source_id]

    def transform(self) -> np.ndarray | None:
        session = self.session
        if session["extrinsic"] is None:
            return None
        extrinsic = validate_transform(session["extrinsic"])
        if session["mode"] == "eye_to_hand":
            return extrinsic
        if session["base_from_tool"] is None:
            return None
        return validate_transform(session["base_from_tool"]) @ extrinsic

    def store(self, frame: Frame) -> Frame:
        self.counter += 1
        frame.frame_id = self.counter
        frame.capture_key = f"{self.capture_namespace}:{self.counter}"
        self.frames[frame.frame_id] = frame
        while len(self.frames) > 8:
            self.frames.popitem(last=False)
        return frame

    def capture(self) -> Frame:
        with self.lock:
            if self.source == "realsense":
                if self.camera is None:
                    raise ValueError("相机未连接")
                frame = self.camera.capture()
            elif self.source == "import":
                if self.imported is None:
                    raise ValueError("没有导入的帧")
                frame = copy.copy(self.imported)
            elif self.source == "demo":
                frame = demo_frame()
            else:
                raise ValueError("相机已断开，请重新连接或选择离线示例")
            return self.store(frame)

    def frame(self, frame_id: int) -> Frame:
        if frame_id not in self.frames:
            raise LookupError("显示帧已过期或数据源已切换，请重新采集后选点")
        return self.frames[frame_id]

    def switch(self, source: str, serial: str = "") -> Frame | None:
        with self.lock:
            if source not in {"demo", "realsense", "idle"}:
                raise ValueError("未知数据源")
            if source == "idle":
                if self.camera:
                    self.camera.close()
                self.camera = None
                self.source = self.source_id = "idle"
                self.sessions.setdefault("idle", new_session("idle"))
                self.frames.clear()
                self.imported = None
                return None
            if source == "realsense" and self.camera:
                self.camera.close()
                self.camera = None
                # A failed reconnect must not keep a dead live source active.
                self.source = "disconnected"
                self.frames.clear()
            candidate = RealSenseCamera(serial) if source == "realsense" else None
            try:
                first = candidate.capture() if candidate else demo_frame()
            except Exception:
                if candidate:
                    candidate.close()
                raise
            if self.camera:
                self.camera.close()
            self.camera = candidate
            self.source = source
            self.source_id = f"realsense:{candidate.serial}" if candidate else "demo"
            self.sessions.setdefault(self.source_id, new_session(self.source_id, source == "demo"))
            self.frames.clear()
            self.imported = None
            return self.store(first)

    def import_frame(self, data: bytes) -> Frame:
        frame = decode_frame(data)
        with self.lock:
            if self.camera:
                self.camera.close()
                self.camera = None
            self.source = "import"
            self.source_id = "import:" + hashlib.sha256(data).hexdigest()[:16]
            if self.source_id not in self.sessions:
                imported_session = new_session(self.source_id, frame.source == "demo")
                imported_session.update(extrinsic=None, label="导入数据 · 尚未标定")
                self.sessions[self.source_id] = imported_session
            self.imported = frame
            self.frames.clear()
            return self.store(copy.copy(frame))

    def select(self, frame_id: int, u: int, v: int, radius: int, capture_key: str | None = None) -> dict:
        with self.lock:
            if len(self.session["selections"]) >= 2000:
                raise ValueError("选点记录已达 2000，请导出会话后开始新会话")
            frame = self.frame(frame_id)
            if capture_key is not None and capture_key != frame.capture_key:
                raise LookupError("显示帧属于另一次运行，请重新采集后选点")
            sample = frame.sample(u, v, radius)
            transform = self.transform()
            sample.update({"id": uuid.uuid4().hex[:10], "source_id": self.source_id,
                           "base_from_tool_at_capture": copy.deepcopy(self.session["base_from_tool"]),
                           "base_m": apply_transform(transform, sample["camera_m"]).tolist() if transform is not None else None,
                           "transform_at_capture": transform.tolist() if transform is not None else None})
            self.session["selections"].append(sample)
            return sample

    def add_pair(self, selection_id: str, base_mm: list[float], role: str, label: str) -> dict:
        with self.lock:
            if role not in {"calibration", "validation"}:
                raise ValueError("点用途必须为 calibration 或 validation")
            sample = next((p for p in self.session["selections"] if p["id"] == selection_id), None)
            if sample is None:
                raise ValueError("请先在当前数据源图像中选择一个有效点")
            if any(p["selection_id"] == selection_id for p in self.session["pairs"]):
                raise ValueError("这个选点已经记录过；独立验证请重新采集未参与标定的物理点")
            base = finite_array(base_mm, (3,), "基座坐标") / 1000
            pair = {"id": uuid.uuid4().hex[:10], "selection_id": selection_id,
                    "camera_m": sample["camera_m"], "base_m": base.tolist(), "role": role,
                    "label": label[:100], "pixel": sample["pixel"], "frame_id": sample["frame_id"],
                    "timestamp": sample["timestamp"], "serial": sample["serial"]}
            pair["base_from_tool_at_capture"] = sample.get("base_from_tool_at_capture")
            self.session["pairs"].append(pair)
            self.session["fit"] = None
            return pair

    def solve(self, method: str) -> dict:
        with self.lock:
            if method == "pointfit":
                if self.session["mode"] != "eye_to_hand":
                    raise ValueError("三维对应点求解用于固定相机；末端相机请使用手眼标定")
                pairs = [p for p in self.session["pairs"] if p["role"] == "calibration"]
                result = fit_rigid([p["camera_m"] for p in pairs], [p["base_m"] for p in pairs])
            elif method == "handeye":
                result = solve_hand_eye(self.session["observations"], self.session["mode"])
            else:
                raise ValueError("未知标定方法")
            self.session["extrinsic"] = result["matrix"]
            self.session["label"] = "三维对应点标定" if method == "pointfit" else "手眼标定"
            self.session["fit"] = result
            return result

    def update_transform(self, mode, matrix, robot_matrix, label, clearance_mm, surface_offset_mm):
        with self.lock:
            if mode not in {"eye_to_hand", "eye_in_hand"}:
                raise ValueError("未知安装方式")
            extrinsic = validate_transform(matrix).tolist() if matrix is not None else None
            robot = validate_transform(robot_matrix).tolist() if robot_matrix is not None else None
            values = finite_array([clearance_mm, surface_offset_mm])
            if not 0 <= values[0] <= 1000 or abs(values[1]) > 500:
                raise ValueError("预接近高度应为 0–1000 mm，表面偏移绝对值不超过 500 mm")
            fit = self.session["fit"] if mode == self.session["mode"] and np.array_equal(extrinsic, self.session["extrinsic"]) else None
            if mode != self.session["mode"]:
                self.session.update(selections=[], pairs=[], observations=[])
            self.session.update(mode=mode, extrinsic=extrinsic, base_from_tool=robot, label=label[:100],
                                clearance_mm=float(values[0]), surface_offset_mm=float(values[1]), fit=fit)

    def state(self) -> dict:
        with self.lock:
            transform = self.transform()
            session = copy.deepcopy(self.session)
            errors = []
            for pair in session["pairs"]:
                pair_transform = transform
                if session["mode"] == "eye_in_hand":
                    pose = pair.get("base_from_tool_at_capture")
                    pair_transform = (validate_transform(pose) @ validate_transform(session["extrinsic"])
                                      if pose is not None and session["extrinsic"] is not None else None)
                if pair_transform is not None:
                    pair["predicted_m"] = apply_transform(pair_transform, pair["camera_m"]).tolist()
                    pair["error_mm"] = float(np.linalg.norm(np.asarray(pair["predicted_m"]) - pair["base_m"]) * 1000)
                    if pair["role"] == "validation":
                        errors.append(pair["error_mm"])
            validation = {"count": len(errors), "rms_mm": float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
                          "max_mm": max(errors) if errors else None}
            return {"source": self.source, "source_id": self.source_id, "session": session,
                    "demo_reference_transform": demo_transform().tolist() if self.source == "demo" else None,
                    "base_from_camera": transform.tolist() if transform is not None else None,
                    "validation": validation, "frame_id": next(reversed(self.frames), None)}

    def detect_board(self, frame_id: int, columns: int, rows: int, square_mm: float) -> dict:
        with self.lock:
            if not (3 <= columns <= 20 and 3 <= rows <= 20 and 1 <= square_mm <= 200):
                raise ValueError("内角点数量应为 3–20，方格边长应为 1–200 mm")
            frame = self.frame(frame_id)
            # PnP requires a supported color distortion model; SDK XYZ is not a substitute here.
            if frame.intrinsics.model not in {"none", "brown_conrady", "opencv", "plumb_bob"}:
                raise ValueError("该彩色畸变模型需要先去畸变再进行棋盘格 PnP")
            gray = cv2.cvtColor(frame.color, cv2.COLOR_RGB2GRAY)
            found, corners = cv2.findChessboardCornersSB(gray, (columns, rows), flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
            if not found:
                raise ValueError("没有找到完整棋盘格；请检查内角点数量、清晰度和遮挡")
            object_points = np.zeros((columns * rows, 3), dtype=np.float32)
            object_points[:, :2] = np.mgrid[:columns, :rows].T.reshape(-1, 2) * square_mm / 1000
            distortion = np.asarray(frame.intrinsics.distortion or [0] * 5, dtype=float)
            success, rvec, tvec = cv2.solvePnP(object_points, corners, frame.intrinsics.matrix, distortion)
            if not success or tvec[2, 0] <= 0:
                raise ValueError("棋盘格位姿求解失败")
            projected, _ = cv2.projectPoints(object_points, rvec, tvec, frame.intrinsics.matrix, distortion)
            error = float(np.sqrt(np.mean(np.sum((projected.reshape(-1, 2) - corners.reshape(-1, 2))**2, axis=1))))
            matrix = np.eye(4)
            matrix[:3, :3], matrix[:3, 3] = cv2.Rodrigues(rvec)[0], tvec.ravel()
            return {"frame_id": frame_id, "camera_from_target": matrix.tolist(),
                    "corners": corners.reshape(-1, 2).tolist(), "reprojection_rms_px": error,
                    "columns": columns, "rows": rows, "square_mm": square_mm}

    def add_observation(self, frame_id: int, base_from_tool, camera_from_target) -> dict:
        with self.lock:
            frame = self.frame(frame_id)
            observation = {"id": uuid.uuid4().hex[:10], "frame_id": frame_id, "timestamp": frame.timestamp,
                           "base_from_tool": validate_transform(base_from_tool).tolist(),
                           "camera_from_target": validate_transform(camera_from_target).tolist()}
            self.session["observations"].append(observation)
            self.session["fit"] = None
            return observation

    def import_session(self, value: dict):
        if value.get("schema") != "depthbridge-session-v1" or value.get("source_id") != self.source_id:
            raise ValueError("会话版本或数据源不匹配；请先连接原设备或导入原 RGB-D 文件")
        candidate = copy.deepcopy(value)
        if bool(candidate.get("synthetic")) != self.session["synthetic"]:
            raise ValueError("合成示例会话不能用于真实设备")
        if candidate.get("mode") not in {"eye_to_hand", "eye_in_hand"}:
            raise ValueError("会话安装方式无效")
        for key in ("extrinsic", "base_from_tool"):
            if candidate.get(key) is not None:
                validate_transform(candidate[key])
        if not isinstance(candidate.get("selections"), list) or len(candidate["selections"]) > 2000:
            raise ValueError("会话选点记录无效或过多")
        for sample in candidate["selections"]:
            finite_array(sample["camera_m"], (3,))
        for pair in candidate.get("pairs", []):
            finite_array(pair["camera_m"], (3,))
            finite_array(pair["base_m"], (3,))
            if pair["role"] not in {"calibration", "validation"}:
                raise ValueError("会话对应点用途无效")
            if pair.get("base_from_tool_at_capture") is not None:
                validate_transform(pair["base_from_tool_at_capture"])
        for observation in candidate.get("observations", []):
            validate_transform(observation["base_from_tool"])
            validate_transform(observation["camera_from_target"])
        defaults = new_session(self.source_id, candidate["synthetic"])
        defaults.update(candidate)
        finite_array([defaults["clearance_mm"], defaults["surface_offset_mm"]])
        with self.lock:
            self.sessions[self.source_id] = defaults

    def measurements_csv(self) -> str:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["id", "role", "label", "frame_id", "timestamp", "u", "v", "camera_x_m", "camera_y_m", "camera_z_m",
                         "measured_base_x_m", "measured_base_y_m", "measured_base_z_m", "error_mm"])
        for p in self.state()["session"]["pairs"]:
            label = p["label"]
            if label.startswith(("=", "+", "-", "@")):
                label = "'" + label
            writer.writerow([p["id"], p["role"], label, p["frame_id"], p["timestamp"], *p["pixel"],
                             *p["camera_m"], *p["base_m"], p.get("error_mm", "")])
        return "\ufeff" + stream.getvalue()

    def close(self):
        with self.lock:
            if self.camera:
                self.camera.close()
                self.camera = None

    def session_bytes(self) -> bytes:
        return json.dumps(self.session, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
