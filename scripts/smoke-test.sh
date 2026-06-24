#!/bin/bash
# smoke-test.sh — 在 PVE LXC redroid 上烟测构建的 APK
# 用法: ./smoke-test.sh </path/to/fanqie-clean.apk>
set -euo pipefail

APK="${1:-}"
if [ -z "$APK" ] || [ ! -f "$APK" ]; then
  echo "用法: $0 <apk-path>"
  exit 1
fi

REDROID_HOST="192.168.1.222"
REDROID_SSH="ssh -i /home/agent/.ssh/monitor-key root@$REDROID_HOST"

echo "=== 连接 redroid ==="
$REDROID_SSH docker exec redroid getprop ro.build.version.release

echo "=== 安装 APK ==="
$REDROID_SSH docker cp "$APK" redroid:/data/local/tmp/test.apk
$REDROID_SSH docker exec redroid sh -c 'pm install -r /data/local/tmp/test.apk' || { echo "❌ 安装失败"; exit 1; }
echo "✅ 安装成功"

echo "=== 启动 App (SafeModeActivity) ==="
$REDROID_SSH docker exec redroid sh -c 'am start -n com.dragon.read/.app.SafeModeActivity'
sleep 10

echo "=== 检查崩溃日志 ==="
CRASH=$($REDROID_SSH docker exec redroid sh -c 'logcat -d -b crash 2>/dev/null' | grep -E "FATAL EXCEPTION|CRASH" || true)
if [ -n "$CRASH" ]; then
  echo "❌ 检测到崩溃:"
  echo "$CRASH"
  exit 1
fi

echo "=== 检查 ANR ==="
ANR=$($REDROID_SSH docker exec redroid sh -c 'logcat -d 2>/dev/null' | grep -E "FATAL EXCEPTION|ANR in com.dragon.read" || true)
if [ -n "$ANR" ]; then
  echo "❌ 检测到 ANR"
  echo "$ANR"
  exit 1
fi

PROC=$($REDROID_SSH docker exec redroid sh -c 'dumpsys activity activities 2>/dev/null | grep com.dragon.read' || true)
if [ -z "$PROC" ]; then
  echo "❌ App 未运行"
  exit 1
fi

echo "✅ 烟测通过 — 无启动崩溃"
