import streamlit as st

MAX_ENV_FILE_SIZE = 100 * 1024


def render_repository_input():
    st.subheader("Nouvelle tache")

    prompt = st.text_area(
        "Task",
        placeholder="Ex: Generer une infrastructure Docker/Kubernetes securisee pour ce projet",
        height=150,
    )

    repo_url = st.text_input(
        "GitHub Repository URL (optionnel)",
        placeholder="https://github.com/owner/repository",
    )

    uploaded_env_file = st.file_uploader(
        "Optional .env file",
        type=None,
        accept_multiple_files=False,
        help="Accepted: .env, .env.*, or .txt files up to 100 KB. Secret values are never shown in the interface.",
    )

    uploaded_env_payload = None
    env_file_error = None
    if uploaded_env_file is not None:
        uploaded_env_payload, env_file_error = _normalize_uploaded_env(uploaded_env_file)
        if env_file_error:
            st.error(env_file_error)
        elif uploaded_env_payload:
            st.caption(
                f"Selected environment file: {uploaded_env_payload['name']} "
                f"({uploaded_env_payload['size']} bytes)"
            )

    repository_visibility = st.radio(
        "Repository visibility",
        options=["public", "private"],
        index=0,
        horizontal=True,
    )

    github_token = None
    if repository_visibility == "private":
        github_token = st.text_input(
            "GitHub Personal Access Token",
            type="password",
            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx",
            help="Ce token est utilise uniquement pour cloner le depot prive. Il n'est pas stocke.",
        )

    submitted = st.button("Lancer les agents")

    if submitted:
        if not prompt.strip():
            st.error("Task is required.")
            submitted = False
        if env_file_error:
            submitted = False

    return (
        prompt,
        repo_url.strip() or None,
        repository_visibility,
        github_token,
        uploaded_env_payload,
        submitted,
    )


def _normalize_uploaded_env(uploaded_file):
    file_name = (uploaded_file.name or "").strip()
    if not _is_allowed_env_filename(file_name):
        return None, "Invalid environment file. Please upload .env, .env.* or .txt."

    file_bytes = uploaded_file.getvalue()
    if len(file_bytes) > MAX_ENV_FILE_SIZE:
        return None, "Environment file is too large. Maximum supported size is 100 KB."

    content_type = getattr(uploaded_file, "type", "") or "text/plain"
    if not (content_type.startswith("text/") or content_type in {"application/octet-stream", "application/x-env"}):
        return None, "Unsupported environment file type. Please upload a plain text file."

    if b"\x00" in file_bytes:
        return None, "Binary files are not accepted for environment upload."

    return {
        "name": file_name,
        "content": file_bytes,
        "type": content_type,
        "size": len(file_bytes),
    }, None


def _is_allowed_env_filename(file_name: str) -> bool:
    lowered = file_name.lower()
    return (
        lowered == ".env"
        or lowered.startswith(".env.")
        or lowered.endswith(".env")
        or lowered.endswith(".txt")
    )
