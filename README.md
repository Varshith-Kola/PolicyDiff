# PolicyDiff

**Automated Terms of Service & Privacy Policy Change Monitor with Plain-Language Alerts**

PolicyDiff monitors privacy policies and terms of service pages from companies you care about. When changes are detected, it runs structured diffs and uses AI to explain what changed in plain language — telling you things like *"This company now claims the right to use your data for AI training"* or *"Your bank removed the clause prohibiting third-party data sharing."*

![Dashboard](https://img.shields.io/badge/Status-Production--Ready-green) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **Google OAuth Sign-In** — Multi-user support with Google accounts; each user gets an isolated dashboard
- **Per-User Policy Isolation** — Each user's policies, snapshots, and diffs are completely independent
- **URL Monitoring** — Add any privacy policy or ToS URL and PolicyDiff will track it
- **Automated Scraping** — Periodic background checks with configurable per-policy intervals
- **Smart Diffing** — Clause-level change detection (added, removed, modified sections)
- **AI Analysis** — GPT-4o-mini powered plain-language summaries of what changed and why it matters
- **Severity Ratings** — Every change is rated: `informational`, `concerning`, or `action-needed`
- **Per-User Email Alerts** — Follow policies with the bell icon; get HTML email alerts when they change
- **Webhook Alerts** — Slack/Discord/generic webhook notifications
- **Email Preferences** — Control frequency (immediate/daily/weekly) and severity threshold per user
- **Side-by-Side Diffs** — Full HTML diff view showing exactly what words changed
- **Timeline View** — See how each company's privacy posture evolved over time
- **Wayback Machine Seeding** — Automatically bootstrap history from web archives
- **Export & Reporting** — Download change reports as CSV or JSON
- **GDPR Compliance** — Data export, account deletion, consent tracking, and unsubscribe
- **Modern Dashboard** — Dark-themed, responsive SPA with search and filtering
- **SSRF Protection** — All policy URLs validated against private/reserved IP ranges
- **XSS Prevention** — DOMPurify sanitization on all rendered HTML
- **Rate Limiting** — Sliding-window limiter on expensive operations
- **Test Suite** — 39 tests covering API, security, and diff computation

---

## Quick Start

### Prerequisites

- **Python 3.10+** (3.12 recommended)
- **pip** (Python package manager)
- **Git**

### Step 1: Clone the Repository

```bash
git clone https://github.com/Varshith-Kola/PolicyDiff.git
cd PolicyDiff
```

### Step 2: Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate   # macOS / Linux
# venv\Scripts\activate    # Windows
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment

```bash
cp .env.example .env
```

Open `.env` in your editor and set the required values:

```bash
# Required for AI-powered analysis (optional — app works without it)
OPENAI_API_KEY=sk-your-openai-key

# Google OAuth (optional — enables multi-user Google Sign-In)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback

# Email notifications (optional — enables email alerts)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
ALERT_FROM_EMAIL=your-email@gmail.com
ALERT_TO_EMAIL=admin@example.com

# API key auth (optional — single-user mode without Google OAuth)
API_KEY=your-secret-api-key
```

> **Google OAuth setup:** Create credentials at [Google Cloud Console](https://console.cloud.google.com/apis/credentials). Add `http://localhost:8000/api/auth/google/callback` as an authorized redirect URI.

> **Gmail app passwords:** If using Gmail for SMTP, generate an [App Password](https://myaccount.google.com/apppasswords) (requires 2FA enabled).

### Step 5: Run the Server

```bash
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

### Docker (Alternative)

```bash
cp .env.example .env
# Edit .env with your keys
docker compose up --build -d
```

---

## Authentication

PolicyDiff supports two authentication modes (can be used together):

### Google OAuth (Multi-User)

1. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`
2. Click **"Sign in with Google"** on the login screen
3. Each user gets their own isolated set of policies and data
4. Users can follow policies and receive personalized email alerts

### API Key (Single-User)

1. Set `API_KEY=your-secret-key` in `.env`
2. Enter the API key on the login screen
3. All policies are shared (no per-user isolation)

When neither is configured, authentication is disabled entirely (development mode).

---

## Email Notifications

Users receive email alerts when followed policies change. The notification flow:

| Event | Email Sent? |
|-------|------------|
| **Check Now** detects a change | Yes — to all followers |
| **Scheduled check** detects a change | Yes — to all followers |
| **Wayback seed** creates diffs | Yes — latest diff to followers |
| **Wayback seed** adds first snapshot | Yes — confirmation to followers |
| **First snapshot** captured | Yes — confirmation to followers |

To configure email preferences:
1. Click the **bell icon** on a policy card to follow it
2. Click your profile picture → **Email Preferences**
3. Set frequency (immediate/daily/weekly) and minimum severity threshold

---

## Running Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

All 39 tests should pass. Tests use an isolated in-memory database and disable authentication.

---

## Database Migrations

```bash
# Generate a migration after model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

---

## Configuration Reference

All configuration is done via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | *(empty)* | API key for single-user auth |
| `SECRET_KEY` | *(auto)* | Secret for signing bearer tokens |
| `GOOGLE_CLIENT_ID` | *(empty)* | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | *(empty)* | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/auth/google/callback` | OAuth redirect URI |
| `OPENAI_API_KEY` | — | OpenAI API key for AI analysis |
| `LLM_MAX_CONCURRENT` | `3` | Max concurrent LLM API calls |
| `DATABASE_URL` | `sqlite:///./data/policydiff.db` | Database URL (SQLite or PostgreSQL) |
| `CHECK_INTERVAL_HOURS` | `24` | Default check interval |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server for email alerts |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PASSWORD` | — | SMTP password (use app passwords for Gmail) |
| `ALERT_FROM_EMAIL` | — | Sender email address |
| `ALERT_TO_EMAIL` | — | Admin notification email |
| `WEBHOOK_URL` | — | Slack/Discord/generic webhook URL |
| `RATE_LIMIT_REQUESTS` | `60` | Max requests per rate-limit window |
| `RATE_LIMIT_WINDOW` | `60` | Rate-limit window in seconds |
| `CORS_ORIGINS` | *(empty)* | Comma-separated allowed CORS origins |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

---

## API Reference

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Exchange API key for bearer token |
| `GET` | `/api/auth/status` | Check auth status and available methods |
| `GET` | `/api/auth/google/login` | Start Google OAuth flow |
| `GET` | `/api/auth/google/callback` | Google OAuth callback |
| `GET` | `/api/auth/me` | Get current user profile |

### Policies (per-user isolated)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/policies` | List current user's policies |
| `POST` | `/api/policies` | Add a new policy |
| `GET` | `/api/policies/{id}` | Get policy details |
| `PUT` | `/api/policies/{id}` | Update a policy |
| `DELETE` | `/api/policies/{id}` | Delete a policy |
| `POST` | `/api/policies/{id}/check` | Check a policy now |
| `POST` | `/api/policies/{id}/seed-wayback` | Seed from Wayback Machine |

### Snapshots & Diffs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/policies/{id}/snapshots` | List snapshots |
| `GET` | `/api/policies/{id}/snapshots/{sid}` | Get snapshot content |
| `GET` | `/api/policies/{id}/diffs` | List diffs (filter by severity) |
| `GET` | `/api/policies/{id}/timeline` | Get policy timeline |
| `GET` | `/api/diffs/{id}` | Get full diff details |
| `GET` | `/api/diffs` | List all diffs (search/filter) |
| `GET` | `/api/export/diffs` | Export diffs as CSV or JSON |

### User & Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/me/follow` | Follow/unfollow a policy |
| `GET` | `/api/auth/me/email-preferences` | Get email preferences |
| `PUT` | `/api/auth/me/email-preferences` | Update email preferences |
| `POST` | `/api/auth/me/unsubscribe` | Unsubscribe from all emails |
| `GET` | `/api/auth/me/export` | GDPR data export |
| `DELETE` | `/api/auth/me` | Delete account (GDPR) |

### Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/dashboard/stats` | Dashboard statistics |
| `POST` | `/api/check-all` | Check all active policies |
| `POST` | `/api/test-notification` | Send a test notification |
| `GET` | `/health` | Health check (public) |

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Backend | **FastAPI** (Python 3.12) | Async-native, auto docs, dependency injection |
| Auth | **Google OAuth 2.0** + **JWT** | Secure multi-user with per-user isolation |
| Database | **SQLAlchemy** + SQLite/PostgreSQL | ORM with migration support via Alembic |
| Frontend | **TailwindCSS** + **Alpine.js** | No build step, reactive SPA |
| Security | **DOMPurify** + SSRF validation | XSS prevention + SSRF-safe URL checks |
| Scraping | **httpx** + **Playwright** + **BeautifulSoup4** | JS rendering fallback + robust parsing |
| Diffing | **difflib** (stdlib) | Clause-level fuzzy matching |
| AI Analysis | **OpenAI GPT-4o-mini** | Fast, structured summarization |
| Scheduling | **APScheduler** | In-process, per-policy intervals |
| Notifications | **SMTP** + **Webhooks** | Per-user email + Slack/Discord |
| Testing | **pytest** (39 tests) | API, security, and unit tests |
| Deployment | **Docker** | Non-root container with healthcheck |

---

## Project Structure

```
PolicyDiff/
├── app/
│   ├── main.py              # FastAPI app, lifespan, middleware
│   ├── config.py             # Centralised settings (pydantic-settings)
│   ├── database.py           # SQLAlchemy engine, session management
│   ├── models.py             # ORM models (User, Policy, Snapshot, Diff, etc.)
│   ├── schemas.py            # Pydantic schemas with validation
│   ├── middleware/
│   │   ├── auth.py           # Auth (API key + Google OAuth + bearer token)
│   │   ├── rate_limit.py     # In-memory sliding-window rate limiter
│   │   └── request_logging.py # Request/response logging
│   ├── utils/
│   │   ├── datetime_helpers.py # UTC-aware datetime utilities
│   │   ├── url_validator.py   # SSRF-safe URL validation
│   │   └── security.py       # API key hashing, token generation
│   ├── routers/
│   │   ├── auth.py           # Auth status + API key login
│   │   ├── users.py          # Google OAuth + user profile + GDPR
│   │   ├── policies.py       # Policy CRUD (per-user isolated)
│   │   ├── snapshots.py      # Snapshot endpoints
│   │   ├── diffs.py          # Diff endpoints + export
│   │   └── dashboard.py      # Dashboard + check actions
│   ├── services/
│   │   ├── scraper.py        # Web scraping with HTML preprocessing
│   │   ├── differ.py         # Clause-level diff computation
│   │   ├── analyzer.py       # LLM analysis with burst control
│   │   ├── notifier.py       # Per-user email + webhook notifications
│   │   ├── scheduler.py      # APScheduler with per-policy intervals
│   │   ├── pipeline.py       # Scrape→diff→analyze→notify (session-safe)
│   │   └── wayback.py        # Wayback Machine auto-seeding + notify
│   └── static/
│       ├── index.html         # SPA with Google Sign-In + user dashboard
│       ├── css/app.css        # Custom styles
│       └── js/
│           ├── app.js         # Alpine.js app (auth, routing, search)
│           └── markdown.js    # Markdown renderer (marked.js + DOMPurify)
├── alembic/                   # Database migrations
├── tests/                     # pytest test suite (39 tests)
├── data/                      # SQLite database (auto-created, gitignored)
├── requirements.txt
├── pyproject.toml             # pytest + ruff config
├── Dockerfile                 # Non-root, healthcheck enabled
├── docker-compose.yml
├── .env.example               # Template — copy to .env
└── README.md
```

---

## Demo Tips

1. **Sign in with Google** to create your account
2. **Add 3-5 popular policies** (Google, OpenAI, Spotify, state.gov, etc.)
3. **Click the bell icon** on policy cards to follow them for email alerts
4. **Run "Check Now"** to capture snapshots and trigger AI analysis
5. **Use Wayback seeding** to auto-populate historical changes
6. **Open Email Preferences** to configure notification frequency and severity
7. **Navigate the diff view** for side-by-side comparisons and AI summaries
8. **Export diffs** as CSV for compliance documentation
9. **Try the mobile view** — resize browser or use devtools

---

## License

MIT
