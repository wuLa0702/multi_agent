#!/usr/bin/env bash
# ============================================================
# multi-agent 后端快速重启（日常开发用）
#
# 功能：杀 8010 旧进程 → 校验依赖 → 起后端（uvicorn --reload）
# 用法：
#   bash scripts/dev-restart.sh
#
# 与 dev.sh 的区别：
#   - dev.sh         完整启动：检查 Docker → 起资源(redis+opensandbox) → 起后端
#   - dev-restart.sh 快重启：不碰 docker 容器，只重启后端进程（秒级）
#
# 说明：
#   - 本地后端 = venv 直跑，不涉及任何镜像；改 backend/src/ 代码热重载即时生效
#   - 首次启动 / 资源变了请用 dev.sh（本脚本不含 compose up）
#   - 前端（未来）：在本脚本追加 npm dev 启动即可
# ============================================================
set -euo pipefail

# 定位项目根（脚本在 scripts/ 下，根 = 上一级）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 共享函数：kill_port（杀端口进程，Windows 走 PowerShell 精确杀 uvicorn 树+孤儿）
source "$ROOT/scripts/lib/common.sh"

echo "=============================================="
echo "  multi-agent 后端快速重启 (dev)"
echo "=============================================="

# ── [1/3] 清理 8010 端口旧进程（Ctrl+C 残留 / reloader 孤儿 spawn 子进程）──
echo ""
echo "==> [1/3] 清理 8010 旧进程..."
kill_port 8010

# ── [2/3] 校验后端依赖 ──
echo ""
echo "==> [2/3] 校验后端依赖..."
PY="python"
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"      # Windows venv
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"              # Linux/macOS venv
fi

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "❌ 后端依赖未安装。请先：pip install -r requirements.txt（或 pip install -e .）"
  exit 1
fi
echo "✅ 依赖正常"

# ── [3/3] 启动后端 ──
echo ""
echo "==> [3/3] 启动后端 (FastAPI :8010)..."
echo "   访问: http://localhost:8010/docs | 健康检查: http://localhost:8010/v1/health"
echo "   （Ctrl+C 停止后端；停资源: docker compose --env-file .env.dev down）"
echo ""
cd "$ROOT/backend"
exec "$PY" -m uvicorn src.api.main:app --reload --port 8010
