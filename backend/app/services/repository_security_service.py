import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse


class RepositorySecurityService:
    ALLOWED_HOSTS = {"github.com", "www.github.com"}

    # Extensions vraiment dangereuses / inutiles pour l'analyse
    HARD_BLOCKED_EXTENSIONS = {
        ".exe", ".dll", ".so", ".bin", ".msi", ".scr", ".apk", ".dmg", ".iso"
    }

    # Extensions script à surveiller, mais pas à bloquer automatiquement
    SOFT_SCRIPT_EXTENSIONS = {
        ".bat", ".cmd", ".ps1", ".sh"
    }

    SUSPICIOUS_FILENAMES = {
        ".env",
        ".env.local",
        "id_rsa",
        "id_dsa",
        "secrets.txt",
        "credentials.txt",
    }

    LOW_RISK_DIRS = {
        "docs",
        "doc",
        "tests",
        "test",
        "examples",
        "example",
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

    HIGH_CONFIDENCE_SECRET_PATTERNS = [
        r"AKIA[0-9A-Z]{16}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"AIza[0-9A-Za-z\-_]{35}",
        r"-----BEGIN\s+PRIVATE\s+KEY-----",
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

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "normalized_url": repo_url,
        }

    def scan_repository(self, repo_path: str, max_file_size_bytes: int = 1_000_000) -> Dict[str, Any]:
        repo = Path(repo_path)

        blocked_reasons: List[str] = []
        warnings: List[str] = []

        hard_blocked_files: List[str] = []
        suspicious_files: List[str] = []
        prompt_injection_hits: List[Dict[str, str]] = []
        secret_hits: List[Dict[str, str]] = []
        high_confidence_secret_hits: List[Dict[str, str]] = []
        oversized_files: List[str] = []
        soft_script_hits: List[str] = []

        scanned_files = 0

        for path in repo.rglob("*"):
            if ".git" in path.parts:
                continue
            if not path.is_file():
                continue

            scanned_files += 1
            rel_path = str(path.relative_to(repo)).replace("\\", "/")
            suffix = path.suffix.lower()

            # Hard block seulement pour de vraies extensions à risque
            if suffix in self.HARD_BLOCKED_EXTENSIONS:
                hard_blocked_files.append(rel_path)
                blocked_reasons.append(
                    f"Blocked binary or executable extension detected: {rel_path}"
                )
                continue

            # Scripts: warning seulement
            if suffix in self.SOFT_SCRIPT_EXTENSIONS:
                soft_script_hits.append(rel_path)
                if not self._is_low_risk_path(rel_path):
                    warnings.append(f"Script file detected and should be reviewed: {rel_path}")

            if path.name in self.SUSPICIOUS_FILENAMES:
                suspicious_files.append(rel_path)
                if self._is_low_risk_path(rel_path):
                    warnings.append(f"Sensitive-like filename detected in low-risk area: {rel_path}")
                else:
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

            # Prompt injection hits
            for pattern in self.PROMPT_INJECTION_PATTERNS:
                if re.search(pattern, content, flags=re.IGNORECASE):
                    prompt_injection_hits.append({
                        "file": rel_path,
                        "pattern": pattern,
                    })

            # High-confidence secrets
            for pattern in self.HIGH_CONFIDENCE_SECRET_PATTERNS:
                if re.search(pattern, content, flags=re.IGNORECASE):
                    high_confidence_secret_hits.append({
                        "file": rel_path,
                        "pattern": pattern,
                    })

            # Generic secret-like patterns
            for pattern in self.SECRET_PATTERNS:
                if re.search(pattern, content, flags=re.IGNORECASE):
                    secret_hits.append({
                        "file": rel_path,
                        "pattern": pattern,
                    })

        if prompt_injection_hits:
            warnings.append("Potential prompt injection patterns detected in repository files")

        if secret_hits:
            warnings.append("Potential secret-like patterns detected in repository files")

        if high_confidence_secret_hits:
            blocked_reasons.append("High-confidence secret material detected in repository files")

        risk_score = self._compute_risk_score(
            blocked_reasons=blocked_reasons,
            hard_blocked_files=hard_blocked_files,
            suspicious_files=suspicious_files,
            prompt_injection_hits=prompt_injection_hits,
            secret_hits=secret_hits,
            high_confidence_secret_hits=high_confidence_secret_hits,
            soft_script_hits=soft_script_hits,
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
                "blocked_extensions": "failed" if hard_blocked_files else "passed",
                "prompt_injection_scan": "warning" if prompt_injection_hits else "passed",
                "secret_scan": "failed" if high_confidence_secret_hits else ("warning" if secret_hits else "passed"),
                "size_policy": "warning" if oversized_files else "passed",
                "script_review": "warning" if soft_script_hits else "passed",
            },
            "warnings": sorted(set(warnings)),
            "blocked_reasons": sorted(set(blocked_reasons)),
            "details": {
                "hard_blocked_files": hard_blocked_files,
                "suspicious_files": suspicious_files,
                "soft_script_hits": soft_script_hits,
                "prompt_injection_hits": self._deduplicate_hits(prompt_injection_hits),
                "secret_hits": self._filter_contextual_secret_hits(secret_hits),
                "high_confidence_secret_hits": self._deduplicate_hits(high_confidence_secret_hits),
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

    def _is_low_risk_path(self, rel_path: str) -> bool:
        parts = {part.lower() for part in rel_path.replace("\\", "/").split("/")}
        return any(part in self.LOW_RISK_DIRS for part in parts)

    def _filter_contextual_secret_hits(self, hits: List[Dict[str, str]]) -> List[Dict[str, str]]:
        filtered: List[Dict[str, str]] = []
        for hit in self._deduplicate_hits(hits):
            file_path = hit["file"]
            # On garde tout dans le détail, mais le scoring sera plus faible pour docs/tests/examples
            filtered.append({
                **hit,
                "context": "low_risk_area" if self._is_low_risk_path(file_path) else "normal_area",
            })
        return filtered

    @staticmethod
    def _deduplicate_hits(hits: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen = set()
        deduped = []
        for hit in hits:
            key = (hit.get("file"), hit.get("pattern"))
            if key not in seen:
                seen.add(key)
                deduped.append(hit)
        return deduped

    def _compute_risk_score(
        self,
        blocked_reasons: List[str],
        hard_blocked_files: List[str],
        suspicious_files: List[str],
        prompt_injection_hits: List[Dict[str, str]],
        secret_hits: List[Dict[str, str]],
        high_confidence_secret_hits: List[Dict[str, str]],
        soft_script_hits: List[str],
    ) -> int:
        score = 0

        # Hard blocks = score élevé
        score += len(blocked_reasons) * 50
        score += len(hard_blocked_files) * 40
        score += len(high_confidence_secret_hits) * 50

        # Scripts = léger warning
        score += len(soft_script_hits) * 2

        # Sensitive filenames = warning léger
        score += len(suspicious_files) * 5

        # Prompt injection = plus sérieux
        score += len(prompt_injection_hits) * 12

        # Secret-like patterns = dépend du contexte
        for hit in self._deduplicate_hits(secret_hits):
            if self._is_low_risk_path(hit["file"]):
                score += 2
            else:
                score += 10

        return min(score, 100)

    @staticmethod
    def _decide_status(blocked_reasons: List[str], risk_score: int) -> str:
        if blocked_reasons:
            return "blocked"
        if risk_score >= 20:
            return "safe_with_warnings"
        return "safe"