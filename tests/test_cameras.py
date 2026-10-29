import sys
from types import SimpleNamespace

import numpy as np
import pytest

from depthbridge.cameras import RealSenseCamera, list_devices


def fake_sdk():
    device = SimpleNamespace(get_info=lambda field: "D435" if field == "name" else "serial-test",
                             first_depth_sensor=lambda: SimpleNamespace(get_depth_scale=lambda: 0.001))
    intr = SimpleNamespace(width=4, height=3, fx=10, fy=10, ppx=2, ppy=1, model="distortion.none", coeffs=[0]*5)
    profile = SimpleNamespace(as_video_stream_profile=lambda: SimpleNamespace(intrinsics=intr))
    depth = SimpleNamespace(profile=profile, get_data=lambda: np.full((3, 4), 650, np.uint16), get_timestamp=lambda: 123.0)
    color = SimpleNamespace(get_data=lambda: np.full((3, 4, 3), 100, np.uint8))
    frames = SimpleNamespace(get_depth_frame=lambda: depth, get_color_frame=lambda: color)
    pipeline = SimpleNamespace(start=lambda config: SimpleNamespace(get_device=lambda: device),
                               wait_for_frames=lambda timeout: frames, stop=lambda: None)
    config = SimpleNamespace(enable_device=lambda serial: None, enable_stream=lambda *args: None)
    vertices = np.zeros((3, 4, 3), np.float32)
    vertices[:, :, 2] = 0.65
    return SimpleNamespace(context=lambda: SimpleNamespace(query_devices=lambda: [device]),
                           camera_info=SimpleNamespace(name="name", serial_number="serial", firmware_version="firmware"),
                           pipeline=lambda: pipeline, config=lambda: config,
                           stream=SimpleNamespace(depth=1, color=2), format=SimpleNamespace(z16=1, rgb8=2),
                           align=lambda stream: SimpleNamespace(process=lambda value: value),
                           pointcloud=lambda: SimpleNamespace(calculate=lambda value: SimpleNamespace(get_vertices=lambda: vertices)))


def test_sdk_adapter_uses_scale_registration_and_xyz(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyrealsense2", fake_sdk())
    assert list_devices()["devices"][0]["name"] == "D435"
    camera = RealSenseCamera("serial-test")
    frame = camera.capture()
    assert frame.aligned
    assert frame.depth_m[0, 0] == pytest.approx(0.65)
    assert frame.sample(2, 1, 0)["camera_m"][2] == pytest.approx(0.65)
    camera.close()
    assert not camera.started


def test_missing_optional_sdk_is_explained(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyrealsense2", None)
    result = list_devices()
    assert result["sdk_installed"] is False
    assert "realsense" in result["message"]


def test_capture_timeout_is_explained_and_close_tolerates_unplug(monkeypatch):
    sdk = fake_sdk()
    monkeypatch.setitem(sys.modules, "pyrealsense2", sdk)
    camera = RealSenseCamera()

    def fail(*args):
        raise RuntimeError("device disconnected")

    camera.pipeline.wait_for_frames = fail
    camera.pipeline.stop = fail
    with pytest.raises(ValueError, match="采集失败"):
        camera.capture()
    camera.close()
    assert not camera.started


def test_start_failure_is_explained(monkeypatch):
    sdk = fake_sdk()
    pipeline = sdk.pipeline()

    def fail(*args):
        raise RuntimeError("busy")

    pipeline.start = fail
    sdk.pipeline = lambda: pipeline
    monkeypatch.setitem(sys.modules, "pyrealsense2", sdk)
    with pytest.raises(ValueError, match="无法启动"):
        RealSenseCamera()
