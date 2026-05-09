
# Zowsup-CLI

A restructured [Zowsup](https://github.com/clarithromycine/zowsup/) with async architecture, AI integration, and a full-stack web dashboard for monitoring and managing WhatsApp bot accounts.

---

## Requirements

- Python 3.10+
- Node.js 18+ (dashboard frontend only)

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Configuration

```bash
cp conf/config.conf.example conf/config.conf
```

Edit `conf/config.conf`:

```ini
PLATFORM=linux
PYTHON=/usr/bin/python
ACCOUNT_PATH=/data/account/
TMP_ACCOUNT_PATH=/data/account/tmp/
DOWNLOAD_PATH=/data/tmp/
UPLOAD_PATH=/data/tmp/
LOG_PATH=/data/log/
DEFAULT_ENV=android
```

---

## Running the bot

```bash
python script/main.py [account-number]
python script/main.py [account-number] --debug
python script/main.py [account-number] --proxy "host:port:user:pass"
```

No account number starts **interactive mode** (useful for testing commands).

---

## Account management

### Register a new companion device

```bash
# QR code scan
python script/regwithscan.py

# Link code (recommended)
python script/regwithlinkcode.py [account-number]
```

After registration you get an `[account-number]_[device-id]` account directory.

### Import / export (6-segment backup format)

```bash
# Import
python script/import6.py "[6-segment-string]" --env android

# Export
python script/export6.py [account-number]
```

Supported `--env` values: `android`, `smb_android`, `ios`, `smb_ios`

---

## Commands

### Shell mode

```bash
python script/main.py [account-number] [command] [params...]
```

### Interactive mode

```
[command] [params...]
```

### Reference

#### Account
| Command | Description |
|---|---|
| `account.init` | First login / initialize account |
| `account.info` | Registration info |
| `account.getname` / `account.setname` | Get / set push name |
| `account.getavatar` / `account.setavatar` | Get / set avatar |
| `account.getemail` / `account.setemail` | Get / set email |
| `account.verifyemail` / `account.verifyemailcode` | Email verification |
| `account.set2fa` | Configure 2FA |

#### Contacts
| Command | Description |
|---|---|
| `contact.list` | List contacts |
| `contact.sync` | Sync contacts |
| `contact.getprofile` | Get profile |
| `contact.getavatar` | Get avatar |
| `contact.getdevices` | List devices |
| `contact.trust` | Trust identity key |

#### Groups
| Command | Description |
|---|---|
| `group.create` | Create group |
| `group.list` | List groups |
| `group.info` | Get group info |
| `group.join` | Join via invite code |
| `group.leave` | Leave group |
| `group.add` / `group.remove` | Add / remove members |
| `group.promote` / `group.demote` | Change admin role |
| `group.approve` | Approve pending members |
| `group.seticon` | Set group icon |
| `group.getinvite` | Get invite code |

#### Messaging
| Command | Description |
|---|---|
| `msg.send` | Send text |
| `msg.sendmedia` | Send media |
| `msg.sendad` | Send ad message |
| `msg.quotedreply` | Send quoted reply |
| `msg.edit` | Edit sent message |
| `msg.revoke` | Revoke message |

#### Multi-device
| Command | Description |
|---|---|
| `md.devices` | List linked devices |
| `md.link` | Link device via QR |
| `md.inputcode` | Link via pair code |
| `md.remove` | Unlink device(s) |

#### Misc / Business
| Command | Description |
|---|---|
| `misc.checkactive` | Check if numbers are active |
| `misc.bizfeatures` | Business account features |
| `misc.bizintegrity` | Business account integrity |
| `misc.prekeycount` | Prekey count on server |
| `misc.reachouttimelock` | Reachout timelock |
| `msgshortlink.get/decode/setmsg/reset` | Short link operations |
| `newsletter.join/leave/metadata/…` | Newsletter operations |

---

## Web dashboard

A web dashboard for monitoring messages, managing accounts, and configuring AI strategies.

**Stack:** Flask 3 + Flask-SocketIO (backend) · React 18 + Vite + Ant Design v5 (frontend)

### Directory layout

```
app/dashboard/
├── api/          # Flask REST API blueprints
├── strategy/     # AI strategy engine
├── utils/        # bot_status, avatar_queue, db helpers
├── bridge.py     # Integration point — called by bot core
├── config.py     # Dashboard-specific config
└── frontend/     # React + Vite frontend
    ├── src/
    ├── package.json
    └── vite.config.ts
```

### Starting

```bash
# Backend + frontend together (recommended for development)
python script/start_dashboard.py

# Backend only (port 5000)
python script/dashboard_server.py

# Frontend dev server only (port 5173, proxies /api → 5000)
cd app/dashboard/frontend
npm install   # first time only
npm run dev
```

The dashboard is gated by the `DASHBOARD_MODE` environment variable.  
`script/dashboard_server.py` sets it automatically. Running `script/main.py` alone never writes to the dashboard DB.

### Features

- **Contact list** — avatars, unread badges, last-message preview, real-time updates
- **Chat history** — per-contact conversation view with AI "thoughts" panel
- **Bot management** — account list, one-click start, live startup log stream, import/export 6-segment backups, failure marking and batch delete
- **Strategy management** — global and per-user AI reply strategies, history table, one-click toggle/rollback
- **Real-time push** — WebSocket (Socket.IO) + SSE; no polling

### Bot management details

| Action | How |
|---|---|
| Start a bot | Click **Start** on an account row; logs stream in a modal |
| Import accounts | Paste 6-segment strings; `script/import6.py` runs per line |
| Export accounts | Select rows → Export; `script/export6.py` output shown in a modal |
| Mark / unmark failed | Manual toggle, or auto-set on permanent ban (403/401) |
| Batch delete failed | One click removes all failure-marked account directories |

### Selected API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/bot/accounts` | List accounts with live status |
| `POST` | `/api/bot/import` | Import 6-segment strings |
| `POST` | `/api/bot/export` | Export 6-segment strings |
| `DELETE` | `/api/bot/accounts/<phone>` | Delete account directory |
| `PATCH` | `/api/bot/accounts/<phone>/mark-failed` | Toggle failure mark |
| `DELETE` | `/api/bot/accounts` | Batch-delete all failed accounts |
| `PATCH` | `/api/strategy/<id>/toggle` | Toggle strategy active state |
| `DELETE` | `/api/strategy/<id>` | Delete strategy row |

Full spec: `docs/openapi.yaml`

---

## Docker

```bash
# Copy and configure environment
cp .env.example .env

# Build and start (backend + nginx frontend)
docker compose up --build -d
```

Services:
- `backend` → http://localhost:5000
- `frontend` (Nginx) → http://localhost:80

---

## Project structure

```
zowsup-cli/
├── app/
│   ├── ai_module/          # AI service, strategy, satisfaction plugin
│   ├── dashboard/
│   │   ├── api/            # Flask blueprints
│   │   ├── strategy/       # Strategy engine
│   │   ├── utils/          # DB, avatar queue, bot status helpers
│   │   ├── bridge.py       # Bot ↔ dashboard integration facade
│   │   └── frontend/       # React 18 + Vite dashboard UI
│   ├── zowbot.py           # Bot engine
│   └── zowbot_cmd/         # Command handler implementations
├── core/                   # Protocol stack (async)
├── consonance/             # Noise protocol handshake
├── axolotl/                # Signal Protocol encryption
├── script/
│   ├── main.py             # Run the bot
│   ├── dashboard_server.py # Run the dashboard backend
│   ├── start_dashboard.py  # Run backend + frontend together
│   ├── regwithscan.py      # Register via QR scan
│   ├── regwithlinkcode.py  # Register via link code
│   ├── import6.py          # Import 6-segment account backup
│   └── export6.py          # Export 6-segment account backup
├── conf/                   # config.conf, constants, logging
├── proto/                  # Protobuf definitions
└── docs/                   # DEPLOY.md, OPERATIONS.md, openapi.yaml
```

---

## Support

- Telegram: [Zowsup Community](https://t.me/+au1dTQz7jyU0YjU5)

## License

See [LICENSE](./LICENSE).

