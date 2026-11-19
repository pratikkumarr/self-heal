# Cloud deployment and browser exam

Allow time for a full rehearsal. Render can take up to 15 minutes to reject a candidate that never passes readiness, in addition to build time. Its free services can also take about a minute to wake. [Render health checks](https://render.com/docs/health-checks) · [Render free services](https://render.com/docs/free)

## 1. Pratik prepares GitHub and Supabase

1. Finish the four merges in [TEAM_SETUP.md](TEAM_SETUP.md) and verify that the CI run on `main` passes. Enable **Issues** in the repository settings if you want issue posting.
2. Create a Supabase project. In **SQL Editor → New query**, paste and run [database/schema.sql](database/schema.sql). Check that `select count(*) from selfheal.deployments;` succeeds.
3. In Supabase **Connect**, choose **Session pooler** and copy its URI. Substitute the database password, URL-encoding it if it contains reserved URI characters, and append `?sslmode=require` (or `&sslmode=require` if the URI already has query parameters). Use the pooler's port `5432`. Save the URI as `DATABASE_URL` in the Render monitor in step 4. [Supabase PostgreSQL connections](https://supabase.com/docs/guides/database/connecting-to-postgres)
4. Generate a random token for `MONITOR_INGEST_TOKEN` in PowerShell. Enter the same value in Render monitor and in the restricted GitHub environment in step 5.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 2. Ram prepares optional diagnosis

Create an OpenAI project API key if available and enter it as `OPENAI_API_KEY` on the Render monitor. It defaults to `gpt-4.1-mini`. Set `OPENAI_MODEL` there if using another compatible model. Run the first exam rehearsal with whichever mode you plan to show. The app uses the Responses API with storage disabled and sends recognized observations from service logs, without their raw messages. If the key is absent or the request fails, the incident labels the result **Rule-based**. [OpenAI Responses API storage](https://developers.openai.com/api/docs/guides/conversation-state?api-mode=responses)

## 3. Sachin pins v1 and creates the target service

Use a clean clone. Create the dedicated Render release branch **before** provisioning the target or applying the Blueprint.

```powershell
git switch main
git pull --ff-only origin main
git status --short
git switch -c release/target
Get-Content target_app/release.json
$v1 = (git rev-parse HEAD).Trim()
git push -u origin release/target
$v1
```

The release manifest must say `v1` and `ready`. Save the full SHA printed above. The target's first Render deployment should build this commit.

Create the two Git-backed Render web services in the same workspace with **one** of these methods.

- **Blueprint.** In Render, select **New → Blueprint**, connect the GitHub repository, and use `render.yaml` from `main`. Enter `DATABASE_URL` and `MONITOR_INGEST_TOKEN` when prompted. Confirm both services are created. Use the monitor's Environment page for the rest of step 4.
- **Manual services.** Select **New → Web Service**, connect the same GitHub repository for each service, and enter the settings below. Set the monitor's environment before starting its first build if the create form permits it.

| Render field | Target | Monitor |
| --- | --- | --- |
| Name | `selfheal-target` | `selfheal-monitor` |
| Branch | `release/target` | `main` |
| Root Directory | Leave blank | Leave blank |
| Runtime | Python | Python |
| Instance type | Free | Free |
| Build Command | `pip install -r target_app/requirements.txt` | `pip install -r requirements.txt` |
| Start Command | `python -m uvicorn target_app.main:app --host 0.0.0.0 --port $PORT` | `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` | `/health` |
| Auto-Deploy | Off | Off |

On Render, verify that target **Auto-Deploy** is off before pushing v2, and leave the target without a persistent disk so zero-downtime deployments apply. Wait for its first successful deploy and open `<TARGET_URL>/health` and `<TARGET_URL>/version` in the browser. Confirm HTTP 200 and the exact approved v1 SHA. Copy both services' public HTTPS URLs and the target's service ID (`srv-…`) from the target service page. [Render Blueprint reference](https://render.com/docs/blueprint-spec) · [Render deploy behavior](https://render.com/docs/deploys)

## 4. Saatyak configures the monitor and checks the database

In Render, use **Account Settings → API Keys** to create two keys for this workspace. Give the monitor key read access to the target service/deploys and read access to logs if available. Give the Actions key permission to read the target service/deploys and trigger a deploy. Use the Actions key only in step 5. Find the workspace ID (`tea-…`) in the Render workspace settings, or use the [List Workspaces API](https://api-docs.render.com/reference/list-owners). [Render API key permissions](https://render.com/docs/api)

In **monitor → Environment**, set these values and deploy the monitor.

| Monitor variable | Value |
| --- | --- |
| `DATABASE_URL` | Supabase session pooler URI from step 1 |
| `MONITOR_INGEST_TOKEN` | Shared token from step 1 |
| `TARGET_URL` | Target public HTTPS base URL |
| `RENDER_TARGET_SERVICE_ID` | Target service ID |
| `RENDER_API_KEY` | Monitor Render read key |
| `RENDER_OWNER_ID` | Workspace ID for log collection. Omit if unavailable |
| `GITHUB_REPO` | `OWNER/REPO` for dashboard links and issue creation |
| `GITHUB_ISSUES_TOKEN` | Optional fine-grained PAT for this repo with **Issues: Read and write** |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional values from Ram |

Create the GitHub token in **Personal settings → Developer settings → Personal access tokens → Fine-grained tokens**. Select the correct resource owner and repository. GitHub organization approval may be required. Keep the token server-side in Render. An unconfigured issue token leaves a stored draft. [GitHub create-issue API](https://docs.github.com/en/rest/issues/issues#create-an-issue)

Check `<MONITOR_URL>/health` for `{"status":"healthy","storage":"postgresql"}`. Open `<MONITOR_URL>/` and confirm the exact v1 version, deploy ID, and commit. Pratik can check persisted records anytime in Supabase SQL Editor.

```sql
select deploy_id, commit_sha, render_status, observed_at, is_incident, issue_state, issue_url,
       evidence::jsonb ->> 'candidate_http_status' as candidate_http_status,
       evidence::jsonb ->> 'recovery' as recovery
from selfheal.deployments
order by observed_at desc;
```

## 5. Sachin configures Actions and proves v1 dispatch

In **GitHub repo → Settings → Environments**, create `render-target`. Under **Deployment branches and tags**, choose **Selected branches and tags** and add a **Branch** rule matching `main`. Keep this environment's deployment credentials scoped to it. Public repositories support this on GitHub Free. A private repository requires a GitHub plan that supports environment secrets and branch policies. [GitHub deployment environment settings](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

- Add environment secrets **`RENDER_API_KEY`** (the Actions deploy key) and **`MONITOR_INGEST_TOKEN`** (the monitor's token).
- Under **Settings → Secrets and variables → Actions → Variables**, add repository variables **`RENDER_TARGET_SERVICE_ID`**, **`TARGET_URL`**, **`MONITOR_URL`**, and **`TARGET_V1_SHA`**. The URLs are public HTTPS base URLs and the SHA is the full value from step 3.
- Open **Actions → Deploy target and verify recovery → Run workflow**. Select branch `main`, operation `v1`, and leave the report fields blank. Review the workflow summary, Render history, and `/version`. The job requires a live deploy and a public readiness response from the exact v1 commit.

## 6. Sachin pins v2 and rehearses rejection

From the clone used to create `release/target`, confirm the branch is still at the v1 SHA. Change only the checked-in target manifest.

```powershell
git switch release/target
git pull --ff-only origin release/target
git rev-parse HEAD
Copy-Item target_app/releases/v2.json target_app/release.json
git add -- target_app/release.json
git diff --cached --name-only
git commit -m "Prepare v2 with deliberately failing readiness"
git diff --name-only HEAD^ HEAD
$v2 = (git rev-parse HEAD).Trim()
git push origin release/target
$v2
```

Only `target_app/release.json` should appear in the diff. Keep the release branch rooted at the approved snapshot and keep both release commits reachable. The workflow's selected SHA is independent of moving branch heads. Set repository variable **`TARGET_V2_SHA`** to the full v2 SHA. Leave `main` unchanged. [Render commit-specific deployments](https://api-docs.render.com/reference/create-deploy)

Dispatch **v2** on **main** with the same workflow. The candidate starts and passes the workflow's basic CI check, while its readiness route returns HTTP 503. Only Render can route probes to the candidate until it becomes live. The public target should keep returning v1.

| Verify in the browser | Expected evidence after the rehearsal |
| --- | --- |
| GitHub Actions | Candidate Smoke CI passed, selected v2 SHA matches the Render deploy, and the deployment job exits red after reporting Render's rejection |
| Render target Deploys | New v2 deploy has a failed or canceled update event and the previous v1 deploy remains live. Review the candidate's event and logs for the readiness failure |
| Public target | `/health` returns HTTP 200 and `/version` still returns v1 and its SHA |
| Monitor and Supabase | Same v2 deployment ID, commit, observed time, and Render status. Native protection is shown when baseline ID and public commit are verified |
| Evidence and diagnosis | Candidate HTTP 503 is shown when the server captures a readiness marker matching its commit. Otherwise inspect the Render event and report that the monitor had only the available evidence |
| GitHub Issues | The incident links to a real issue when creation succeeds. With no token or a definitive API rejection it shows a draft |

## Browser-only exam

1. Rehearse once before the exam and bookmark your monitor, target `/health` and `/version`, GitHub Actions run, and Render target Deploys page. Confirm staff can access any private pages they need. Use GitHub and Render sign-in for their authenticated controls.
2. At the exam, open the monitor and target on the college computer. Compare the live deploy ID, target HTTP 200, and v1 SHA. Show the previous genuine rehearsal incident immediately if time is tight.
3. Click **Run deployment** in the monitor, select **Run workflow → main → v2 → Run workflow**, and show candidate Smoke CI followed by Render polling. Refresh the monitor while Render evaluates readiness. In a short slot, show the rehearsal run's completed evidence while the new run is still in progress.
4. When Render settles, open the failed candidate event, expand its monitor incident, and compare the deploy ID and commit with Actions. Show the still-healthy v1, diagnosis source, and GitHub issue or draft. This run demonstrates native deployment protection.
5. If asked to demonstrate a separate manual rollback, use **Render deploys**, choose a recent eligible successful deploy, then click **Rollback → Rollback to this deploy**. Record which deploy you selected. Confirm the new deployment shows trigger `rollback` and status `live` in the monitor, and check its commit and readiness at the public target. The rollback is a separate deployment. [Render rollback workflow](https://render.com/docs/rollbacks)

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Smoke CI fails | Compare the pinned SHA and its manifest with the selected v1/v2 option. Inspect dependency installation and Python version in the job log. |
| Render build fails | Open the actual candidate's Deploy details. Check the repository root and install command. A build failure lacks the expected v2 readiness evidence. |
| Monitor remains unhealthy | Check the Supabase project is awake, `DATABASE_URL` uses the configured session pooler and TLS, the password is encoded, and `selfheal.deployments` exists. Review Render logs. |
| Render API 401/403 | Check the Actions key is in the `render-target` environment, the monitor has its own read key, each has the required workspace permissions, and the ID points to the target service. |
| Candidate readiness takes too long | Allow Render's 15-minute readiness window plus build time. Review the deploy page. If Actions times out, save its candidate and previous live deploy IDs. Once Render settles, dispatch `report` on `main` and enter those IDs. This reads an existing deploy without triggering a new one. |
| Monitor report 401/503/502 | Check both copies of the ingest token, monitor health, database credentials, and the monitor's Render key. After fixing the configuration, dispatch `report` using the original deploy and baseline IDs. |
| Candidate shows `live` unexpectedly | Verify the target health-check path is `/health` and the v2 SHA has the failing manifest. Restore v1 via workflow or use Render's rollback controls and verify the public endpoints before retrying. |
| Candidate 503 unavailable | Check workspace ID, logs permissions, and the candidate's Render Deploy page. Build/application logs are queried by service and deploy time window. The stored incident retains the evidence available at first report. |
| Draft issue | Check that Issues is enabled and the fine-grained token has access. Dispatch `report` for that same deploy after fixing credentials. |
| Issue delivery requires review | Search GitHub Issues for the exact deploy ID. An interrupted request can leave an uncertain posting result. Confirm whether GitHub created the issue before manually filing the stored draft. Automatic retries avoid creating a second issue in this state. |
| Missing Actions button or run skipped | Set `GITHUB_REPO` on the monitor, ensure the workflow exists on the default branch, allow Actions in Settings, and dispatch using `main`. |
| Free service cold start | Open the monitor and target in the browser ahead of the exam. Wait for their endpoints to respond, then refresh the dashboard. |
