#!/usr/bin/env python3
"""
DevSecOps RAG corpus cleaner / normalizer.

Transforms the raw knowledge corpus under rag/corpus/ into an embedding-ready,
canonical-schema form under rag/corpus_cleaned/. This step does NOT embed or
chunk — it cleans, normalizes structure, infers metadata, and marks semantic
chunk boundaries so a downstream LLM chunker (GPT-4.1 mini) + embedding model
(text-embedding-3-small) + Qdrant can ingest with maximum retrieval quality.

Design principles (see CLEANING_REPORT.md):
  * Deterministic and re-runnable — no LLM calls, no randomness.
  * Body text is preserved verbatim (only whitespace-normalized) to guarantee
    technical accuracy. Terminology normalization is applied to the metadata
    layer (tags/service) that drives hybrid-retrieval filtering, NOT to the
    body, because rewriting infra guidance risks subtle correctness errors.
  * No external knowledge is added; .tf files are converted to explained
    knowledge via a hand-curated, source-grounded sidecar (terraform_entries.json).

Usage:  python rag/tools/clean_corpus.py
"""
from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from collections import Counter
from itertools import combinations

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "rag" / "corpus"
OUT = REPO / "rag" / "corpus_cleaned"
TF_ENTRIES_FILE = REPO / "rag" / "tools" / "terraform_entries.json"
GENERATED_BY = "rag/tools/clean_corpus.py"

# --------------------------------------------------------------------------- #
# Inference maps  (Task 3: Domain Inference Rules)
# --------------------------------------------------------------------------- #
DOMAIN_RESOURCE_TYPE = {
    "terraform": "terraform",
    "docker": "docker", "dockerfile": "docker", "docker_compose": "docker",
    "k8s": "kubernetes", "kubernetes": "kubernetes",
    "security": "security", "iam": "security", "secrets": "security",
    "supply_chain": "security", "incidents": "security", "networking": "security",
    "env_example": "security", "devsecops": "security",
    "observability": "observability", "cost": "cost",
    "architecture": "architecture", "cloud": "architecture",
}

DOMAIN_INFERENCE_TAGS = {
    "dockerfile": ["docker", "build", "runtime"],
    "docker": ["docker"],
    "docker_compose": ["docker", "compose", "local-development"],
    "k8s": ["kubernetes", "orchestration"],
    "kubernetes": ["kubernetes", "orchestration"],
    "terraform": ["infrastructure", "provisioning", "iac"],
    "iam": ["security", "identity", "access-control"],
    "security": ["security"],
    "secrets": ["security", "secrets-management"],
    "cost": ["finops", "optimization"],
    "observability": ["monitoring", "logging", "metrics"],
    "incidents": ["failure-modes", "reliability-engineering"],
    "networking": ["networking"],
    "supply_chain": ["supply-chain", "security"],
    "architecture": ["architecture"],
    "cloud": ["aws", "architecture"],
    "devsecops": ["devsecops", "security"],
    "env_example": ["secrets", "configuration"],
}

DOMAIN_DEFAULT_SERVICE = {
    "terraform": "HashiCorp Terraform",
    "docker": "Docker", "dockerfile": "Docker", "docker_compose": "Docker Compose",
    "k8s": "Kubernetes", "kubernetes": "Kubernetes",
    "iam": "AWS IAM", "secrets": "Secrets Management", "security": "Security",
    "supply_chain": "Supply Chain Security", "incidents": "Cloud Incident Response",
    "networking": "AWS Networking", "env_example": "Application Configuration",
    "devsecops": "DevSecOps", "observability": "Observability",
    "cost": "AWS Cost Management", "architecture": "AWS Architecture", "cloud": "AWS",
}

