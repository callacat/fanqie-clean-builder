#!/usr/bin/env bash
# test-apk.sh — Install APK on emulator, launch, capture results
# Usage: test-apk.sh <apk-path> <output-dir> [test-label]
set -euo pipefail

APK="$1"
OUT="$2"
LABEL="${3:-test}"
CRASH_LOG="$OUT/crash.log"
SCREENSHOT="$OUT/screenshot.png"
LOGCAT="$OUT/logcat.txt"
SUMMARY="$OUT/summary.json"

mkdir -p "$OUT"

# Detect aapt (Android SDK build-tools or standalone)
AAPT=""
if command -v aapt &>/dev/null; then
  AAPT="aapt"
elif [ -n "${ANDROID_HOME:-}" ]; then
  AAPT=$(find "$ANDROID_HOME/build-tools" -name aapt -type f 2>/dev/null | head -1)
fi

# Extract APK metadata
PACKAGE=""
MAIN_ACTIVITY=""
if [ -n "$AAPT" ]; then
  BADGING=$("$AAPT" dump badging "$APK" 2>/dev/null || true)
  PACKAGE=$(echo "$BADGING" | grep "^package:" | sed "s/.*name='\([^']*\).*/\1/")
  MAIN_ACTIVITY=$(echo "$BADGING" | grep "launchable-activity:" | sed "s/.*name='\([^']*\).*/\1/")
fi
# Fallback: unzip + strings
if [ -z "$PACKAGE" ]; then
  PACKAGE=$(unzip -p "$APK" AndroidManifest.xml 2>/dev/null | strings | grep -E '^com\.' | head -1 || echo "com.dragon.read")
fi
if [ -z "$MAIN_ACTIVITY" ]; then
  # Known fallbacks for this app
  MAIN_ACTIVITY=$(unzip -p "$APK" AndroidManifest.xml 2>/dev/null | strings | grep -iE 'activity' | grep -iE '\.(Welcome|Main|Splash|Home|Launch)' | head -1 | tr -d '\0' || echo "")
  [ -z "$MAIN_ACTIVITY" ] && MAIN_ACTIVITY="com.dragon.read.activity.WelcomeActivity"
fi

echo "[${LABEL}] Package: $PACKAGE, MainActivity: $MAIN_ACTIVITY"

# Wait for emulator
echo "[${LABEL}] Waiting for emulator..."
adb wait-for-device

# Disable animations (also done by emulator-runner, but belt-and-suspenders)
adb shell settings put global window_animation_scale 0.0 2>/dev/null || true
adb shell settings put global transition_animation_scale 0.0 2>/dev/null || true
adb shell settings put global animator_duration_scale 0.0 2>/dev/null || true

# Install APK
APK_SIZE=$(stat -c%s "$APK" 2>/dev/null || stat -f%z "$APK" 2>/dev/null || echo 0)
echo "[${LABEL}] Installing APK ($(( APK_SIZE / 1048576 )) MB)..."
INSTALL_OUT=$(adb install -r -g "$APK" 2>&1) || {
  echo "$INSTALL_OUT" | tee "$OUT/install.log"
  cat > "$SUMMARY" <<JSONEOF
{"result":"install_failed","label":"$LABEL","apk_size_bytes":$APK_SIZE}
JSONEOF
  exit 1
}
echo "$INSTALL_OUT" | tee "$OUT/install.log"

# Clear logcat buffer
adb logcat -c 2>/dev/null || true

# Launch activity
echo "[${LABEL}] Launching $PACKAGE/$MAIN_ACTIVITY..."
adb shell am start -n "$PACKAGE/$MAIN_ACTIVITY" -W 2>&1 | tee "$OUT/launch.log" &
sleep 15  # Let the app initialize
wait

# Collect logcat — crash markers only
adb logcat -d -v time 2>/dev/null | grep -iE 'FATAL EXCEPTION|CRASH|ANR|Native crash|ClassNotFoundException|uncaught' | head -50 > "$CRASH_LOG" || true
adb logcat -d -v brief '*:E' 2>/dev/null | head -100 >> "$OUT/logcat_errors.txt" || true

# Screenshot
adb shell screencap -p /data/local/tmp/screenshot.png 2>/dev/null || true
adb pull /data/local/tmp/screenshot.png "$SCREENSHOT" 2>/dev/null || true
adb shell rm /data/local/tmp/screenshot.png 2>/dev/null || true

# Check if process is alive
PID_CHECK=$(adb shell pidof "$PACKAGE" 2>/dev/null || true)
if [ -z "$PID_CHECK" ]; then
  PID_CHECK=$(adb shell ps -A 2>/dev/null | grep "$PACKAGE" | awk '{print $2}' | head -1 || echo "")
fi

CRASH_COUNT=$(wc -l < "$CRASH_LOG" 2>/dev/null || echo 0)

if [ -n "$PID_CHECK" ]; then
  RESULT="launched"
  echo "[${LABEL}] ✅ App is running (PID: $PID_CHECK)"
elif [ "$CRASH_COUNT" -gt 0 ]; then
  RESULT="crashed"
  echo "[${LABEL}] ❌ App crashed (see crash.log)"
  cat "$CRASH_LOG"
else
  RESULT="launched_but_exited"
  echo "[${LABEL}] ⚠️ App launched but exited (no crash marker)"
fi

cat > "$SUMMARY" <<JSONEOF
{
  "result": "$RESULT",
  "label": "$LABEL",
  "package": "$PACKAGE",
  "crash_count": $CRASH_COUNT,
  "pid": "${PID_CHECK:-null}",
  "apk_size_bytes": $APK_SIZE
}
JSONEOF

echo "[${LABEL}] Done → $OUT"
