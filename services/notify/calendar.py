"""Provider-side calendar event for an approved, booked referral.

Why this shape: there is no GCP project for this demo, so we do not call the
Google Calendar API directly. Instead we post a *structured, machine-readable*
line to Slack, which a Slack Workflow (Google Calendar connector, the
`google.calendar/create_event` step) consumes to create the real event. That
keeps setup entirely inside the Slack UI — no service account, no domain-wide
delegation.

Known tradeoff, stated plainly: the event is created outside this system, so
we never receive a Google event ID and cannot record it against the verdict.
The booking is therefore *not* in our audit trail — only the intent to book
is. If that audit gap matters (it plausibly does for a signed clinical
approval), the upgrade path is a service account calling the Calendar API
directly from here, which would return an ID we can persist. `build_event()`
below is deliberately transport-agnostic so that swap is a one-file change.

Title policy (invariant #2): event titles carry NO clinical content. A
calendar entry syncs to phones, shows on shared office displays, and appears
in notification previews outside the building. Title is referral ID plus
urgency; everything else lives behind the worklist link.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.output_filter import check_output
from services.notify.slack import meets_threshold

log = logging.getLogger("meridian.notify.calendar")

WEBHOOK_URL = os.environ.get("SLACK_CALENDAR_WEBHOOK_URL") or os.environ.get(
    "SLACK_WEBHOOK_URL"
)
TIMEOUT_SECONDS = float(os.environ.get("SLACK_TIMEOUT_S", "5"))
WORKLIST_BASE_URL = os.environ.get("WORKLIST_BASE_URL", "http://localhost:3000")

# Marker the Slack Workflow trigger matches on. Keep it stable — changing it
# means reconfiguring the workflow in the Slack UI.
EVENT_MARKER = "[MERIDIAN-CALENDAR]"


def build_event(
    *,
    referral_id: str,
    urgency: str,
    booked_slot: str,
    approved_by: str,
) -> dict:
    """Build the calendar event payload.

    Transport-agnostic on purpose: these are exactly the fields the Google
    Calendar API needs, so swapping the Slack-workflow transport for a direct
    API call means changing only how this dict is delivered.
    """
    return {
        "title": f"Colonoscopy consult — {referral_id} ({urgency})",
        "start": booked_slot,
        "description": (
            f"Triage approved by {approved_by}. "
            f"Details: {WORKLIST_BASE_URL}/worklist/{referral_id}\n"
            "DEMO — synthetic data. Not for clinical use."
        ),
        "referral_id": referral_id,
        "urgency": urgency,
    }


def create_calendar_event(
    *,
    referral_id: str,
    urgency: str,
    booked_slot: str | None,
    approved_by: str,
) -> dict:
    """Request creation of a provider-side calendar event. Never raises.

    Status values: requested, skipped_below_threshold, skipped_no_slot,
    skipped_no_webhook, blocked_by_output_filter, failed.
    """
    try:
        # Same urgency gate as Slack notification, and for the same reason: a
        # routine screening booking landing on the provider calendar via this
        # path is noise. Shares SLACK_NOTIFY_MIN_URGENCY so the two channels
        # can't drift apart — set it to "routine" to schedule every approval.
        if not meets_threshold(urgency):
            log.info(
                "calendar_skipped_below_threshold",
                extra={"referral_id": referral_id, "urgency": urgency},
            )
            return {"status": "skipped_below_threshold", "urgency": urgency}

        if not booked_slot:
            # No slot means nothing to schedule. Not an error — plenty of
            # approvals record the verdict before a time is chosen.
            log.info("calendar_skipped_no_slot", extra={"referral_id": referral_id})
            return {"status": "skipped_no_slot"}

        if not WEBHOOK_URL:
            log.info("calendar_skipped_no_webhook", extra={"referral_id": referral_id})
            return {"status": "skipped_no_webhook"}

        event = build_event(
            referral_id=referral_id,
            urgency=urgency,
            booked_slot=booked_slot,
            approved_by=approved_by,
        )

        # Filter the title and description — these are the strings that leave
        # our access-controlled surface and land on calendars/phones.
        for field in ("title", "description"):
            try:
                result = check_output(event[field])
            except Exception:
                log.exception("calendar_filter_error_fail_closed")
                return {
                    "status": "blocked_by_output_filter",
                    "reasons": [f"filter_error:{field}"],
                }
            if not result.allowed:
                log.warning(
                    "calendar_blocked_by_output_filter",
                    extra={"referral_id": referral_id, "field": field, "reasons": result.reasons},
                )
                return {"status": "blocked_by_output_filter", "reasons": result.reasons}

        text = (
            f"{EVENT_MARKER}\n"
            f"*{event['title']}*\n"
            f"• When: {event['start']}\n"
            f"• {event['description'].splitlines()[0]}"
        )
        resp = httpx.post(WEBHOOK_URL, json={"text": text}, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        log.info(
            "calendar_event_requested",
            extra={"referral_id": referral_id, "slot": booked_slot},
        )
        # "requested", never "created": the event is created by the Slack
        # workflow downstream, and we get no confirmation back.
        return {"status": "requested", "event": event}

    except Exception as e:
        log.exception("calendar_event_failed", extra={"referral_id": referral_id})
        return {"status": "failed", "error": str(e)}
