# DepthBridge Studio · 设计文档

> 版本：0.2.0 · 更新：2026-11-18
> 本文描述 `depthbridge-studio` 的设计背景、架构、接口、数据流与边界/异常场景，作为总览入口。
> 事实性内容以 `src/depthbridge/` 实际代码为准；文件格式细节见 [数据格式](docs/数据格式.md)，实测与验收结论见 [测试记录](docs/测试记录.md)、[D435 相机实测记录](docs/D435_相机实测记录.md) 与 [D435 验收指南](docs/D435_验收指南.md)。
> 无法仅凭仓库确认的内容在文末「假设与待确认」显式列出。

---

## 1. 背景与目标

### 1.1 问题

RGB-D 测量在用于机械臂之前需要回答三件事：

1. **像素是否可信**：点击的像素到底对应哪个三维点，邻域深度是否混入边缘或背景；
2. **变换是否成立**：相机坐标到基座（或末端）的刚体变换能否由分散的对应点稳定求出；
3. **误差是否独立**：验证点是否与拟合点分离，历史测量能否追溯到当时的帧与变换快照。

现场痛点通常是采集、标定、验证工具分散，图像与坐标无法追溯，甚至把示例变换误用到真实相机上。

### 1.2 目标

- **本地一体化**：采集、选点、标定、独立验证、导出在同一浏览器工作台完成。
- **可追溯**：每个选点携带 `frame_id`、`capture_key`、采集时间与变换快照（`frames.py`、`workspace.py`）。
- **数据源隔离**：真实设备按序列号、导入帧按内容哈希、合成示例单独标记，互不继承标定（`workspace.py`）。
- **离线可用**：界面、字体、点云与几何计算均在本地；RealSense SDK 为可选扩展（`cameras.py`）。

### 1.3 非目标

- 不执行机械臂动作、逆解或碰撞检测，只显示预接近高度偏移。
- 不自动删除标定异常点，不引入缩放（`geometry.py` 的 `fit_rigid`）。
- 不把棋盘格 PnP / 手眼的一致性摘要等同于机械臂实际抓取精度。
- 不从一个 RGB-D ZIP 自动证明它已完成几何对齐，只校验声明与形状（见 [数据格式](docs/数据格式.md)）。

---

## 2. 总体架构

```
┌────────────────────────── 数据源 ──────────────────────────┐
│ RealSense D435 (SDK)   │   RGB-D ZIP (导入)   │   合成示例    │
└───────────┬──────────────────────┬─────────────────┬────────┘
            │ capture()            │ decode_frame()  │ demo_frame()
            v                      v                 v
     ┌──────────────────────────────────────────────────────┐
     │ cameras.py / frames.py                               │
     │ 对齐采集 · SDK XYZ · 深度自适应着色 · ZIP 编解码 · PLY  │
     └──────────────────────────┬───────────────────────────┘
                                │ Frame
                                v
     ┌──────────────────────────────────────────────────────┐
     │ workspace.py  进程内工作区                            │
     │ 按 source_id 隔离会话 · 最多 8 帧缓存 · capture_key   │
     │ 选点 / 对应点 / 刚体拟合 / 手眼 / 独立验证 / 导出      │
     └──────────┬───────────────────────────┬───────────────┘
                │ geometry.py               │ 导出
                │ 像素→相机→基座             │
                v                           v
     ┌──────────────────────────────────────────────────────┐
     │ app.py  FastAPI + uvicorn（127.0.0.1:8765）           │
     │ /api/* JSON 接口 · 中间件 · 异常→HTTP 映射 · 静态托管 │
     └──────────────────────────┬───────────────────────────┘
                                │ HTTP / JSON / 文件下载
                                v
     ┌──────────────────────────────────────────────────────┐
     │ static/  原生 JavaScript + Canvas                    │
     │ RGB/深度/叠加 · 点云 · 三步主流程 · 离线字体与动效     │
     └──────────────────────────────────────────────────────┘
```

可编辑架构图、坐标图与帧一致性图见 [docs/diagrams](docs/diagrams/)（`scripts/render_diagrams.py` 可重新生成）。

### 2.1 模块职责

