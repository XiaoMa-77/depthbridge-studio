# DepthBridge Studio · 深度桥

**给固定支架上的 Intel RealSense D435 使用的本地 RGB-D 定位与标定工作台。**

点选图像 → 检查深度与相机三维坐标 → 采集同名三维点 → 求相机到机械臂基座的变换 → 用新点验证。

![采集与定位界面，画面与数值为离线合成示例](docs/images/workbench.png)

无需相机即可运行合成示例。界面、点云与计算均在本地运行，无 CDN、外部推理服务或云端上传。版本 `0.1.0` 的真实 D435 画质、USB 稳定性及机械臂定位精度留待接设备验收；离线测试不代表实机精度。

## Windows 快速启动

推荐 **Python 3.12 x64**。打开 PowerShell，在项目目录执行：

```powershell
.\setup.ps1
.\start.ps1
```

如果执行策略限制脚本，可在当前终端使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

启动后打开 **http://127.0.0.1:8765**，默认进入合成示例。已有 `.venv` 时也可直接执行：

```powershell
.\.venv\Scripts\python.exe -m depthbridge
.\.venv\Scripts\python.exe -m depthbridge --devices
```

手动安装 / Linux：

```bash
python3.12 -m venv .venv
# Windows 使用 .venv\Scripts\python.exe 替代下面的 .venv/bin/python
.venv/bin/python -m pip install -e ".[realsense]"
.venv/bin/python -m depthbridge
```

仅离线使用可安装 `pip install -e .`；RealSense 扩展为可选项。端口冲突时用 `--port 8766`，不自动开浏览器用 `--no-browser`。PyCharm 请选择项目 `.venv` 解释器，运行 `main.py`。

## 明天固定 D435 的测试顺序

详细步骤和验收表见 **[固定 D435 真机测试](docs/D435_验收指南.md)**。

1. D435 固定后保持安装位置不变，USB 3 连接电脑，关闭占用相机的程序。
2. 点击“检测设备”，选择序列号，“连接 D435”。连接后不会沿用合成标定。
3. 检查 RGB、深度、叠加和点云。点击普通哑光物体内部，观察深度和相机坐标是否合理。
4. 用已标定 TCP 测量若干**同一个物理点**的基座坐标。界面填写 **mm**；图像选点是物体可见表面点。
5. 至少 4 组非共线点，推荐 8–12 组覆盖工作区；尽量包含不同高度。
6. 点击“求解固定相机变换”。另外采集新的物理点，选择“独立验证”，检查三维误差。
7. 退出前导出会话和标定；需要复现画面时，另存 RGB-D 帧。进程退出后内存会话不自动保留。

## 功能

| 功能 | 内容 |
|---|---|
| 离线示例 | 明确标为 SYNTHETIC 的方块、球和零件场景 |
| D435 采集 | RealSense SDK，640×480 RGB/Depth，深度对齐 RGB，SDK 生成 XYZ 点图 |
| 联动测量 | RGB/深度/叠加选点、邻域中值深度、无效深度拒绝、边缘跨度提示 |
| 三维查看 | 点云旋转缩放、相机/基座坐标轴、表面点和预接近点位置预览 |
| 固定相机标定 | 相机点与实测基座点刚体拟合，无缩放、不暗中删除离群点 |
| 独立验证 | 验证点不参与求解，逐点误差、RMS、最大值和 CSV |
| 手动变换 | 明确方向的 4×4 矩阵，检查旋转正交性、有限值及单位 |
| 进阶手眼 | 棋盘格 PnP、固定/末端相机 Park 求解、姿态激励检查 |
| 文件 | RGB-D ZIP、JSON 会话/标定、CSV 对应点、相机坐标系 PLY |

预接近预览沿**基座 +Z**偏移，可设置表面偏移；它不进行机械臂逆解、碰撞检测或动作执行。夹爪工作姿态、TCP 与物体夹持中心仍需结合实际任务确定。

## 坐标约定

- 内部和 JSON 矩阵平移：**米**。界面实测坐标和误差：**毫米**。
- 相机光学坐标：X 向右、Y 向下、Z 向前。深度为光轴 Z，不是斜距。
- 列向量；`T_base_from_camera` 表示相机坐标转换到基座坐标：`p_base = R @ p_camera + t`。
- 末端相机：`T_base_from_camera = T_base_from_tool @ T_tool_from_camera`。机器人位姿必须与相机采集对应。
- 真实数据用 SDK XYZ 点图处理畸变。离线没有 XYZ 时仅支持明确实现的无畸变/OpenCV Brown 模型，其他模型会拒绝。
- 手动矩阵应来自已知标定；输入一个单位阵会明确按同一坐标系计算，并不意味着完成实物标定。

## 数据格式与恢复

见 [RGB-D 文件格式](docs/数据格式.md)。工作台导出的 ZIP 包含 `color.png`、`depth.npy`、`metadata.json`；真实 SDK 帧另含 `points.npy`。不通过调整图片尺寸冒充几何对齐。

每个数据源有独立的进程内会话。真实相机以序列号区分；记录帧以文件内容区分。先连接同一设备/导入同一文件，再导入会话 JSON。相机被移动、更换分辨率或工作区配置后，应重新标定。标定 JSON 与会话 JSON 用不同入口导入。

## Astra 兼容性

本版实时采集适配 **RealSense**。Astra 可通过规范 RGB-D ZIP 导入离线数据。Astra、Astra Pro、Astra+ 与 Astra 2 的驱动路径可能不同，旧设备需 OpenNI/SDK v1，不能假定 Orbbec SDK v2 通用；本版不声称已提供 Astra 实时驱动。先完成固定 D435 实测，再按具体 Astra 型号增加适配。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,realsense]"
.\.venv\Scripts\python.exe -m pytest --cov=depthbridge --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
```

浏览器验收运行 `python scripts/verify_browser.py`，使用 Playwright Chromium 或本机 Edge；脚本自动启动临时服务并清理进程。验证边界和实际结果记录在 [测试记录](docs/测试记录.md)。GitHub CI 在 Windows/Linux 跑离线数值与 API 测试，并在 Linux 跑浏览器流程；硬件不在 CI 中。

## 技术来源

- [RealSense SDK](https://github.com/realsenseai/librealsense) 与[对齐说明](https://github.com/realsenseai/librealsense/blob/master/wrappers/python/examples/align-depth2color.py)
- [OpenCV 相机与手眼标定](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)
- [Orbbec SDK 型号说明](https://github.com/orbbec/pyorbbecsdk)、[OpenNI 支持](https://www.orbbec.com/developers/openni-sdk/)

MIT License。
