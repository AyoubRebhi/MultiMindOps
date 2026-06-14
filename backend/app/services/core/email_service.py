"""Email delivery service (Gmail SMTP).

The single chokepoint for outbound transactional email. Nothing else in the
codebase imports ``smtplib`` — callers (e.g. ``invitation_service``) depend on
this service so the SMTP details, error mapping and config resolution live in
exactly one place:

    InvitationService → EmailService → Gmail SMTP

Configuration is read ONLY from ``settings`` (which loads ``.env``); nothing is
hard-coded. See ``backend/app/core/config.py`` for the field declarations.

Gmail SMTP gotcha (handled here): the SMTP AUTH *username* must be the full
Gmail address. The project's ``.env`` sets ``SMTP_USERNAME`` to a friendly app
label, so we resolve the actual login from ``EMAIL_FROM`` when ``SMTP_USERNAME``
is not itself an email — and use the label only as the From display name.

Errors are normalized to two exception types so callers don't have to know the
``smtplib`` taxonomy:

* ``EmailConfigError``  — the service is disabled or missing required config.
* ``EmailDeliveryError`` — SMTP accepted the connection attempt but the send
  failed (auth rejected, recipient refused, timeout, relay unavailable, …).
  The message is human-readable and SAFE to surface to an admin (it never
  contains the SMTP password — see ``__init__`` redaction note).
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Base class for email-layer failures."""


class EmailConfigError(EmailError):
    """The email subsystem is disabled or not fully configured."""


class EmailDeliveryError(EmailError):
    """A configured send was attempted but did not succeed."""


@dataclass(frozen=True)
class EmailMessageSpec:
    """A single email to send. ``html_body`` is optional but recommended."""

    to: str
    subject: str
    text_body: str
    html_body: Optional[str] = None


def _looks_like_email(value: str) -> bool:
    value = (value or "").strip()
    return "@" in value and "." in value.split("@")[-1]


