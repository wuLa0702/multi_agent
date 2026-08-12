#!/usr/bin/env bash
# ============================================================
# multi-agent 完整启动（开发模式，首次或资源变更时用）
#
# 功能：检查 Docker → 起资源(redis + opensandbox) → 起前端 → 起后端
# 用法：
#   bash scripts/dev.sh            # 启动全部（含杀 8010/5176 旧进程）
# 日常只改后端代码 → 用 scripts/dev-restart.sh 快重启（不碰容器）
# 退出后端后如需停资源：
#   docker compose --env-file .env.dev down
#
# 前端：
#   - 首次运行自动 pnpm install；日志落 logs/frontend-dev.log
#   - 代理固定指向本地后端 8010（8000 被遗留进程占用，2026-08-02 拍板）
#   - 前端访问 http://localhost:5176
#
# 前置：Docker Desktop 已启动；.env.dev 已配置（复制 .env.example）
# 首次运行会拉镜像（redis/opensandbox），耗时取决于网络
# ============================================================
set -euo pipefail

# 定位项目根（脚本在 scripts/ 下，根 = 上一级）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 共享函数：kill_port（杀端口进程，Windows 走 PowerShell 精确杀 uvicorn 树+孤儿）、open_browser
source "$ROOT/scripts/lib/common.sh"

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

# ── [4/5] 前端由 dev-restart.sh 统一启动（避免重复起 5176）──
echo ""
echo "==> [4/5] 前端随后端一起启动（dev-restart.sh 负责）..."

# ── [5/5] 启动前端 + 后端（dev-restart.sh：杀 8010/5176 → 起前端 → 起后端 → 就绪校验 + URL 指南）──
echo ""
echo "==> [5/5] 启动前端 + 后端..."
exec bash "$ROOT/scripts/dev-restart.sh"
