# SNOW ARC

Helpdesk attachment archiver for **ServiceNow** and **Freshdesk**. Connects to your helpdesk platform, retrieves ticket/incident attachments older than a configurable age, and archives them to either **Amazon S3** or a **local folder** — freeing up space in the source platform while keeping a searchable, browsable record.

> Contributed by [rithwickbathini](https://github.com/rithwickbathini).

## Features

- **Multi-platform**: ServiceNow (incidents) and Freshdesk (tickets), each with its own settings and dashboard UI.
- **Two storage backends**: Amazon S3 (with per-connection credentials) or a local filesystem path.
- **Web dashboard**: browse, search, and download/delete archived attachments per platform (`index.html`, `servicenow*.html`, `freshdesk*.html`).
- **Encrypted credential storage**: platform and storage secrets are encrypted at rest (`backend/crypto.py`).
- **Optional AI assistant**: ask questions about archived attachments via Claude (Anthropic API), if configured.
- **User accounts**: simple session-based login (`backend/auth.py`).

## Tech stack

- Python 3.14, stdlib `http.server` (no framework) for the backend/API
- SQLite for attachment metadata (`backend/db.py`)
- `boto3` for S3, `cryptography` (Fernet) for secret encryption
- Plain HTML/JS + Tailwind (via CDN) for the frontend, no build step

## Setup

Requires [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/cloudeontech-hue/SNOW_ARC_NEW.git
cd SNOW_ARC_NEW
uv sync
```

### Environment variables

Create a `.env` file in the project root (never commit this — it's gitignored):

```bash
# Required: key used to encrypt/decrypt stored credentials
SECRET_KEY=change-me-to-a-long-random-string

# Optional: enables the AI assistant chat feature
ANTHROPIC_API_KEY=

# Optional: fallback AWS S3 settings (can also be set per-connection in the UI)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=
AWS_S3_BUCKET=

# Server port (default 7002)
PORT=7002
```

## Running

```bash
uv run run_dashboard.py
```

Then open `http://localhost:<PORT>/` in your browser.

| Route | Description |
|---|---|
| `/` | Landing page |
| `/servicenow` | ServiceNow connection page |
| `/servicenow/settings` | ServiceNow credentials & storage settings |
| `/servicenow/dashboard` | Browse archived ServiceNow attachments |
| `/freshdesk` | Freshdesk connection page |
| `/freshdesk/settings` | Freshdesk credentials & storage settings |
| `/freshdesk/dashboard` | Browse archived Freshdesk attachments |

## Project structure

```
backend/
  auth.py            # session-based login/logout
  crypto.py           # Fernet encryption for stored secrets
  db.py                # SQLite attachment metadata store
  s3_client.py         # S3 client, upload, presigned URLs
  storage.py            # local filesystem storage
  store.py               # JSON config load/save helpers
  sync_engine.py          # retrieval/archival orchestration
  integrations/
    base.py               # shared types, platform registry
    servicenow.py          # ServiceNow API integration
    freshdesk.py           # Freshdesk API integration
claude_client.py       # Anthropic Claude client for the AI assistant
run_dashboard.py        # HTTP server entrypoint + all API routes
*.html                    # frontend pages (no build step)
test_connection/          # standalone connection-test scripts
```

## Testing a platform connection

```bash
uv run test_connection/test_api.py
uv run test_connection/test_sdk.py
```
