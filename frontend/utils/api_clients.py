import requests

API_BASE = "http://localhost:8000"


def create_task(
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

    response = requests.post(f"{API_BASE}/tasks/", json=payload, timeout=300)

    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise Exception(f"Backend error {response.status_code}: {detail}")

    return response.json()