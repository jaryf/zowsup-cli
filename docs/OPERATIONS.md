# Zowsup Dashboard — Operations Manual

## Daily operations

### Starting the server

```bash
# Direct
python script/dashboard.py

# Or start both frontend + backend
python script/start.py

# Docker
docker compose up -d
```

### Stopping the server

```bash
# Direct — Ctrl+C or:
kill $(cat data/bot.pid)

# Docker
docker compose down
```

### Health check

```bash
curl http://localhost:5000/api/health
```

Returns `{"status": "ok"}` when healthy, `"degraded"` when some DB tables
are missing, `"error"` when the DB is unreachable.

---

## Database maintenance

### Backup (run daily via cron or Task Scheduler)

```bash
python scripts/backup_db.py --keep 30
```

Backs up `data/dashboard.db` to `data/backups/dashboard_<timestamp>.db`.

#### Cron example (Linux, daily at 02:00)
```cron
0 2 * * * cd /opt/zowsup-cli && .venv/bin/python scripts/backup_db.py --keep 30
```

#### Task Scheduler example (Windows)
```
Program:   C:\path\to\zowsup-cli\.venv\Scripts\python.exe
Arguments: scripts\backup_db.py --keep 30
Start in:  C:\path\to\zowsup-cli
```

### Restore from backup

```bash
# List available backups
python scripts/restore_db.py --list

# Restore most recent
python scripts/restore_db.py --latest

# Restore specific file
python scripts/restore_db.py data/backups/dashboard_20260428_020000.db
```

**Always stop the dashboard server before restoring.**

### Manual SQLite inspection

```bash
sqlite3 data/dashboard.db
.tables
SELECT count(*) FROM chat_messages;
PRAGMA integrity_check;
.quit
```

---

## Log management

Logs are written to `logs/dashboard.log` with daily rotation (10 MB per
file, 5 backups retained by default).

### View recent logs

```bash
# Linux
tail -f logs/dashboard.log

# Windows PowerShell
Get-Content logs\dashboard.log -Wait -Tail 50
```

### Adjust log level

Set `LOG_LEVEL=DEBUG` in `.env` and restart to see verbose output.
Reset to `LOG_LEVEL=INFO` for normal operation.

---

## API token rotation

1. Generate a new token:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Update `DASHBOARD_API_TOKEN` in `.env`.
3. Restart the server.
4. Update any clients (bots, scripts) that use the old token.

**Or** use the API endpoint (while the old token is still valid):
```bash
curl -X POST http://localhost:5000/api/auth/refresh \
     -H "Authorization: Bearer <current-token>"
# Response includes new_token and instructions
```

---

## Monitoring

### Check if the process is running

```bash
# Linux
ps aux | grep script/dashboard
# or
curl -sf http://localhost:5000/api/health && echo "UP" || echo "DOWN"
```

### Key metrics to watch

| Metric | Where to find |
|--------|---------------|
| DB size | `ls -lh data/dashboard.db` |
| Log errors | `grep ERROR logs/dashboard.log` |
| Response time | Nginx access log / APM |
| Memory usage | `ps -o pid,rss,command -p <pid>` |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `401 Unauthorized` on all requests | Token not set or wrong | Check `DASHBOARD_API_TOKEN` in `.env` |
| `{"status": "degraded"}` from health | DB tables missing | Restart server (db_init re-runs on startup) |
| Server won't start, port in use | Another process on port 5000 | Change `DASHBOARD_PORT` or kill the other process |
| Frontend shows "Network Error" | Backend not running or CORS | Start backend; check `CORS_ORIGINS` in `.env` |
| High memory after long runtime | SQLite WAL checkpoint not running | Run `PRAGMA wal_checkpoint(TRUNCATE)` in sqlite3 |
| Log file growing too large | Log rotation not configured | See 8.10 — rotating file handler is active by default |

---

## Security checklist

- [ ] `DASHBOARD_API_TOKEN` is set and ≥ 32 characters
- [ ] `DASHBOARD_DEBUG=false`
- [ ] `.env` file is not world-readable (`chmod 600 .env`)
- [ ] `data/` directory is not publicly accessible
- [ ] TLS is terminated at Nginx/load-balancer level
- [ ] `CORS_ORIGINS` is restricted to your actual domain
- [ ] Backups are stored off-server
