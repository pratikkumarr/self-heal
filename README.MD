# Self-Healing CI/CD Pipeline

A GitHub Actions workflow deploys an approved FastAPI commit to Render and polls the new deploy by ID. Render gates traffic with HTTP readiness. The monitor independently checks the deployment through Render, records incidents in Supabase PostgreSQL, diagnoses available evidence, and optionally opens a GitHub issue. Its browser dashboard shows the public target probe, real Render deployment history, and saved incidents.

| Path | Responsibility |
| --- | --- |
| `target_app/` | Target app and versioned readiness configuration |
| `backend/` | Monitor API, Render polling, public probes, incident orchestration, and issue delivery |
| `database/` | PostgreSQL schema and incident store, with SQLite for local development |
| `ai/` | Sanitized log observations, OpenAI diagnosis, and rule-based analysis |
| `dashboard/` | Responsive HTML, CSS, and JavaScript |
| `.github/workflows/` | CI and authenticated deployment workflow |
| `tests/` | App tests, SQLite tests, and mocked provider integration tests |

## Run locally on Windows PowerShell

Run from the repository root using Python 3.11 or later. The Render and Actions configurations use Python 3.13. Activation is optional.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
Copy-Item .env.example .env
```

Use `Copy-Item` for initial setup only. The monitor reads `.env` from the repository root. Start the target in terminal 1.

```powershell
.\.venv\Scripts\python.exe -m uvicorn target_app.main:app --host 127.0.0.1 --port 8001
```

Start the monitor in terminal 2 from the same repository root.

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open [the dashboard](http://127.0.0.1:8000/) or run these checks from a third terminal.

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8001/version
Invoke-RestMethod http://127.0.0.1:8000/health
(Invoke-RestMethod http://127.0.0.1:8000/api/overview).target
```

Render supplies the deployed commit automatically. For a clean local checkout of a committed release, you can set `LOCAL_GIT_COMMIT` to its SHA before starting Uvicorn.

With only the local services configured, the dashboard probes the real local target and uses an empty SQLite incident store. Render deployment history is unavailable until you configure Render credentials. The automated provider fixtures are used exclusively in tests. The workspace contains no seeded deployment evidence.

## Verification and next steps

- [TEAM_SETUP.md](TEAM_SETUP.md) gives each teammate their files, staging commands, and PR sequence.
- [DEPLOYMENT.md](DEPLOYMENT.md) gives the cloud setup, exact release pinning, verification checklist, and browser-only exam walkthrough.
- Live GitHub Actions, Render, Supabase, OpenAI, and GitHub issue creation are **UNVERIFIED** until exercised with your repository, services, and credentials. Provider integration tests use mocked HTTP responses. Storage tests use real SQLite and, when `TEST_DATABASE_URL` points to a disposable PostgreSQL instance, real PostgreSQL. CI provisions that instance.
- The monitor records native retention when the pre-deploy ID remains live and the public endpoint serves its commit. A manual rollback creates a separate Render deploy with trigger `rollback`. Use the dashboard's Render link for that operation.
