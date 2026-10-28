# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure inbound-capture normalizer.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* / SQLAlchemy / FastAPI on the path. The
tests are table-driven where the shapes repeat and assert the two invariants the
engine promises above all: every channel maps onto the same canonical
:class:`InboundMessage`, and a slightly malformed payload never raises.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.inbound_capture.normalize import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_UNKNOWN,
    CHANNEL_WEBHOOK,
    AttachmentRef,
    InboundMessage,
    idempotency_key,
    normalize,
    normalize_email,
    normalize_sms,
    normalize_subject,
    normalize_webhook,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_channel_constants_are_distinct() -> None:
    values = {CHANNEL_EMAIL, CHANNEL_WEBHOOK, CHANNEL_SMS, CHANNEL_UNKNOWN}
    assert len(values) == 4
    assert CHANNEL_EMAIL == "email"
    assert CHANNEL_WEBHOOK == "webhook"
    assert CHANNEL_SMS == "sms"


# ---------------------------------------------------------------------------
# normalize_subject
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Re: Hello", "Hello"),
        ("RE: Hello", "Hello"),
        ("re: Hello", "Hello"),
        ("Fwd: Hello", "Hello"),
        ("FW: Hello", "Hello"),
        ("Fw: Hello", "Hello"),
        ("Aw: Hallo", "Hallo"),
        ("Re: Re: Re: Hello", "Hello"),
        ("Re: Fwd: Re: Hello", "Hello"),
        ("RE: FW: Aw: Deeply Nested", "Deeply Nested"),
        ("Re[2]: Counter", "Counter"),
        ("Re(3): Counter", "Counter"),
        ("Fwd[10]: Counter", "Counter"),
        ("   Re:    spaced   out   ", "spaced out"),
        ("No prefix here", "No prefix here"),
        ("Subject: keep this", "Subject: keep this"),  # "subject" is not a reply prefix
        ("Reply: not stripped", "Reply: not stripped"),  # "reply" != "re"
        ("", ""),
        ("   ", ""),
        ("Re:", ""),
        ("Re: Re: Re:", ""),
        ("Re: a:b:c", "a:b:c"),  # only leading reply prefixes go; inner colons stay
    ],
)
def test_normalize_subject(raw: str, expected: str) -> None:
    assert normalize_subject(raw) == expected


def test_normalize_subject_preserves_case_of_body() -> None:
    assert normalize_subject("RE: KEEP CamelCase") == "KEEP CamelCase"


def test_normalize_subject_collapses_internal_whitespace() -> None:
    assert normalize_subject("Re:  RFI    0042    urgent\tnow") == "RFI 0042 urgent now"


# ---------------------------------------------------------------------------
# normalize_email - happy path + canonical shape
# ---------------------------------------------------------------------------


def test_normalize_email_full_payload() -> None:
    parsed = {
        "from": "  sender@site.com  ",
        "to": ["a@x.com", "b@y.com"],
        "cc": "c@z.com",
        "subject": "Re: RFI 12 about the slab",
        "date": "2026-06-24T10:30:00+00:00",
        "text": "Please advise on the rebar spacing.",
        "message_id": "<abc123@mail>",
        "in_reply_to": "<orig@mail>",
        "attachments": [
            {"filename": "detail.pdf", "content_type": "application/pdf", "size": 2048, "path": "/tmp/detail.pdf"},
        ],
    }
    msg = normalize_email(parsed)
    assert isinstance(msg, InboundMessage)
    assert msg.channel == CHANNEL_EMAIL
    assert msg.sender == "sender@site.com"  # trimmed
    assert msg.recipients == ("a@x.com", "b@y.com", "c@z.com")  # cc folded after to
    assert msg.subject == "Re: RFI 12 about the slab"  # display subject keeps prefix
    assert msg.external_id == "<abc123@mail>"
    assert msg.in_reply_to == "<orig@mail>"
    assert msg.sent_at == datetime(2026, 6, 24, 10, 30, tzinfo=UTC)
    assert msg.body == "Please advise on the rebar spacing."
    assert len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att == AttachmentRef("detail.pdf", "application/pdf", 2048, "/tmp/detail.pdf")


def test_normalize_email_comma_string_recipients() -> None:
    msg = normalize_email({"to": "a@x.com, b@y.com; c@z.com"})
    assert msg.recipients == ("a@x.com", "b@y.com", "c@z.com")


