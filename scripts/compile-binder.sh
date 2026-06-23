#!/usr/bin/env bash
# compile-binder.sh — Compile binder_linux.ko natively on ARM64 VPS
# Usage: bash compile-binder.sh
# Output: /tmp/binder-out/binder_linux.ko
set -euo pipefail

SRCDIR="${1:-/tmp/linux-oracle-6.8-6.8.0}"
OUTDIR="/tmp/binder-out"
mkdir -p "$OUTDIR"

KVERSION=$(uname -r)
echo "=== Running kernel: $KVERSION ==="
echo "=== Source: $SRCDIR ==="

if [ ! -d "$SRCDIR" ]; then
  echo "❌ Kernel source not found at $SRCDIR"
  echo "Trying apt-get source..."
  cd /tmp
  apt-get source linux-oracle-6.8 2>&1 | tail -3
  SRCDIR=$(find /tmp -maxdepth 1 -type d -name 'linux-oracle*' | head -1)
  [ -d "$SRCDIR" ] || { echo "Still no source"; exit 1; }
fi

cd "$SRCDIR"

# Use running kernel's config as base
cp /boot/config-"$KVERSION" .config

echo "=== Enabling Android binder in config ==="
./scripts/config --enable CONFIG_ANDROID
./scripts/config --module CONFIG_ANDROID_BINDER_IPC
./scripts/config --module CONFIG_ANDROID_BINDERFS
./scripts/config --module CONFIG_ANDROID_BINDER_IPC_SELFTEST 2>/dev/null || true
./scripts/config --set-str CONFIG_ANDROID_BINDER_DEVICES "binder,hwbinder,vndbinder"

# Ensure we have Module.symvers from running kernel
cp /lib/modules/"$KVERSION"/build/Module.symvers Module.symvers

echo "=== Preparing ==="
make olddefconfig 2>&1 | tail -2
make prepare 2>&1 | tail -2
make modules_prepare 2>&1 | tail -2

echo "=== Compiling binder module ==="
make M=drivers/android 2>&1 | tail -10

if [ -f drivers/android/binder_linux.ko ]; then
  cp drivers/android/binder_linux.ko "$OUTDIR/"
  [ -f drivers/android/binderfs.ko ] && cp drivers/android/binderfs.ko "$OUTDIR/" || true
  echo "✅ SUCCESS"
  file "$OUTDIR/binder_linux.ko"
  ls -lh "$OUTDIR/"
  modinfo "$OUTDIR/binder_linux.ko" | grep -E 'filename|description|vermagic'
else
  echo "❌ FAILED"
  exit 1
fi
