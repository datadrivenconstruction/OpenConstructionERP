# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""With the academy flag off the webhook touches nothing; refusals never log a secret.

The session handed in is a fake that records what the handler adds and
explodes on anything else, so "touches nothing" is measured, not assumed.
The database flows are in ``tests/pg/trainer/test_webhook_*``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.modules.trainer.models import TrainerWebhookEvent
from app.modules.trainer.webhook import compute_signature, handle_webhook

SECRET = "whsec_unit_never_logged_7f3a9c"
BODY = json.dumps(
    {
        "id": "evt_unit_1",
        "type": "order.paid",
        "data": {
            "offer_code": "p1",
            "email": "buyer@example.com",
            "paid_at": "2026-10-05T10:00:00Z",
        },
    }
).encode()


class _RecordingSession:
    """Accepts ``add`` and ``commit``; any other use is a test failure."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the webhook used session.{name}")


class _ExplodingSession:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the webhook used session.{name} with the flag off")


async def _never_seed(enrolment_id: object) -> None:
    raise AssertionError("seed called")


def _settings(*, academy_mode: bool, secret: str | None = SECRET):
    return get_settings().model_copy(
        update={
            "academy_mode": academy_mode,
            "trainer_webhook_secret": SecretStr(secret) if secret is not None else None,
        }
    )


def _signed(body: bytes = BODY, secret: str = SECRET) -> tuple[dict[str, str], str]:
    ts = str(int(time.time()))
    signature = "sha256=" + compute_signature(secret, body, ts)
    return {"X-OE-Timestamp": ts, "X-OE-Signature": signature}, signature


async def test_flag_off_answers_404_and_touches_nothing_even_when_signed() -> None:
    headers, _ = _signed()
    outcome = await handle_webhook(
        _ExplodingSession(),  # type: ignore[arg-type]
        _settings(academy_mode=False),
        raw_body=BODY,
        headers=headers,
        seed_on_enrol=_never_seed,
    )
    assert (outcome.http_status, outcome.status) == (404, "disabled")
    assert outcome.body() == {"status": "disabled"}


async def test_flag_on_the_same_signed_delivery_reaches_the_database() -> None:
    """The other polarity: with the flag on, the same request does use the session."""
    headers, _ = _signed()
    with pytest.raises(AssertionError, match="used session"):
        await handle_webhook(
            _ExplodingSession(),  # type: ignore[arg-type]
            _settings(academy_mode=True),
            raw_body=BODY,
            headers=headers,
            seed_on_enrol=_never_seed,
        )


@pytest.mark.parametrize("secret", [None, ""])
async def test_no_secret_answers_503_and_writes_nothing(secret: str | None) -> None:
    headers, _ = _signed()
    outcome = await handle_webhook(
        _ExplodingSession(),  # type: ignore[arg-type]
        _settings(academy_mode=True, secret=secret),
        raw_body=BODY,
        headers=headers,
        seed_on_enrol=_never_seed,
    )
    assert (outcome.http_status, outcome.status) == (503, "not_configured")


async def test_a_bad_signature_logs_a_row_that_trusts_nothing_in_the_body() -> None:
    headers, _ = _signed(secret="whsec_forger")
    session = _RecordingSession()
    outcome = await handle_webhook(
        session,  # type: ignore[arg-type]
        _settings(academy_mode=True),
        raw_body=BODY,
        headers=headers,
        seed_on_enrol=_never_seed,
    )
    assert (outcome.http_status, outcome.status) == (401, "rejected")
    assert session.commits == 1
    [row] = session.added
    assert isinstance(row, TrainerWebhookEvent)
    assert row.signature_ok is False
    assert row.event_id.startswith("rejected:")
    assert row.event_id != "evt_unit_1"
    assert row.payload is None
    assert row.email is None
    assert row.product_ref is None
    assert row.error == "bad_signature"


async def test_a_stale_delivery_is_refused_before_anything_is_read() -> None:
    ts = str(int(time.time()) - 3600)
    headers = {"X-OE-Timestamp": ts, "X-OE-Signature": compute_signature(SECRET, BODY, ts)}
    session = _RecordingSession()
    outcome = await handle_webhook(
        session,  # type: ignore[arg-type]
        _settings(academy_mode=True),
        raw_body=BODY,
        headers=headers,
        seed_on_enrol=_never_seed,
    )
    assert (outcome.http_status, outcome.status) == (401, "rejected")
    assert [row.error for row in session.added] == ["stale_timestamp"]


async def test_refusals_never_log_the_secret_or_the_signature(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    forged_headers, forged_signature = _signed(secret="whsec_forger")
    _, real_signature = _signed()
    await handle_webhook(
        _RecordingSession(),  # type: ignore[arg-type]
        _settings(academy_mode=True),
        raw_body=BODY,
        headers=forged_headers,
        seed_on_enrol=_never_seed,
    )
    await handle_webhook(
        _ExplodingSession(),  # type: ignore[arg-type]
        _settings(academy_mode=True, secret=""),
        raw_body=BODY,
        headers=forged_headers,
        seed_on_enrol=_never_seed,
    )
    trainer_records = [r for r in caplog.records if r.name.startswith("app.modules.trainer")]
    assert len(trainer_records) >= 2, "the refusals must be logged, or this test proves nothing"
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret_value in (SECRET, forged_signature, real_signature, forged_signature.removeprefix("sha256=")):
        assert secret_value not in text
    assert "bad_signature" in text
