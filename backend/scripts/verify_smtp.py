"""Manual SMTP / invitation-email verification (Phase 12).

This is NOT part of the automated test suite (it sends a real email over Gmail
SMTP). Run it by hand to confirm the live email pipeline works end to end.

Usage (from the repo root, with the project venv active):

    # 1) Validate the resolved SMTP config without sending anything:
    python -m backend.scripts.verify_smtp --check

    # 2) Send a real invitation email to yourself to verify Gmail delivery:
    python -m backend.scripts.verify_smtp --to you@example.com

Config is read from .env via Settings — nothing is hard-coded here. The
temporary password shown is a freshly generated sample (NOT a real account
credential); this script only exercises EmailService + the template.
"""

from __future__ import annotations

import argparse
import sys

from backend.app.core.password_generator import generate_temporary_password
from backend.app.services.core.email_service import EmailError, email_service
from backend.app.services.core.invitation_service import build_accept_url


def _print_config() -> None:
    problems = email_service.config_problems()
    print("-- Resolved SMTP configuration -----------------------------")
    print(f"  From address : {email_service.from_address}")
    print(f"  From name    : {email_service._from_name}")
    print(f"  SMTP login   : {email_service._login_username}")
    print(f"  SMTP host    : {email_service._host}:{email_service._port}")
    print(f"  Enabled      : {email_service.is_enabled()}")
    if problems:
        print("  Problems     :")
        for p in problems:
            print(f"    - {p}")
    print("------------------------------------------------------------")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Gmail SMTP delivery.")
    parser.add_argument("--to", help="Recipient address to send a test invitation email to.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only print the resolved config (no email sent).",
    )
    args = parser.parse_args(argv)

    _print_config()

    if args.check or not args.to:
        if not args.to and not args.check:
            print("\nNothing to do. Pass --to <email> to send a test, or --check.")
        return 0 if email_service.is_enabled() else 1

    if not email_service.is_enabled():
        print("\nSMTP is not enabled/configured — refusing to send. Fix the problems above.")
        return 1

    temp_password = generate_temporary_password()
    print(f"\nSending a test invitation email to {args.to} ...")
    try:
        email_service.send_invitation_email(
            to_email=args.to,
            workspace_name="Sample DevOps Workspace",
            role="DEVOPS_ENGINEER",
            temp_password=temp_password,
            accept_url=build_accept_url("sample-verification-token"),
            invited_by="SMTP Verification Script",
            message="This is a one-off SMTP verification email.",
        )
    except EmailError as exc:
        print(f"FAILED: {exc}")
        return 1

    print("OK — email dispatched. Check the recipient's inbox (and spam folder).")
    print(f"(Sample temporary password used in the email body: {temp_password})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
