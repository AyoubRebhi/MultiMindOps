---
id: devsecops_best_practices
artifact_type: devsecops
doc_type: security
title: DevSecOps Best Practices — Shift-Left Security
description: Meilleures pratiques DevSecOps — intégration de la sécurité dans le cycle de développement
tags: [devsecops, security, shift-left, sast, dast, sca, sbom, threat-modeling]
keywords: [sast, dast, sca, sbom, threat-model, secret-scanning, policy-as-code]
---

# DevSecOps — Intégration de la Sécurité dans le SDLC

## 1. Les 4 piliers du DevSecOps

### Shift-Left Security
Intégrer la sécurité dès la phase de design, pas après le déploiement.

```
SDLC sécurisé :
  Plan → Code → Build → Test → Release → Deploy → Monitor
    │       │      │       │        │        │         │
  Threat  SAST   SCA    DAST    SBOM    Config  Runtime
  Model         Trivy  OWASP    Snyk    Audit   Alerts
```

### Policy as Code
```yaml
# OPA / Conftest — Politique de sécurité en code
# policy/docker.rego
package docker

deny[msg] {
  input.config.User == ""
  msg := "Image must specify a non-root USER"
}

deny[msg] {
  input.config.Healthcheck == null
  msg := "Image must define a HEALTHCHECK"
}

# Vérification dans CI
# conftest test Dockerfile --policy policy/
```

## 2. SAST — Outils recommandés

| Outil | Langage | Règles |
|-------|---------|--------|
| Semgrep | Multi | OWASP, secrets, custom |
| Bandit | Python | B1xx-B7xx |
| SpotBugs | Java | FindSec-Bugs |
| ESLint Security | JS/TS | eslint-plugin-security |
| CodeQL | Multi | CVE, taint-tracking |

```bash
# Bandit — Python
bandit -r ./backend -ll -f json -o bandit-report.json

# Semgrep — Multi
semgrep --config=p/python --config=p/owasp-top-ten ./backend

# Résultats dans le SARIF pour GitHub Security tab
semgrep --config=auto --sarif > semgrep.sarif
```

## 3. Gestion des Secrets — Règles d'or

```bash
# 1. Scanner les secrets AVANT le commit
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks

  - repo: https://github.com/trufflesecurity/trufflehog
    rev: v3.63.0
    hooks:
      - id: trufflehog
        args: ["git", "--only-verified"]
```

```python
# 2. Chargement sécurisé des secrets en Python
import boto3
import json

def get_secret(secret_name: str) -> dict:
    """Récupère un secret depuis AWS Secrets Manager."""
    client = boto3.client("secretsmanager", region_name="eu-west-1")
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])

# Utilisation
secrets = get_secret("production/api/credentials")
DATABASE_URL = secrets["database_url"]
```

## 4. SBOM — Software Bill of Materials

```bash
# Générer un SBOM pour l'image Docker
syft myapp:latest -o spdx-json > sbom.spdx.json

# Analyser le SBOM avec Grype
grype sbom:./sbom.spdx.json --fail-on high

# CycloneDX — format alternatif
cyclonedx-py environment -o sbom.cyclonedx.json
```

## 5. Container Registry Security

```bash
# Signer les images avec Cosign (Sigstore)
cosign generate-key-pair

# Signer après build
cosign sign --key cosign.key myregistry.io/myapp:1.0.0

# Vérifier avant déploiement
cosign verify --key cosign.pub myregistry.io/myapp:1.0.0

# Politique de vérification dans Kubernetes (Kyverno)
```

```yaml
# Kyverno — Vérifier les signatures d'images
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signatures
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-image-signature
      match:
        resources:
          kinds: ["Pod"]
      verifyImages:
        - imageReferences:
            - "myregistry.io/myapp:*"
          attestors:
            - count: 1
              entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      ...
                      -----END PUBLIC KEY-----
```

## 6. Monitoring de sécurité en production

```yaml
# Falco — Détection de comportements anormaux en runtime
# /etc/falco/falco_rules.yaml (règle custom)
- rule: Unexpected outbound connection
  desc: Detect unexpected outbound network connections
  condition: >
    outbound and not proc.name in (allowed_processes)
    and not fd.sip in (allowed_ips)
  output: >
    Unexpected connection (process=%proc.name
    user=%user.name dest=%fd.rip:%fd.rport)
  priority: WARNING
  tags: [network, mitre_exfiltration]
```

## 7. Threat Modeling — STRIDE

```
STRIDE pour une API REST :
  
  Spoofing       → Authentification JWT/mTLS
  Tampering      → Signature des requêtes, HTTPS obligatoire
  Repudiation    → Audit logs immuables (CloudTrail)
  Info Disclosure→ Chiffrement des données sensibles, filtrage des logs
  Denial of Serv.→ Rate limiting, WAF, circuit breakers
  Elevation      → RBAC strict, validation des permissions à chaque requête
```

## 8. Checklist DevSecOps par phase

```
PHASE CODE :
  □ Pre-commit hooks (secret scan, linting)
  □ Threat modeling pour nouvelles fonctionnalités
  □ Dependency pinning (requirements.txt avec hash)

PHASE BUILD :
  □ SAST (Semgrep, Bandit, CodeQL)
  □ SCA (Safety, Snyk, OWASP Dependency-Check)
  □ Dockerfile lint (Hadolint)
  □ Scan image Docker (Trivy, Grype)
  □ Génération SBOM

PHASE TEST :
  □ DAST (OWASP ZAP, Nuclei)
  □ Tests d'authentification et autorisation
  □ Fuzzing des entrées utilisateur

PHASE DEPLOY :
  □ Infrastructure as Code scanné (tfsec, Checkov)
  □ Secrets injectés via Secrets Manager (pas via env vars)
  □ Images signées (Cosign)
  □ Policy enforcement (OPA/Kyverno)

PHASE MONITOR :
  □ Runtime security (Falco)
  □ Alerting sur anomalies (GuardDuty, Security Hub)
  □ Rotation des credentials
  □ Audit des accès privilégiés
```
