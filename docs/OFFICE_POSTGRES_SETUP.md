# Office PostgreSQL Setup (Windows)

Aurum talks to PostgreSQL directly via `psycopg`. **pgAdmin is only a GUI** for
creating databases and running SQL — the actual **PostgreSQL Windows service**
must be running for `/health` and live validation to succeed.

## 1. Confirm PostgreSQL is running

In PowerShell:

```powershell
Get-Service *postgres*
```

Look for a service such as `postgresql-x64-16` (version may differ).

Start it if stopped:

```powershell
Start-Service postgresql-x64-16
```

Replace the service name with the one from `Get-Service`.

## 2. Create the Aurum database (pgAdmin or psql)

In pgAdmin (or `psql`):

1. Connect to your local server.
2. Create database `aurum` (or match `DB_NAME` in `.env`).
3. Ensure the user in `.env` can connect (often `postgres` on office laptops).

## 3. Configure environment

From the repo root:

```powershell
copy .env.office.example .env
```

Edit `.env` — set `DB_PASSWORD` to your local postgres password.

**Canonical office values (use these exactly):**

| Variable | Canonical value |
|----------|-----------------|
| `DB_PORT` | `5433` |
| `DB_NAME` | `aurum` |
| `DB_USER` | `postgres` |

These match `src/db_config.py` defaults. Set `DB_PORT` to the **one** port your
PostgreSQL service actually listens on. If your native Windows install uses
`5432`, change this single line to `5432` — do not run with an ambiguous or
guessed port (that mismatch is the usual cause of `database: unreachable`).

Supported variables:

| Variable | Purpose |
|----------|---------|
| `DB_HOST` | Postgres host (usually `localhost`) |
| `DB_PORT` | Postgres port |
| `DB_NAME` | Database name |
| `DB_USER` | Database user |
| `DB_PASSWORD` | Database password (**never commit**) |
| `DB_CONNECT_TIMEOUT` | Seconds before health probe fails fast (default `3`) |

Legacy `AURUM_POSTGRES_*` names still work; `DB_*` takes precedence.

## 4. Start the API

```powershell
uvicorn api.main:app --reload --port 8000
```

## 5. Verify health

```powershell
curl http://127.0.0.1:8000/health
```

**Healthy example (HTTP 200):**

```json
{
  "status": "ok",
  "database": "ok",
  "database_target": {
    "host": "localhost",
    "port": 5433,
    "database": "aurum"
  }
}
```

**Degraded example (HTTP 503):**

```json
{
  "status": "degraded",
  "database": "unreachable",
  "database_target": {
    "host": "localhost",
    "port": 5433,
    "database": "aurum"
  }
}
```

No password or full connection string appears in the response.

## 6. React UI mode

When `/health` reports `database: unreachable`, the React app uses **Verified
Snapshot** mode — it does **not** show "Live API" or enable POST `/runs`, even
if `GET /reports/latest` returns 200 from an on-disk snapshot.

Live validation requires both a reachable API **and** `database: ok`.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `/health` hangs | Lower `DB_CONNECT_TIMEOUT`; confirm wrong host/port |
| `database: unreachable` | Service stopped, wrong port, or DB does not exist |
| UI shows Live but run fails | Stale UI — refresh; confirm `/health` not just `/reports/latest` |
| pgAdmin connects but API does not | pgAdmin may use a different port than `.env` |
