# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure mailbox rules and the stdlib IMAP transport for invoice intake.

No database and no framework: the settings validation and the fetch / finish
steps take a ``client_factory`` so a fake IMAP client drives them in tests.
"""

from __future__ import annotations

import imaplib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MAX_MESSAGES_PER_POLL = 20
IMAP_TIMEOUT_SECONDS = 30
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$|^\[[0-9A-Fa-f:]+\]$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class MailboxConfig:
    host: str
    port: int
    use_ssl: bool
    username: str
    password: str
    folder: str = "INBOX"
    processed_folder: str = ""


@dataclass(frozen=True)
class FetchedMessage:
    uid: str
    raw: bytes


ClientFactory = Callable[[MailboxConfig], Any]


def default_client_factory(cfg: MailboxConfig) -> Any:
    if cfg.use_ssl:
        return imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=IMAP_TIMEOUT_SECONDS)
    return imaplib.IMAP4(cfg.host, cfg.port, timeout=IMAP_TIMEOUT_SECONDS)


def validate_mailbox_settings(
    *,
    enabled: bool,
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    has_password: bool,
    folder: str,
    processed_folder: str,
    intake_address: str,
) -> list[tuple[str, str]]:
    """Return ``(field, code)`` pairs; empty means the settings are acceptable.

    A disabled mailbox may be saved half-filled, an enabled one must be complete.
    """
    errors: list[tuple[str, str]] = []
    host = (host or "").strip()
    if host and not _HOST_RE.match(host):
        errors.append(("host", "host_invalid"))
    if not 1 <= int(port) <= 65535:
        errors.append(("port", "port_out_of_range"))
    for name, value in (("folder", folder), ("processed_folder", processed_folder)):
        if any(ord(c) < 32 for c in value or ""):
            errors.append((name, "folder_invalid"))
    if processed_folder and processed_folder.strip().lower() == (folder or "").strip().lower():
        errors.append(("processed_folder", "folder_same_as_source"))
    if intake_address and not _EMAIL_RE.match(intake_address.strip()):
        errors.append(("intake_address", "address_invalid"))
    if host and not use_ssl and host.lower() not in _LOCAL_HOSTS:
        errors.append(("use_ssl", "ssl_required"))
    if enabled:
        if not host:
            errors.append(("host", "host_required"))
        if not (username or "").strip():
            errors.append(("username", "username_required"))
        if not has_password:
            errors.append(("password", "password_required"))
        if not (folder or "").strip():
            errors.append(("folder", "folder_required"))
    return errors


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def check_connection(cfg: MailboxConfig, client_factory: ClientFactory = default_client_factory) -> int:
    """Log in, open the folder read-only and return how many messages it holds."""
    client = client_factory(cfg)
    try:
        client.login(cfg.username, cfg.password)
        typ, data = client.select(_quote(cfg.folder), readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"folder {cfg.folder!r} cannot be opened")
        return int((data[0] or b"0").decode() or 0)
    finally:
        _close(client)


def fetch_unseen(
    cfg: MailboxConfig,
    client_factory: ClientFactory = default_client_factory,
    limit: int = MAX_MESSAGES_PER_POLL,
) -> list[FetchedMessage]:
    """Fetch up to ``limit`` unseen messages without flagging them (``BODY.PEEK``)."""
    client = client_factory(cfg)
    out: list[FetchedMessage] = []
    try:
        client.login(cfg.username, cfg.password)
        typ, _ = client.select(_quote(cfg.folder))
        if typ != "OK":
            raise imaplib.IMAP4.error(f"folder {cfg.folder!r} cannot be opened")
        typ, data = client.uid("SEARCH", None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return out
        for uid in data[0].split()[:limit]:
            typ, parts = client.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK":
                continue
            raw = next((p[1] for p in parts if isinstance(p, tuple) and len(p) > 1), None)
            if raw:
                out.append(FetchedMessage(uid=uid.decode() if isinstance(uid, bytes) else str(uid), raw=bytes(raw)))
        return out
    finally:
        _close(client)


def finish_messages(
    cfg: MailboxConfig,
    uids: list[str],
    client_factory: ClientFactory = default_client_factory,
) -> None:
    """Mark handled messages seen and, when configured, move them to the processed folder."""
    if not uids:
        return
    client = client_factory(cfg)
    try:
        client.login(cfg.username, cfg.password)
        client.select(_quote(cfg.folder))
        for uid in uids:
            client.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            if cfg.processed_folder:
                typ, _ = client.uid("COPY", uid, _quote(cfg.processed_folder))
                if typ == "OK":
                    client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        if cfg.processed_folder:
            client.expunge()
    finally:
        _close(client)


def _close(client: Any) -> None:
    try:
        client.logout()
    except Exception:  # noqa: BLE001 - closing a dead connection must not mask the real error
        pass
