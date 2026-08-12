#!/usr/bin/env bash
# ============================================================
# multi-agent 后端快速重启（日常开发用）
#
# 功能：杀 8010/5176 旧进程 → 校验依赖 → 起前端(Vite) → 起后端（uvicorn --reload）
# 用法：
#   bash scripts/dev-restart.sh
#
# 与 dev.sh 的区别：
#   - dev.sh         完整启动：检查 Docker → 起资源(redis+opensandbox) → 起前端 → 起后端
#   - dev-restart.sh 快重启：不碰 docker 容器，起前端 + 重启后端进程（秒级）
#
# 说明：
#   - 本地后端 = venv 直跑，不涉及任何镜像；改 backend/src/ 代码热重载即时生效
#   - 首次启动 / 资源变了请用 dev.sh（本脚本不含 compose up）
#   - 前端：随后端一起后台启动（Vite :5176，日志 logs/frontend-dev.log），访问 http://localhost:5176
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

# ── [1/4] 清理旧进程（8010 后端 / 5176 前端）──
echo ""
echo "==> [1/4] 清理 8010/5176 旧进程..."
kill_port 8010
kill_port 5176

# ── [2/4] 校验后端依赖 ──
echo ""
echo "==> [2/4] 校验后端依赖..."
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
echo "✅ 后端依赖正常"

# ── [3/4] 启动前端（Vite :5176，后台运行）──
echo ""
echo "==> [3/4] 启动前端 (Vite :5176)..."
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "⏳ 首次运行：安装前端依赖 (pnpm install)..."
  (cd "$ROOT/frontend" && pnpm install) || { echo "❌ 前端依赖安装失败，请检查 pnpm 与网络"; exit 1; }
fi
mkdir -p "$ROOT/logs"
(cd "$ROOT/frontend" && VITE_API_PROXY="http://127.0.0.1:8010" pnpm dev > "$ROOT/logs/frontend-dev.log" 2>&1 &)

# 前端就绪校验（最多 20s；curl 探活 5176）
FE_OK=0
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 20); do
    if curl -s -o /dev/null -m 2 "http://localhost:5176" 2>/dev/null; then FE_OK=1; break; fi
    sleep 1
  done
fi
if [ "$FE_OK" = "1" ]; then
  echo "   ✅ 前端就绪 → http://localhost:5176"
else
  echo "   ⚠️  前端暂未就绪（可能仍编译中），日志: logs/frontend-dev.log"
fi

# ── [4/4] 启动后端（后台）→ 校验 /v1/health 就绪 → 输出 URL 指南 ──
echo ""
echo "==> [4/4] 启动后端 (FastAPI :8010)..."
cd "$ROOT/backend"
"$PY" -m uvicorn src.api.main:app --reload --port 8010 > "$ROOT/logs/backend-dev.log" 2>&1 &

# 后端就绪校验（最多 30s；/v1/health 200 = 就绪）
BE_OK=0
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null -m 2 "http://localhost:8010/v1/health" 2>/dev/null; then BE_OK=1; break; fi
    sleep 1
  done
fi
if [ "$BE_OK" = "1" ]; then echo "   ✅ 后端就绪（/v1/health 200）"; else echo "   ⚠️  后端未就绪，日志: logs/backend-dev.log"; fi

# ── URL 指南（每个地址说明用途）──
echo ""
echo "=============================================="
echo "  服务已启动 · 入口指南（按需打开）"
echo "=============================================="
echo "  🖥️  http://localhost:5176   前端页面（完整 UI，日常主要入口）"
echo "  🏠  http://localhost:8010    后端导航页（接口入口汇总）"
echo "  📚  http://localhost:8010/docs   API 交互文档（Swagger，可在线测试接口）"
echo "  ❤️  http://localhost:8010/v1/health  健康检查（200=正常；redis 断连显示 degraded 不影响主功能）"
echo "  🗂  日志：logs/frontend-dev.log · logs/backend-dev.log"
echo "  停止：Ctrl+C 停后端；前端 taskkill 5176 或重跑本脚本；资源: docker compose --env-file .env.dev down"
echo ""
echo "  提示：MCP 外部 server 连不上（如 Smithery 403）是正常降级——只跳过该 server，不影响启动与内置工具。"
wait
