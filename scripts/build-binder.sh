#!/usr/bin/env bash
# build-binder.sh — Cross-compile binder_linux.ko for ARM64 on GHA
# Works with Oracle kernel 6.8.0-1054 or compatible
set -euo pipefail

KVERSION="${1:-6.8.0-1054-oracle}"
SRCDIR="/tmp/kernel-source"
OUTDIR="/tmp/binder-output"
mkdir -p "$OUTDIR"

echo "=== Kernel version: $KVERSION ==="

# Install cross-compiler
sudo apt-get update -qq
sudo apt-get install -y -qq aarch64-linux-gnu-gcc 2>&1 | tail -2
export CROSS_COMPILE=aarch64-linux-gnu-
export ARCH=arm64

# Get kernel source
echo "=== Getting kernel source ==="
# For Oracle kernel, need to add the repo
sudo add-apt-repository -y 'deb http://archive.ubuntu.com/ubuntu/ jammy-updates main universe multiverse' 2>/dev/null
sudo add-apt-repository -y 'deb-src http://archive.ubuntu.com/ubuntu/ jammy-updates main universe multiverse' 2>/dev/null
sudo apt-get update -qq 2>&1 | tail -1

cd /tmp
apt-get source linux-oracle-6.8 2>&1 | tail -5
# Find source dir
SRC_DIR=$(find /tmp -maxdepth 1 -type d -name 'linux-oracle-6.8*' | head -1)
if [ -z "$SRC_DIR" ]; then
  echo "ERROR: kernel source not found"
  exit 1
fi
echo "Source: $SRC_DIR"
cd "$SRC_DIR"

# Configure for binder module
echo "=== Configuring kernel ==="
# Use generic arm64 defconfig as base, enable binder
make ARCH=arm64 defconfig 2>&1 | tail -2
./scripts/config --enable CONFIG_ANDROID
./scripts/config --enable CONFIG_ANDROID_BINDER_IPC
./scripts/config --set-val CONFIG_ANDROID_BINDER_IPC m
./scripts/config --enable CONFIG_ANDROID_BINDERFS
./scripts/config --set-val CONFIG_ANDROID_BINDERFS m
./scripts/config --set-str CONFIG_ANDROID_BINDER_DEVICES ""
./scripts/config --set-val CONFIG_ANDROID_BINDER_IPC_SELFTEST n
./scripts/config --disable CONFIG_ANDROID_LOW_MEMORY_KILLER

# Prepare module build
make ARCH=arm64 olddefconfig 2>&1 | tail -2
make ARCH=arm64 prepare 2>&1 | tail -2
make ARCH=arm64 scripts 2>&1 | tail -2

# Build only binder module
echo "=== Compiling binder_linux.ko ==="
make ARCH=arm64 M=drivers/android modules 2>&1 | tail -10

# Verify
if [ -f drivers/android/binder_linux.ko ]; then
  cp drivers/android/binder_linux.ko "$OUTDIR/"
  cp drivers/android/binderfs.ko "$OUTDIR/" 2>/dev/null || true
  echo "✅ Build success"
  file "$OUTDIR/binder_linux.ko"
  ls -lh "$OUTDIR/"
else
  echo "❌ Build failed"
  exit 1
fi
