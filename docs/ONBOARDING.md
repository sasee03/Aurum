# Aurum Platform — New Team Member Onboarding Guide

Welcome to the Aurum team! This guide will help you get from zero to fully productive on your first day.

---

## Table of Contents

1. [What is Aurum?](#what-is-aurum)
2. [Tech Stack](#tech-stack)
3. [Prerequisites](#prerequisites)
4. [Initial Setup](#initial-setup)
5. [Running the Platform](#running-the-platform)
6. [Verifying Your Setup](#verifying-your-setup)
7. [Project Structure](#project-structure)
8. [Development Workflow](#development-workflow)
9. [Testing](#testing)
10. [Key Concepts](#key-concepts)
11. [Common Issues & Troubleshooting](#common-issues--troubleshooting)
12. [Essential Reading](#essential-reading)
13. [Team Roles & Communication](#team-roles--communication)

---

## What is Aurum?

Aurum is a **deterministic data-quality validation platform** that validates data across medallion ETL pipeline layers (Raw → Bronze → Silver → Gold).

### Core Purpose
- Identifies which layer failed first
- Explains root cause with SQL evidence
- Quantifies business impact
- Returns a deterministic verdict: **TRUSTED / WARNING / NOT TRUSTED**

### Key Principle
**There is NO LLM in the decision path.** The engine decides using:
- SQL-based checks and row counts
- Statistical reconciliation
- Deterministic rules

The LLM (Ollama) only explains *after* the verdict is computed—it never influences the decision.

---

## Tech Stack

### Backend
- **Python 3.11+**
- **FastAPI** — HTTP API layer
- **PostgreSQL** — Data being validated (via Docker)
- **SQLite** — App-state store (projects, runs, reports)
- **psycopg** — Direct PostgreSQL driver
- **Ollama** — Local LLM (explanation only, not decision)

### Frontend
- **React 19**
- **TypeScript 6**
- **Vite 8** — Build tool
- **TanStack Query** — Server state management
- **Tailwind CSS 4** — Styling
- **React Router 6** — Routing
- **Axios** — HTTP client

### Infrastructure
- **Docker** — PostgreSQL container
- **Windows** — Primary development OS
- **PowerShell/CMD** — Shell environment

---

## Prerequisites

### Required Software

1. **Python 3.11 or higher**
   ```powershell
   python --version
   ```

2. **Node.js 18+ and npm**
   ```powershell
   node --version
   npm --version
   ```

3. **Docker Desktop** (for PostgreSQL)
   - Download from https://www.docker.com/products/docker-desktop/
   - Must be running before starting the backend

4. **Git**
   ```powershell
   git --version
   ```

5. **Ollama** (for AI assistant features)
   - Download from https://ollama.ai/
   - Install the `llama3` model after installation

---

## Initial Setup

### 1. Clone the Repository

```powershell
# Clone to a NON-OneDrive location to avoid sync issues
cd C:\dev
git clone <repository-url> Aurum
cd Aurum
```

⚠️ **Important:** Do NOT clone into OneDrive, Dropbox, or any synced folder—this causes file lock conflicts.

### 2. Checkout Main Branch

```powershell
git checkout main
git pull origin main
```

### 3. Set Up Python Environment

```powershell
# Create virtual environment
python -m venv .venv

# Activate it (PowerShell)
.venv\Scripts\Activate.ps1

# Or activate it (CMD)
.venv\Scripts\activate.bat

# Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Database Connection

Each developer needs their own `.env` file (never committed to git):

```powershell
# Copy the example file
copy .env.office.example .env
```

Edit `.env` and set your local PostgreSQL password:

```env
DB_HOST=localhost
DB_PORT=5433
DB_NAME=aurum
DB_USER=postgres
DB_PASSWORD=your_actual_password_here
DB_CONNECT_TIMEOUT=3
```

**Canonical office values** (use these exactly):
- `DB_PORT=5433` (Docker default; if you use native PostgreSQL on 5432, change this)
- `DB_NAME=aurum`
- `DB_USER=postgres`

### 5. Start PostgreSQL (Docker)

```powershell
# Start Docker Desktop first, then:
docker compose up -d

# Verify it's running
docker ps
```

You should see a container named `aurum-postgres` running on port 5433.

### 6. Create the Aurum Database

The Docker container automatically creates the `aurum` database. Verify it:

```powershell
# Check health endpoint after starting backend (see next section)
curl http://127.0.0.1:8000/health
```

Should return:
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

### 7. Install Frontend Dependencies

```powershell
cd frontend
npm install
cd ..
```

---

## Running the Platform

### Backend (FastAPI)

```powershell
# From repo root, with .venv activated
.venv\Scripts\uvicorn api.main:app --reload --port 8000
```

The API will be available at: http://127.0.0.1:8000

### Frontend (React + Vite)

In a **separate terminal**:

```powershell
cd frontend
npm run dev
```

The frontend will be available at: http://localhost:5173

### Demo Data Generation (First Time Only)

The first time you run validation, generate the demo data:

```powershell
# From repo root, with .venv activated
python -m src.generate_data
```

This downloads the Olist dataset (~120MB) and creates demo CSVs.

---

## Verifying Your Setup

### 1. Check Backend Health

```powershell
curl http://127.0.0.1:8000/health
```

**Expected:** `"status": "ok"` and `"database": "ok"`

**If degraded:** Check that Docker Desktop is running and PostgreSQL container is up.

### 2. Run the Demo

```powershell
# From repo root, with .venv activated
python -m src.run_demo
```

**Expected output:**
```
Dataset:          Olist Brazilian E-Commerce
Bronze rows:      112,650 line items
Bronze Quality:   PASS
Silver Quality:   FAIL
Gold Quality:     IMPACTED
First Failed Layer: Bronze -> Silver
Estimated Loss:   BRL 13.45 M
Final Verdict:    NOT TRUSTED
```

### 3. Run Tests

```powershell
python -m pytest -q
```

**Expected:** 108 tests passed

### 4. Access the Frontend

Open http://localhost:5173 in your browser.

You should see:
- Landing page with project cards
- Ability to navigate to different sections
- "Live API" indicator in top-right if backend is running

---

## Project Structure

```
Aurum/
├── api/                          # FastAPI backend
│   ├── main.py                   # Main API endpoints
│   ├── aurum_assistant/          # AI assistant (explain-only)
│   ├── datasets_router.py        # Dataset management
│   └── projects_router.py        # Project management
│
├── src/                          # Core validation engine (DECIDES)
│   ├── bronze_validator.py       # Bronze layer checks (B1-B8)
│   ├── silver_validator.py       # Silver layer checks (S1-S10)
│   ├── gold_validator.py         # Gold layer checks (G1-G6)
│   ├── cross_layer_validator.py  # Cross-layer checks (X1-X4)
│   ├── verdict_engine.py         # Final verdict computation
│   ├── report_builder.py         # Assembles complete report
│   ├── data_loader.py            # PostgreSQL ETL
│   └── run_demo.py               # CLI entry point
│
├── frontend/                     # React UI (EXPLAINS)
│   ├── src/
│   │   ├── components/           # React components
│   │   ├── pages/                # Page components
│   │   ├── services/             # API clients
│   │   └── types/                # TypeScript types
│   └── public/                   # Static assets
│
├── data/                         # Data files (gitignored)
│   ├── olist/                    # Olist dataset CSVs
│   ├── app_state.sqlite          # SQLite app state
│   └── sample/                   # Sample data
│
├── docs/                         # Documentation
│   ├── ROADMAP.md                # Phase plan & rules
│   ├── CODEBASE_MAP.md           # File-by-file guide
│   ├── API_CONTRACT.md           # Report schema
│   ├── OFFICE_POSTGRES_SETUP.md  # Database setup
│   └── ONBOARDING.md             # This file
│
├── tests/                        # Test suite (108 tests)
├── .env                          # Local config (gitignored)
├── docker-compose.yml            # PostgreSQL container
└── requirements.txt              # Python dependencies
```

---

## Development Workflow

### Making Changes

1. **Always create a branch**
   ```powershell
   git checkout -b feature/your-feature-name
   ```

2. **Never commit to main directly**
   ```powershell
   # Always push to a feature branch
   git push -u origin feature/your-feature-name
   ```

3. **Stage specific files** (not `git add .`)
   ```powershell
   git add src/specific_file.py
   git commit -m "feat: add specific feature"
   ```

### Code Guidelines

**For Backend (Python):**
- Follow PEP 8 style
- Add docstrings to functions
- Run tests before committing
- Never hardcode values—compute from data

**For Frontend (TypeScript/React):**
- Use TypeScript strictly—no `any` types
- Keep components small and focused
- Use TanStack Query for server state
- Match the project's existing patterns

### Git Commit Messages

Use conventional commits:
- `feat:` — New feature
- `fix:` — Bug fix
- `docs:` — Documentation
- `test:` — Tests
- `refactor:` — Code restructuring
- `chore:` — Maintenance

Example:
```
feat: add Gold layer revenue reconciliation check

- Implements G1 check comparing Silver vs Gold revenue
- Adds tolerance for floating-point rounding
- Updates test suite with new check scenario
```

---

## Testing

### Run All Tests

```powershell
python -m pytest
```

### Run Specific Test File

```powershell
python -m pytest tests/test_verdict_engine.py
```

### Run with Coverage

```powershell
python -m pytest --cov=src --cov-report=html
```

### Frontend Testing

```powershell
cd frontend
npm run lint
```

---

## Key Concepts

### 1. Decide vs Explain Boundary

**DECIDES (Backend engine):**
- All validators (`bronze_validator.py`, `silver_validator.py`, etc.)
- `verdict_engine.py` — computes final verdict
- `report_builder.py` — assembles report

**EXPLAINS (UI and LLM):**
- `app/streamlit_app.py` — displays report
- `frontend/` — React UI
- `aurum_assistant/` — AI explanations

**Rule:** UI and LLM only read the report. They NEVER change the verdict or trust score.

### 2. Layer Status Flow

```
Raw → Bronze → Silver → Gold
```

Each layer has checks that return:
- `PASS` — Check satisfied
- `WARN` — Outside tolerance, not critical
- `FAIL` — Check violated
- `IMPACTED` — Correct logic, but upstream layer failed
- `SKIPPED` — Check couldn't run

**Layer Status = Worst Check Status**

**Final Verdict:**
- Any `FAIL` → `NOT TRUSTED`
- Any `WARN` or `IMPACTED` → `WARNING`
- All `PASS` → `TRUSTED`

### 3. Trust Score

Deterministic score based on check outcomes:

| Status | Weight |
|--------|--------|
| FAIL | -50 |
| IMPACTED | -10 |
| WARN | -5 |
| PASS | 0 |
| SKIPPED | 0 |
| **Base** | **100** |

Demo score: 100 + (-50 for failures) = **40 (NOT TRUSTED, HIGH severity)**

### 4. Report Contract (17 Keys)

Every report has exactly these top-level keys:
1. `run_id`
2. `timestamp`
3. `dataset_name`
4. `final_verdict`
5. `trust_score`
6. `severity`
7. `layers`
8. `root_cause`
9. `business_impact` (includes `estimated_loss`)
10. `suggested_action`
11. `checks`
12. `detection_layers`
13. `coverage`
14. `metadata`
15. `trust_narrative`
16. `layer_status`
17. `first_failed_layer`

**Never add, remove, or rename keys without team consensus.**

---

## Common Issues & Troubleshooting

### Backend won't start

**Symptom:** `uvicorn` fails or `/health` returns 503

**Solutions:**
1. Check Docker Desktop is running
   ```powershell
   docker ps
   ```

2. Verify PostgreSQL container is up
   ```powershell
   docker logs aurum-postgres
   ```

3. Check `.env` file exists and has correct values
   ```powershell
   type .env
   ```

4. Verify port 8000 isn't already in use
   ```powershell
   netstat -ano | findstr :8000
   ```

### Frontend won't connect to backend

**Symptom:** "Live API" indicator shows offline

**Solutions:**
1. Verify backend is running on port 8000
   ```powershell
   curl http://127.0.0.1:8000/health
   ```

2. Check CORS configuration in `api/main.py`
   - Should include `http://localhost:5173`

3. Clear browser cache and reload

### Database connection fails

**Symptom:** `/health` returns `"database": "unreachable"`

**Solutions:**
1. Confirm PostgreSQL container is running
   ```powershell
   docker ps
   ```

2. Check DB_PORT matches container port
   - Docker default: 5433
   - Native PostgreSQL: usually 5432

3. Verify credentials in `.env`

4. Test direct connection
   ```powershell
   docker exec -it aurum-postgres psql -U postgres -d aurum
   ```

### Tests fail

**Symptom:** `pytest` shows failures

**Solutions:**
1. Regenerate demo data
   ```powershell
   python -m src.generate_data
   ```

2. Ensure Docker PostgreSQL is running

3. Check for uncommitted changes that might affect tests

4. Run specific failing test with verbose output
   ```powershell
   python -m pytest tests/test_specific.py -v
   ```

### OneDrive sync issues

**Symptom:** File lock errors, weird git behavior

**Solution:**
1. Move repo to non-synced location
   ```powershell
   # Stop OneDrive sync for the folder, then:
   move D:\Learn\Aurum-1 C:\dev\Aurum
   cd C:\dev\Aurum
   ```

2. Update remote
   ```powershell
   git remote set-url origin <repository-url>
   ```

---

## Essential Reading

Start with these documents in order:

### Day 1
1. **This document** — `docs/ONBOARDING.md`
2. **README.md** — Quick start and overview
3. **docs/ROADMAP.md** — Project phases and non-negotiable rules

### Day 2
4. **docs/CODEBASE_MAP.md** — Where everything lives
5. **docs/API_CONTRACT.md** — Report structure
6. **docs/check_catalogue.md** — All validation checks

### As Needed
7. **docs/OFFICE_POSTGRES_SETUP.md** — Database troubleshooting
8. **docs/PERFORMANCE_STRESS_REPORT.md** — Performance testing
9. **docs/integration_reliability.md** — Integration testing

---

## Team Roles & Communication

### Development Team Structure

**Backend / Engine:**
- Owns validation engine (`src/`)
- Maintains report contract
- Ensures deterministic decisions

**Frontend / UI:**
- Builds React interface
- Displays report data (never computes it)
- Maintains UI/UX consistency

**Integration / QA:**
- Verifies contract conformance
- Runs daily tests
- Validates end-to-end flow

**AI Assistant:**
- LLM integration (Ollama)
- Explanation features only
- Never touches decision path

### Communication Channels

- **Daily standups** — Progress and blockers
- **GitHub** — All code changes via PRs
- **Documentation** — Update docs with code changes
- **Contract changes** — Must have team consensus

### When in Doubt

1. **Read the docs** — Check `docs/` first
2. **Run the tests** — `pytest` reveals contract violations
3. **Check `/health`** — Database issues show here first
4. **Ask the team** — Better to ask than break production

---

## Quick Reference Commands

### Everyday Commands

```powershell
# Activate Python environment
.venv\Scripts\Activate.ps1

# Start backend
uvicorn api.main:app --reload --port 8000

# Start frontend (separate terminal)
cd frontend && npm run dev

# Run tests
python -m pytest -q

# Check health
curl http://127.0.0.1:8000/health

# Run demo
python -m src.run_demo

# Docker PostgreSQL
docker compose up -d        # Start
docker compose down         # Stop
docker compose logs         # View logs
docker ps                   # Check status
```

### Git Workflow

```powershell
# Create feature branch
git checkout -b feature/my-feature

# Stage and commit
git add src/specific_file.py
git commit -m "feat: description"

# Push to remote
git push -u origin feature/my-feature

# Update from main
git checkout main
git pull origin main
git checkout feature/my-feature
git merge main
```

---

## Next Steps

1. ✅ Complete initial setup (above)
2. ✅ Run the demo successfully
3. ✅ Access the frontend
4. ✅ Run all tests
5. 📖 Read ROADMAP.md for project direction
6. 📖 Read CODEBASE_MAP.md to understand structure
7. 🎯 Pick your first task from the current phase
8. 💬 Introduce yourself to the team

---

## Getting Help

**If you're stuck:**
1. Check this document's troubleshooting section
2. Check the relevant doc in `docs/`
3. Search recent git commits for similar changes
4. Ask a teammate or team lead

**Remember:** Questions are welcome. Better to ask than to build in the wrong direction.

---

## Welcome to Aurum!

You're now ready to contribute. Remember the core principles:

- **Decide vs Explain** — Keep the boundary clear
- **Never fake data** — Real values or honest labels
- **Verify, don't assert** — Trust but verify
- **Small, gated units** — One thing at a time
- **Engine is frozen** — Changes require team review

Let's build something excellent together.

---

*Last updated: Current session*  
*For questions or improvements to this guide, submit a PR or contact the team lead.*
