#!/bin/bash
set -e
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1 || ! python3 --version >/dev/null 2>&1; then
    echo ""
    echo "Python is required to run this tool, and it isn't set up on this Mac yet."
    echo "Triggering Apple's installer for it..."
    xcode-select --install >/dev/null 2>&1 || true
    echo ""
    echo "If a popup appeared, click Install and wait for it to finish (a"
    echo "few minutes), then run this tool again."
    echo ""
    echo "If you closed the popup, or nothing appeared, install Python"
    echo "directly instead (no Xcode needed) from:"
    echo "    https://www.python.org/downloads/macos/"
    echo "Then run this tool again."
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

python3 app/roadmap-launcher.py
