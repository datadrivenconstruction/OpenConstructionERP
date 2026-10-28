"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ``pack`` catalogue source: what the active pack ships resolves like any other catalogue.

Pack discovery is replaced by three fakes, so no pack has to be installed.
The bodies are the shipped neutral catalogue under another id: a pack file is
the same JSON a shipped catalogue is.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.partner_pack import discovery
from app.modules.project_governance import catalogue as cat
from app.modules.project_governance import catalogue_packs as packs
from app.modules.project_governance import catalogue_store, evaluator, public
from app.modules.project_governance.catalogue_store import CatalogueStore, resolve_catalogue
from app.modules.project_governance.errors import GovernanceError
from app.modules.project_governance.schemas import ModelChange, ModelSet


def _body(catalogue_id: str, version: int = 1) -> bytes:
    raw = json.loads((cat.CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))
    raw["id"] = catalogue_id
    raw["version"] = version
    return json.dumps(raw).encode("utf-8")


def _entry(catalogue_id: str, version: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "phase_model",
        "id": catalogue_id,
        "version": version,
        "path": f"catalogues/phase_model/{catalogue_id}_v{version}.json",
        **extra,
    }


def _pack(slug: str, *entries: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(slug=slug, metadata={"catalogues": list(entries)})


class Packs:
    """The installation's packs for one test: which exist, which is active, what files they carry."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.active: SimpleNamespace | None = None
        self.all: list[SimpleNamespace] = []
        self.files: dict[tuple[str, str], bytes] = {}
        monkeypatch.setattr(discovery, "get_active_pack", lambda: self.active)
        monkeypatch.setattr(discovery, "discover_packs", lambda: list(self.all))
        monkeypatch.setattr(discovery, "read_pack_file", lambda slug, rel: self.files.get((slug, rel)))

    def install(self, pack: SimpleNamespace, *, active: bool = False, with_files: bool = True) -> SimpleNamespace:
        self.all.append(pack)
        if active:
            self.active = pack
        if with_files:
            for entry in pack.metadata["catalogues"]:
                if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                    self.files[(pack.slug, entry["path"])] = _body(entry["id"], entry["version"])
        return pack


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> Packs:
    packs.clear_pack_catalogue_cache()
    yield Packs(monkeypatch)
    packs.clear_pack_catalogue_cache()


def _resolve(catalogue_id: str, version: int | None = None, **kwargs: Any) -> Any:
    return asyncio.run(resolve_catalogue(None, "pack", catalogue_id, version, **kwargs))


def _refusal(catalogue_id: str, version: int | None = None, **kwargs: Any) -> GovernanceError:
    with pytest.raises(GovernanceError) as caught:
        _resolve(catalogue_id, version, **kwargs)
    return caught.value


# --------------------------------------------------------------------- the declaration


def test_a_manifest_declares_its_catalogues(installed: Packs) -> None:
    pack = _pack("acme", _entry("acme_model", 2, default_for_new_projects=True, default_for_countries=["de", " at "]))
    (ref,) = packs.declared_catalogues(pack)
    assert ref == packs.PackCatalogue(
        slug="acme",
        kind="phase_model",
        id="acme_model",
        version=2,
        path="catalogues/phase_model/acme_model_v2.json",
        default_for_new_projects=True,
        default_for_countries=("DE", "AT"),
    )


@pytest.mark.parametrize(
    "entry",
    [
        "not an object",
        {"kind": "phase_model", "id": "x", "version": 1},
        {"kind": "phase_model", "id": "x", "version": "1", "path": "x.json"},
        {"kind": "phase_model", "id": "x", "version": 0, "path": "x.json"},
        {"kind": "phase_model", "id": "x", "version": True, "path": "x.json"},
        {"kind": "phase_model", "id": " ", "version": 1, "path": "x.json"},
        {"kind": "phase_model", "id": "x", "version": 1, "path": "x.json", "default_for_countries": "DE"},
    ],
)
def test_a_malformed_entry_is_left_out_and_the_good_one_stays(installed: Packs, entry: Any) -> None:
    pack = _pack("acme", entry, _entry("acme_model"))
    assert [c.id for c in packs.declared_catalogues(pack)] == ["acme_model"]


def test_a_manifest_without_catalogues_declares_none(installed: Packs) -> None:
    assert packs.declared_catalogues(SimpleNamespace(slug="acme", metadata={})) == ()
    assert packs.declared_catalogues(SimpleNamespace(slug="acme", metadata=None)) == ()
    assert packs.declared_catalogues(SimpleNamespace(slug="acme", metadata={"catalogues": {"id": "x"}})) == ()


# --------------------------------------------------------------------- G-01: the resolver


def test_pack_is_a_source_the_api_accepts(installed: Packs) -> None:
    assert "pack" in catalogue_store.SOURCES
    assert ModelSet(catalogue_source="pack", catalogue_id="acme_model").catalogue_source == "pack"
    assert ModelChange(catalogue_source="pack", catalogue_id="acme_model", mapping={}).catalogue_source == "pack"


def test_the_active_packs_catalogue_resolves_through_the_kind(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")), active=True)
    resolved = _resolve("acme_model")
    assert isinstance(resolved, cat.Catalogue)
    assert (resolved.id, resolved.version) == ("acme_model", 1)
    # The same body the shipped neutral catalogue is, so the tags came through the same validator.
    assert resolved.host_of("permits") == cat.get_catalogue("neutral").host_of("permits")


def test_without_a_version_the_highest_declared_one_resolves(installed: Packs) -> None:
    installed.install(
        _pack("acme", _entry("acme_model", 1), _entry("acme_model", 3), _entry("acme_model", 2)), active=True
    )
    assert _resolve("acme_model").version == 3
    assert _resolve("acme_model", 2).version == 2
    assert _refusal("acme_model", 9).code == "unknown_catalogue"


def test_an_unknown_kind_or_id_is_not_found(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")), active=True)
    refused = _refusal("something_else")
    assert (refused.code, refused.status_code) == ("unknown_catalogue", 404)
    # The shipped id does not leak into the pack source, nor the pack id into the shipped one.
    assert _refusal("neutral").code == "unknown_catalogue"
    with pytest.raises(GovernanceError) as caught:
        asyncio.run(resolve_catalogue(None, "shipped", "acme_model", None))
    assert caught.value.code == "unknown_catalogue"


def test_no_active_pack_means_nothing_to_pin(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")))
    assert _refusal("acme_model").code == "unknown_catalogue"


def test_a_request_id_resolves_only_in_the_active_pack(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")), active=True)
    installed.install(_pack("other", _entry("other_model")))
    assert _refusal("other_model").code == "unknown_catalogue"
    # A tenant id changes nothing: a pack catalogue belongs to the installation.
    assert _refusal("other_model", tenant_id="t1").code == "unknown_catalogue"
    assert _resolve("acme_model", tenant_id="t1").id == "acme_model"


def test_a_stored_pin_keeps_resolving_after_another_pack_became_active(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")), active=True)
    installed.install(_pack("other", _entry("other_model")))
    assert _resolve("other_model", 1, from_pin=True).id == "other_model"
    # A pin on a pack that is no longer installed at all cannot resolve.
    assert _refusal("gone_model", 1, from_pin=True).code == "unknown_catalogue"


def test_the_active_pack_wins_when_two_packs_declare_one_id(installed: Packs) -> None:
    installed.install(_pack("other", _entry("shared_model", 1)))
    installed.install(_pack("acme", _entry("shared_model", 1)), active=True)
    ref = packs.find_pack_catalogue("phase_model", "shared_model", 1, active_only=False)
    assert ref is not None and ref.slug == "acme"


def test_a_declared_file_that_is_missing_is_named(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")), active=True, with_files=False)
    refused = _refusal("acme_model")
    assert (refused.code, refused.status_code) == ("pack_catalogue_invalid", 422)


def test_a_body_that_carries_another_id_or_version_is_refused(installed: Packs) -> None:
    pack = installed.install(_pack("acme", _entry("acme_model"), _entry("second_model", 2)), active=True)
    first, second = (e["path"] for e in pack.metadata["catalogues"])
    installed.files[("acme", first)] = _body("another_id", 1)
    installed.files[("acme", second)] = _body("second_model", 1)
    assert _refusal("acme_model").code == "pack_catalogue_invalid"
    refused = _refusal("second_model")
    assert refused.code == "pack_catalogue_invalid"
    assert "declaration_mismatch" in str(refused)


def test_a_pack_cannot_bring_a_catalogue_the_validator_refuses(installed: Packs) -> None:
    pack = installed.install(_pack("acme", _entry("acme_model"), _entry("junk_model")), active=True)
    first, second = (e["path"] for e in pack.metadata["catalogues"])
    raw = json.loads(_body("acme_model"))
    # A subject outside the vocabulary: the same refusal a tenant catalogue gets on publish.
    raw["document_types"][0]["hosts"] = ["not_a_subject"]
    installed.files[("acme", first)] = json.dumps(raw).encode("utf-8")
    installed.files[("acme", second)] = b"{ not json"
    refused = _refusal("acme_model")
    assert refused.code == "pack_catalogue_invalid"
    assert "document_hosts_unknown" in str(refused)
    assert _refusal("junk_model").code == "pack_catalogue_invalid"


def test_a_replaced_pack_file_is_read_again(installed: Packs) -> None:
    pack = installed.install(_pack("acme", _entry("acme_model")), active=True)
    path = pack.metadata["catalogues"][0]["path"]
    assert _resolve("acme_model").id == "acme_model"
    installed.files[("acme", path)] = _body("renamed", 1)
    assert _refusal("acme_model").code == "pack_catalogue_invalid"


def test_the_new_code_is_registered() -> None:
    assert "pack_catalogue_invalid" in evaluator.ALL_CODES


# --------------------------------------------------------------------- pinning and listing


def test_only_the_active_packs_catalogue_is_pinnable(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model", 2)), active=True)
    installed.install(_pack("other", _entry("other_model")))
    store = CatalogueStore(None)
    assert asyncio.run(store.assert_pinnable(None, "pack", "acme_model", None)) == 2
    with pytest.raises(GovernanceError) as caught:
        asyncio.run(store.assert_pinnable("t1", "pack", "other_model", None))
    assert caught.value.code == "unknown_catalogue"


def test_the_list_offers_the_active_packs_catalogues(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model", 1), _entry("acme_model", 2), _entry("broken")), active=True)
    installed.install(_pack("other", _entry("other_model")))
    installed.files[("acme", "catalogues/phase_model/broken_v1.json")] = b"{ not json"
    items = asyncio.run(CatalogueStore(None).list_available(None))
    from_packs = [i for i in items if i["source"] == "pack"]
    assert [(i["id"], i["latest_version"], i["pack"]) for i in from_packs] == [("acme_model", 2, "acme")]
    assert from_packs[0]["phases"] and from_packs[0]["state"] == "published"
    # The shipped ones are still there.
    assert {"neutral", "hoai_lph"} <= {i["id"] for i in items if i["source"] == "shipped"}


def test_without_a_pack_the_list_is_the_shipped_one(installed: Packs) -> None:
    items = asyncio.run(CatalogueStore(None).list_available(None))
    assert items and {i["source"] for i in items} == {"shipped"}


# --------------------------------------------------------------------- G-02: the default


def test_a_pack_names_the_default_for_new_projects(installed: Packs) -> None:
    installed.install(
        _pack(
            "acme",
            _entry("acme_general", 3, default_for_new_projects=True),
            _entry("acme_german", 1, default_for_countries=["DE"]),
            _entry("acme_plain", 1),
        ),
        active=True,
    )
    assert packs.pack_default_pin("phase_model") == packs.CataloguePin("pack", "acme_general", 3)
    assert packs.pack_default_pin("phase_model", "FR") == packs.CataloguePin("pack", "acme_general", 3)
    # The catalogue named for the country wins over the one named for every country.
    assert packs.pack_default_pin("phase_model", " de ") == packs.CataloguePin("pack", "acme_german", 1)
    assert packs.pack_default_pin("delivery_forms") is None


def test_a_pack_without_an_opinion_or_an_inactive_pack_names_nothing(installed: Packs) -> None:
    installed.install(_pack("other", _entry("other_model", default_for_new_projects=True)))
    assert packs.pack_default_pin("phase_model") is None
    installed.install(_pack("acme", _entry("acme_plain")), active=True)
    assert packs.pack_default_pin("phase_model", "DE") is None


def test_the_default_pin_falls_back_to_the_shipped_country_default(installed: Packs) -> None:
    assert public.default_catalogue_pin("phase_model", "DE") == packs.CataloguePin(
        "shipped",
        cat.default_catalogue_id_for_country("DE"),
        cat.get_catalogue(cat.default_catalogue_id_for_country("DE")).version,
    )
    installed.install(_pack("acme", _entry("acme_model", 2, default_for_new_projects=True)), active=True)
    assert public.default_catalogue_pin("phase_model", "DE") == packs.CataloguePin("pack", "acme_model", 2)


def test_a_kind_nobody_registered_has_no_default(installed: Packs) -> None:
    assert public.default_catalogue_pin("kind_of_no_module", "DE") is None


def test_a_default_whose_file_is_broken_is_not_the_default(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model", default_for_new_projects=True)), active=True, with_files=False)
    pin = public.default_catalogue_pin("phase_model", None)
    assert pin is not None and pin.source == "shipped"


def test_the_list_marks_exactly_one_default(installed: Packs) -> None:
    store = CatalogueStore(None)
    shipped_default = cat.default_catalogue_id_for_country("DE")
    items = asyncio.run(store.list_available(None, country_code="DE"))
    assert [(i["source"], i["id"]) for i in items if i["default"]] == [("shipped", shipped_default)]
    installed.install(_pack("acme", _entry("acme_model", default_for_countries=["DE"])), active=True)
    items = asyncio.run(store.list_available(None, country_code="DE"))
    assert [(i["source"], i["id"]) for i in items if i["default"]] == [("pack", "acme_model")]
    items = asyncio.run(store.list_available(None, country_code="FR"))
    assert [i["source"] for i in items if i["default"]] == ["shipped"]


# --------------------------------------------------------------------- cloning into a tenant catalogue


class _Repo:
    """The two repository calls a clone makes, kept in memory."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    async def list_tenant_catalogues(self, *_a: Any, **_k: Any) -> list[Any]:
        return []

    async def add(self, row: Any) -> Any:
        self.added.append(row)
        return row


def _clone(based_on_id: str, version: int | None = None) -> Any:
    store = CatalogueStore.__new__(CatalogueStore)
    store.session = None
    store.repo = _Repo()
    return asyncio.run(
        store.create(
            "tenant-1",
            code="ours",
            name="Our model",
            based_on_source="pack",
            based_on_id=based_on_id,
            based_on_version=version,
            actor_id=None,
        )
    )


def test_a_company_starts_its_own_catalogue_from_the_packs(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model", 1), _entry("acme_model", 2)), active=True)
    row = _clone("acme_model")
    assert (row.tenant_id, row.code, row.state, row.based_on) == ("tenant-1", "ours", "draft", "pack:acme/acme_model@2")
    assert (row.draft_body["id"], row.draft_body["version"]) == ("ours", 1)
    # The pack's structure came along, and the draft is a catalogue the tenant rules accept.
    draft = cat.catalogue_from_body(row.draft_body, source="tenant", origin="clone")
    source = _resolve("acme_model")
    assert [p.code for p in draft.phases] == [p.code for p in source.phases]
    assert draft.host_of("permits") == source.host_of("permits")
    # The pack is named too: two packs may carry the same catalogue id.
    assert _clone("acme_model", 1).based_on == "pack:acme/acme_model@1"


def test_only_the_active_packs_catalogue_can_be_cloned(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")), active=True)
    installed.install(_pack("other", _entry("other_model")))
    with pytest.raises(GovernanceError) as caught:
        _clone("other_model")
    assert (caught.value.code, caught.value.status_code) == ("unknown_catalogue", 404)


def test_a_broken_pack_file_cannot_be_cloned(installed: Packs) -> None:
    installed.install(_pack("acme", _entry("acme_model")), active=True, with_files=False)
    with pytest.raises(GovernanceError) as caught:
        _clone("acme_model")
    assert caught.value.code == "pack_catalogue_invalid"


# --------------------------------------------------------------------- second review: manifest rules and defaults


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "no_such_kind", "id": "x", "version": 1, "path": "x.json"},
        {"kind": "phase_model", "id": "Bad-Id", "version": 1, "path": "x.json"},
        {"kind": "phase_model", "id": "1starts_with_a_digit", "version": 1, "path": "x.json"},
        {"kind": "phase_model", "id": "x" * 65, "version": 1, "path": "x.json"},
        {"kind": "phase_model", "id": "x", "version": 1, "path": "x.json", "default_for_countries": ["DEU"]},
        {"kind": "phase_model", "id": "x", "version": 1, "path": "x.json", "default_for_countries": ["D1"]},
    ],
)
def test_an_entry_that_breaks_a_manifest_rule_is_left_out(installed: Packs, entry: Any) -> None:
    pack = _pack("acme", entry, _entry("acme_model"))
    assert [c.id for c in packs.declared_catalogues(pack)] == ["acme_model"]


