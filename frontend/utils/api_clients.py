import requests

API_BASE = "http://localhost:8000"


def preview_plan(
    prompt: str,
    repo_url: str | None = None,
    repository_visibility: str = "public",
    github_token: str | None = None,
):
    payload = {
        "prompt": prompt,
        "repo_url": repo_url,
        "repository_visibility": repository_visibility,
        "github_token": github_token,
    }

    response = requests.post(
        f"{API_BASE}/tasks/plan-preview",
        json=payload,
        timeout=300,
    )

    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise Exception(f"Backend error {response.status_code}: {detail}")

    return response.json()


def generate_artifacts(
    prompt: str,
    approved_artifacts: list[str],
    repo_url: str | None = None,
    repository_visibility: str = "public",
    github_token: str | None = None,
):
    payload = {
        "prompt": prompt,
        "repo_url": repo_url,
        "repository_visibility": repository_visibility,
        "github_token": github_token,
        "approved_artifacts": approved_artifacts,
    }
    response = requests.post(f"{API_BASE}/tasks/generate", json=payload, timeout=300)
    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise Exception(f"Backend error {response.status_code}: {detail}")
    return response.json()


def review_generated_artifacts(
    task_id: str,
    reviewed_artifacts: dict[str, str],
    review_notes: str | None = None,
):
    payload = {
        "reviewed_artifacts": reviewed_artifacts,
        "review_notes": review_notes,
    }
    response = requests.post(
        f"{API_BASE}/tasks/{task_id}/review",
        json=payload,
        timeout=300,
    )
    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise Exception(f"Backend error {response.status_code}: {detail}")
    return response.json()
