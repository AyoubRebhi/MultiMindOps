"""
Transform backend security data into frontend-expected format.

Converts repository_security (risk_score, warnings, blocked_reasons) and
env_security_runtime into SecurityAnalysis format with score, vulnerabilities,
grade, and recommendations.
"""

from typing import Any, Dict, List, Optional


class SecurityScoreTransformer:
    """Transform backend security data into frontend SecurityAnalysis schema."""

    @staticmethod
    def _score_to_grade(score: int) -> str:
        """Convert numeric score (0-100) to letter grade."""
        if score >= 90:
            return "A+"
        elif score >= 85:
            return "A"
        elif score >= 75:
            return "B"
        elif score >= 65:
            return "C"
        elif score >= 50:
            return "D"
        else:
            return "F"

    @staticmethod
    def _categorize_vulnerability_severity(warning_text: str) -> str:
        """
        Infer severity level from warning text.
        Uses keyword matching to categorize as critical, high, medium, or low.
        """
        critical_keywords = [
            "blocked",
            "secret",
            "executable",
            "high-confidence",
            "dangerous",
            "critical",
        ]
        high_keywords = [
            "prompt injection",
            "malicious",
            "suspicious",
            "potential",
            "script file",
        ]
        medium_keywords = [
            "sensitive",
            "filename",
            "review",
            "warning",
            "detected",
        ]

        text_lower = warning_text.lower()

        for keyword in critical_keywords:
            if keyword in text_lower:
                return "critical"

        for keyword in high_keywords:
            if keyword in text_lower:
                return "high"

        for keyword in medium_keywords:
            if keyword in text_lower:
                return "medium"

        return "low"

    @staticmethod
    def transform(
        repository_security: Optional[Dict[str, Any]],
        env_security_runtime: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Transform repository_security and env_security_runtime into SecurityAnalysis.

        Args:
            repository_security: Output from RepositorySecurityService.scan_repository()
                Contains: status, risk_score, warnings, blocked_reasons, checks, details
            env_security_runtime: Environment variable security analysis
                Contains: sensitive_values, all_values, score (optional)

        Returns:
            SecurityAnalysis dict with: score, grade, vulnerabilities, critical/high/medium/low,
            env_security, summary, recommendations
        """

        if not repository_security:
            repository_security = {}

        if not env_security_runtime:
            env_security_runtime = {}

        # Extract base security score
        risk_score = repository_security.get("risk_score", 0)
        # Convert risk_score to security_score (invert if needed - 0 risk = good score)
        # But risk_score is already 0-100 where higher is worse
        # So we invert: security_score = 100 - risk_score
        security_score = max(0, min(100, 100 - risk_score))

        grade = SecurityScoreTransformer._score_to_grade(security_score)

        # Build vulnerabilities list from warnings and blocked_reasons
        vulnerabilities: List[Dict[str, Any]] = []

        blocked_reasons = repository_security.get("blocked_reasons", [])
        for reason in blocked_reasons:
            severity = SecurityScoreTransformer._categorize_vulnerability_severity(reason)
            vulnerabilities.append(
                {
                    "severity": severity,
                    "title": reason,
                    "description": reason,
                    "file": "repository",
                    "line": 0,
                    "cve": None,
                    "recommendation": f"Review and fix: {reason}",
                }
            )

        warnings = repository_security.get("warnings", [])
        for warning in warnings:
            severity = SecurityScoreTransformer._categorize_vulnerability_severity(warning)
            vulnerabilities.append(
                {
                    "severity": severity,
                    "title": warning,
                    "description": warning,
                    "file": "repository",
                    "line": 0,
                    "cve": None,
                    "recommendation": f"Review and mitigate: {warning}",
                }
            )

        # Count vulnerabilities by severity
        severity_counts = {
            "critical": len([v for v in vulnerabilities if v["severity"] == "critical"]),
            "high": len([v for v in vulnerabilities if v["severity"] == "high"]),
            "medium": len([v for v in vulnerabilities if v["severity"] == "medium"]),
            "low": len([v for v in vulnerabilities if v["severity"] == "low"]),
        }

        # Get security checks status
        checks = repository_security.get("checks", {})
        check_summaries = []
        for check_name, status in checks.items():
            if status == "passed":
                check_summaries.append(f"✓ {check_name.replace('_', ' ')}")
            elif status == "warning":
                check_summaries.append(f"⚠ {check_name.replace('_', ' ')}")
            elif status == "failed":
                check_summaries.append(f"✗ {check_name.replace('_', ' ')}")

        # Build summary
        repo_status = repository_security.get("status", "unknown")
        status_text = {
            "blocked": "Repository is BLOCKED due to security violations",
            "safe_with_warnings": "Repository has security warnings that need review",
            "safe": "Repository passed security checks",
        }.get(repo_status, "Repository security status unknown")

        summary = f"{status_text}. Security Score: {security_score}/100 ({grade}). " f"Total issues: {len(vulnerabilities)}"

        # Build recommendations
        recommendations = []
        recommendations.extend(
            [
                v.get("recommendation", "Review issue")
                for v in vulnerabilities
                if v["severity"] in ("critical", "high")
            ]
        )

        if not repo_status == "safe":
            recommendations.append("Run security scanning on deployment pipeline")
            recommendations.append("Review repository access controls")

        if severity_counts["critical"] > 0:
            recommendations.insert(0, "Address critical vulnerabilities immediately")

        # Parse details for additional insights
        details = repository_security.get("details", {})
        if details.get("high_confidence_secret_hits"):
            recommendations.append("Remove exposed secrets from repository history")

        if details.get("hard_blocked_files"):
            recommendations.append("Remove binary/executable files from repository")

        # Build env_security object
        env_security = {}
        if env_security_runtime:
            env_score = env_security_runtime.get("score", 100)
            exposed_secrets = env_security_runtime.get("sensitive_values", [])
            issues = []

            if exposed_secrets:
                issues.append(f"{len(exposed_secrets)} sensitive variables detected in environment")

            env_security = {
                "score": env_score,
                "exposed_secrets": exposed_secrets,
                "issues": issues,
            }

        return {
            "score": security_score,
            "grade": grade,
            "status": repo_status,
            "vulnerabilities": vulnerabilities,
            "critical": severity_counts["critical"],
            "high": severity_counts["high"],
            "medium": severity_counts["medium"],
            "low": severity_counts["low"],
            "summary": summary,
            "recommendations": recommendations[:5],  # Limit to 5 recommendations
            "checks": check_summaries,
            "env_security": env_security if env_security else None,
        }
