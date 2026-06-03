"""Unit tests for the Terraform plan → Infrastructure Summary parser.

Pure logic — no terraform binary required. Covers the resource-count parser
(Phase 2) and the category model (Phase 3).
"""

import json

from backend.app.services.terraform_pipeline.plan_summary import (
    build_infrastructure_summary,
    categorize_resources,
    parse_resource_counts,
)


def _change(rtype: str, actions):
    return {"type": rtype, "change": {"actions": actions}}


def test_parse_counts_only_creates():
    plan = {
        "resource_changes": [
            _change("aws_vpc", ["create"]),
            _change("aws_subnet", ["create"]),
            _change("aws_subnet", ["create"]),
            _change("aws_db_instance", ["no-op"]),     # ignored
            _change("aws_instance", ["delete"]),        # ignored
            _change("aws_eip", ["delete", "create"]),   # replace → counted
        ]
    }
    counts = parse_resource_counts(plan)
    assert counts == {"aws_vpc": 1, "aws_subnet": 2, "aws_eip": 1}


def test_parse_counts_handles_missing_fields():
    plan = {
        "resource_changes": [
            {"change": {"actions": ["create"]}},   # no type → skipped
            {"type": "aws_vpc"},                    # no change → skipped
            "not-a-dict",                            # junk → skipped
            _change("aws_s3_bucket", ["create"]),
        ]
    }
    assert parse_resource_counts(plan) == {"aws_s3_bucket": 1}


def test_parse_counts_empty_plan():
    assert parse_resource_counts({}) == {}
    assert parse_resource_counts({"resource_changes": []}) == {}


def test_categorize_groups_and_orders():
    counts = {
        "aws_vpc": 1,
        "aws_subnet": 4,
        "aws_eks_cluster": 1,
        "aws_db_instance": 1,
        "aws_s3_bucket": 1,
        "aws_security_group": 2,
    }
    summary = categorize_resources(counts)

    assert summary["total_resources"] == 10
    assert summary["resource_counts"] == counts

    names = [c["name"] for c in summary["categories"]]
    # Canonical order, only non-empty categories present.
    assert names == ["Networking", "Compute", "Database", "Storage", "Security"]

    networking = next(c for c in summary["categories"] if c["name"] == "Networking")
    labels = {i["label"]: i["count"] for i in networking["items"]}
    assert labels == {"VPC": 1, "Subnet": 4}


def test_categorize_unknown_type_falls_back_to_other():
    summary = categorize_resources({"aws_msk_cluster": 1})
    other = next(c for c in summary["categories"] if c["name"] == "Other")
    assert other["items"][0]["label"] == "Msk Cluster"
    assert other["items"][0]["count"] == 1
    # "Other" must be last when present alongside known categories.
    summary2 = categorize_resources({"aws_msk_cluster": 1, "aws_vpc": 1})
    assert summary2["categories"][-1]["name"] == "Other"


def test_build_summary_from_json_text():
    plan = {
        "resource_changes": [
            _change("aws_vpc", ["create"]),
            _change("aws_eks_cluster", ["create"]),
        ]
    }
    summary = build_infrastructure_summary(json.dumps(plan))
    assert summary is not None
    assert summary["total_resources"] == 2
    assert {c["name"] for c in summary["categories"]} == {"Networking", "Compute"}


def test_build_summary_invalid_json_returns_none():
    assert build_infrastructure_summary("} not json {") is None


def test_build_summary_empty_plan_is_zero():
    summary = build_infrastructure_summary(json.dumps({"resource_changes": []}))
    assert summary is not None
    assert summary["total_resources"] == 0
    assert summary["categories"] == []
