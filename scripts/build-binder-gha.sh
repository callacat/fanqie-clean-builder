#!/usr/bin/env bash
# build-binder-gha.sh — Cross-compile binder_linux.ko for ARM64 on GHA
# Output: /tmp/binder-out/binder_linux.ko (upload as artifact)
set -euo pipefail
KVERSION="${1:-6.8.0-1054-oracle}"
OUTDIR="/tmp/binder-out"
mkdir -p "$OUTDIR"

echo "=== Installing cross-compiler ==="
sudo apt-get update -qq
sudo apt-get install -y -qq aarch64-linux-gnu-gcc 2>&1 | tail -1
aarch64-linux-gnu-gcc --version | head -1

echo "=== Adding source repos ==="
echo 'deb http://archive.ubuntu.com/ubuntu/ jammy-updates main universe multiverse' | sudo tee -a /etc/apt/sources.list
echo 'deb-src http://archive.ubuntu.com/ubuntu/ jammy-updates main universe multiverse' | sudo tee -a /etc/apt/sources.list
sudo apt-get update -qq 2>&1 | tail -1

echo "=== Getting Oracle kernel source ==="
cd /tmp
apt-get source linux-oracle-6.8 2>&1 | tail -5
SRC_DIR=$(find /tmp -maxdepth 1 -type d -name 'linux-oracle*' | head -1)
if [ -z "$SRC_DIR" ]; then
  # Fallback: generic linux source
  apt-get source linux-image-unsigned-"$KVERSION" 2>&1 | tail -5
  SRC_DIR=$(find /tmp -maxdepth 1 -type d -name 'linux-*' | head -1)
fi
echo "Source dir: $SRC_DIR"
cd "$SRC_DIR"

echo "=== Configuring ==="
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- defconfig 2>&1 | tail -1
./scripts/config --enable CONFIG_ANDROID
./scripts/config --module CONFIG_ANDROID_BINDER_IPC
./scripts/config --enable CONFIG_ANDROID_BINDERFS
./scripts/config --module CONFIG_ANDROID_BINDERFS
./scripts/config --set-str CONFIG_ANDROID_BINDER_DEVICES "binder,hwbinder,vndbinder"

echo "=== Preparing ==="
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig 2>&1 | tail -1
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- prepare 2>&1 | tail -1

echo "=== Building binder module ==="
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- M=drivers/android 2>&1 | tail -10

if [ -f drivers/android/binder_linux.ko ]; then
  cp drivers/android/binder_linux.ko "$OUTDIR/"
  echo "✅ SUCCESS"
  file "$OUTDIR/binder_linux.ko"
  ls -lh "$OUTDIR/"
else
  # Try building via modules_prepare first
  make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- modules_prepare 2>&1 | tail -2
  make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- M=drivers/android 2>&1 | tail -10
  if [ -f drivers/android/binder_linux.ko ]; then
    cp drivers/android/binder_linux.ko "$OUTDIR/"
    echo "✅ SUCCESS (after modules_prepare)"
  else
    echo "❌ FAILED"
    exit 1
  fi
fi
