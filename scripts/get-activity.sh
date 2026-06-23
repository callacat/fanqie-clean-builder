#!/usr/bin/env bash
# get-activity.sh — Download official APK and extract package + launchable activity
set -euo pipefail
curl -sL -o /tmp/official.apk \
  'https://cloud.dsdog.tk/d/google/temp/%E7%95%AA%E8%8C%84%E5%85%8D%E8%B4%B9%E5%B0%8F%E8%AF%B4_7.2.4.32.apk?sign=xUavME2Rt4Vf1FTbCppPq7sU8bRUFh29hrbIhdsXon4=:0'
ls -lh /tmp/official.apk

AAPT2=$(find /usr/local/lib/android/sdk/build-tools -name aapt2 -type f 2>/dev/null | head -1)
echo "aapt2: ${AAPT2:-NOT_FOUND}"

echo "--- packagename ---"
"$AAPT2" dump packagename /tmp/official.apk 2>/dev/null || echo "(aapt2 failed)"

echo "--- badging (filtered) ---"
"$AAPT2" dump badging /tmp/official.apk 2>/dev/null | grep -E '^package:|^launchable-activity:' || echo "(no badging output)"
