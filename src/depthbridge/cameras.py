"""RealSense adapter; SDK imports remain optional for offline operation."""

import importlib
import logging
import time

import numpy as np

from .frames import Frame
from .geometry import Intrinsics


def realsense_sdk():
    try:
        return importlib.import_module("pyrealsense2")
    except ImportError as exc:
        raise ValueError('未安装 RealSense SDK。请在项目虚拟环境运行：python -m pip install -e ".[realsense]"') from exc


def list_devices() -> dict:
    try:
        rs = realsense_sdk()
    except ValueError as exc:
        return {"sdk_installed": False, "devices": [], "message": str(exc)}
    try:
        devices = [{"name": device.get_info(rs.camera_info.name),
                    "serial": device.get_info(rs.camera_info.serial_number),
                    "firmware": device.get_info(rs.camera_info.firmware_version)}
                   for device in rs.context().query_devices()]
        return {"sdk_installed": True, "devices": devices,
                "message": "请选择设备连接" if devices else "未发现 RealSense 设备；请检查 USB 3 连接，并关闭占用相机的程序"}
    except RuntimeError as exc:
        return {"sdk_installed": True, "devices": [], "message": f"SDK 已安装，但设备检测失败：{exc}"}


class RealSenseCamera:
    def __init__(self, serial: str = ""):
        rs = realsense_sdk()
        self.rs = rs
        self.pipeline = rs.pipeline()
        self.started = False
        config = rs.config()
        if serial:
            config.enable_device(serial)
        config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 30)
        try:
            profile = self.pipeline.start(config)
            self.started = True
            device = profile.get_device()
            self.serial = device.get_info(rs.camera_info.serial_number)
            self.name = device.get_info(rs.camera_info.name)
            self.scale = device.first_depth_sensor().get_depth_scale()
            self.align = rs.align(rs.stream.color)
            self.pointcloud = rs.pointcloud()
            for _ in range(5):
                self.pipeline.wait_for_frames(5000)
        except RuntimeError as exc:
            self.close()
            raise ValueError(f"无法启动 RealSense：{exc}。请检查 USB 3、驱动及相机占用") from exc

    def capture(self) -> Frame:
        try:
            frames = self.align.process(self.pipeline.wait_for_frames(5000))
            depth, color = frames.get_depth_frame(), frames.get_color_frame()
            if not depth or not color:
                raise ValueError("没有收到完整的彩色与深度帧，请重新采集")
            intr = depth.profile.as_video_stream_profile().intrinsics
            k = Intrinsics(intr.width, intr.height, intr.fx, intr.fy, intr.ppx, intr.ppy,
                           str(intr.model).split(".")[-1], list(intr.coeffs))
            # SDK performs distortion-aware deprojection; copy memory before the next capture.
            vertices = self.pointcloud.calculate(depth)
            xyz = np.asanyarray(vertices.get_vertices()).view(np.float32).reshape(intr.height, intr.width, 3).copy()
            return Frame(np.asanyarray(color.get_data()).copy(),
                         np.asanyarray(depth.get_data()).astype(np.float32) * self.scale,
                         k, "realsense", time.time(), xyz=xyz, serial=self.serial,
                         description=f"{self.name} · 深度已对齐 RGB · SDK XYZ · device timestamp {depth.get_timestamp():.1f} ms")
        except RuntimeError as exc:
            raise ValueError(f"相机采集失败：{exc}。请检查连接后重新连接设备") from exc

    def close(self):
        if self.started:
            try:
                self.pipeline.stop()
            except RuntimeError as exc:
                logging.getLogger(__name__).warning("Camera cleanup: %s", exc)
            finally:
                self.started = False
