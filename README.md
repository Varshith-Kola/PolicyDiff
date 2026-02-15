# PolicyDiff v2.0

**Automated Terms of Service & Privacy Policy Change Monitor with Plain-Language Alerts**

PolicyDiff monitors privacy policies and terms of service pages from companies you care about. When changes are detected, it runs structured diffs and uses AI to explain what changed in plain language — telling you things like *"This company now claims the right to use your data for AI training"* or *"Your bank removed the clause prohibiting third-party data sharing."*

![Dashboard](https://img.shields.io/badge/Status-Production--Ready-green) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## What's New in v2.0

- **Authentication** — API key + bearer token auth; disabled by default for backward compatibility
- **SSRF Protection** — All policy URLs are validated against private/reserved IP ranges
- **XSS Prevention** — DOMPurify sanitization on all rendered HTML
- **Rate Limiting** — In-memory sliding-window limiter on expensive operations
- **Concurrent DB Safety** — Each pipeline check gets its own database session
- **Per-Policy Scheduling** — Policies can have individual check intervals
- **Idempotency Guards** — Duplicate snapshots and diffs are prevented
- **LLM Burst Control** — Global semaphore limits concurrent OpenAI API calls
- **N+1 Query Elimination** — Aggregated queries for policy list endpoints
- **Database Migrations** — Alembic integration for schema evolution
- **CSV/JSON Export** — Export diff reports for compliance
- **SPA Routing** — Hash-based browser routing with back/forward support
- **Mobile Responsive** — Collapsible sidebar with hamburger menu
- **Search & Filter** — Filter policies by name/company, diffs by severity
- **Test Suite** — pytest with API, security, and diff computation tests
- **Request Logging** — Structured access logs with latency tracking
- **PostgreSQL Ready** — Database layer supports Postgres for multi-instance deployments

---

## Features

- **URL Monitoring** — Add any privacy policy or ToS URL and PolicyDiff will track it
- **Automated Scraping** — Periodic background checks with configurable per-policy intervals
- **Smart Diffing** — Clause-level change detection (added, removed, modified sections)
- **AI Analysis** — GPT-4o-mini powered plain-language summaries of what changed and why it matters
- **Severity Ratings** — Every change is rated: `informational`, `concerning`, or `action-needed`
- **Email & Webhook Alerts** — HTML email + Slack/Discord/generic webhook notifications
- **Side-by-Side Diffs** — Full HTML diff view showing exactly what words changed
- **Timeline View** — See how each company's privacy posture evolved over time
- **Wayback Machine Seeding** — Automatically bootstrap history from web archives
- **Export & Reporting** — Download change reports as CSV or JSON
- **Modern Dashboard** — Dark-themed, responsive SPA with search and filtering

---

## Quick Start

### Option 1: Run Locally

```bash
# 1. Clone and enter the project
cd PolicyDiff

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY for AI analysis (optional)
# Set API_KEY for authentication (recommended for production)

# 5. Run the server
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

### Option 2: Docker

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your keys

# 2. Build and run
docker compose up --build -d
```

Open **http://localhost:8000** in your browser.

### Running Tests

```bash
pip install -r requirements.txt
pytest -v
```

### Database Migrations

```bash
# Generate a migration after model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

---

## Configuration

All configuration is done via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | *(empty)* | API key for authentication; auth disabled when empty |
| `SECRET_KEY` | *(auto)* | Secret for signing bearer tokens |
| `OPENAI_API_KEY` | — | OpenAI API key for AI analysis (optional) |
| `LLM_MAX_CONCURRENT` | `3` | Max concurrent LLM API calls |
| `DATABASE_URL` | `sqlite:///./data/policydiff.db` | Database URL (SQLite or PostgreSQL) |
| `CHECK_INTERVAL_HOURS` | `24` | Default check interval |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server for email alerts |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password |
| `ALERT_FROM_EMAIL` | — | Sender email |
| `ALERT_TO_EMAIL` | — | Recipient email |
| `WEBHOOK_URL` | — | Slack/Discord/generic webhook URL |
| `RATE_LIMIT_REQUESTS` | `60` | Max requests per rate-limit window |
| `RATE_LIMIT_WINDOW` | `60` | Rate-limit window in seconds |
| `CORS_ORIGINS` | *(empty)* | Comma-separated allowed CORS origins |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

---

## Authentication

Authentication is **disabled by default** for backward compatibility.

To enable:
1. Set `API_KEY=your-secret-key` in `.env`
2. The frontend shows a login screen where you enter the API key
3. All API requests require either:
   - `X-API-Key: your-key` header, or
   - `Authorization: Bearer <token>` (obtained from `/api/auth/login`)

Public endpoints (no auth required): `/`, `/health`, `/static/*`, `/api/auth/*`

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Exchange API key for bearer token |
| `GET` | `/api/auth/status` | Check if auth is enabled |
| `GET` | `/api/policies` | List all policies |
| `POST` | `/api/policies` | Add a new policy |
| `GET` | `/api/policies/{id}` | Get policy details |
| `PUT` | `/api/policies/{id}` | Update a policy |
| `DELETE` | `/api/policies/{id}` | Delete a policy |
| `POST` | `/api/policies/{id}/check` | Check a policy now |
| `POST` | `/api/policies/{id}/seed-wayback` | Seed from Wayback Machine |
| `GET` | `/api/policies/{id}/snapshots` | List snapshots |
| `POST` | `/api/policies/{id}/snapshots/seed` | Seed a snapshot manually |
| `GET` | `/api/policies/{id}/diffs` | List diffs (filterable by severity) |
| `GET` | `/api/policies/{id}/timeline` | Get policy timeline |
| `GET` | `/api/diffs/{id}` | Get full diff details |
| `GET` | `/api/diffs` | List all diffs (search/filter) |
| `GET` | `/api/export/diffs` | Export diffs as CSV or JSON |
| `GET` | `/api/dashboard/stats` | Dashboard statistics |
| `POST` | `/api/check-all` | Check all active policies |
| `GET` | `/health` | Health check (public) |

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Backend | **FastAPI** (Python 3.12) | Async-native, auto docs, dependency injection |
| Database | **SQLAlchemy** + SQLite/PostgreSQL | ORM with migration support via Alembic |
| Frontend | **TailwindCSS** + **Alpine.js** | No build step, reactive SPA |
| Security | **DOMPurify** + SSRF validation | XSS prevention + SSRF-safe URL checks |
| Scraping | **httpx** + **Playwright** + **BeautifulSoup4** | JS rendering fallback + robust parsing |
| Diffing | **difflib** (stdlib) | Clause-level fuzzy matching |
| AI Analysis | **OpenAI GPT-4o-mini** | Fast, structured summarization |
| Scheduling | **APScheduler** | In-process, per-policy intervals |
| Notifications | **SMTP** + **Webhooks** | Email + Slack/Discord |
| Testing | **pytest** | API, security, and unit tests |
| Deployment | **Docker** | Non-root container with healthcheck |

---

## Project Structure

```
PolicyDiff/
├── app/
│   ├── main.py              # FastAPI app, lifespan, middleware
│   ├── config.py             # Centralised settings (pydantic-settings)
│   ├── database.py           # SQLAlchemy engine, session management
│   ├── models.py             # ORM models (Policy, Snapshot, Diff)
│   ├── schemas.py            # Pydantic schemas with validation
│   ├── middleware/
│   │   ├── auth.py           # Authentication (API key + bearer token)
│   │   ├── rate_limit.py     # In-memory sliding-window rate limiter
│   │   └── request_logging.py # Request/response logging
│   ├── utils/
│   │   ├── datetime_helpers.py # UTC-aware datetime utilities
│   │   ├── url_validator.py   # SSRF-safe URL validation
│   │   └── security.py       # API key hashing, token generation
│   ├── routers/
│   │   ├── auth.py           # Authentication endpoints
│   │   ├── policies.py       # Policy CRUD (N+1 eliminated)
│   │   ├── snapshots.py      # Snapshot endpoints
│   │   ├── diffs.py          # Diff endpoints + export
│   │   └── dashboard.py      # Dashboard + check actions
│   ├── services/
│   │   ├── scraper.py        # Web scraping with HTML preprocessing
│   │   ├── differ.py         # Clause-level diff computation
│   │   ├── analyzer.py       # LLM analysis with burst control
│   │   ├── notifier.py       # Email + webhook notifications
│   │   ├── scheduler.py      # APScheduler with per-policy intervals
│   │   ├── pipeline.py       # Scrape→diff→analyze→notify (session-safe)
│   │   └── wayback.py        # Wayback Machine auto-seeding
│   └── static/
│       ├── index.html         # SPA with auth gate + mobile responsive
│       ├── css/app.css        # Custom styles
│       └── js/
│           ├── app.js         # Alpine.js app (auth, routing, search)
│           └── markdown.js    # Markdown renderer (marked.js + DOMPurify)
├── alembic/                   # Database migrations
├── tests/                     # pytest test suite
├── data/                      # SQLite database (auto-created)
├── requirements.txt
├── pyproject.toml             # pytest + ruff config
├── Dockerfile                 # Non-root, healthcheck enabled
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Demo Tips

1. **Add 3-5 popular policies** (Google, OpenAI, Spotify, etc.)
2. **Run "Check All"** to capture initial snapshots
3. **Use Wayback seeding** to auto-populate historical changes
4. **Click "Check Now"** to show real-time scraping + analysis
5. **Navigate the diff view** for side-by-side comparisons and AI summaries
6. **Export diffs** as CSV for compliance documentation
7. **Try the mobile view** — resize browser or use devtools

---

## License

MIT
