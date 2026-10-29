import argparse
import threading
import webbrowser

import uvicorn

from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="DepthBridge Studio · RGB-D 抓取标定工作台")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--devices", action="store_true", help="检测 RealSense SDK 与设备后退出")
    args = parser.parse_args()
    if args.devices:
        import json

        from .cameras import list_devices
        print(json.dumps(list_devices(), ensure_ascii=False, indent=2))
        return
    if not 1024 <= args.port <= 65535:
        parser.error("端口应在 1024–65535 之间")
    if not args.no_browser:
        timer = threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{args.port}",))
        timer.daemon = True
        timer.start()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
