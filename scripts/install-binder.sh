#!/usr/bin/env bash
# install-binder.sh — Install binder module with automatic rollback on failure
set -euo pipefail

MODULE_PATH="/tmp/binder-out/binder_linux.ko"
ROLLBACK_DIR="/tmp/binder-rollback"
mkdir -p "$ROLLBACK_DIR"

echo "=== Pre-install snapshot ==="
lsmod | grep binder > "$ROLLBACK_DIR/lsmod-before.txt" 2>/dev/null || true
[ -f /dev/binder ] && cksum /dev/binder > "$ROLLBACK_DIR/dev-binder-cksum.txt" 2>/dev/null || true
find /dev -name '*binder*' 2>/dev/null > "$ROLLBACK_DIR/dev-binder-before.txt" || true

rollback() {
  local msg="$1"
  echo "❌ $msg — rolling back"
  # Unload new module if loaded
  rmmod binder_linux 2>/dev/null || true
  # Reload original (Oracle) module
  ORIG_MODULE=$(find /usr/lib/modules -name 'binder_linux.ko' 2>/dev/null | head -1)
  if [ -n "$ORIG_MODULE" ]; then
    insmod "$ORIG_MODULE" 2>/dev/null || true
  fi
  # Restart redroid
  docker compose -f /opt/redroid/docker-compose.yml restart 2>/dev/null || true
  echo "Rollback complete."
  exit 1
}

echo "=== Step 1: Load binder module ==="
ORIG_MODULE=$(find /usr/lib/modules -name 'binder_linux.ko' 2>/dev/null | head -1 || true)
if [ -f "$ORIG_MODULE" ]; then
  # Backup Oracle module
  cp "$ORIG_MODULE" "$ROLLBACK_DIR/original-binder.ko"
fi

# Remove old module
rmmod binder_linux 2>/dev/null || true
sleep 1

# Install new module
insmod "$MODULE_PATH" 2>&1 || rollback "insmod failed"

# Verify module loaded
lsmod | grep -q binder_linux || rollback "module did not load"

echo "=== Step 2: Create device nodes ==="
cat /proc/devices | grep binder > "$ROLLBACK_DIR/binder-major.txt"

MAJOR=$(awk '/binder/ {print $1}' /proc/devices)
echo "Binder major: $MAJOR"

rm -f /dev/binder /dev/hwbinder /dev/vndbinder
mknod /dev/binder c "$MAJOR" 0 || rollback "mknod binder failed"
mknod /dev/hwbinder c "$MAJOR" 1 || rollback "mknod hwbinder failed"
mknod /dev/vndbinder c "$MAJOR" 2 || rollback "mknod vndbinder failed"
chmod 666 /dev/binder /dev/hwbinder /dev/vndbinder

# Verify device nodes are live
timeout 3 sh -c 'ls -la /dev/binder /dev/hwbinder /dev/vndbinder' || rollback "device nodes not created"

echo "=== Step 3: Functional test ==="
# A working binder device should allow a simple open+close
TEST_OUT=$(timeout 5 sh -c 'exec 3<>/dev/binder && echo OK' 2>&1 || echo "FAIL")
echo "Binder open test: $TEST_OUT"

echo "=== Step 4: Test redroid container ==="
docker compose -f /opt/redroid/docker-compose.yml down 2>/dev/null || true
docker compose -f /opt/redroid/docker-compose.yml up -d 2>&1 | tail -3
sleep 15

CONTAINER=$(docker ps --filter name=redroid --format '{{.Names}}' | head -1)
if [ -z "$CONTAINER" ]; then
  rollback "redroid container not running"
fi

# Test binder inside container
BINDER_TEST=$(timeout 5 docker exec "$CONTAINER" sh -c 'ls -la /dev/binder 2>/dev/null && echo BINDER_OK' 2>&1 || echo "FAIL")
echo "Container binder: $BINDER_TEST"

# Test APK install
APK="/data/local/tmp/official.apk"
if docker exec "$CONTAINER" test -f "$APK" 2>/dev/null; then
  INSTALL_TEST=$(timeout 60 docker exec "$CONTAINER" sh -c 'pm install -r '"$APK"' 2>&1' | tail -3 || echo "INSTALL_FAILED")
  echo "Install test: $INSTALL_TEST"
  if echo "$INSTALL_TEST" | grep -qi 'Success\|pkg='; then
    echo "✅ BINDER WORKS"
  else
    rollback "APK install failed"
  fi
else
  echo "(APK not preloaded, skipping install test)"
fi

echo "=== Step 5: Persist across reboot ==="
# Write modprobe config
cat > /etc/modprobe.d/binder.conf << 'EOF'
options binder_linux devices="binder,hwbinder,vndbinder"
EOF

# Load at boot
if ! grep -q 'binder_linux' /etc/modules 2>/dev/null; then
  echo 'binder_linux' >> /etc/modules
fi
echo "✅ Persistence configured"

echo "=== ALL OK ==="
