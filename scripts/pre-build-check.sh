#!/usr/bin/env bash
# pre-build-check.sh — Check memory headroom before kicking off a build
# Exits 1 if too tight, prints warning if marginal.
set -euo pipefail

AVAILABLE_MB=$(free -m | awk '/^Mem:/{print $7}')
SWAP_FREE_MB=$(free -m | awk '/^Swap:/{print $4}')
TOTAL_MB=$((AVAILABLE_MB + SWAP_FREE_MB))

echo "[pre-build] Mem avail: ${AVAILABLE_MB}MB  Swap free: ${SWAP_FREE_MB}MB  Headroom: ${TOTAL_MB}MB"

if [ "$TOTAL_MB" -lt 1024 ]; then
  echo "[pre-build] ❌ CRITICAL: less than 1GB headroom ($TOTAL_MB MB). Aborting."
  exit 1
elif [ "$TOTAL_MB" -lt 2048 ]; then
  echo "[pre-build] ⚠️  WARNING: less than 2GB headroom ($TOTAL_MB MB). Build may be slow."
fi
