# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Connector contracts for the finance ERP / accounting integration surface.

Design rules baked into the contract:

* ``push`` and ``pull`` both accept ``dry_run`` and MUST be completely
  side-effect-free when it is True - no storage writes, no ledger rows.
  A dry run reports what *would* happen so a user can preview before
  committing. The only write a dry run is allowed to cause is the
  :class:`~app.modules.finance.connector_models.SyncLog` history row the
  service persists, never anything inside the connector itself.
* A connector never holds the request transaction open: the service hands
  it already-gathered data (push) or lets it call the finance service to
  write balanced ledger pairs (pull).
* Secrets live encrypted on the config row and are read through
  :meth:`Connector.credentials`; a connector never logs them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.storage import StorageBackend
    from app.modules.finance.connector_models import AccountingConnectorConfig


class ConnectorError(Exception):
    """Base error for connector operations."""


class ConnectorConfigError(ConnectorError):
    """Raised when a connector's configuration is invalid or unusable."""


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Best-effort coercion of a cell value to ``Decimal`` - never raises.

    Tolerates the thousands/decimal-separator noise that real accounting
    exports carry (``"1,234.50"``, ``"1 234,50"``) by stripping spaces and,
    when a comma is clearly the decimal mark, swapping it for a dot.
    """
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return default
    text = text.replace(" ", "").replace(" ", "")
    if "," in text and "." not in text:
        # "1234,50" -> decimal comma; "1,234" stays ambiguous but the
        # common European decimal-comma case is the safer assumption here.
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return default


@dataclass
class SyncResult:
    """Outcome of a single connector run, persisted into a ``SyncLog`` row."""

    direction: str
    records_in: int = 0
    records_out: int = 0
    file_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """Derive a coarse status from the counts and errors.

        * ``success`` - nothing went wrong.
        * ``partial`` - some records moved but at least one error surfaced.
        * ``failed``  - errors and nothing moved.
        """
        if not self.errors:
            return "success"
        if self.records_in or self.records_out:
            return "partial"
        return "failed"

    def merge(self, other: SyncResult) -> None:
        """Fold another result into this one (used for the ``both`` direction)."""
        self.records_in += other.records_in
        self.records_out += other.records_out
        self.file_keys.extend(other.file_keys)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        for key, value in other.details.items():
            self.details[f"{other.direction}.{key}"] = value


@dataclass
class PushPayload:
    """Normalised rows the service hands a connector for an outbound push.

    Money values are pre-serialised to strings so a connector never has to
    reach back into the ORM or worry about ``Decimal`` precision.
    """

    invoices: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    ledger: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_records(self) -> int:
        return len(self.invoices) + len(self.payments) + len(self.ledger)


@dataclass
class ConnectorField:
    """A single config field a connector exposes to the UI form builder."""

    key: str
    label: str
    kind: str = "text"  # text | textarea | select | secret | bool
    options: tuple[str, ...] = ()
    help: str = ""
    secret: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "options": list(self.options),
            "help": self.help,
            "secret": self.secret,
        }


class Connector(ABC):
    """Abstract base every concrete connector implements.

    Subclasses declare their identity and config surface as class
    variables and implement :meth:`validate_config`, :meth:`push` and
    :meth:`pull`.
    """

    connector_type: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    supported_directions: ClassVar[tuple[str, ...]] = ("push", "pull", "both")
    setting_fields: ClassVar[tuple[ConnectorField, ...]] = ()
    # Market codes whose packs contribute this type; empty = offered to everyone.
    required_markets: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        config: AccountingConnectorConfig,
        *,
        storage: StorageBackend,
        session: AsyncSession,
    ) -> None:
        self.config = config
        self.storage = storage
        self.session = session

    # ── Config access ────────────────────────────────────────────────────

    def settings(self) -> dict[str, Any]:
        """Return the non-secret settings JSON (never raises on bad data)."""
        raw = getattr(self.config, "settings_", None)
        return dict(raw) if isinstance(raw, dict) else {}

    def credentials(self) -> dict[str, Any]:
        """Decrypt and return the credentials JSON, or ``{}`` when unset."""
        import json

        from app.core.crypto import decrypt_secret

        raw = decrypt_secret(getattr(self.config, "credentials", None))
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    # ── Catalogue description (for the registry / UI) ─────────────────────

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """Return a catalogue entry the frontend uses to build the form."""
        return {
            "connector_type": cls.connector_type,
            "display_name": cls.display_name,
            "supported_directions": list(cls.supported_directions),
            "fields": [f.as_dict() for f in cls.setting_fields],
        }

    # ── Behaviour ─────────────────────────────────────────────────────────

    @abstractmethod
    async def validate_config(self) -> list[str]:
        """Return a list of human-readable problems (empty list = valid)."""

    @abstractmethod
    async def push(self, payload: PushPayload, *, dry_run: bool) -> SyncResult:
        """Send finance documents to the external system."""

    @abstractmethod
    async def pull(self, *, dry_run: bool) -> SyncResult:
        """Read general-ledger data from the external system into the platform."""
