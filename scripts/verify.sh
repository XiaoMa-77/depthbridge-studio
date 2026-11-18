#!/usr/bin/env bash
# 本地一键离线校验：与 CI 的 tests 作业对齐，不访问相机或外部服务。
# 用法：bash scripts/verify.sh [--browser]
#   --browser  追加浏览器流程（需要 Playwright Chromium 或本机 Edge）
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON="python"
fi
echo "==> 解释器: $PYTHON ($($PYTHON --version 2>&1))"

COV_FLAGS=""
if "$PYTHON" -c "import pytest_cov" >/dev/null 2>&1; then
  COV_FLAGS="--cov=depthbridge --cov-report=term-missing --cov-fail-under=80"
fi

echo "==> 1/4 测试..."
# shellcheck disable=SC2086
"$PYTHON" -m pytest -q $COV_FLAGS

echo "==> 2/4 静态检查..."
"$PYTHON" -m ruff check src tests scripts

echo "==> 3/4 编译检查..."
"$PYTHON" -m compileall -q src tests scripts

echo "==> 4/4 构建与发行包检查..."
"$PYTHON" -m build
"$PYTHON" scripts/check_distribution.py

if [[ "${1:-}" == "--browser" ]]; then
  echo "==> 附加: 浏览器流程..."
  "$PYTHON" scripts/verify_browser.py
fi

echo "全部离线校验通过。"
