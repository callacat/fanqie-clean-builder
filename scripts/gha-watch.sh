#!/usr/bin/env bash
set -euo pipefail

# gha-watch.sh — Monitor GHA builds for fanqie-clean-builder
# Polls every 30s, notifies via ~/bin/notify on build completion.
#
# Usage:
#   nohup bash scripts/gha-watch.sh &

REPO="callacat/fanqie-clean-builder"
WORKFLOW="Fanqie Clean Build Pipeline"
TOKEN_FILE="$HOME/.github-token"
NOTIFY_CMD="$HOME/bin/notify"
POLL_INTERVAL=30
PID_FILE="/tmp/gha-watch-fanqie.pid"

# Ensure single instance
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[gha-watch] Already running (PID $(cat "$PID_FILE")). Exiting."
  exit 1
fi
echo $$ > "$PID_FILE"

# Load token
if [ -f "$TOKEN_FILE" ]; then
  export GITHUB_TOKEN
  GITHUB_TOKEN="$(cat "$TOKEN_FILE" | tr -d '[:space:]')"
fi

# Verify gh works
gh auth status &>/dev/null || {
  echo "[gha-watch] FATAL: gh not authenticated. Set GITHUB_TOKEN via $TOKEN_FILE"
  rm -f "$PID_FILE"
  exit 1
}

LAST_RUN=""

notify() {
  local level="$1"
  local msg="$2"
  local ts
  ts="$(date '+%H:%M:%S')"
  echo "[$ts] [$level] $msg"
  if [ -x "$NOTIFY_CMD" ]; then
    "$NOTIFY_CMD" "[GHA] ${WORKFLOW}" "${msg}" "${level}" 2>/dev/null || true
  fi
}

log() { echo "[gha-watch] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

# Initialize LAST_RUN to the latest completed run so we don't re-notify
LAST_RUN="$(gh run list -R "$REPO" -w "$WORKFLOW" --json databaseId,status \
  --jq '.[] | select(.status=="completed") | .databaseId' --limit 1 2>/dev/null || echo "")"
log "Starting monitor (last known completed run: ${LAST_RUN:-none})"

while true; do
  RUN_DATA="$(gh run list -R "$REPO" -w "$WORKFLOW" --json databaseId,status,conclusion,headBranch \
    --limit 1 2>/dev/null || echo "")"

  if [ -z "$RUN_DATA" ]; then
    sleep "$POLL_INTERVAL"
    continue
  fi

  RUN_ID="$(echo "$RUN_DATA" | jq -r '.[0].databaseId // ""')"
  STATUS="$(echo "$RUN_DATA" | jq -r '.[0].status // ""')"
  CONCLUSION="$(echo "$RUN_DATA" | jq -r '.[0].conclusion // ""')"

  # No data or same run as before → sleep
  if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "$LAST_RUN" ]; then
    sleep "$POLL_INTERVAL"
    continue
  fi

  # Only act on completed runs
  if [ "$STATUS" = "completed" ]; then
    BRANCH="$(echo "$RUN_DATA" | jq -r '.[0].headBranch // "unknown"')"

    case "$CONCLUSION" in
      success)
        notify "success" "Build #${RUN_ID} (${BRANCH}) completed successfully"
        ;;
      failure)
        FAIL_DIR="$(mktemp -d)"
        ERROR_MSG=""
        log "Build #${RUN_ID} failed, fetching logs ..."
        # Try log-failed view first (gh >=2.50), fall back to full log grep
        if gh run view "$RUN_ID" -R "$REPO" --log-failed &>/dev/null; then
          ERROR_MSG="$(gh run view "$RUN_ID" -R "$REPO" --log-failed 2>/dev/null | \
            grep -m 8 -iE '(error|Error|ERROR|FAILED|exit code [1-9]|Exception|Traceback|fatal)' | \
            head -8 || true)"
        fi
        if [ -z "$ERROR_MSG" ]; then
          ERROR_MSG="$(gh run view "$RUN_ID" -R "$REPO" --log 2>/dev/null | \
            grep -m 8 -iE '(error|Error|ERROR|FAILED|exit code [1-9]|Exception|Traceback|fatal)' | \
            head -8 || true)"
        fi
        if [ -z "$ERROR_MSG" ]; then
          ERROR_MSG="Unknown error — check manually: gh run view $RUN_ID -R $REPO"
        fi
        notify "failure" "Build #${RUN_ID} (${BRANCH}) FAILED\n${ERROR_MSG:0:800}"
        rm -rf "$FAIL_DIR"
        ;;
      cancelled)
        notify "failure" "Build #${RUN_ID} (${BRANCH}) was cancelled"
        ;;
      skipped|neutral)
        log "Build #${RUN_ID} skipped/neutral, ignoring"
        ;;
    esac

    LAST_RUN="$RUN_ID"
  fi

  sleep "$POLL_INTERVAL"
done
