---
id: dockerfile_production_patterns
artifact_type: dockerfile
doc_type: docker
title: Dockerfile Production Patterns — Multi-stage builds
description: Patterns avancés de Dockerfile pour la production — multi-stage, distroless, sécurité
tags: [docker, dockerfile, multi-stage, production, python, fastapi, java, node]
keywords: [multi-stage, distroless, alpine, builder, layer, cache, healthcheck]
---

# Dockerfile Production Patterns

## 1. Python / FastAPI — Multi-stage avec distroless

```dockerfile
# ── Stage 1 : Dépendances ────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Copier uniquement les fichiers de dépendances (cache Docker)
COPY requirements.txt .

RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2 : Application ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Métadonnées
LABEL org.opencontainers.image.title="FastAPI Application"
LABEL org.opencontainers.image.version="1.0.0"

# Utilisateur non-root
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home --shell /bin/false appuser

# Copier les packages Python installés depuis le builder
COPY --from=builder /root/.local /home/appuser/.local

WORKDIR /app
COPY --chown=appuser:appgroup . .

# Variables d'environnement de production
ENV PATH="/home/appuser/.local/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--no-access-log"]
```

## 2. Node.js — Multi-stage avec npm ci

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /build
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -s /bin/false -D appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appgroup /build/dist ./dist
COPY --from=builder --chown=appuser:appgroup /build/node_modules ./node_modules
USER appuser
HEALTHCHECK --interval=30s --timeout=5s \
    CMD wget -qO- http://localhost:3000/health || exit 1
EXPOSE 3000
CMD ["node", "dist/server.js"]
```

## 3. Java / Spring Boot — Multi-stage avec layers

```dockerfile
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /build
COPY pom.xml .
# Télécharger les dépendances en cache séparé
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B

FROM eclipse-temurin:17-jre-alpine AS runtime
RUN addgroup -g 1001 appgroup && adduser -u 1001 -G appgroup -D appuser
WORKDIR /app
# Extraire les layers Spring Boot pour un meilleur caching
COPY --from=builder /build/target/*.jar app.jar
RUN java -Djarmode=layertools -jar app.jar extract
USER appuser
HEALTHCHECK --interval=30s --timeout=10s \
    CMD wget -qO- http://localhost:8080/actuator/health || exit 1
EXPOSE 8080
ENTRYPOINT ["java", \
    "-XX:MaxRAMPercentage=75.0", \
    "-XX:+UseContainerSupport", \
    "-Djava.security.egd=file:/dev/./urandom", \
    "-jar", "app.jar"]
```

## 4. .dockerignore — Template complet

```
# Contrôle de version
.git/
.gitignore
.gitattributes

# Environnements et secrets
.env
.env.*
*.pem
*.key
*.p12
*.pfx
secrets/

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/
.venv/
venv/
env/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage

# Node
node_modules/
npm-debug.log
yarn-error.log
.npm/

# Docker
Dockerfile*
docker-compose*.yml
.dockerignore

# IDE
.idea/
.vscode/
*.swp
*.swo
.DS_Store

# CI/CD
.github/
.gitlab-ci.yml
Jenkinsfile

# Documentation
docs/
*.md
LICENSE

# Tests
tests/
test/
spec/
```

## 5. Optimisation du cache Docker

```dockerfile
# MAUVAIS — invalide le cache à chaque changement de code
COPY . .
RUN pip install -r requirements.txt

# CORRECT — séparer les dépendances du code
COPY requirements.txt .          # cache stable
RUN pip install -r requirements.txt
COPY . .                         # code change souvent
```
