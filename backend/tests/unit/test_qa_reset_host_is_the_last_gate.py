# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The QA reset reads the Host header last, so a spoofed Host opens nothing.

The hostname gate reads ``Host``, which any caller sets. It may only ever add
a refusal on top of the gates a caller cannot forge, the environment switch
and the shared secret, so it runs after them: a request that names a
development host still meets the closed switch and the token check first.
"""

from __future__ import annotations

import pytest

from app.modules.admin.service import GateError, check_gates

_DEV_HOST = "localhost"


def _code(**kwargs: object) -> str:
    with pytest.raises(GateError) as exc:
        check_gates(**kwargs)
    return exc.value.code


def test_a_development_host_does_not_open_a_disabled_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QA_RESET_ALLOWED", raising=False)
    monkeypatch.setenv("QA_RESET_TOKEN", "s3cret-token")
    assert _code(hostname=_DEV_HOST, confirm_token="s3cret-token", tenant="demo") == "qa_reset_disabled"


@pytest.mark.parametrize("token", [None, "", "guess"])
def test_a_development_host_does_not_replace_the_token(monkeypatch: pytest.MonkeyPatch, token: str | None) -> None:
    monkeypatch.setenv("QA_RESET_ALLOWED", "1")
    monkeypatch.setenv("QA_RESET_TOKEN", "s3cret-token")
    assert _code(hostname=_DEV_HOST, confirm_token=token, tenant="demo") == "qa_reset_token_mismatch"


def test_a_development_host_does_not_open_a_reset_without_a_server_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QA_RESET_ALLOWED", "1")
    monkeypatch.delenv("QA_RESET_TOKEN", raising=False)
    assert _code(hostname=_DEV_HOST, confirm_token="anything", tenant="demo") == "qa_reset_token_unset"


def test_the_host_still_refuses_a_production_name_when_the_other_gates_are_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QA_RESET_ALLOWED", "1")
    monkeypatch.setenv("QA_RESET_TOKEN", "s3cret-token")
    assert (
        _code(hostname="openconstructionerp.com", confirm_token="s3cret-token", tenant="demo")
        == "qa_reset_production_hostname"
    )
