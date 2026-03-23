import streamlit as st


def render_task_result(task):
    st.subheader("Résultat final")
    st.json(task)

    if task.get("plan"):
        st.subheader("Plan généré")
        st.json(task["plan"])

    result = task.get("result") or {}
    infrastructure = result.get("infrastructure") or {}

    if infrastructure:
        st.subheader("Artefacts infrastructure")
        st.json(infrastructure)