#!/usr/bin/env bash
# ============================================================
# multi-agent 一键启动（开发模式）
#
# 功能：检查 Docker → 起资源(redis + opensandbox) → 起后端
# 用法：
#   bash scripts/dev.sh            # 启动全部
# 退出后端后如需停资源：
#   docker compose --env-file .env.dev down
#
# 前置：Docker Desktop 已启动；.env.dev 已配置（复制 .env.example）
# 首次运行会拉镜像（redis/opensandbox），耗时取决于网络
# ============================================================
set -euo pipefail

# 定位项目根（脚本在 scripts/ 下，根 = 上一级）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=============================================="
echo "  multi-agent 一键启动 (dev)"
echo "=============================================="

# ── [1/4] 检查 Docker ──
echo ""
echo "==> [1/4] 检查 Docker..."
if ! docker info >/dev/null 2>&1; then
  echo "❌ Docker 未运行。请先启动 Docker Desktop，再重试。"
  exit 1
fi
echo "✅ Docker 正常"

# ── [2/4] 启动资源（redis + opensandbox）──
echo ""
echo "==> [2/4] 启动资源 (redis 6398 + opensandbox 8080)..."
docker compose --env-file .env.dev up -d redis opensandbox

# ── [3/4] 等待资源就绪 ──
echo ""
echo "==> [3/4] 等待资源就绪..."

# 等 redis 健康（compose healthcheck，最多 30s）
REDIS_OK=0
for _ in $(seq 1 15); do
  if docker inspect --format '{{.State.Health.Status}}' multi-agent-redis 2>/dev/null | grep -q "healthy"; then
    REDIS_OK=1
    break
  fi
  sleep 2
done
if [ "$REDIS_OK" = "1" ]; then
  echo "✅ redis 就绪 (localhost:6398)"
else
  echo "⚠️  redis 健康检查超时，继续尝试（后端会自行重试连接）"
fi

# 等 opensandbox 端口可访问（最多 30s；首次启动较慢）
SANDBOX_OK=0
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 15); do
    if curl -s -o /dev/null -m 2 "http://localhost:8080" 2>/dev/null; then
      SANDBOX_OK=1
      break
    fi
    sleep 2
  done
fi
if [ "$SANDBOX_OK" = "1" ]; then
  echo "✅ opensandbox 就绪 (localhost:8080)"
else
  echo "⚠️  opensandbox 端口暂不可达（可能仍在拉镜像/启动，后端连不上时会报错，可稍后重试）"
fi

# ── [4/4] 启动后端 ──
echo ""
echo "==> [4/4] 启动后端 (FastAPI :8000)..."
cd "$ROOT/backend"

# 选择 Python：优先项目 venv（在项目根，Windows Scripts / Linux bin 兼容）
PY="python"
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"      # Windows venv
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"              # Linux/macOS venv
fi

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "❌ 后端依赖未安装。请先：pip install -r ../requirements.txt（或 pip install -e .）"
  exit 1
fi

echo "✅ 启动完成，访问："
echo "   API 文档   http://localhost:8000/docs"
echo "   健康检查   http://localhost:8000/v1/health"
echo "   （Ctrl+C 停止后端；停资源：docker compose --env-file .env.dev down）"
echo ""
exec "$PY" -m uvicorn src.api.main:app --reload --port 8000
