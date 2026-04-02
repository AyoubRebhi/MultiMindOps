import streamlit as st

from frontend.components.env_security_summary import render_env_security_summary


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

    if validation.get("generated_with_rag") or validation.get("fallback_used"):
        st.markdown("### Generation telemetry")
        col1, col2 = st.columns(2)
        col1.metric("Generated with RAG", "Yes" if validation.get("generated_with_rag") else "No")
        col2.metric("Fallback used", "Yes" if validation.get("fallback_used") else "No")

    quality_issues = validation.get("quality_issues", [])
    if quality_issues:
        st.markdown("### Quality issues")
        for issue in quality_issues:
            if "sensitive" in issue.lower() or ".env" in issue.lower() or "clear text" in issue.lower():
                st.error(issue)
            else:
                st.warning(issue)

    warnings = validation.get("warnings", [])
    if warnings:
        st.markdown("### Validation warnings")
        for warning in warnings:
            st.warning(warning)


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


def _render_infrastructure_section(infrastructure: dict, sensitive_variable_names: set[str]):
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
                    st.code(
                        _sanitize_artifact_content_for_display(
                            artifact_content,
                            sensitive_variable_names,
                        )
                    )
                else:
                    st.write("Empty / not generated")


def _render_repository_analysis_section(result: dict):
    repo_summary = result.get("repo_summary") or {}
    repository_analysis = result.get("repository_analysis") or {}
    analysis_metadata = (
        ((repository_analysis.get("decision") or {}).get("latest_analysis") or {}).get("analysis_metadata")
        or {}
    )

    if not repo_summary and not repository_analysis:
        return

    st.subheader("Repository Analysis")

    cache_status = repository_analysis.get("cache_status")
    if cache_status:
        st.info(f"Analysis cache status: {cache_status}")

    services = repo_summary.get("services") or []
    key_entrypoints = repo_summary.get("key_entrypoints") or []
    infrastructure_needs = repo_summary.get("infrastructure_needs") or []

    col1, col2, col3 = st.columns(3)
    col1.metric("Detected services", len(services))
    col2.metric("Entrypoints", len(key_entrypoints))
    col3.metric("Infra needs", len(infrastructure_needs))

    render_env_security_summary(
        env_files=repo_summary.get("env_files"),
        sanitized_env_context=repo_summary.get("sanitized_env_context"),
        analysis_metadata=analysis_metadata,
    )

    if services:
        st.markdown("### Detected services")
        st.dataframe(
            [
                {
                    "Name": service.get("name", "unknown"),
                    "Type": service.get("type", "unknown"),
                    "Framework": service.get("framework", "unknown"),
                    "Language": service.get("language", "unknown"),
                    "Entrypoint": service.get("entrypoint", ""),
                    "Port": service.get("port", ""),
                }
                for service in services
            ],
            use_container_width=True,
            hide_index=True,
        )


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
    sensitive_variable_names = _collect_sensitive_variable_names(result)

    repository_security = result.get("repository_security") or {}
    if repository_security:
        _render_security_section(repository_security)

    validation = result.get("validation") or {}
    if validation:
        _render_validation_section(validation)

    _render_repository_analysis_section(result)

    human_review = result.get("human_review") or {}
    if human_review:
        _render_human_review_section(human_review)

    plan = result.get("plan") or task.get("plan") or {}
    if plan:
        _render_plan_section(plan)

    infrastructure = result.get("infrastructure") or {}
    if infrastructure:
        _render_infrastructure_section(infrastructure, sensitive_variable_names)

    with st.expander("Raw task JSON", expanded=False):
        st.json(_sanitize_task_for_display(task, sensitive_variable_names))


def _sanitize_task_for_display(value, sensitive_variable_names: set[str]):
    if isinstance(value, dict):
        sanitized = {}
        for key, nested_value in value.items():
            lowered = str(key).lower()
            if lowered == "env_security_runtime":
                sanitized[key] = {
                    "sensitive_values": "[hidden]",
                    "all_values": "[hidden]",
                }
                continue
            if lowered in {"artifacts", "original_artifacts", "reviewed_artifacts"} and isinstance(nested_value, dict):
                sanitized[key] = {
                    artifact_key: _sanitize_artifact_content_for_display(
                        artifact_value,
                        sensitive_variable_names,
                    )
                    for artifact_key, artifact_value in nested_value.items()
                }
                continue
            sanitized[key] = _sanitize_task_for_display(
                nested_value,
                sensitive_variable_names,
            )
        return sanitized

    if isinstance(value, list):
        return [_sanitize_task_for_display(item, sensitive_variable_names) for item in value]

    return value


def _collect_sensitive_variable_names(result: dict) -> set[str]:
    variables = (
        ((result.get("repo_summary") or {}).get("sanitized_env_context") or {}).get("variables")
        or []
    )
    return {
        str(item.get("name")).upper()
        for item in variables
        if item.get("is_sensitive") and item.get("name")
    }


def _sanitize_artifact_content_for_display(
    content: str,
    sensitive_variable_names: set[str],
) -> str:
    text = str(content or "")
    if not text or not sensitive_variable_names:
        return text

    sanitized_lines = []
    for line in text.splitlines():
        updated_line = line
        stripped = line.strip()
        for variable_name in sensitive_variable_names:
            for prefix in (
                f"{variable_name}=",
                f"{variable_name}:",
                f"- {variable_name}=",
            ):
                if stripped.startswith(prefix):
                    separator = "=" if "=" in prefix else ":"
                    left = updated_line.split(separator, 1)[0]
                    updated_line = f"{left}{separator} [REDACTED]"
                    break
            else:
                continue
            break
        sanitized_lines.append(updated_line)

    return "\n".join(sanitized_lines)
