"""Slack notification for approved triage verdicts.

Posture (deliberate, and different from the triage path):

- **Never raises, never blocks.** By the time we notify, the nurse has already
  signed and the verdict is committed. A Slack outage must not fail an approval
  that already happened, so every failure here is logged and swallowed.
- **Output-filtered, fail-closed.** Invariant #2 applies to every generated
  string, and a staff channel is not an exception — Slack messages land on
  phone lock screens, get exported, and get screenshotted. If the filter
  blocks or errors, we do not post.
- **Minimal clinical content by construction.** The message carries urgency,
  fired rule IDs, and a link back to the worklist. Patient-identifying and
  clinical detail stays behind the link, where it is access-controlled.

Unset SLACK_WEBHOOK_URL disables notification entirely (logged once per call
site, never an error) — same graceful-degradation pattern as the other
integrations in this repo.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.output_filter import check_output
from app.schemas import URGENCY_ORDER, Urgency

log = logging.getLogger("meridian.notify.slack")

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Only notify at or above this urgency. Set to "routine" to notify on every
# approved verdict. Default is "urgent": a routine screening referral pinging
# the channel is how a channel gets muted, and then the urgent one is missed.
NOTIFY_MIN_URGENCY: Urgency = os.environ.get("SLACK_NOTIFY_MIN_URGENCY", "urgent")  # type: ignore[assignment]

TIMEOUT_SECONDS = float(os.environ.get("SLACK_TIMEOUT_S", "5"))

WORKLIST_BASE_URL = os.environ.get("WORKLIST_BASE_URL", "http://localhost:3000")

_URGENCY_EMOJI = {
    "routine": ":white_circle:",
    "soon": ":large_yellow_circle:",
    "urgent": ":red_circle:",
    "emergency": ":rotating_light:",
}


def meets_threshold(urgency: str, minimum: str | None = None) -> bool:
    """True if `urgency` is at or above the notify threshold.

    Unknown urgency values fail *loud*: we notify rather than silently drop,
    since a value we don't recognise is more likely to matter, not less.
    """
    minimum = minimum or NOTIFY_MIN_URGENCY
    try:
        return URGENCY_ORDER.index(urgency) >= URGENCY_ORDER.index(minimum)
    except ValueError:
        log.warning("unknown_urgency_notifying_anyway", extra={"urgency": urgency})
        return True


def build_message(
    *,
    referral_id: str,
    verdict_id: str,
    urgency: str,
    rules_fired: list[str],
    rule_version: str,
    approved_by: str,
    booked_slot: str | None,
) -> str:
    """Compose the notification text.

    No patient name, no symptoms, no source text — those stay behind the link.
    Rule IDs are safe to name: they are config identifiers, not diagnoses.
    """
    emoji = _URGENCY_EMOJI.get(urgency, ":white_circle:")
    lines = [
        f"{emoji} *{urgency.upper()}* referral approved — `{referral_id}`",
        f"• Approved by: {approved_by}",
        f"• Slot: {booked_slot or '_not yet scheduled_'}",
        f"• Rules fired: {', '.join(f'`{r}`' for r in rules_fired) or '_none_'}",
        f"• Rule set: `{rule_version}`",
        f"<{WORKLIST_BASE_URL}/worklist/{referral_id}|Open in worklist> · "
        f"verdict `{verdict_id}`",
        "_DEMO — synthetic data. Not for clinical use._",
    ]
    return "\n".join(lines)


def notify_verdict_approved(
    *,
    referral_id: str,
    verdict_id: str,
    urgency: str,
    rules_fired: list[str],
    rule_version: str,
    approved_by: str,
    booked_slot: str | None = None,
) -> dict:
    """Post an approved-verdict notification to Slack.

    Returns a small status dict for logging/telemetry. Never raises.

    Status values: sent, skipped_below_threshold, skipped_no_webhook,
    blocked_by_output_filter, failed.
    """
    try:
        if not meets_threshold(urgency):
            log.info(
                "slack_notify_skipped_below_threshold",
                extra={"referral_id": referral_id, "urgency": urgency},
            )
            return {"status": "skipped_below_threshold", "urgency": urgency}

        if not WEBHOOK_URL:
            log.info(
                "slack_notify_skipped_no_webhook",
                extra={"referral_id": referral_id},
            )
            return {"status": "skipped_no_webhook"}

        text = build_message(
            referral_id=referral_id,
            verdict_id=verdict_id,
            urgency=urgency,
            rules_fired=rules_fired,
            rule_version=rule_version,
            approved_by=approved_by,
            booked_slot=booked_slot,
        )

        # Invariant #2, fail-closed: a filter error blocks the post.
        try:
            result = check_output(text)
        except Exception:
            log.exception("slack_notify_filter_error_fail_closed")
            return {"status": "blocked_by_output_filter", "reasons": ["filter_error"]}
        if not result.allowed:
            log.warning(
                "slack_notify_blocked_by_output_filter",
                extra={"referral_id": referral_id, "reasons": result.reasons},
            )
            return {"status": "blocked_by_output_filter", "reasons": result.reasons}

        resp = httpx.post(WEBHOOK_URL, json={"text": text}, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        log.info(
            "slack_notify_sent",
            extra={"referral_id": referral_id, "urgency": urgency},
        )
        return {"status": "sent"}

    except Exception as e:
        # Approval already committed — a notification failure must never
        # surface as an approval failure.
        log.exception("slack_notify_failed", extra={"referral_id": referral_id})
        return {"status": "failed", "error": str(e)}
