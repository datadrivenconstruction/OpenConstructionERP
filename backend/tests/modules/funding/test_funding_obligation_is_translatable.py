# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A derived deadline has to be readable by somebody who does not read English.

The React client never showed the problem, because it renders a deadline from
the ``kind`` enum through its own locales and ignores the sentence the server
stored. Every other caller of the REST API got the sentence, and a sentence is
data: there is no later moment at which it can be translated.

So each derived obligation now carries the two halves that can be translated,
``detail_key`` and ``detail_params``, and the English prose in ``detail``
became the rendering of those two rather than the original of them. The tests
here hold the three things that arrangement can get wrong.

**The halves can disagree.** A sentence edited at the call site while its key
stays put leaves a row whose prose and whose key say different things, and
whichever a reader believes, the other one is a lie. Nothing about that is
visible: both fields are populated and both are plausible.

**A key can be minted and never translated.** ``check_i18n_orphan_keys.py``
counts keys called with a default value in the front end's own source, so a
key the back end writes into a row and the client never spells out is invisible
to it. The gate stays green whether the key reached 43 locale files or one.
Nothing else was checking, which is why the check is here and reads the locale
files directly.

**A translation can drop the number.** "Due {{days}} days after the award
period ends" is worth translating. "Due days after the award period ends" is
not, and it fails silently, because a missing interpolation value renders as
nothing at all rather than as an error.

