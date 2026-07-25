#!/bin/bash
set -e
cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1 || ! python3 --version >/dev/null 2>&1; then
    echo ""
    echo "Python is required to run this tool, and it isn't available yet."
    echo ""
    echo "If macOS just showed a popup about installing the Command Line"
    echo "Developer Tools and you dismissed it, open Terminal and run:"
    echo ""
    echo "    xcode-select --install"
    echo ""
    echo "Click Install when the popup appears, wait for it to finish, then"
    echo "run this tool again."
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

python3 app/roadmap-launcher.py
