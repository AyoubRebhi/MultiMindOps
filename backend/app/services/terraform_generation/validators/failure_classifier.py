"""
Terraform failure classification.

A failed Terraform validation/init is NOT one thing. The pipeline must tell apart
problems that mean "the generated HCL is bad" from problems that mean "the box
running terraform could not reach the provider registry". The former is a real
generation defect; the latter is an environment outage that must NOT discard the
generated artifacts or block the workflow.

Classes
-------
* ``NETWORK_ERROR``          — terraform could not reach the registry/network
                              (DNS failure, connection refused/timeout, TLS).
* ``PROVIDER_FETCH_FAILED``  — registry reachable but provider install failed
                              (version query, download, checksum mismatch).
* ``VALIDATION_FAILED``      — a genuine HCL/semantic/security defect
                              (hcl2 parse error, `terraform validate` error,
                              critical security finding, fmt drift).

``NETWORK_ERROR`` and ``PROVIDER_FETCH_FAILED`` are *recoverable* — the artifacts
are fine and the phase can be retried once connectivity returns. ``VALIDATION_
FAILED`` is not recoverable by a retry.
"""

from __future__ import annotations

from typing import Optional

from backend.app.services.terraform_generation.validators.models import (
    TerraformValidationResult,
)

# ── Classification labels ────────────────────────────────────────────────────

NETWORK_ERROR = "NETWORK_ERROR"
PROVIDER_FETCH_FAILED = "PROVIDER_FETCH_FAILED"
VALIDATION_FAILED = "VALIDATION_FAILED"

_RECOVERABLE = {NETWORK_ERROR, PROVIDER_FETCH_FAILED}

# Substrings (lower-cased) that indicate a networking problem reaching the
# registry rather than a defect in the generated configuration.
_NETWORK_MARKERS = (
    "could not connect",
    "cannot connect",
    "connection refused",
    "connection reset",
    "no such host",
    "dial tcp",
    "i/o timeout",
    "timeout while contacting",
    "timed out",
    "tls handshake",
    "network is unreachable",
    "temporary failure in name resolution",
    "name resolution",
    "server misbehaving",
    "registry.terraform.io",
    "registry service is unreachable",
    "context deadline exceeded",
    "eof",
    "503 service unavailable",
    "502 bad gateway",
    "504 gateway",
)

# Substrings indicating provider acquisition failed (registry reachable, but the
# install/version step failed).
_PROVIDER_MARKERS = (
    "failed to query available provider packages",
    "failed to install provider",
    "could not retrieve the list of available versions",
    "error while installing",
    "checksum",
    "the given provider",
    "no available releases match",
    "failed to obtain dependency lock",
    "inconsistent dependency lock file",
)


def is_recoverable(classification: Optional[str]) -> bool:
    """True when the failure is an environment issue, not a config defect."""
    return classification in _RECOVERABLE


def classify_terraform_output(text: Optional[str]) -> Optional[str]:
    """Classify a raw terraform stdout/stderr blob.

    Returns ``NETWORK_ERROR`` / ``PROVIDER_FETCH_FAILED`` / ``VALIDATION_FAILED``,
    or ``None`` when the text shows no recognisable error. Network markers win
    over provider markers because a registry that is unreachable manifests as
    both ("failed to query available provider packages: ... dial tcp ...") and
    the actionable root cause is the network.
    """
    if not text:
        return None
    lowered = text.lower()
    has_network = any(m in lowered for m in _NETWORK_MARKERS)
    has_provider = any(m in lowered for m in _PROVIDER_MARKERS)
    if has_network:
        return NETWORK_ERROR
    if has_provider:
        return PROVIDER_FETCH_FAILED
    return None


def classify_validation_result(
    result: TerraformValidationResult,
) -> Optional[str]:
    """Classify a :class:`TerraformValidationResult`.

    Returns ``None`` when validation did not block. Otherwise returns one of the
    three labels. Genuine config defects (hcl2 parse / terraform validate errors,
    critical security findings) always take precedence so a real defect can never
    be masked as a transient network issue.
    """
    if not result.is_blocking:
        return None

    blocking = {"error", "critical"}
    issues = [i for i in result.issues if i.severity in blocking]
    security_blocking = [s for s in result.security_issues if s.severity in blocking]

    # A real config/semantic/security defect wins immediately.
    genuine = [i for i in issues if i.source in ("hcl2_parse", "terraform_validate")]
    if genuine or security_blocking:
        return VALIDATION_FAILED

    # Otherwise inspect init/fmt failures for network / provider signatures.
    env_text = " ".join(
        i.message for i in issues if i.source in ("terraform_init", "terraform_fmt")
    )
    classification = classify_terraform_output(env_text)
    if classification:
        return classification

    # A terraform_init failure with no recognisable network/provider signature is
    # most likely a real config error surfaced at init time → do not mask it.
    return VALIDATION_FAILED
