param(
    [string]$ServiceName = "ShortyWaitress",
    [switch]$SkipCheck,
    [switch]$SkipCollectstatic,
    [switch]$SkipRestart
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found at .venv. Create it before restarting the service."
}

$env:DJANGO_SETTINGS_PROFILE = "prod"

$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') {
            return
        }

        $name, $value = $_ -split '=', 2
        $name = $name.Trim()
        $value = $value.Trim()

        if ($name) {
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

Write-Host "Project root: $projectRoot"
Write-Host "Service name: $ServiceName"
Write-Host "DJANGO_SETTINGS_PROFILE=prod"

if (-not $SkipCheck) {
    Write-Host ""
    Write-Host "[1/3] Running Django system checks..."
    & $python manage.py check
}

if (-not $SkipCollectstatic) {
    Write-Host ""
    Write-Host "[2/3] Running collectstatic..."
    Write-Host "This step is included because production serves files from staticfiles/, so CSS changes are not reflected until collectstatic runs."
    & $python manage.py collectstatic --noinput
}

if (-not $SkipRestart) {
    Write-Host ""
    Write-Host "[3/3] Restarting Windows service..."
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "Service '$ServiceName' was not found."
    }

    Restart-Service -Name $ServiceName
    Start-Sleep -Seconds 2

    $service = Get-Service -Name $ServiceName
    Write-Host ""
    Write-Host "Service status after restart:"
    $service | Select-Object Status, Name, DisplayName | Format-Table -AutoSize
} else {
    Write-Host ""
    Write-Host "[3/3] Service restart skipped."
}

Write-Host ""
Write-Host "Done."
