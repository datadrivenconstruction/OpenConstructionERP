# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One vocabulary for every reason a payment certificate can show.

A line of the certificate that has no figure says why with a reason key. The
calculator emits some keys, the module that stores a document's taxes emits
one, and the certificate emits the rest. They all reach the same screen and
the same printed sheet, so they are listed in one place,
``app.core.payment_taxes.ALL_REASON_KEYS``, and this file holds the three
sides to it: the keys the consumers' source really uses, the list, and the
printed sentence of each key in both languages.

Also here: the registry that says which project a source document belongs to,
and the check of a contract's certificate settings. Neither needs a database.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest
from fastapi import HTTPException

from app.core.payment_taxes import ALL_REASON_KEYS, CONSUMER_REASON_KEYS, REASON_KEYS
from app.modules.contracts import certificate_taxes, hakedis, hakedis_document
from app.modules.contracts.hakedis_layout import HAKEDIS_LABELS
from app.modules.tax_withholding import service as tax_service
from app.modules.tax_withholding import source_owners

CONSUMERS = [
    pathlib.Path(str(module.__file__)) for module in (hakedis, certificate_taxes, hakedis_document, tax_service)
]

#: Calls whose argument at this position is a reason key.
REASON_CALLS = {"_held": 1, "held_result": 0, "add": 1}
#: Keyword arguments and dataclass fields that carry a reason key.
REASON_NAMES = {"reason_key", "previous_held_reason", "held_reason"}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _strings(node: ast.AST | None) -> set[str]:
    """Every literal a reason expression can evaluate to (``a or "b"``, ``x if c else "y"``).

    A string that is only an argument or a subscript inside the expression,
    as in ``values["reason_key"]``, is not a value of it and is not collected.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.BoolOp):
        return set().union(*(_strings(value) for value in node.values))
    if isinstance(node, ast.IfExp):
        return _strings(node.body) | _strings(node.orelse)
    return set()


def reasons_in(path: pathlib.Path) -> set[str]:
    """The reason keys one consumer writes, read from its syntax tree."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            position = REASON_CALLS.get(_name(node.func))
            if position is not None and len(node.args) > position:
                found |= _strings(node.args[position])
            for keyword in node.keywords:
                if keyword.arg in REASON_NAMES:
                    found |= _strings(keyword.value)
        elif isinstance(node, ast.AnnAssign) and _name(node.target) in REASON_NAMES:
            found |= _strings(node.value)
    return found - {""}


