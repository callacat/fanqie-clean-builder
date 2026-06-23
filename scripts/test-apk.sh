#!/usr/bin/env bash
# test-apk.sh — Install APK, launch, capture crash/screenshot
# Usage: test-apk.sh <apk-path> <output-dir> [test-label]
set -euo pipefail

APK="$1" OUT="$2" LABEL="${3:-test}"
SUMMARY="$OUT/summary.json" CRASH_LOG="$OUT/crash.log" SCREENSHOT="$OUT/screenshot.png"
PACKAGE="com.dragon.read"
MAIN_ACTIVITY="com.dragon.read.pages.splash.SplashActivity"

mkdir -p "$OUT"
echo "[${LABEL}] Package=$PACKAGE Activity=$MAIN_ACTIVITY"

APK_SIZE=$(stat -c%s "$APK" 2>/dev/null || echo 0)
echo "[${LABEL}] Installing APK ($(( APK_SIZE / 1048576 )) MB)..."
INSTALL_EXIT=0
timeout 420 adb install -r "$APK" 2>&1 | tee "$OUT/install.log" || INSTALL_EXIT=$?
if [ $INSTALL_EXIT -ne 0 ]; then
  echo "[${LABEL}] Install failed exit=$INSTALL_EXIT"
  echo '{"result":"install_failed","label":"'"$LABEL"'","exit_code":'"$INSTALL_EXIT"'}' > "$SUMMARY"
  exit 1
fi

adb logcat -c 2>/dev/null || true
adb shell am start -n "$PACKAGE/$MAIN_ACTIVITY" -W 2>&1 | tee "$OUT/launch.log" || true
sleep 10

adb logcat -d -v time 2>/dev/null | grep -iE 'FATAL EXCEPTION|CRASH|ANR|Native crash|ClassNotFoundException|uncaught' | head -50 > "$CRASH_LOG" || true
adb shell screencap -p /data/local/tmp/screenshot.png 2>/dev/null || true
adb pull /data/local/tmp/screenshot.png "$SCREENSHOT" 2>/dev/null || true
adb shell rm /data/local/tmp/screenshot.png 2>/dev/null || true

PID=$(adb shell pidof "$PACKAGE" 2>/dev/null || adb shell ps -A 2>/dev/null | grep "$PACKAGE" | awk '{print $2}' | head -1 || echo "")
CC=$(wc -l < "$CRASH_LOG" 2>/dev/null || echo 0)

if [ -n "$PID" ]; then
  RESULT="launched"; echo "[${LABEL}] App running PID=$PID"
elif [ "$CC" -gt 0 ]; then
  RESULT="crashed"; echo "[${LABEL}] Crashed"; cat "$CRASH_LOG"
else
  RESULT="exited"; echo "[${LABEL}] Exited no crash"
fi

echo '{"result":"'"$RESULT"'","label":"'"$LABEL"'","package":"'"$PACKAGE"'","crash_count":'"$CC"',"pid":'${PID:-null}'}' > "$SUMMARY"
echo "[${LABEL}] Done"
