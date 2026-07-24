#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="$ROOT/../settings/roadmap-settings.local.json"
mkdir -p "$HOME/Library/LaunchAgents"

# Read time and timezone from settings, fall back to 08:00 UTC
if [ -f "$SETTINGS" ]; then
    UPDATE_TIME=$(python3 -c "import json,sys; d=json.load(open('$SETTINGS')); print(d.get('update_time','08:00'))" 2>/dev/null || echo "08:00")
    UPDATE_TZ=$(python3 -c "import json,sys; d=json.load(open('$SETTINGS')); print(d.get('update_timezone','UTC'))" 2>/dev/null || echo "UTC")
else
    UPDATE_TIME="08:00"
    UPDATE_TZ="UTC"
fi

if [ -z "${JIRA_HOST:-}" ]; then
    echo "JIRA_HOST is not set. Export it (e.g. in your shell profile) before installing the daily update — the tool has no built-in default." >&2
    exit 1
fi

HOUR=$(echo "$UPDATE_TIME" | cut -d: -f1 | sed 's/^0//')
MINUTE=$(echo "$UPDATE_TIME" | cut -d: -f2 | sed 's/^0//')
HOUR=${HOUR:-8}
MINUTE=${MINUTE:-0}

# Prefer Homebrew python3 — /usr/bin/python3 on macOS is an Xcode stub
# that runs in a restricted context and can't access user files from launchd.
if [ -x /opt/homebrew/bin/python3 ]; then
    PYTHON3=/opt/homebrew/bin/python3
elif [ -x /usr/local/bin/python3 ]; then
    PYTHON3=/usr/local/bin/python3
else
    PYTHON3=/usr/bin/python3
fi

# Write launchers to ~/Library/Application Scripts/ which is outside
# the TCC-protected Documents folder so launchd can execute them freely.
# Both the daily-update job AND the hourly missed-update checker must use
# this indirection — launchd can't even set a working directory or exec a
# file straight out of ~/Documents/... without Full Disk Access, which
# fails as "Operation not permitted" / "cannot access parent directories"
# at shell init, before the wrapped script ever runs.
LAUNCHER_DIR="$HOME/Library/Application Scripts/jira-report"
LAUNCHER="$LAUNCHER_DIR/run.sh"
MONITOR_LAUNCHER="$LAUNCHER_DIR/monitor.sh"
mkdir -p "$LAUNCHER_DIR"
cat > "$LAUNCHER" << LAUNCHER_EOF
#!/bin/bash
exec $PYTHON3 "$(dirname "$ROOT")/app/run-daily-update.py"
LAUNCHER_EOF
chmod +x "$LAUNCHER"
cat > "$MONITOR_LAUNCHER" << MONITOR_EOF
#!/bin/bash
exec $PYTHON3 "$ROOT/check-missed-update.py"
MONITOR_EOF
chmod +x "$MONITOR_LAUNCHER"

install_plist() {
    local SRC="$ROOT/launchd/$1"
    local LABEL="$2"
    local TARGET="$HOME/Library/LaunchAgents/${LABEL}.plist"
    local TMP="$TARGET.tmp"
    sed \
        -e "s|__JIRA_REPORT_APP_DIR__|$ROOT|g" \
        -e "s|__JIRA_REPORT_ROOT__|$(dirname "$ROOT")|g" \
        -e "s|__JIRA_REPORT_LAUNCHER_DIR__|$LAUNCHER_DIR|g" \
        -e "s|__JIRA_REPORT_LAUNCHER__|$LAUNCHER|g" \
        -e "s|__JIRA_REPORT_MONITOR_LAUNCHER__|$MONITOR_LAUNCHER|g" \
        -e "s|__JIRA_REPORT_HOUR__|$HOUR|g" \
        -e "s|__JIRA_REPORT_MINUTE__|$MINUTE|g" \
        -e "s|__JIRA_REPORT_TZ__|$UPDATE_TZ|g" \
        -e "s|__JIRA_REPORT_JIRA_HOST__|$JIRA_HOST|g" \
        "$SRC" > "$TMP"
    mv "$TMP" "$TARGET"
    # JIRA_REPORT_TEST_MODE lets tests exercise plist/wrapper generation
    # without touching the real launchd state on the machine running them.
    if [ -z "${JIRA_REPORT_TEST_MODE:-}" ]; then
        launchctl unload "$TARGET" >/dev/null 2>&1 || true
        launchctl load "$TARGET"
    fi
}

install_plist "jira-report-daily-update.plist"        "roadmap-jira-report-update"
install_plist "jira-report-missed-update-check.plist" "roadmap-jira-report-missed-update-check"
