#!/usr/bin/env bash
# test-apk.sh — Install APK on emulator, launch, capture results
# Usage: test-apk.sh <apk-path> <output-dir> [test-label]
set -euo pipefail

APK="$1"
OUT="$2"
LABEL="${3:-test}"
SUMMARY="$OUT/summary.json"
CRASH_LOG="$OUT/crash.log"
SCREENSHOT="$OUT/screenshot.png"

mkdir -p "$OUT"

# ── Extract APK metadata ──
# aapt2 is in SDK build-tools dir on emulator-runner runners
PACKAGE=""
MAIN_ACTIVITY=""
AAPT2=$(find /usr/local/lib/android/sdk/build-tools -name aapt2 -type f 2>/dev/null | head -1)
if [ -n "$AAPT2" ]; then
  # aapt2 dump packagename returns just the package string directly (no parsing)
  PACKAGE=$("$AAPT2" dump packagename "$APK" 2>/dev/null || true)
  echo "[${LABEL}] aapt2 at $AAPT2 package=$PACKAGE"
fi

# Fallback: unzip + strings
if [ -z "$PACKAGE" ]; then
  PACKAGE=$(unzip -p "$APK" AndroidManifest.xml 2>/dev/null | strings | grep -E '^com\.' | head -1 || echo "com.dragon.read")
fi
MAIN_ACTIVITY=$(unzip -p "$APK" AndroidManifest.xml 2>/dev/null | strings | grep -iE '^(com\.).*\.(Welcome|Main|Splash|Home|Launch)[A-Za-z]*' | head -1 || echo "com.dragon.read.activity.WelcomeActivity")

echo "[${LABEL}] Package: $PACKAGE, MainActivity: $MAIN_ACTIVITY"

# ── Wait for emulator ──
adb wait-for-device
for i in $(seq 1 60); do
  BOOT=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
  [ "$BOOT" = "1" ] && break
  sleep 2
done
if [ "$BOOT" != "1" ]; then
  echo "[${LABEL}] Emulator boot timeout" | tee "$OUT/error.log"
  exit 1
fi
echo "[${LABEL}] Emulator booted"

# ── Install APK (timeout per install to avoid job-level timeout) ──
APK_SIZE=$(stat -c%s "$APK" 2>/dev/null || echo 0)
echo "[${LABEL}] Installing APK ($(( APK_SIZE / 1048576 )) MB)..."
rm -f "$OUT/install.log"
INSTALL_EXIT=0
timeout 420 adb install -r "$APK" 2>&1 | tee "$OUT/install.log" || INSTALL_EXIT=$?
if [ $INSTALL_EXIT -ne 0 ]; then
  echo "[${LABEL}] Install failed (exit=$INSTALL_EXIT)"
  cat > "$SUMMARY" << EOF
{"result":"install_failed","label":"$LABEL","exit_code":$INSTALL_EXIT}
EOF
  exit 1
fi

# ── Launch Activity ──
adb logcat -c 2>/dev/null || true
adb shell am start -n "$PACKAGE/$MAIN_ACTIVITY" -W 2>&1 | tee "$OUT/launch.log" || true
sleep 10

# Collect crash markers
adb logcat -d -v time 2>/dev/null | grep -iE 'FATAL EXCEPTION|CRASH|ANR|Native crash|ClassNotFoundException|uncaught|Force Closing' | head -50 > "$CRASH_LOG" || true

# Screenshot
adb shell screencap -p /data/local/tmp/screenshot.png 2>/dev/null || true
adb pull /data/local/tmp/screenshot.png "$SCREENSHOT" 2>/dev/null || true
adb shell rm /data/local/tmp/screenshot.png 2>/dev/null || true

# Process check
PID=$(adb shell pidof "$PACKAGE" 2>/dev/null || adb shell ps -A 2>/dev/null | grep "$PACKAGE" | awk '{print $2}' | head -1 || echo "")
CC=$(wc -l < "$CRASH_LOG" 2>/dev/null || echo 0)

if [ -n "$PID" ]; then
  RESULT="launched"
  echo "[${LABEL}] App running (PID: $PID)"
elif [ "$CC" -gt 0 ]; then
  RESULT="crashed"
  echo "[${LABEL}] App crashed"
  cat "$CRASH_LOG"
else
  RESULT="exited"
  echo "[${LABEL}] App exited, no crash"
fi

cat > "$SUMMARY" << EOF
{"result":"$RESULT","label":"$LABEL","package":"$PACKAGE","crash_count":$CC,"pid":${PID:-null}}
EOF
echo "[${LABEL}] Done"
