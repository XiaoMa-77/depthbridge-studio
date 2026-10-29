"""Validate built artifacts include offline UI and exclude local runtime data."""

import tarfile
import zipfile
from pathlib import Path

from depthbridge import __version__


def main():
    dist = Path(__file__).resolve().parents[1] / "dist"
    wheel = next(dist.glob(f"depthbridge_studio-{__version__}-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for required in ["depthbridge/static/index.html", "depthbridge/static/app.js", "depthbridge/static/cloud.js",
                         "depthbridge/static/workbench.css", "depthbridge/static/effects.js", "depthbridge/geometry.py", "depthbridge/cameras.py"]:
            assert required in names, required
        for font in ["sans", "display", "mono"]:
            assert f"depthbridge/static/fonts/depthbridge-{font}.woff2" in names
        for license_name in ["notosanssc", "manrope", "ibmplexmono"]:
            assert f"depthbridge/static/fonts/OFL-{license_name}.txt" in names
        assert not any(".venv/" in name or "/qa-output/" in name or "/data/" in name for name in names)
    with tarfile.open(dist / f"depthbridge_studio-{__version__}.tar.gz") as archive:
        names = archive.getnames()
        for suffix in ["/README.md", "/setup.ps1", "/docs/D435_验收指南.md", "/scripts/verify_browser.py",
                       "/docs/diagrams/architecture.svg", "/docs/images/workbench.png"]:
            assert any(name.endswith(suffix) for name in names), suffix
        assert not any("/.venv/" in name or "/qa-output/" in name or "/.planning/" in name for name in names)
    print("Wheel UI/assets and source distribution verified; no runtime data included.")


if __name__ == "__main__":
    main()
