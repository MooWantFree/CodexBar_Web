param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectPath = (Get-Location).Path,

    [Parameter(Mandatory = $false)]
    [string]$TaskName = 'Codex Token Report Daily Scan',

    [Parameter(Mandatory = $false)]
    [datetime]$At = '23:55'
)

$ErrorActionPreference = 'Stop'
$resolvedProject = (Resolve-Path -LiteralPath $ProjectPath).Path
$pyproject = Join-Path $resolvedProject 'pyproject.toml'
if (-not (Test-Path -LiteralPath $pyproject)) {
    throw "找不到 $pyproject"
}

$uv = (Get-Command uv -ErrorAction Stop).Source
$action = New-ScheduledTaskAction `
    -Execute $uv `
    -Argument 'run codex-token-report --scan-only' `
    -WorkingDirectory $resolvedProject
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Incrementally scans local Codex session logs for token usage.' `
    -Force | Out-Null

Write-Host "已创建计划任务：$TaskName（每天 $($At.ToString('HH:mm'))）"
