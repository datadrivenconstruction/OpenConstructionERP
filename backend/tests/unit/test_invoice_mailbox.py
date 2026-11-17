# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Invoice mailbox: settings validation, the IMAP fetch/finish steps and the poll loop.

A fake IMAP client stands in for the server, so what is fetched, what is flagged and what
is moved is asserted exactly. No database and no network.
"""

from __future__ import annotations

import imaplib
import uuid
from contextlib import asynccontextmanager
from email.message import EmailMessage
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.finance import invoice_mailbox_logic as logic
from app.modules.finance import invoice_mailbox_service as svc_mod
from app.modules.finance.invoice_mailbox_service import InvoiceMailboxService

PDF = b"%PDF-1.4\n% scan\n%%EOF"


def _mail(data: bytes = PDF, subject: str = "Scan") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "scan@office.example"
    msg["To"] = "invoices@company.example"
    msg.set_content("scan")
    msg.add_attachment(data, maintype="application", subtype="pdf", filename="a.pdf")
    return msg.as_bytes()


class FakeImap:
    """Records every command; holds a mailbox of ``{uid: raw}`` with a seen set."""

    instances: list[FakeImap] = []

    def __init__(self, messages: dict[str, bytes], fail_login: bool = False, copy_ok: bool = True) -> None:
        self.messages = messages
        self.seen: set[str] = set()
        self.log: list[tuple] = []
        self.fail_login = fail_login
        self.copy_ok = copy_ok
        FakeImap.instances.append(self)

    def login(self, user: str, password: str) -> None:
        self.log.append(("login", user, password))
        if self.fail_login:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, folder: str, readonly: bool = False):
        self.log.append(("select", folder, readonly))
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, cmd: str, *args: Any):
        self.log.append((cmd, *args))
        if cmd == "SEARCH":
            unseen = [u for u in self.messages if u not in self.seen]
            return "OK", [" ".join(unseen).encode()]
        if cmd == "FETCH":
            uid = args[0].decode()
            return "OK", [(b"1 (BODY[] {n}", self.messages[uid]), b")"]
        if cmd == "STORE" and "\\Seen" in args[2]:
            self.seen.add(args[0])
        if cmd == "COPY":
            return ("OK" if self.copy_ok else "NO"), []
        return "OK", []

    def expunge(self) -> None:
        self.log.append(("expunge",))

    def logout(self) -> None:
        self.log.append(("logout",))


def _cfg(**kw: Any) -> logic.MailboxConfig:
    base = {"host": "imap.example.com", "port": 993, "use_ssl": True, "username": "u", "password": "p"}
    base.update(kw)
    return logic.MailboxConfig(**base)


# ── validation ───────────────────────────────────────────────────────────────


def _ok(**kw: Any) -> list[tuple[str, str]]:
    base = {
        "enabled": True,
        "host": "imap.example.com",
        "port": 993,
        "use_ssl": True,
        "username": "u",
        "has_password": True,
        "folder": "INBOX",
        "processed_folder": "",
        "intake_address": "",
    }
    base.update(kw)
    return logic.validate_mailbox_settings(**base)


def test_a_complete_mailbox_is_valid() -> None:
    assert _ok(processed_folder="Processed", intake_address="invoices@company.example") == []


def test_a_disabled_mailbox_may_be_half_filled() -> None:
    assert _ok(enabled=False, host="", username="", has_password=False) == []


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"host": ""}, ("host", "host_required")),
        ({"host": "imaps://x.example"}, ("host", "host_invalid")),
        ({"username": " "}, ("username", "username_required")),
        ({"has_password": False}, ("password", "password_required")),
        ({"port": 70000}, ("port", "port_out_of_range")),
        ({"use_ssl": False}, ("use_ssl", "ssl_required")),
        ({"processed_folder": "inbox"}, ("processed_folder", "folder_same_as_source")),
        ({"intake_address": "not-an-address"}, ("intake_address", "address_invalid")),
        ({"folder": "IN\nBOX"}, ("folder", "folder_invalid")),
    ],
)
def test_each_rule_names_its_field(kw: dict, expected: tuple[str, str]) -> None:
    assert expected in _ok(**kw)


def test_plain_imap_is_allowed_only_on_the_local_machine() -> None:
    assert _ok(host="localhost", use_ssl=False, port=143) == []


# ── fetch / finish ───────────────────────────────────────────────────────────


def test_fetch_peeks_and_does_not_flag() -> None:
    box = FakeImap({"7": _mail(), "9": _mail(b"%PDF-1.4\n%x\n%%EOF")})
    got = logic.fetch_unseen(_cfg(), lambda _c: box)
    assert [m.uid for m in got] == ["7", "9"]
    assert box.seen == set()
    assert ("FETCH", b"7", "(BODY.PEEK[])") in box.log
    assert box.log[-1] == ("logout",)


def test_finish_marks_seen_and_moves_when_a_processed_folder_is_set() -> None:
    box = FakeImap({"7": _mail()})
    logic.finish_messages(_cfg(processed_folder="Done"), ["7"], lambda _c: box)
    assert box.seen == {"7"}
    assert ("COPY", "7", '"Done"') in box.log
    assert ("expunge",) in box.log


def test_finish_without_processed_folder_only_marks_seen() -> None:
    box = FakeImap({"7": _mail()})
    logic.finish_messages(_cfg(), ["7"], lambda _c: box)
    assert box.seen == {"7"}
    assert not any(e[0] in {"COPY", "expunge"} for e in box.log)


def test_a_failed_copy_keeps_the_message_in_place() -> None:
    box = FakeImap({"7": _mail()}, copy_ok=False)
    logic.finish_messages(_cfg(processed_folder="Done"), ["7"], lambda _c: box)
    assert not any(e[0] == "STORE" and "\\Deleted" in e[3] for e in box.log if len(e) > 3)


def test_check_connection_reports_the_message_count_read_only() -> None:
    box = FakeImap({"1": b"x", "2": b"y"})
    assert logic.check_connection(_cfg(), lambda _c: box) == 2
    assert ("select", '"INBOX"', True) in box.log


# ── poller ───────────────────────────────────────────────────────────────────


class _Session:
    def __init__(self) -> None:
        self.flushed = 0

    async def flush(self) -> None:
        self.flushed += 1

    @asynccontextmanager
    async def begin_nested(self):
        yield


def _row(**kw: Any) -> SimpleNamespace:
    base = {
        "project_id": uuid.uuid4(),
        "host": "imap.example.com",
        "port": 993,
        "use_ssl": True,
        "username": "u",
        "password_encrypted": None,
        "folder": "INBOX",
        "processed_folder": "",
        "last_error": "stale",
        "last_polled_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _patch_capture(monkeypatch: pytest.MonkeyPatch, fail_on: bytes | None = None) -> list[bytes]:
    seen: list[bytes] = []

    async def fake_capture(self: Any, *, project_id: Any, raw: bytes, user_id: Any) -> dict:
        seen.append(raw)
        if fail_on is not None and fail_on in raw:
            raise RuntimeError("database down")
        return {"sender": "s", "created": [object()], "duplicates": [], "rejected": []}

    monkeypatch.setattr(svc_mod.InvoiceCaptureService, "capture_from_email", fake_capture)
    monkeypatch.setattr(svc_mod.InvoiceCaptureService, "__init__", lambda self, session: None)
    return seen


@pytest.mark.asyncio
async def test_poll_captures_each_message_then_marks_it_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_capture(monkeypatch)
    box = FakeImap({"7": _mail(), "9": _mail(b"%PDF-1.4\n%x\n%%EOF")})
    row = _row()
    counts = await InvoiceMailboxService(_Session(), lambda _c: box).poll(row)  # type: ignore[arg-type]
    assert counts["messages"] == 2 and counts["created"] == 2 and counts["failed"] == 0
    assert box.seen == {"7", "9"}
    assert row.last_error is None and row.last_polled_at


@pytest.mark.asyncio
async def test_a_failing_message_stays_unseen_and_the_batch_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_capture(monkeypatch, fail_on=b"Subject: BOOM")
    box = FakeImap({"7": _mail(subject="BOOM"), "9": _mail()})
    row = _row()
    counts = await InvoiceMailboxService(_Session(), lambda _c: box).poll(row)  # type: ignore[arg-type]
    assert counts["failed"] == 1 and counts["created"] == 1
    assert box.seen == {"9"}
    assert "1 message" in row.last_error


@pytest.mark.asyncio
async def test_a_dead_mailbox_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_capture(monkeypatch)
    box = FakeImap({"7": _mail()}, fail_login=True)
    row = _row()
    counts = await InvoiceMailboxService(_Session(), lambda _c: box).poll(row)  # type: ignore[arg-type]
    assert counts["messages"] == 0
    assert "AUTHENTICATIONFAILED" in row.last_error and row.last_polled_at


@pytest.mark.asyncio
async def test_the_stored_password_is_decrypted_for_login(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.crypto import encrypt_secret

    _patch_capture(monkeypatch)
    box = FakeImap({})
    row = _row(password_encrypted=encrypt_secret("s3cret"))
    await InvoiceMailboxService(_Session(), lambda _c: box).poll(row)  # type: ignore[arg-type]
    assert ("login", "u", "s3cret") in box.log
    assert row.password_encrypted != "s3cret"


@pytest.mark.asyncio
async def test_test_connection_reports_failure_as_a_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.finance.invoice_mailbox_schemas import MailboxTest

    async def no_row(self: Any, _pid: Any) -> None:
        return None

    monkeypatch.setattr(InvoiceMailboxService, "get", no_row)
    data = MailboxTest(host="imap.example.com", username="u", password="p")
    bad = await InvoiceMailboxService(_Session(), lambda _c: FakeImap({}, fail_login=True)).test(uuid.uuid4(), data)  # type: ignore[arg-type]
    assert bad["ok"] is False and "AUTHENTICATIONFAILED" in bad["error"]
    good = await InvoiceMailboxService(_Session(), lambda _c: FakeImap({"1": b"x"})).test(uuid.uuid4(), data)  # type: ignore[arg-type]
    assert good == {"ok": True, "message_count": 1, "error": None}
