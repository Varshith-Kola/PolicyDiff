"""Notification service — email + webhook (Slack/Discord/generic).

Supports:
  - SMTP email alerts with severity-based HTML styling
  - Generic webhook POST (works with Slack, Discord, or any endpoint)
  - send_alert() dispatches to all configured channels
"""

import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SEVERITY_COLORS = {
    "informational": "#3B82F6",
    "concerning": "#F59E0B",
    "action-needed": "#EF4444",
}

SEVERITY_EMOJI = {
    "informational": "ℹ️",
    "concerning": "⚠️",
    "action-needed": "🚨",
}


# ---------------------------------------------------------------------------
# Email notifications
# ---------------------------------------------------------------------------

def _build_email_html(
    policy_name: str, company: str, severity: str,
    summary: str, key_changes: str, recommendation: str, diff_id: int,
) -> str:
    """Build a beautiful HTML email for a policy change alert."""
    color = SEVERITY_COLORS.get(severity, "#6B7280")
    emoji = SEVERITY_EMOJI.get(severity, "")
    changes = json.loads(key_changes) if key_changes else []

    changes_html = ""
    for change in changes:
        changes_html += f'<li style="margin-bottom:8px;color:#374151;">{change}</li>'

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <div style="background:linear-gradient(135deg,#1e293b,#334155);border-radius:12px;padding:24px;margin-bottom:20px;">
            <h1 style="color:white;margin:0;font-size:24px;">PolicyDiff Alert</h1>
            <p style="color:#94a3b8;margin:4px 0 0 0;font-size:14px;">Policy Change Detected</p>
        </div>
        <div style="background:white;border:1px solid #e5e7eb;border-radius:12px;padding:24px;margin-bottom:16px;">
            <div style="display:flex;align-items:center;margin-bottom:16px;">
                <span style="background:{color};color:white;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;text-transform:uppercase;">
                    {emoji} {severity}
                </span>
            </div>
            <h2 style="color:#111827;margin:0 0 4px 0;font-size:20px;">{policy_name}</h2>
            <p style="color:#6b7280;margin:0 0 16px 0;font-size:14px;">{company}</p>
            <div style="background:#f9fafb;border-radius:8px;padding:16px;margin-bottom:16px;">
                <h3 style="color:#111827;margin:0 0 8px 0;font-size:15px;">Summary</h3>
                <p style="color:#374151;margin:0;font-size:14px;line-height:1.6;">{summary}</p>
            </div>
            {"<div style='margin-bottom:16px;'><h3 style='color:#111827;margin:0 0 8px 0;font-size:15px;'>Key Changes</h3><ul style='margin:0;padding-left:20px;'>" + changes_html + "</ul></div>" if changes_html else ""}
            <div style="background:#eff6ff;border-radius:8px;padding:16px;">
                <h3 style="color:#1e40af;margin:0 0 8px 0;font-size:15px;">Recommendation</h3>
                <p style="color:#1e40af;margin:0;font-size:14px;">{recommendation}</p>
            </div>
        </div>
        <p style="color:#9ca3af;font-size:12px;text-align:center;">
            Sent by PolicyDiff — Your automated policy change monitor
        </p>
    </div>
    """


async def _send_email(
    policy_name: str, company: str, severity: str,
    summary: str, key_changes: str, recommendation: str, diff_id: int,
) -> bool:
    """Send an email alert. Returns True on success."""
    if not all([settings.smtp_user, settings.smtp_password, settings.alert_to_email]):
        logger.debug("Email not configured — skipping")
        return False

    try:
        msg = MIMEMultipart("alternative")
        emoji = SEVERITY_EMOJI.get(severity, "")
        msg["Subject"] = f"{emoji} PolicyDiff: {company} {severity.title()} — {policy_name}"
        msg["From"] = settings.alert_from_email or settings.smtp_user
        msg["To"] = settings.alert_to_email

        plain = f"""PolicyDiff Alert — {severity.upper()}

