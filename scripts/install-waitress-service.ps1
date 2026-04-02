param(
    [string]$ServiceName = "ShortyWaitress",
    [string]$DisplayName = "Shorty Waitress",
    [string]$Description = "Runs the Shorty Django application with Waitress.",
    [string]$NssmPath = "",
    [switch]$StartService
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $projectRoot "scripts\start-waitress.ps1"
$stdoutLog = Join-Path $projectRoot "logs\waitress-service.out.log"
$stderrLog = Join-Path $projectRoot "logs\waitress-service.err.log"

function Resolve-NssmPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if ([System.IO.Path]::IsPathRooted($RequestedPath)) {
            if (Test-Path $RequestedPath) {
                return $RequestedPath
            }
        } else {
            $candidate = Join-Path $projectRoot $RequestedPath
            if (Test-Path $candidate) {
                return $candidate
            }
        }

        throw "NSSM executable not found: $RequestedPath"
    }

    $candidates = @(
        "nssm.exe",
        (Join-Path $projectRoot "tools\nssm\win64\nssm.exe"),
        (Join-Path $projectRoot "tools\nssm\win32\nssm.exe"),
        "C:\Program Files\nssm\win64\nssm.exe",
        "C:\Program Files\nssm\win32\nssm.exe",
        "C:\nssm\win64\nssm.exe",
        "C:\nssm\win32\nssm.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -eq "nssm.exe") {
            $command = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($command) {
                return $command.Source
            }
            continue
        }

        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "NSSM executable was not found. Install NSSM or pass -NssmPath."
}

$nssm = Resolve-NssmPath -RequestedPath $NssmPath
$powershellExe = (Get-Command powershell.exe -ErrorAction Stop).Source

if (-not (Test-Path $startScript)) {
    throw "Start script not found: $startScript"
}

New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "logs") | Out-Null

$serviceExists = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

if (-not $serviceExists) {
    & $nssm install $ServiceName $powershellExe "-ExecutionPolicy" "Bypass" "-File" $startScript
} else {
    Write-Host "Service '$ServiceName' already exists. Updating its settings."
}

& $nssm set $ServiceName AppDirectory $projectRoot
& $nssm set $ServiceName DisplayName $DisplayName
& $nssm set $ServiceName Description $Description
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppStdout $stdoutLog
& $nssm set $ServiceName AppStderr $stderrLog
& $nssm set $ServiceName AppRotateFiles 1
& $nssm set $ServiceName AppRotateOnline 1
& $nssm set $ServiceName AppRotateSeconds 86400
& $nssm set $ServiceName AppRotateBytes 10485760

if ($StartService) {
    Start-Service -Name $ServiceName
    Write-Host "Started service '$ServiceName'."
} else {
    Write-Host "Installed or updated service '$ServiceName'."
    Write-Host "Start it with: Start-Service -Name $ServiceName"
}