def test_normalize_email_alias_keys() -> None:
    # Hyphenated header-style aliases must work too.
    msg = normalize_email({"sender": "s@x.com", "message-id": "<id@m>", "in-reply-to": "<r@m>", "body": "hi"})
    assert msg.sender == "s@x.com"
    assert msg.external_id == "<id@m>"
    assert msg.in_reply_to == "<r@m>"
    assert msg.body == "hi"


def test_normalize_email_missing_fields_safe_defaults() -> None:
    msg = normalize_email({})
    assert msg.channel == CHANNEL_EMAIL
    assert msg.sender == ""
    assert msg.recipients == ()
    assert msg.subject == ""
    assert msg.body == ""
    assert msg.external_id == ""
    assert msg.in_reply_to is None
    assert msg.attachments == ()
    assert msg.sent_at == _EPOCH


def test_normalize_email_blank_fields_collapse() -> None:
    msg = normalize_email({"from": "   ", "subject": "", "to": [], "in_reply_to": "  "})
    assert msg.sender == ""
    assert msg.subject == ""
    assert msg.recipients == ()
    assert msg.in_reply_to is None


# ---------------------------------------------------------------------------
# normalize_webhook
# ---------------------------------------------------------------------------


def test_normalize_webhook_full_payload() -> None:
    payload = {
        "sender": "alice",
        "to": "project-room",
        "id": "evt-99",
        "timestamp": "2026-06-24T08:00:00Z",  # trailing Z must parse
        "title": "Site question",
        "text": "Is gate 3 open?",
        "thread_id": "thr-1",
        "files": [{"name": "photo.jpg", "type": "image/jpeg", "bytes": 1000}],
    }
    msg = normalize_webhook(payload)
    assert msg.channel == CHANNEL_WEBHOOK
    assert msg.sender == "alice"
    assert msg.recipients == ("project-room",)
    assert msg.external_id == "evt-99"
    assert msg.sent_at == datetime(2026, 6, 24, 8, 0, tzinfo=UTC)
    assert msg.subject == "Site question"
    assert msg.body == "Is gate 3 open?"
    assert msg.in_reply_to == "thr-1"
    assert msg.attachments == (AttachmentRef("photo.jpg", "image/jpeg", 1000, None),)


def test_normalize_webhook_channel_hint_overrides_stored_channel() -> None:
    msg = normalize_webhook({"text": "hi"}, channel_hint="chat-provider")
    assert msg.channel == "chat-provider"
    assert msg.body == "hi"


def test_normalize_webhook_channel_hint_is_not_a_payload_field() -> None:
    # A literal "channel" key is a recipient alias, not the stored channel; the
    # stored channel comes from channel_hint / the default.
    msg = normalize_webhook({"channel": "general", "text": "x"})
    assert msg.channel == CHANNEL_WEBHOOK
    assert msg.recipients == ("general",)


def test_normalize_webhook_missing_fields_safe_defaults() -> None:
    msg = normalize_webhook({})
    assert msg.channel == CHANNEL_WEBHOOK
    assert msg.sender == ""
    assert msg.recipients == ()
    assert msg.external_id == ""
    assert msg.subject == ""
    assert msg.body == ""
    assert msg.in_reply_to is None
    assert msg.attachments == ()
    assert msg.sent_at == _EPOCH


def test_normalize_webhook_alias_priority_first_wins() -> None:
    # Both "sender" and "from" present: "sender" wins (listed first).
    msg = normalize_webhook({"sender": "first", "from": "second"})
    assert msg.sender == "first"


# ---------------------------------------------------------------------------
# normalize_sms
# ---------------------------------------------------------------------------


def test_normalize_sms_full_payload() -> None:
    payload = {
        "from": "+15551234567",
        "to": "+15557654321",
        "sms_id": "sms-7",
        "sent_at": "2026-06-24T12:00:00+00:00",
        "text": "On my way to site.",
    }
    msg = normalize_sms(payload)
    assert msg.channel == CHANNEL_SMS
    assert msg.sender == "+15551234567"
    assert msg.recipients == ("+15557654321",)
    assert msg.external_id == "sms-7"
    assert msg.sent_at == datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    assert msg.body == "On my way to site."
    assert msg.subject == ""  # SMS never has a subject
    assert msg.in_reply_to is None  # SMS never threads
    assert msg.attachments == ()


def test_normalize_sms_msisdn_alias() -> None:
    msg = normalize_sms({"msisdn": "+1999", "message": "hello"})
    assert msg.sender == "+1999"
    assert msg.body == "hello"