def test_a_repeated_declaration_counts_once(installed: Packs) -> None:
    first = _entry("acme_model", 1)
    again = {**_entry("acme_model", 1), "path": "catalogues/phase_model/another_file.json"}
    declared = packs.declared_catalogues(_pack("acme", first, again, _entry("acme_model", 2)))
    assert [(c.id, c.version, c.path) for c in declared] == [
        ("acme_model", 1, first["path"]),
        ("acme_model", 2, "catalogues/phase_model/acme_model_v2.json"),
    ]


def test_a_default_of_a_kind_nobody_registered_is_no_default(installed: Packs) -> None:
    entry = {"kind": "no_such_kind", "id": "x", "version": 1, "path": "x.json", "default_for_new_projects": True}
    installed.install(_pack("acme", entry), active=True, with_files=False)
    assert public.default_catalogue_pin("no_such_kind", "DE") is None


def test_a_broken_country_default_falls_through_to_the_general_default(installed: Packs) -> None:
    pack = installed.install(
        _pack(
            "acme",
            _entry("acme_german", default_for_countries=["DE"]),
            _entry("acme_general", default_for_new_projects=True),
        ),
        active=True,
    )
    assert public.default_catalogue_pin("phase_model", "DE") == packs.CataloguePin("pack", "acme_german", 1)
    installed.files[("acme", pack.metadata["catalogues"][0]["path"])] = b"{ not json"
    # The pack's own general default comes before the shipped catalogue of the country.
    assert public.default_catalogue_pin("phase_model", "DE") == packs.CataloguePin("pack", "acme_general", 1)
    assert packs.pack_default_candidates("phase_model", "DE") == (
        packs.CataloguePin("pack", "acme_german", 1),
        packs.CataloguePin("pack", "acme_general", 1),
    )


