param(
    [string]$ListenHost = "",
    [int]$ListenPort = 0
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found at .venv. Create it before starting Waitress."
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

if (-not $ListenHost) {
    $ListenHost = if ($env:WAITRESS_HOST) { $env:WAITRESS_HOST } else { "127.0.0.1" }
}

if ($ListenPort -eq 0) {
    $ListenPort = if ($env:WAITRESS_PORT) { [int]$env:WAITRESS_PORT } else { 8080 }
}

Write-Host "Starting Waitress on ${ListenHost}:$ListenPort with DJANGO_SETTINGS_PROFILE=prod"
& $python -m waitress --listen="${ListenHost}:$ListenPort" config.wsgi:application
