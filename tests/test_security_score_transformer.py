"""Test the security score transformer to verify the fix works."""

import sys
import json
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from backend.app.services.security.security_score_transformer import SecurityScoreTransformer


def test_security_score_transformer():
    """Test that transformer produces frontend-expected format."""

    # Mock repository security data (from RepositorySecurityService)
    repository_security = {
        "status": "safe_with_warnings",
        "risk_score": 35,
        "warnings": [
            "Script file detected and should be reviewed: build.sh",
            "Sensitive filename detected: .env",
            "Potential secret-like patterns detected in repository files",
        ],
        "blocked_reasons": [],
        "checks": {
            "blocked_extensions": "passed",
            "prompt_injection_scan": "warning",
            "secret_scan": "warning",
            "size_policy": "passed",
            "script_review": "warning",
        },
        "details": {
            "hard_blocked_files": [],
            "suspicious_files": [".env", "secrets.txt"],
            "soft_script_hits": ["build.sh", "deploy.sh"],
            "prompt_injection_hits": [],
            "secret_hits": [],
            "high_confidence_secret_hits": [],
            "oversized_files": [],
        },
    }

    # Mock environment security data
    env_security_runtime = {
        "score": 90,
        "sensitive_values": ["API_KEY", "DATABASE_PASSWORD"],
        "all_values": ["API_KEY", "DATABASE_PASSWORD", "PORT", "DEBUG"],
    }

    # Transform
    result = SecurityScoreTransformer.transform(repository_security, env_security_runtime)

    # Verify structure
    print("✓ Testing Security Score Transformer")
    print("-" * 50)

    # Check required fields
    required_fields = [
        "score",
        "grade",
        "status",
        "vulnerabilities",
        "critical",
        "high",
        "medium",
        "low",
        "summary",
        "recommendations",
        "env_security",
    ]

    print(f"✓ Checking required fields: {len(required_fields)} fields")
    for field in required_fields:
        assert field in result, f"Missing field: {field}"
        print(f"  • {field}: {repr(result[field])[:60]}...")

    # Verify score calculation
    print(f"\n✓ Security Score Calculation")
    print(f"  • Risk Score (backend): {repository_security['risk_score']}")
    print(f"  • Security Score (frontend): {result['score']} (inverted from risk)")
    print(f"  • Grade: {result['grade']}")
    assert result["score"] == 65, f"Expected score 65, got {result['score']}"
    assert result["grade"] == "C", f"Expected grade C, got {result['grade']}"

    # Verify vulnerability transformation
    print(f"\n✓ Vulnerability Transformation")
    print(f"  • Total vulnerabilities: {len(result['vulnerabilities'])}")
    print(f"  • Critical: {result['critical']}")
    print(f"  • High: {result['high']}")
    print(f"  • Medium: {result['medium']}")
    print(f"  • Low: {result['low']}")
    print(f"  • Breakdown: {result['critical']}C + {result['high']}H + {result['medium']}M + {result['low']}L = {len(result['vulnerabilities'])}")

    for vuln in result["vulnerabilities"][:3]:
        print(f"    - [{vuln['severity'].upper()}] {vuln['title'][:50]}")

    # Verify environment security
    print(f"\n✓ Environment Security Integration")
    print(f"  • Env Score: {result['env_security']['score']}")
    print(f"  • Exposed Secrets: {len(result['env_security']['exposed_secrets'])}")
    print(f"  • Issues: {len(result['env_security']['issues'])}")

    # Verify recommendations
    print(f"\n✓ Recommendations Generated")
    print(f"  • Total: {len(result['recommendations'])}")
    for i, rec in enumerate(result["recommendations"], 1):
        print(f"  {i}. {rec[:60]}...")

    print("\n" + "=" * 50)
    print("✅ All tests passed!")
    print("=" * 50)
    print("\n📊 FULL RESULT:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_security_score_transformer()