# Ordered: first match wins. Normalizes synonyms to a canonical service label.
SERVICE_PATTERNS = [
    (r"\beks\b|elastic kubernetes service", "AWS EKS"),
    (r"\becs\b|fargate", "AWS ECS"),
    (r"\blambda\b", "AWS Lambda"),
    (r"secrets manager", "AWS Secrets Manager"),
    (r"parameter store|\bssm\b|systems manager", "AWS Systems Manager"),
    (r"\bkms\b|envelope encryption", "AWS KMS"),
    (r"guardduty", "Amazon GuardDuty"),
    (r"cloudtrail", "AWS CloudTrail"),
    (r"cloudwatch", "Amazon CloudWatch"),
    (r"\bwaf\b", "AWS WAF"),
    (r"\birsa\b|instance profile|assume\s?role|least privilege|\biam\b", "AWS IAM"),
    (r"transit gateway|privatelink|\bvpc\b|subnet|nat gateway|flow log", "Amazon VPC"),
    (r"\bs3\b", "Amazon S3"),
    (r"\brds\b|aurora", "Amazon RDS"),
    (r"dynamodb", "Amazon DynamoDB"),
    (r"\balb\b|\bnlb\b|load balancer", "Elastic Load Balancing"),
    (r"\bvault\b", "HashiCorp Vault"),
    (r"opentelemetry|\botel\b", "OpenTelemetry"),
    (r"prometheus", "Prometheus"),
    (r"cosign|sigstore", "Sigstore Cosign"),
    (r"\btrivy\b", "Trivy"),
    (r"\bfalco\b", "Falco"),
    (r"github actions", "GitHub Actions"),
    (r"terraform", "HashiCorp Terraform"),
    (r"docker compose", "Docker Compose"),
    (r"dockerfile|docker", "Docker"),
    (r"kubernetes|kubelet|networkpolicy|kubectl|\bpod\b|deployment", "Kubernetes"),
]

AWS_RE = re.compile(
    r"\b(aws|ec2|eks|ecs|s3|rds|vpc|iam|lambda|dynamodb|cloudwatch|fargate|"
    r"guardduty|cloudtrail|kms|secrets manager|parameter store|ssm|irsa|alb|nlb|"
    r"aurora|elasticache|sqs|sns|transit gateway|privatelink|savings plan|"
    r"well-architected|nat gateway|ecr|sts|control tower|organizations)\b", re.I)
GCP_RE = re.compile(r"\b(gcp|gke|google cloud|gcs|bigquery)\b", re.I)
AZURE_RE = re.compile(r"\b(azure|aks)\b", re.I)

