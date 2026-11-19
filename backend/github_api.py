from backend.settings import REPO


def issue_payload(deploy, evidence, rule):
    return {
        "title": f"Render incident {deploy.id} ({deploy.status})",
        "body": (
            f"Render deploy: `{deploy.id}`\n\n"
            f"Commit: `{deploy.commit}`\n\n"
            f"Observed status: `{deploy.status}` at {deploy.updated_at}\n\n"
            f"{evidence['status_detail']}\n\n"
            f"Candidate readiness HTTP status: {evidence['candidate_http_status'] or 'Unavailable'}\n\n"
            f"Recovery observation: {evidence['recovery']}\n\n"
            f"Suggested fix: {rule['suggestion']}"
        ),
    }


def create_issue(client, repo, token, payload):
    if not REPO.fullmatch(repo):
        raise ValueError("Invalid GitHub repository")
    response = client.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        json=payload,
    )
    response.raise_for_status()
    number = response.json()["number"]
    if response.status_code != 201 or type(number) is not int or number < 1:
        raise ValueError("GitHub issue creation could not be confirmed")
    return f"https://github.com/{repo}/issues/{number}"
