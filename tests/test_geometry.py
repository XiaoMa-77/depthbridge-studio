import numpy as np
import pytest

from depthbridge.geometry import Intrinsics, apply_transform, fit_rigid, make_transform, validate_transform


def test_pixel_to_camera_uses_optical_z_and_principal_point():
    k = Intrinsics(640, 480, 600, 600, 320, 240)
    np.testing.assert_allclose(k.deproject([[320, 240], [380, 210]], [0.6, 0.6]),
                               [[0, 0, 0.6], [0.06, -0.03, 0.6]], atol=1e-10)


def test_rigid_fit_recovers_known_rotation_translation():
    points = np.array([[0, 0, 0.5], [0.1, 0, 0.5], [0, 0.2, 0.5], [0.1, 0.2, 0.6], [-0.2, 0.1, 0.7]])
    expected = make_transform([0.3, -0.1, 0.9], [175, 2, 35])
    target = apply_transform(expected, points)
    result = fit_rigid(points, target)
    np.testing.assert_allclose(result["matrix"], expected, atol=1e-10)
    assert result["rms_mm"] < 1e-8


def test_planar_noncollinear_points_are_valid():
    points = np.array([[0, 0, 0.5], [0.1, 0, 0.5], [0, 0.1, 0.5], [0.1, 0.1, 0.5]])
    result = fit_rigid(points, points + [0.2, 0.3, 0.1])
    assert result["rms_mm"] < 1e-8


def test_collinear_points_and_nonrigid_matrices_are_rejected():
    with pytest.raises(ValueError, match="共线|collinear"):
        fit_rigid([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], [[0, 0, 0]] * 4)
    invalid = np.eye(4)
    invalid[0, 0] = 2
    with pytest.raises(ValueError):
        validate_transform(invalid)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0])
def test_invalid_intrinsics_rejected(bad):
    with pytest.raises(ValueError):
        Intrinsics(640, 480, bad, 600, 320, 240)


def test_unsupported_distortion_is_not_treated_as_pinhole():
    k = Intrinsics(640, 480, 600, 600, 320, 240, "inverse_brown_conrady", [0.1, 0, 0, 0, 0])
    with pytest.raises(ValueError, match="SDK|畸变"):
        k.deproject([[320, 240]], [0.6])
