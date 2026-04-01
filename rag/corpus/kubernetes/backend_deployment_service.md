---
id: kubernetes_backend_deployment_service
artifact_type: kubernetes
language: generic
framework: generic
project_type: backend_service
runtime: kubernetes
dependencies: []
tags: [deployment, service, kubernetes]
description: Minimal Deployment and Service manifests for a backend container.
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
        - name: backend
          image: backend:latest
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: backend
spec:
  selector:
    app: backend
  ports:
    - port: 8080
      targetPort: 8080
