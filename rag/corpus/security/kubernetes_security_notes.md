---
id: security_kubernetes_notes
artifact_type: security
language: generic
framework: generic
project_type: generic
runtime: kubernetes
dependencies: []
tags: [security, kubernetes]
description: Security reminders for Kubernetes manifest generation.
---
- Avoid broad privileges in pods.
- Prefer explicit container ports and selectors.
- Keep secrets out of plain manifests when possible.
