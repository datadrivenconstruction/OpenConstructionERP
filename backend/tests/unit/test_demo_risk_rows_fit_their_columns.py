# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every risk row a demo pack seeds has to fit the column it is written to.

The catalogue is a promise: a project a user can pick from the list has to
install. One could not. ``it-park-bangalore`` prices an Indian campus in INR,
the seed scored its risks on a cost-scaled formula, and the eleven-character
result did not fit ``RiskItem.risk_score``, which is a ``String(10)``.
PostgreSQL refused the INSERT, ``POST /api/demo/install/it-park-bangalore``
answered 500 with nothing written, and it did so every time, for as long as the
pack had shipped.

Nothing caught it because nothing compared what the seed writes with what the
column accepts. That comparison is this file. It walks the whole catalogue,
generates the risk rows each entry would seed, and measures every value against
the width declared on the model. The widths are read off ``RiskItem.__table__``
rather than repeated here, so a column narrowed tomorrow is measured at its new
width without anyone remembering to come back.

Two things keep this honest. The score comes from ``_seed_risk_score``, the
function ``install_demo_project`` itself calls, so a seed that goes back to
inventing its own scale fails here rather than in production. And the tuple is
unpacked by position, guarded on arity, so a generator that grows a field
breaks the test instead of quietly shifting every value one column across.

No database: ``_generate_module_data`` is a pure function of the template.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import String

from app.core.demo_projects import (
    DEMO_CATALOG,
    DEMO_TEMPLATES,
    _generate_module_data,
    _seed_risk_score,
)
from app.modules.risk.models import RiskItem

# ``install_demo_project`` unpacks each generated risk as
# (code, title, description, category, probability, impact_cost,
#  schedule_days, severity, mitigation, status).
_RISK_TUPLE_ARITY = 10

_CATALOG_IDS = [entry["demo_id"] for entry in DEMO_CATALOG]


def _declared_width(column_name: str) -> int | None:
    """Return the ``String(n)`` limit on a RiskItem column, or None if unbounded."""
    column_type = RiskItem.__table__.columns[column_name].type
    return column_type.length if isinstance(column_type, String) else None


def _seeded_values(template, risk_row: tuple) -> dict[str, str]:
    """Mirror the column assignment ``install_demo_project`` makes per risk.

    Only the fields whose value can vary with the pack are listed. The two
    constants the seed writes (``contingency_plan`` and ``response_cost``) and
    the ``Text`` columns cannot overflow and are left out.
    """
    _code, title, _desc, category, probability, impact_cost, _days, severity, _mitigation, status = risk_row
    return {
        "code": _code,
        "title": title,
        "category": category,
        "probability": str(probability),
        "impact_cost": str(round(impact_cost, 2)),
        "impact_severity": severity,
        "risk_score": _seed_risk_score(probability, severity),
        "status": status,
        "currency": template.currency,
    }


def _generated_risks(demo_id: str) -> list[tuple]:
    template = DEMO_TEMPLATES[demo_id]
    generated = _generate_module_data(
        template,
        uuid.uuid4(),
        uuid.uuid4(),
        demo_id,
        datetime(2026, 3, 2, tzinfo=UTC),
    )
    return list(generated.get("risks", []))


@pytest.mark.parametrize("demo_id", _CATALOG_IDS)
def test_generated_risk_rows_fit_the_risk_register_columns(demo_id: str) -> None:
    """No value the seed derives for a catalogue entry overflows its column."""
    template = DEMO_TEMPLATES[demo_id]
    risks = _generated_risks(demo_id)
    assert risks, f"{demo_id} generates no risk rows"

    for risk_row in risks:
        assert len(risk_row) == _RISK_TUPLE_ARITY, (
            f"{demo_id}: generated risk tuple has {len(risk_row)} fields, "
            f"but install_demo_project unpacks {_RISK_TUPLE_ARITY}"
        )
        for column_name, value in _seeded_values(template, risk_row).items():
            width = _declared_width(column_name)
            if width is None:
                continue
            assert len(value) <= width, (
                f"{demo_id}: {column_name}={value!r} is {len(value)} characters, "
                f"but oe_risk_register.{column_name} accepts {width}. "
                f"PostgreSQL rejects the INSERT and the whole install returns 500."
            )


def test_the_seeded_score_is_the_registers_own_scale() -> None:
    """The seed scores a risk the way the API does, not on a scale of its own.

    ``_compute_risk_score`` is what ``RiskService`` writes for a risk created
    through the API, and what the router and the summary endpoint recompute on
    read. The seed calling anything else is what put eight-figure values in a
    ten-character column, and what made the cross-project dashboard rank every
    seeded risk above every real one.
    """
    from app.modules.risk.service import _compute_risk_score

    for probability, severity in ((0.1, "low"), (0.45, "medium"), (0.6, "high"), (1.0, "critical")):
        assert _seed_risk_score(probability, severity) == str(_compute_risk_score(probability, severity))


def test_every_catalogue_entry_has_a_template() -> None:
    """A catalogue row without a template is an install that 404s on selection."""
    orphans = sorted(set(_CATALOG_IDS) - set(DEMO_TEMPLATES))
    assert not orphans, f"catalogue entries with no template: {orphans}"
