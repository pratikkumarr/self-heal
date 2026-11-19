"use strict";

const el = (id) => document.getElementById(id);
const date = (value) => value ? new Date(value).toLocaleString() : "Unavailable";
let loading = false;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function setLink(anchor, url) {
  anchor.hidden = true;
  anchor.removeAttribute("href");
  if (typeof url !== "string") return;
  try {
    const parsed = new URL(url);
    if (!["https:", "http:"].includes(parsed.protocol)) return;
    anchor.href = parsed.href;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.hidden = false;
  } catch {
    return;
  }
}

function pill(status) {
  const tone = status === "live" ? " good" :
    /failed|canceled/.test(status) ? " bad" :
      /progress|queued|created/.test(status) ? " pending" : "";
  return element("span", status.replaceAll("_", " "), "pill" + tone);
}

function showTarget(target, live) {
  const health = el("health");
  health.textContent = target.healthy === true ? "Healthy" :
    target.healthy === false ? "Probe failed" : "Unavailable";
  health.className = "value " + (target.healthy === true ? "good" : target.healthy === false ? "bad" : "");
  el("health-detail").textContent = target.http_status ? "HTTP " + target.http_status : (target.error || "");
  el("target-url").textContent = target.url || "";
  setLink(el("target-url"), target.url);
  el("version").textContent = target.version || "Unavailable";
  el("commit").textContent = target.commit || "Commit unavailable";
  el("live").textContent = live?.id || "Unavailable";
  el("live-detail").textContent = live ?
    (live.trigger === "rollback" ? "Explicit Render rollback" : "Reported live by Render") : "";
}

function showDeployments(deployments, error) {
  const container = el("deploy-rows");
  container.replaceChildren();
  for (const deployment of deployments) {
    const row = element("tr");
    row.append(element("td", deployment.id, "mono"));
    const commit = element("td", deployment.commit.slice(0, 12), "mono");
    commit.title = deployment.commit;
    row.append(commit);
    const status = element("td");
    status.append(pill(deployment.status));
    row.append(status, element("td", deployment.trigger.replaceAll("_", " ")),
      element("td", date(deployment.updated_at)));
    container.append(row);
  }
  el("history").hidden = deployments.length === 0;
  el("history-empty").hidden = deployments.length > 0;
  el("history-empty").textContent = error || "Render returned no deployments.";
}

function finding(label, value) {
  const node = element("p", undefined, "finding");
  node.append(element("strong", label), document.createTextNode(value));
  return node;
}

function showIncidents(incidents, error) {
  const container = el("incident-rows");
  const expanded = new Set([...container.querySelectorAll("details[open]")].map((node) => node.dataset.deploy));
  container.replaceChildren();
  for (const incident of incidents) {
    const ev = incident.evidence;
    const diagnosis = ev.diagnosis;
    const card = element("article", undefined, "incident");
    const title = element("div", undefined, "incident-heading");
    title.append(element("h3", incident.deploy_id, "mono"), pill(incident.render_status));
    card.append(title, element("p", date(incident.observed_at) + " · " + incident.commit_sha, "muted mono"));
    card.append(finding("Recovery observation", ev.recovery));
    const details = element("details");
    details.dataset.deploy = incident.deploy_id;
    details.open = expanded.has(incident.deploy_id);
    const readiness = ev.candidate_http_status ?
      "HTTP " + ev.candidate_http_status + " · " + ev.candidate_reason + " (from service logs)" : "Unavailable.";
    details.append(element("summary", "Evidence and diagnosis"),
      finding("Render outcome", ev.status_detail), finding("Candidate readiness", readiness),
      finding("Log evidence", ev.log_availability));
    if (ev.log_observations.length) {
      details.append(element("pre", JSON.stringify(ev.log_observations, null, 2)));
    }
    details.append(finding(diagnosis.source + " diagnosis", diagnosis.summary),
      finding("Suggested fix", diagnosis.suggestion));
    if (diagnosis.note) details.append(element("p", diagnosis.note, "muted"));
    if (ev.baseline_deploy_id) details.append(finding("Previous live deploy", ev.baseline_deploy_id));
    if (ev.live_deploy_id) details.append(finding("Live deploy at observation", ev.live_deploy_id));
    if (ev.public_target) {
      details.append(finding("Public target at observation",
        (ev.public_target.http_status ? "HTTP " + ev.public_target.http_status : "HTTP status unavailable") +
        " · " + (ev.public_target.version || "Version unavailable")));
    }
    if (incident.issue_state !== "created") {
      details.append(finding("GitHub issue draft", ev.issue_draft.title), element("pre", ev.issue_draft.body));
    }
    card.append(details);
    const links = element("div", undefined, "incident-links");
    if (incident.issue_url) {
      const issue = element("a", "GitHub issue ↗");
      setLink(issue, incident.issue_url);
      links.append(issue);
    } else {
      const issueStatus = incident.issue_state === "draft" ? "Draft issue" : "Issue delivery requires review";
      links.append(element("span", issueStatus, "pill"));
    }
    if (ev.run_url) {
      const run = element("a", "GitHub Actions run ↗");
      setLink(run, ev.run_url);
      links.append(run);
    }
    card.append(links);
    container.append(card);
  }
  el("incidents-empty").hidden = incidents.length > 0;
  el("incidents-empty").textContent = error || "No incidents have been recorded.";
}

async function refresh() {
  if (loading) return;
  loading = true;
  el("refresh").disabled = true;
  try {
    const response = await fetch("/api/overview", { cache: "no-store" });
    if (!response.ok) throw new Error("Overview unavailable");
    const data = await response.json();
    el("storage").textContent = data.storage;
    setLink(el("actions-link"), data.actions_url);
    setLink(el("render-link"), data.render_url);
    const live = data.deployments.find((deploy) => deploy.status === "live");
    showTarget(data.target, live);
    showDeployments(data.deployments, data.errors.render);
    showIncidents(data.incidents, data.errors.database);
    el("refresh-state").textContent = "Target checked " + date(data.target.observed_at);
  } catch {
    el("refresh-state").textContent = "Refresh failed. Any displayed observations may be stale.";
    if (!el("deploy-rows").children.length) el("history-empty").textContent = "History unavailable.";
    if (!el("incident-rows").children.length) el("incidents-empty").textContent = "Incidents unavailable.";
  } finally {
    loading = false;
    el("refresh").disabled = false;
  }
}

el("refresh").addEventListener("click", refresh);
refresh();
window.setInterval(() => { if (!document.hidden) refresh(); }, 30000);
