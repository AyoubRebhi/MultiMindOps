import streamlit as st


def render_task_logs(logs):
    st.subheader("Agent Logs")

    if not logs:
        st.info("No logs available.")
        return

    for log in logs:
        step = log.get("step", "unknown")
        message = log.get("message", "")

        if "security" in step:
            st.warning(f"[{step}] {message}")
        elif step == "completed":
            st.success(f"[{step}] {message}")
        elif "validation" in step:
            st.info(f"[{step}] {message}")
        else:
            st.write(f"**[{step}]** {message}")