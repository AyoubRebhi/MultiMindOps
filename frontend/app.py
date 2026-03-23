import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="DevSecOps AI Platform", layout="wide")
st.title("DevSecOps AI Platform - Sprint 2 Prototype")

if "task_response" not in st.session_state:
    st.session_state.task_response = None

prompt = st.text_area(
    "Décris la tâche DevSecOps à exécuter",
    placeholder="Ex: Déployer une API FastAPI avec Docker, Kubernetes, CI/CD sécurisé et monitoring",
    height=150,
)

if st.button("Lancer la tâche"):
    if prompt.strip():
        with st.status("Exécution des agents...", expanded=True) as status:
            st.write("Création de la tâche...")
            try:
                response = requests.post(
                    f"{API_BASE}/tasks/",
                    json={"prompt": prompt},
                    timeout=(10, 300),  # (connection timeout, read timeout)
                )

                if response.status_code == 200:
                    st.session_state.task_response = response.json()
                    st.write("Planner Agent terminé")
                    st.write("Infrastructure Agent terminé")
                    status.update(label="Workflow terminé", state="complete")
                else:
                    st.error(f"Erreur: {response.status_code} - {response.text}")
                    status.update(label="Erreur", state="error")
            except requests.exceptions.Timeout:
                st.error("⏱️ Le traitement prend trop longtemps. Vérifiez que le backend est en cours d'exécution et disposant suffisamment de ressources.")
                status.update(label="Timeout", state="error")
            except requests.exceptions.ConnectionError:
                st.error("❌ Impossible de connexion au backend. Assurez-vous que le serveur FastAPI est en cours d'exécution sur http://localhost:8000")
                status.update(label="Erreur de connexion", state="error")
            except Exception as e:
                st.error(f"❌ Erreur: {str(e)}")
                status.update(label="Erreur", state="error")

if st.session_state.task_response:
    task = st.session_state.task_response

    st.subheader("Résultat")
    st.json(task)

    st.subheader("Logs")
    for log in task.get("logs", []):
        st.write(f"- **{log['step']}**: {log['message']}")

    if task.get("plan"):
        st.subheader("Plan généré")
        st.json(task["plan"])

    if task.get("result"):
        st.subheader("Résultat orchestrateur")
        st.json(task["result"])