"""Probe an already connected RealSense via the local workbench; save data locally.

This measures repeated readings and software consistency, not absolute accuracy.
"""

import argparse
import base64
import csv
import io
import json
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from depthbridge.frames import decode_frame

POINTS = [(120, 270), (190, 120), (230, 430), (400, 435), (575, 260)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("data/camera-probe"))
    args = parser.parse_args()
    if not 2 <= args.frames <= 300:
        parser.error("--frames must be 2–300")
    args.output.mkdir(parents=True, exist_ok=True)
    rows, frames, differences = [], [], []
    invalid_rejected = False
    started = time.perf_counter()
    with httpx.Client(base_url=args.url, timeout=30, trust_env=False) as client:
        status = client.get("/api/status").raise_for_status().json()
        if status["source"] != "realsense":
            raise SystemExit("Connect the real camera in the workbench before running this probe.")
        first_id = None
        for index in range(args.frames):
            packet = client.post("/api/frames").raise_for_status().json()["frame"]
            assert packet["source"] == "realsense" and packet["serial"]
            frame_id = packet["frame_id"]
            archive = client.get(f"/api/frames/{frame_id}/archive").raise_for_status().content
            frame = decode_frame(archive)
            valid = np.isfinite(frame.depth_m) & (frame.depth_m >= 0.05) & (frame.depth_m <= 10)
            xyz_valid = valid & np.isfinite(frame.xyz).all(axis=2) & (frame.xyz[:, :, 2] > 0)
            delta = np.abs(frame.xyz[:, :, 2][xyz_valid] - frame.depth_m[xyz_valid])
            frames.append({"frame_id": frame_id, "timestamp": frame.timestamp,
                           "valid_percent": packet["valid_percent"],
                           "sdk_z_difference_mm": float(delta.max()*1000) if len(delta) else None})
            for u, v in POINTS:
                row = {"frame_id": frame_id, "u": u, "v": v, "depth_mm": None, "range_mm": None,
                       "neighborhood_depth_mm": None, "neighborhood_spread_mm": None}
                try:
                    point = frame.sample(u, v, 0)
                    neighborhood = frame.sample(u, v, 2)
                    row.update(depth_mm=point["depth_m"]*1000,
                               range_mm=float(np.linalg.norm(point["camera_m"])*1000),
                               neighborhood_depth_mm=neighborhood["depth_m"]*1000,
                               neighborhood_spread_mm=neighborhood["spread_mm"])
                    if index in {0, args.frames-1}:
                        result = client.post("/api/selections", json={"frame_id": frame_id, "u": u, "v": v,
                                                                    "radius": 0}).raise_for_status().json()["selection"]
                        differences.append(float(np.linalg.norm(np.array(result["camera_m"])-point["camera_m"])*1000))
                except ValueError:
                    pass
                rows.append(row)
            if index == 0:
                first_id = frame_id
                (args.output / "first-frame.zip").write_bytes(archive)
                invalid = np.argwhere(~valid)
                if len(invalid):
                    v, u = map(int, invalid[len(invalid)//2])
                    invalid_rejected = client.post("/api/selections", json={"frame_id": frame_id, "u": u, "v": v,
                                                                          "radius": 0}).status_code == 422
            if index == args.frames-1:
                (args.output / "last-frame.zip").write_bytes(archive)
                for name in ("color", "depth"):
                    (args.output / f"{name}.png").write_bytes(base64.b64decode(packet[name].split(",", 1)[1]))
                with Image.open(io.BytesIO(base64.b64decode(packet["depth"].split(",", 1)[1]))) as depth:
                    Image.blend(Image.fromarray(frame.color), depth.convert("RGB"), .45).save(args.output / "overlay.png")
                (args.output / "pointcloud.ply").write_bytes(client.get(f"/api/frames/{frame_id}/cloud.ply").raise_for_status().content)
                (args.output / "session.json").write_bytes(client.get("/api/exports/session.json").raise_for_status().content)
            if (index+1) % 10 == 0 or index == args.frames-1:
                print(f"Captured {index+1}/{args.frames} actual frames", flush=True)
        stale_status = client.post("/api/selections", json={"frame_id": first_id, "u": 120, "v": 270,
                                                           "radius": 0}).status_code if args.frames > 8 else None
    stats = []
    for u, v in POINTS:
        samples = [r for r in rows if r["u"] == u and r["v"] == v and r["depth_mm"] is not None]
        depths = [r["depth_mm"] for r in samples]
        median_depths = [r["neighborhood_depth_mm"] for r in samples]
        stats.append({"pixel": [u, v], "valid_frames": len(samples),
                      "median_depth_mm": float(np.median(depths)) if samples else None,
                      "observed_depth_std_mm": float(np.std(depths)) if samples else None,
                      "observed_depth_peak_to_peak_mm": float(np.ptp(depths)) if samples else None,
                      "median_camera_range_mm": float(np.median([r["range_mm"] for r in samples])) if samples else None,
                      "neighborhood_observed_std_mm": float(np.std(median_depths)) if samples else None})
    report = {"source": status["source_id"], "frame_count": args.frames, "elapsed_seconds": time.perf_counter()-started,
              "resolution": [packet["width"], packet["height"]], "intrinsics": packet["intrinsics"],
              "valid_percent_mean": float(np.mean([f["valid_percent"] for f in frames])),
              "api_archive_coordinate_difference_max_mm": max(differences) if differences else None,
              "sdk_depth_z_difference_max_mm": max(f["sdk_z_difference_mm"] for f in frames if f["sdk_z_difference_mm"] is not None),
              "invalid_depth_rejected": invalid_rejected, "stale_frame_status": stale_status,
              "display_range_m": packet["depth_range_m"], "points": stats, "frames": frames,
              "scope": "Observed repeated readings, no ruler ground truth and no robot calibration"}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with (args.output / "samples.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert differences and max(differences) < .001, "API/archive XYZ mismatch"
    assert report["sdk_depth_z_difference_max_mm"] < .01, "SDK XYZ Z/depth scale mismatch"
    assert stale_status in {None, 409}, "Stale frame was not rejected"
    print(json.dumps({k: v for k, v in report.items() if k not in {"frames", "intrinsics"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
