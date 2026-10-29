"""Validate built artifacts include offline UI and exclude local runtime data."""

import tarfile
import zipfile
from pathlib import Path


def main():
    dist = Path(__file__).resolve().parents[1] / "dist"
    wheel = next(dist.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for required in ["depthbridge/static/index.html", "depthbridge/static/app.js", "depthbridge/static/cloud.js",
                         "depthbridge/static/style.css", "depthbridge/geometry.py", "depthbridge/cameras.py"]:
            assert required in names, required
        assert not any(".venv/" in name or "/qa-output/" in name or "/data/" in name for name in names)
    with tarfile.open(next(dist.glob("*.tar.gz"))) as archive:
        names = archive.getnames()
        for suffix in ["/README.md", "/setup.ps1", "/docs/D435_验收指南.md", "/scripts/verify_browser.py"]:
            assert any(name.endswith(suffix) for name in names), suffix
        assert not any("/.venv/" in name or "/qa-output/" in name or "/.planning/" in name for name in names)
    print("Wheel UI/assets and source distribution verified; no runtime data included.")


if __name__ == "__main__":
    main()
