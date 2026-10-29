"""Registered RGB-D frames, lossless portable archives, point sampling."""

import base64
import io
import json
import time
import zipfile
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .geometry import Intrinsics, make_transform

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


@dataclass
class Frame:
    color: np.ndarray
    depth_m: np.ndarray
    intrinsics: Intrinsics
    source: str
    timestamp: float
    aligned: bool = True
    xyz: np.ndarray | None = None
    serial: str = ""
    description: str = ""
    frame_id: int = 0

    def __post_init__(self):
        shape = (self.intrinsics.height, self.intrinsics.width)
        if self.color.shape != (*shape, 3) or self.color.dtype != np.uint8:
            raise ValueError("彩色图必须是与内参尺寸一致的 RGB uint8 图像")
        if self.depth_m.shape != shape or self.depth_m.dtype.kind not in "fiu":
            raise ValueError("深度图必须是与内参尺寸一致的数值二维数组")
        if not self.aligned:
            raise ValueError("必须先将深度对齐到彩色图；不能通过缩放代替几何对齐")
        if not np.isfinite(self.timestamp):
            raise ValueError("帧时间戳无效")
        if self.xyz is not None and (self.xyz.shape != (*shape, 3) or self.xyz.dtype.kind != "f"):
            raise ValueError("SDK XYZ 点图形状无效")

    def sample(self, u: int, v: int, radius: int = 2) -> dict:
        if not (0 <= u < self.intrinsics.width and 0 <= v < self.intrinsics.height):
            raise ValueError("像素超出图像范围")
        if not (0 <= radius <= 8):
            raise ValueError("采样半径应在 0–8 像素之间")
        center = float(self.depth_m[v, u])
        if not np.isfinite(center) or not (0.05 <= center <= 10):
            raise ValueError("点击处没有有效深度，请选择物体内部的有效像素")
        patch = self.depth_m[max(0, v-radius):v+radius+1, max(0, u-radius):u+radius+1]
        valid = patch[np.isfinite(patch) & (patch >= 0.05) & (patch <= 10)]
        depth = float(np.median(valid))
        if self.xyz is not None:
            native = self.xyz[v, u].astype(float)
            if not np.all(np.isfinite(native)) or native[2] <= 0:
                raise ValueError("SDK XYZ 点图在该像素无效")
            point = native * (depth / native[2])
        else:
            point = self.intrinsics.deproject([[u, v]], [depth])[0]
        spread = float(np.percentile(valid, 90) - np.percentile(valid, 10))
        return {"pixel": [u, v], "camera_m": point.tolist(), "depth_m": depth,
                "spread_mm": spread * 1000, "valid_fraction": float(valid.size / patch.size),
                "radius": radius, "frame_id": self.frame_id, "timestamp": self.timestamp,
                "source": self.source, "serial": self.serial,
                "warning": "邻域深度变化较大，可能位于边缘或混入背景，建议半径改为 0 或重新选点" if spread > 0.01 else ""}

    def cloud(self, max_points: int = 4500) -> tuple[np.ndarray, np.ndarray]:
        stride = max(1, int(np.ceil(np.sqrt(self.depth_m.size / max_points))))
        yy, xx = np.mgrid[0:self.intrinsics.height:stride, 0:self.intrinsics.width:stride]
        depths = self.depth_m[::stride, ::stride]
        valid = np.isfinite(depths) & (depths >= 0.05) & (depths <= 10)
        colors = self.color[::stride, ::stride][valid]
        if self.xyz is not None:
            points = self.xyz[::stride, ::stride][valid].astype(float)
            finite = np.isfinite(points).all(axis=1) & (points[:, 2] > 0)
            return points[finite], colors[finite]
        if not np.any(valid):
            return np.empty((0, 3)), np.empty((0, 3), dtype=np.uint8)
        return self.intrinsics.deproject(np.column_stack([xx[valid], yy[valid]]), depths[valid]), colors

    def to_packet(self) -> dict:
        valid = np.isfinite(self.depth_m) & (self.depth_m >= 0.05) & (self.depth_m <= 10)
        lower, upper = (np.percentile(self.depth_m[valid], [2, 98]).astype(float)
                        if np.any(valid) else (0.2, 1.8))
        if upper - lower < 0.2:
            midpoint = (lower + upper) / 2
            lower, upper = max(0.05, midpoint - 0.1), min(10.0, midpoint + 0.1)
        depth = np.zeros(self.depth_m.shape, dtype=np.uint8)
        depth[valid] = np.clip((self.depth_m[valid] - lower) / (upper - lower) * 255, 0, 255).astype(np.uint8)
        depth_color = cv2.cvtColor(cv2.applyColorMap(255 - depth, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)
        depth_color[~valid] = [12, 20, 30]
        points, colors = self.cloud()
        return {"frame_id": self.frame_id, "source": self.source, "serial": self.serial,
                "description": self.description, "timestamp": self.timestamp,
                "width": self.intrinsics.width, "height": self.intrinsics.height,
                "intrinsics": self.intrinsics.to_dict(), "aligned": self.aligned,
                "depth_range_m": [float(lower), float(upper)],
                "valid_percent": round(float(valid.mean() * 100), 2),
                "color": image_url(self.color), "depth": image_url(depth_color),
                "points": np.round(points, 6).tolist(), "colors": colors.tolist()}


def image_url(array: np.ndarray) -> str:
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def demo_frame() -> Frame:
    width, height = 640, 480
    image = Image.new("RGB", (width, height), "#242f3c")
    draw = ImageDraw.Draw(image)
    yy, xx = np.mgrid[:height, :width]
    depth = np.full((height, width), 0.78, dtype=np.float32)
    for x in range(0, width, 40):
        draw.line((x, 0, x, height), fill="#354352")
    for y in range(0, height, 40):
        draw.line((0, y, width, y), fill="#354352")
    draw.rounded_rectangle((130, 130, 275, 275), radius=8, fill="#c88151", outline="#f2bd8c", width=3)
    depth[130:276, 130:276] = 0.65
    draw.ellipse((355, 165, 485, 295), fill="#568bb4", outline="#a3d3ed", width=3)
    circle = (xx - 420)**2 + (yy - 230)**2 <= 65**2
    depth[circle] = 0.68 - np.sqrt(np.maximum(0, 65**2-(xx[circle]-420)**2-(yy[circle]-230)**2)) / 1000
    draw.rounded_rectangle((280, 335, 430, 400), radius=15, fill="#88a98a", outline="#c4dec1", width=3)
    depth[335:401, 280:431] = 0.72
    draw.text((18, 16), "DEPTHBRIDGE / SYNTHETIC RGB-D", fill="#a8bbcc")
    draw.text((159, 192), "BLOCK", fill="#fff0df")
    draw.text((402, 222), "BALL", fill="#e9f8ff")
    draw.text((327, 360), "PART", fill="#f1fff2")
    depth[20:42, 580:615] = 0
    return Frame(np.asarray(image).copy(), depth, Intrinsics(width, height, 610, 610, 319.5, 239.5),
                 "demo", time.time(), description="合成场景 · 几何示例，非实机测量")


def demo_transform() -> np.ndarray:
    return make_transform([0.35, 0, 0.9], [180, 0, -8])


def encode_frame(frame: Frame) -> bytes:
    output = io.BytesIO()
    metadata = {"schema": "depthbridge-frame-v1", "intrinsics": frame.intrinsics.to_dict(),
                "depth_scale_m": 1.0, "aligned_to": "color", "timestamp": frame.timestamp,
                "source": frame.source, "serial": frame.serial, "description": frame.description}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        image = io.BytesIO()
        Image.fromarray(frame.color).save(image, format="PNG")
        archive.writestr("color.png", image.getvalue())
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))
        arrays = {"depth.npy": frame.depth_m}
        if frame.xyz is not None:
            arrays["points.npy"] = frame.xyz
        for name, array in arrays.items():
            stream = io.BytesIO()
            np.save(stream, array, allow_pickle=False)
            archive.writestr(name, stream.getvalue())
    return output.getvalue()