The title has the same two halves and one more way to go wrong, so the same
three checks are made of it here. ``title_key`` is not stored: it is the kind
key for a deadline the server derived and empty for one somebody typed, and
what separates those is ``source``. Getting that line wrong is silent in both
directions - a key on a typed row replaces somebody's note with a generic
label, and no key on a derived row leaves the server's English on a page in
another language. The rollup carries the same string, so it carries the same
key, and the one value the key deliberately does not interpolate travels
beside it.
"""

from __future__ import annotations

import json
import pathlib
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funding import service as funding_service
from app.modules.funding.models import FundingObligation
from app.modules.funding.router import _title_key
from app.modules.funding.schemas import _OBLIGATION_KIND
from app.modules.funding.service import (
    OBLIGATION_DETAIL_TEMPLATES,
    FundingService,
    obligation_title_params,
    render_detail,
)
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session

#: Found through the module itself rather than through a relative path, so the
#: tests pass wherever pytest was started from.
_SERVICE_SOURCE = pathlib.Path(str(funding_service.__file__))
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_LOCALE_DIR = _REPO_ROOT / "frontend" / "src" / "app" / "locales"

#: A key that already ships in every locale a reader can select. It is the
#: sibling of the four new ones - the client renders an obligation's title
#: from it - so the files that answer it are exactly the files that have to
#: answer these. Asking the tree this way rather than listing 43 filenames
#: means a locale added tomorrow is covered without anybody editing this file.
_SIBLING_KEY = "funding.obligation_kind.final_report"


def _detail_keys_the_service_writes() -> set[str]:
    """Every ``funding.obligation_detail.`` key the service source can store."""
    source = _SERVICE_SOURCE.read_text("utf-8")
    return set(re.findall(r'"(funding\.obligation_detail\.[a-z_]+)"', source))


def _required_locale_files() -> list[pathlib.Path]:
    """The locale files that carry the sibling key, and so must carry these."""
    return sorted(path for path in _LOCALE_DIR.glob("*.ts") if f'"{_SIBLING_KEY}"' in path.read_text("utf-8"))


def _locale_value(text: str, key: str) -> str | None:
    """One key's translated value out of a locale file, or ``None`` if absent.

    The files are one ``"key": "value",`` per line. The value is pulled out as
    a JSON string rather than by slicing, so an apostrophe escaped in the file
    arrives here as the character a reader would see.
    """
    match = re.search(rf'"{re.escape(key)}":\s*("(?:[^"\\]|\\.)*")', text)
    if match is None:
        return None
    return json.loads(match.group(1))


def _title_keys_the_module_can_state() -> list[str]:
    """Every ``funding.obligation_kind.`` key ``title_key`` can point at.

    Read off the pattern the API validates ``kind`` against rather than listed
    here, so a kind added to the module is covered the day it is added instead
    of the day somebody remembers this file.
    """
    kinds = _OBLIGATION_KIND.removeprefix("^(").removesuffix(")$").split("|")
    return sorted(f"funding.obligation_kind.{kind}" for kind in kinds if kind)


def _placeholders(template: str) -> set[str]:
    """The names a template interpolates, in either spelling.

    Python's ``str.format`` writes ``{days}`` and i18next writes ``{{days}}``.
    Both reduce to the same name, which is the thing that has to survive a
    translation.
    """
    return set(re.findall(r"\{\{?(\w+)\}?\}", template))


# ── The two halves of the sentence have to agree ────────────────────────


def test_every_key_the_service_stores_has_a_sentence_to_render() -> None:
    """A key with no template renders an empty detail, and nobody would notice."""
    written = _detail_keys_the_service_writes()
    # Guard against the scan finding nothing and making the comparison vacuous.
    assert len(written) >= 4, sorted(written)
    assert written == set(OBLIGATION_DETAIL_TEMPLATES), {
        "stored but never templated": sorted(written - set(OBLIGATION_DETAIL_TEMPLATES)),
        "templated but never stored": sorted(set(OBLIGATION_DETAIL_TEMPLATES) - written),
    }


def test_an_unknown_key_renders_nothing_rather_than_half_a_sentence() -> None:
    assert render_detail("funding.obligation_detail.not_a_key", {"days": 30}) == ""


def test_a_missing_value_renders_nothing_rather_than_a_sentence_with_a_hole() -> None:
    assert render_detail("funding.obligation_detail.final_report", {"days": 30}) == ""


# ── Every key reaches every locale ──────────────────────────────────────


def test_the_locale_files_this_check_reads_are_really_there() -> None:
    """A check that discovers no files passes without measuring anything."""
    assert _LOCALE_DIR.is_dir(), f"the locale directory moved: {_LOCALE_DIR}"
    required = _required_locale_files()
    assert len(required) >= 40, [path.name for path in required]
    # en-US is an overlay of American spellings rather than a full locale, and
    # en-GB is the same for British ones. Neither answers the sibling key, so
    # neither is asked for these. Stated here so that a change which starts
    # pulling them in fails loudly instead of quietly widening the job.
    assert {"en-US.ts", "en-GB.ts"}.isdisjoint({path.name for path in required})


def test_every_locale_answers_every_detail_key() -> None:
    missing: dict[str, list[str]] = {}
    for path in _required_locale_files():
        text = path.read_text("utf-8")
        absent = sorted(key for key in OBLIGATION_DETAIL_TEMPLATES if _locale_value(text, key) is None)
        if absent:
            missing[path.name] = absent
    assert missing == {}, missing


def test_every_locale_answers_every_title_key_the_module_states() -> None:
    """The title has a key too, and it is only worth having if it resolves.

    ``title_key`` was a field the client happened to read and the server
    happened to fill. It is now the contract on two surfaces - the deadline
    list and the application summary - so every value it can take has to reach
    every locale, not just the one kind this file already used as its sibling.
    """
    keys = _title_keys_the_module_can_state()
    # A scan that finds no kinds would make the comparison below vacuous.
    assert len(keys) >= 8, keys

    missing: dict[str, list[str]] = {}
    for path in _required_locale_files():
        text = path.read_text("utf-8")
        absent = sorted(key for key in keys if _locale_value(text, key) is None)
        if absent:
            missing[path.name] = absent
    assert missing == {}, missing


def test_no_title_key_carries_a_placeholder_no_caller_fills() -> None:
    """The name of a deadline interpolates nothing, on purpose.

    The same key labels the group a deadline belongs to as well as the
    deadline itself, so a draw number put inside it would split that group.
    The number travels in ``title_params`` instead. A locale that added a
    placeholder would render a hole on both surfaces and nothing would say so.
    """
    holes: dict[str, list[str]] = {}
    for path in _required_locale_files():
        text = path.read_text("utf-8")
        for key in _title_keys_the_module_can_state():
            value = _locale_value(text, key)
            if value is not None and _placeholders(value):
                holes.setdefault(path.name, []).append(key)
    assert holes == {}, holes


def test_no_translation_drops_the_number_the_sentence_is_about() -> None:
    """A dropped placeholder renders as nothing, not as an error."""
    wrong: dict[str, dict[str, Any]] = {}
    for path in _required_locale_files():
        text = path.read_text("utf-8")
        for key, template in OBLIGATION_DETAIL_TEMPLATES.items():
            value = _locale_value(text, key)
            if value is None:
                continue  # Reported by the test above; not this one's finding.
            if _placeholders(value) != _placeholders(template):
                wrong[f"{path.name}:{key}"] = {
                    "expected": sorted(_placeholders(template)),
                    "found": sorted(_placeholders(value)),
                }
    assert wrong == {}, wrong


def test_no_locale_is_left_holding_the_english_sentence() -> None:
    """A copied English string is a hole that reads as though it were filled."""
    untranslated: list[str] = []
    for path in _required_locale_files():
        if path.name == "en.ts":
            continue
        text = path.read_text("utf-8")
        for key, template in OBLIGATION_DETAIL_TEMPLATES.items():
            value = _locale_value(text, key)
            if value is not None and _placeholders(value) and value == template.replace("{", "{{").replace("}", "}}"):
                untranslated.append(f"{path.name}:{key}")
    assert untranslated == [], untranslated


# ── The same thing, against a real database ─────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"funding-i18n-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Funding",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Funding {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def _awarded(session: AsyncSession) -> tuple[FundingService, Any, Any]:
    """An approved application under a programme that implies every deadline."""
    service = FundingService(session)
    project_id = await _project(session)
    programme = await service.programmes.create(
        code=f"KFW-{uuid.uuid4().hex[:6].upper()}",
        name="Energy efficient refurbishment",
        country="DE",
        proof_of_use_due_days=180,
        disbursement_spend_days=60,
        retention_years=10,
        currency="EUR",
        status="open",
    )
    application = await service.applications.create(
        project_id=project_id,
        programme_id=programme.id,
        code=f"APP-{uuid.uuid4().hex[:6].upper()}",
        currency="EUR",
        status="draft",
        eligible_cost_base=Decimal("1000000"),
        requested_amount=Decimal("350000"),
    )
    await service.record_award(
        application,
        approved=True,
        approved_amount=Decimal("350000"),
        award_period_start="2026-04-01",
        award_period_end="2026-12-31",
    )
    return service, programme, application


def _by_kind(rows: list[FundingObligation]) -> dict[str, FundingObligation]:
    return {row.kind: row for row in rows}


async def test_the_stored_prose_is_exactly_what_the_key_and_its_values_render(session: AsyncSession) -> None:
    """The half a reader believes and the half a translator reads must match."""
    service, _programme, application = await _awarded(session)
    disbursement = await service.disbursements.create(
        application_id=application.id,
        sequence=1,
        code="MA-2026-01",
        amount_requested=Decimal("60000"),
        status="submitted",
    )
    await service.on_funds_received(application, disbursement, "2026-09-20")

    rows = await service.obligations.list_for_application(application.id)
    assert {row.kind for row in rows} == {"final_report", "retention_end", "spend_window"}
    for row in rows:
        assert row.detail_key, f"{row.kind} was derived without a key"
        assert row.detail, f"{row.kind} rendered to nothing"
        assert row.detail == render_detail(row.detail_key, row.detail_params)


async def test_each_derived_deadline_carries_the_key_and_the_values_its_terms_imply(
    session: AsyncSession,
) -> None:
    service, programme, application = await _awarded(session)
    disbursement = await service.disbursements.create(
        application_id=application.id,
        sequence=2,
        code="MA-2026-02",
        amount_requested=Decimal("60000"),
        status="submitted",
    )
    await service.on_funds_received(application, disbursement, "2026-09-20")
    rows = _by_kind(await service.obligations.list_for_application(application.id))

    assert rows["final_report"].detail_key == "funding.obligation_detail.final_report"
    assert rows["final_report"].detail_params == {"days": 180, "programme": programme.code}

    assert rows["retention_end"].detail_key == "funding.obligation_detail.retention_end"
    assert rows["retention_end"].detail_params == {"years": 10, "programme": programme.code}

    assert rows["spend_window"].detail_key == "funding.obligation_detail.spend_window"
    # The draw is named in the values even though the sentence never says it,
    # because the title does and a caller rendering the title from ``kind``
    # would otherwise be matching draws on a date and guessing on a tie.
    assert rows["spend_window"].detail_params == {
        "days": 60,
        "programme": programme.code,
        "sequence": 2,
    }


async def test_accepting_the_proof_of_use_changes_which_sentence_the_retention_deadline_tells(
    session: AsyncSession,
) -> None:
    """One kind, two sentences. This is why the key is stored, not derived from ``kind``."""
    service, _programme, application = await _awarded(session)
    before = _by_kind(await service.obligations.list_for_application(application.id))
    assert before["retention_end"].detail_key == "funding.obligation_detail.retention_end"

    proof = await service.proofs.create(application_id=application.id, kind="final", status="submitted")
    await service.on_proof_accepted(application, proof, "2027-03-31")

    after = _by_kind(await service.obligations.list_for_application(application.id))
    assert after["retention_end"].detail_key == "funding.obligation_detail.retention_end_accepted"
    assert after["retention_end"].detail_params == {"years": 10, "accepted_on": "2027-03-31"}
    assert after["retention_end"].detail == render_detail(
        after["retention_end"].detail_key, after["retention_end"].detail_params
    )


async def test_an_obligation_somebody_typed_carries_no_key_at_all(session: AsyncSession) -> None:
    """Their words are not a key into anything, and translating them loses the note."""
    service, _programme, application = await _awarded(session)
    typed = await service.obligations.create(
        application_id=application.id,
        kind="condition",
        title="Display the funding sign on the hoarding",
        detail="The authority sends the artwork",
        due_on="2026-05-01",
        source="manual",
        status="open",
    )
    assert typed.detail_key == ""
    assert typed.detail_params == {}
    assert _title_key(typed) == ""


async def test_a_derived_deadline_is_named_by_its_kind(session: AsyncSession) -> None:
    service, _programme, application = await _awarded(session)
    rows = _by_kind(await service.obligations.list_for_application(application.id))
    assert _title_key(rows["final_report"]) == "funding.obligation_kind.final_report"
    assert _title_key(rows["retention_end"]) == "funding.obligation_kind.retention_end"


async def test_a_typed_obligation_with_no_words_still_gets_a_name(session: AsyncSession) -> None:
    """Falling back to the kind beats showing a reader an empty cell."""
    service, _programme, application = await _awarded(session)
    blank = await service.obligations.create(
        application_id=application.id,
        kind="condition",
        title="   ",
        due_on="2026-05-01",
        source="manual",
        status="open",
    )
    assert _title_key(blank) == "funding.obligation_kind.condition"


async def test_a_condition_out_of_the_award_notice_keeps_the_words_somebody_typed(
    session: AsyncSession,
) -> None:
    """Typed is typed, whichever source it was filed under.

    The module writes ``programme_rule`` on the rows it derives and forces a
    hand written one away from that value, so ``programme_rule`` is the single
    thing that means "the server wrote this title". Asking about ``manual``
    instead answered this row wrongly: a condition copied out of an award
    notice came back carrying a key, and a caller that believed the key put
    "Condition of the award" on the page where somebody had written what the
    condition actually was.
    """
    service, _programme, application = await _awarded(session)
    typed = await service.obligations.create(
        application_id=application.id,
        kind="condition",
        title="Keep the funding sign on the hoarding until handover",
        detail="Paragraph 7 of the notice",
        due_on="2026-05-01",
        source="award_notice",
        status="open",
    )
    assert _title_key(typed) == ""
    assert obligation_title_params(typed) == {}


async def test_the_reference_a_derived_title_names_travels_beside_its_key(
    session: AsyncSession,
) -> None:
    """The prose says which draw; the key cannot, so the number goes beside it.

    ``funding.obligation_kind.spend_window`` has no placeholder in it, and it
    stays that way because the same key labels the group a deadline belongs to.
    A caller renders the key and attaches the reference itself, which it can
    only do if the reference is on the wire.
    """
    service, _programme, application = await _awarded(session)
    disbursement = await service.disbursements.create(
        application_id=application.id,
        sequence=3,
        code="MA-2026-03",
        amount_requested=Decimal("60000"),
        status="submitted",
    )
    await service.on_funds_received(application, disbursement, "2026-09-20")
    rows = _by_kind(await service.obligations.list_for_application(application.id))

    assert obligation_title_params(rows["spend_window"]) == {"sequence": 3}
    # The other two titles are whole sentences on their own and name nothing.
    assert obligation_title_params(rows["final_report"]) == {}
    assert obligation_title_params(rows["retention_end"]) == {}


def test_a_title_reference_is_read_off_a_row_that_never_stored_one() -> None:
    """``detail_params`` reads back ``None`` on an upgraded installation.

    Not reachable through this test database, and that is the point: the column
    is NOT NULL on anything ``create_all`` builds, so the row can only be made
    by hand. It is the shape measured on a database that reached the column
    through the boot heal, where a callable default could not be rendered into
    DDL and the column arrived nullable. Indexing it rather than guarding it
    turns the summary endpoint into a 500, and the summary is the one endpoint
    that stayed up the last time these two columns caught us out.
    """
    row = SimpleNamespace(source="programme_rule", kind="spend_window", title="", detail_params=None)

    assert obligation_title_params(row) == {}  # type: ignore[arg-type]


async def test_the_summary_names_the_next_deadline_by_kind_as_well_as_by_title(
    session: AsyncSession,
) -> None:
    """``next_due_title`` is the server's English; ``next_due_kind`` is translatable."""
    service, _programme, application = await _awarded(session)
    summary = await service.application_summary(application, today="2026-06-01")

    assert summary["next_due_on"] == "2027-06-29"
    assert summary["next_due_kind"] == "final_report"
    assert summary["next_due_title"] == "Final proof of use"


