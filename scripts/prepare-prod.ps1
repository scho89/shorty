param()

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found at .venv. Create it before running preparation."
}

$env:DJANGO_SETTINGS_PROFILE = "prod"

& $python -m pip install -r requirements.txt
& $python manage.py check --deploy
& $python manage.py migrate
& $python manage.py collectstatic --noinput
