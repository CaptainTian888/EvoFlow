# Windows contributor scripts

Isolated **dev stack** only.

| Script | Purpose |
|--------|---------|
| `dev-stack-isolated.bat` | One-click isolated stack |
| `start-dev-stack.ps1` / `restart-dev-stack.*` | Start / restart |
| `watch-external-gateway.ps1` | Supervise uvicorn on 8070; log every exit + auto-restart |
| `backend-common.ps1` | Shared helpers |
| `pytest-backend.ps1` | Backend tests |

### Unstable Gateway (ERR_CONNECTION_REFUSED)

1. Run Gateway under supervisor (not a bare terminal uvicorn):
   ```powershell
   .\scripts\windows\watch-external-gateway.ps1 -Port 8070
   ```
2. Desktop with `$env:EVOFLOW_GATEWAY_URL='http://127.0.0.1:8070'`
3. When it flaps, grep:
   - `[gateway-watch]` / `window.__EVOFLOW_GATEWAY_WATCH__` (UI)
   - `~/.evoflow-dev/logs/gateway-supervisor.log` (exit codes)
   - `~/.evoflow-dev/logs/evoflow-gateway-*.log` → `[GATEWAY-EXIT]` (why Python shut down)

Publish / release: `../maintainer/windows/`.
