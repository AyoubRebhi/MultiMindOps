import streamlit as st


def render_repository_input():
    st.subheader("Nouvelle tache")

    prompt = st.text_area(
        "Task",
        placeholder="Ex: Generer une infrastructure Docker/Kubernetes securisee pour ce projet",
        height=150,
    )

    repo_url = st.text_input(
        "GitHub Repository URL (optionnel)",
        placeholder="https://github.com/owner/repository",
    )

    repository_visibility = st.radio(
        "Repository visibility",
        options=["public", "private"],
        index=0,
        horizontal=True,
    )

    github_token = None
    if repository_visibility == "private":
        github_token = st.text_input(
            "GitHub Personal Access Token",
            type="password",
            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx",
            help="Ce token est utilise uniquement pour cloner le depot prive. Il n'est pas stocke.",
        )

    submitted = st.button("Lancer les agents")

    return prompt, repo_url.strip() or None, repository_visibility, github_token, submitted
