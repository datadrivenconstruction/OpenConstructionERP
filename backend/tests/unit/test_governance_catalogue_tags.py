"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Catalogue tags: a document type says what it hosts, a phase says what it enables.

The expectations below are written by hand from the source models, not derived
from ``spine_keys`` or from the JSON, so a catalogue that loses or misplaces a
tag goes red here.
"""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.project_governance import catalogue as cat
from app.modules.project_governance import catalogue_kinds as kinds
from app.modules.project_governance import catalogue_store, public

SUBJECTS = (
    "delivery_model",
    "permits",
    "plant",
    "procurement",
    "design",
    "stakeholders",
    "organisation",
    "quality",
    "staffing",
    "engineering_brief",
    "site_logistics",
    "commitment_release",
    "hse",
)

# catalogue -> capability -> the phases a person who knows the model would name.
ENABLING_PHASES: dict[str, dict[str, tuple[str, ...]]] = {
    "neutral": {
        "procurement": ("tender",),
        "construction_start": ("construction",),
        "handover": ("handover",),
        "operation": ("operation",),
    },
    # Two phases only, and one gate between them. Awards wait for that gate, so it is
    # execution that enables procurement: the gate out of development is the one that
    # releases it. A package that has to be ordered earlier is released by a commitment.
    "elf_module_framework": {
        "procurement": ("execution",),
        "construction_start": ("execution",),
        "handover": ("execution",),
        "operation": (),
    },
    "aho_heft9": {
        "procurement": ("stufe3",),
        "construction_start": ("stufe4",),
        "handover": ("stufe5",),
        "operation": (),
    },
    # LPH 8 covers construction supervision up to acceptance, so it enables both.
    "hoai_lph": {
        "procurement": ("lph6",),
        "construction_start": ("lph8",),
        "handover": ("lph8",),
        "operation": ("lph9",),
    },
    "riba_2020": {
        "procurement": ("stage4",),
        "construction_start": ("stage5",),
        "handover": ("stage6",),
        "operation": ("stage7",),
    },
    # B101 ends with the construction phase; closeout and handover happen inside it.
    "aia_b101": {
        "procurement": ("procurement",),
        "construction_start": ("construction",),
        "handover": ("construction",),
        "operation": (),
    },
}

# Hosts that must not drift: (catalogue, subject) -> (area, document type).
PINNED_HOSTS: dict[tuple[str, str], tuple[str, str]] = {
    ("neutral", "design"): ("scope", "scope_statement"),
    ("neutral", "permits"): ("scope", "approval_conditions_register"),
    ("hoai_lph", "design"): ("scope", "objektbeschreibung"),
    ("hoai_lph", "permits"): ("scope", "genehmigungsunterlagen"),
    ("hoai_lph", "delivery_model"): ("procurement", "procurement_strategy"),
    ("riba_2020", "design"): ("scope", "scope_statement"),
    ("aia_b101", "quality"): ("quality", "quality_management_plan"),
    ("aho_heft9", "design"): ("b", "planungsvorgaben"),
    ("aho_heft9", "organisation"): ("a", "projekthandbuch"),
    ("elf_module_framework", "design"): ("m07_design_management", "m07_design_management_frame"),
    ("elf_module_framework", "plant"): ("m04_equipment", "m04_equipment_frame"),
    ("elf_module_framework", "staffing"): ("m05_personnel", "m05_personnel_frame"),
    ("elf_module_framework", "engineering_brief"): ("m03_engineering_scheduling", "m03_engineering_scheduling_frame"),
    ("elf_module_framework", "site_logistics"): ("m06_logistics", "m06_logistics_frame"),
    ("elf_module_framework", "hse"): ("m11_hse", "m11_hse_frame"),
    ("elf_module_framework", "procurement"): ("m08_procurement", "m08_procurement_frame"),
    ("elf_module_framework", "quality"): ("m10_quality", "m10_quality_frame"),
    ("elf_module_framework", "commitment_release"): ("m09_commercial", "m09_commercial_frame"),
    ("elf_module_framework", "delivery_model"): ("m02_contract_management", "m02_contract_management_frame"),
    # The source framework keeps the permit roadmap with contract management, not with design.
    ("elf_module_framework", "permits"): ("m02_contract_management", "m02_contract_management_frame"),
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cat.clear_catalogue_cache()
    yield
    cat.clear_catalogue_cache()


def test_the_vocabulary_is_the_agreed_one() -> None:
    assert kinds.host_subjects() >= set(SUBJECTS)
    assert kinds.phase_capabilities() >= {"construction_start", "handover", "operation", "procurement"}


def test_the_expectation_table_covers_every_shipped_catalogue() -> None:
    assert set(ENABLING_PHASES) == set(cat.CATALOGUE_IDS)


@pytest.mark.parametrize("cid", cat.CATALOGUE_IDS)
@pytest.mark.parametrize("capability", ["procurement", "construction_start", "handover", "operation"])
def test_phases_enabling_matches_the_source_model(cid: str, capability: str) -> None:
    catalogue = cat.get_catalogue(cid)
    assert public.phases_enabling_in(catalogue, capability) == ENABLING_PHASES[cid][capability]


@pytest.mark.parametrize("cid", cat.CATALOGUE_IDS)
@pytest.mark.parametrize("subject", SUBJECTS)
def test_every_shipped_catalogue_hosts_every_subject_exactly_once(cid: str, subject: str) -> None:
    catalogue = cat.get_catalogue(cid)
    hosting = [d for d in catalogue.document_types if subject in d.hosts]
    assert len(hosting) == 1, f"{cid} hosts {subject!r} in {[d.code for d in hosting]}"
    host = public.host_in(catalogue, subject)
    assert host == public.Host(area_code=hosting[0].area, doc_type=hosting[0].code)
    assert host.area_code in {a.code for a in catalogue.areas}


@pytest.mark.parametrize(("key", "expected"), sorted(PINNED_HOSTS.items()))
def test_named_hosts(key: tuple[str, str], expected: tuple[str, str]) -> None:
    cid, subject = key
    host = public.host_in(cat.get_catalogue(cid), subject)
    assert (host.area_code, host.doc_type) == expected


def test_the_delivery_form_is_not_hosted_by_the_bill_of_quantities() -> None:
    assert public.host_in(cat.get_catalogue("hoai_lph"), "delivery_model").doc_type != "leistungsverzeichnisse"


@pytest.mark.parametrize("cid", ["hoai_lph", "riba_2020", "aia_b101", "aho_heft9"])
def test_document_types_added_for_hosting_are_required_only_where_the_wiring_says(cid: str) -> None:
    """A host added where the source model names none is required at one gate, the one written down below.

    It used to ask nothing of any gate, which left the hosted module waiting
    for a document that could never become binding.
    """
    catalogue = cat.get_catalogue(cid)
    for doc in catalogue.document_types:
        if doc.hosts and doc.source_ref is None and doc.name_key.startswith("governance.catalogue.neutral."):
            assert doc.required_at_gates == (WIRED_GATES[(cid, doc.code)],), doc.code
    if cid == "aho_heft9":
        assert catalogue.host_of("design").required_at_gates == (WIRED_GATES[(cid, "planungsvorgaben")],)


def test_an_untagged_catalogue_answers_none_and_empty() -> None:
    body = _body()
    for doc in body["document_types"]:
        doc.pop("hosts", None)
    for phase in body["phases"]:
        phase.pop("enables", None)
    catalogue = cat.catalogue_from_body(body, source="tenant", origin="test")
    assert public.host_in(catalogue, "design") is None
    assert public.phases_enabling_in(catalogue, "handover") == ()


def _body() -> dict[str, Any]:
    body = cat.get_catalogue("neutral").model_dump(mode="json")
    body["areas_from"] = None
    return body


def _errors(body: dict[str, Any]) -> list[str]:
    with pytest.raises(cat.InvalidCatalogueError) as exc:
        cat.catalogue_from_body(body, source="tenant", origin="test")
    return [e.split(":")[0] for e in exc.value.errors]


def _doc(body: dict[str, Any], code: str) -> dict[str, Any]:
    return next(d for d in body["document_types"] if d["code"] == code)


def test_the_unbroken_body_is_valid() -> None:
    cat.catalogue_from_body(_body(), source="tenant", origin="test")


def test_an_unknown_subject_is_refused() -> None:
    body = _body()
    _doc(body, "risk_register")["hosts"] = ["no_such_subject"]
    assert _errors(body) == ["document_hosts_unknown"]


def test_a_subject_listed_twice_on_one_document_is_refused() -> None:
    body = _body()
    _doc(body, "scope_statement")["hosts"] = ["design", "design"]
    assert _errors(body) == ["document_hosts_duplicate"]


def test_a_subject_hosted_by_two_documents_is_refused() -> None:
    body = _body()
    _doc(body, "risk_register")["hosts"] = ["design"]
    assert _errors(body) == ["subject_hosted_twice"]


def test_an_unknown_capability_is_refused() -> None:
    body = _body()
    body["phases"][0]["enables"] = ["lift_off"]
    assert _errors(body) == ["phase_enables_unknown"]


def test_a_capability_listed_twice_on_one_phase_is_refused() -> None:
    body = _body()
    body["phases"][8]["enables"] = ["construction_start", "construction_start"]
    assert _errors(body) == ["phase_enables_duplicate"]


def test_two_phases_may_enable_the_same_thing() -> None:
    body = _body()
    body["phases"][7]["enables"] = ["procurement"]
    catalogue = cat.catalogue_from_body(body, source="tenant", origin="test")
    assert public.phases_enabling_in(catalogue, "procurement") == ("tender", "award")


def test_a_module_registers_its_own_tags() -> None:
    before_subjects, before_caps = set(kinds._HOST_SUBJECTS), set(kinds._PHASE_CAPABILITIES)
    try:
        kinds.register_host_subject("test_subject_x")
        kinds.register_phase_capability("test_capability_x")
        body = copy.deepcopy(_body())
        _doc(body, "risk_register")["hosts"] = ["test_subject_x"]
        body["phases"][0]["enables"] = ["test_capability_x"]
        catalogue = cat.catalogue_from_body(body, source="tenant", origin="test")
        assert public.host_in(catalogue, "test_subject_x") == public.Host("risk", "risk_register")
        with pytest.raises(ValueError, match="must match"):
            kinds.register_host_subject("Not A Tag")
    finally:
        kinds._HOST_SUBJECTS.clear()
        kinds._HOST_SUBJECTS.update(before_subjects)
        kinds._PHASE_CAPABILITIES.clear()
        kinds._PHASE_CAPABILITIES.update(before_caps)


def test_the_resolver_fails_closed_for_the_tenant_source() -> None:
    """The tenant check is on by default; only a stored pin may skip it."""
    params = inspect.signature(catalogue_store.resolve_catalogue).parameters
    assert params["tenant_id"].default is None and params["tenant_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["from_pin"].default is False and params["from_pin"].kind is inspect.Parameter.KEYWORD_ONLY


# ── a hosting document must be able to become binding ──
#
# A frame document becomes binding at a gate that lists it. A module whose
# subject it hosts waits for exactly that, so a hosting document no gate
# requires leaves that module's concept in review for the whole project.

# Platform wiring, NOT a claim about the source models: where a source names no gate for a
# document that hosts one of our subjects, the document is required at the gate into the
# phase that needs the subject. Subjects a tender is built on need to be binding before
# procurement starts; subjects of the site need to be binding before construction starts.
NEEDED_BEFORE: dict[str, str] = {
    "organisation": "procurement",
    "stakeholders": "procurement",
    "delivery_model": "procurement",
    "procurement": "procurement",
    "design": "procurement",
    "permits": "construction_start",
    "quality": "construction_start",
    "plant": "construction_start",
    "staffing": "construction_start",
    "engineering_brief": "procurement",
    "site_logistics": "construction_start",
    "hse": "construction_start",
    "commitment_release": "construction_start",
    "economics": "procurement",
}

# The requirements this platform added, written out by hand. A document that hosts several
# subjects is required at the earliest gate any of them needs.
WIRED_GATES: dict[tuple[str, str], str] = {
    ("aho_heft9", "planungsvorgaben"): "stufe2_to_stufe3",
    ("hoai_lph", "procurement_strategy"): "lph5_to_lph6",
    ("hoai_lph", "stakeholder_register"): "lph5_to_lph6",
    ("hoai_lph", "project_handbook"): "lph5_to_lph6",
    ("hoai_lph", "quality_management_plan"): "lph7_to_lph8",
    ("hoai_lph", "resource_plan"): "lph7_to_lph8",
    ("riba_2020", "procurement_strategy"): "stage3_to_stage4",
    ("riba_2020", "scope_statement"): "stage3_to_stage4",
    ("riba_2020", "stakeholder_register"): "stage3_to_stage4",
    ("riba_2020", "project_handbook"): "stage3_to_stage4",
    ("riba_2020", "approval_conditions_register"): "stage4_to_stage5",
    ("riba_2020", "quality_management_plan"): "stage4_to_stage5",
    ("riba_2020", "resource_plan"): "stage4_to_stage5",
    ("riba_2020", "budget_baseline"): "stage4_to_stage5",
    ("aia_b101", "procurement_strategy"): "construction_documents_to_procurement",
    ("aia_b101", "scope_statement"): "construction_documents_to_procurement",
    ("aia_b101", "stakeholder_register"): "construction_documents_to_procurement",
    ("aia_b101", "project_handbook"): "construction_documents_to_procurement",
    ("aia_b101", "approval_conditions_register"): "procurement_to_construction",
    ("aia_b101", "quality_management_plan"): "procurement_to_construction",
    ("aia_b101", "resource_plan"): "procurement_to_construction",
    ("aia_b101", "budget_baseline"): "procurement_to_construction",
}


@pytest.mark.parametrize("cid", cat.CATALOGUE_IDS)
def test_every_hosting_document_is_required_at_a_gate(cid: str) -> None:
    stuck = [d.code for d in cat.get_catalogue(cid).document_types if d.hosts and not d.required_at_gates]
    assert stuck == []


@pytest.mark.parametrize(("key", "gate_code"), sorted(WIRED_GATES.items()))
def test_the_wired_requirement_sits_at_the_named_gate(key: tuple[str, str], gate_code: str) -> None:
    cid, doc_code = key
    doc = next(d for d in cat.get_catalogue(cid).document_types if d.code == doc_code)
    assert tuple(doc.required_at_gates) == (gate_code,)


@pytest.mark.parametrize("cid", cat.CATALOGUE_IDS)
def test_a_hosting_document_binds_before_its_subject_is_needed(cid: str) -> None:
    """No later than the gate into the phase that needs the subject, wherever a gate leads into it."""
    catalogue = cat.get_catalogue(cid)
    order = {g.code: i for i, g in enumerate(catalogue.gates)}
    late: list[tuple[str, str]] = []
    for doc in catalogue.document_types:
        for subject in doc.hosts:
            phases = catalogue.phases_enabling(NEEDED_BEFORE[subject])
            into = [g.code for g in catalogue.gates if phases and g.to_phase == phases[0]]
            if not into:
                # The model starts in that phase: nothing can be bound before it, the first gate has to do.
                continue
            if min(order[g] for g in doc.required_at_gates) > order[into[0]]:
                late.append((doc.code, subject))
    assert late == []


def test_a_hosting_document_no_gate_requires_is_refused() -> None:
    body = _body()
    _doc(body, "scope_statement")["required_at_gates"] = []
    assert _errors(body) == ["hosting_document_never_required"]


def test_a_document_that_hosts_nothing_may_stay_unrequired() -> None:
    body = _body()
    doc = _doc(body, "risk_register")
    assert not doc.get("hosts")
    doc["required_at_gates"] = []
    cat.catalogue_from_body(body, source="tenant", origin="test")


def test_the_framework_catalogue_names_its_source_without_quoting_a_publication() -> None:
    path = Path(cat.__file__).parent / "catalogues" / "elf_module_framework.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    title = body["source_title"]
    # Verified with no URL, so the validator needs a title, and a neutral one.
    assert title == "Source framework"


def test_the_demo_seed_signs_in_as_the_platform_demo_accounts() -> None:
    from app.core import demo_cast
    from app.core.demo_accounts import DEMO_ACCOUNT_EMAILS, SHOWCASE_OWNER_EMAIL
    from app.modules.project_governance import seed

    assert seed._OWNER_EMAIL == SHOWCASE_OWNER_EMAIL
    # The owner and the two parts of the cast are the three demo logins where they exist.
    assert {seed._OWNER_EMAIL} | set(demo_cast.CAST.values()) == set(DEMO_ACCOUNT_EMAILS)
    assert sorted(demo_cast.CAST) == ["cost", "decider"]
    # ``cost`` joins first: a seeder that takes "the first member who is not the owner" gets it.
    assert demo_cast.JOIN_ORDER == ("cost", "decider")
    source = inspect.getsource(seed)
    assert "demo@" not in source
    assert "manager@" not in source and "estimator@" not in source


def test_the_demo_cast_cannot_create_a_user() -> None:
    """The cast is the demo logins an installation has. A demo is not worth a new account."""
    import ast

    from app.core import demo_cast

    tree = ast.parse(inspect.getsource(demo_cast))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "User" in imported, "the module no longer reads users; this test reads nothing"
    # Read through a select, never built and never handed to the session.
    assert "User" not in called
    assert not called & {"add", "add_all", "merge", "hash_password", "create_user", "register"}
    assert not imported & {"hash_password", "UserRepository", "UserService"}
    assert not {"remove_demo_cast", "CAST_TAG", "CastPart"} & set(vars(demo_cast))


def test_the_cast_left_the_users_module_and_the_project_purge_alone() -> None:
    from app.core import demo_accounts, demo_cast

    assert not hasattr(demo_accounts, "DEMO_CAST_EMAILS")
    modules = Path(demo_cast.__file__).parents[1] / "modules"
    readers = [*sorted((modules / "users").rglob("*.py")), modules / "projects" / "service.py"]
    assert len(readers) > 3
    naming = [str(path.relative_to(modules)) for path in readers if "demo_cast" in path.read_text(encoding="utf-8")]
    assert naming == []


def test_the_one_gate_of_the_eleven_area_model_is_the_gate_that_releases_procurement() -> None:
    """A module asks for the gates whose target phase enables procurement; an empty answer means never."""
    catalogue = cat.get_catalogue("elf_module_framework")
    enabling = set(public.phases_enabling_in(catalogue, "procurement"))
    releasing = [g.code for g in catalogue.gates if g.to_phase in enabling]
    assert releasing == ["development_to_execution"]
    first = min(catalogue.phases, key=lambda p: p.order)
    assert first.code not in enabling
