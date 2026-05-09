"""
Failure Classifier — deterministic, heuristic-based failure taxonomy system.

Implements a priority-ordered rule chain. Each rule is an independent,
unit-testable callable.  The first matching rule becomes the primary
classification; the second match (if any) becomes the secondary type.

Confidence scores reflect empirical signal strength, not uncertainty —
a high confidence means the rule is very specific and rarely fires falsely.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional

from .remediation_models import ExtractedError, FailureClassification, FailureType

logger = logging.getLogger(__name__)


# ── Rule data structure ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClassificationRule:
    failure_type: FailureType
    confidence: float
    matched_rule: str
    test: Callable[[str, ExtractedError], bool]


# ── Individual rule predicates ────────────────────────────────────────────────

def _base_image_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"(?:pull|manifest|image)\s+.+?(?:not\s+found|not\s+exist|unknown|error)"
        r"|unable\s+to\s+find\s+image"
        r"|no\s+such\s+manifest"
        r"|error\s+response\s+from\s+daemon.*(?:pull|manifest)"
        r"|manifest\s+unknown"
        r"|repository\s+does\s+not\s+exist",
        text, re.IGNORECASE,
    ))


def _permission_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"permission\s+denied"
        r"|access\s+denied"
        r"|operation\s+not\s+permitted"
        r"|EACCES"
        r"|EPERM"
        r"|you\s+do\s+not\s+have\s+(?:sufficient\s+)?permission",
        text, re.IGNORECASE,
    ))


def _syntax_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"SyntaxError"
        r"|syntax\s+error"
        r"|unexpected\s+token"
        r"|unexpected\s+indent"
        r"|invalid\s+syntax"
        r"|parse\s+error"
        r"|unexpected\s+EOF"
        r"|mismatched\s+input"
        r"|expecting\s+.+\s+got"
        r"|IndentationError",
        text, re.IGNORECASE,
    ))


def _network_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"connection\s+refused"
        r"|connection\s+timed?\s+out"
        r"|connection\s+reset"
        r"|network\s+unreachable"
        r"|could\s+not\s+resolve\s+host"
        r"|temporary\s+failure\s+in\s+name\s+resolution"
        r"|getaddrinfo\s+.+\s+failed"
        r"|SSL\s+(?:handshake\s+)?error"
        r"|certificate\s+(?:verify\s+)?(?:failed|error)"
        r"|curl:\s+\((?:6|7|28|35|60)\)"   # curl error codes for network issues
        r"|wget:\s+unable\s+to\s+resolve",
        text, re.IGNORECASE,
    ))


def _package_manager_test(text: str, extracted: ExtractedError) -> bool:
    if extracted.package_manager is None:
        return False
    return bool(re.search(
        r"npm\s+ERR!"
        r"|Could\s+not\s+find\s+a\s+version\s+that\s+satisfies"
        r"|No\s+matching\s+distribution\s+found"
        r"|E:\s+Unable\s+to\s+locate\s+package"
        r"|Package\s+.+\s+was\s+not\s+found"
        r"|Cannot\s+find\s+module\s+'(?!\.)"   # npm module not found (not relative path)
        r"|peer\s+dep(?:endency)?\s+(?:missing|conflict)"
        r"|ERESOLVE\s+unable\s+to\s+resolve"
        r"|error:\s+package\s+.+\s+not\s+found"
        r"|ERROR:\s+No\s+matching\s+distribution",
        text, re.IGNORECASE,
    ))


def _missing_file_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"no\s+such\s+file\s+or\s+directory"
        r"|ENOENT"
        r"|FileNotFoundError"
        r"|cannot\s+find\s+.+\s+file"
        r"|file\s+.+\s+does\s+not\s+exist"
        r"|cannot\s+open\s+.+:\s+no\s+such"
        r"|stat\s+.+:\s+no\s+such\s+file",
        text, re.IGNORECASE,
    ))


def _env_var_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"(?:environment\s+variable|env(?:iron)?(?:ment)?\s+var(?:iable)?)\s+"
        r".+(?:not\s+set|missing|undefined|required|not\s+found)"
        r"|KeyError.*(?:os\.environ|getenv)"
        r"|variable\s+.+\s+is\s+not\s+(?:set|defined)"
        r"|required\s+environment\s+variable\s+.+\s+missing"
        r"|\$\{[A-Z_]+\}\s+.*(?:unset|undefined)",
        text, re.IGNORECASE,
    ))


def _build_context_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"COPY\s+.+:\s+no\s+such"
        r"|ADD\s+.+:\s+no\s+such"
        r"|path\s+.+\s+does\s+not\s+exist\s+(?:in|inside)\s+build\s+context"
        r"|Dockerfile.*not\s+found"
        r"|cannot\s+locate\s+.+Dockerfile"
        r"|context\s+.+\s+not\s+found"
        r"|failed\s+to\s+read\s+Dockerfile",
        text, re.IGNORECASE,
    ))


def _dependency_test(text: str, _extracted: ExtractedError) -> bool:
    return bool(re.search(
        r"ImportError"
        r"|ModuleNotFoundError"
        r"|cannot\s+import\s+name"
        r"|No\s+module\s+named\s+"
        r"|require\(\)\s*:\s*cannot\s+find\s+module"
        r"|Cannot\s+find\s+module\s+'\.{1,2}/"   # relative module not found
        r"|library\s+.+\s+not\s+found"
        r"|undefined\s+reference\s+to"
        r"|symbol\s+.+\s+not\s+found"
        r"|ld\s+returned\s+1\s+exit\s+status",
        text, re.IGNORECASE,
    ))


# ── Ordered rule chain (highest specificity / confidence first) ───────────────
#
# Ordering matters: the first matching rule wins as the PRIMARY classification.
# Rules that are highly specific (rarely fire falsely) go first.

_RULES: List[ClassificationRule] = [
    ClassificationRule(
        failure_type=FailureType.BASE_IMAGE_FAILURE,
        confidence=0.95,
        matched_rule="base_image_pull_or_manifest_error",
        test=_base_image_test,
    ),
    ClassificationRule(
        failure_type=FailureType.BUILD_CONTEXT_FAILURE,
        confidence=0.93,
        matched_rule="dockerfile_copy_add_context_missing",
        test=_build_context_test,
    ),
    ClassificationRule(
        failure_type=FailureType.PERMISSION_FAILURE,
        confidence=0.93,
        matched_rule="permission_denied_or_eacces",
        test=_permission_test,
    ),
    ClassificationRule(
        failure_type=FailureType.SYNTAX_ERROR,
        confidence=0.92,
        matched_rule="syntax_or_parse_error",
        test=_syntax_test,
    ),
    ClassificationRule(
        failure_type=FailureType.ENVIRONMENT_VARIABLE_FAILURE,
        confidence=0.91,
        matched_rule="env_var_missing_or_undefined",
        test=_env_var_test,
    ),
    ClassificationRule(
        failure_type=FailureType.NETWORK_FAILURE,
        confidence=0.90,
        matched_rule="network_or_dns_or_ssl_error",
        test=_network_test,
    ),
    ClassificationRule(
        failure_type=FailureType.PACKAGE_MANAGER_FAILURE,
        confidence=0.89,
        matched_rule="package_manager_resolve_or_install_error",
        test=_package_manager_test,
    ),
    ClassificationRule(
        failure_type=FailureType.MISSING_FILE,
        confidence=0.88,
        matched_rule="file_not_found_enoent",
        test=_missing_file_test,
    ),
    ClassificationRule(
        failure_type=FailureType.DEPENDENCY_FAILURE,
        confidence=0.85,
        matched_rule="import_or_module_or_linker_error",
        test=_dependency_test,
    ),
]


# ── Public API ────────────────────────────────────────────────────────────────

def classify_failure(text: str, extracted: ExtractedError) -> FailureClassification:
    """
    Classify the build failure type from log text and extracted error info.

    Rules fire in priority order. First match → primary type.
    A second scan finds the secondary type (if any).

    Args:
        text: Sanitized (or raw) log text from the build.
        extracted: Previously computed ExtractedError.

    Returns:
        FailureClassification with type, confidence, and matched rule name.
    """
    logger.debug("[FailureClassifier] Running %d rules against %d chars", len(_RULES), len(text))

    primary: Optional[ClassificationRule] = None
    secondary: Optional[FailureType] = None

    for rule in _RULES:
        try:
            matched = rule.test(text, extracted)
        except Exception as exc:
            logger.warning("[FailureClassifier] Rule %s raised: %s", rule.matched_rule, exc)
            continue

        if not matched:
            continue

        if primary is None:
            primary = rule
            logger.info(
                "[FailureClassifier] Primary: type=%s confidence=%.2f rule=%s",
                rule.failure_type.value,
                rule.confidence,
                rule.matched_rule,
            )
        elif secondary is None:
            secondary = rule.failure_type
            logger.debug(
                "[FailureClassifier] Secondary: type=%s rule=%s",
                rule.failure_type.value,
                rule.matched_rule,
            )
            break  # We only need primary + one secondary

    if primary is None:
        logger.info("[FailureClassifier] No rule matched — classifying as unknown_failure")
        return FailureClassification(
            failure_type=FailureType.UNKNOWN_FAILURE,
            confidence=0.30,
            matched_rule="no_rule_matched",
            secondary_type=None,
        )

    return FailureClassification(
        failure_type=primary.failure_type,
        confidence=primary.confidence,
        matched_rule=primary.matched_rule,
        secondary_type=secondary,
    )