EXAMPLE_STEMS = {"backend_deployment_service_kb", "docker_local_stack_kb"}

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def normspace(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def kebab(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    return s


def bullets(items) -> str:
    return "\n".join(f"- {normspace(x)}" for x in items if x and str(x).strip())


def numbered(items) -> str:
    out = []
    n = 1
    for x in items:
        if x and str(x).strip():
            out.append(f"{n}. {normspace(x)}")
            n += 1
    return "\n".join(out)


def detect_service(blob: str, domain: str) -> str:
    low = blob.lower()
    for pat, label in SERVICE_PATTERNS:
        if re.search(pat, low):
            return label
    return DOMAIN_DEFAULT_SERVICE.get(domain, "Other")


def detect_provider(blob: str) -> str:
    a, g, z = bool(AWS_RE.search(blob)), bool(GCP_RE.search(blob)), bool(AZURE_RE.search(blob))
    distinct = sum([a, g, z])
    if distinct > 1:
        return "multi"
    if a:
        return "aws"
    if g:
        return "gcp"
    if z:
        return "azure"
    return "multi"  # provider-agnostic (generic docker/k8s/terraform concepts)


def detect_importance(domain: str, concept: str, category: str, content: str, example: bool) -> str:
    head = f"{concept} {category}".lower()
    if domain == "incidents":
        return "critical"
    if "critical" in head:
        return "critical"
    if domain in {"iam", "secrets", "security", "supply_chain", "networking", "devsecops"}:
        return "high"
    if example:
        return "medium"
    body = content.lower()
    if domain in {"terraform", "kubernetes", "k8s", "cloud", "architecture"}:
        signals = ["least privilege", "encryption", "rbac", "hardening", "public access",
                   "secret", "security group", "privilege escalation", "block public"]
        return "high" if any(k in body for k in signals) else "medium"
    return "medium"  # cost, observability, docker, fallback


def build_tags(file_tags, domain: str, service: str) -> list[str]:
    """Deterministic inference signals (domain, inferred tags, service) lead so they
    are never truncated; curated file-level tags follow. Capped to keep payloads tight."""
    tags: list[str] = []

    def add(t):
        t = kebab(t)
        if t and t not in tags:
            tags.append(t)

    add(domain)
    for t in DOMAIN_INFERENCE_TAGS.get(domain, [domain]):
        add(t)
    add(service)
    for t in (file_tags or []):
        add(t)
    return tags[:16]


def assign_chunk_hints(categories: list[str]) -> list[str]:
    """Mark category-run boundaries for the downstream semantic chunker.
    start  = a new semantic group begins here (safe cut BEFORE this entry)
    continue = same group as the previous entry
    end    = last entry of the group (safe cut AFTER this entry)
    A single-entry group is marked 'start' (standalone, self-contained chunk).
    """
    n = len(categories)
    hints = [None] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and categories[j + 1] == categories[i]:
            j += 1
        if i == j:
            hints[i] = "start"
        else:
            hints[i] = "start"
            for k in range(i + 1, j):
                hints[k] = "continue"
            hints[j] = "end"
        i = j + 1
    return hints


# --------------------------------------------------------------------------- #
# Content assemblers  -> the self-contained text that will be embedded
# --------------------------------------------------------------------------- #
def assemble_standard(e: dict) -> str:
    body = normspace(e["concept"]) + "\n\n" + normspace(e["description"])
    for title, key in [("Decision rules", "decision_rules"),
                        ("Trade-offs", "tradeoffs"),
                        ("Anti-patterns", "anti_patterns"),
                        ("AWS Well-Architected alignment", "aws_alignment")]:
        items = e.get(key) or []
        bl = bullets(items)
        if bl:
            body += f"\n\n{title}:\n{bl}"
    return body


def assemble_incident(e: dict) -> str:
    body = normspace(e["concept"]) + "\n\n" + normspace(e["description"])
    if e.get("preventive_controls"):
        body += "\n\nPreventive controls:\n" + bullets(e["preventive_controls"])
    if e.get("detection_signals"):
        body += "\n\nDetection signals:\n" + bullets(e["detection_signals"])
    if e.get("remediation_runbook"):
        body += "\n\nRemediation runbook:\n" + numbered(e["remediation_runbook"])
    if e.get("anti_patterns"):
        body += "\n\nAnti-patterns:\n" + bullets(e["anti_patterns"])
    return body


def assemble_tf(e: dict) -> str:
    body = normspace(e["concept"]) + "\n\n" + normspace(e["what_it_does"])
    if e.get("when_to_use"):
        body += "\n\nWhen to use:\n" + bullets(e["when_to_use"])
    if e.get("best_practices"):
        body += "\n\nBest practices:\n" + bullets(e["best_practices"])
    if e.get("security_considerations"):
        body += "\n\nSecurity considerations:\n" + bullets(e["security_considerations"])
    if e.get("code_reference"):
        body += "\n\nTerraform resources: " + normspace(e["code_reference"])
    return body


# --------------------------------------------------------------------------- #
# Canonical entry builder
# --------------------------------------------------------------------------- #
def make_canonical(*, source_id, concept, category, content, domain, file_tags,
                   rel_path, stem, example, used_ids) -> dict:
    blob = f"{concept} {category} {content} {' '.join(file_tags or [])}"
    service = detect_service(f"{concept} {category}", domain) \
        if detect_service(f"{concept} {category}", domain) != DOMAIN_DEFAULT_SERVICE.get(domain) \
        else detect_service(blob, domain)
    provider = detect_provider(blob)
    importance = detect_importance(domain, concept, category, content, example)
    resource_type = "terraform" if rel_path.endswith(".tf") else DOMAIN_RESOURCE_TYPE.get(domain, "other")

    gid = f"{domain}/{stem}::{source_id}"
    if gid in used_ids:
        suffix = 2
        while f"{gid}-{suffix}" in used_ids:
            suffix += 1
        gid = f"{gid}-{suffix}"
    used_ids.add(gid)

    return {
        "id": gid,
        "title": normspace(concept),
        "domain": domain,
        "service": service,
        "category": normspace(category),
        "content": content,
        "tags": build_tags(file_tags, domain, service),
        "importance": importance,
        "cloud_provider": provider,
        "resource_type": resource_type,
        "chunk_hint": None,  # filled in after all entries of a file are built
        "source": {"file": rel_path, "source_id": source_id},
    }


# --------------------------------------------------------------------------- #
# Per-file processing
# --------------------------------------------------------------------------- #
def domain_of(path: Path) -> str:
    return path.parent.name


def process_kb_file(path: Path, stats: dict, all_entries: list, used_ids: set) -> dict | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    rel = path.relative_to(REPO).as_posix()
    stem = path.stem
    domain = domain_of(path)
    meta = data.get("metadata", {})
    file_tags = meta.get("tags", [])
    example = (domain in {"dockerfile", "docker_compose", "env_example"}
               or stem in EXAMPLE_STEMS
               or (meta.get("id", "").startswith("security_") and meta.get("id", "").endswith("_notes_kb")))

    # --- the master index is metadata, NOT knowledge: do not embed it ---------
    if "entries" not in data and "knowledge_base_files" in data:
        stats["index_files"] += 1
        eval_qs = data.get("query_examples", [])
        return {
            "file_name": rel,
            "domain": domain,
            "resource_type": "other",
            "generated_by": GENERATED_BY,
            "note": ("Master index / Qdrant ingestion schema — intentionally NOT "
                     "converted into embeddable chunks (it is corpus metadata, not "
                     "knowledge). Its query_examples are preserved as a retrieval "
                     "evaluation set in evaluation_queries.json."),
            "entry_count": 0,
            "evaluation_queries": eval_qs,
            "cleaned_entries": [],
        }

    raw_entries = data.get("entries", [])
    cleaned = []
    seen_hashes = {}
    for e in raw_entries:
        concept = e.get("concept")
        description = e.get("description")
        category = e.get("category", domain)
        # Drop broken / incomplete entries (Task 1)
        if not concept or not description:
            stats["dropped_incomplete"] += 1
            continue
        is_incident = "preventive_controls" in e or "remediation_runbook" in e
        content = assemble_incident(e) if is_incident else assemble_standard(e)
        # Within-file exact-duplicate removal (Task 1)
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if h in seen_hashes:
            stats["dropped_duplicate"] += 1
            continue
        seen_hashes[h] = True
        entry = make_canonical(source_id=e.get("id", kebab(concept)), concept=concept,
                               category=category, content=content, domain=domain,
                               file_tags=file_tags, rel_path=rel, stem=stem,
                               example=example, used_ids=used_ids)
        cleaned.append(entry)

    hints = assign_chunk_hints([c["category"] for c in cleaned])
    for c, hint in zip(cleaned, hints):
        c["chunk_hint"] = hint
    all_entries.extend(cleaned)

    return {
        "file_name": rel,
        "domain": domain,
        "resource_type": DOMAIN_RESOURCE_TYPE.get(domain, "other"),
        "generated_by": GENERATED_BY,
        "source_title": meta.get("title", ""),
        "entry_count": len(cleaned),
        "cleaned_entries": cleaned,
    }


def process_tf_files(tf_spec: dict, stats: dict, all_entries: list, used_ids: set) -> list[dict]:
    outputs = []
    for rel_path, spec in tf_spec["files"].items():
        domain = spec["domain"]
        stem = Path(rel_path).stem
        cleaned = []
        for e in spec["entries"]:
            content = assemble_tf(e)
            entry = make_canonical(source_id=e["source_id"], concept=e["concept"],
                                   category=e["category"], content=content, domain=domain,
                                   file_tags=[], rel_path=rel_path, stem=stem,
                                   example=False, used_ids=used_ids)
            cleaned.append(entry)
        hints = assign_chunk_hints([c["category"] for c in cleaned])
        for c, hint in zip(cleaned, hints):
            c["chunk_hint"] = hint
        all_entries.extend(cleaned)
        stats["tf_files"] += 1
        outputs.append({
            "file_name": rel_path,
            "domain": domain,
            "resource_type": "terraform",
            "generated_by": GENERATED_BY,
            "source_title": spec.get("title", ""),
            "note": ("Derived from Terraform (.tf) source. Each entry explains what the "
                     "resources do, when to use them, best practices, and security "
                     "considerations — grounded strictly in the file's own comments and "
                     "resource definitions. Raw HCL is not embedded without explanation."),
            "entry_count": len(cleaned),
            "cleaned_entries": cleaned,
        })
    return outputs


# --------------------------------------------------------------------------- #
# Cross-file near-duplicate detection (report only; nothing deleted)
# --------------------------------------------------------------------------- #
def token_set(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{4,}", text.lower())}


def find_cross_file_overlaps(entries: list, threshold: float = 0.3):
    sets = [(e["id"], e["source"]["file"], token_set(e["content"])) for e in entries]
    pairs = []
    for (id_a, f_a, s_a), (id_b, f_b, s_b) in combinations(sets, 2):
        if f_a == f_b:
            continue
        inter = len(s_a & s_b)
        if inter == 0:
            continue
        jac = inter / len(s_a | s_b)
        if jac >= threshold:
            pairs.append((round(jac, 3), id_a, id_b))
    pairs.sort(reverse=True)
    return pairs


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    stats = Counter()
    manifest_files = []
    all_entries: list = []
    used_ids: set = set()

    json_files = sorted(CORPUS.rglob("*.json"))
    for path in json_files:
        out = process_kb_file(path, stats, all_entries, used_ids)
        if out is None:
            continue
        rel_dir = path.parent.relative_to(CORPUS)
        out_path = OUT / rel_dir / f"{path.stem}.cleaned.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_files.append({"output": out_path.relative_to(REPO).as_posix(),
                               "source": out["file_name"],
                               "domain": out["domain"],
                               "entry_count": out["entry_count"]})
        if "evaluation_queries" in out:
            # the master index is counted via stats["index_files"], not as a KB file
            (OUT / "evaluation_queries.json").write_text(
                json.dumps({"source": out["file_name"],
                            "description": "Retrieval evaluation queries with expected entry ids. "
                                           "Use for recall@k / faithfulness eval, NOT for embedding.",
                            "queries": out["evaluation_queries"]}, indent=2, ensure_ascii=False),
                encoding="utf-8")
        else:
            stats["kb_files_processed"] += 1

    # Terraform .tf files
    tf_spec = json.loads(TF_ENTRIES_FILE.read_text(encoding="utf-8"))
    for out in process_tf_files(tf_spec, stats, all_entries, used_ids):
        rel_dir = Path(out["file_name"]).parent.relative_to("rag/corpus")
        out_path = OUT / rel_dir / f"{Path(out['file_name']).stem}.cleaned.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_files.append({"output": out_path.relative_to(REPO).as_posix(),
                               "source": out["file_name"],
                               "domain": out["domain"],
                               "entry_count": out["entry_count"]})

    overlaps = find_cross_file_overlaps(all_entries)

    # ---- distributions ----
    dist = {
        "by_domain": dict(Counter(e["domain"] for e in all_entries)),
        "by_resource_type": dict(Counter(e["resource_type"] for e in all_entries)),
        "by_cloud_provider": dict(Counter(e["cloud_provider"] for e in all_entries)),
        "by_importance": dict(Counter(e["importance"] for e in all_entries)),
        "by_chunk_hint": dict(Counter(e["chunk_hint"] for e in all_entries)),
    }

    manifest = {
        "generated_by": GENERATED_BY,
        "schema": ["id", "title", "domain", "service", "category", "content",
                   "tags", "importance", "cloud_provider", "resource_type",
                   "chunk_hint", "source"],
        "totals": {
            "source_files_processed": stats["kb_files_processed"] + stats["tf_files"] + stats["index_files"],
            "kb_files": stats["kb_files_processed"],
            "tf_files": stats["tf_files"],
            "index_files": stats["index_files"],
            "cleaned_entries": len(all_entries),
            "dropped_incomplete": stats["dropped_incomplete"],
            "dropped_duplicate": stats["dropped_duplicate"],
        },
        "distributions": dist,
        "files": manifest_files,
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- cross-file overlap report ----
    write_report(stats, dist, len(all_entries), overlaps, manifest_files)

    print(f"Cleaned {len(all_entries)} entries from "
          f"{stats['kb_files_processed']} KB + {stats['tf_files']} tf + {stats['index_files']} index files.")
    print(f"Dropped: {stats['dropped_incomplete']} incomplete, {stats['dropped_duplicate']} duplicate.")
    print(f"Cross-file near-duplicate pairs (Jaccard>=0.3): {len(overlaps)}")
    print(f"Output -> {OUT.relative_to(REPO).as_posix()}/")


def write_report(stats, dist, total, overlaps, manifest_files):
    lines = []
    lines.append("# DevSecOps RAG Corpus — Cleaning & Normalization Report\n")
    lines.append(f"Generated by `{GENERATED_BY}` (deterministic, re-runnable).\n")
    lines.append("## Summary\n")
    lines.append(f"- Cleaned entries: **{total}**")
    lines.append(f"- KB files: {stats['kb_files_processed']} · Terraform files: {stats['tf_files']} · Index files: {stats['index_files']}")
    lines.append(f"- Dropped incomplete entries (missing concept/description): {stats['dropped_incomplete']}")
    lines.append(f"- Dropped exact within-file duplicates: {stats['dropped_duplicate']}\n")

    lines.append("## Canonical schema\n")
    lines.append("```json")
    lines.append(json.dumps({
        "id": "domain/file::source_id", "title": "", "domain": "", "service": "",
        "category": "", "content": "self-contained, embeddable text",
        "tags": [], "importance": "low|medium|high|critical",
        "cloud_provider": "aws|gcp|azure|multi",
        "resource_type": "terraform|docker|kubernetes|security|architecture|ci_cd|observability|cost|other",
        "chunk_hint": "start|continue|end",
        "source": {"file": "rag/corpus/...", "source_id": "original-id"},
    }, indent=2))
    lines.append("```\n")

    for title, key in [("Entries by domain", "by_domain"),
                       ("Entries by resource_type", "by_resource_type"),
                       ("Entries by cloud_provider", "by_cloud_provider"),
                       ("Entries by importance", "by_importance"),
                       ("Entries by chunk_hint", "by_chunk_hint")]:
        lines.append(f"### {title}\n")
        for k, v in sorted(dist[key].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {k}: {v}")
        lines.append("")

    lines.append("## Cross-file near-duplicate candidates\n")
    lines.append("Pairs are **reported, not deleted** — per the original corpus audit, overlapping "
                 "entries (e.g. the EKS-vs-ECS-vs-Lambda framework appearing in both the AWS patterns "
                 "and EKS KBs) cover the same topic from different angles and should be linked, not "
                 "merged. Review these for the downstream chunker / dedup policy.\n")
    if not overlaps:
        lines.append("_No cross-file pairs above Jaccard 0.3._\n")
    else:
        lines.append("| Jaccard | Entry A | Entry B |")
        lines.append("|---|---|---|")
        for jac, a, b in overlaps[:25]:
            lines.append(f"| {jac} | `{a}` | `{b}` |")
        lines.append("")

    lines.append("## Key decisions\n")
    lines.append("1. **Body preserved verbatim** (whitespace-normalized only). Terminology "
                 "normalization is applied to the metadata layer (`tags`, `service`) — which drives "
                 "hybrid-retrieval filtering — rather than rewriting infra guidance, to guarantee "
                 "technical accuracy. The corpus was already terminologically consistent.")
    lines.append("2. **Master index excluded from embeddings.** `terraform/aws_infra_kb_index.json` is "
                 "corpus metadata, not knowledge; embedding it would pollute retrieval. Its "
                 "`query_examples` are preserved as `evaluation_queries.json` for recall@k testing.")
    lines.append("3. **`.tf` files explained, not dumped.** Each Terraform file is converted to "
                 "knowledge entries (what it does / when to use / best practices / security "
                 "considerations) grounded strictly in the file's own comments and resources.")
    lines.append("4. **`chunk_hint` marks category-run boundaries**: `start` opens a semantic group "
                 "(safe to cut before), `continue` stays in it, `end` closes it (safe to cut after). "
                 "Each entry remains a complete ~400-600 token unit — no aggressive splitting.")
    lines.append("5. **Near-duplicates surfaced, not silently removed**, so the human/owner controls "
                 "the dedup policy. Only exact within-file duplicates are auto-removed.\n")

    (OUT / "CLEANING_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
