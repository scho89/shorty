# Production Deployment

This project can run behind Caddy/HAProxy with SSL terminated at the proxy and Django served locally over HTTP by Waitress.

## Server Checklist

- Install Python 3.12
- Install Microsoft ODBC Driver 17 for SQL Server
- Create `.venv` and install `requirements.txt`
- Fill in `.env` with production values
- Set `DJANGO_SETTINGS_PROFILE=prod`
- Run migrations and `collectstatic`
- Start Waitress on a private listen address such as `127.0.0.1:8080`

## Required `.env` Values

- `SECRET_KEY`
- `DEBUG=False`
- `DJANGO_SETTINGS_PROFILE=prod`
- `DB_HOST`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_PORT=1433`
- `ALLOWED_HOSTS=your-public-domain`
- `CSRF_TRUSTED_ORIGINS=https://your-public-domain`
- `WAITRESS_HOST=127.0.0.1`
- `WAITRESS_PORT=8080`

Optional:

- `ALLOW_LOCAL_HOSTS=True` if you want `127.0.0.1` and `localhost` allowed in production for local checks

## Prepare the App

```powershell
.\scripts\prepare-prod.ps1
```

## Start Waitress

```powershell
.\scripts\start-waitress.ps1
```

Or explicitly:

```powershell
.\scripts\start-waitress.ps1 -ListenHost 127.0.0.1 -ListenPort 8080
```

## Health Check

Use this endpoint from HAProxy or Caddy:

```text
/_healthz/
```

It returns `200` when Django and the database are both reachable, and `503` if the app is up but the database is failing.

## Proxy Notes

- Forward the original `Host` header
- Forward `X-Forwarded-Proto: https`
- Proxy to `127.0.0.1:8080`

## Windows Service Suggestion

If this server is Windows, register `scripts\start-waitress.ps1` with NSSM or another service manager so the app starts on boot.

Example NSSM target:

- Program: `powershell.exe`
- Arguments: `-ExecutionPolicy Bypass -File C:\GitHub\shorty\scripts\start-waitress.ps1`
- Startup directory: `C:\GitHub\shorty`

Or use the helper script in this repo:

```powershell
.\scripts\install-waitress-service.ps1 -ServiceName ShortyWaitress -StartService
```

If NSSM is not on `PATH`, pass its location explicitly:

```powershell
.\scripts\install-waitress-service.ps1 -NssmPath C:\nssm\win64\nssm.exe -StartService
```
