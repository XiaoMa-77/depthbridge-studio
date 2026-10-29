import numpy as np
import pytest

from depthbridge.geometry import make_transform, solve_hand_eye


@pytest.mark.parametrize("mode", ["eye_to_hand", "eye_in_hand"])
def test_handeye_direction_recovers_known_transform(mode):
    rng = np.random.default_rng(18)
    expected = make_transform([0.23, -0.12, 0.8], [175, 5, 12])
    constant = make_transform([0.02, 0.08, 0.14], [10, -15, 20])
    observations = []
    for _ in range(18):
        robot = make_transform(rng.uniform(-0.3, 0.3, 3), rng.uniform(-60, 60, 3))
        board = (np.linalg.inv(expected) @ np.linalg.inv(robot) @ constant if mode == "eye_in_hand"
                 else np.linalg.inv(expected) @ robot @ constant)
        observations.append({"base_from_tool": robot, "camera_from_target": board})
    result = solve_hand_eye(observations, mode)
    np.testing.assert_allclose(result["matrix"], expected, atol=1e-8)
    assert result["rms_mm"] < 1e-6


def test_no_rotational_excitation_is_rejected():
    observations = [{"base_from_tool": make_transform([n * 0.01, 0, 0], [0, 0, 0]),
                     "camera_from_target": np.eye(4)} for n in range(8)]
    with pytest.raises(ValueError, match="旋转"):
        solve_hand_eye(observations, "eye_in_hand")
