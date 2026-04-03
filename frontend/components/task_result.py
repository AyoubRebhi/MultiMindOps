import streamlit as st

from frontend.components.env_security_summary import render_env_security_summary
from frontend.utils.api_clients import view_artifact_file


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

    result = task.get("result") or {}
    artifact_contract = result.get("artifact_contract") or {}
    repo_summary = result.get("repo_summary") or {}
    validation = result.get("validation") or {}
    cicd = result.get("cicd") or {}
    sensitive_variable_names = _collect_sensitive_variable_names(result)

    _render_demo_view(
        task=task,
        result=result,
        artifact_contract=artifact_contract,
        repo_summary=repo_summary,
        validation=validation,
        cicd=cicd,
    )

    show_debug = st.toggle("Show debug details", value=False)
    if not show_debug:
        return

    _render_debug_view(
        task=task,
        result=result,
        sensitive_variable_names=sensitive_variable_names,
    )


def _render_demo_view(
    *,
    task: dict,
    result: dict,
    artifact_contract: dict,
    repo_summary: dict,
    validation: dict,
    cicd: dict,
):
    st.markdown("### Demo Summary")

    repo_url = (
        (((result.get("repository_analysis") or {}).get("identity") or {}).get("normalized_url"))
        or task.get("repo_url")
        or "Repository not provided"
    )
    stack_label = _format_stack_label(repo_summary)
    execution_policy = (
        result.get("execution_policy")
        or artifact_contract.get("execution_policy")
        or {}
    )

    col1, col2 = st.columns(2)
    col1.write(f"**Repository:** {repo_url}")
    col2.write(f"**Detected stack:** {stack_label}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Global status", validation.get("status", result.get("status", "unknown")))
    col2.metric(
        "Infrastructure artifacts",
        len(_paths_by_status(artifact_contract, groups={"infrastructure", "deployment"}, statuses={"generated"})),
    )
    col3.metric(
        "CI/CD artifacts",
        len(_paths_by_status(artifact_contract, groups={"cicd"}, statuses={"generated", "reused", "detected"})),
    )

    if execution_policy.get("artifact_generation_only"):
        st.success("Artifact generation only. No real deployment, build, or apply commands are executed.")
    else:
        st.info("Execution policy available.")

    _render_status_explainer()
    _render_generated_reused_missing_summary(artifact_contract, validation)
    _render_infrastructure_demo_section(artifact_contract)
    _render_cicd_demo_section(artifact_contract, cicd)
    _render_validation_demo_section(validation)


def _render_status_explainer():
    st.caption(
        "Status guide: generated = created by the platform, reused = already existed and was kept, "
        "missing = requested but not satisfied."
    )


def _render_generated_reused_missing_summary(artifact_contract: dict, validation: dict):
    statuses = artifact_contract.get("artifact_statuses") or []
    generated = sorted(
        item["path"] for item in statuses if item.get("status") == "generated"
    )
    reused = sorted(
        item["path"]
        for item in statuses
        if item.get("status") in {"reused", "detected"}
    )
    missing = validation.get("missing_artifacts") or artifact_contract.get("missing_artifacts") or []
    quality_issues = validation.get("quality_issues") or []

    st.markdown("### Outcome Summary")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Generated", len(generated))
    col2.metric("Reused", len(reused))
    col3.metric("Missing", len(missing))
    col4.metric("Quality issues", len(quality_issues))

    if generated:
        st.markdown("**Generated artifacts**")
        for path in generated:
            st.write(f"- {path}")

    if reused:
        st.markdown("**Reused artifacts**")
        for path in reused:
            st.write(f"- {path}")

    if missing:
        st.markdown("**Missing artifacts**")
        for path in missing:
            st.warning(path)

    if quality_issues:
        st.markdown("**Quality issues**")
        for issue in quality_issues:
            st.warning(issue)


def _render_infrastructure_demo_section(artifact_contract: dict):
    generated_paths = _paths_by_status(
        artifact_contract,
        groups={"infrastructure", "deployment"},
        statuses={"generated"},
    )
    reused_paths = _paths_by_status(
        artifact_contract,
        groups={"infrastructure", "deployment"},
        statuses={"reused", "detected"},
    )

    st.markdown("### Infrastructure Artifacts")
    if generated_paths:
        for path in generated_paths:
            st.write(f"- {path}")
    else:
        st.info("No infrastructure artifact was generated in this run.")

    if reused_paths:
        st.caption("Existing infrastructure-related artifacts detected:")
        for path in reused_paths:
            st.write(f"- {path}")


