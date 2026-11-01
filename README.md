# Tracker Finance 2.0

The primary application is the Python Telegram bot in `main.py` with its Telegram Mini App in `webapp/`. In deployment it uses Supabase PostgreSQL; local development can fall back to SQLite. The currency is RUB.

## Run locally

1. Copy `.env.example` to `.env` and set `BOT_TOKEN`. To use Supabase locally, also set `DATABASE_URL`.
2. Install dependencies with `py -m pip install -r requirements.txt`.
3. Start the bot with `py main.py`.

The web server listens on `PORT` (default `8080`). The Mini App is served at `/app`. Telegram requires a public HTTPS address; set `PUBLIC_URL` to that address to show its launch button. For local browser development, `APP_DEV=1` enables the development-only local-user fallback.

## Deploy to Railway

Render runs the primary Python bot with `python main.py`. Set at least:

- `BOT_TOKEN`
- `ALLOWED_USERS` for a private deployment
- `DATABASE_URL` from Supabase Dashboard → **Connect** → **Session pooler**
- `DB_SCHEMA=tracker_finance` (this is the default)
- `PUBLIC_URL` to the generated HTTPS domain
- `TIMEZONE`

The app creates its tables in the private `tracker_finance` PostgreSQL schema on startup; existing tables in Supabase's `public` schema are left untouched. No Render disk is needed when `DATABASE_URL` is configured. Without it, the app uses local SQLite, which is not persistent across Render instance replacement. Existing SQLite records are not automatically copied to Supabase. `ANTHROPIC_API_KEY` is optional and enables Claude parsing for free-text financial messages.

## Migrate existing SQLite data

If the local `finance.db` already contains records, set the Supabase Session Pooler URI as `DATABASE_URL` in the local, ignored `.env` file. From the project root, first review the read-only counts:

```bash
py scripts/migrate_sqlite_to_supabase.py
```

If the counts are expected, explicitly apply the copy:

```bash
py scripts/migrate_sqlite_to_supabase.py --apply
```

The migration preserves IDs and skips conflicting rows, so it can be rerun safely. Never commit `.env` or paste `DATABASE_URL` into chat.

## Project layout

- `main.py`, `requirements.txt`, `Procfile`, `railway.json`: active Python application and deployment configuration.
- `webapp/`: active Mini App frontend.
- `tests/`: API integration tests; run with `py -m unittest discover -s tests -v`.
- `src/`, `package.json`, and parts of `scripts/`: earlier JavaScript/Supabase prototype; they are not used by the Render start command.
- `supabase/schema.sql`: SQL reference for the active PostgreSQL schema; the Python app also creates it automatically.
- `files/`: legacy copies and the Russian setup guide; use the root files for the active deployment.

Never commit `.env`, database files, bot tokens, or service-role keys. Use `.env.example` only as a template.
