# Tracker Finance 2.0

The primary application is the Python Telegram bot in `main.py` with its Telegram Mini App in `webapp/`. It uses SQLite for transactions, budgets, goals, settings, and learned categories. The currency is RUB.

## Run locally

1. Copy `.env.example` to `.env` and set `BOT_TOKEN`.
2. Install dependencies with `py -m pip install -r requirements.txt`.
3. Start the bot with `py main.py`.

The web server listens on `PORT` (default `8080`). The Mini App is served at `/app`. Telegram requires a public HTTPS address; set `PUBLIC_URL` to that address to show its launch button. For local browser development, `APP_DEV=1` enables the development-only local-user fallback.

## Deploy to Railway

`railway.json` and `Procfile` both start the primary Python bot. Set at least:

- `BOT_TOKEN`
- `ALLOWED_USERS` for a private deployment
- `DB_PATH=/data/finance.db`
- `PUBLIC_URL` to the generated HTTPS domain
- `TIMEZONE`

Attach a persistent Railway Volume at `/data`; otherwise the SQLite database may be lost when the service is replaced. `ANTHROPIC_API_KEY` is optional and enables Claude parsing for free-text financial messages.

## Project layout

- `main.py`, `requirements.txt`, `Procfile`, `railway.json`: active Python application and deployment configuration.
- `webapp/`: active Mini App frontend.
- `tests/`: API integration tests; run with `py -m unittest discover -s tests -v`.
- `src/`, `package.json`, `supabase/`, and `scripts/`: earlier JavaScript/Supabase prototype and setup utilities; they are not used by the Railway start command.
- `files/`: legacy copies and the Russian setup guide; use the root files for the active deployment.

Never commit `.env`, database files, bot tokens, or service-role keys. Use `.env.example` only as a template.
