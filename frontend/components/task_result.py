import streamlit as st


def _render_security_section(repository_security: dict):
    st.subheader("Repository Security")

    status = repository_security.get("status", "unknown")

    if status == "safe":
        st.success(f"Security status: {status}")
    elif status == "safe_with_warnings":
        st.warning(f"Security status: {status}")
    elif status == "blocked":
        st.error(f"Security status: {status}")
    else:
        st.info(f"Security status: {status}")

    checks = repository_security.get("checks", {})
    if checks:
        st.markdown("### Security checks")
        for check_name, check_status in checks.items():
            if check_status == "passed":
                st.write(f"[PASS] **{check_name}**: {check_status}")
            elif check_status == "warning":
                st.write(f"[WARN] **{check_name}**: {check_status}")
            elif check_status == "failed":
                st.write(f"[FAIL] **{check_name}**: {check_status}")
            else:
                st.write(f"[INFO] **{check_name}**: {check_status}")

    warnings = repository_security.get("warnings", [])
    if warnings:
        st.markdown("### Security warnings")
        for warning in warnings:
            st.warning(warning)

    blocked_reasons = repository_security.get("blocked_reasons", [])
    if blocked_reasons:
        st.markdown("### Blocked reasons")
        for reason in blocked_reasons:
            st.error(reason)

    risk_score = repository_security.get("risk_score")
    if risk_score is not None:
        st.markdown(f"### Risk score: `{risk_score}/100`")

    details = repository_security.get("details", {})
    if details:
        with st.expander("Security scan details", expanded=False):
            st.json(details)


def _render_validation_section(validation: dict):
    st.subheader("Artifact Validation")

    status = validation.get("status", "unknown")
    if status == "valid":
        st.success(f"Validation status: {status}")
    elif status == "partial":
        st.warning(f"Validation status: {status}")
    else:
        st.info(f"Validation status: {status}")

    required_artifacts = validation.get("required_artifacts", [])
    generated_artifacts = validation.get("generated_artifacts", [])
    missing_artifacts = validation.get("missing_artifacts", [])

    col1, col2, col3 = st.columns(3)
    col1.metric("Required artifacts", len(required_artifacts))
    col2.metric("Generated artifacts", len(generated_artifacts))
    col3.metric("Missing artifacts", len(missing_artifacts))

    if required_artifacts:
        st.markdown("### Required artifacts")
        for artifact in required_artifacts:
            st.write(f"- {artifact}")

    if generated_artifacts:
        st.markdown("### Generated artifacts")
        for artifact in generated_artifacts:
            st.write(f"- {artifact}")

    if missing_artifacts:
        st.markdown("### Missing artifacts")
        for artifact in missing_artifacts:
            st.error(artifact)


def _render_human_review_section(human_review: dict):
    st.subheader("Human Review Status")

    status = human_review.get("status", "unknown")
    if status == "awaiting_review":
        st.info("Waiting for human approval or corrections.")
    elif status == "approved_with_changes":
        st.warning("Approved after manual corrections.")
    elif status == "approved":
        st.success("Approved without manual changes.")
    else:
        st.info(f"Review status: {status}")

    changed_artifacts = human_review.get("changed_artifacts", [])
    if changed_artifacts:
        st.markdown("### Manually updated artifacts")
        for artifact in changed_artifacts:
            st.write(f"- {artifact}")

    review_notes = human_review.get("review_notes")
    if review_notes:
        st.markdown("### Review notes")
        st.write(review_notes)

    reviewed_at = human_review.get("reviewed_at")
    if reviewed_at:
        st.caption(f"Reviewed at: {reviewed_at}")


def _render_plan_section(plan: dict):
    st.subheader("Execution Plan")

    st.write(f"**Agent:** {plan.get('agent', 'N/A')}")
    st.write(f"**Complexity:** {plan.get('estimated_complexity', 'N/A')}")

    reasoning_summary = plan.get("reasoning_summary")
    if reasoning_summary:
        st.markdown("### Reasoning summary")
        st.info(reasoning_summary)

    steps = plan.get("steps", [])
    if steps:
        st.markdown("### Planned steps")
        for idx, step in enumerate(steps, start=1):
            st.write(f"{idx}. {step}")

    required_artifacts = plan.get("required_artifacts", [])
    if required_artifacts:
        st.markdown("### Required artifacts from planner")
        for artifact in required_artifacts:
            st.write(f"- {artifact}")


def _render_infrastructure_section(infrastructure: dict):
    st.subheader("Infrastructure Result")

    summary = infrastructure.get("summary")
    if summary:
        st.info(summary)

    notes = infrastructure.get("notes", [])
    if notes:
        st.markdown("### Notes")
        for note in notes:
            st.write(f"- {note}")

    security_recommendations = infrastructure.get("security_recommendations", [])
    if security_recommendations:
        st.markdown("### Security recommendations")
        for rec in security_recommendations:
            st.write(f"- {rec}")

    artifacts = infrastructure.get("artifacts", {})
    if artifacts:
        st.markdown("### Generated artifact contents")

        for artifact_name, artifact_content in artifacts.items():
            with st.expander(f"{artifact_name}", expanded=False):
                if artifact_content:
                    st.code(artifact_content)
                else:
                    st.write("Empty / not generated")


def render_task_result(task: dict):
    st.subheader("Final Result")

    task_status = task.get("status", "unknown")
    if task_status == "completed":
        st.success(f"Task status: {task_status}")
    elif task_status == "partial_success":
        st.warning(f"Task status: {task_status}")
    elif task_status == "blocked":
        st.error(f"Task status: {task_status}")
    else:
        st.info(f"Task status: {task_status}")

    st.markdown("### Task metadata")
    st.write(f"**Task ID:** {task.get('id', 'N/A')}")
    st.write(f"**Prompt:** {task.get('prompt', 'N/A')}")

    result = task.get("result") or {}

    repository_security = result.get("repository_security") or {}
    if repository_security:
        _render_security_section(repository_security)

    validation = result.get("validation") or {}
    if validation:
        _render_validation_section(validation)

    human_review = result.get("human_review") or {}
    if human_review:
        _render_human_review_section(human_review)

    plan = result.get("plan") or task.get("plan") or {}
    if plan:
        _render_plan_section(plan)

    infrastructure = result.get("infrastructure") or {}
    if infrastructure:
        _render_infrastructure_section(infrastructure)

    with st.expander("Raw task JSON", expanded=False):
        st.json(task)