def test_normalize_sms_missing_fields_safe_defaults() -> None:
    msg = normalize_sms({})
    assert msg.channel == CHANNEL_SMS
    assert msg.sender == ""
    assert msg.recipients == ()
    assert msg.body == ""
    assert msg.subject == ""
    assert msg.external_id == ""
    assert msg.in_reply_to is None
    assert msg.attachments == ()
    assert msg.sent_at == _EPOCH


def test_normalize_sms_mms_media_attachment() -> None:
    msg = normalize_sms({"text": "pic", "media": [{"filename": "m.jpg", "content_type": "image/jpeg", "size": 5}]})
    assert msg.attachments == (AttachmentRef("m.jpg", "image/jpeg", 5, None),)


# ---------------------------------------------------------------------------
# datetime coercion - via the public normalizers
# ---------------------------------------------------------------------------


def test_sent_at_accepts_datetime_object_aware() -> None:
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert normalize_email({"date": dt}).sent_at == dt


def test_sent_at_accepts_naive_datetime_assumed_utc() -> None:
    dt = datetime(2026, 1, 2, 3, 4, 5)  # naive
    assert normalize_email({"date": dt}).sent_at == dt.replace(tzinfo=UTC)


def test_sent_at_shifts_offset_to_utc() -> None:
    # +02:00 local should be stored as the equivalent UTC instant.
    msg = normalize_email({"date": "2026-06-24T12:00:00+02:00"})
    assert msg.sent_at == datetime(2026, 6, 24, 10, 0, tzinfo=UTC)


def test_sent_at_tolerates_trailing_z() -> None:
    msg = normalize_webhook({"timestamp": "2026-06-24T10:00:00Z"})
    assert msg.sent_at == datetime(2026, 6, 24, 10, 0, tzinfo=UTC)


def test_sent_at_tolerates_lowercase_z() -> None:
    msg = normalize_webhook({"timestamp": "2026-06-24T10:00:00z"})
    assert msg.sent_at == datetime(2026, 6, 24, 10, 0, tzinfo=UTC)


def test_sent_at_date_only_iso() -> None:
    msg = normalize_email({"date": "2026-06-24"})
    assert msg.sent_at == datetime(2026, 6, 24, 0, 0, tzinfo=UTC)


def test_sent_at_unparseable_falls_back_to_epoch() -> None:
    assert normalize_email({"date": "not a date"}).sent_at == _EPOCH
    assert normalize_email({"date": 12345}).sent_at == _EPOCH  # non-str, non-datetime
    assert normalize_webhook({"timestamp": ""}).sent_at == _EPOCH


def test_sent_at_result_is_always_aware() -> None:
    for payload_dt in ("2026-06-24T10:00:00", "2026-06-24", "garbage", "", "2026-06-24T10:00:00Z"):
        msg = normalize_email({"date": payload_dt})
        assert msg.sent_at.tzinfo is not None


# ---------------------------------------------------------------------------
# attachments coercion edge cases
# ---------------------------------------------------------------------------


def test_attachments_size_alias_and_clamp() -> None:
    msg = normalize_email({"attachments": [{"filename": "a", "size_bytes": "2048"}, {"filename": "b", "size": -5}]})
    assert msg.attachments[0].size_bytes == 2048  # numeric string parsed
    assert msg.attachments[1].size_bytes == 0  # negative clamped


def test_attachments_storage_hint_aliases() -> None:
    msg = normalize_email(
        {"attachments": [{"filename": "a", "url": "https://store/a"}, {"filename": "b", "cid": "cid:123"}]}
    )
    assert msg.attachments[0].storage_hint == "https://store/a"
    assert msg.attachments[1].storage_hint == "cid:123"


def test_attachments_empty_element_dropped() -> None:
    # A dict with no usable info carries nothing and is skipped.
    msg = normalize_email({"attachments": [{}, {"filename": "real.pdf"}]})
    assert len(msg.attachments) == 1
    assert msg.attachments[0].filename == "real.pdf"


def test_attachments_non_list_ignored() -> None:
    assert normalize_email({"attachments": "not-a-list"}).attachments == ()
    assert normalize_email({"attachments": {"filename": "x"}}).attachments == ()


def test_attachments_non_dict_elements_skipped() -> None:
    msg = normalize_email({"attachments": ["string", 42, None, {"filename": "ok"}]})
    assert len(msg.attachments) == 1
    assert msg.attachments[0].filename == "ok"