# ── the default of any kind, by the project's country ──

PROBE_KIND = "probe_schedule"


def _probe_body() -> Any:
    from pydantic import create_model

    return create_model("ProbeBody", id=(str, ...), version=(int, ...))


@pytest.fixture
def probe_kind():
    """A kind of another module with shipped files that claim countries, one of them twice."""
    from app.modules.project_governance.catalogue_kinds import (
        CatalogueKind,
        register_catalogue_kind,
        unregister_catalogue_kind,
    )

    def shipped(catalogue_id: str, version: int, *countries: str) -> SimpleNamespace:
        return SimpleNamespace(id=catalogue_id, version=version, jurisdiction_countries=countries)

    files = [
        shipped("neutral", 1),
        shipped("german", 1, "DE"),
        shipped("german", 2, "DE"),
        shipped("alpine_a", 1, "AT", "CH"),
        shipped("alpine_b", 1, "AT"),
        SimpleNamespace(id="bare", version=1),
    ]
    register_catalogue_kind(
        CatalogueKind(
            kind=PROBE_KIND, model=_probe_body(), validator=lambda obj, source: [], list_shipped=lambda: tuple(files)
        )
    )
    yield files
    unregister_catalogue_kind(PROBE_KIND)


def test_a_kind_without_a_pack_opinion_defaults_to_the_one_shipped_catalogue_of_the_country(
    installed: Packs, probe_kind
) -> None:
    # The newest version of the one catalogue that claims the country.
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("shipped", "german", 2)
    assert public.default_catalogue_pin(PROBE_KIND, " de ") == packs.CataloguePin("shipped", "german", 2)
    assert public.default_catalogue_pin(PROBE_KIND, "CH") == packs.CataloguePin("shipped", "alpine_a", 1)


