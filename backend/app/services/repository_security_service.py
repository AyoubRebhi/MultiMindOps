import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse


class RepositorySecurityService:
    ALLOWED_HOSTS = {"github.com", "www.github.com"}

    BLOCKED_EXTENSIONS = {
        ".exe", ".dll", ".so", ".bin", ".msi", ".bat", ".cmd", ".scr",
        ".ps1", ".jar", ".class", ".apk", ".dmg", ".iso"
    }

    SUSPICIOUS_FILENAMES = {
        ".env",
        ".env.local",
        "id_rsa",
        "id_dsa",
        "secrets.txt",
        "credentials.txt",
    }

    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+previous\s+instructions",
        r"ignore\s+all\s+previous\s+instructions",
        r"system\s+prompt",
        r"developer\s+message",
        r"you\s+are\s+chatgpt",
        r"reveal\s+secrets",
        r"disregard\s+prior\s+instructions",
        r"bypass\s+safety",
        r"do\s+not\s+follow\s+the\s+rules",
    ]

    SECRET_PATTERNS = [
        r"AKIA[0-9A-Z]{16}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"AIza[0-9A-Za-z\-_]{35}",
        r"-----BEGIN\s+PRIVATE\s+KEY-----",
        r"(?i)api[_-]?key\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)secret[_-]?key\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)password\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)token\s*=\s*['\"][^'\"]+['\"]",
    ]

    def validate_repo_url(self, repo_url: str) -> Dict[str, Any]:
        repo_url = repo_url.strip()
        parsed = urlparse(repo_url)

        issues: List[str] = []

        if parsed.scheme not in {"http", "https"}:
            issues.append("Repository URL must use http or https")

        if parsed.netloc not in self.ALLOWED_HOSTS:
            issues.append("Only github.com repositories are allowed")

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 2:
            issues.append("Repository URL must contain owner and repository name")

        is_valid = len(issues) == 0

        return {
            "valid": is_valid,
            "issues": issues,
            "normalized_url": repo_url,
        }

    def scan_repository(self, repo_path: str, max_file_size_bytes: int = 1_000_000) -> Dict[str, Any]:
        repo = Path(repo_path)

        blocked_reasons: List[str] = []
        warnings: List[str] = []

        suspicious_files: List[str] = []
        prompt_injection_hits: List[Dict[str, str]] = []
        secret_hits: List[Dict[str, str]] = []
        oversized_files: List[str] = []

        scanned_files = 0

        for path in repo.rglob("*"):
            if ".git" in path.parts:
                continue
            if not path.is_file():
                continue

            scanned_files += 1
            rel_path = str(path.relative_to(repo))

            if path.suffix.lower() in self.BLOCKED_EXTENSIONS:
                suspicious_files.append(rel_path)
                blocked_reasons.append(f"Blocked binary or executable extension detected: {rel_path}")
                continue

            if path.name in self.SUSPICIOUS_FILENAMES:
                suspicious_files.append(rel_path)
                warnings.append(f"Sensitive filename detected: {rel_path}")

            try:
                size = path.stat().st_size
                if size > max_file_size_bytes:
                    oversized_files.append(rel_path)
                    warnings.append(f"Large file skipped during security scan: {rel_path}")
                    continue
            except Exception:
                warnings.append(f"Unable to read file metadata: {rel_path}")
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                warnings.append(f"Unable to read text content: {rel_path}")
                continue

            for pattern in self.PROMPT_INJECTION_PATTERNS:
                if re.search(pattern, content, flags=re.IGNORECASE):
                    prompt_injection_hits.append({
                        "file": rel_path,
                        "pattern": pattern,
                    })

            for pattern in self.SECRET_PATTERNS:
                if re.search(pattern, content, flags=re.IGNORECASE):
                    secret_hits.append({
                        "file": rel_path,
                        "pattern": pattern,
                    })

        if prompt_injection_hits:
            warnings.append("Potential prompt injection patterns detected in repository files")

        if secret_hits:
            warnings.append("Potential secrets detected in repository files")

        risk_score = self._compute_risk_score(
            blocked_reasons=blocked_reasons,
            suspicious_files=suspicious_files,
            prompt_injection_hits=prompt_injection_hits,
            secret_hits=secret_hits,
        )

        status = self._decide_status(
            blocked_reasons=blocked_reasons,
            risk_score=risk_score,
        )

        return {
            "status": status,
            "scanned_files": scanned_files,
            "risk_score": risk_score,
            "checks": {
                "blocked_extensions": "failed" if blocked_reasons else "passed",
                "prompt_injection_scan": "warning" if prompt_injection_hits else "passed",
                "secret_scan": "warning" if secret_hits else "passed",
                "size_policy": "warning" if oversized_files else "passed",
            },
            "warnings": sorted(set(warnings)),
            "blocked_reasons": sorted(set(blocked_reasons)),
            "details": {
                "suspicious_files": suspicious_files,
                "prompt_injection_hits": prompt_injection_hits,
                "secret_hits": secret_hits,
                "oversized_files": oversized_files,
            },
        }

    def run_security_gate(self, repo_url: str, repo_path: str) -> Dict[str, Any]:
        url_validation = self.validate_repo_url(repo_url)

        if not url_validation["valid"]:
            return {
                "status": "blocked",
                "repo_url": repo_url,
                "checks": {
                    "url_validation": "failed",
                },
                "warnings": [],
                "blocked_reasons": url_validation["issues"],
                "details": {},
            }

        scan_result = self.scan_repository(repo_path)

        checks = {
            "url_validation": "passed",
            **scan_result["checks"],
        }

        return {
            "status": scan_result["status"],
            "repo_url": repo_url,
            "checks": checks,
            "warnings": scan_result["warnings"],
            "blocked_reasons": scan_result["blocked_reasons"],
            "details": scan_result["details"],
            "risk_score": scan_result["risk_score"],
            "scanned_files": scan_result["scanned_files"],
        }

    @staticmethod
    def _compute_risk_score(
        blocked_reasons: List[str],
        suspicious_files: List[str],
        prompt_injection_hits: List[Dict[str, str]],
        secret_hits: List[Dict[str, str]],
    ) -> int:
        score = 0
        score += len(blocked_reasons) * 50
        score += len(suspicious_files) * 10
        score += len(prompt_injection_hits) * 15
        score += len(secret_hits) * 20
        return min(score, 100)

    @staticmethod
    def _decide_status(blocked_reasons: List[str], risk_score: int) -> str:
        if blocked_reasons:
            return "blocked"
        if risk_score >= 40:
            return "safe_with_warnings"
        return "safe"