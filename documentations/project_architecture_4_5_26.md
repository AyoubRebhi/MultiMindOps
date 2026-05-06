# Analyse Architecturale Complète — Plateforme DevSecOps IA Multi-Agents

**Document** : Analyse technique et académique (niveau PFE)  
**Date** : 04 mai 2026  
**Auteur** : Ayoub Rebhi  
**Projet** : DevSecOps AI Platform — Génération autonome d'Infrastructure-as-Code par agents IA

---

## Table des matières

1. [Introduction](#1-introduction)
2. [Problématique](#2-problématique)
3. [Architecture globale](#3-architecture-globale)
4. [Description des composants](#4-description-des-composants)
5. [Workflow d'exécution](#5-workflow-dexécution)
6. [Défis techniques](#6-défis-techniques)
7. [Solution proposée](#7-solution-proposée)
8. [Valeur ajoutée](#8-valeur-ajoutée)
9. [Conclusion](#9-conclusion)

---

## 1. Introduction

La transformation numérique des organisations modernes repose sur la capacité à déployer des infrastructures cloud robustes, sécurisées et évolutives dans des délais toujours plus courts. Cette exigence confronte les équipes d'ingénierie à une double contrainte : la maîtrise d'un écosystème technique vaste (Terraform, Kubernetes, Docker, CI/CD, AWS, sécurité applicative) et la répétabilité des processus dans un contexte de changement continu.

Le présent projet constitue une **plateforme DevSecOps pilotée par l'intelligence artificielle**, conçue pour automatiser la génération d'artefacts d'infrastructure à partir d'une simple description textuelle (prompt) ou d'une URL de dépôt GitHub. La solution intègre une architecture multi-agents orchestrée par LangGraph, une couche de récupération de connaissances hybride (RAG + MCP), et plusieurs fournisseurs LLM avec stratégies de repli, permettant de produire de façon autonome des fichiers Terraform HCL, des manifestes Kubernetes, des Dockerfiles et des pipelines CI/CD GitHub Actions — le tout avec validation humaine optionnelle et estimation de coût AWS.

Ce document en constitue l'analyse architecturale complète, structurée pour un contexte académique de niveau Projet de Fin d'Études (PFE), avec la rigueur technique requise pour valider les choix de conception.

---

## 2. Problématique

### 2.1 Le contexte : la complexité du DevSecOps moderne

L'ingénierie cloud moderne repose sur un empilement de technologies interdépendantes : un projet fullstack typique nécessite la maîtrise simultanée de l'Infrastructure-as-Code (Terraform), de l'orchestration de conteneurs (Kubernetes), de la conteneurisation (Docker), des pipelines CI/CD (GitHub Actions), de la gestion des secrets, du scanning de sécurité et de la modélisation des coûts cloud. Ce cycle de vie, désigné sous le terme DevSecOps, intègre la sécurité dès la conception plutôt qu'en fin de chaîne.

Pour une équipe de développement, la mise en place de cette infrastructure représente :

- **Plusieurs jours-homme** de travail répétitif et à faible valeur ajoutée
- Un **risque d'erreur élevé** (mauvaises pratiques Terraform, fichiers YAML invalides, secrets exposés)
- Une **dépendance aux experts** : les équipes sans ingénieur DevOps dédié sont bloquées
- Un **manque de cohérence** entre les artefacts produits par différents développeurs ou équipes
- Une **absence de vision coût** : les équipes déploient sans mesurer l'impact financier en amont

### 2.2 Limitations des approches existantes

**1. Outils de génération statiques (cookiecutters, Yeoman, scripts Bash)**  
Ces approches produisent des templates figés, non adaptés au projet cible. Ils ne comprennent pas le contexte applicatif (type d'application, scalabilité requise, dépendances) et génèrent des artefacts génériques qui nécessitent une personnalisation manuelle importante. Ils ne savent pas distinguer une application monolithique stateful d'une architecture microservices sans état.

**2. Assistants IA généralistes (ChatGPT, Copilot)**  
Ces modèles génèrent du code sur instruction, mais ils souffrent de plusieurs limitations critiques dans un contexte DevSecOps : absence de cohérence inter-artefacts (le fichier Terraform ne sait rien du Dockerfile), hallucinations sur les API propriétaires (ressources AWS inexistantes, arguments mal nommés), incapacité à raisonner sur les coûts, et absence de boucle de validation sur le code généré.

**3. Plateformes Infrastructure-as-Code managées (Pulumi Automation, CDK)**  
Ces outils offrent une abstraction programmatique, mais restent réservés aux équipes expertes. Ils ne résolvent pas le problème de la génération à partir d'un besoin métier exprimé en langage naturel.

**4. Solutions de génération LLM naïves (prompt unique → code)**  
Un appel LLM unique, sans contexte enrichi ni validation, produit des résultats non fiables pour du code d'infrastructure. Le taux d'erreur est trop élevé pour un usage en production : API mal utilisées, configurations réseau incomplètes, valeurs hardcodées, secrets exposés.

### 2.3 Pourquoi un système multi-agents avec RAG et MCP ?

L'inefficacité des approches précédentes tient à une cause commune : **l'absence d'un raisonnement structuré et contextuel**. Résoudre ce problème requiert :

1. **Décomposition des responsabilités** : chaque domaine (planification, Terraform, Kubernetes, CI/CD, coûts) nécessite une expertise spécialisée et un contexte différent. Un agent unique ne peut pas exceller sur tous ces fronts simultanément.

2. **Connaissance structurée à la génération** : le modèle de langage doit être augmenté de schémas de ressources AWS précis, de patterns DevSecOps éprouvés, et de templates valides — c'est le rôle du RAG et du MCP.

3. **Validation et raffinement itératif** : la génération de code d'infrastructure ne peut pas être un acte unique ; elle nécessite des boucles d'évaluation (syntaxe, sécurité, cohérence) avec possibilité de correction automatique.

4. **Orchestration déterministe** : les artefacts produits doivent être cohérents entre eux (le Kubernetes manifest doit référencer les outputs Terraform, le pipeline CI/CD doit connaître le registre ECR). Cette dépendance inter-artefacts requiert une orchestration explicite.

---

## 3. Architecture globale

### 3.1 Vue d'ensemble

La plateforme s'articule autour de cinq couches fonctionnelles qui communiquent de manière orchestrée :

```
┌─────────────────────────────────────────────────────────────────────┐
│                      INTERFACE UTILISATEUR                          │
│          React TypeScript — Workflow 8 étapes — Port 3000           │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP (REST API)
┌───────────────────────────▼─────────────────────────────────────────┐
│                     BACKEND FASTAPI                                 │
│    Routes : /tasks, /artifacts, /evaluation — Port 8000             │
│    TaskService (PostgreSQL) — OrchestratorAgent (LangGraph)         │
└──────┬──────────────────────┬────────────────────────────┬──────────┘
       │                      │                            │
┌──────▼──────┐    ┌──────────▼──────────┐    ┌───────────▼──────────┐
│   AGENTS    │    │   COUCHE KNOWLEDGE  │    │   FOURNISSEURS LLM   │
│             │    │                     │    │                       │
│ Orchestrator│    │ HybridRAGService     │    │ GitHub Models (Prim.)│
│ Planner     │    │  ├─ MCPClient       │    │ Groq (Secondaire)    │
│ Terraform   │    │  │   (schemas HCL)  │    │ Ollama (local)       │
│ Kubernetes  │◄───┤  └─ QdrantService   │    │ LightningAI (legacy) │
│ Infrastructure   │      (corpus 768d)  │    │                       │
│ CICD        │    │                     │    │  LLMRouter            │
│ CostEstim.  │    │ EmbeddingService    │    │  (fallback chain)     │
│ MultiPlan   │    │  (nomic-embed-text) │    └───────────────────────┘
│ Codebase    │    └─────────────────────┘
│ Analysis    │
└─────────────┘
       │
┌──────▼─────────────────────────────────────────────────────────────┐
│                    SERVICES D'INFRASTRUCTURE                        │
│                                                                     │
│  RepositoryParser  │  ApplicationProfiler  │  SecurityService       │
│  GitHubService     │  ArtifactContractSvc  │  CicdWorkflowBuilder   │
│  InfraContextMapper│  TemplateRetrieval    │  ValidationService     │
└────────────────────┴───────────────────────┴────────────────────────┘
       │
┌──────▼─────────────────────────────────────────────────────────────┐
│                    SERVICES EXTERNES / PERSISTANCE                  │
│                                                                     │
│  PostgreSQL (tâches, cache analyses)    Qdrant (vecteurs 768d)     │
│  GitHub API (repos, tokens)             Ollama (embeddings local)  │
│  MCP Server (schémas Terraform/K8s)                                │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 Flux de données principal

```
Utilisateur
    │
    ▼ POST /tasks/plan-preview {prompt, repo_url, .env}
FastAPI TaskService
    │
    ▼ Créer tâche PostgreSQL + lancer OrchestratorAgent
LangGraph StateGraph
    │
    ├─▶ [Phase 1] CodebaseAnalysisAgent
    │       ├── GitHubService → clone + parse dépôt
    │       ├── RepositorySecurityService → gate sécurité
    │       ├── ApplicationProfilerService → profil applicatif
    │       └── Chunks → stockés dans l'état LangGraph
    │
    ├─▶ [Phase 2] PlannerAgent
    │       ├── Compression du contexte applicatif
    │       ├── Appel LLM (Groq/GitHub Models)
    │       ├── Normalisation des artefacts
    │       └── infrastructure_blueprint (compute, DB, réseau, scaling)
    │
    ├─▶ [Phase 3] CostEstimationAgent
    │       ├── Modèle de prix AWS déterministe
    │       ├── Calcul mensuel par composant
    │       └── Recommandations d'optimisation
    │
    ├─▶ [Phase 4] MultiPlanAgent
    │       ├── Variante low_cost (types dégradés, mono-AZ)
    │       ├── Variante balanced (blueprint original)
    │       └── Variante high_performance (multi-AZ, répliques)
    │
    ⏸ → Retour utilisateur (preview plan + coût + sécurité)
    │
    ▼ POST /tasks/validate-plan {decision: "approved"}
    │
    ├─▶ [Phase 5] TerraformAgent
    │       ├── HybridRAG (MCP schemas + Qdrant corpus)
    │       ├── Boucle ReAct (max 3 itérations)
    │       ├── Génération HCL splitté (providers, vpc, eks, outputs...)
    │       └── terraform_outputs (contrat → KubernetesAgent)
    │
    ├─▶ [Phase 6] KubernetesAgent
    │       ├── RAG Qdrant (doc_type=k8s)
    │       ├── Injection des références ${terraform_output:...}
    │       ├── Boucle ReAct (max 2 itérations)
    │       └── deployment.yaml + service.yaml
    │
    ├─▶ [Phase 7] InfrastructureAgent (Docker)
    │       ├── RAG Qdrant (doc_type=docker)
    │       ├── Artefacts fallback déterministes
    │       ├── Boucle ReAct (max 3 itérations)
    │       └── Dockerfile + .dockerignore + docker-compose + .env.example
    │
    ├─▶ [Phase 8] ValidationPhase
    │       └── ArtifactQualityValidator → missing_artifacts, quality_issues
    │
    ├─▶ [Phase 9] CICDAgent
    │       ├── Handoff context normalisé
    │       ├── CicdWorkflowBuilderService
    │       └── .github/workflows/ci-cd.yml
    │
    └─▶ [Phase 10] Finalise
            └── Agrégation résultat → retour API
```

---

## 4. Description des composants

### 4.1 OrchestratorAgent — Chef d'orchestre LangGraph

**Fichier** : [backend/app/agents/orchestrator_agent.py](backend/app/agents/orchestrator_agent.py)  
**Technologie** : LangGraph `StateGraph`, 1541 lignes

L'OrchestratorAgent est le composant central du système. Il définit un graphe d'état dirigé avec **14 nœuds** et des arêtes conditionnelles dynamiques. Son état (`OrchestratorState`) est un dictionnaire typé qui traverse l'ensemble du graphe, s'enrichissant à chaque phase :

```
OrchestratorState {
  prompt, repo_url, github_token,          # Entrées utilisateur
  status, logs, error_message,             # Métadonnées d'exécution
  repository_security, repository_analysis,# Résultats analyse repo
  application_profile,                     # Profil applicatif détecté
  agent_context,                           # Contextes planner/infra
  plan, plans, selected_plan,              # Résultats planification
  cost_estimation, terraform_outputs,      # Coûts + contrat Terraform
  infra, cicd, validation, result,         # Artefacts générés
  requires_user_input, auto_mode           # Contrôle du flux
}
```

L'orchestrateur expose plusieurs **points d'entrée** selon le mode d'interaction :
- `run()` : exécution complète en mode automatique (phases 1 à 14)
- `run_plan_preview()` : phases 1 à 5, pause pour validation humaine
- `run_until_plan_selection()` : phases 1 à 7, pause pour sélection de variante
- `resume_with_human_decision()` : reprise après décision humaine (approbation/rejet/modification)
- `resume_with_plan()` : reprise après sélection d'une variante de plan

Les **fonctions de routage conditionnel** (`_route_*`) implémentent la logique de décision entre les nœuds :
- Si la sécurité du dépôt est bloquante → finalisation immédiate
- Si le plan est vide → finalisation sans génération
- Si le mode automatique est activé → sélection automatique de la variante "balanced"
- Si tous les artefacts requis sont générés → passage à la phase CI/CD

### 4.2 PlannerAgent — Stratège d'infrastructure

**Fichier** : [backend/app/agents/planner_agent.py](backend/app/agents/planner_agent.py)

Le PlannerAgent a la responsabilité de transformer le profil applicatif détecté (type d'application, scalabilité, stateful/stateless, services détectés) en un **plan d'exécution structuré** avec une liste d'artefacts requis et un `infrastructure_blueprint` déterministe.

Le blueprint est calculé par une **table de correspondance** selon trois axes :
- **Scalabilité élevée + microservices** → EKS, Redis, RDS Multi-AZ
- **Monolithe stateful** → ECS, ALB, RDS, EBS
- **Stateless** → Lambda, API Gateway, DynamoDB/Aurora Serverless

Cette approche déterministe garantit la cohérence entre le profil détecté et l'architecture proposée, sans dépendre d'une hallucination LLM sur le choix de compute.

Le plan produit enforce un **ordre infrastructure-first** : Terraform → Docker → Kubernetes → GitHub Actions.

### 4.3 TerraformAgent — Générateur HCL avec RAG hybride

**Fichier** : [backend/app/agents/terraform_agent.py](backend/app/agents/terraform_agent.py)

C'est l'agent le plus critique du système. Il génère les fichiers Terraform HCL en utilisant le `HybridRAGService` pour enrichir le prompt LLM avec des schémas de ressources AWS précis, puis raffine le résultat dans une boucle ReAct jusqu'à satisfaction des critères de qualité.

**Sortie** : jusqu'à 7 fichiers HCL distincts :
- `terraform/providers.tf` : configuration du provider AWS avec version
- `terraform/backend.tf` : remote state S3 + DynamoDB locking
- `terraform/vpc.tf` : VPC, subnets publics/privés, NAT Gateway
- `terraform/eks.tf` ou `terraform/ecs.tf` : cluster de compute
- `terraform/variables.tf` : déclaration des variables
- `terraform/terraform.tfvars` : valeurs des variables
- `terraform/outputs.tf` : outputs exportés (endpoint, ARN, etc.)

Le **contrat `terraform_outputs`** est une innovation clé : il standardise les références entre agents sous la forme `${terraform_output:cluster_endpoint}`, permettant au KubernetesAgent d'utiliser les valeurs sans les hardcoder.

**Évaluateur de qualité** (boucle ReAct) :
- Présence obligatoire de `outputs.tf` avec `cluster_endpoint`, `cluster_name`, `load_balancer_dns`, `ecr_repository_url`
- Présence de `providers.tf` et `vpc.tf`
- Présence de `eks.tf` OU `ecs.tf` (sauf mode serverless)
- Absence de contamination YAML (détection de `apiVersion:`, `kind:` dans le HCL)

### 4.4 KubernetesAgent — Générateur de manifestes contextuels

**Fichier** : [backend/app/agents/kubernetes_agent.py](backend/app/agents/kubernetes_agent.py)

Le KubernetesAgent consomme le contrat `terraform_outputs` et génère des manifestes Kubernetes (`deployment.yaml`, `service.yaml`) qui **référencent dynamiquement** les valeurs Terraform plutôt que de les hardcoder. Cette approche résout le problème classique de cohérence entre IaC et orchestration de conteneurs.

Exemple de référence dans le manifest généré :
```yaml
image: ${terraform_output:ecr_repository_url}:latest
```

L'évaluateur de la boucle ReAct vérifie :
- Syntaxe YAML valide
- Présence de `apiVersion`, `kind: Deployment`, et d'un Service
- Utilisation des références `${terraform_output:...}` pour l'URL du registre
- Absence d'identifiants AWS hardcodés (account ID, cluster ARN)

### 4.5 InfrastructureAgent — Générateur d'artefacts Docker

**Fichier** : [backend/app/agents/infrastructure_agent.py](backend/app/agents/infrastructure_agent.py)

Responsable de la couche de conteneurisation, cet agent génère quatre artefacts :
- `Dockerfile` : adapté au langage et au framework détectés
- `.dockerignore` : exclusions pertinentes
- `docker-compose.yml` : composition locale pour développement
- `.env.example` : modèle de variables d'environnement (sans valeurs sensibles)

Il implémente une **stratégie de fallback à deux niveaux** : si le LLM produit un artefact invalide après la boucle ReAct, un fallback déterministe construit à partir du contexte applicatif est utilisé à la place. Ce choix est tracé dans le `validation_summary`.

### 4.6 CodebaseAnalysisAgent — Analyseur de dépôt avec gate sécurité

**Fichier** : [backend/app/agents/codebase_analysis_agent.py](backend/app/agents/codebase_analysis_agent.py)

Ce composant effectue une analyse complète du dépôt GitHub fourni :
1. **Gate de sécurité** : détection de patterns malveillants (crypto-miners, backdoors, exfiltration de données) via `RepositorySecurityService`
2. **Profiling applicatif** : détection du type d'application, des frameworks, des langages, du niveau de scalabilité, de la statefulness
3. **Cache intelligent** : comparaison commit SHA + empreinte `.env` pour éviter les ré-analyses inutiles
4. **Production de chunks** : découpage du code source en segments pour injection RAG

Le `application_profile` produit est la donnée la plus critique du workflow : il conditionne l'entièreté de l'architecture générée en aval.

### 4.7 CostEstimationAgent — Modèle de coût AWS déterministe

**Fichier** : [backend/app/agents/cost_estimation_agent.py](backend/app/agents/cost_estimation_agent.py)

Calcule les coûts AWS mensuels à partir d'un modèle de prix statique intégré :

| Service | Tarif |
|---------|-------|
| EC2 t3.medium | 0.0416 $/h |
| EKS control plane | 0.10 $/h (73 $/mois) |
| RDS Multi-AZ | 2× le coût instance |
| Lambda | 0.20 $ / million requêtes |
| S3 | 0.023 $/Go/mois |
| ALB | 0.008 $/h + LCU |

La décomposition produit un profil (`startup`, `small_production`, `medium_production`, `enterprise`) et des recommandations d'optimisation générées soit par LLM, soit par règles déterministes en cas d'échec.

### 4.8 MultiPlanAgent — Générateur de variantes de plan

**Fichier** : [backend/app/agents/multi_plan_agent.py](backend/app/agents/multi_plan_agent.py)

Sans appel LLM, ce composant dérive **trois variantes du blueprint** en appliquant des tables de transition sur les types d'instances et la topologie réseau :

- **low_cost** : instances dégradées (ex. `t3.medium` → `t3.small`), mono-AZ, sans répliques de lecture
- **balanced** : blueprint original (coût de référence)
- **high_performance** : instances upgradées (ex. `m5.xlarge` → `m5.2xlarge`), Multi-AZ, répliques, caching

Chaque variante reçoit une estimation de coût recalculée et un score sur trois axes (cost_efficiency, scalability, reliability). La recommandation finale est déterminée par analyse des mots-clés du prompt utilisateur.

### 4.9 CICDAgent — Constructeur de pipelines GitHub Actions

**Fichier** : [backend/app/agents/cicd_agent.py](backend/app/agents/cicd_agent.py)

Dernière phase de génération, cet agent construit les workflows GitHub Actions adaptés au projet. Il reçoit un `handoff_context` normalisé (runtime détecté, chemins d'artefacts, informations de registre) et utilise le `CicdWorkflowBuilderService` pour assembler les étapes (build, test, push ECR, deploy EKS/ECS).

### 4.10 Couche RAG hybride (HybridRAGService + MCPClient)

**Fichiers** :  
- [backend/app/services/rag/hybrid_rag_service.py](backend/app/services/rag/hybrid_rag_service.py)  
- [backend/app/services/mcp_client.py](backend/app/services/mcp_client.py)

La couche de récupération de connaissances est la pièce maîtresse de la robustesse du système. Elle fusionne deux sources complémentaires :

**MCP (Model Context Protocol)** — précision schématique :
Le serveur MCP expose des ressources structurées via le protocole standardisé MCP :
- `aws://terraform/resource/{resource_name}` : schéma HCL officiel d'une ressource AWS avec exemple
- `aws://kubernetes/template/{template_name}` : templates K8s annotés
- `aws://best-practices/{category}` : pratiques AWS Well-Architected
- Outils : `validate_terraform_code`, `suggest_terraform_fix`, `get_architecture_template`

Le `MCPClient` fonctionne en mode direct (chargement JSON, zéro overhead subprocess) avec un cache TTL de 24 heures.

**Qdrant** — rappel sémantique :
Une collection vectorielle `devsecops_knowledge` indexe un corpus DevSecOps avec des vecteurs de 768 dimensions (`nomic-embed-text:v1.5` via Ollama). La recherche hybride combine similarité cosinus et boost par mots-clés, avec un seuil de score minimum de 0.28. Les chunks sont filtrables par `doc_type` (terraform, k8s, docker, cicd, security, cloud).

**Fusion** :
```
Résultat hybride = [MCP resources (priorité)] ++ [Qdrant results (complémentarité)]
                   → déduplication par contenu
                   → formatage pour injection LLM
```

### 4.11 LLMRouter — Chaîne de repli fournisseurs

**Fichier** : [backend/app/services/llm/llm_router.py](backend/app/services/llm/llm_router.py)

```
GitHub Models (meta/llama-3-70b-instruct, Azure-backed)
    │  Timeout / RateLimitError / réponse vide ?
    ▼
Groq (llama3-8b-8192, 2 tentatives)
    │  Toutes les clés épuisées ?
    ▼
Erreur propagée à l'agent (boucle ReAct → tentative suivante)
```

Le `LLMService` (Groq) gère jusqu'à **6 clés API en rotation** (`GROQ_API_KEY` à `GROQ_API_KEY_6`), avec :
- Délai minimal de 2 secondes entre appels sur une même clé
- Respect de l'en-tête `Retry-After` en cas de rate limit
- Retry exponentiel sur erreurs réseau transitoires (1s, 2s, 4s)

### 4.12 EnhancedBaseAgent — Boucle ReAct avec mémoire

**Fichier** : [backend/app/agents/base_agent.py](backend/app/agents/base_agent.py)

Tous les agents producteurs héritent de `EnhancedBaseAgent`, qui implémente la boucle **ReAct (Reasoning + Acting)** :

```
1. Vérification mémoire (cache SHA256 du prompt, confiance ≥ 0.7)
2. Appel LLM avec prompt système + prompt utilisateur
3. Évaluation par fonction domaine-spécifique
4. Si problèmes détectés : prompt de raffinement + nouvelle itération
5. Stockage en mémoire avec score de confiance
6. Retour de la meilleure réponse ou de la dernière en cas d'épuisement
```

Le score de confiance décroît à chaque itération : `1.0 - 0.15 × tentative`. La mémoire (`AgentMemory`) cache par hash SHA256 du prompt, avec éviction LRU et TTL optionnel.

---

## 5. Workflow d'exécution

### 5.1 Scénario de référence : génération à partir d'un dépôt GitHub

**Entrée utilisateur** :
```
Prompt : "Deploy a scalable FastAPI microservices application"
Repo URL : https://github.com/user/fastapi-microservices
Mode : interactive (avec validation humaine)
```

**Phase 1 — Analyse du dépôt** (CodebaseAnalysisAgent)
1. Clonage via GitHubService, extraction de l'arbre de fichiers
2. `RepositorySecurityService` : scan des patterns malveillants → statut `safe`
3. `ApplicationProfilerService` : détection FastAPI, Python, PostgreSQL, Redis → `microservices`, scalabilité `high`, `stateless`
4. Production de chunks indexés pour le contexte des agents suivants

**Phase 2 — Planification** (PlannerAgent)
1. Compression du profil : `{type: microservices, scalability: high, stateless: true, services: [postgres, redis]}`
2. Appel Groq : `llama3-8b-8192`
3. Normalisation : artefacts filtrés, ordre infrastructure-first imposé
4. Blueprint déterministe : **EKS** (microservices + scalabilité haute), RDS Multi-AZ, ElastiCache Redis

**Phase 3 — Estimation des coûts** (CostEstimationAgent)
```
Résultat :
  EKS control plane    :   73 $/mois
  EC2 m5.large × 3    :  315 $/mois
  RDS db.t3.medium    :   66 $/mois
  ElastiCache t3.micro:   24 $/mois
  ALB                 :   18 $/mois
  S3 + DT             :    8 $/mois
  ─────────────────────────────────
  TOTAL               :  504 $/mois  (profil: small_production)
```

**Phase 4 — Multi-plan** (MultiPlanAgent)
- low_cost : t3.small × 2, mono-AZ, sans cache → 187 $/mois
- balanced : m5.large × 3, Multi-AZ → 504 $/mois *(recommandé)*
- high_performance : m5.2xlarge × 5, Multi-AZ, répliques → 1 420 $/mois

**⏸ Pause — L'API retourne le plan à l'utilisateur**

**Phase 5 — Génération Terraform** (TerraformAgent, après approbation)
1. HybridRAG : récupération du schéma `aws_eks_cluster` via MCP + patterns EKS depuis Qdrant
2. Appel GitHub Models (meta/llama-3-70b-instruct), température 0.2
3. Itération 1 : évaluateur → manque `outputs.tf` → prompt de raffinement
4. Itération 2 : évaluateur → tous les critères satisfaits
5. Production : 7 fichiers HCL + contrat `terraform_outputs`

**Phase 6 — Génération Kubernetes** (KubernetesAgent)
1. RAG Qdrant filtré `doc_type=k8s` : top 5 résultats
2. Appel LLM avec références `${terraform_output:ecr_repository_url}` injectées
3. Itération 1 : évaluateur → all pass
4. Production : `deployment.yaml` + `service.yaml`

**Phase 7 — Génération Docker** (InfrastructureAgent)
1. RAG Qdrant filtré `doc_type=docker` : templates Python/FastAPI
2. Appel LLM : génération Dockerfile multi-stage, .dockerignore, docker-compose
3. Itération 1 : évaluateur → port exposé manquant → raffinement
4. Itération 2 : all pass
5. Production : 4 artefacts Docker

**Phase 8 — Validation** (ArtifactQualityValidator)
- Tous les artefacts requis présents → statut `complete`

**Phase 9 — CI/CD** (CICDAgent)
- Génération GitHub Actions : build → test → docker build/push ECR → deploy EKS
- Production : `.github/workflows/ci-cd.yml`

**Phase 10 — Finalisation**
- Agrégation de tous les artefacts dans le résultat final
- Mise à jour du statut de tâche dans PostgreSQL

**Résultat final** :
```
terraform/
  providers.tf, backend.tf, vpc.tf, eks.tf,
  variables.tf, terraform.tfvars, outputs.tf
kubernetes/
  deployment.yaml, service.yaml
Dockerfile, .dockerignore, docker-compose.yml, .env.example
.github/workflows/ci-cd.yml
```

---

## 6. Défis techniques

### 6.1 Génération de code d'infrastructure valide et cohérent

Le principal défi est que les LLMs, entraînés sur des corpus généraux, manquent de précision sur les API propriétaires AWS (noms d'arguments, valeurs requises, dépendances entre ressources). Une ressource Terraform mal formée peut sembler correcte syntaxiquement mais échouer à l'application (`terraform apply`) à cause d'un argument déprécié, d'une référence cyclique ou d'une permission IAM manquante.

**Complication supplémentaire** : la cohérence inter-fichiers. Le fichier `outputs.tf` doit exporter exactement les valeurs consommées par le manifest Kubernetes. Sans mécanisme de contrat explicite, les LLMs tendent à diverger entre les fichiers.

### 6.2 Hallucinations sur les ressources AWS

Les modèles de langage hallucinent régulièrement des arguments inexistants dans les ressources Terraform (ex. `aws_eks_cluster.enable_irsa` qui n'existe pas), des API Kubernetes dépréciées (`extensions/v1beta1`), ou des propriétés Docker invalides. Ces erreurs ne sont pas détectables à la lecture, uniquement à l'exécution.

### 6.3 Gestion d'un workflow multi-étapes avec état persistant

Un workflow de 14 phases avec des points de pause, des décisions humaines conditionnelles, des reprises depuis un état partiel et des routages dynamiques ne peut pas être implémenté avec une chaîne de traitement séquentielle simple. La moindre défaillance dans la gestion de l'état peut corrompre le contexte d'un agent en aval.

### 6.4 Disponibilité et limites des fournisseurs LLM

Les APIs LLM commerciales imposent des rate limits stricts (Groq : 30 req/min sur le plan gratuit), des quotas de tokens, et des indisponibilités ponctuelles. Un système de production ne peut pas s'appuyer sur un unique fournisseur sans stratégie de repli.

### 6.5 Maintien de la cohérence inter-agents

Chaque agent travaille en isolation relative, mais les artefacts qu'il produit doivent être compatibles avec ceux des agents précédents et suivants. Par exemple :
- Le Dockerfile doit exposer le même port que le Service Kubernetes
- Le manifest Kubernetes doit référencer le bon registre ECR
- Le pipeline CI/CD doit connaître le nom du cluster EKS

Sans mécanisme de contrat explicite, ces dépendances deviennent des sources de divergence.

### 6.6 Compatibilité Windows et encodage

L'exécution sur Windows (PowerShell) introduit des problèmes d'encodage pour les sorties LLM contenant des caractères Unicode ou des guillemets typographiques. L'API Groq peut retourner des caractères non-ASCII qui provoquent des erreurs `UnicodeDecodeError` dans le pipeline.

### 6.7 Performance du pipeline RAG sur des corpus DevSecOps

Les embeddings de code Terraform ou YAML avec un modèle généraliste (`nomic-embed-text`) peuvent produire des vecteurs de faible qualité si le corpus n'est pas bien structuré. Le seuil de score minimum (0.28) doit être calibré pour éviter à la fois les faux négatifs (bons exemples non récupérés) et les faux positifs (exemples non pertinents injectés).

---

## 7. Solution proposée

### 7.1 Architecture multi-agents spécialisés

La décomposition en agents spécialisés résout le problème de la généralisation forcée : chaque agent est conçu avec un prompt système dédié, une évaluation domaine-spécifique, et un contexte RAG filtré. Le TerraformAgent reçoit uniquement des schémas HCL ; le KubernetesAgent reçoit uniquement des templates YAML. Cette spécialisation améliore la qualité des sorties en réduisant le "bruit" dans le contexte LLM.

### 7.2 RAG hybride MCP + Qdrant

La combinaison MCP (précision schématique) + Qdrant (rappel sémantique) résout les deux faces du problème de la connaissance :

- **MCP** répond à "comment écrire exactement `aws_eks_cluster` en HCL ?" avec le schéma officiel de la ressource.
- **Qdrant** répond à "quels patterns utilise-t-on pour un cluster EKS production-grade ?" avec des exemples issus du corpus.

Cette dualité minimise les hallucinations tout en fournissant des patterns contextuels riches.

### 7.3 Boucle ReAct avec évaluation domaine-spécifique

Au lieu d'un appel LLM unique, le système itère :
1. Génération initiale
2. Évaluation structurée (critères précis, pas d'heuristiques générales)
3. Si critères non satisfaits : prompt de raffinement ciblé sur les problèmes détectés
4. Nouvelle génération (max 3 itérations)

Cette approche converge en 1-2 itérations dans la majorité des cas, avec un taux de satisfaction final proche de 100% sur les critères mesurables.

### 7.4 Contrat inter-agents (terraform_outputs)

Le mécanisme `terraform_outputs` introduit une abstraction de contrat entre TerraformAgent et KubernetesAgent. Les valeurs sont représentées par des références symboliques (`${terraform_output:cluster_endpoint}`) plutôt que des valeurs concrètes, ce qui :
- Garantit que les manifests Kubernetes restent valides même si les valeurs Terraform changent
- Élimine le hardcoding d'identifiants AWS dans le code versionné
- Permet la validation statique de la cohérence inter-artefacts

### 7.5 Chaîne de repli fournisseurs LLM

```
GitHub Models (Azure, modèle 70B) 
    → timeout/rate limit → Groq (llama3-8b-8192, clé 1)
    → rate limit → Groq (llama3-8b-8192, clé 2..6)
    → toutes épuisées → propagation d'erreur → retry boucle ReAct
```

La rotation de 6 clés Groq avec throttling par clé (2s minimum) permet de maintenir un débit continu même sous charge.

### 7.6 Profiling applicatif déterministe

L'`ApplicationProfilerService` détermine l'architecture cloud à partir de signaux mesurables dans le code (présence de `kubernetes/`, `docker-compose.yml`, détection de frameworks, nombre de services, patterns de scalabilité) plutôt que de déléguer cette décision au LLM. Cela garantit que le blueprint infrastructure est cohérent avec la réalité du projet analysé.

### 7.7 Fallbacks déterministes

Pour chaque artefact, si la génération LLM échoue après la boucle ReAct, un fallback construit à partir de templates paramétriques codés en dur est utilisé. Ce fallback, bien que moins riche, est garanti valide syntaxiquement et fonctionnellement. Le système trace le chemin utilisé (LLM ou fallback) dans les métadonnées de validation.

### 7.8 Encodage UTF-8 universel

Un patch d'encodage global est appliqué au démarrage de l'application (stdout/stderr reconfigurés en UTF-8, `PYTHONIOENCODING=utf-8`) pour garantir la compatibilité sur Windows avec les sorties LLM potentiellement non-ASCII.

---

## 8. Valeur ajoutée

### 8.1 Ce que le système n'est pas

Pour comprendre la valeur ajoutée, il est important de définir ce que le système **n'est pas** :

- **Ce n'est pas un template engine** : il ne copie pas des templates pré-définis ; il génère des artefacts adaptés au profil spécifique de chaque application.
- **Ce n'est pas un générateur Terraform générique** : il comprend le type d'application (monolithe, microservices, serverless) et choisit l'architecture AWS correspondante.
- **Ce n'est pas un chatbot** : il n'engage pas une conversation ouverte ; il exécute un workflow structuré avec validation, coûts et sécurité intégrés.
- **Ce n'est pas une solution one-shot** : il itère, évalue, raffine et adapte sa sortie à des critères de qualité mesurables.

### 8.2 Différenciation par rapport aux LLMs généralistes

| Dimension | ChatGPT / Copilot | Cette plateforme |
|-----------|------------------|-----------------|
| Cohérence inter-artefacts | Non garantie | Contrat terraform_outputs |
| Connaissance AWS précise | Hallucinations fréquentes | RAG hybride MCP + Qdrant |
| Validation du code généré | Aucune | Boucle ReAct + évaluateurs |
| Estimation des coûts | Approximative | Modèle déterministe AWS |
| Profiling applicatif | Manuel (utilisateur) | Automatique (CodebaseAnalysisAgent) |
| Sécurité intégrée | Optionnelle | Gate + scan intégrés |
| Variantes d'architecture | Aucune | 3 variantes (coût/performance) |
| Persistance et reprise | Aucune | PostgreSQL + LangGraph state |

### 8.3 Différenciation par rapport aux outils DevOps existants

| Dimension | Terraform CDK / Pulumi | Cette plateforme |
|-----------|----------------------|-----------------|
| Public cible | Experts DevOps | Développeurs sans expertise infra |
| Point d'entrée | Code programmatique | Prompt en langage naturel |
| Analyse de dépôt | Inexistante | Automatique (profil, sécurité) |
| Génération CI/CD | Manuelle | Automatique et cohérente |
| Vision coût en amont | Inexistante | Incluse dans la prévisualisation |
| Validation humaine | Inexistante | Checkpoint interactif intégré |

### 8.4 Intelligence décisionnelle

Le système prend des **décisions architecturales justifiées** plutôt que de suivre un template fixe :

1. **Choix de compute** : EKS vs ECS vs Lambda en fonction du type d'application détecté, pas d'un paramètre utilisateur
2. **Topologie réseau** : Multi-AZ vs mono-AZ selon la criticité du profil (scalabilité haute → Multi-AZ)
3. **Recommandation de variante** : analyse sémantique du prompt pour détecter les signaux de priorité (budget vs performance)
4. **Gestion des secrets** : détection et sanitization des fichiers `.env`, injection sous forme de variables Terraform (pas de hardcoding)

### 8.5 DevSecOps natif

Contrairement à des outils qui ajoutent la sécurité en option :

- La **gate sécurité** bloque l'analyse d'un dépôt compromis avant toute génération
- Les fichiers `.env` uploadés sont **hachés et sanitizés** avant d'être injectés dans le contexte
- Les manifests Kubernetes générés **n'exposent pas de secrets** et suivent les pratiques de moindre privilège
- Le pipeline CI/CD généré intègre les étapes de **scanning d'images** (Trivy placeholder)

### 8.6 Observabilité et traçabilité

Chaque décision du système est tracée :
- `AgentMemory` : historique des décisions par agent avec scores de confiance
- `logs` dans l'état LangGraph : chronologie complète du workflow
- `validation_summary` : traçabilité LLM vs fallback par artefact
- `react_iterations` : nombre d'itérations ReAct par agent
- `rag` metadata : disponibilité MCP, Qdrant, sources utilisées

Cette traçabilité permet l'audit complet d'une génération et l'amélioration continue du système.

### 8.7 Extensibilité architecturale

Le design par agents spécialisés et la séparation claire des couches (orchestration / génération / connaissance / LLM) permettent d'étendre le système sans refactoring majeur :
- Ajouter un agent `SecurityHardeningAgent` qui post-traite les artefacts
- Intégrer un nouveau fournisseur LLM dans le `LLMRouter`
- Enrichir le corpus Qdrant avec de nouveaux patterns
- Ajouter une ressource MCP pour un nouveau provider cloud (GCP, Azure)

---

## 9. Conclusion

La plateforme DevSecOps IA présentée dans ce document constitue une réponse architecturale complète à un problème industriel réel : la complexité croissante de la mise en place d'infrastructures cloud sécurisées pour des équipes sans expertise DevOps dédiée.

La valeur de la solution repose sur cinq piliers complémentaires :

1. **La spécialisation multi-agents** : chaque domaine (planification, Terraform, Kubernetes, Docker, CI/CD, coûts, sécurité) est traité par un composant expert avec son propre contexte, ses propres critères de qualité et ses propres stratégies de repli.

2. **La couche de connaissance hybride** : la combinaison du Model Context Protocol (précision schématique) et de Qdrant (rappel sémantique) fournit aux LLMs la connaissance nécessaire pour générer du code d'infrastructure valide, réduisant drastiquement le taux d'hallucination.

3. **L'orchestration déterministe par LangGraph** : le workflow en graphe d'état avec routage conditionnel garantit la cohérence du flux d'exécution, la persistance de l'état entre les phases, et la possibilité de points d'arrêt pour la validation humaine.

4. **Le contrat inter-agents** : le mécanisme `terraform_outputs` résout le problème fondamental de la cohérence entre artefacts générés indépendamment, en introduisant une abstraction de contrat qui découple la génération de l'utilisation.

5. **La résilience opérationnelle** : la chaîne de repli LLM (GitHub Models → Groq × 6 clés), les fallbacks déterministes, les boucles ReAct avec évaluation domaine-spécifique, et la mémoire avec cache confiance garantissent une disponibilité et une qualité de sortie acceptables même en conditions dégradées.

Sur le plan académique, ce travail illustre l'application concrète des paradigmes de l'IA moderne (agents réactifs, RAG, LangGraph) à un domaine métier exigeant (Infrastructure-as-Code, DevSecOps), démontrant que l'intelligence artificielle ne se substitue pas aux ingénieurs cloud mais amplifie leur productivité en automatisant les tâches répétitives tout en intégrant la connaissance expert dans le processus de génération.

Les axes d'amélioration identifiés pour les travaux futurs incluent : l'intégration d'un agent de test d'infrastructure (`terraform validate` automatique, dry-run Kubernetes), l'enrichissement dynamique du corpus Qdrant à partir des corrections utilisateurs, le support de providers cloud additionnels (GCP GKE, Azure AKS), et l'implémentation d'un cycle de feedback LLM-as-judge sur les artefacts produits en production.

---

*Document généré le 04 mai 2026 — Projet de Fin d'Études, Esprit School of Engineering*  
*Analyse basée sur l'implémentation réelle du code source — branche `dev`*
