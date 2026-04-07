---
id: github_actions_security_best_practices
artifact_type: cicd
doc_type: cicd
title: GitHub Actions — Security & Best Practices
description: Workflow GitHub Actions sécurisé avec SAST, DAST, scan de dépendances et déploiement
tags: [cicd, github-actions, security, sast, dast, devsecops, pipeline]
keywords: [workflow, secrets, permissions, oidc, trivy, semgrep, dependabot, codeql]
---

# GitHub Actions — CI/CD DevSecOps Complet

## 1. Structure du workflow sécurisé

```yaml
# .github/workflows/ci-cd.yml
name: CI/CD DevSecOps Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

# Permissions minimales globales
permissions:
  contents: read

jobs:
  # ── Étape 1 : Tests et Qualité ────────────────────────────────────────────
  test:
    name: Tests & Lint
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Run linter
        run: ruff check . && mypy .

      - name: Run tests
        run: pytest --cov=. --cov-report=xml -v
        env:
          DATABASE_URL: ${{ secrets.TEST_DATABASE_URL }}

  # ── Étape 2 : SAST (Static Analysis) ─────────────────────────────────────
  sast:
    name: Static Security Analysis
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      contents: read
    steps:
      - uses: actions/checkout@v4

      - name: Semgrep SAST
        uses: semgrep/semgrep-action@v1
        with:
          config: >-
            p/python
            p/owasp-top-ten
            p/secrets
        env:
          SEMGREP_APP_TOKEN: ${{ secrets.SEMGREP_APP_TOKEN }}

      - name: CodeQL Analysis
        uses: github/codeql-action/analyze@v3
        with:
          languages: python

  # ── Étape 3 : Scan des dépendances ───────────────────────────────────────
  dependency-scan:
    name: Dependency & Secret Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Scan secrets avec Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: OWASP Dependency-Check
        uses: dependency-check/Dependency-Check_Action@main
        with:
          project: myapp
          path: .
          format: HTML

      - name: Safety check (Python)
        run: |
          pip install safety
          safety check --full-report

  # ── Étape 4 : Build & Scan de l'image Docker ─────────────────────────────
  docker-build:
    name: Build & Container Security Scan
    runs-on: ubuntu-latest
    needs: [test, sast]
    permissions:
      contents: read
      packages: write
      security-events: write
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build Docker image (sans push)
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          tags: myapp:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          load: true

      - name: Trivy — Scan vulnérabilités image
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: myapp:${{ github.sha }}
          format: sarif
          output: trivy-results.sarif
          severity: CRITICAL,HIGH
          exit-code: 1

      - name: Upload Trivy SARIF
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: trivy-results.sarif

  # ── Étape 5 : Push vers le registry (main uniquement) ────────────────────
  push-image:
    name: Push to Registry
    runs-on: ubuntu-latest
    needs: [docker-build, dependency-scan]
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: read
      id-token: write   # OIDC pour authentification AWS/GCP
      packages: write
    steps:
      - uses: actions/checkout@v4

      # OIDC — pas de secrets long-lived
      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789:role/GitHubActionsRole
          aws-region: eu-west-1

      - name: Login to Amazon ECR
        uses: aws-actions/amazon-ecr-login@v2

      - name: Push image to ECR
        run: |
          docker tag myapp:${{ github.sha }} \
            123456789.dkr.ecr.eu-west-1.amazonaws.com/myapp:${{ github.sha }}
          docker push \
            123456789.dkr.ecr.eu-west-1.amazonaws.com/myapp:${{ github.sha }}
```

## 2. Sécurité des secrets dans GitHub Actions

```yaml
# RÈGLES pour les secrets :
# 1. Utiliser ${{ secrets.NOM }} — jamais en clair
# 2. Ne jamais afficher avec echo ou print
# 3. Marquer sensitive=true dans les étapes custom
# 4. Utiliser OIDC plutôt que des clés d'accès long-lived

# Mauvais — clé en clair dans l'environnement
env:
  AWS_ACCESS_KEY: AKIAIOSFODNN7EXAMPLE  # INTERDIT

# Correct — via GitHub Secrets
env:
  AWS_ACCESS_KEY: ${{ secrets.AWS_ACCESS_KEY_ID }}
```

## 3. Dependabot — Mises à jour automatiques

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    labels: ["dependencies", "security"]
    open-pull-requests-limit: 5

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

## 4. Workflow Python FastAPI — Exemple complet

```yaml
name: FastAPI CI

on: [push, pull_request]

jobs:
  ci:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: testdb
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - run: pip install -r requirements.txt

      - run: pytest tests/ -v --tb=short
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/testdb

      - name: Build Docker image
        run: docker build -t app:ci .

      - name: Trivy scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: app:ci
          severity: CRITICAL
          exit-code: 1
```
