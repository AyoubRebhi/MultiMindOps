import requests

API_BASE = "http://localhost:8000"


def preview_plan(
    prompt: str,
    repo_url: str | None = None,
    repository_visibility: str = "public",
    github_token: str | None = None,
    uploaded_env_file: dict | None = None,
):
    request_kwargs = _build_request_kwargs(
        prompt=prompt,
        repo_url=repo_url,
        repository_visibility=repository_visibility,
        github_token=github_token,
        uploaded_env_file=uploaded_env_file,
    )
    response = requests.post(
        f"{API_BASE}/tasks/plan-preview",
        timeout=300,
        **request_kwargs,
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
    uploaded_env_file: dict | None = None,
):
    request_kwargs = _build_request_kwargs(
        prompt=prompt,
        repo_url=repo_url,
        repository_visibility=repository_visibility,
        github_token=github_token,
        approved_artifacts=approved_artifacts,
        uploaded_env_file=uploaded_env_file,
    )
    response = requests.post(
        f"{API_BASE}/tasks/generate",
        timeout=300,
        **request_kwargs,
    )
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


def _build_task_form_data(
    *,
    prompt: str,
    repo_url: str | None,
    repository_visibility: str,
    github_token: str | None,
    approved_artifacts: list[str] | None = None,
):
    data = [
        ("prompt", prompt),
        ("repository_visibility", repository_visibility),
    ]
    if repo_url:
        data.append(("repo_url", repo_url))
    if github_token:
        data.append(("github_token", github_token))
    for artifact in approved_artifacts or []:
        data.append(("approved_artifacts", artifact))
    return data


def _build_env_file_payload(uploaded_env_file: dict | None):
    if not uploaded_env_file:
        return None
    return {
        "env_file": (
            uploaded_env_file.get("name") or ".env",
            uploaded_env_file.get("content") or b"",
            uploaded_env_file.get("type") or "text/plain",
        )
    }


def _build_request_kwargs(
    *,
    prompt: str,
    repo_url: str | None,
    repository_visibility: str,
    github_token: str | None,
    approved_artifacts: list[str] | None = None,
    uploaded_env_file: dict | None = None,
):
    if not uploaded_env_file:
        payload = {
            "prompt": prompt,
            "repo_url": repo_url,
            "repository_visibility": repository_visibility,
            "github_token": github_token,
        }
        if approved_artifacts is not None:
            payload["approved_artifacts"] = approved_artifacts
        return {"json": payload}

    return {
        "data": _build_task_form_data(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
            approved_artifacts=approved_artifacts,
        ),
        "files": _build_env_file_payload(uploaded_env_file),
    }