def test_a_country_nobody_claims_or_two_claim_or_no_country_has_no_default(installed: Packs, probe_kind) -> None:
    """``None`` keeps its meaning: the owning module pins its neutral file."""
    assert public.default_catalogue_pin(PROBE_KIND, "FR") is None
    assert public.default_catalogue_pin(PROBE_KIND, "AT") is None
    assert public.default_catalogue_pin(PROBE_KIND, None) is None
    assert public.default_catalogue_pin(PROBE_KIND, "  ") is None


def test_the_pack_is_asked_before_the_shipped_catalogue_of_the_country(installed: Packs, probe_kind) -> None:
    entry = _entry("acme_schedule", default_for_new_projects=True) | {"kind": PROBE_KIND}
    installed.install(_pack("acme", entry), active=True, with_files=False)
    installed.files[("acme", entry["path"])] = json.dumps({"id": "acme_schedule", "version": 1}).encode("utf-8")
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("pack", "acme_schedule", 1)
    assert public.default_catalogue_pin(PROBE_KIND, "FR") == packs.CataloguePin("pack", "acme_schedule", 1)


def test_a_kind_whose_shipped_files_do_not_load_has_no_default(installed: Packs, probe_kind) -> None:
    from app.modules.project_governance.catalogue import InvalidCatalogueError
    from app.modules.project_governance.catalogue_kinds import CatalogueKind, register_catalogue_kind

    def broken() -> tuple[Any, ...]:
        raise InvalidCatalogueError("probe.json", ["unreadable"])

    register_catalogue_kind(
        CatalogueKind(kind=PROBE_KIND, model=_probe_body(), validator=lambda obj, source: [], list_shipped=broken)
    )
    assert public.default_catalogue_pin(PROBE_KIND, "DE") is None