def decode_frame(data: bytes) -> Frame:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("RGB-D 文件包不能超过 100 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10 or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
                raise ValueError("解压后数据过大")
            metadata = json.loads(archive.read("metadata.json"))
            if metadata.get("aligned_to") != "color":
                raise ValueError("metadata.aligned_to 必须明确为 color；请先完成深度和彩色对齐")
            scale = float(metadata["depth_scale_m"])
            if not np.isfinite(scale) or scale <= 0:
                raise ValueError("depth_scale_m 必须为正数")
            intrinsics = Intrinsics(**metadata["intrinsics"])
            with Image.open(io.BytesIO(archive.read("color.png"))) as image:
                if image.size != (intrinsics.width, intrinsics.height):
                    raise ValueError("彩色图尺寸和内参不符")
                color = np.asarray(image.convert("RGB")).copy()
            depth = np.load(io.BytesIO(archive.read("depth.npy")), allow_pickle=False)
            if depth.dtype.kind not in "fiu":
                raise ValueError("深度数组必须为数值")
            xyz = np.load(io.BytesIO(archive.read("points.npy")), allow_pickle=False) if "points.npy" in archive.namelist() else None
            return Frame(color, depth.astype(np.float32) * scale, intrinsics,
                         str(metadata.get("source", "import")), float(metadata.get("timestamp", 0)),
                         xyz=xyz, serial=str(metadata.get("serial", "")),
                         description=str(metadata.get("description", "导入 RGB-D 数据")))
    except (KeyError, TypeError, zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"RGB-D 文件包无效：{exc}") from exc


def cloud_ply(points: np.ndarray, colors: np.ndarray) -> bytes:
    header = (f"ply\nformat ascii 1.0\ncomment units meters; camera optical frame\nelement vertex {len(points)}\n"
              "property float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
    rows = [f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {int(c[0])} {int(c[1])} {int(c[2])}"
            for p, c in zip(points, colors, strict=True)]
    return (header + "\n".join(rows) + "\n").encode("ascii")
