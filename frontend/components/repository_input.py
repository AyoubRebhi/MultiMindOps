import streamlit as st


def render_repository_input():
    st.subheader("Nouvelle tâche")

    prompt = st.text_area(
        "Task",
        placeholder="Ex: Générer une infrastructure Docker/Kubernetes sécurisée pour ce projet",
        height=150,
    )

    repo_url = st.text_input(
        "GitHub Repository URL (optionnel)",
        placeholder="https://github.com/owner/repository",
    )

    submitted = st.button("Lancer les agents")

    return prompt, repo_url.strip() or None, submitted