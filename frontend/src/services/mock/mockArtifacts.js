/* ============================================================================
   mockArtifacts.js — generated artifacts (Dockerfile, Terraform, K8s, ...).
   `content` holds a short representative snippet for the code viewer.
   ========================================================================== */

export const mockArtifacts = [
  {
    id: 'art-001',
    projectId: 'prj-001',
    type: 'dockerfile',
    name: 'Dockerfile',
    path: 'payments-api/Dockerfile',
    language: 'docker',
    status: 'passed',
    validated: true,
    sizeKb: 1.2,
    updatedAt: '2026-06-11T13:18:00Z',
    content: `# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=app:app . .
RUN useradd -m app
USER app
EXPOSE 8000
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]`,
  },
  {
    id: 'art-002',
    projectId: 'prj-001',
    type: 'terraform',
    name: 'main.tf',
    path: 'payments-api/infra/main.tf',
    language: 'hcl',
    status: 'passed',
    validated: true,
    sizeKb: 3.8,
    updatedAt: '2026-06-11T13:46:00Z',
    content: `module "ecs_service" {
  source       = "./modules/ecs"
  name         = "payments-api"
  cpu          = 512
  memory       = 1024
  image        = var.container_image
  desired_count = 2
  subnets      = module.vpc.private_subnets
}

resource "aws_db_instance" "payments" {
  identifier        = "payments-api-db"
  engine            = "postgres"
  instance_class    = "db.t3.medium"
  allocated_storage = 20
}`,
  },
  {
    id: 'art-003',
    projectId: 'prj-002',
    type: 'dockerfile',
    name: 'Dockerfile',
    path: 'customer-portal/Dockerfile',
    language: 'docker',
    status: 'passed',
    validated: true,
    sizeKb: 1.5,
    updatedAt: '2026-06-12T08:30:00Z',
    content: `FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80`,
  },
  {
    id: 'art-004',
    projectId: 'prj-004',
    type: 'dockerfile',
    name: 'Dockerfile',
    path: 'auth-service/Dockerfile',
    language: 'docker',
    status: 'failed',
    validated: false,
    sizeKb: 1.1,
    updatedAt: '2026-06-12T07:42:00Z',
    content: `FROM eclipse-temurin:21-jdk AS build
WORKDIR /app
COPY . .
RUN ./gradlew bootJar

FROM gcr.io/distroless/java21-debian12
COPY --from=build /app/build/libs/app.jar /app.jar
# ⚠ corrector flagged: missing non-root USER + EXPOSE
ENTRYPOINT ["java", "-jar", "/app.jar"]`,
  },
  {
    id: 'art-005',
    projectId: 'prj-003',
    type: 'kubernetes',
    name: 'deployment.yaml',
    path: 'data-pipeline/k8s/deployment.yaml',
    language: 'yaml',
    status: 'passed',
    validated: true,
    sizeKb: 2.4,
    updatedAt: '2026-06-10T19:02:00Z',
    content: `apiVersion: apps/v1
kind: Deployment
metadata:
  name: data-pipeline
spec:
  replicas: 3
  selector:
    matchLabels: { app: data-pipeline }
  template:
    metadata:
      labels: { app: data-pipeline }
    spec:
      containers:
        - name: worker
          image: gcr.io/cloudforge/data-pipeline:1.8.0
          resources:
            requests: { cpu: "500m", memory: "1Gi" }
            limits: { cpu: "2", memory: "4Gi" }`,
  },
  {
    id: 'art-006',
    projectId: 'prj-003',
    type: 'helm',
    name: 'values.yaml',
    path: 'data-pipeline/chart/values.yaml',
    language: 'yaml',
    status: 'warning',
    validated: true,
    sizeKb: 1.9,
    updatedAt: '2026-06-10T19:05:00Z',
    content: `replicaCount: 3
image:
  repository: gcr.io/cloudforge/data-pipeline
  tag: "1.8.0"
autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 75`,
  },
];
