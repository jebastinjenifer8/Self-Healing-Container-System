# Self-Healing Container Management System

A local Windows-friendly project using Python, Flask, Docker, HTML/CSS/JavaScript, and SQLite.

## Features
- Lists Docker containers and their status.
- Monitors opted-in containers every 5 seconds.
- Attempts to restart opted-in stopped containers.
- Stores recovery events persistently in `recovery_logs.db`.
- Dashboard refreshes every 5 seconds.
- Recovery API: `POST /api/recover/<container_name>`.
- Limits repeated recovery attempts and waits before retrying.

## Requirements
- Windows 10/11
- Docker Desktop running with the Linux engine
- Python 3.10 or newer
- VS Code (recommended)

## Setup in PowerShell

Open this folder in VS Code, then run:

```powershell
py -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you already created and activated `venv`, skip the first two setup commands as appropriate.

## Start the application

Make sure Docker Desktop is running, then:

```powershell
python app.py
```

Open the dashboard at http://127.0.0.1:5000

API endpoints:
- `GET /api/status`
- `GET /api/containers`
- `GET /api/logs`
- `POST /api/recover/<container_name>`

## Create an opted-in test container

The monitor deliberately only restarts containers that have the label `self_heal=true`. This avoids restarting one-shot containers such as `hello-world` or unrelated containers.

Create a labelled Nginx test container:

```powershell
docker run -d --name self-healing-test --label self_heal=true nginx:alpine
```

If a container with that name already exists, remove it only if it is your disposable test container:

```powershell
docker rm -f self-healing-test
docker run -d --name self-healing-test --label self_heal=true nginx:alpine
```

Test automatic recovery:
1. Leave `python app.py` running.
2. Open a second terminal.
3. Run `docker stop self-healing-test`.
4. Wait up to about 5–10 seconds for the next monitor check and startup.
5. Run `docker ps` and confirm `self-healing-test` is `Up`.
6. Visit `/api/logs` or the dashboard to review the recovery event.

## Important notes
- The monitor runs inside the Flask process; keep the terminal and app running.
- Only containers with `self_heal=true` are managed.
- This starter project checks whether a container is running; it does not yet check application-level HTTP health inside every container.
- SQLite recovery logs persist between app restarts.
- Do not expose this development dashboard publicly. It has no authentication and can start containers through its local API.
- `venv/` and the generated SQLite database are not included in the ZIP. The database is created automatically at startup.