| 模块 | 文件 | 职责 |
|---|---|---|
| 启动入口 | `src/depthbridge/__main__.py`、`main.py` | 解析 `--port` / `--no-browser` / `--devices`；uvicorn 仅绑定回环地址 |
| 相机适配 | `src/depthbridge/cameras.py` | 可选导入 pyrealsense2；枚举设备；640×480 z16/rgb8@30 配置、深度对齐到彩色、5 帧预热、深度比例与 SDK XYZ |
| 帧与档案 | `src/depthbridge/frames.py` | `Frame` 形状/对齐/时间戳校验；邻域中值选点；点云降采样；RGB-D ZIP 编解码（`allow_pickle=False`）；PLY 导出 |
| 几何 | `src/depthbridge/geometry.py` | 内参与畸变校验、变换合法性、刚体拟合、Park 手眼求解；约定列向量、米、`T_目标_from_来源` |
| 工作区 | `src/depthbridge/workspace.py` | 进程内会话按 `source_id` 隔离；8 帧缓存与 `capture_key`；选点/对应点/观测/拟合/状态/CSV/会话导入 |
| Web API | `src/depthbridge/app.py` | FastAPI 路由、Pydantic 入参约束、中间件、异常映射、静态托管 |
| 前端 | `src/depthbridge/static/` | 原生 JS、Canvas 图像与点云、离线字体、粒子与界面动效 |
| CI | `.github/workflows/ci.yml` | Ubuntu/Windows × Python 3.11/3.12 跑测试与静态检查；独立浏览器作业 |
| 校验脚本 | `scripts/*.py`、`scripts/verify.sh` | 浏览器流程、发行包、真机探测、示意图渲染及本地一键校验 |

> 本地 Web 框架实际为 **FastAPI + uvicorn**（`app.py`），不是 Flask；见「假设与待确认」第 1 条。

---

## 3. 接口设计

### 3.1 命令行（`__main__.py`）

| 命令 | 行为 |
|---|---|
| `python -m depthbridge` | 启动服务，绑定 `127.0.0.1:8765`，1.5 s 后打开浏览器 |
| `--port N` | 覆盖端口，须在 1024–65535，否则 `parser.error` |
| `--no-browser` | 不自动打开浏览器 |
| `--devices` | 打印 `list_devices()` 的 JSON 后退出，不启动服务 |

`pyproject.toml` 的 `[project.scripts] depthbridge` 指向 `depthbridge.__main__:main`。

### 3.2 Web API（`app.py`）

所有 `/api/*` 返回 JSON，错误体为 `{"detail": "..."}`。Pydantic 模型统一 `extra="forbid"`、`allow_inf_nan=False`。

| 方法 | 路径 | 用途 | 成功 / 失败 |
|---|---|---|---|
| GET | `/` | 返回 `static/index.html` | 200 |
| GET | `/static/...` | 静态资源（JS/CSS/字体） | 200 |
| GET | `/api/status` | 版本 + `Workspace.state()` | 200 |
| GET | `/api/devices` | SDK 安装状态与设备列表 | 200 |
| POST | `/api/sources` | 切换 `demo` / `realsense` / `idle` | 201；未知来源 422 |
| POST | `/api/frames` | 采集一帧并入缓存 | 201；无相机或已断开 422 |
| POST | `/api/frames/import` | 上传 RGB-D ZIP（原始 bytes） | 201；损坏 422；>100 MB 413 |
| GET | `/api/frames/{id}/archive` | 下载该帧 ZIP | 200；帧过期 409 |
| GET | `/api/frames/{id}/cloud.ply` | 下载点云（≤30000 点） | 200；帧过期 409 |
| POST | `/api/selections` | 选点采样，`radius` 0–8，`capture_key` 可选 | 201；越界/无深度 422；帧不符 409 |
| POST | `/api/pairs` | 记录实测基座点（mm→m） | 201；重复/无效 422 |
| DELETE | `/api/pairs/{id}` | 删除对应点并使拟合失效 | 200 |
| POST | `/api/calibrations` | `pointfit` / `handeye` 求解 | 201；点不足/共线/激励不足 422 |
| PUT | `/api/transforms` | 手动矩阵、安装方式与预览参数 | 200；非法矩阵/越界 422 |
| POST | `/api/board-observations/detection` | 棋盘格角点检测与 PnP | 200；未找到/模型不支持 422 |
| POST | `/api/handeye-observations` | 记录一组手眼观测 | 201；矩阵非法 422 |
| DELETE | `/api/handeye-observations/{id}` | 删除观测 | 200 |
| GET | `/api/exports/session.json` | 会话 JSON 下载 | 200 |
| PUT | `/api/session` | 导入会话 JSON | 200；来源/字段不匹配 422 |
| GET | `/api/exports/measurements.csv` | 对应点与误差 CSV | 200 |
| GET | `/api/exports/calibration.json` | 标定 JSON 下载 | 200 |
| POST | `/api/calibrations/import` | 导入标定 JSON | 200；版本/单位/方向/来源不符 422 |

中间件与异常映射：

- `Content-Length > 100 MB` → **413**；`Origin` 非本机 → **403**。
- 全部响应加 `X-Content-Type-Options: nosniff`；`/api/*` 加 `Cache-Control: no-store`。
- `ValueError` → **422**，`LookupError` → **409**，`cv2.error` → **422**（带中文提示）。

### 3.3 数据格式（摘要）

