import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from frontend.components.artifact_review import render_artifact_review
from frontend.components.repository_input import render_repository_input
from frontend.components.task_logs import render_task_logs
from frontend.components.task_result import render_task_result
from frontend.utils.api_clients import generate_artifacts, preview_plan

st.set_page_config(page_title="DevSecOps AI Platform", layout="wide")
st.title("DevSecOps AI Platform - Sprint 2 Prototype")

if "preview_response" not in st.session_state:
    st.session_state.preview_response = None

if "task_response" not in st.session_state:
    st.session_state.task_response = None

if "form_data" not in st.session_state:
    st.session_state.form_data = None

prompt, repo_url, repository_visibility, github_token, submitted = render_repository_input()

if submitted:
    with st.spinner("Generating plan preview..."):
        preview = preview_plan(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
        )
        st.session_state.preview_response = preview
        st.session_state.form_data = {
            "prompt": prompt,
            "repo_url": repo_url,
            "repository_visibility": repository_visibility,
            "github_token": github_token,
        }
        st.session_state.task_response = None

if st.session_state.preview_response:
    preview = st.session_state.preview_response

    st.subheader("Plan Preview")
    st.json(preview.get("plan"))

    required_artifacts = (preview.get("plan") or {}).get("required_artifacts", [])
    approved_artifacts = render_artifact_review(required_artifacts)

    if st.button("Generate approved artifacts"):
        with st.spinner("Generating selected artifacts..."):
            form_data = st.session_state.form_data or {}
            result = generate_artifacts(
                prompt=form_data.get("prompt"),
                repo_url=form_data.get("repo_url"),
                repository_visibility=form_data.get("repository_visibility", "public"),
                github_token=form_data.get("github_token"),
                approved_artifacts=approved_artifacts,
            )
            st.session_state.task_response = result

if st.session_state.task_response:
    task = st.session_state.task_response
    render_task_logs(task.get("logs", []))
    render_task_result(task)