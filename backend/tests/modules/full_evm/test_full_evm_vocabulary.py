# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The module's declared vocabularies, checked against their sources of truth.

``VALIDATION_STATUSES`` is not a choice this module gets to make. The write is
``row.validation_status = report.status.value`` in ``_apply_report``, so the set
of values that can reach the column is decided by
``app.core.validation.engine.ValidationStatus``, one import away. The tuple was
missing ``unsupported`` until this file was written, and ``unsupported`` is
precisely the status the engine returns when the ``full_evm`` rule set resolves
to no rules, so the one value that reports a broken registration was the one
value the module said could not occur.

The honest scope of that bug: nothing imports the tuple, and both schemas type
the field as a plain ``str``, so no write was ever refused and no response ever
failed. What was wrong was the module's own published description of its column,
in a name it exports. That is worth being right, and it is worth having a check,
because the reason it stayed wrong is that no code disagreed with it.

Which is also why every assertion below names something outside this module -
the engine's enum, the mapped columns, the writer function. Checking the tuple
against itself, or against string literals repeated in a fixture, would have
agreed with the bug at every step.

``schemas.py`` pins the module's three other vocabularies to their ``Literal``
restatements via ``_check_vocabulary`` at import time. That mechanism does not
fit here, because this tuple is deliberately *not* equal to the enum: it carries
the extra ``pending`` that the column defaults to and the engine can never
produce. The relationship is a superset with one named exception, so it is
spelled out here instead.
"""

from __future__ import annotations

import inspect

from sqlalchemy import Column

from app.core.validation.engine import ValidationStatus
from app.modules.full_evm import models as full_evm_models
from app.modules.full_evm import service as full_evm_service
from app.modules.full_evm.models import VALIDATION_STATUSES

#: The one member that is ours rather than the engine's: the column default,
#: meaning nothing has validated this row yet.
NEVER_VALIDATED = "pending"


def _validation_status_columns() -> list[Column]:
    """Every ``validation_status`` column the module maps, found rather than listed.

    Walking the module's exports means a third model that grows the column is
    covered the day it lands, instead of on the day someone remembers to add it
    here.
    """
    found: list[Column] = []
    for name in full_evm_models.__all__:
        table = getattr(getattr(full_evm_models, name), "__table__", None)
        if table is None:
            continue
        column = table.c.get("validation_status")
        if column is not None:
            found.append(column)
    return found


def test_every_status_the_engine_can_produce_is_a_declared_status() -> None:
    """The engine picks the word; the tuple only gets to describe it.

    This is the direction that matters. A status the engine can return and the
    module has not declared is a row whose value every consumer of this tuple,
    a filter or a report, will treat as unknown.
    """
    engine_values = {status.value for status in ValidationStatus}
    undeclared = engine_values - set(VALIDATION_STATUSES)
    assert not undeclared, (
        f"the engine can write {sorted(undeclared)} into validation_status, but VALIDATION_STATUSES does not list them"
    )


def test_the_only_declared_status_the_engine_cannot_produce_is_the_column_default() -> None:
    """The other direction, so the tuple cannot quietly accumulate dead values.

    Everything here is either a value the engine produces or the documented
    default. An eighth word that is neither would fail this.
    """
    engine_values = {status.value for status in ValidationStatus}
    ours = set(VALIDATION_STATUSES) - engine_values
    assert ours == {NEVER_VALIDATED}, (
        f"VALIDATION_STATUSES declares {sorted(ours)} that the engine never returns; "
        f"only {NEVER_VALIDATED!r}, the column default, is expected to be ours"
    )


def test_unsupported_is_declared_because_a_lost_registration_writes_it() -> None:
    """Name the specific value the bug dropped, so a revert is unambiguous.

    ``unsupported`` is what the engine reports when every requested rule set
    resolves to zero rules. If ``on_startup`` ever stops registering the
    ``full_evm`` rules, this is the word that gets persisted on every baseline
    and measurement, and it has to be a value the module admits exists.
    """
    assert ValidationStatus.UNSUPPORTED.value in VALIDATION_STATUSES


def test_every_declared_status_fits_the_column_it_is_written_to() -> None:
    """Widening the vocabulary must not outgrow the storage.

    Both ``validation_status`` columns are ``String(16)``. A status longer than
    that is a ``DataError`` at the moment of the write, on a code path
    (``_apply_report``) that runs after the useful work is done, so the whole
    save is lost rather than the status alone. The bound is read off the columns
    rather than restated, so a narrowing of either column fails here too.
    """
    columns = _validation_status_columns()
    assert columns, "no validation_status column found, so the loop below checks nothing"
    for column in columns:
        limit = column.type.length
        too_long = [value for value in VALIDATION_STATUSES if len(value) > limit]
        assert not too_long, f"{column.table.name}.{column.name} is String({limit}), which cannot hold {too_long}"


def test_the_writer_still_takes_the_status_straight_from_the_report() -> None:
    """The premise of this whole file, asserted rather than assumed.

    Every check above is only meaningful while ``_apply_report`` copies the
    engine's status onto the row verbatim. If that ever becomes a mapping or a
    lookup, the tuple stops being governed by the engine's enum and these tests
    would be guarding a rule that no longer holds, silently.
    """
    source = inspect.getsource(full_evm_service._apply_report)
    assert "row.validation_status = report.status.value" in source, (
        "_apply_report no longer copies the engine status verbatim, so the "
        "vocabulary checks in this file need rethinking rather than updating"
    )
