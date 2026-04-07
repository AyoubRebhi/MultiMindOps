---
id: kubernetes_deployment_patterns
artifact_type: k8s
doc_type: k8s
title: Kubernetes Deployment Patterns — Production Ready
description: Patterns de déploiement Kubernetes production — Deployment, Service, HPA, ConfigMap, Secret
tags: [kubernetes, k8s, deployment, service, hpa, configmap, production, helm]
keywords: [deployment, service, hpa, configmap, secret, rolling-update, namespace, label]
---

# Kubernetes — Patterns de Déploiement Production

## 1. Namespace et Labels

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    environment: production
    managed-by: terraform
    team: platform
```

## 2. Deployment complet avec bonnes pratiques

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: production
  labels:
    app: api
    version: "1.0.0"
    environment: production
  annotations:
    deployment.kubernetes.io/revision: "1"
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # 1 pod supplémentaire pendant le déploiement
      maxUnavailable: 0  # 0 pod indisponible — zero downtime
  template:
    metadata:
      labels:
        app: api
        version: "1.0.0"
    spec:
      serviceAccountName: api-sa
      automountServiceAccountToken: false

      # Répartition sur plusieurs nodes
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: api
                topologyKey: kubernetes.io/hostname

      # Security Context au niveau du Pod
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
        seccompProfile:
          type: RuntimeDefault

      containers:
        - name: api
          image: myregistry.io/myapp:1.0.0  # tag fixe — jamais :latest en prod
          imagePullPolicy: Always

          ports:
            - containerPort: 8000
              protocol: TCP
              name: http

          # Security Context au niveau du Container
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]

          # Ressources obligatoires
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"

          # Variables d'environnement
          env:
            - name: APP_ENV
              valueFrom:
                configMapKeyRef:
                  name: api-config
                  key: APP_ENV
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: api-secrets
                  key: DATABASE_URL

          # Health checks
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 20
            timeoutSeconds: 5
            failureThreshold: 3

          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3

          startupProbe:
            httpGet:
              path: /health
              port: 8000
            failureThreshold: 30
            periodSeconds: 5

          # Volumes pour le filesystem read-only
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: cache
              mountPath: /app/.cache

      volumes:
        - name: tmp
          emptyDir: {}
        - name: cache
          emptyDir: {}

      # Tolérance aux pannes de nodes
      terminationGracePeriodSeconds: 60
```

## 3. Service et Ingress

```yaml
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: api-service
  namespace: production
  labels:
    app: api
spec:
  type: ClusterIP  # jamais NodePort ou LoadBalancer directement
  selector:
    app: api
  ports:
    - port: 80
      targetPort: 8000
      protocol: TCP
      name: http
---
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  namespace: production
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  tls:
    - hosts: [api.example.com]
      secretName: api-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: api-service
                port:
                  number: 80
```

## 4. Horizontal Pod Autoscaler

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

## 5. ConfigMap et Secret

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-config
  namespace: production
data:
  APP_ENV: "production"
  LOG_LEVEL: "info"
  CORS_ORIGINS: "https://app.example.com"
  MAX_CONNECTIONS: "100"
---
# secret.yaml (géré via External Secrets Operator en production)
apiVersion: v1
kind: Secret
metadata:
  name: api-secrets
  namespace: production
type: Opaque
# En production : utiliser External Secrets Operator
# Les valeurs ne doivent pas être committées en clair
```
