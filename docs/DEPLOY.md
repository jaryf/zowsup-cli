# Zowsup Dashboard — Deployment Guide

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Node.js | 20+ |
| npm | 9+ |
| SQLite | 3.35+ (bundled with Python 3.11) |

---

## Option A — Direct (no Docker)

### 1. Clone and prepare

```bash
git clone <repo-url> zowsup-cli
cd zowsup-cli
```

### 2. Backend setup

```bash
# Create virtual environment
python -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate
# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Open .env and set:
#   DASHBOARD_API_TOKEN=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
#   DASHBOARD_DEBUG=false
#   LOG_LEVEL=INFO
```

### 4. Run pre-flight checks

```bash
python scripts/check_production.py
```

All critical checks must pass before continuing.

### 5. Start the backend

```bash
python script/dashboard.py# Backend listens on http://0.0.0.0:5000
```

### 6. Build the frontend

```bash
cd app/dashboard/frontend
npm install
npm run build
# Output: app/dashboard/frontend/dist/
```

### 7. Serve the frontend

#### Option A1 — Serve via Flask (simplest)

Add the `dist/` folder as Flask static files (not implemented by default —
use Nginx or a CDN instead for production).

#### Option A2 — Nginx (recommended)

```nginx
server {
    listen 80;
    root /path/to/zowsup-cli/app/dashboard/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /socket.io/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

## Option B — Docker Compose

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — set DASHBOARD_API_TOKEN at minimum
```

### 2. Build and start

```bash
docker compose up --build -d
```

Services:
- **backend** → http://localhost:5000
- **frontend** (Nginx) → http://localhost:80

### 3. View logs

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

### 4. Stop

```bash
docker compose down
```

---

## Verifying the deployment

```bash
# Health check (no auth required)
curl http://localhost:5000/api/health

# Expected response:
# {"status": "ok", "journal_mode": "wal", "tables": {...}}
```

Open **http://localhost:5000/api/docs** in a browser to view the Swagger UI.

---

## Updating

```bash
git pull
pip install -r requirements.txt        # backend deps
cd app/dashboard/frontend && npm install    # frontend deps
npm run build                          # rebuild frontend
# Restart: python script/dashboard.py  (or: docker compose restart backend)
```

---

## Environment variables reference

See [`.env.example`](../.env.example) for the full list with descriptions.

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHBOARD_API_TOKEN` | _(empty)_ | Bearer token for API auth |
| `DASHBOARD_HOST` | `0.0.0.0` | Bind address |
| `DASHBOARD_PORT` | `5000` | Port |
| `DASHBOARD_DEBUG` | `false` | Debug mode (never `true` in production) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LOG_DIR` | `logs/` | Log file directory |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
