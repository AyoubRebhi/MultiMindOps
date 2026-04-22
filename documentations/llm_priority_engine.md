# LLM Priority Engine — GLM-5.1 Context Analysis

## Architecture

3-stage pipeline pour transformer un repo en contexte ciblé:

### 1️⃣ QuickScannerService (sans LLM)
- **Entrée**: Chemin du repo
- **Fonction**: Walk directory tree (4 niveaux max), détecte signal files
- **Sortie**: JSON compact (~1KB)
  - root_files, top_level_dirs
  - signal_files (package.json, Dockerfile, requirements.txt, etc.)
  - languages_hinted, size_category
  - hints: is_monorepo, has_docker, has_ci_cd, has_kubernetes, has_terraform

### 2️⃣ LLMPriorityEngine (GLM-5.1:cloud)
- **Modèle**: GLM-5.1 via Ollama (OpenAI-compatible API)
- **Température**: 0.1 (déterministe)
- **Max tokens**: 1500
- **Système prompt**: DevSecOps expert rules
- **Entrée**: QuickScan payload
- **Sortie**: JSON structuré
  ```json
  {
    "critical_files": [
      {"path": "...", "priority": 1, "reason": "...", "category": "entrypoint"}
    ],
    "architecture_hint": "multi-service monorepo...",
    "primary_stack": ["Python", "FastAPI", "Docker"]
  }
  ```
- **Fallback**: Heuristique statique if GLM fails

### 3️⃣ TargetedRepositoryParser (sans LLM)
- **Entrée**: PriorityResult (fichiers classés)
- **Fonction**: Lit 5-20 fichiers uniquement (max 4000 chars/fichier)
- **Sortie**: Contexte riche ciblé
  - key_files_content: {path → snippet}
  - file_relationships: croix-références
  - critical_sections: base images, ports, env vars
  - architecture_summary: texte résumé

## Impact vs Ancien Système

| Métrique | Avant (heuristique) | Après (GLM) |
|---|---|---|
| Fichiers scannés | 250+ | 5-20 |
| Volume contexte | ~100KB | ~20KB |
| Détection monorepo | Heuristiques | LLM intelligent |
| Fallback | Aucun | Heuristique garantie |

## Cas d'Utilisation

Monorepo FastAPI+React+Terraform (2000 fichiers):
1. QuickScan → détecte: Python, JS, Terraform, 2000 fichiers
2. GLM note: backend/main.py, frontend/package.json, requirements.txt, terraform/main.tf, .github/workflows/ci.yml
3. TargetedParser lit ces 5 fichiers → contexte parsé

## Rôle Exact de GLM-5.1

**Input**: Résumé léger du repo (structure, pas contenu)
**Task**: Classer par priorité DevSecOps: entrypoints → deps → infra → ci/cd → config
**Output**: Ranked list 5-20 fichiers + architecture hint
**Fallback**: Hardcoded heuristic priorité_map si LLM timeout/error

## Scoring Heuristique (Fallback)

Priority → Category
- 1 → entrypoint (main.py, app.js, etc.)
- 2 → dependency (requirements.txt, package.json)
- 3 → infra (Dockerfile, terraform, k8s)
- 3 → ci_cd (.github/workflows)
- 4 → docs (README.md)
- 5 → config (.env.example)
