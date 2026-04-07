#!/usr/bin/env bash
# CI 门禁脚本 — 依次执行：语法检查 → 单元测试 → 覆盖率检查
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ---------------------------------------------------------------------------
# Python 解释器探测
# ---------------------------------------------------------------------------
if [[ -x "$ROOT_DIR/../../venv/bin/python" ]]; then
  PY_BIN="$ROOT_DIR/../../venv/bin/python"
else
  PY_BIN="python3"
fi

echo "=== [1/3] 语法检查（py_compile）==="
# 检查所有 scripts/ 下 .py 文件的语法，不依赖 flake8/ruff
find scripts -name "*.py" | while read -r f; do
  "$PY_BIN" -m py_compile "$f" && echo "  OK  $f" || { echo "  FAIL $f"; exit 1; }
done

echo ""
echo "=== [2/3] CI Smoke 测试 ==="
"$PY_BIN" -m pytest -q -m ci_smoke \
  tests/test_integration.py \
  tests/test_data_fetcher.py \
  tests/test_analyzer.py

echo ""
echo "=== [3/3] 覆盖率检查（目标 ≥ 60%）==="
# 安静模式：如果 pytest-cov 未安装则跳过，不阻断 CI
if "$PY_BIN" -c "import pytest_cov" 2>/dev/null; then
  "$PY_BIN" -m pytest -q -m ci_smoke \
    --cov=scripts \
    --cov-report=term-missing \
    --cov-fail-under=60 \
    tests/test_integration.py \
    tests/test_data_fetcher.py \
    tests/test_analyzer.py
else
  echo "  跳过（pytest-cov 未安装，运行 pip install pytest-cov 启用）"
fi

echo ""
echo "✅ CI 门禁全部通过"
