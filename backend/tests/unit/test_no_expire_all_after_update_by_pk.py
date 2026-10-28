# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠No repository may follow an update-by-primary-key with ``expire_all()``.

``UPDATE ... WHERE id = :pk`` writes past the ORM, and the tempting repair is
``session.expire_all()``. It marks every loaded instance stale, so the next
attribute read anywhere in the session becomes a lazy load from async code and
raises ``MissingGreenlet`` - a fault that surfaces far from the repository that
caused it. :func:`app.core.orm_write.apply_update` reconciles just the row it
wrote.

The check is deliberately narrow. It matches only the plain update-by-pk
sequence, so conditional updates, bulk updates and a deliberate expiry before a
re-read are left alone; those need their own treatment, not this one.
"""

from __future__ import annotations

import re
from pathlib import Path

BANNED = re.compile(
    r"stmt = update\((?P<model>\w+)\)\.where\((?P=model)\.id == \w+\)\.values\(\*\*\w+\)\s*\n"
    r"\s*await self\.session\.execute\(stmt\)\s*\n"
    r"\s*await self\.session\.flush\(\)\s*\n"
    r"\s*self\.session\.expire_all\(\)",
)

APP = Path(__file__).resolve().parents[2] / "app"


def test_update_by_pk_never_expires_the_whole_session() -> None:
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        source = path.read_text(encoding="utf-8", errors="replace")
        if "expire_all()" not in source:
            continue
        for match in BANNED.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(APP.parent)}:{line}")

    assert not offenders, (
        "update-by-pk followed by expire_all(); use "
        "app.core.orm_write.apply_update instead:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_actually_matches_the_shape_it_bans() -> None:
    """A guard that cannot fail is not a guard."""
    sample = (
        "        stmt = update(Invoice).where(Invoice.id == invoice_id).values(**fields)\n"
        "        await self.session.execute(stmt)\n"
        "        await self.session.flush()\n"
        "        self.session.expire_all()\n"
    )
    assert BANNED.search(sample) is not None

    converted = "        await apply_update(self.session, Invoice, invoice_id, **fields)\n"
    assert BANNED.search(converted) is None