| 格式 | 标识 / 关键内容 |
|---|---|
| RGB-D ZIP | `depthbridge-frame-v1`：固定文件名 `color.png`、`depth.npy`、`metadata.json`，可选 `points.npy` |
| 会话 JSON | `depthbridge-session-v1`：选点、采集时间、`capture_key`、变换快照、对应点、手眼观测 |
| 标定 JSON | `depthbridge-calibration-v1`：`units=meters`、`direction`、`matrix`、`mode`、`source_id`、`synthetic` |
| CSV | 对应点、用途、相机与实测基座坐标、误差（标签防公式注入） |
| PLY | 相机光学坐标系降采样原色点云，单位 m |

字段契约、深度比例、畸变模型与单位约定见 [docs/数据格式.md](docs/数据格式.md)。

---

## 4. 数据流

### 4.1 主流程：采集 → 标定 → 测量 → 导出

```
连接/切换数据源
  → POST /api/frames 采集并入缓存
  → 浏览器等 RGB 与深度图都加载后冻结显示帧（applyPacket）
  → 点击像素：POST /api/selections
       → Frame.sample(): 中心深度有效性 → 邻域中值 → SDK XYZ 或内参反投影 → 相机 XYZ
  → 填写实测基座坐标：POST /api/pairs（mm 转 m，区分 calibration / validation）
  → POST /api/calibrations：fit_rigid 或 solve_hand_eye → 写入会话 extrinsic
  → state(): 对验证点算独立三维误差（不参与拟合）
  → 导出 session.json / calibration.json / measurements.csv / 帧 ZIP / PLY
```

### 4.2 显示帧与测量一致性

- `Workspace.store()` 为每帧分配递增 `frame_id` 与 `<进程命名空间>:<帧计数>` 形式的 `capture_key`，缓存最多 8 帧，超出即淘汰最早帧。
- 前端点击时 `stopLive()` 递增 `captureEpoch`，废弃尚未完成的预览刷新；选点请求同时携带 `frame_id` 与 `capture_key`。
- 服务端 `select()` 先查帧是否在缓存，再比对 `capture_key`：不一致或帧已淘汰均返回 409。

### 4.3 会话隔离与单位

- `source_id` 决定会话：`demo`、`realsense:<serial>`、`import:<sha256 前 16 位>`、`idle`；断开设备只切到 `idle`，本进程会话仍保留。
- 内部计算、JSON 与矩阵平移用 **m**；页面实测输入与误差显示用 **mm**（`add_pair` 除以 1000）。
- 末端相机（`eye_in_hand`）用 `base_from_tool_at_capture` 重算历史点；更新当前机器人位姿不改写历史测量。

### 4.4 状态分层

`Workspace.state()` 输出 `source` / `source_id` / `session` / `base_from_camera` / `validation` / `frame_id`；前端 `setState()` 按来源渲染状态条、徽标、可用操作与最近点列表。实时预览每 400 ms 发起一次采集。

---

## 5. 边界与异常场景

| # | 场景 | 处理策略 | 表现 |
|---|---|---|---|
| 1 | SDK 未安装 | `list_devices()` 返回 `sdk_installed: false` 与安装指引；采集不启动 | `/api/devices` 返回 message |
| 2 | 无相机 / 相机被占用 / 启动失败 | 启动初始为 `idle`，采集禁用；`RealSenseCamera` 把 `RuntimeError` 转成中文 `ValueError` 并 `close()` | 采集 422，不隐式用示例冒充真机 |
| 3 | 采集超时 / 运行中掉线 | 5 s 等待超时或空帧 → `ValueError("采集失败…")`；`close()` 容忍拔出异常 | 422 + 重连提示 |
| 4 | 帧缓存淘汰（超过 8 帧） | `frame()` 抛 `LookupError` | 选点 409「帧已过期」 |
| 5 | 恢复旧会话 / 跨进程同编号帧 | `capture_key` 与当前缓存帧不一致 | 选点 409 |
| 6 | 像素越界 / 半径越界 / NaN 坐标 | `Frame.sample()` 校验 `0≤u<W`、`0≤v<H`、`0≤radius≤8`，Pydantic 拒绝 NaN | 422 |
| 7 | 中心无有效深度（不在 0.05–10 m） | 拒绝测量，不从邻域编造深度 | 422「没有有效深度」 |
| 8 | 邻域深度跳变 > 10 mm | 返回 `warning`，建议 `radius=0` 或重新选点 | 前端显示警告 |
| 9 | 对应点不足 4 组 / 共线或过于集中 | `fit_rigid` 拒绝 | 422 |
| 10 | 变换非刚体、行列式 ≠ +1、末行非法、含 NaN/Inf | `validate_transform` 统一校验 | 422 |
| 11 | 手眼观测少于 6 组 / 旋转激励不足 | 显式拒绝，不返回看似合理的结果 | 422 |
| 12 | 末端相机缺少 `base_from_tool` | `transform()` 返回 `None`，不生成基座坐标 | 坐标显示「尚未标定」 |
| 13 | 同一选点重复作为验证点 | `add_pair` 拒绝 | 422「重新采集未参与标定的物理点」 |
| 14 | 会话来源 / 合成标记 / 安装方式不匹配 | `import_session` 校验 `source_id`、`synthetic`、`mode`、矩阵与记录数 | 422 |
| 15 | 标定文件版本 / 单位 / 方向 / 来源不符 | `POST /api/calibrations/import` 逐项校验；合成标定不能用于真实相机 | 422 |
| 16 | RGB-D ZIP 损坏、过大、未声明对齐、含 pickle、条目过多 | 限制 100 MB / ≤10 条目、`allow_pickle=False`、`aligned_to=color` | 422（超限 413） |
| 17 | 请求体过大 / 跨域来源 | 中间件按 `Content-Length` 与 `Origin` 拦截 | 413 / 403 |
| 18 | 棋盘格未找到 / PnP 失败 / 畸变模型不支持 | `detect_board` 校验内角点数、方格边长与模型后报错 | 422 |
| 19 | CSV 标签以 `= + - @` 开头 | `measurements_csv` 前置单引号防公式注入 | 导出安全 |
| 20 | 预接近高度 / 表面偏移越界 | `update_transform` 校验 0–1000 mm / |偏移| ≤500 mm | 422 |

