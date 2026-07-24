$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$state = Join-Path $root "settings/roadmap-settings.json"
$stamp = Join-Path $root ".last-daily-run-utc"
$nowUtc = [DateTime]::UtcNow

if (-not (Test-Path $state)) { exit 0 }
if ($nowUtc.ToString("HH:mm") -ne "00:00") { exit 0 }

$todayUtc = $nowUtc.ToString("yyyy-MM-dd")
if (Test-Path $stamp) {
    $last = Get-Content $stamp -Raw
    if ($last -eq $todayUtc) { exit 0 }
}

python "$root\jira-report.py" --state "$state"
Set-Content -Path $stamp -Value $todayUtc -NoNewline
