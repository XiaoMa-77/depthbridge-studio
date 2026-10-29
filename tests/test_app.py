import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from depthbridge.app import create_app
from depthbridge.frames import demo_transform
from depthbridge.geometry import apply_transform


@pytest.fixture
def client():
    with TestClient(create_app()) as result:
        yield result


def test_offline_workflow_and_exact_frame_selection(client):
    assert client.get("/").status_code == 200
    packet = client.post("/api/frames").json()
    frame = packet["frame"]
    response = client.post("/api/selections", json={"frame_id": frame["frame_id"], "u": 200, "v": 200, "radius": 0})
    assert response.status_code == 201
    selection = response.json()["selection"]
    np.testing.assert_allclose(selection["base_m"], apply_transform(demo_transform(), selection["camera_m"]))
    assert client.get(f'/api/frames/{frame["frame_id"]}/archive').content.startswith(b"PK")
    assert b"end_header" in client.get(f'/api/frames/{frame["frame_id"]}/cloud.ply').content


def test_evicted_frame_and_invalid_depth_are_explicit(client):
    frame_id = client.post("/api/frames").json()["frame"]["frame_id"]
    assert client.post("/api/selections", json={"frame_id": frame_id, "u": 590, "v": 30}).status_code == 422
    for _ in range(9):
        client.post("/api/frames")
    assert client.post("/api/selections", json={"frame_id": frame_id, "u": 200, "v": 200}).status_code == 409


def test_point_calibration_excludes_validation_points(client):
    frame_id = client.post("/api/frames").json()["frame"]["frame_id"]
    for index, pixel in enumerate([(180, 180), (240, 180), (180, 240), (240, 240), (360, 360)]):
        selection = client.post("/api/selections", json={"frame_id": frame_id, "u": pixel[0], "v": pixel[1], "radius": 0}).json()["selection"]
        measured = apply_transform(demo_transform(), selection["camera_m"])
        if index == 4:
            measured = measured + [0.005, 0, 0]
        response = client.post("/api/pairs", json={"selection_id": selection["id"], "base_mm": (measured * 1000).tolist(),
                                                    "role": "validation" if index == 4 else "calibration"})
        assert response.status_code == 201
    response = client.post("/api/calibrations", json={"method": "pointfit"})
    assert response.status_code == 201
    state = response.json()["state"]
    assert state["session"]["fit"]["rms_mm"] < 1e-6
    assert state["validation"]["count"] == 1
    assert state["validation"]["rms_mm"] == pytest.approx(5.0)
    assert "measured_base_x_m" in client.get("/api/exports/measurements.csv").text


def test_imported_hardware_frame_does_not_inherit_demo_transform(client):
    archive = client.get("/api/frames/1/archive").content
    response = client.post("/api/frames/import", content=archive, headers={"Content-Type": "application/zip"})
    assert response.status_code == 201
    session = response.json()["state"]["session"]
    assert session["source_id"].startswith("import:")
    # A frame import contains data, never an implicitly trusted calibration.
    assert session["extrinsic"] is None


def test_session_roundtrip_and_bad_transform_rejection(client):
    session = client.get("/api/exports/session.json").json()
    assert client.put("/api/session", json=session).status_code == 200
    session["source_id"] = "realsense:other-device"
    assert client.put("/api/session", json=session).status_code == 422
    matrix = np.eye(4)
    matrix[0, 0] = 1000
    response = client.put("/api/transforms", json={"mode": "eye_to_hand", "matrix": matrix.tolist()})
    assert response.status_code == 422


def test_exported_synthetic_calibration_cannot_be_applied_to_real_source(client):
    value = client.get("/api/exports/calibration.json").json()
    assert value["synthetic"] is True
    assert value["units"] == "meters"
    assert value["direction"] == "base_from_camera"
    value["synthetic"] = False
    assert client.post("/api/calibrations/import", json=value).status_code == 422


def test_malformed_and_misregistered_archive_errors(client):
    assert client.post("/api/frames/import", content=b"not a zip").status_code == 422
    assert client.post("/api/pairs", json={"selection_id": "missing", "base_mm": [0, 0, 0]}).status_code == 422
    response = client.get("/api/exports/session.json")
    assert json.loads(response.content)["schema"] == "depthbridge-session-v1"
