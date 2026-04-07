---
id: cis_kubernetes_benchmark
artifact_type: k8s
doc_type: k8s
title: CIS Kubernetes Benchmark — Security Best Practices
description: Règles de sécurité Kubernetes issues du CIS Kubernetes Benchmark v1.8
tags: [kubernetes, k8s, security, cis, hardening, rbac, pod-security]
keywords: [rbac, psp, securitycontext, networkpolicy, serviceaccount, secret]
---

# CIS Kubernetes Benchmark — Sécurité des Workloads

## 1. SecurityContext obligatoire (CIS 5.2)

Chaque Pod doit définir un SecurityContext restrictif.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: api
          image: myapp:1.0.0
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
```

## 2. RBAC — Principe du moindre privilège (CIS 5.1)

```yaml
# ServiceAccount dédié par application
apiVersion: v1
kind: ServiceAccount
metadata:
  name: api-sa
  namespace: production
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: api-role
  namespace: production
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list"]
  # NE PAS ajouter "secrets" sauf nécessité absolue
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: api-rolebinding
  namespace: production
subjects:
  - kind: ServiceAccount
    name: api-sa
roleRef:
  kind: Role
  name: api-role
  apiGroup: rbac.authorization.k8s.io
```

## 3. Network Policies — Isolation réseau (CIS 5.3)

```yaml
# Deny-all par défaut, puis allow explicite
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-ingress
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8000
```

## 4. Gestion des Secrets (CIS 5.4)

```yaml
# Utiliser External Secrets Operator ou Sealed Secrets
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: api-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: api-env-secret
    creationPolicy: Owner
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: production/api
        property: database_url

# ConfigMap pour données non-sensibles uniquement
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-config
data:
  APP_ENV: "production"
  LOG_LEVEL: "info"
```

## 5. Resource Limits obligatoires (CIS 5.2.4)

```yaml
containers:
  - name: api
    resources:
      requests:
        memory: "128Mi"
        cpu: "100m"
      limits:
        memory: "512Mi"
        cpu: "500m"
```

## 6. Liveness et Readiness Probes

```yaml
containers:
  - name: api
    livenessProbe:
      httpGet:
        path: /health
        port: 8000
      initialDelaySeconds: 15
      periodSeconds: 20
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /ready
        port: 8000
      initialDelaySeconds: 5
      periodSeconds: 10
```

## 7. Pod Disruption Budget — Haute disponibilité

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: api
```

## 8. Ingress avec TLS

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  tls:
    - hosts:
        - api.example.com
      secretName: api-tls-cert
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
