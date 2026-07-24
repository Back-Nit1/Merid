"""Notification tests. The load-bearing assertions here are the negative ones:
notification must never raise, and must never post a string that fails the
output filter.
"""

from __future__ import annotations

import pytest

from services.notify import calendar as cal
from services.notify import slack


class _FakeResponse:
    def raise_for_status(self):
        return None


@pytest.fixture
def captured(monkeypatch):
    """Capture httpx.post calls from both notify modules."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return _FakeResponse()

    monkeypatch.setattr(slack.httpx, "post", fake_post)
    monkeypatch.setattr(cal.httpx, "post", fake_post)
    monkeypatch.setattr(slack, "WEBHOOK_URL", "https://hooks.slack.com/services/TEST")
    monkeypatch.setattr(cal, "WEBHOOK_URL", "https://hooks.slack.com/services/TEST")
    return calls


def _approve(**overrides):
    kwargs = dict(
        referral_id="REF-0042",
        verdict_id="V-1",
        urgency="urgent",
        rules_fired=["YOUNG_BLEEDING_PLUS_FEATURE"],
        rule_version="2026.07.24-1",
        approved_by="Nurse Chen",
        booked_slot="2026-07-28T09:00",
    )
    kwargs.update(overrides)
    return slack.notify_verdict_approved(**kwargs)


# --- threshold gating ------------------------------------------------------


@pytest.mark.parametrize(
    "urgency,expected",
    [("routine", False), ("soon", False), ("urgent", True), ("emergency", True)],
)
def test_default_threshold_is_urgent_and_above(urgency, expected):
    assert slack.meets_threshold(urgency, "urgent") is expected


@pytest.mark.parametrize("urgency", ["routine", "soon", "urgent", "emergency"])
def test_threshold_routine_notifies_on_every_verdict(urgency):
    """The configurable path: SLACK_NOTIFY_MIN_URGENCY=routine notifies on all."""
    assert slack.meets_threshold(urgency, "routine") is True


def test_unknown_urgency_notifies_rather_than_drops():
    assert slack.meets_threshold("banana", "urgent") is True


def test_below_threshold_does_not_post(captured):
    result = _approve(urgency="routine")
    assert result["status"] == "skipped_below_threshold"
    assert captured == []


def test_urgent_posts(captured):
    result = _approve()
    assert result["status"] == "sent"
    assert len(captured) == 1
    assert "REF-0042" in captured[0]["json"]["text"]


# --- invariant #2: output filter -------------------------------------------


def test_message_passes_output_filter():
    from app.output_filter import check_output

    text = slack.build_message(
        referral_id="REF-0042",
        verdict_id="V-1",
        urgency="urgent",
        rules_fired=["YOUNG_BLEEDING_PLUS_FEATURE"],
        rule_version="2026.07.24-1",
        approved_by="Nurse Chen",
        booked_slot="2026-07-28T09:00",
    )
    assert check_output(text).allowed


def test_diagnostic_language_is_blocked_not_posted(captured, monkeypatch):
    """If anything ever injects a condition term into the message, we must
    block the post rather than leak it to a staff channel."""
    monkeypatch.setattr(
        slack, "build_message", lambda **kw: "REF-0042 probable hemorrhoids, don't worry"
    )
    result = _approve()
    assert result["status"] == "blocked_by_output_filter"
    assert captured == []


def test_calendar_title_carries_no_clinical_content():
    from app.output_filter import check_output

    event = cal.build_event(
        referral_id="REF-0042",
        urgency="urgent",
        booked_slot="2026-07-28T09:00",
        approved_by="Nurse Chen",
    )
    assert check_output(event["title"]).allowed
    assert check_output(event["description"]).allowed
    assert "REF-0042" in event["title"]


# --- never raises ----------------------------------------------------------


def test_slack_transport_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(slack, "WEBHOOK_URL", "https://hooks.slack.com/services/TEST")

    def boom(*a, **k):
        raise RuntimeError("slack is down")

    monkeypatch.setattr(slack.httpx, "post", boom)
    result = _approve()
    assert result["status"] == "failed"


def test_calendar_transport_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(cal, "WEBHOOK_URL", "https://hooks.slack.com/services/TEST")

    def boom(*a, **k):
        raise RuntimeError("slack is down")

    monkeypatch.setattr(cal.httpx, "post", boom)
    result = cal.create_calendar_event(
        referral_id="REF-0042",
        urgency="urgent",
        booked_slot="2026-07-28T09:00",
        approved_by="Nurse Chen",
    )
    assert result["status"] == "failed"


def test_no_webhook_configured_is_not_an_error(monkeypatch):
    monkeypatch.setattr(slack, "WEBHOOK_URL", None)
    assert _approve()["status"] == "skipped_no_webhook"


def test_calendar_respects_same_threshold_as_slack(captured):
    """A routine approval must not schedule via this path — the two channels
    share one threshold so they can't drift apart."""
    result = cal.create_calendar_event(
        referral_id="REF-0001",
        urgency="routine",
        booked_slot="2026-08-10T14:00",
        approved_by="Nurse Test",
    )
    assert result["status"] == "skipped_below_threshold"
    assert captured == []


def test_calendar_urgent_is_requested(captured):
    result = cal.create_calendar_event(
        referral_id="REF-0042",
        urgency="urgent",
        booked_slot="2026-07-28T09:00",
        approved_by="Nurse Chen",
    )
    assert result["status"] == "requested"
    assert len(captured) == 1
    assert cal.EVENT_MARKER in captured[0]["json"]["text"]


def test_calendar_without_slot_is_skipped(captured):
    result = cal.create_calendar_event(
        referral_id="REF-0042", urgency="urgent", booked_slot=None, approved_by="N"
    )
    assert result["status"] == "skipped_no_slot"
    assert captured == []
