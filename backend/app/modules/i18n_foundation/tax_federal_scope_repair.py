# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tell an upgraded install that its two country-wide rates are federal layers.

What is wrong on those databases
--------------------------------
``combination`` arrived in ``v3302_tax_combination``. On the boot path a new
column is added by the schema heal and a revision's ``upgrade()`` body is never
executed, so what an existing install gets is the column filled with its server
default, ``national``, on every row. The revision's own backfill - which names
these rows explicitly - does not run, and the revision file says so in as many
words on its ``# boot-repair:`` line.

Ten of the thirteen affected rows are repaired by
:func:`~app.modules.i18n_foundation.tax_subdivision_repair.repair_tax_subdivisions`,
which has to write ``combination`` anyway because the table's check constraint
holds it and ``subdivision_code`` to be one statement. The two that are left are
the country-wide ones, Canadian GST and the United States federal placeholder,
and nothing reaches them: they carry no subdivision either way, so they are
outside that repair's predicate, they break no constraint, and they block
nothing. The install runs on with two rows that quietly describe the wrong
scope.

What it costs
-------------
``national`` and ``federal`` are not two spellings of "country-wide". The
resolver in ``tax_rules`` splits the active rows into three lists by
``combination``, and only the ``federal`` list is the base a sub-national rate
is measured against. With Canadian GST filed as ``national`` that list is empty,
the federal rate is zero, and every Canadian answer that leans on it moves:

* British Columbia resolves to 7 % instead of 5 + 7 = 12 %, and Quebec to
  9.975 % instead of 14.975 %, because a ``stacks_on_federal`` rate is added to
  a federal base that is not there.
* Alberta, which levies no provincial tax, answers ``federal_only`` at 0 % with
  no components at all - a status that says "the federal rate is the whole
  answer" attached to the claim that the federal rate is nothing.
* Ontario and the other harmonised provinces are unaffected, because a
  ``replaces_federal`` rate never reads the base. That is the awkward part: the
  province most likely to be checked first is the one that looks right.

It also reaches the write path. ``TaxConfigurationService._country_has_federal_layer``
asks whether any row of the country is ``federal``, and the answer is what stops
a new Canadian rate being saved as ``national``. On an unrepaired install that
guard is off, so the database can acquire more rows with the same defect through
the API.

Fill, never overwrite
---------------------
The value was never right, so this is ``always_wrong`` rather than
``superseded``: there is no date on which these rows correctly said
``national``. Correcting it in place is the whole repair.

Landing it moves money, and that is the point rather than a side effect. On an
unrepaired Canadian database the answers above are what a caller gets today, so
the repair takes Alberta from 0 % to 5 %, British Columbia from 7 % to 12 % and
Quebec from 9.975 % to 14.975 %. Every one of those is a correction of a number
that is wrong now, not a re-pricing of one that was right until some date.

No issued document reprices, and that is measured rather than assumed, because
it is the question that decides whether a rate correction may be applied in
place at all. An invoice carries its own ``amount_subtotal``, ``tax_amount``,
``retention_amount`` and ``amount_total`` as stored columns, with the EN 16931
per-line rate in ``finance.InvoiceLine.vat_rate``, and ``tax_config_id`` is a
plain reference rather than a live lookup. Nothing in a document path reaches
the resolver: ``tax_rules.resolve`` has one consumer,
``I18nFoundationService.resolve_tax_rate``, reached only from this module's own
``/tax-rate`` endpoint, and neither ``finance`` nor ``procurement`` imports this
module at all. So what changes when this lands is the live lookup surface - the
tax rate screen and the ``_country_has_federal_layer`` write guard - and not the
history.

Even so the statement only writes where ``combination`` is still ``national``,
which is the value the server default left, and where ``subdivision_code`` is
NULL. Three things follow:

* An operator who deliberately set one of these rows to something else keeps
  what they set. The repair has an opinion about the default it recognises, not
  about an answer somebody gave.
* Re-running is a no-op, which the registry requires: after the first pass no
  row matches. Idempotence is a property of the statement, not of a marker
  saying the repair already ran.
* A row that somehow carries both this tax code and a subdivision is skipped
  rather than written. Writing ``federal`` onto it would breach
  ``subdivision_matches_combination`` and fail the repair on every boot
  thereafter, and a Canadian GST row filed under a province is somebody's own
  edit rather than the default this repair recognises.

What it will not touch
----------------------
``rate_pct`` is never in the statement, and neither is anything else. Only the
exact ``(country_code, tax_code)`` pairs this platform ships as federal layers,
listed in :data:`SHIPPED_FEDERAL_COMBINATION`. A country-wide rate a deployment
added by hand is not guessed at: whether it is the base of a sub-national
structure or the entire answer for its country is a question about that
jurisdiction, not about its tax code.
"""

from __future__ import annotations

import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import TaxConfiguration

logger = logging.getLogger(__name__)

#: The value the boot heal leaves on every pre-existing row, and the only value
#: this repair is willing to replace. Named rather than spelled inline at the
#: predicate so the reason it is the marker - it is the column's server default,
#: not a considered answer - stays attached to it.
_UNSET_COMBINATION = "national"

#: Which of the shipped country-wide rates are federal layers, keyed on country
#: plus tax code. Same shape as
#: :data:`~app.modules.i18n_foundation.subdivisions.SHIPPED_SUBDIVISION_COMBINATION`
#: and for the same reason: it is a repair table rather than a source of truth,
#: recording what the seed file says for rows an upgraded install got the
#: default for instead.
#:
#: It lives here rather than in ``subdivisions.py`` because neither row has a
#: subdivision and neither ever will. A federal layer is the thing sub-national
#: rates are measured against, which is the opposite end of that axis.
#:
#: Canada's GST is the base its provinces stack on or replace. The United States
#: row is a zero-rate placeholder and is still ``federal`` rather than
#: ``national``, because what it exists to state is that the federal layer is
#: nothing, which is what a state rate adds to. Hong Kong ships an identically
#: shaped ``NONE`` row and stays ``national``, since nothing sits alongside it -
#: which is why this is a list of pairs and not a rule about zero rates.
#: Pakistan's federal sales tax is the layer the provincial services taxes sit beside.
SHIPPED_FEDERAL_COMBINATION: dict[tuple[str, str], str] = {
    ("CA", "GST"): "federal",
    ("US", "NONE"): "federal",
    ("PK", "GST"): "federal",
}


async def repair_federal_tax_scope(session: AsyncSession) -> int:
    """Move the shipped country-wide rates from ``national`` to ``federal``.

    Args:
        session: An open session. The caller commits; the repair registry does.

    Returns:
        Number of rows corrected by this call. Zero on every boot after the
        first, and zero on a fresh install, where the seed file already carries
        the values.
    """
    repaired = 0
    for (country_code, tax_code), combination in SHIPPED_FEDERAL_COMBINATION.items():
        result = await session.execute(
            update(TaxConfiguration)
            .where(
                TaxConfiguration.country_code == country_code,
                TaxConfiguration.tax_code == tax_code,
                TaxConfiguration.combination == _UNSET_COMBINATION,
                TaxConfiguration.subdivision_code.is_(None),
            )
            .values(combination=combination)
        )
        repaired += result.rowcount or 0

    if repaired:
        logger.info(
            "Corrected %d country-wide tax row(s) that described themselves as national "
            "rather than as the federal layer their subdivisions are measured against.",
            repaired,
        )
    return repaired
