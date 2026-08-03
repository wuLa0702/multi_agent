#!/usr/bin/env bash
# ============================================================
# scripts/lib/common.sh — dev.sh / dev-restart.sh 共享函数
#
# 唯一真相源：杀端口进程、开浏览器等跨脚本逻辑只在此维护。
# 用法：source "$ROOT/scripts/lib/common.sh"（需先定义 ROOT）
# ============================================================

# ── kill_port <PORT>：清理占用端口的旧进程（含 uvicorn 孤儿子进程）──
# Windows（Git Bash）：走 PowerShell 脚本（scripts/lib/kill-port.ps1），
#   按「uvicorn 命令行匹配 + netstat 监听 PID 的后代 + BFS 递归」三层全杀，
#   不会漏掉 uvicorn --reload 的孤儿 spawn 子进程（旧版 netstat+taskkill 的盲区）。
# Linux/macOS：lsof 回退。
kill_port() {
  local PORT="$1"
  if command -v powershell >/dev/null 2>&1; then
    local result
    result=$(powershell -NoProfile -ExecutionPolicy Bypass -File "$ROOT/scripts/lib/kill-port.ps1" -Port "$PORT" 2>/dev/null | tail -1)
    if [ "$result" = "CLEAN" ]; then
      echo "✅ 已清理 $PORT 端口进程（含孤儿子进程）"
    else
      echo "⚠️  $PORT 仍被占用: ${result#REMAIN: }（多为跨会话/高权限进程，请手动处理）"
    fi
  elif command -v lsof >/dev/null 2>&1; then
    local pids
    pids=$(lsof -ti:"$PORT" 2>/dev/null || true)
    if [ -n "$pids" ]; then
      kill $pids 2>/dev/null || true
      echo "✅ 已清理 $PORT 旧进程: $pids"
    else
      echo "ℹ️  $PORT 无残留进程"
    fi
  else
    echo "⚠️  无 powershell/lsof，跳过 $PORT 旧进程清理"
  fi
}

# ── open_browser <URL>：跨平台打开默认浏览器 ──
open_browser() {
  local URL="$1"
  if [ -n "$COMSPEC" ]; then
    cmd //c start "" "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
  fi
}
