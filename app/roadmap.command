#!/bin/bash
set -e
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1 || ! python3 --version >/dev/null 2>&1; then
    echo ""
    echo "Python isn't set up on this Mac yet. Triggering Apple's installer for it..."
    xcode-select --install >/dev/null 2>&1 || true
    echo ""
    echo "If a popup appeared, click Install and wait for it to finish (a"
    echo "few minutes), then run this tool again."
    echo "If nothing appeared, the Command Line Tools may already be present"
    echo "but broken — run 'xcode-select --install' yourself in Terminal to see why."
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

python3 app/roadmap-launcher.py