def test_the_phase_model_keeps_its_own_last_resort(installed: Packs) -> None:
    for country in ("FR", None, ""):
        pin = public.default_catalogue_pin("phase_model", country)
        assert pin == packs.CataloguePin("shipped", "neutral", cat.get_catalogue("neutral").version)


def test_the_staffing_files_resolve_by_country_through_the_port(installed: Packs) -> None:
    """The real files of a module that used to carry this rule itself."""
    staffing = pytest.importorskip("app.modules.staffing.catalogue")
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    staffing.register_kinds()
    shipped = get_catalogue_kind(staffing.STAFFING_MODEL_KIND).shipped()
    german = [c for c in shipped if "DE" in c.jurisdiction_countries]
    assert len(german) == 1
    assert public.default_catalogue_pin(staffing.STAFFING_MODEL_KIND, "DE") == packs.CataloguePin(
        "shipped", german[0].id, german[0].version
    )
    unclaimed = next(code for code in ("FR", "JP", "BR") if not any(code in c.jurisdiction_countries for c in shipped))
    assert public.default_catalogue_pin(staffing.STAFFING_MODEL_KIND, unclaimed) is None


# ── a national regional pack is asked before the shipped catalogue of the country ──


@pytest.fixture
def regional(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The regional pack configurations of the installation, for one test."""
    configs: list[dict[str, Any]] = []

    def packs_for_country(country_code: str | None) -> tuple[dict[str, Any], ...]:
        wanted = (country_code or "").strip().upper()
        return tuple(c for c in configs if wanted and wanted in c.get("countries", ()))

    monkeypatch.setattr(cat.regional_packs, "packs_for_country", packs_for_country)
    return configs


def test_a_regional_pack_never_loses_to_a_shipped_file(installed: Packs, probe_kind, regional) -> None:
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("shipped", "german", 2)
    regional.append({"countries": ["DE", "AT"], PROBE_KIND: {"DE": "alpine_a", "AT": " alpine_b "}})
    # One shipped file claims DE; the national pack names another and wins.
    assert public.default_catalogue_pin(PROBE_KIND, "de") == packs.CataloguePin("shipped", "alpine_a", 1)
    # Two shipped files claim AT, which alone is no answer; the pack settles it.
    assert public.default_catalogue_pin(PROBE_KIND, "AT") == packs.CataloguePin("shipped", "alpine_b", 1)
    # The entry is per country: nothing is said about CH.
    assert public.default_catalogue_pin(PROBE_KIND, "CH") == packs.CataloguePin("shipped", "alpine_a", 1)


def test_a_regional_entry_names_the_newest_version_of_a_shipped_catalogue(
    installed: Packs, probe_kind, regional
) -> None:
    regional.append({"countries": ["FR"], PROBE_KIND: {"FR": "german"}})
    assert public.default_catalogue_pin(PROBE_KIND, "FR") == packs.CataloguePin("shipped", "german", 2)


def test_regional_packs_that_disagree_or_name_nothing_shipped_have_no_say(
    installed: Packs, probe_kind, regional
) -> None:
    regional.append({"countries": ["DE"], PROBE_KIND: {"DE": "no_such_file"}})
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("shipped", "german", 2)
    regional.clear()
    regional.append({"countries": ["DE"], PROBE_KIND: {"DE": "alpine_a"}})
    regional.append({"countries": ["DE"], PROBE_KIND: {"DE": "alpine_b"}})
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("shipped", "german", 2)
    # A state pack under a national one does not vote, and an entry of another kind is not read.
    regional.clear()
    regional.append({"countries": ["DE"], "parent_pack": "dach", PROBE_KIND: {"DE": "alpine_a"}})
    regional.append({"countries": ["DE"], "another_kind": {"DE": "alpine_b"}, PROBE_KIND: "alpine_b"})
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("shipped", "german", 2)


def test_the_active_pack_is_asked_before_a_regional_pack(installed: Packs, probe_kind, regional) -> None:
    regional.append({"countries": ["DE"], PROBE_KIND: {"DE": "alpine_a"}})
    entry = _entry("acme_schedule", default_for_new_projects=True) | {"kind": PROBE_KIND}
    installed.install(_pack("acme", entry), active=True, with_files=False)
    installed.files[("acme", entry["path"])] = json.dumps({"id": "acme_schedule", "version": 1}).encode("utf-8")
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("pack", "acme_schedule", 1)


def test_a_regional_registry_that_fails_costs_only_its_own_say(
    installed: Packs, probe_kind, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(country_code: str | None) -> tuple[dict[str, Any], ...]:
        raise RuntimeError("the registry did not load")

    monkeypatch.setattr(cat.regional_packs, "packs_for_country", broken)
    assert public.default_catalogue_pin(PROBE_KIND, "DE") == packs.CataloguePin("shipped", "german", 2)


def test_the_phase_model_reads_its_regional_entry_through_the_same_reader(installed: Packs, regional) -> None:
    regional.append({"countries": ["FR"], "governance_catalogue": {"FR": "riba_2020"}})
    assert cat.regional_pack_entry("governance_catalogue", "fr") == "riba_2020"
    assert cat.regional_pack_entry("governance_catalogue", "DE") is None
    assert cat.default_catalogue_id_for_country("FR") == "riba_2020"
    assert public.default_catalogue_pin("phase_model", "FR").catalogue_id == "riba_2020"


#: The country rule each module carried itself: module, kind constant, the private function.
#: The port has to give the same catalogue for every country, or the private rule cannot go.
PRIVATE_COUNTRY_RULES = [
    ("commitment_release", "AUTHORITY_SCHEDULE_KIND", "default_schedule_id_for_country"),
    ("delivery_model", "DELIVERY_FORMS_KIND", "default_catalogue_id_for_country"),
    ("design_management", "NUMBERING_KIND", "default_scheme_id_for_country"),
    ("staffing", "STAFFING_MODEL_KIND", "default_catalogue_id_for_country"),
    ("stakeholders", "FRAMEWORK_KIND", "default_framework_id_for_country"),
    ("site_logistics", "SITE_LOGISTICS_KIND", "default_catalogue_id"),
]


@pytest.mark.parametrize(("module", "kind_name", "rule_name"), PRIVATE_COUNTRY_RULES, ids=lambda v: str(v))
def test_the_port_answers_what_the_private_country_rule_of_a_module_answered(
    installed: Packs, module: str, kind_name: str, rule_name: str
) -> None:
    """Asked of the module's real files and of the real regional packs, country by country."""
    from app.core import regional_packs
    from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

    catalogue = pytest.importorskip(f"app.modules.{module}.catalogue")
    rule = getattr(catalogue, rule_name, None)
    if rule is None:
        pytest.skip(f"{module} no longer carries {rule_name}; the port is its only country rule")
    register = getattr(catalogue, "register_kinds", None) or getattr(catalogue, "register_kind", None)
    if register is not None:
        register()
    kind = getattr(catalogue, kind_name)
    neutral = rule(None)
    countries = {"FR", "JP", "ZZ"}
    for item in get_catalogue_kind(kind).shipped():
        countries |= {str(c).upper() for c in getattr(item, "jurisdiction_countries", None) or ()}
    for config in regional_packs.pack_configs():
        countries |= {str(c).upper() for c in config.get("countries") or ()}
    differing = {}
    for country in sorted(countries):
        pin = public.default_catalogue_pin(kind, country)
        answer = pin.catalogue_id if pin is not None else neutral
        if pin is not None and pin.source != "shipped" or answer != rule(country):
            differing[country] = (answer, rule(country))
    assert differing == {}, f"{kind}: port against {module}.{rule_name}: {differing}"
    assert public.default_catalogue_pin(kind, None) is None


def test_a_default_named_for_the_subdivision_comes_before_the_country_one(installed: Packs) -> None:
    installed.install(
        _pack(
            "acme",
            _entry("acme_german", default_for_countries=["DE"]),
            _entry("acme_bavarian", default_for_countries=["DE-BY"]),
        ),
        active=True,
    )
    bavarian, german = packs.CataloguePin("pack", "acme_bavarian", 1), packs.CataloguePin("pack", "acme_german", 1)
    assert public.default_catalogue_pin("phase_model", "DE", "DE-BY") == bavarian
    assert packs.pack_default_candidates("phase_model", "DE", "DE-BY") == (bavarian, german)
    # Another Land of the country, no Land at all, or a subdivision of another country: the country's default.
    assert public.default_catalogue_pin("phase_model", "DE", "DE-BW") == german
    assert public.default_catalogue_pin("phase_model", "DE") == german
    assert packs.pack_default_candidates("phase_model", "AT", "DE-BY") == ()


def test_a_subdivision_code_is_accepted_and_a_malformed_one_refuses_the_entry() -> None:
    ok = packs.declared_catalogues(_pack("acme", _entry("acme_by", default_for_countries=["DE-BY"])))
    assert [c.default_for_countries for c in ok] == [("DE-BY",)]
    assert packs.declared_catalogues(_pack("acme", _entry("acme_x", default_for_countries=["DE-"]))) == ()
