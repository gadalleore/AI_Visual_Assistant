<#
.SYNOPSIS
    Easy launcher for the AI Visual Assistant Screen Watcher on Windows.

.DESCRIPTION
    Starts the screen watcher in Follow Mode friendly configuration.
    After running this (or py screen_watcher.py --fast), tell your AI
    "Follow Mode On" and later ask it to run:

        py screen_watcher.py follow grab

    The AI will then get a stable set of images it can read reliably.

    Right-click → "Run with PowerShell" also works.

.EXAMPLE
    .\Start-ScreenWatcher.ps1
    .\Start-ScreenWatcher.ps1 -Interval 0.6 -MaxAgeSeconds 300 -MaxKeep 30
#>

param(
    [double]$Interval = 0.65,
    [int]$MaxAgeSeconds = 300,
    [int]$MaxKeep = 30
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "AI Visual Assistant - starting screen watcher (follow-friendly)..." -ForegroundColor Cyan
Write-Host "Project folder: $scriptDir" -ForegroundColor DarkGray
Write-Host "After starting, use:  py screen_watcher.py follow grab   (best for AI vision)" -ForegroundColor Yellow
Write-Host ""

# Make sure dependencies are present
& py -m pip install --quiet -r requirements.txt 2>$null

# Launch with follow-oriented defaults (larger buffer, longer retention)
& py screen_watcher.py `
    --interval $Interval `
    --max-age $MaxAgeSeconds `
    --max-keep $MaxKeep `
    --follow
