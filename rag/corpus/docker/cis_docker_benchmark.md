---
id: cis_docker_benchmark
artifact_type: docker
doc_type: docker
title: CIS Docker Benchmark — Security Best Practices
description: Règles de sécurité Docker issues du CIS Docker Benchmark v1.6
tags: [docker, security, cis, hardening, benchmark]
keywords: [rootless, non-root, read-only, capabilities, seccomp, apparmor]
---

# CIS Docker Benchmark — Règles de Sécurité Essentielles

## 1. Exécuter les conteneurs en non-root (CIS 4.1)

Ne jamais exécuter un conteneur en tant que root. Créer un utilisateur dédié dans le Dockerfile.

```dockerfile
# MAUVAIS — exécution en root par défaut
FROM python:3.11-slim
CMD ["python", "app.py"]

# CORRECT — utilisateur non-root
FROM python:3.11-slim
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home appuser
USER appuser
CMD ["python", "app.py"]
```

## 2. Filesystem en lecture seule (CIS 5.12)

Monter le filesystem du conteneur en lecture seule pour prévenir les modifications non autorisées.

```yaml
# docker-compose.yml
services:
  api:
    image: myapp:latest
    read_only: true
    tmpfs:
      - /tmp
      - /var/run
```

```bash
# CLI équivalent
docker run --read-only --tmpfs /tmp myapp:latest
```

## 3. Supprimer les capabilities Linux inutiles (CIS 5.3)

Commencer par tout supprimer, puis ajouter uniquement les capabilities nécessaires.

```yaml
services:
  api:
    image: myapp:latest
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE   # si le service écoute sur un port < 1024
```

## 4. Limiter les ressources (CIS 5.10 / 5.11)

Toujours définir des limites de mémoire et CPU pour éviter le DoS.

```yaml
services:
  api:
    image: myapp:latest
    deploy:
      resources:
        limits:
          memory: 512m
          cpus: "0.5"
        reservations:
          memory: 128m
          cpus: "0.1"
```

## 5. Désactiver le mode privilégié (CIS 5.4)

Ne jamais utiliser `privileged: true` en production.

```yaml
# INTERDIT en production
services:
  bad:
    privileged: true   # DANGER — accès complet au kernel

# CORRECT
services:
  api:
    security_opt:
      - no-new-privileges:true
```

## 6. Profil Seccomp et AppArmor (CIS 5.1 / 5.2)

```yaml
services:
  api:
    security_opt:
      - seccomp:seccomp-profile.json
      - apparmor:docker-default
```

## 7. Images de base minimales

Préférer `distroless` ou `alpine` pour minimiser la surface d'attaque.

```dockerfile
# Distroless — aucun shell, aucun package manager
FROM gcr.io/distroless/python3-debian12
COPY --from=builder /app /app
CMD ["/app/main.py"]

# Alpine — très léger (~5 MB)
FROM python:3.11-alpine
RUN pip install --no-cache-dir -r requirements.txt
```

## 8. Scanner les images avant déploiement

```bash
# Trivy — scanner open source
trivy image myapp:latest --severity CRITICAL,HIGH

# Grype — alternative
grype myapp:latest

# Docker Scout
docker scout cves myapp:latest
```

## 9. Ne jamais inclure de secrets dans les images (CIS 4.10)

```dockerfile
# MAUVAIS
ENV API_KEY=sk-secret123

# CORRECT — utiliser Docker secrets ou variables au runtime
RUN --mount=type=secret,id=api_key API_KEY=$(cat /run/secrets/api_key) pip install ...
```

## 10. .dockerignore — exclure les fichiers sensibles

```
.env
.env.*
*.pem
*.key
*.p12
secrets/
.git/
__pycache__/
*.pyc
node_modules/
.DS_Store
```