# ---------------------------------------------------------------------------
# raw_refs - unrecognised fields preserved, never dropped
# ---------------------------------------------------------------------------


def test_raw_refs_captures_unknown_fields_sorted() -> None:
    msg = normalize_email({"from": "s@x.com", "x_priority": "high", "spam_score": 0.1})
    # Recognised "from" is absent from raw_refs; the two unknowns are present, sorted.
    assert msg.raw_refs == ("spam_score=0.1", "x_priority=high")


def test_raw_refs_empty_when_all_recognised() -> None:
    msg = normalize_sms({"from": "+1", "to": "+2", "text": "hi", "id": "s1"})
    assert msg.raw_refs == ()


def test_raw_refs_skips_none_values() -> None:
    msg = normalize_webhook({"text": "hi", "weird": None})
    assert msg.raw_refs == ()


def test_raw_refs_caps_long_values() -> None:
    long_value = "z" * 500
    msg = normalize_webhook({"text": "hi", "huge": long_value})
    (ref,) = msg.raw_refs
    assert ref.startswith("huge=")
    assert ref.endswith("...")
    assert len(ref) <= len("huge=") + 200


def test_raw_refs_renders_nested_structures() -> None:
    msg = normalize_webhook({"text": "hi", "headers": {"x": 1}})
    (ref,) = msg.raw_refs
    assert ref.startswith("headers=")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def test_normalize_dispatches_email() -> None:
    msg = normalize(CHANNEL_EMAIL, {"from": "s@x.com", "subject": "hi"})
    assert msg.channel == CHANNEL_EMAIL
    assert msg.sender == "s@x.com"


def test_normalize_dispatches_sms() -> None:
    msg = normalize(CHANNEL_SMS, {"from": "+1", "text": "hi"})
    assert msg.channel == CHANNEL_SMS
    assert msg.body == "hi"


def test_normalize_dispatches_webhook() -> None:
    msg = normalize(CHANNEL_WEBHOOK, {"text": "hi"})
    assert msg.channel == CHANNEL_WEBHOOK


def test_normalize_is_case_and_whitespace_insensitive() -> None:
    msg = normalize("  EMAIL  ", {"from": "s@x.com"})
    assert msg.channel == CHANNEL_EMAIL
    assert msg.sender == "s@x.com"


def test_normalize_unknown_channel_uses_webhook_shape_marks_unknown() -> None:
    msg = normalize("", {"text": "hi"})
    assert msg.channel == CHANNEL_UNKNOWN
    assert msg.body == "hi"


def test_normalize_unknown_channel_preserves_label() -> None:
    # A non-empty but unrecognised channel is kept as the stored label.
    msg = normalize("teams", {"text": "hi"})
    assert msg.channel == "teams"
    assert msg.body == "hi"


# ---------------------------------------------------------------------------
# malformed payloads must NOT raise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "normalizer",
    [normalize_email, normalize_webhook, normalize_sms],
)
@pytest.mark.parametrize(
    "bad_payload",
    [
        {},
        {"to": 12345},
        {"to": [None, "", "  ", "ok@x.com"]},
        {"attachments": "nope"},
        {"attachments": [None, 1, "x"]},
        {"date": object()},
        {"sent_at": ["a", "list"]},
        {"text": 999},
        {"from": {"nested": "dict"}},
        {"size": float("inf")},
    ],
)
def test_normalizers_never_raise_on_malformed(normalizer, bad_payload) -> None:
    msg = normalizer(bad_payload)
    assert isinstance(msg, InboundMessage)
    assert msg.sent_at.tzinfo is not None  # always an aware datetime


@pytest.mark.parametrize("channel", [CHANNEL_EMAIL, CHANNEL_WEBHOOK, CHANNEL_SMS, "unknownX", "", "   "])
def test_normalize_dispatch_never_raises_on_garbage(channel) -> None:
    msg = normalize(channel, {"weird": object(), "to": 5})
    assert isinstance(msg, InboundMessage)


def test_normalizers_tolerate_non_dict_payload() -> None:
    # Defensive: a non-dict slipping through still yields a default message.
    for normalizer in (normalize_email, normalize_webhook, normalize_sms):
        msg = normalizer(None)  # type: ignore[arg-type]
        assert isinstance(msg, InboundMessage)
        assert msg.sender == ""


def test_inbound_message_is_hashable_and_frozen() -> None:
    msg = normalize_sms({"from": "+1", "text": "hi", "id": "s1"})
    # Frozen dataclass -> hashable -> usable in a set / dict key.
    assert msg in {msg}
    with pytest.raises(Exception):
        msg.sender = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# idempotency_key