def all_constants(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_the_reader_finds_reason_keys_in_every_consumer_that_emits_them() -> None:
    """Guard on the instrument: a reader that finds nothing would pass every check below."""
    found = {path.name: reasons_in(path) for path in CONSUMERS}
    assert "not_entered" in found["hakedis.py"]
    assert "previous_unknown" in found["hakedis.py"]
    assert "provider_failed" in found["certificate_taxes.py"]
    assert "stamp_duty_base_unknown" in found["service.py"]


@pytest.mark.parametrize("path", CONSUMERS, ids=lambda path: path.name)
def test_a_consumer_uses_no_reason_outside_the_shared_vocabulary(path: pathlib.Path) -> None:
    assert reasons_in(path) <= set(ALL_REASON_KEYS), sorted(reasons_in(path) - set(ALL_REASON_KEYS))


def test_every_consumer_reason_is_written_somewhere() -> None:
    """A key nobody emits is a sentence nobody will ever read; it should leave the list."""
    written: set[str] = set()
    for path in CONSUMERS:
        written |= all_constants(path)
    # ``other`` is the sentence printed for a key the table does not know; it
    # is reached through its label, never set as a reason.
    assert "reason.other" in written
    expected = set(CONSUMER_REASON_KEYS) - {"other"}
    assert expected <= written, sorted(expected - written)


def test_the_two_halves_of_the_vocabulary_do_not_overlap() -> None:
    assert not set(REASON_KEYS) & set(CONSUMER_REASON_KEYS)
    assert len(set(ALL_REASON_KEYS)) == len(ALL_REASON_KEYS)


@pytest.mark.parametrize("language", ["tr", "en"])
def test_every_reason_has_its_sentence_and_every_sentence_its_reason(language: str) -> None:
    labelled = {key.removeprefix("reason.") for key in HAKEDIS_LABELS[language] if key.startswith("reason.")}
    assert labelled == set(ALL_REASON_KEYS) - {""}


def test_the_two_languages_do_not_share_a_reason_sentence() -> None:
    for key in ALL_REASON_KEYS:
        if key:
            assert HAKEDIS_LABELS["tr"][f"reason.{key}"] != HAKEDIS_LABELS["en"][f"reason.{key}"], key


# ── Who owns a source document ───────────────────────────────────────────────


@pytest.fixture
def owners():
    before = dict(source_owners._resolvers)
    source_owners._resolvers.clear()
    yield source_owners
    source_owners._resolvers.clear()
    source_owners._resolvers.update(before)


@pytest.mark.asyncio
async def test_a_kind_nobody_registered_for_belongs_to_no_project(owners) -> None:
    project = uuid.uuid4()
    assert owners.registered_source_kinds() == ()
    with pytest.raises(owners.SourceOwnerMissingError):
        await owners.resolve_source_project(None, "progress_claim", uuid.uuid4())
    assert not await owners.source_belongs_to_project(
        None, source_kind="progress_claim", source_id=uuid.uuid4(), project_id=project
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("flavour", ["sync", "async"])
async def test_the_owner_decides_and_only_its_own_project_matches(owners, flavour: str) -> None:
    mine, theirs, document, unknown = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    known = {document: mine}

    def sync_resolver(_session, source_id):
        return known.get(source_id)

    async def async_resolver(_session, source_id):
        return known.get(source_id)

    owners.register_source_owner("progress_claim", sync_resolver if flavour == "sync" else async_resolver)
    assert owners.registered_source_kinds() == ("progress_claim",)

    async def belongs(source_id: uuid.UUID, project_id: uuid.UUID, kind: str = "progress_claim") -> bool:
        return await owners.source_belongs_to_project(
            None, source_kind=kind, source_id=source_id, project_id=project_id
        )

    assert await belongs(document, mine)
    assert not await belongs(document, theirs)
    assert not await belongs(unknown, mine)
    # Registering one kind says nothing about another.
    assert not await belongs(document, mine, "invoice")


@pytest.mark.asyncio
async def test_an_owner_answering_with_text_is_read_as_the_same_project(owners) -> None:
    mine, document = uuid.uuid4(), uuid.uuid4()
    owners.register_source_owner("invoice", lambda _session, _source_id: str(mine))
    assert await owners.resolve_source_project(None, "invoice", document) == mine
    assert await owners.source_belongs_to_project(None, source_kind="invoice", source_id=document, project_id=mine)


@pytest.mark.asyncio
async def test_registering_again_replaces_and_unregistering_closes(owners) -> None:
    first, second, document = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owners.register_source_owner("invoice", lambda _session, _source_id: first)
    owners.register_source_owner("invoice", lambda _session, _source_id: second)
    assert await owners.resolve_source_project(None, "invoice", document) == second
    owners.unregister_source_owner("invoice")
    owners.unregister_source_owner("invoice")
    assert not await owners.source_belongs_to_project(
        None, source_kind="invoice", source_id=document, project_id=second
    )


# ── A contract's certificate settings ────────────────────────────────────────


def test_a_contract_that_says_nothing_about_the_certificate_is_accepted() -> None:
    for country in ("TR", "DE", None):
        hakedis_document.check_terms(country, None)
        hakedis_document.check_terms(country, {})
        hakedis_document.check_terms(country, {"payment_terms_days": 30})


def test_the_certificate_exists_for_the_country_that_has_a_standard_and_on_request() -> None:
    assert hakedis_document.hakedis_available("TR", None)
    assert hakedis_document.hakedis_available("TR", {})
    assert not hakedis_document.hakedis_available("DE", {})
    assert not hakedis_document.hakedis_available(None, None)
    assert hakedis_document.hakedis_available("DE", {"hakedis": {"preset": "TR"}})


@pytest.mark.parametrize(
    "entry",
    [
        "yes",
        {"preset": "no-such-preset"},
        {"remove": ["no_such_line"]},
        {"retention": {"pct": "-1"}},
        {"no_such_setting": 1},
    ],
)
def test_settings_that_cannot_be_used_are_refused_when_the_contract_is_saved(entry) -> None:
    with pytest.raises(HTTPException) as refused:
        hakedis_document.check_terms("TR", {"hakedis": entry})
    assert refused.value.status_code == 400
    assert refused.value.detail["error"] == "invalid_contract_terms"
    assert refused.value.detail["field"] == "terms.hakedis"
    assert refused.value.detail["message"]


def test_usable_settings_are_accepted() -> None:
    hakedis_document.check_terms("TR", {"hakedis": {"retention": {"pct": "5"}, "advance_amount": "1000.00"}})
