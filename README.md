# PolicyDiff

**Automated Terms of Service & Privacy Policy Change Monitor with Plain-Language Alerts**

PolicyDiff monitors privacy policies and terms of service pages from companies you care about. When changes are detected, it runs structured diffs and uses AI to explain what changed in plain language — telling you things like *"This company now claims the right to use your data for AI training"* or *"Your bank removed the clause prohibiting third-party data sharing."*

![Dashboard](https://img.shields.io/badge/Status-Ready-green) ![Python](https://img.shields.io/badge/Python-3.12-blue) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

- **URL Monitoring** — Add any privacy policy or ToS URL and PolicyDiff will track it
- **Automated Scraping** — Periodic background checks with configurable intervals (6h to weekly)
- **Smart Diffing** — Clause-level change detection (added, removed, modified sections)
- **AI Analysis** — GPT-4o-mini powered plain-language summaries of what changed and why it matters
- **Severity Ratings** — Every change is rated: `informational`, `concerning`, or `action-needed`
- **Email Alerts** — Beautiful HTML email notifications with severity-based urgency
- **Side-by-Side Diffs** — Full HTML diff view showing exactly what words changed
- **Timeline View** — See how each company's privacy posture evolved over time
- **Seed Snapshots** — Bootstrap history from the Wayback Machine or other sources
- **Check Now Button** — Manually trigger an immediate check for any policy
- **Modern Dashboard** — Dark-themed, responsive SPA built with TailwindCSS

---

## Quick Start

### Option 1: Run Locally (Recommended for Development)

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
# Edit .env with your OpenAI API key (optional but recommended)

# 5. Run the server
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

### Option 2: Docker

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your API keys

# 2. Build and run
docker compose up --build

# Or run detached
docker compose up -d --build
```

Open **http://localhost:8000** in your browser.

---

## Configuration

All configuration is done via environment variables (`.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key for AI analysis (optional — falls back to basic analysis) |
| `DATABASE_URL` | `sqlite:///./data/policydiff.db` | Database connection string |
| `CHECK_INTERVAL_HOURS` | `24` | Default interval between automatic checks |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server for email alerts |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username (email) |
| `SMTP_PASSWORD` | — | SMTP password (use app passwords for Gmail) |
| `ALERT_FROM_EMAIL` | — | Sender email address |
| `ALERT_TO_EMAIL` | — | Recipient email address |

---

## Usage Guide

### 1. Add a Policy

Click **"Add Policy"** and enter:
- **Name**: Human-readable name (e.g., "Google Privacy Policy")
- **Company**: Company name
- **URL**: Direct link to the policy page
- **Type**: Privacy Policy or Terms of Service
- **Check interval**: How often to check for changes

### 2. Run Initial Check

Click the refresh icon on a policy card or use **"Check Now"** in the detail view. This captures the first snapshot.

### 3. Seed Historical Data (Optional)

In the policy detail view, click **"Seed Snapshot"** to paste a previous version of the policy. This is useful for:
- Bootstrapping from the [Wayback Machine](https://web.archive.org)
- Establishing a baseline before monitoring

### 4. Monitor Changes

PolicyDiff automatically checks on schedule. When changes are detected:
- The dashboard shows the change with a severity badge
- An email alert is sent (if configured)
- Full analysis is available in the diff detail view

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/policies` | List all policies |
| `POST` | `/api/policies` | Add a new policy |
| `GET` | `/api/policies/{id}` | Get policy details |
| `PUT` | `/api/policies/{id}` | Update a policy |
| `DELETE` | `/api/policies/{id}` | Delete a policy |
| `POST` | `/api/policies/{id}/check` | Check a policy now |
| `GET` | `/api/policies/{id}/snapshots` | List snapshots |
| `POST` | `/api/policies/{id}/snapshots/seed` | Seed a snapshot |
| `GET` | `/api/policies/{id}/diffs` | List diffs for a policy |
| `GET` | `/api/policies/{id}/timeline` | Get policy timeline |
| `GET` | `/api/diffs/{id}` | Get full diff details |
| `GET` | `/api/dashboard/stats` | Dashboard statistics |
| `POST` | `/api/check-all` | Check all active policies |
| `GET` | `/health` | Health check |

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Backend | **FastAPI** (Python) | Async-native, fast to develop, great for scraping/LLM workloads |
| Database | **SQLite** + SQLAlchemy | Zero config, portable, perfect for single-instance deployment |
| Frontend | **TailwindCSS** + **Alpine.js** | No build step, CDN-delivered, reactive without framework overhead |
| Scraping | **httpx** + **BeautifulSoup4** | Async HTTP + robust HTML parsing |
| Diffing | **difflib** (stdlib) | Battle-tested, built-in, clause-level parsing |
| AI Analysis | **OpenAI GPT-4o-mini** | Fast, cheap, excellent at structured summarization |
| Scheduling | **APScheduler** | In-process, no external broker needed |
| Email | **smtplib** (stdlib) | Zero-dependency SMTP |
| Deployment | **Docker** | Single container, reproducible |

---

## Project Structure

```
PolicyDiff/
├── app/
│   ├── main.py              # FastAPI app + lifespan
│   ├── config.py             # Environment configuration
│   ├── database.py           # SQLAlchemy + SQLite setup
│   ├── models.py             # ORM models (Policy, Snapshot, Diff)
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── routers/
│   │   ├── policies.py       # Policy CRUD
│   │   ├── snapshots.py      # Snapshot endpoints
│   │   ├── diffs.py          # Diff endpoints
│   │   └── dashboard.py      # Dashboard + check actions
│   ├── services/
│   │   ├── scraper.py        # Web scraping engine
│   │   ├── differ.py         # Clause-level diff computation
│   │   ├── analyzer.py       # LLM analysis (OpenAI)
│   │   ├── notifier.py       # Email notifications
│   │   ├── scheduler.py      # APScheduler setup
│   │   └── pipeline.py       # Core scrape→diff→analyze→notify pipeline
│   └── static/
│       ├── index.html         # SPA dashboard
│       ├── css/app.css        # Custom styles
│       └── js/app.js          # Alpine.js application
├── data/                      # SQLite database (auto-created)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Demo Tips

1. **Add 3-5 popular policies** (Google, OpenAI, Spotify, etc.)
2. **Run "Check All"** to capture initial snapshots
3. **Seed an old version** using the Wayback Machine to demonstrate change detection
4. **Click "Check Now"** to show real-time scraping + analysis
5. **Navigate the diff view** to show side-by-side comparisons and AI summaries

---

## License

MIT
