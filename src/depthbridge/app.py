"""Local HTTP API and bundled workbench frontend."""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import cv2
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .cameras import list_devices
from .frames import MAX_ARCHIVE_BYTES, cloud_ply, encode_frame
from .geometry import validate_transform
from .workspace import Workspace


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceInput(Model):
    source: Literal["demo", "realsense", "idle"]
    serial: str = ""


class SelectionInput(Model):
    frame_id: int
    u: int
    v: int
    radius: int = Field(default=2, ge=0, le=8)
    capture_key: str | None = None


class PairInput(Model):
    selection_id: str
    base_mm: list[float] = Field(min_length=3, max_length=3)
    role: Literal["calibration", "validation"] = "calibration"
    label: str = ""


class CalibrationInput(Model):
    method: Literal["pointfit", "handeye"] = "pointfit"


class TransformInput(Model):
    mode: Literal["eye_to_hand", "eye_in_hand"]
    matrix: list[list[float]] | None = None
    base_from_tool: list[list[float]] | None = None
    label: str = "手动变换 · 待独立验证"
    clearance_mm: float = 80
    surface_offset_mm: float = 0


class BoardInput(Model):
    frame_id: int
    columns: int = 9
    rows: int = 6
    square_mm: float = 20


class ObservationInput(Model):
    frame_id: int
    base_from_tool: list[list[float]]
    camera_from_target: list[list[float]]


def download(content: bytes | str, filename: str, media_type: str) -> Response:
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


def create_app(initial_source: str = "idle") -> FastAPI:
    workspace = Workspace(initial_source=initial_source)

    @asynccontextmanager
    async def lifespan(app):
        yield
        workspace.close()

    app = FastAPI(title="DepthBridge Studio", version=__version__, lifespan=lifespan)
    app.state.workspace = workspace

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if int(request.headers.get("content-length", "0")) > MAX_ARCHIVE_BYTES:
            return JSONResponse({"detail": "文件或请求超过 100 MB"}, status_code=413)
        origin = request.headers.get("origin")
        allowed = {f"http://{request.url.netloc}", f"http://127.0.0.1:{request.url.port or 80}",
                   f"http://localhost:{request.url.port or 80}"}
        if origin and origin not in allowed:
            return JSONResponse({"detail": "请通过本机工作台操作"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(LookupError)
    async def stale_frame(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(cv2.error)
    async def invalid_cv(request, exc):
        return JSONResponse({"detail": f"视觉计算失败，请检查图像和标定数据：{exc}"}, status_code=422)

    @app.get("/api/status")
    def status():
        return {"version": __version__, **workspace.state()}

    @app.get("/api/devices")
    def devices():
        return list_devices()

    @app.post("/api/sources", status_code=201)
    def sources(value: SourceInput):
        with workspace.lock:
            frame = workspace.switch(value.source, value.serial)
            return {"frame": frame.to_packet() if frame is not None else None, "state": workspace.state()}

    @app.post("/api/frames", status_code=201)
    def frames():
        with workspace.lock:
            return {"frame": workspace.capture().to_packet(), "state": workspace.state()}

    @app.post("/api/frames/import", status_code=201)
    async def import_frame(request: Request):
        body = await request.body()
        with workspace.lock:
            frame = workspace.import_frame(body)
            return {"frame": frame.to_packet(), "state": workspace.state()}

    @app.get("/api/frames/{frame_id}/archive")
    def frame_archive(frame_id: int):
        with workspace.lock:
            return download(encode_frame(workspace.frame(frame_id)), f"rgbd-frame-{frame_id}.zip", "application/zip")

    @app.get("/api/frames/{frame_id}/cloud.ply")
    def frame_cloud(frame_id: int):
        with workspace.lock:
            points, colors = workspace.frame(frame_id).cloud(max_points=30000)
            return download(cloud_ply(points, colors), f"camera-cloud-{frame_id}.ply", "application/octet-stream")

    @app.post("/api/selections", status_code=201)
    def selections(value: SelectionInput):
        selection = workspace.select(**value.model_dump())
        return {"selection": selection, "state": workspace.state()}

    @app.post("/api/pairs", status_code=201)
    def pairs(value: PairInput):
        pair = workspace.add_pair(**value.model_dump())
        return {"pair": pair, "state": workspace.state()}

    @app.delete("/api/pairs/{pair_id}")
    def delete_pair(pair_id: str):
        with workspace.lock:
            workspace.session["pairs"] = [p for p in workspace.session["pairs"] if p["id"] != pair_id]
            workspace.session["fit"] = None
            return workspace.state()

    @app.post("/api/calibrations", status_code=201)
    def calibrations(value: CalibrationInput):
        result = workspace.solve(value.method)
        return {"result": result, "state": workspace.state()}

    @app.put("/api/transforms")
    def transforms(value: TransformInput):
        workspace.update_transform(value.mode, value.matrix, value.base_from_tool, value.label,
                                   value.clearance_mm, value.surface_offset_mm)
        return workspace.state()

    @app.post("/api/board-observations/detection")
    def detect_board(value: BoardInput):
        return workspace.detect_board(**value.model_dump())

    @app.post("/api/handeye-observations", status_code=201)
    def handeye_observations(value: ObservationInput):
        observation = workspace.add_observation(**value.model_dump())
        return {"observation": observation, "state": workspace.state()}

    @app.delete("/api/handeye-observations/{observation_id}")
    def delete_observation(observation_id: str):
        with workspace.lock:
            workspace.session["observations"] = [o for o in workspace.session["observations"] if o["id"] != observation_id]
            workspace.session["fit"] = None
            return workspace.state()

    @app.get("/api/exports/session.json")
    def session_export():
        with workspace.lock:
            return download(workspace.session_bytes(), "depthbridge-session.json", "application/json")

    @app.put("/api/session")
    def session_import(value: dict):
        try:
            workspace.import_session(value)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"会话字段无效：{exc}") from exc
        return workspace.state()

    @app.get("/api/exports/measurements.csv")
    def measurements_export():
        return download(workspace.measurements_csv(), "depthbridge-measurements.csv", "text/csv; charset=utf-8")

    @app.get("/api/exports/calibration.json")
    def calibration_export():
        state = workspace.state()
        session = state["session"]
        value = {"schema": "depthbridge-calibration-v1", "units": "meters", "mode": session["mode"],
                 "direction": "base_from_camera" if session["mode"] == "eye_to_hand" else "tool_from_camera",
                 "matrix": session["extrinsic"], "source_id": workspace.source_id,
                 "synthetic": session["synthetic"], "label": session["label"], "fit": session["fit"],
                 "validation": state["validation"]}
        return download(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), "depthbridge-calibration.json", "application/json")

    @app.post("/api/calibrations/import")
    def calibration_import(value: dict):
        session = workspace.session
        if value.get("schema") != "depthbridge-calibration-v1" or value.get("units") != "meters":
            raise ValueError("标定文件版本或单位不匹配")
        if value.get("source_id") != workspace.source_id or bool(value.get("synthetic")) != session["synthetic"]:
            raise ValueError("标定文件与当前数据源不匹配，合成标定不能用于真实相机")
        direction = "base_from_camera" if value.get("mode") == "eye_to_hand" else "tool_from_camera"
        if value.get("direction") != direction:
            raise ValueError("标定文件变换方向不匹配")
        validate_transform(value.get("matrix"))
        workspace.update_transform(value["mode"], value["matrix"], session["base_from_tool"],
                                   str(value.get("label", "导入标定")), session["clearance_mm"], session["surface_offset_mm"])
        return workspace.state()

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static, check_dir=False), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app
