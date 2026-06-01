"""Log redaction filter — masks credentials in log messages.

What this protects
------------------
Any log line that contains a recognisable secret (GitHub PAT, AWS access
key, JWT, Authorization bearer header, password=…) gets the secret
replaced with ``"••• REDACTED •••"`` before it leaves the Python logging
pipeline. This is the last line of defence between "a service accidentally
calls ``logger.info(token)``" and "the token ends up in Loki / CloudWatch
/ stdout".

Design choices
--------------
* This is a **logging.Filter**, not a Formatter, so it runs BEFORE any
  formatter and applies to every handler attached to the root logger.
* Patterns match WELL-KNOWN secret shapes only — we do not try to detect
  "any high-entropy string", which produces false positives that turn
  every log review into a hunt for the real signal. The credentials API
  itself NEVER calls ``logger.info(plaintext)``, so the redactor is a
  defence-in-depth measure, not a primary control.
* The filter is idempotent — re-applying it on an already-redacted line
  is a no-op. Important because some handlers re-format on retry.

Limitations
-----------
* If a caller has already pre-formatted the message into ``record.msg``
  with %-style placeholders, the filter rewrites ``record.msg`` AND
  iterates ``record.args``. If args are exotic (objects with
  ``__str__`` that lazily render a secret), the redactor will only
  catch them once formatted — which Python's logging does before
  emit(). Good enough for the secret shapes we worry about; not a
  bypass-proof generic DLP.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Pattern

# Substitution applied wherever a pattern matches. Eight bullets is enough
# to be obviously "this is masked" without being decorative.
_MASK = "••• REDACTED •••"


def _build_patterns() -> list[Pattern[str]]:
    """Compile the redaction patterns once at import time.

    Each entry targets a specific recognisable secret shape:

    * GitHub fine-grained PAT — ``github_pat_<22>_<59 base62>``
    * GitHub classic PAT      — ``ghp_<36 base62>``
    * GitHub OAuth token      — ``gho_<36>``
    * GitHub Apps token       — ``ghs_<36>``, ``ghr_<36>``, ``ghu_<36>``
    * AWS access key id       — ``AKIA[0-9A-Z]{16}`` (also AGPA/ANPA/etc)
    * AWS secret access key   — assignment-style match because the bare
                                 token shape collides with random base64.
    * JWT                     — ``eyJ<base64>.<base64>.<base64>``
    * Authorization header    — ``Authorization: Bearer <…>``
    * password=<…> / token=<…> in URL or form-encoded strings.
    """
    return [
        # GitHub fine-grained PAT
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
        # GitHub classic PAT + variants
        re.compile(r"\bgh[opsur]_[A-Za-z0-9]{36,}\b"),
        # AWS access key id (AKIA + 16) and related prefixes
        re.compile(r"\b(?:AKIA|ASIA|AGPA|ANPA|AROA|AIDA|AIPA)[0-9A-Z]{16}\b"),
        # AWS secret access key style: "aws_secret_access_key = abc…" or
        # JSON-quoted variants. Matches the assignment, not bare strings,
        # to avoid mauling random base64.
        re.compile(
            r"(?i)(aws[_-]?secret[_-]?access[_-]?key)\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{20,})[\"']?"
        ),
        # JWT — three base64url chunks joined by dots.
        re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
        # Authorization: Bearer <token>
        re.compile(r"(?i)(Authorization\s*:\s*Bearer)\s+[A-Za-z0-9._\-]+"),
        # generic password=… in URL or form-encoded strings.
        re.compile(r"(?i)(\bpassword\s*[:=]\s*)([^\s,&\"']{4,})"),
        # generic token=… as above.
        re.compile(r"(?i)(\btoken\s*[:=]\s*)([^\s,&\"']{8,})"),
    ]


_PATTERNS: list[Pattern[str]] = _build_patterns()


def redact(text: str) -> str:
    """Apply every redaction pattern to ``text`` and return the result.

    Pure function — exposed so tests can assert on the exact mask without
    going through the logging pipeline. Used by the filter below but also
    by call-sites that want to scrub a string before passing it on (e.g.
    error messages routed to the UI).
    """
    if not text:
        return text
    out = text
    for pat in _PATTERNS:
        # Patterns with a capture group restore the group so the SHAPE of
        # the line is preserved ("Authorization: Bearer •••") while the
        # secret itself is gone. Patterns without a group replace the
        # whole match.
        if pat.groups == 0:
            out = pat.sub(_MASK, out)
        elif pat.groups == 1:
            # Some patterns use a single group for the prefix; substitute
            # ``\1`` + mask. Keep the leading group, replace the rest.
            out = pat.sub(lambda m: m.group(1) + " " + _MASK, out)
        else:
            # Two groups: prefix + secret. Keep prefix, drop secret.
            out = pat.sub(lambda m: m.group(1) + _MASK, out)
    return out


class SecretRedactingFilter(logging.Filter):
    """Logging filter — rewrites ``record.msg`` and ``record.args`` in place.

    Attach once to the root logger; every handler benefits.

        from backend.app.core.log_redaction import install_secret_redactor
        install_secret_redactor()

    The filter NEVER raises — a malformed message must still reach the
    log handler (with whatever level it carried). Failing closed here
    would silently lose error logs during an incident.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Strings come through msg with no args; pre-format messages
            # come through msg='%s' + args=(...). We redact whichever
            # carries the actual content.
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _redact_value(v) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(_redact_value(a) for a in record.args)
        except Exception:
            # Logging filters must not raise — leaving the record
            # un-redacted is worse than nothing on this specific line,
            # but better than dropping the record entirely.
            pass
        return True


def _redact_value(value):
    """Best-effort string-coerce + redact for individual log args."""
    if isinstance(value, str):
        return redact(value)
    return value


_INSTALLED = False


def install_secret_redactor() -> None:
    """Attach the redactor to the root logger. Idempotent.

    Call once at process boot — after ``setup_utf8_encoding`` so the
    encoding fix is in place before the filter starts touching strings.
    Subsequent calls are no-ops; the module-level flag prevents
    duplicate filters on the same logger.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    root = logging.getLogger()
    # Avoid stacking duplicates if a test re-imports the module.
    if not any(isinstance(f, SecretRedactingFilter) for f in root.filters):
        root.addFilter(SecretRedactingFilter())
    # Also attach to every existing handler so child loggers that bypass
    # the root filter via propagate=False (some libs do this) still get
    # redacted output.
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactingFilter) for f in handler.filters):
            handler.addFilter(SecretRedactingFilter())
    _INSTALLED = True


def reset_for_tests() -> None:
    """Remove the installed filter — used only by the test suite.

    Production code never calls this. Logging filters are process-global
    so a test that wants to exercise the un-filtered path needs an
    explicit reset.
    """
    global _INSTALLED
    root = logging.getLogger()
    root.filters = [f for f in root.filters if not isinstance(f, SecretRedactingFilter)]
    for handler in root.handlers:
        handler.filters = [f for f in handler.filters if not isinstance(f, SecretRedactingFilter)]
    _INSTALLED = False