async def test_the_summary_states_the_key_its_next_deadline_can_be_read_in(
    session: AsyncSession,
) -> None:
    """The one string on the rollup a person reads, with a key beside it.

    ``next_due_title`` is the server's English and there is no later moment at
    which it can be translated. ``next_due_kind`` was put beside it first, and
    it is not enough: it says what the deadline is about, not whose words the
    title is, so a caller reading it alone either leaves English on the page or
    translates away a note somebody wrote.
    """
    service, _programme, application = await _awarded(session)
    summary = await service.application_summary(application, today="2026-06-01")

    assert summary["next_due_title"] == "Final proof of use"
    assert summary["next_due_title_key"] == "funding.obligation_kind.final_report"
    assert summary["next_due_title_params"] == {}


async def test_the_summary_names_the_draw_when_a_spend_window_is_what_is_due_next(
    session: AsyncSession,
) -> None:
    """Two spend windows on one award differ by draw, and only by draw."""
    service, _programme, application = await _awarded(session)
    disbursement = await service.disbursements.create(
        application_id=application.id,
        sequence=4,
        code="MA-2026-04",
        amount_requested=Decimal("60000"),
        status="submitted",
    )
    await service.on_funds_received(application, disbursement, "2026-09-20")
    summary = await service.application_summary(application, today="2026-10-01")

    # Sixty days from receipt, which lands before the report and the retention.
    assert summary["next_due_on"] == "2026-11-19"
    assert summary["next_due_title_key"] == "funding.obligation_kind.spend_window"
    assert summary["next_due_title_params"] == {"sequence": 4}


