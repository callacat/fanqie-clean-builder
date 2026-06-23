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
LOGCAT="$OUT/logcat.txt"

mkdir -p "$OUT"

# ── Extract APK metadata ──
# android-emulator-runner doesn't put aapt in PATH, but SDK tools are available
PACKAGE=""
MAIN_ACTIVITY=""

# Try aapt2 (Android SDK build-tools, available in emulator-runner env)
AAPT2=$(find /usr/local/lib/android/sdk/build-tools -name aapt2 -type f 2>/dev/null | head -1)
if [ -n "$AAPT2" ]; then
  BADGING=$("$AAPT2" dump badging "$APK" 2>/dev/null || true)
  PACKAGE=$(echo "$BADGING" | grep "^package:" | sed "s/.*name='\([^']*\).*/\1/")
  MAIN_ACTIVITY=$(echo "$BADGING" | grep "launchable-activity:" | sed "s/.*name='\([^']*\).*/\1/")
  echo "[${LABEL}] Using aapt2 at $AAPT2"
fi

# Fallback: unzip + parse raw AndroidManifest.xml
if [ -z "$PACKAGE" ]; then
  PACKAGE=$(unzip -p "$APK" AndroidManifest.xml 2>/dev/null | strings | grep -E '^com\.' | head -1 || echo "com.dragon.read")
fi
if [ -z "$MAIN_ACTIVITY" ]; then
  MAIN_ACTIVITY=$(unzip -p "$APK" AndroidManifest.xml 2>/dev/null | strings | grep -iE '^(com\.).*\.(Welcome|Main|Splash|Home|Launch)[A-Za-z]*' | head -1 || echo "com.dragon.read.activity.WelcomeActivity")
fi

echo "[${LABEL}] Package: $PACKAGE, MainActivity: $MAIN_ACTIVITY"

# ── Wait for emulator ──
echo "[${LABEL}] Waiting for emulator..."
adb wait-for-device
BOOT_COMPLETE=""
for i in $(seq 1 60); do
  BOOT_COMPLETE=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
  [ "$BOOT_COMPLETE" = "1" ] && break
  sleep 2
done
if [ "$BOOT_COMPLETE" != "1" ]; then
  echo "[${LABEL}] ❌ Emulator did not boot in 120s" | tee "$OUT/error.log"
  exit 1
fi
echo "[${LABEL}] ✅ Emulator booted"

# ── Install APK (with 10-min timeout per install) ──
APK_SIZE=$(stat -c%s "$APK" 2>/dev/null || stat -f%z "$APK" 2>/dev/null || echo 0)
echo "[${LABEL}] Installing APK ($(( APK_SIZE / 1048576 )) MB, 10 min timeout)..."
rm -f "$OUT/install.log"
INSTALL_RESULT=0
timeout 600 adb install -r "$APK" 2>&1 | tee "$OUT/install.log" || INSTALL_RESULT=$?
if [ $INSTALL_RESULT -ne 0 ]; then
  echo "[${LABEL}] ❌ Install failed (exit=$INSTALL_RESULT)" | tee -a "$OUT/error.log"
  cat > "$SUMMARY" << JSONEOF
{"result":"install_failed","label":"$LABEL","apk_size_bytes":$APK_SIZE,"exit_code":$INSTALL_RESULT}
JSONEOF
  exit 1
fi

# ── Launch Activity ──
echo "[${LABEL}] Launching $PACKAGE/$MAIN_ACTIVITY..."
adb logcat -c 2>/dev/null || true
adb shell am start -n "$PACKAGE/$MAIN_ACTIVITY" -W 2>&1 | tee "$OUT/launch.log" || true

# Collect crash markers
sleep 10
adb logcat -d -v time 2>/dev/null | grep -iE 'FATAL EXCEPTION|CRASH|ANR|Native crash|ClassNotFoundException|uncaught|Force Closing' | head -50 > "$CRASH_LOG" || true

# Screenshot
adb shell screencap -p /data/local/tmp/screenshot.png 2>/dev/null || true
adb pull /data/local/tmp/screenshot.png "$SCREENSHOT" 2>/dev/null || true
adb shell rm /data/local/tmp/screenshot.png 2>/dev/null || true

# Check PID
PID_CHECK=$(adb shell pidof "$PACKAGE" 2>/dev/null || adb shell ps -A 2>/dev/null | grep "$PACKAGE" | awk '{print $2}' | head -1 || echo "")
CRASH_COUNT=$(wc -l < "$CRASH_LOG" 2>/dev/null || echo 0)

if [ -n "$PID_CHECK" ]; then
  RESULT="launched"
  echo "[${LABEL}] ✅ App running (PID: $PID_CHECK)"
elif [ "$CRASH_COUNT" -gt 0 ]; then
  RESULT="crashed"
  echo "[${LABEL}] ❌ App crashed"
  cat "$CRASH_LOG"
else
  RESULT="exited_cleanly"
  echo "[${LABEL}] ⚠️ App exited, no crash"
fi

cat > "$SUMMARY" << JSONEOF
{"result":"$RESULT","label":"$LABEL","package":"$PACKAGE","crash_count":$CRASH_COUNT,"pid":${PID_CHECK:-null},"apk_size_bytes":$APK_SIZE}
JSONEOF
echo "[${LABEL}] Done → $OUT"
