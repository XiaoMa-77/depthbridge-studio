import copy
import json

import numpy as np
import pytest

import depthbridge.workspace as module
from depthbridge.frames import demo_frame
from depthbridge.geometry import apply_transform, make_transform
from depthbridge.workspace import Workspace


class FakeCamera:
    def __init__(self, serial=""):
        if serial == "broken":
            raise ValueError("camera unavailable")
        self.serial = serial or "D435-test"
        self.closed = False

    def capture(self):
        frame = demo_frame()
        frame.source = "realsense"
        frame.serial = self.serial
        return frame

    def close(self):
        self.closed = True


def test_real_source_never_inherits_synthetic_transform_and_reconnect_is_explicit(monkeypatch):
    monkeypatch.setattr(module, "RealSenseCamera", FakeCamera)
    work = Workspace()
    frame = work.switch("realsense")
    assert work.session["synthetic"] is False
    assert work.transform() is None
    selected = work.select(frame.frame_id, 200, 200, 0)
    assert selected["base_m"] is None
    assert work.state()["source_id"] == "realsense:D435-test"
    with pytest.raises(ValueError, match="unavailable"):
        work.switch("realsense", "broken")
    with pytest.raises(ValueError, match="断开"):
        work.capture()
    work.switch("demo")
    assert work.session["synthetic"]


def test_eye_in_hand_requires_robot_pose_and_preserves_direction():
    work = Workspace()
    extrinsic = make_transform([0.02, 0, 0.1], [0, 0, 10])
    work.update_transform("eye_in_hand", extrinsic, None, "test", 80, 0)
    assert work.transform() is None
    pose = make_transform([0.3, 0.2, 0.4], [180, 0, 20])
    work.update_transform("eye_in_hand", extrinsic, pose, "test", 80, 0)
    np.testing.assert_allclose(work.transform(), pose @ extrinsic)
    with pytest.raises(ValueError, match="固定相机"):
        work.solve("pointfit")


def test_wrist_validation_uses_pose_at_capture_not_latest_pose():
    work = Workspace()
    extrinsic = make_transform([0.02, 0, 0.1], [0, 0, 10])
    pose = make_transform([0.3, 0.2, 0.4], [180, 0, 20])
    work.update_transform("eye_in_hand", extrinsic, pose, "test", 80, 0)
    point = work.select(1, 200, 200, 0)
    base = apply_transform(pose @ extrinsic, point["camera_m"])
    work.add_pair(point["id"], base * 1000, "validation", "held-out")
    work.update_transform("eye_in_hand", extrinsic, make_transform([1, 1, 1], [0, 0, 0]), "new-pose", 80, 0)
    assert work.state()["validation"]["rms_mm"] < 1e-8


def test_duplicate_pair_is_rejected_and_csv_formula_is_escaped():
    work = Workspace()
    point = work.select(1, 200, 200, 0)
    base = apply_transform(work.transform(), point["camera_m"])
    work.add_pair(point["id"], base * 1000, "calibration", "=formula")
    assert "'=formula" in work.measurements_csv()
    with pytest.raises(ValueError, match="已经记录"):
        work.add_pair(point["id"], base * 1000, "validation", "same")


def test_mode_and_preview_limits_are_validated():
    work = Workspace()
    for kwargs in [("bad", np.eye(4), None, "", 80, 0), ("eye_to_hand", np.eye(4), None, "", -1, 0)]:
        with pytest.raises(ValueError):
            work.update_transform(*kwargs)
    with pytest.raises(ValueError):
        work.solve("unknown")


def test_observation_and_session_roundtrip():
    work = Workspace()
    work.add_observation(1, np.eye(4), make_transform([0, 0, 0.5], [0, 0, 0]))
    value = json.loads(work.session_bytes())
    work.import_session(value)
    assert len(work.session["observations"]) == 1
    broken = copy.deepcopy(value)
    broken["observations"][0]["base_from_tool"][0][0] = 99
    with pytest.raises(ValueError):
        work.import_session(broken)


def test_synthetic_chessboard_detection():
    work = Workspace()
    frame = demo_frame()
    image = np.full((480, 640, 3), 180, np.uint8)
    columns, rows, size, x0, y0 = 9, 6, 30, 140, 120
    for row in range(rows + 1):
        for col in range(columns + 1):
            image[y0 + row*size:y0 + (row+1)*size, x0 + col*size:x0 + (col+1)*size] = 255 if (row+col) % 2 else 0
    frame.color = image
    work.store(frame)
    result = work.detect_board(frame.frame_id, columns, rows, 20)
    assert len(result["corners"]) == columns * rows
    assert result["reprojection_rms_px"] < 0.1
    assert np.asarray(result["camera_from_target"])[2, 3] > 0
    with pytest.raises(ValueError, match="完整棋盘格"):
        work.detect_board(1, 9, 6, 20)