{policy_name} ({company})

{summary}

Recommendation: {recommendation}
"""
        msg.attach(MIMEText(plain, "plain"))

        html = _build_email_html(
            policy_name, company, severity, summary, key_changes, recommendation, diff_id
        )
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(
                settings.alert_from_email or settings.smtp_user,
                [settings.alert_to_email],
                msg.as_string(),
            )

        logger.info(f"[email] alert sent for {policy_name} (severity: {severity})")
        return True

    except Exception as e:
        logger.error(f"[email] failed to send alert: {e}")
        return False


# ---------------------------------------------------------------------------
# Webhook notifications (Slack / Discord / generic)
# ---------------------------------------------------------------------------

def _build_webhook_payload(
    policy_name: str, company: str, severity: str,
    summary: str, key_changes: str, recommendation: str, diff_id: int,
) -> dict:
    """Build a JSON payload compatible with Slack, Discord, and generic webhooks.

    Uses Slack's Block Kit format, which Discord also accepts via /slack endpoint.
    For generic webhooks, a simple JSON body is sent.
    """
    emoji = SEVERITY_EMOJI.get(severity, "")
    changes = json.loads(key_changes) if key_changes else []
    changes_text = "\n".join(f"  • {c}" for c in changes[:5])

    # Detect if it looks like a Slack or Discord webhook
    webhook_url = settings.webhook_url or ""
    is_slack = "hooks.slack.com" in webhook_url or "discord.com/api/webhooks" in webhook_url

    if is_slack:
        # Slack Block Kit format (also works with Discord's /slack compat endpoint)
        return {
            "text": f"{emoji} PolicyDiff: {severity.upper()} — {policy_name} ({company})",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{emoji} PolicyDiff Alert"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Policy:*\n{policy_name}"},
                        {"type": "mrkdwn", "text": f"*Company:*\n{company}"},
                        {"type": "mrkdwn", "text": f"*Severity:*\n{severity.upper()}"},
                        {"type": "mrkdwn", "text": f"*Diff ID:*\n#{diff_id}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Summary:*\n{summary}"},
                },
                *([{
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Key Changes:*\n{changes_text}"},
                }] if changes_text else []),
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Recommendation:*\n{recommendation}"},
                },
            ],
        }
    else:
        # Generic webhook — simple JSON
        return {
            "event": "policy_change",
            "policy_name": policy_name,
            "company": company,
            "severity": severity,
            "severity_emoji": emoji,
            "summary": summary,
            "key_changes": changes,
            "recommendation": recommendation,
            "diff_id": diff_id,
        }


async def _send_webhook(
    policy_name: str, company: str, severity: str,
    summary: str, key_changes: str, recommendation: str, diff_id: int,
) -> bool:
    """Send a webhook notification. Returns True on success."""
    if not settings.webhook_url:
        logger.debug("Webhook not configured — skipping")
        return False

    payload = _build_webhook_payload(
        policy_name, company, severity, summary, key_changes, recommendation, diff_id
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()

        logger.info(f"[webhook] alert sent for {policy_name} (severity: {severity})")
        return True

    except Exception as e:
        logger.error(f"[webhook] failed to send alert: {e}")
        return False


# ---------------------------------------------------------------------------
# Per-user notifications (for followers of a policy)
# ---------------------------------------------------------------------------

SEVERITY_RANK = {"informational": 0, "concerning": 1, "action-needed": 2}


async def _send_user_email(
    to_email: str, policy_name: str, company: str, severity: str,
    summary: str, key_changes: str, recommendation: str, diff_id: int,
) -> bool:
    """Send an email alert to a specific user. Returns True on success."""
    if not all([settings.smtp_user, settings.smtp_password]):
        return False

    try:
        msg = MIMEMultipart("alternative")
        emoji = SEVERITY_EMOJI.get(severity, "")
        msg["Subject"] = f"{emoji} PolicyDiff: {company} {severity.title()} — {policy_name}"
        msg["From"] = settings.alert_from_email or settings.smtp_user
        msg["To"] = to_email

        plain = f"""PolicyDiff Alert — {severity.upper()}

