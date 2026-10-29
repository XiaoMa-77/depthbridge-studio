"""Own the server process directly so Windows shell children cannot be orphaned."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def main():
    project = Path(__file__).resolve().parents[1]
    output = project / "qa-output"
    output.mkdir(exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (output / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "depthbridge", "--port", str(port), "--no-browser"],
                                   cwd=project, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            opener = build_opener(ProxyHandler({}))
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Server exited; inspect qa-output/server.log")
                try:
                    with opener.open(url + "/api/status", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Local server did not become ready")
            result = subprocess.run([sys.executable, str(project / "scripts/browser_check.py"),
                                     "--url", url, "--output", str(output)], cwd=project, check=False)
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