def _render_cicd_demo_section(artifact_contract: dict, cicd: dict):
    generated_paths = _paths_by_status(
        artifact_contract,
        groups={"cicd"},
        statuses={"generated"},
    )
    reused_paths = _paths_by_status(
        artifact_contract,
        groups={"cicd"},
        statuses={"reused", "detected"},
    )
    missing_paths = _paths_by_status(
        artifact_contract,
        groups={"cicd"},
        statuses={"pending", "skipped"},
    )

    st.markdown("### CI/CD Artifacts")

    if reused_paths:
        st.info("CI/CD workflow already exists in the repository and was reused.")
    elif generated_paths:
        st.success("CI/CD workflow was generated for this repository.")
    elif missing_paths:
        st.warning("CI/CD workflow was requested but is still pending.")
    else:
        st.info("No CI/CD artifact was required for this run.")

    if generated_paths:
        st.markdown("**Generated CI/CD artifacts**")
        for path in generated_paths:
            st.write(f"- {path}")

    if reused_paths:
        st.markdown("**Reused CI/CD artifacts**")
        for path in reused_paths:
            label = "Workflow existing and reused" if path.startswith(".github/workflows/") else "Reused"
            st.write(f"- {path} ({label})")

    if missing_paths:
        st.markdown("**Pending or skipped CI/CD targets**")
        for path in missing_paths:
            st.write(f"- {path}")

    workflow_artifacts = cicd.get("artifacts") or {}
    workflow_path = next(
        (path for path in generated_paths if path.startswith(".github/workflows/")),
        None,
    )
    if workflow_path and workflow_artifacts:
        workflow_content = next(iter(workflow_artifacts.values()))
        with st.expander("Generated workflow content", expanded=False):
            st.code(workflow_content, language="yaml")

    _render_reused_cicd_viewers(cicd, key_prefix="demo")


def _render_validation_demo_section(validation: dict):
    st.markdown("### Validation")

    status = validation.get("status", "unknown")
    if status == "valid":
        st.success("Validation passed")
    elif status == "partial":
        st.warning("Validation is partial")
    else:
        st.info(f"Validation status: {status}")

    warnings = validation.get("warnings") or []
    if warnings:
        st.markdown("**Important warnings**")
        for warning in warnings:
            st.warning(warning)


def _render_debug_view(
    *,
    task: dict,
    result: dict,
    sensitive_variable_names: set[str],
):
    st.markdown("---")
    st.subheader("Debug Details")

    st.markdown("### Task metadata")
    st.write(f"**Task ID:** {task.get('id', 'N/A')}")
    st.write(f"**Prompt:** {task.get('prompt', 'N/A')}")

    _render_execution_policy_section(result.get("execution_policy") or {})

    repository_security = result.get("repository_security") or {}
    if repository_security:
        _render_security_section(repository_security)

    validation = result.get("validation") or {}
    if validation:
        _render_validation_section(validation)

    _render_repository_analysis_section(result)

    artifact_contract = result.get("artifact_contract") or {}
    if artifact_contract:
        _render_artifact_contract_section(artifact_contract)

    human_review = result.get("human_review") or {}
    if human_review:
        _render_human_review_section(human_review)

    plan = result.get("plan") or task.get("plan") or {}
    if plan:
        _render_plan_section(plan)

    infrastructure = result.get("infrastructure") or {}
    if infrastructure:
        _render_infrastructure_section(infrastructure, sensitive_variable_names)

    cicd = result.get("cicd") or {}
    if cicd:
        _render_cicd_section(cicd, sensitive_variable_names)

    with st.expander("Raw task JSON", expanded=False):
        st.json(_sanitize_task_for_display(task, sensitive_variable_names))


def _format_stack_label(repo_summary: dict) -> str:
    runtime = repo_summary.get("runtime") or {}
    languages = runtime.get("languages") or []
    frameworks = runtime.get("frameworks") or []
    project_type = repo_summary.get("project_type")

    parts = []
    if project_type:
        parts.append(str(project_type))
    if frameworks:
        parts.append(", ".join(str(item) for item in frameworks))
    if languages:
        parts.append(", ".join(str(item) for item in languages))
    return " | ".join(parts) if parts else "Unknown stack"


def _paths_by_status(
    artifact_contract: dict,
    *,
    groups: set[str],
    statuses: set[str],
) -> list[str]:
    return sorted(
        {
            item["path"]
            for item in (artifact_contract.get("artifact_statuses") or [])
            if item.get("group") in groups and item.get("status") in statuses
        }
    )


