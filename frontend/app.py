import streamlit as st

from components.repository_input import render_repository_input
from components.task_logs import render_task_logs
from components.task_result import render_task_result
from utils.api_clients import create_task

st.set_page_config(page_title="DevSecOps AI Platform", layout="wide")
st.title("DevSecOps AI Platform - Sprint 2 Prototype")

if "task_response" not in st.session_state:
    st.session_state.task_response = None

prompt, repo_url, submitted = render_repository_input()

if submitted:
    with st.spinner("Exécution du workflow multi-agents..."):
        response = create_task(prompt=prompt, repo_url=repo_url)
        st.session_state.task_response = response

if st.session_state.task_response:
    task = st.session_state.task_response
    render_task_logs(task.get("logs", []))
    render_task_result(task)