async def test_the_summary_leaves_a_typed_next_deadline_in_the_words_it_was_typed_in(
    session: AsyncSession,
) -> None:
    """An empty key is the answer, not a missing one."""
    service, _programme, application = await _awarded(session)
    await service.obligations.create(
        application_id=application.id,
        kind="condition",
        title="Send the interim photographs to the Land office",
        due_on="2026-05-15",
        source="award_notice",
        status="open",
    )
    summary = await service.application_summary(application, today="2026-04-01")

    assert summary["next_due_on"] == "2026-05-15"
    assert summary["next_due_title"] == "Send the interim photographs to the Land office"
    assert summary["next_due_title_key"] == ""
    assert summary["next_due_title_params"] == {}


async def test_a_summary_with_nothing_due_names_no_kind(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await _project(session)
    programme = await service.programmes.create(
        code=f"NONE-{uuid.uuid4().hex[:6].upper()}",
        country="DE",
        proof_of_use_due_days=0,
        retention_years=0,
        currency="EUR",
        status="open",
    )
    application = await service.applications.create(
        project_id=project_id,
        programme_id=programme.id,
        code=f"APP-{uuid.uuid4().hex[:6].upper()}",
        currency="EUR",
        status="draft",
    )
    summary = await service.application_summary(application, today="2026-06-01")
    assert summary["next_due_kind"] == ""
    assert summary["next_due_title"] == ""
    assert summary["next_due_title_key"] == ""
    assert summary["next_due_title_params"] == {}


@pytest.mark.parametrize("key", sorted(OBLIGATION_DETAIL_TEMPLATES))
def test_english_is_carried_by_the_locale_file_too(key: str) -> None:
    """The bundle the other 42 fall back to has to answer as well."""
    text = (_LOCALE_DIR / "en.ts").read_text("utf-8")
    value = _locale_value(text, key)
    assert value is not None, f"en.ts never answers {key}"
    assert _placeholders(value) == _placeholders(OBLIGATION_DETAIL_TEMPLATES[key])
