"""Notification message formatting for email and SMS."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TriageResult:
    """Result from AI triage analysis."""

    classification: str  # bug_report, feature_request, question, praise, complaint, spam
    severity: str        # critical, high, medium, low, unknown
    summary: str
    reasoning: str = ""


@dataclass
class FormattedNotification:
    """A fully formatted notification ready to send."""

    subject: str
    html_body: str
    text_body: str


SEVERITY_INDICATORS = {
    "critical": "!!!",
    "high": "!!",
    "medium": "!",
    "low": "",
    "unknown": "?",
}

SEVERITY_COLORS = {
    "critical": "#dc2626",
    "high": "#ea580c",
    "medium": "#ca8a04",
    "low": "#6b7280",
    "unknown": "#9ca3af",
}

SOURCE_LABELS = {
    "github": "GitHub",
    "forge": "SPT-Forge",
    "reddit": "Reddit",
}

TYPE_LABELS = {
    "issue": "Issue",
    "comment": "Comment",
    "pr": "Pull Request",
    "post": "Post",
    "mod_comment": "Mod Comment",
    "mod_update": "Mod Update",
}


def format_notification(
    source: str,
    source_id: str,
    item_type: str,
    repo_or_context: str,
    title: str,
    body: str,
    author: str,
    url: str,
    triage: TriageResult,
) -> FormattedNotification:
    """Format a notification for both email and SMS delivery."""
    severity_indicator = SEVERITY_INDICATORS.get(triage.severity, "")
    severity_color = SEVERITY_COLORS.get(triage.severity, "#6b7280")
    source_label = SOURCE_LABELS.get(source, source)
    type_label = TYPE_LABELS.get(item_type, item_type)
    classification_display = triage.classification.replace("_", " ").upper()

    # Subject line
    subject_prefix = f"{severity_indicator} " if severity_indicator else ""
    subject = (
        f"[Wingman] {subject_prefix}{classification_display} "
        f"on {repo_or_context} ({source_label})"
    )

    # Truncate body for display
    body_preview = body[:500].strip()
    if len(body) > 500:
        body_preview += "..."

    # HTML email body
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">

<div style="border-left: 4px solid {severity_color}; padding: 12px 16px; margin-bottom: 20px; background: #f8f9fa;">
    <h2 style="margin: 0 0 8px 0; font-size: 18px;">
        {severity_indicator} New {type_label}: {_html_escape(title)}
    </h2>
</div>

<table style="width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 14px;">
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold; white-space: nowrap;">Source:</td>
        <td style="padding: 4px 0;">{source_label} / {_html_escape(repo_or_context)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold; white-space: nowrap;">Type:</td>
        <td style="padding: 4px 0;">{type_label}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold; white-space: nowrap;">Author:</td>
        <td style="padding: 4px 0;">{_html_escape(author)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold; white-space: nowrap;">Classification:</td>
        <td style="padding: 4px 0;"><span style="color: {severity_color}; font-weight: bold;">{classification_display}</span></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold; white-space: nowrap;">Severity:</td>
        <td style="padding: 4px 0;"><span style="color: {severity_color}; font-weight: bold;">{triage.severity.upper()}</span></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold; white-space: nowrap;">AI Summary:</td>
        <td style="padding: 4px 0;">{_html_escape(triage.summary)}</td></tr>
</table>

<blockquote style="margin: 0 0 16px 0; padding: 12px 16px; background: #f1f3f5; border-left: 3px solid #dee2e6; font-size: 13px; color: #495057; white-space: pre-wrap;">
{_html_escape(body_preview)}
</blockquote>

<p style="margin: 0;">
    <a href="{url}" style="color: #2563eb; text-decoration: none; font-weight: bold;">
        View on {source_label} &rarr;
    </a>
</p>

<hr style="margin: 24px 0 12px 0; border: none; border-top: 1px solid #dee2e6;">
<p style="font-size: 11px; color: #868e96; margin: 0;">
    Wingman v1.0
</p>

</body>
</html>"""

    # SMS plain text (compact, ~300 chars max)
    sms_parts = []
    if severity_indicator:
        sms_parts.append(f"{severity_indicator} {classification_display}")
    else:
        sms_parts.append(classification_display)
    sms_parts.append(f"{repo_or_context} ({source_label})")
    sms_parts.append(f'"{title}" by {author}')
    if triage.summary:
        sms_parts.append(f"AI: {triage.summary}")
    sms_parts.append(url)
    text_body = "\n".join(sms_parts)

    return FormattedNotification(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )


def format_watcher_failure(
    watcher_name: str,
    failures: int,
    error: str,
    last_success: str,
) -> FormattedNotification:
    """Format a meta-notification for a failing watcher."""
    subject = f"[Wingman] SYSTEM: {watcher_name} failing"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
<div style="border-left: 4px solid #dc2626; padding: 12px 16px; background: #fef2f2;">
    <h2 style="margin: 0; font-size: 18px; color: #dc2626;">Watcher Failure Alert</h2>
</div>
<table style="width: 100%; margin: 16px 0; font-size: 14px;">
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Watcher:</td>
        <td>{_html_escape(watcher_name)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Consecutive failures:</td>
        <td>{failures}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Last error:</td>
        <td>{_html_escape(error)}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Last success:</td>
        <td>{_html_escape(last_success or 'Never')}</td></tr>
</table>
</body></html>"""

    text_body = (
        f"WINGMAN ALERT: {watcher_name} has failed {failures} times.\n"
        f"Error: {error}\n"
        f"Last success: {last_success or 'Never'}"
    )

    return FormattedNotification(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )


def _html_escape(text: str) -> str:
    """Basic HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
