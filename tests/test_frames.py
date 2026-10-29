import io
import json
import zipfile

import numpy as np
import pytest

from depthbridge.frames import Frame, cloud_ply, decode_frame, demo_frame, encode_frame


def test_archive_roundtrip_preserves_depth_color_intrinsics():
    original = demo_frame()
    restored = decode_frame(encode_frame(original))
    np.testing.assert_array_equal(original.color, restored.color)
    np.testing.assert_allclose(original.depth_m, restored.depth_m)
    assert restored.intrinsics == original.intrinsics
    assert restored.sample(200, 200, 0)["depth_m"] == pytest.approx(0.65)


def test_invalid_center_does_not_invent_depth_from_neighbors():
    frame = demo_frame()
    with pytest.raises(ValueError, match="有效深度"):
        frame.sample(590, 30, 8)
    with pytest.raises(ValueError):
        frame.sample(-1, 0)


def test_depth_edge_is_reported():
    sample = demo_frame().sample(130, 200, 3)
    assert sample["spread_mm"] > 100
    assert sample["warning"]


def test_sdk_xyz_is_used_and_archived():
    frame = demo_frame()
    xyz = np.zeros((*frame.depth_m.shape, 3), np.float32)
    xyz[:, :, 2] = frame.depth_m
    xyz[:, :, 0] = 0.123
    frame.xyz = xyz
    restored = decode_frame(encode_frame(frame))
    assert restored.sample(200, 200, 0)["camera_m"][0] == pytest.approx(0.123)


def test_registration_must_be_explicit():
    original = demo_frame()
    with pytest.raises(ValueError, match="对齐"):
        Frame(original.color, original.depth_m, original.intrinsics, "import", 0, aligned=False)
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(encode_frame(original))) as source, zipfile.ZipFile(stream, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "metadata.json":
                meta = json.loads(data)
                meta["aligned_to"] = "depth"
                data = json.dumps(meta).encode()
            target.writestr(name, data)
    with pytest.raises(ValueError, match="对齐"):
        decode_frame(stream.getvalue())


def test_cloud_filters_bad_depth_and_ply_count_matches():
    frame = demo_frame()
    points, colors = frame.cloud(2000)
    assert 0 < len(points) <= 2000
    assert np.isfinite(points).all()
    text = cloud_ply(points, colors).decode()
    assert f"element vertex {len(points)}" in text
    assert len(text.split("end_header\n")[1].strip().splitlines()) == len(points)


def test_millimeter_archive_scale():
    original = demo_frame()
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(encode_frame(original))) as source, zipfile.ZipFile(stream, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "metadata.json":
                meta = json.loads(data)
                meta["depth_scale_m"] = 0.001
                data = json.dumps(meta).encode()
            elif name == "depth.npy":
                buffer = io.BytesIO()
                np.save(buffer, (original.depth_m * 1000).astype(np.uint16), allow_pickle=False)
                data = buffer.getvalue()
            target.writestr(name, data)
    assert decode_frame(stream.getvalue()).sample(200, 200, 0)["depth_m"] == pytest.approx(0.65)
