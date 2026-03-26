import os
import sys
import streamlit as st

# Ensure the repository root is on sys.path so imports like "frontend.components" work
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from frontend.components.repository_input import render_repository_input
from frontend.components.task_logs import render_task_logs
from frontend.components.task_result import render_task_result
from frontend.utils.api_clients import create_task

st.set_page_config(page_title="DevSecOps AI Platform", layout="wide")
st.title("DevSecOps AI Platform - Sprint 2 Prototype")

if "task_response" not in st.session_state:
    st.session_state.task_response = None

prompt, repo_url, repository_visibility, github_token, submitted = render_repository_input()

if submitted:
    with st.spinner("Exécution du workflow multi-agents..."):
        response = create_task(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
        )
        st.session_state.task_response = response

if st.session_state.task_response:
    task = st.session_state.task_response
    render_task_logs(task.get("logs", []))
    render_task_result(task)