#!/usr/bin/env bash
# get-activity.sh — Download official APK and print launchable activity
set -euo pipefail
curl -sL -o /tmp/official.apk \
  'https://cloud.dsdog.tk/d/google/temp/%E7%95%AA%E8%8C%84%E5%85%8D%E8%B4%B9%E5%B0%8F%E8%AF%B4_7.2.4.32.apk?sign=xUavME2Rt4Vf1FTbCppPq7sU8bRUFh29hrbIhdsXon4=:0'
ls -lh /tmp/official.apk
echo '--- AndroidManifest package ---'
unzip -p /tmp/official.apk AndroidManifest.xml | strings | grep '^package' | head -1
echo '--- Launchable activity ---'
unzip -p /tmp/official.apk AndroidManifest.xml | strings | grep -iE '\.(Welcome|Main|Splash|Home|Launch)Activity' | head -10
echo '--- activity alias / launcher ---'
unzip -p /tmp/official.apk AndroidManifest.xml | strings | grep -B1 'android.intent.action.MAIN' | head -10
