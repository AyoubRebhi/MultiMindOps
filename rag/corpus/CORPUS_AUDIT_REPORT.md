# RAG Corpus Audit Report

Date: 2026-04-28
Reviewer: senior cloud-architect lens

## Inventory snapshot

| Domain | Depth | Format | Notes |
|---|---|---|---|
| Terraform (3 KBs) | strong | JSON KB | core concepts, prod best practices, architecture patterns |
| AWS infrastructure patterns | strong | JSON KB | VPC/EC2/ECS/EKS/Lambda/S3/RDS decision rules |
| AWS Well-Architected security | medium | MD | one doc, security pillar only |
| EKS decision intelligence | strong | JSON KB | 869 lines, very deep |
| Kubernetes deployment patterns | medium | MD | 268 lines, no RBAC/NetworkPolicy depth |
| CIS Kubernetes / Docker benchmarks | medium | MD | benchmark notes, no remediation playbooks |
| Dockerfile / compose / env examples | medium | MD | code-level, narrow |
| GitHub Actions CI/CD | weak | YAML examples + 1 security MD | no scanner integration depth |
| DevSecOps best practices | medium | MD | 216 lines, generic |
| Security notes (4 files) | **stub** | MD | 3-line bullet lists, no real value |

## Audit JSON

```json
{
  "strong_areas": [
    "AWS infrastructure patterns (VPC, compute, storage, IAM basics)",
    "Terraform: core concepts, production best practices, architecture patterns",
    "EKS production decision intelligence (very deep)",
    "Dockerfile and docker-compose concrete examples"
  ],
  "weak_areas": [
    "security/*_notes.md — stub files, 3 bullets each, no real reasoning",
    "CI/CD security — only one .md, no scanner-integration depth (Trivy/Snyk/cosign)",
    "Kubernetes — strong on deployment, weak on RBAC, NetworkPolicy, Helm, admission control",
    "AWS IAM — covered only as a side topic in patterns KB; no dedicated IAM KB",
    "Generic DevSecOps best practices file is a checklist, not decision intelligence"
  ],
  "missing_domains": [
    "Cost optimization (right-sizing, spot, savings plans, autoscaling tradeoffs)",
    "Networking deep-dive (zero-trust, SG vs NACL, Transit Gateway, VPC endpoints, PrivateLink)",
    "Observability (logs/metrics/traces, SLOs, alerting, OpenTelemetry, CloudWatch vs Prometheus)",
    "Incident knowledge (postmortems, common misconfigurations, failure modes)",
    "Supply-chain security (SLSA, SBOM, sigstore/cosign, provenance, dependency pinning)",
    "Secrets management (Vault, AWS Secrets Manager, KMS envelope encryption, sealed-secrets, External Secrets)",
    "Multi-account AWS architectures (Organizations, SCPs, Control Tower, landing zones)",
    "Zero-trust architecture (BeyondCorp model, mTLS, service mesh)",
    "Disaster recovery / RTO-RPO patterns",
    "Compliance mapping (SOC2, PCI-DSS, HIPAA → controls)"
  ],
  "redundancies": [
    "security/*_notes.md duplicate themes already covered (poorly) vs the security notes inside Terraform/Docker/K8s KBs — recommend deprecating the stubs once richer KBs exist",
    "CIS Docker and CIS Kubernetes benchmarks repeat content available in the production-patterns docs — keep both (different angles) but link explicitly",
    "DevSecOps best practices MD overlaps with content distributed across other KBs — keep as overview but defer detail to specialized KBs"
  ],
  "rag_quality_issues": [
    "Stub files (3-15 lines) produce noisy retrieval — embeddings cluster around generic words",
    "No consistent tagging schema — some files have frontmatter (artifact_type/runtime/tags), JSON KBs use metadata.tags. Recommend unifying.",
    "Some chunks lack named subheadings — chunker may split mid-rule. New files use explicit entry IDs and named categories to improve chunking."
  ]
}
```

## What was added (8 new KBs)

| Folder | File | Why |
|---|---|---|
| `iam/` | `aws_iam_decision_intelligence_kb.json` | least privilege, role assumption, cross-account, IRSA |
| `networking/` | `zero_trust_networking_kb.json` | SG vs NACL, VPC endpoints, PrivateLink, Transit Gateway, mTLS |
| `cost/` | `aws_cost_optimization_kb.json` | right-sizing, spot, savings plans, autoscaling, NAT cost |
| `incidents/` | `devsecops_failure_modes_kb.json` | postmortem-style — public S3, IMDSv1, exposed kubelet, cred leak |
| `observability/` | `observability_patterns_kb.json` | the three pillars, SLOs, alerting, OTel, log hygiene |
| `architecture/` | `multi_tier_production_architectures_kb.json` | 3-tier, microservices, multi-account, DR |
| `supply_chain/` | `supply_chain_security_kb.json` | SLSA levels, SBOM, cosign, provenance, dep pinning |
| `secrets/` | `secrets_management_kb.json` | Vault, AWS SM, KMS envelope, External Secrets, IRSA pattern |

CI/CD secure-pipeline patterns and K8s RBAC/NetworkPolicy patterns are integrated into the supply-chain and networking KBs respectively to avoid redundancy.

## New evaluation queries (previously weak → should now improve)

1. *"Design a secure multi-account AWS landing zone with SCPs and centralized logging"* — covered by `architecture/multi_tier_production_architectures_kb.json`
2. *"What's the right Kubernetes NetworkPolicy strategy for default-deny with namespace egress?"* — covered by `networking/zero_trust_networking_kb.json`
3. *"How should I rotate database credentials in EKS without downtime?"* — covered by `secrets/secrets_management_kb.json` (External Secrets + IRSA pattern)
4. *"My ECS service is costing too much — what should I check first?"* — covered by `cost/aws_cost_optimization_kb.json`
5. *"Postmortem: a public S3 bucket leaked PII — what controls would have prevented it?"* — covered by `incidents/devsecops_failure_modes_kb.json`
6. *"Implement SLSA Level 3 build provenance with GitHub Actions and cosign"* — covered by `supply_chain/supply_chain_security_kb.json`
7. *"Design SLOs and burn-rate alerts for a payment API"* — covered by `observability/observability_patterns_kb.json`
8. *"Cross-account IAM role assumption with external ID — when and why?"* — covered by `iam/aws_iam_decision_intelligence_kb.json`

## Suggestions for further improvement

1. **Deprecate stub files** — `security/*_notes.md` files (3 bullets each) hurt retrieval quality. Either delete or merge into the new KBs.
2. **Unify tagging** — adopt one schema across MD frontmatter and JSON `metadata.tags`. Suggest: `domain`, `difficulty` (basic|advanced|expert), `type` (pattern|example|rule|incident|tradeoff), `compliance` (cis|pci|soc2|nist).
3. **Add a "compliance map" KB** — cross-reference each control to SOC2/PCI/CIS for automated audit-style queries.
4. **Add real Helm chart and RBAC YAML examples** under `kubernetes/examples/` — currently only one deployment example exists.
5. **Run an evaluation pass** with the 8 new queries before/after re-ingestion; track recall@5 and answer faithfulness.
6. **Chunking guidance** — these new KBs use one logical "entry" per concept (~150-300 tokens) which is ideal for the existing chunker. Verify that the chunker preserves entry boundaries.
7. **Build an automated freshness check** — flag KB entries older than 12 months for review (AWS service evolution is fast).