def _render_execution_policy_section(
    execution_policy: dict,
    *,
    title: str = "Execution Policy",
):
    if not execution_policy:
        return

    st.subheader(title)

    if execution_policy.get("artifact_generation_only"):
        st.success("Artifact generation only")
    else:
        st.info("Execution policy available")

    rows = [
        {
            "Policy": key,
            "Value": "Yes" if bool(value) else "No",
        }
        for key, value in execution_policy.items()
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


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

    quality_issues = validation.get("quality_issues", [])
    if quality_issues:
        st.markdown("### Quality issues")
        for issue in quality_issues:
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


def _render_cicd_section(cicd: dict, sensitive_variable_names: set[str]):
    st.subheader("CI/CD Artifacts")

    summary = cicd.get("summary")
    if summary:
        st.info(summary)

    readiness_summary = cicd.get("readiness_summary")
    if readiness_summary:
        st.caption(readiness_summary)

    notes = cicd.get("notes") or []
    if notes:
        st.markdown("### Notes")
        for note in notes:
            st.write(f"- {note}")

    artifact_groups = cicd.get("artifact_groups") or {}
    artifact_statuses = cicd.get("artifact_statuses") or []
    validation = cicd.get("validation") or {}

    col1, col2, col3 = st.columns(3)
    col1.metric("CI/CD targets", len((artifact_groups.get("cicd") or [])))
    col2.metric(
        "Generated",
        len([item for item in artifact_statuses if item.get("group") == "cicd" and item.get("status") == "generated"]),
    )
    col3.metric("Validation", validation.get("status", "unknown"))

    cicd_group = artifact_groups.get("cicd") or []
    if cicd_group:
        st.markdown("### CI/CD artifact group")
        for artifact in cicd_group:
            st.write(f"- {artifact}")

    if artifact_statuses:
        st.markdown("### CI/CD artifact statuses")
        st.dataframe(
            [
                {
                    "Path": item.get("path", ""),
                    "Status": item.get("status", ""),
                    "Group": item.get("group", ""),
                    "Requested": "Yes" if item.get("requested") else "No",
                    "Generated": "Yes" if item.get("generated") else "No",
                    "Source": item.get("source", ""),
                }
                for item in artifact_statuses
                if item.get("group") == "cicd"
            ],
            use_container_width=True,
            hide_index=True,
        )

    if validation:
        st.markdown("### CI/CD validation")
        if validation.get("status") == "valid":
            st.success("CI/CD contract valid")
        elif validation.get("status") == "partial":
            st.warning("CI/CD contract partial")
        else:
            st.info(f"CI/CD contract status: {validation.get('status', 'unknown')}")

        issues = validation.get("issues") or []
        warnings = validation.get("warnings") or []
        if issues:
            for issue in issues:
                st.error(issue)
        if warnings:
            for warning in warnings:
                st.warning(warning)

    _render_execution_policy_section(
        cicd.get("execution_policy") or {},
        title="CI/CD Execution Policy",
    )

    artifacts = cicd.get("artifacts") or {}
    if artifacts:
        st.markdown("### CI/CD artifact contents")
        for artifact_name, artifact_content in artifacts.items():
            with st.expander(f"{artifact_name}", expanded=False):
                st.code(
                    _sanitize_artifact_content_for_display(
                        artifact_content,
                        sensitive_variable_names,
                    ),
                    language="yaml" if artifact_name.endswith((".yml", ".yaml")) else None,
                )

    _render_reused_cicd_viewers(cicd, key_prefix="debug")


def _render_reused_cicd_viewers(cicd: dict, *, key_prefix: str):
    artifact_entries = cicd.get("artifact_entries") or []
    reusable_entries = [
        item
        for item in artifact_entries
        if item.get("status") in {"reused", "detected"} and item.get("view_url")
    ]
    if not reusable_entries:
        return

    st.markdown("### View existing CI/CD files")
    st.caption("Reused means the workflow already existed in the repository. You can inspect the original file content below.")

    github_token = ((st.session_state.get("form_data") or {}).get("github_token"))
    for entry in reusable_entries:
        path = entry.get("path", "")
        source = entry.get("source", "existing_repo")
        button_key = f"{key_prefix}::view_artifact::{path}"
        if st.button(f"View file: {path}", key=button_key):
            try:
                payload = view_artifact_file(
                    entry["view_url"],
                    github_token=github_token,
                )
                st.session_state[f"{button_key}::payload"] = payload
            except Exception as exc:
                st.error(f"Unable to load {path}: {exc}")

        payload = st.session_state.get(f"{button_key}::payload")
        if payload:
            with st.expander(f"{path} ({source})", expanded=False):
                st.code(payload.get("content", ""), language="yaml")


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


def _render_artifact_contract_section(artifact_contract: dict):
    if not artifact_contract:
        return

    st.subheader("Artifact Contract")

    artifact_groups = artifact_contract.get("artifact_groups") or {}
    requested_artifacts = artifact_contract.get("requested_artifacts") or []
    generated_artifacts = artifact_contract.get("generated_artifacts") or []

    col1, col2, col3 = st.columns(3)
    col1.metric("Requested", len(requested_artifacts))
    col2.metric("Generated", len(generated_artifacts))
    col3.metric("CI/CD group", len((artifact_groups.get("cicd") or [])))

    if artifact_groups:
        st.markdown("### Artifact groups")
        group_rows = [
            {"Group": group_name, "Artifacts": len(paths), "Paths": ", ".join(paths)}
            for group_name, paths in artifact_groups.items()
        ]
        st.dataframe(group_rows, use_container_width=True, hide_index=True)

    with st.expander("Artifact contract details", expanded=False):
        st.json(artifact_contract)


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