class EmailService:
    """SMTP client wrapper. Construct once (module singleton below) or per-test.

    Reading config in ``__init__`` (rather than at class-definition time) means
    a test can build an ``EmailService(custom_settings)`` with monkeypatched
    values without re-importing the module.
    """

    def __init__(self, config=settings):
        self._host = str(getattr(config, "SMTP_HOST", "") or "").strip()
        self._port = int(getattr(config, "SMTP_PORT", 587) or 587)
        self._password = str(getattr(config, "SMTP_PASSWORD", "") or "").strip()
        self._timeout = float(getattr(config, "SMTP_TIMEOUT_SECONDS", 15.0) or 15.0)
        self._enabled = bool(getattr(config, "EMAIL_ENABLED", True))

        raw_username = str(getattr(config, "SMTP_USERNAME", "") or "").strip()
        email_from = str(getattr(config, "EMAIL_FROM", "") or "").strip()
        from_name_cfg = str(getattr(config, "EMAIL_FROM_NAME", "") or "").strip()
        app_name = str(getattr(config, "APP_NAME", "DevSecOps AI Platform") or "").strip()

        # ── Resolve the SMTP AUTH login ──────────────────────────────────────
        # Gmail requires the full address. If SMTP_USERNAME is an email, trust
        # it; otherwise fall back to EMAIL_FROM (the address the app password
        # belongs to). The label form is kept only for the From display name.
        if _looks_like_email(raw_username):
            self._login_username = raw_username
        else:
            self._login_username = email_from

        # From address shown to recipients (and the SMTP MAIL FROM).
        self._from_address = email_from or self._login_username

        # Friendly display name: explicit config → label username → app name.
        if from_name_cfg:
            self._from_name = from_name_cfg
        elif raw_username and not _looks_like_email(raw_username):
            self._from_name = raw_username
        else:
            self._from_name = app_name

        if raw_username and not _looks_like_email(raw_username) and self._login_username:
            logger.info(
                "[email] SMTP_USERNAME=%r is not an email; using EMAIL_FROM=%r "
                "for the SMTP login and %r as the From display name.",
                raw_username, self._login_username, self._from_name,
            )

    # ── Introspection ────────────────────────────────────────────────────────

    @property
    def from_address(self) -> str:
        return self._from_address

    def config_problems(self) -> list[str]:
        """Return a list of human-readable config problems (empty == OK)."""
        problems: list[str] = []
        if not self._enabled:
            problems.append("EMAIL_ENABLED is false")
        if not self._host:
            problems.append("SMTP_HOST is not set")
        if not self._password:
            problems.append("SMTP_PASSWORD is not set")
        if not self._login_username:
            problems.append("neither SMTP_USERNAME (as an email) nor EMAIL_FROM is set")
        if not self._from_address:
            problems.append("EMAIL_FROM is not set")
        return problems

    def is_enabled(self) -> bool:
        """True when email is switched on AND fully configured to send."""
        return self._enabled and not self.config_problems()

    # ── Sending ──────────────────────────────────────────────────────────────

    def send(self, spec: EmailMessageSpec) -> None:
        """Send one email. Raises ``EmailConfigError`` / ``EmailDeliveryError``.

        Synchronous and time-boxed by ``SMTP_TIMEOUT_SECONDS`` so a slow relay
        cannot hang the calling request.
        """
        if not self._enabled:
            raise EmailConfigError("Email delivery is disabled (EMAIL_ENABLED=false)")
        problems = self.config_problems()
        if problems:
            raise EmailConfigError("SMTP is not configured: " + "; ".join(problems))

        recipient = (spec.to or "").strip()
        if not _looks_like_email(recipient):
            raise EmailDeliveryError(f"Invalid recipient address: {recipient!r}")

        msg = EmailMessage()
        msg["From"] = formataddr((self._from_name, self._from_address))
        msg["To"] = recipient
        msg["Subject"] = spec.subject
        msg.set_content(spec.text_body or "")
        if spec.html_body:
            msg.add_alternative(spec.html_body, subtype="html")

        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
                server.ehlo()
                # Gmail on 587 requires STARTTLS before AUTH.
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(self._login_username, self._password)
                server.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            # Most common Gmail failure: app password wrong / 2FA not enabled /
            # username mismatch. Do NOT echo the password — exc carries only the
            # server code + message.
            raise EmailDeliveryError(
                "SMTP authentication failed — check SMTP_USERNAME/EMAIL_FROM and "
                f"the Gmail app password (server said: {exc.smtp_code})."
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailDeliveryError(
                f"The recipient address was refused by the server: {recipient}"
            ) from exc
        except smtplib.SMTPSenderRefused as exc:
            raise EmailDeliveryError(
                f"The sender address {self._from_address} was refused by the server."
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise EmailDeliveryError(
                f"SMTP timed out after {self._timeout:.0f}s connecting to "
                f"{self._host}:{self._port}."
            ) from exc
        except (smtplib.SMTPConnectError, ConnectionError, OSError) as exc:
            # OSError covers DNS failures / connection refused / network down.
            raise EmailDeliveryError(
                f"Could not reach the SMTP server {self._host}:{self._port} "
                f"({exc.__class__.__name__})."
            ) from exc
        except smtplib.SMTPException as exc:
            raise EmailDeliveryError(
                f"SMTP delivery failed ({exc.__class__.__name__})."
            ) from exc

        logger.info("[email] sent %r to %s", spec.subject, recipient)

    def send_invitation_email(
        self,
        *,
        to_email: str,
        workspace_name: str,
        role: str,
        temp_password: str,
        accept_url: str,
        invited_by: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Render + send the workspace-invitation email. Raises on failure."""
        # Imported here to avoid a hard import cycle at module load time.
        from backend.app.services.core.email_templates import render_invitation_email

        subject, html_body, text_body = render_invitation_email(
            workspace_name=workspace_name,
            role=role,
            login_email=to_email,
            temp_password=temp_password,
            accept_url=accept_url,
            invited_by=invited_by,
            message=message,
            app_name=str(getattr(settings, "APP_NAME", "DevSecOps AI Platform")),
        )
        self.send(
            EmailMessageSpec(
                to=to_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
            )
        )


# Module singleton — callers import this. Tests can monkeypatch its ``send`` /
# ``send_invitation_email`` or replace the object entirely.
email_service = EmailService()
