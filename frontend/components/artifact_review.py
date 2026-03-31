import streamlit as st


def render_artifact_review(required_artifacts: list[str]) -> list[str]:
    st.subheader("Review required artifacts")
    st.write("Select the artifacts you want to generate.")

    approved = []

    for artifact in required_artifacts:
        checked = st.checkbox(artifact, value=True, key=f"artifact_{artifact}")
        if checked:
            approved.append(artifact)

    return approved