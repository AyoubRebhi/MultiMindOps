import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from frontend.components.artifact_editor import render_artifact_editor
from frontend.components.artifact_review import render_artifact_review
from frontend.components.repository_input import render_repository_input
from frontend.components.task_logs import render_task_logs
from frontend.components.task_result import render_task_result
from frontend.utils.api_clients import (
    generate_artifacts,
    preview_plan,
    review_generated_artifacts,
)

st.set_page_config(page_title="DevSecOps AI Platform", layout="wide")
st.title("DevSecOps AI Platform - Sprint 2 Prototype")

if "preview_response" not in st.session_state:
    st.session_state.preview_response = None

if "task_response" not in st.session_state:
    st.session_state.task_response = None

if "form_data" not in st.session_state:
    st.session_state.form_data = None

prompt, repo_url, repository_visibility, github_token, uploaded_env_file, submitted = render_repository_input()

if submitted:
    try:
        with st.spinner("Generating plan preview..."):
            preview = preview_plan(
                prompt=prompt,
                repo_url=repo_url,
                repository_visibility=repository_visibility,
                github_token=github_token,
                uploaded_env_file=uploaded_env_file,
            )
            st.session_state.preview_response = preview
            st.session_state.form_data = {
                "prompt": prompt,
                "repo_url": repo_url,
                "repository_visibility": repository_visibility,
                "github_token": github_token,
                "uploaded_env_file": uploaded_env_file,
            }
            st.session_state.task_response = None
    except Exception as exc:
        st.session_state.preview_response = None
        st.error(f"Plan preview failed: {exc}")

if st.session_state.preview_response:
    preview = st.session_state.preview_response
    preview_plan_payload = preview.get("plan")
    preview_status = preview.get("status")
    repository_security = preview.get("repository_security") or {}

    if preview_status == "blocked":
        st.error("Repository analysis was blocked by the security gate.")
        st.json(repository_security)
        logs = preview.get("logs", [])
        if logs:
            render_task_logs(logs)
    elif not isinstance(preview_plan_payload, dict):
        st.error("The planner did not return a valid plan preview.")
    else:
        st.subheader("Plan Preview")
        st.json(preview_plan_payload)

        required_artifacts = preview_plan_payload.get("required_artifacts", [])
        if not required_artifacts:
            st.info(
                "The planner returned a valid preview, but no artifacts were proposed for generation."
            )
            approved_artifacts = []
        else:
            approved_artifacts = render_artifact_review(required_artifacts)

        if required_artifacts and st.button("Generate approved artifacts"):
            with st.spinner("Generating selected artifacts..."):
                form_data = st.session_state.form_data or {}
                result = generate_artifacts(
                    prompt=form_data.get("prompt"),
                    repo_url=form_data.get("repo_url"),
                    repository_visibility=form_data.get("repository_visibility", "public"),
                    github_token=form_data.get("github_token"),
                    approved_artifacts=approved_artifacts,
                    uploaded_env_file=form_data.get("uploaded_env_file"),
                )
                st.session_state.task_response = result

if st.session_state.task_response:
    task = st.session_state.task_response
    render_task_logs(task.get("logs", []))
    render_task_result(task)

    human_review = (task.get("result") or {}).get("human_review") or {}
    if human_review.get("status") == "awaiting_review":
        reviewed_artifacts, review_notes, approve_clicked = render_artifact_editor(task)

        if approve_clicked:
            with st.spinner("Saving human review..."):
                updated_task = review_generated_artifacts(
                    task_id=task["id"],
                    reviewed_artifacts=reviewed_artifacts,
                    review_notes=review_notes,
                )
                st.session_state.task_response = updated_task
                st.rerun()
