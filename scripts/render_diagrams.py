"""Render editable SVG documentation figures with no extra dependencies."""

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams"


class Figure:
    def __init__(self, title, subtitle, height=470):
        self.height = height
        self.parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-label="{escape(title)}">
<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="#8797c1" stroke-width="1.2"/></marker></defs>
<rect width="1200" height="{height}" rx="18" fill="#f5f5f2"/>
<g font-family="Arial, sans-serif"><text x="36" y="40" font-size="12" fill="#3555e8" letter-spacing="2">DEPTHBRIDGE / ENGINEERING NOTES</text>
<text x="36" y="83" font-size="30" font-weight="600" fill="#1d2028">{escape(title)}</text>
<text x="36" y="111" font-size="15" fill="#6b7180">{escape(subtitle)}</text>''']

    def box(self, x, y, width, number, title, lines, *, blue=False):
        fill, stroke, ink = ("#3555e8", "#3555e8", "white") if blue else ("white", "#dce2ee", "#25304a")
        self.parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="152" rx="12" fill="{fill}" stroke="{stroke}"/>')
        self.parts.append(f'<text x="{x+18}" y="{y+28}" font-size="11" letter-spacing="1.3" fill="{ink}" opacity=".65">{escape(number)}</text>')
        self.parts.append(f'<text x="{x+18}" y="{y+59}" font-size="19" font-weight="600" fill="{ink}">{escape(title)}</text>')
        for i, line in enumerate(lines):
            self.parts.append(f'<text x="{x+18}" y="{y+88+i*23}" font-size="13" fill="{ink}" opacity=".8">{escape(line)}</text>')

    def arrow(self, x1, y1, x2, y2, label=""):
        self.parts.append(f'<path d="M{x1} {y1}L{x2} {y2}" stroke="#8797c1" stroke-width="1.5" marker-end="url(#arrow)" fill="none"/>')
        if label:
            self.parts.append(f'<text x="{(x1+x2)/2}" y="{y1-10}" text-anchor="middle" font-size="11" fill="#7182aa">{escape(label)}</text>')

    def note(self, y, text):
        self.parts.append(f'<text x="36" y="{y}" font-size="14" fill="#667591">{escape(text)}</text>')

    def save(self, name):
        self.parts.append('</g></svg>')
        (OUT / name).write_text("\n".join(self.parts), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig = Figure("One local workbench. Four explicit layers.", "RealSense acquisition, geometric state and browser interaction stay on the same computer.")
    fig.box(36, 155, 246, "01 / INPUT", "RGB-D sources", ["D435 via RealSense SDK", "Aligned frame ZIP / explicit demo", "RGB + depth + intrinsics + XYZ"])
    fig.box(330, 155, 246, "02 / COMPUTE", "Python workspace", ["Frame cache + source sessions", "Sampling / rigid fit / hand-eye", "Held-out error statistics"], blue=True)
    fig.box(624, 155, 246, "03 / TRANSPORT", "FastAPI on loopback", ["HTTP request / response", "PNG + JSON / typed operations", "127.0.0.1:8765"])
    fig.box(918, 155, 246, "04 / INTERACTION", "Offline browser UI", ["RGB-D canvas + 3D cloud", "Point inspector + fit + validation", "Local fonts / bounded motion"])
    for a, b in [(282, 330), (576, 624), (870, 918)]:
        fig.arrow(a+3, 232, b-8, 232)
    fig.note(361, "EXPORTS   JSON session / transform  ·  CSV measurements  ·  RGB-D ZIP  ·  camera-frame PLY")
    fig.note(397, "Runtime state is in memory. Save a session and its RGB-D frame separately to reproduce a measurement.")
    fig.note(432, "No CDN, cloud inference or robot motion commands. The camera SDK is an optional local dependency.")
    fig.save("architecture.svg")

    fig = Figure("From a pixel to a robot-frame position.", "Display units: millimetres. Geometry and transform translations: metres.", height=550)
    fig.box(36, 155, 246, "01 / IMAGE", "Pixel + aligned depth", ["Source pixel (u, v), optical Z", "Valid centre depth required", "Neighbourhood median optional"])
    fig.box(330, 155, 246, "02 / CAMERA", "Camera point p_camera", ["D435: SDK XYZ / pixel ray", "X right / Y down / Z forward", "Z is optical depth, not range"])
    fig.box(624, 155, 246, "03 / TRANSFORM", "R @ p_camera + t", ["T_base_from_camera", "Rigid point fit: no scale", "At least 4 non-collinear pairs"], blue=True)
    fig.box(918, 155, 246, "04 / ROBOT BASE", "Point p_base", ["Measured TCP correspondence", "Installation-specific transform", "Independent new points verify fit"])
    for a, b in [(282, 330), (576, 624), (870, 918)]:
        fig.arrow(a+3, 232, b-8, 232)
    fig.note(359, "FIXED CAMERA    T_base_from_camera is estimated from matching physical points in camera and base coordinates.")
    fig.note(396, "WRIST CAMERA    T_base_from_camera = T_base_from_tool @ T_tool_from_camera; use the capture-time robot pose.")
    fig.note(433, "HELD-OUT CHECK   error_mm = 1000 * norm(predicted_base - measured_base). Validation points never enter the fit.")
    fig.note(482, "A low fitting residual measures consistency of recorded pairs. Task accuracy requires new measured physical points.")
    fig.save("coordinates.svg")

    fig = Figure("Measure the frame that is actually visible.", "Sequential preview requests and capture identity keep clicks attached to a specific RGB-D frame.", height=550)
    fig.box(36, 155, 246, "01 / CAPTURE", "Acquire + cache", ["Immutable RGB / depth / XYZ", "Last 8 frames in workspace", "frame_id + process capture_key"])
    fig.box(330, 155, 246, "02 / DISPLAY", "Commit loaded images", ["Wait for RGB + depth images", "Show one consistent frame", "Preview: next request after 400 ms"])
    fig.box(624, 155, 246, "03 / CLICK", "Freeze + select", ["Pause preview; invalidate updates", "Send displayed ID + capture_key", "Sample the cached frame"], blue=True)
    fig.box(918, 155, 246, "04 / TRACE", "Inspect + export", ["XYZ / source / time / pixel", "Expired or mismatched frame: 409", "Save JSON + frame ZIP"])
    for a, b in [(282, 330), (576, 624), (870, 918)]:
        fig.arrow(a+3, 232, b-8, 232)
    fig.note(362, "SESSION RESTORE    History stays available, while points from another capture are never painted onto a new frame.")
    fig.note(401, "MOTION LAYER       Pointer-transparent particles, at most 30 fps; pauses when hidden; reduced-motion and manual off.")
    fig.note(440, "PIXEL MAPPING      Image aspect ratio is preserved at every breakpoint; transitions do not move the measurement canvas.")
    fig.note(489, "The browser sends capture_key for selection validation. Older API clients may omit it; frame expiry still applies.")
    fig.save("frame-consistency.svg")
    print("Rendered architecture.svg, coordinates.svg and frame-consistency.svg")


if __name__ == "__main__":
    main()
