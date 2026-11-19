# Team setup

## Share the source

Pratik runs this from the project root in PowerShell. It writes one ZIP to the system temporary directory. The archive contains the source and templates, including `.github` and `.env.example`.

```powershell
$source = @(
  'dashboard', 'database', 'ai', 'backend', 'target_app', '.github', 'tests',
  'README.md', 'TEAM_SETUP.md', 'DEPLOYMENT.md', '.env.example', '.gitignore',
  '.python-version', 'render.yaml', 'requirements.txt', 'requirements-dev.txt', 'pytest.ini'
)
$zip = Join-Path $env:TEMP ('selfheal-source-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')
tar.exe -a -c -f $zip --exclude=__pycache__ --exclude=*.pyc -- $source
Get-Item -LiteralPath $zip
```

Check that the archive entries include `.github/workflows/deploy-target.yml` and `.env.example`. Share this archive with all four members. It excludes local secrets, `.git`, virtual environments and local data. Extract it into a staging folder outside your clone.

Pratik uses the existing shared GitHub repository with collaborator access for all four members. If starting with a new repository, initialize it with a README and use `main` as the default branch. The repository plan must support a branch-restricted Actions environment. [GitHub environment availability](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

## Clone, branch, and stage

Each member opens PowerShell in their own parent folder and sets the repository URL and their branch from the table.

```powershell
git clone https://github.com/OWNER/REPO.git selfheal
Set-Location selfheal
git switch main
git pull --ff-only origin main
$branch = 'codex/pratik-dashboard'  # Use your branch below
git switch -c $branch
```

Copy only your assigned files from the extracted ZIP into the corresponding paths in your clone. The copied branch can rely on files the other members add through their PRs. If the repository tracks `README.MD`, Pratik performs the case-only rename on Windows **before** copying the ZIP's `README.md`.

```powershell
git mv README.MD README-case-temp.md
git mv README-case-temp.md README.md
```

| Member and branch | Owned files |
| --- | --- |
| Pratik — `codex/pratik-dashboard` | `dashboard/`, `database/`, `README.md`, `TEAM_SETUP.md`, `DEPLOYMENT.md`, `.gitignore`, `tests/__init__.py`, `tests/fixtures.py`, `tests/test_adapters.py` |
| Ram — `codex/ram-diagnosis` | `ai/` |
| Saatyak — `codex/saatyak-orchestrator` | `backend/` except `backend/deploy_target.py`, plus `.env.example`, `requirements.txt`, `tests/test_monitor.py` |
| Sachin — `codex/sachin-delivery` | `target_app/`, `.github/workflows/`, `backend/deploy_target.py`, `render.yaml`, `.python-version`, `requirements-dev.txt`, `pytest.ini`, `tests/test_target.py`, `tests/test_deploy_workflow.py` |

Run your own staging command.

```powershell
# Pratik
git add -- dashboard database README.md TEAM_SETUP.md DEPLOYMENT.md .gitignore tests/__init__.py tests/fixtures.py tests/test_adapters.py

# Ram
git add -- ai

# Saatyak
git add -- backend/__init__.py backend/main.py backend/settings.py backend/orchestrator.py backend/render_api.py backend/target_probe.py backend/github_api.py .env.example requirements.txt tests/test_monitor.py

# Sachin
git add -- target_app .github/workflows backend/deploy_target.py render.yaml .python-version requirements-dev.txt pytest.ini tests/test_target.py tests/test_deploy_workflow.py
```

```powershell
git diff --cached --name-status
git diff --cached --check
git commit -m "Implement assigned self-healing pipeline module"
git push -u origin $branch
```

On GitHub, open **Pull requests → New pull request**, use base `main`, compare your branch, review **Files changed**, and create the PR. Merge Pratik, Ram, and Saatyak first. Before opening or merging Sachin's final PR, bring those changes into his branch and run the full tests.

```powershell
git fetch origin
git merge origin/main
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
git push
```

The full app is expected to start once the four modules are merged. The team can then configure the cloud dependencies in the order in [DEPLOYMENT.md](DEPLOYMENT.md).
