"""HTML + plain-text templates for transactional email.

Kept separate from ``email_service`` so the markup can evolve without touching
the SMTP transport. ``render_invitation_email`` returns a
``(subject, html_body, text_body)`` tuple; the HTML uses inline styles only
(email clients strip <style> blocks and have no external CSS) and a table-based
layout for maximum client compatibility (Gmail, Outlook, Apple Mail).

All caller-supplied values are HTML-escaped before interpolation.
"""

from __future__ import annotations

import html
from typing import Optional

# Brand palette — mirrors the frontend's gradient identity (indigo → violet).
_BRAND_PRIMARY = "#6366f1"
_BRAND_PRIMARY_DARK = "#4f46e5"
_INK = "#0f172a"
_MUTED = "#64748b"
_BORDER = "#e2e8f0"
_SURFACE = "#f8fafc"

# Human-readable role labels (mirrors the frontend ROLE_META).
_ROLE_LABELS = {
    "ADMIN": "Admin",
    "DEVOPS_ENGINEER": "DevOps Engineer",
}


def _role_label(role: Optional[str]) -> str:
    key = (role or "").strip().upper()
    return _ROLE_LABELS.get(key, role or "Member")


def render_invitation_email(
    *,
    workspace_name: str,
    role: str,
    login_email: str,
    temp_password: str,
    accept_url: str,
    invited_by: Optional[str] = None,
    message: Optional[str] = None,
    app_name: str = "DevSecOps AI Platform",
) -> tuple[str, str, str]:
    """Render the invitation email. Returns ``(subject, html, text)``."""
    ws = html.escape(workspace_name or "the workspace")
    role_label = html.escape(_role_label(role))
    email_esc = html.escape(login_email or "")
    pw_esc = html.escape(temp_password or "")
    url_esc = html.escape(accept_url or "", quote=True)
    app_esc = html.escape(app_name or "DevSecOps AI Platform")
    inviter = html.escape(invited_by) if invited_by else None
    personal = html.escape(message) if message else None

    subject = f"You're invited to join {workspace_name} on {app_name}"

    invited_line = (
        f"{inviter} has invited you to join" if inviter else "You have been invited to join"
    )

    # ── Plain-text part ──────────────────────────────────────────────────────
    text_lines = [
        f"{app_name}",
        "",
        "Hello,",
        "",
        f"{invited_by + ' has invited you' if invited_by else 'You have been invited'} "
        f"to join the workspace:",
        "",
        f"  Workspace: {workspace_name}",
        f"  Role:      {_role_label(role)}",
        "",
        "Your sign-in credentials:",
        "",
        f"  Login Email:        {login_email}",
        f"  Temporary Password: {temp_password}",
        "",
    ]
    if message:
        text_lines += [f'Message from your admin: "{message}"', ""]
    text_lines += [
        "Accept your invitation and set your own password here:",
        accept_url,
        "",
        "For security, you'll be required to change this temporary password "
        "after your first sign-in.",
        "",
        "If you weren't expecting this invitation you can safely ignore this email.",
        "",
        f"— The {app_name} team",
    ]
    text_body = "\n".join(text_lines)

    # ── HTML part ────────────────────────────────────────────────────────────
    personal_block = (
        f"""
        <tr>
          <td style="padding:0 32px 8px 32px;">
            <div style="background:{_SURFACE};border:1px solid {_BORDER};border-radius:10px;
                        padding:14px 16px;color:{_INK};font-size:14px;font-style:italic;">
              &ldquo;{personal}&rdquo;
            </div>
          </td>
        </tr>"""
        if personal
        else ""
    )

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#eef2ff;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#eef2ff;padding:32px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;
                      box-shadow:0 6px 24px rgba(15,23,42,.08);">

          <!-- Brand header -->
          <tr>
            <td style="background:linear-gradient(135deg,{_BRAND_PRIMARY},{_BRAND_PRIMARY_DARK});
                       padding:28px 32px;">
              <div style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:.2px;">
                {app_esc}
              </div>
              <div style="color:rgba(255,255,255,.85);font-size:13px;margin-top:2px;">
                AI Cloud Engineering Platform
              </div>
            </td>
          </tr>

          <!-- Title -->
          <tr>
            <td style="padding:30px 32px 6px 32px;">
              <div style="display:inline-block;background:{_SURFACE};color:{_BRAND_PRIMARY_DARK};
                          font-size:12px;font-weight:600;padding:5px 12px;border-radius:999px;
                          border:1px solid {_BORDER};">
                You&rsquo;re invited
              </div>
              <h1 style="margin:14px 0 4px 0;color:{_INK};font-size:22px;font-weight:700;">
                Join {ws}
              </h1>
              <p style="margin:0;color:{_MUTED};font-size:14px;">
                {invited_line} <strong style="color:{_INK};">{ws}</strong> as a
                <strong style="color:{_INK};">{role_label}</strong>.
              </p>
            </td>
          </tr>

          <!-- Invitation summary -->
          <tr>
            <td style="padding:20px 32px 4px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="border:1px solid {_BORDER};border-radius:12px;border-collapse:separate;
                            overflow:hidden;">
                <tr>
                  <td style="padding:12px 16px;color:{_MUTED};font-size:13px;width:42%;
                             border-bottom:1px solid {_BORDER};">Workspace</td>
                  <td style="padding:12px 16px;color:{_INK};font-size:13px;font-weight:600;
                             border-bottom:1px solid {_BORDER};">{ws}</td>
                </tr>
                <tr>
                  <td style="padding:12px 16px;color:{_MUTED};font-size:13px;">Role</td>
                  <td style="padding:12px 16px;color:{_INK};font-size:13px;font-weight:600;">
                    {role_label}
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Credentials -->
          <tr>
            <td style="padding:16px 32px 4px 32px;">
              <div style="color:{_INK};font-size:13px;font-weight:700;margin-bottom:8px;">
                Your sign-in credentials
              </div>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                     style="background:{_SURFACE};border:1px solid {_BORDER};border-radius:12px;
                            border-collapse:separate;overflow:hidden;">
                <tr>
                  <td style="padding:12px 16px;color:{_MUTED};font-size:13px;width:42%;
                             border-bottom:1px solid {_BORDER};">Login Email</td>
                  <td style="padding:12px 16px;color:{_INK};font-size:13px;font-weight:600;
                             border-bottom:1px solid {_BORDER};">{email_esc}</td>
                </tr>
                <tr>
                  <td style="padding:12px 16px;color:{_MUTED};font-size:13px;">Temporary Password</td>
                  <td style="padding:12px 16px;">
                    <code style="font-family:'SFMono-Regular',Consolas,Menlo,monospace;font-size:14px;
                                 font-weight:700;color:{_BRAND_PRIMARY_DARK};letter-spacing:.5px;">
                      {pw_esc}
                    </code>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
{personal_block}
          <!-- CTA -->
          <tr>
            <td style="padding:22px 32px 8px 32px;" align="center">
              <a href="{url_esc}"
                 style="display:inline-block;background:linear-gradient(135deg,{_BRAND_PRIMARY},{_BRAND_PRIMARY_DARK});
                        color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;
                        padding:13px 32px;border-radius:10px;">
                Accept Invitation
              </a>
              <div style="margin-top:12px;color:{_MUTED};font-size:12px;">
                or copy this link into your browser:<br />
                <a href="{url_esc}" style="color:{_BRAND_PRIMARY_DARK};word-break:break-all;">{url_esc}</a>
              </div>
            </td>
          </tr>

          <!-- Security note -->
          <tr>
            <td style="padding:8px 32px 28px 32px;">
              <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;
                          padding:12px 14px;color:#92400e;font-size:12.5px;">
                <strong>Security note:</strong> this temporary password is single-use.
                You&rsquo;ll be asked to set your own password right after your first sign-in.
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:{_SURFACE};padding:18px 32px;border-top:1px solid {_BORDER};">
              <p style="margin:0;color:{_MUTED};font-size:12px;line-height:1.5;">
                If you weren&rsquo;t expecting this invitation, you can safely ignore this email.
                <br />&mdash; The {app_esc} team
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    return subject, html_body, text_body