# ---------------------------------------------------------------------------


def test_idempotency_key_is_stable() -> None:
    a = normalize_email({"message_id": "<id@m>", "subject": "first"})
    b = normalize_email({"message_id": "<id@m>", "subject": "different subject"})
    # Same channel + external id -> same key, regardless of other fields.
    assert idempotency_key(a) == idempotency_key(b)


def test_idempotency_key_differs_by_external_id() -> None:
    a = normalize_email({"message_id": "<id-1@m>"})
    b = normalize_email({"message_id": "<id-2@m>"})
    assert idempotency_key(a) != idempotency_key(b)


def test_idempotency_key_differs_by_channel() -> None:
    email = normalize_email({"message_id": "shared"})
    sms = normalize_sms({"id": "shared"})
    assert idempotency_key(email) != idempotency_key(sms)


def test_idempotency_key_is_hex_sha256() -> None:
    key = idempotency_key(normalize_sms({"id": "x"}))
    assert len(key) == 64
    int(key, 16)  # parses as hex -> raises if not


def test_idempotency_key_channel_case_insensitive() -> None:
    # Same logical channel spelled differently collapses to the same key.
    m1 = InboundMessage(
        channel="EMAIL",
        external_id="x",
        sender="",
        recipients=(),
        sent_at=_EPOCH,
        subject="",
        body="",
        attachments=(),
        in_reply_to=None,
    )
    m2 = InboundMessage(
        channel="email",
        external_id="x",
        sender="",
        recipients=(),
        sent_at=_EPOCH,
        subject="",
        body="",
        attachments=(),
        in_reply_to=None,
    )
    assert idempotency_key(m1) == idempotency_key(m2)


def test_idempotency_key_no_separator_collision() -> None:
    # ("ab", "c") and ("a", "bc") must not collide via naive concatenation.
    m1 = InboundMessage(
        channel="ab",
        external_id="c",
        sender="",
        recipients=(),
        sent_at=_EPOCH,
        subject="",
        body="",
        attachments=(),
        in_reply_to=None,
    )
    m2 = InboundMessage(
        channel="a",
        external_id="bc",
        sender="",
        recipients=(),
        sent_at=_EPOCH,
        subject="",
        body="",
        attachments=(),
        in_reply_to=None,
    )
    assert idempotency_key(m1) != idempotency_key(m2)


def test_idempotency_key_blank_external_id_still_keys() -> None:
    msg = normalize_email({})  # no message id
    key = idempotency_key(msg)
    assert len(key) == 64


# ---------------------------------------------------------------------------
# cross-channel: every channel yields the same canonical shape
# ---------------------------------------------------------------------------


def test_all_channels_produce_inbound_message() -> None:
    msgs = [
        normalize_email({"from": "s@x.com", "text": "e"}),
        normalize_webhook({"sender": "u", "text": "w"}),
        normalize_sms({"from": "+1", "text": "s"}),
    ]
    for msg in msgs:
        assert isinstance(msg, InboundMessage)
        assert isinstance(msg.recipients, tuple)
        assert isinstance(msg.attachments, tuple)
        assert isinstance(msg.raw_refs, tuple)
        assert isinstance(msg.sent_at, datetime)
        assert msg.sent_at.tzinfo is not None


def test_determinism_same_payload_same_message() -> None:
    payload = {
        "from": "s@x.com",
        "to": ["a@x.com", "b@y.com"],
        "subject": "Re: Re: thread",
        "date": "2026-06-24T10:00:00Z",
        "text": "body",
        "message_id": "<id@m>",
        "attachments": [{"filename": "a.pdf", "size": 10}],
        "x_custom": "extra",
    }
    first = normalize_email(dict(payload))
    second = normalize_email(dict(payload))
    assert first == second
    assert idempotency_key(first) == idempotency_key(second)


def test_recipients_order_preserved_with_duplicates() -> None:
    # Order matters and duplicates are kept (someone on To and Cc).
    msg = normalize_email({"to": ["a@x.com", "b@y.com"], "cc": ["a@x.com"]})
    assert msg.recipients == ("a@x.com", "b@y.com", "a@x.com")


def test_future_and_past_dates_round_trip() -> None:
    past = _EPOCH + timedelta(days=1)
    msg = normalize_webhook({"timestamp": past.isoformat()})
    assert msg.sent_at == past
