import streamlit as st


def render_artifact_editor(task: dict):
    result = task.get("result") or {}
    human_review = result.get("human_review") or {}
    infrastructure = result.get("infrastructure") or {}

    artifacts = (
        human_review.get("reviewed_artifacts")
        or human_review.get("original_artifacts")
        or infrastructure.get("artifacts")
        or {}
    )

    if not artifacts:
        return {}, None, False

    st.subheader("Human Review")
    st.write(
        "Review the generated files below. You can edit them before giving final approval."
    )

    reviewed_artifacts = {}
    task_id = task.get("id", "task")

    for artifact_name, artifact_content in artifacts.items():
        reviewed_artifacts[artifact_name] = st.text_area(
            f"{artifact_name}",
            value=artifact_content or "",
            height=260,
            key=f"artifact_review_{task_id}_{artifact_name}",
        )

    review_notes = st.text_area(
        "Review notes",
        value=human_review.get("review_notes") or "",
        placeholder="Optional notes about manual corrections or approval rationale",
        key=f"artifact_review_notes_{task_id}",
    )

    approve_clicked = st.button(
        "Approve reviewed artifacts",
        key=f"approve_review_{task_id}",
    )

    return reviewed_artifacts, review_notes, approve_clicked