{policy_name} ({company})

{summary}

Recommendation: {recommendation}

---
You're receiving this because you follow this policy on PolicyDiff.
To unsubscribe, visit your notification preferences in the app.
"""
        msg.attach(MIMEText(plain, "plain"))

        html = _build_email_html(
            policy_name, company, severity, summary, key_changes, recommendation, diff_id
        )
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(
                settings.alert_from_email or settings.smtp_user,
                [to_email],
                msg.as_string(),
            )

        logger.info(f"[email] user alert sent to {to_email} for {policy_name}")
        return True

    except Exception as e:
        logger.error(f"[email] failed to send user alert to {to_email}: {e}")
        return False


async def notify_policy_followers(
    policy_id: int, policy_name: str, company: str, severity: str,
    summary: str, key_changes: str, recommendation: str, diff_id: int,
) -> int:
    """Send email notifications to all users following a specific policy.

    Respects per-user email preferences (enabled/disabled, frequency, severity threshold).
    Returns the count of successfully sent notifications.
    """
    from app.database import get_scoped_session
    from app.models import UserPageFollow, User, EmailPreference

    sent_count = 0

    with get_scoped_session() as db:
        follows = (
            db.query(UserPageFollow)
            .filter(UserPageFollow.policy_id == policy_id)
            .all()
        )

        if not follows:
            logger.debug(f"No followers for policy {policy_id} — skipping user notifications")
            return 0

        user_ids = [f.user_id for f in follows]
        users = db.query(User).filter(User.id.in_(user_ids), User.is_active == True).all()

        for user in users:
            # Check email preferences
            prefs = (
                db.query(EmailPreference)
                .filter(EmailPreference.user_id == user.id)
                .first()
            )

            # Skip if email disabled or unsubscribed
            if prefs and (not prefs.email_enabled or prefs.unsubscribed_at):
                continue

            # Skip if severity is below user's threshold
            if prefs and prefs.severity_threshold:
                user_threshold = SEVERITY_RANK.get(prefs.severity_threshold, 0)
                alert_severity = SEVERITY_RANK.get(severity, 0)
                if alert_severity < user_threshold:
                    continue

            # TODO: Handle frequency (daily/weekly digest) — for now, all are immediate
            ok = await _send_user_email(
                user.email, policy_name, company, severity,
                summary, key_changes, recommendation, diff_id,
            )
            if ok:
                sent_count += 1

    logger.info(f"[notify] sent {sent_count} user emails for policy {policy_id} ({policy_name})")
    return sent_count


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------

async def send_alert(
    policy_name: str, company: str, severity: str,
    summary: str, key_changes: str, recommendation: str, diff_id: int,
    policy_id: int = 0,
) -> bool:
    """Send notifications via all configured channels + per-user followers.

    Returns True if at least one channel succeeded.
    """
    results = []

    # Global email (ALERT_TO_EMAIL — admin notification)
    email_ok = await _send_email(
        policy_name, company, severity, summary, key_changes, recommendation, diff_id
    )
    results.append(email_ok)

    # Webhook
    webhook_ok = await _send_webhook(
        policy_name, company, severity, summary, key_changes, recommendation, diff_id
    )
    results.append(webhook_ok)

    # Per-user follower notifications
    if policy_id:
        user_count = await notify_policy_followers(
            policy_id, policy_name, company, severity,
            summary, key_changes, recommendation, diff_id,
        )
        results.append(user_count > 0)

    if not any(results):
        logger.info(f"No notification channels configured or all failed for {policy_name}")

    return any(results)


# Backward compatibility alias
send_alert_email = send_alert
