import streamlit as st


def render_task_logs(logs):
    st.subheader("Logs des agents")

    if not logs:
        st.info("Aucun log disponible.")
        return

    for log in logs:
        step = log.get("step", "unknown")
        message = log.get("message", "")
        st.write(f"- **{step}**: {message}")