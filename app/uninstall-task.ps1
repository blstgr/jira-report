$ErrorActionPreference = "Stop"

$taskName = "roadmap-jira-report-update"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Removed daily Jira report task: $taskName"
