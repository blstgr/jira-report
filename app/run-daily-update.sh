#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
STATE="$ROOT/settings/roadmap-settings.json"
STAMP="$ROOT/.last-daily-run-utc"
NOW_UTC="$(date -u +%Y-%m-%dT%H:%M)"
TODAY_UTC="$(date -u +%Y-%m-%d)"
MINUTE_UTC="$(date -u +%H:%M)"

if [[ ! -f "$STATE" ]]; then
  exit 0
fi

if [[ "$MINUTE_UTC" != "00:00" ]]; then
  exit 0
fi

if [[ -f "$STAMP" ]]; then
  LAST="$(cat "$STAMP")"
  if [[ "$LAST" == "$TODAY_UTC" ]]; then
    exit 0
  fi
fi

python3 "$ROOT/jira-report.py" --state "$STATE"
printf "%s\n" "$TODAY_UTC" > "$STAMP"
