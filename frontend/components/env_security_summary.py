import streamlit as st


def render_env_security_summary(
    *,
    env_files: list[dict] | None,
    sanitized_env_context: dict | None,
    analysis_metadata: dict | None = None,
) -> None:
    env_files = env_files or []
    sanitized_env_context = sanitized_env_context or {}
    analysis_metadata = analysis_metadata or {}

    env_detected = bool(
        sanitized_env_context.get("env_detected")
        or env_files
        or analysis_metadata.get("env_detected")
    )
    env_fingerprint = sanitized_env_context.get("env_fingerprint") or analysis_metadata.get(
        "env_fingerprint"
    )
    env_source = sanitized_env_context.get("source") or "repository"
    variables = sanitized_env_context.get("variables") or []

    st.subheader("Secure .env Summary")

    if not env_detected:
        st.info("No environment file detected.")
        st.caption("The interface only shows safe metadata when environment files are present.")
        return

    total_variables = len(variables)
    sensitive_variables = sum(1 for item in variables if item.get("is_sensitive"))
    variables_with_value = sum(1 for item in variables if item.get("has_value"))
    used_for_generation = sum(1 for item in variables if item.get("used_for_generation"))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(".env files", len(env_files) or int(analysis_metadata.get("env_file_count") or 0))
    col2.metric("Variables", total_variables)
    col3.metric("Sensitive", sensitive_variables)
    col4.metric("With value", variables_with_value)

    status_labels = [
        "Detected",
        "Sanitized",
        "Hashed" if env_fingerprint else "Hash pending",
        "Safe for generation",
    ]
    st.caption(f"Source: {env_source}")
    st.caption(" | ".join(status_labels))
    st.caption("Secret values are never displayed. Only sanitized metadata is shown.")
    st.caption("Sensitive values are hashed for traceability and excluded from generation prompts.")

    file_rows = []
    for item in env_files:
        file_rows.append(
            {
                "Path": item.get("path", "unknown"),
                "Source": item.get("source", "repository"),
                "Hash": _truncate_hash(item.get("file_hash")),
                "Variables": item.get("variable_count", 0),
                "Sensitive": item.get("sensitive_variables_count", 0),
            }
        )

    if file_rows:
        st.markdown("### Environment files")
        st.dataframe(file_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Environment metadata is partial: file-level details are not available yet.")

    if env_fingerprint:
        st.caption(f"Environment fingerprint: `{_truncate_hash(env_fingerprint)}`")

    variable_rows = []
    for item in variables:
        variable_rows.append(
            {
                "Variable": item.get("name", "unknown"),
                "Category": item.get("category", "app"),
                "Sensitive": "Yes" if item.get("is_sensitive") else "No",
                "Has value": "Yes" if item.get("has_value") else "No",
                "Source": item.get("source_file", "unknown"),
                "Origin": item.get("env_source", env_source),
                "Used for generation": "Yes" if item.get("used_for_generation") else "No",
                "Sanitized value": _safe_sanitized_value(item),
                "Value hash": _truncate_hash(item.get("value_hash")),
            }
        )

    if variable_rows:
        st.markdown("### Sanitized variables")
        st.dataframe(variable_rows, use_container_width=True, hide_index=True)
    else:
        st.warning("Environment files were detected, but no sanitized variable metadata is available.")

    if used_for_generation != total_variables and total_variables:
        st.caption(
            f"{used_for_generation}/{total_variables} variables are currently marked safe for generation guidance."
        )


def _safe_sanitized_value(item: dict) -> str:
    if item.get("is_sensitive"):
        return "Hidden"
    value = item.get("sanitized_value")
    if value in (None, ""):
        return ""
    return str(value)


def _truncate_hash(value: str | None) -> str:
    if not value:
        return ""
    return f"{value[:12]}..."
