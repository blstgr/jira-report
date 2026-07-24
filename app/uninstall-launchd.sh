#!/bin/bash
set -euo pipefail

uninstall_plist() {
    local TARGET="$HOME/Library/LaunchAgents/$1.plist"
    launchctl unload "$TARGET" >/dev/null 2>&1 || true
    rm -f "$TARGET"
    echo "Removed: $1"
}

uninstall_plist "roadmap-jira-report-update"
uninstall_plist "roadmap-jira-report-missed-update-check"