更多数值口径与文件格式限制见 [docs/数据格式.md](docs/数据格式.md)，实机边界见 [D435 验收指南](docs/D435_验收指南.md)。

---

## 6. 测试策略

| 层次 | 文件 | 覆盖 |
|---|---|---|
| 单元 · 几何 | `tests/test_geometry.py`、`tests/test_handeye.py` | 像素反投影、刚体拟合、共线/少点拒绝、变换合法性（行列式/末行/非有限值）、畸变模型、手眼方向与激励 |
| 单元 · 帧 | `tests/test_frames.py` | ZIP 往返、毫米比例、无效中心、边缘警告、点云与 PLY、空/远处深度预览 |
| 单元 · 工作区 | `tests/test_workspace.py` | 数据源隔离、重连、视觉/末端合成、采集时位姿复用、会话导入边界、棋盘格检测 |
| 单元 · 相机 | `tests/test_cameras.py` | SDK 替身验证比例、XYZ、超时、占用、关闭路径；无真实相机依赖 |
| 集成 · API | `tests/test_app.py` | 采集/选点/标定/验证/导出、帧过期与跨进程标识、会话与标定不匹配、启动等待设备 |
| CLI | `tests/test_cli.py` | `--devices`、回环服务参数、非法端口 |
| 一键校验 | `scripts/verify.sh` | 串联 pytest、ruff、编译检查与发行包检查；可选 `--browser` 追加浏览器流程 |
| CI | `.github/workflows/ci.yml` | Ubuntu/Windows × 3.11/3.12，覆盖率下限 80%；独立浏览器作业 |

原有 45 项测试与 89% 语句覆盖率见 [测试记录](docs/测试记录.md)；本次补充 4 项离线边界测试（变换校验 2 项、会话导入 2 项），合计 49 项。所有测试离线运行：相机使用替身，无网络与真机调用。本地运行：

```bash
python -m pytest -q --cov=depthbridge --cov-report=term-missing
bash scripts/verify.sh
```

---

## 7. 假设与待确认

以下内容无法仅凭仓库内文件确认，或存在环境差异，部署/验收前请人工复核：

1. **Web 框架描述差异**：任务背景称 Flask，实际代码为 **FastAPI + uvicorn**（`app.py`、`pyproject.toml`）。本文以仓库代码为准；建议同步修订背景描述。
2. **绝对精度**：文档明确说明绝对测距误差与机械臂基座定位精度尚未用已知距离和实测物理点验证；合成示例中的 3 mm 偏差仅用于证明验证点未参与拟合。
3. **非 D435 实时采集**：README 说明 Orbbec Astra 等可通过规范 RGB-D ZIP 导入，具体型号的实时适配未确认。
4. **本地验证环境**：本次离线验证使用 Python 3.12.10 + OpenCV 5.0.0，而项目约束为 `opencv-python-headless>=4.10,<5`（OpenCV 5 移除了 `calibrateHandEye`）。按 `constraints-py312.txt` 安装 4.x 后应复跑手眼测试。
5. **浏览器流程**：本次未运行 Playwright/Edge 浏览器检查，相关结论沿用 [测试记录](docs/测试记录.md)；如需复核运行 `python scripts/verify_browser.py`。
6. **真机结论**：D435 实拍、连续预览与帧导出结论沿用 [D435 相机实测记录](docs/D435_相机实测记录.md)；本次未连接真实相机。
