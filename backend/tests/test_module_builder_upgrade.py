# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Upgrading an installed module, without a database.

What counts as adding and what as taking away, the token that only an upgrade
accepts, and the refusals the frontend words itself. The upgrade itself, over
a table holding records, is in ``tests/pg/test_module_builder_v2_hardening.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.module_builder import generator, layout, refresh, review_token, upgrade
from app.modules.module_builder.spec import ModuleSpec

USER = "8f1d4a40-5c55-4c1a-9a3b-5d7c0f2e9a11"
REF = {"name": "ref", "label": "Ref", "type": "text", "required": True}
COUNT = {"name": "count", "label": "Count", "type": "integer"}
KIND = {"name": "kind", "label": "Kind", "type": "select", "options": ["a", "b"]}
CONTRACT = {"name": "contract", "label": "Contract", "type": "link", "target": "contract"}
DUE = {"name": "due_on", "label": "Due", "type": "date"}
STATUS = {"states": [{"code": "open", "label": "Open"}, {"code": "closed", "label": "Closed", "done": True}]}
RULE = {"code": "REF_REQUIRED", "message": "Needs a ref.", "kind": "required", "field": "ref"}


def _spec(fields: list[dict], features: dict | None = None, **over: Any) -> ModuleSpec:
    data: dict[str, Any] = {
        "key": "rv_upgrade",
        "display_name": "Upgrade log",
        "schema_version": 2,
        "entity": {"name": "item", "display_name": "Item", "project_scoped": True, "fields": fields},
        "rules": [RULE],
        "features": features or {},
    }
    entity = over.pop("entity", None)
    if entity:
        data["entity"].update(entity)
    data.update(over)
    return ModuleSpec.model_validate(data)


def _kinds(changes: list[upgrade.Change]) -> set[tuple]:
    return {tuple(c.as_dict().values()) for c in changes}


def _codes(problems: list[upgrade.Problem]) -> set[tuple]:
    return {tuple(p.as_dict().items()) for p in problems}


class TestWhatAnUpgradeAdds:
    def test_fields_links_states_rules_and_functions(self) -> None:
        old = _spec([REF, COUNT, KIND, DUE], {"status": STATUS})
        new = _spec(
            [
                REF,
                {**COUNT, "label": "How many", "required": True},
                {**KIND, "options": ["a", "b", "c"]},
                DUE,
                CONTRACT,
            ],
            {
                "status": {"states": [*STATUS["states"], {"code": "held", "label": "Held"}]},
                "due": {"field": "due_on"},
                "export": True,
                "comments": True,
            },
            rules=[RULE, {"code": "COUNT_POS", "message": "Above zero.", "kind": "positive", "field": "count"}],
            display_name="Upgrade register",
        )

        changes, problems = upgrade.compare(old, new)

        assert problems == []
        assert _kinds(changes) == {
            ("field_changed", "count"),
            ("field_changed", "kind"),
            ("link_added", "contract"),
            ("state_added", "held"),
            ("feature_added", "due"),
            ("feature_added", "export"),
            ("feature_added", "comments"),
            ("rule_added", "COUNT_POS"),
            ("label_changed",),
        }

    def test_a_reworded_rule_and_relabelled_state(self) -> None:
        old = _spec([REF], {"status": STATUS})
        relabelled = {"states": [{"code": "open", "label": "To do"}, STATUS["states"][1]]}
        new = _spec([REF], {"status": relabelled}, rules=[{**RULE, "message": "A ref, please."}])

        changes, problems = upgrade.compare(old, new)

        assert problems == []
        assert _kinds(changes) == {("feature_changed", "status"), ("label_changed",)}

    def test_wording_is_said_once(self) -> None:
        old = _spec([REF])
        new = _spec([REF], rules=[{**RULE, "message": "A ref, please."}], display_name="Upgrade register")

        assert upgrade.compare(old, new) == ([upgrade.Change("label_changed")], [])

    def test_the_same_spec_changes_nothing(self) -> None:
        spec = _spec([REF, COUNT], {"status": STATUS})
        assert upgrade.compare(spec, spec) == ([], [])


class TestWhatAnUpgradeRefuses:
    def test_everything_that_takes_away(self) -> None:
        old = _spec(
            [REF, COUNT, {**KIND, "options": ["a", "b", "c"]}, DUE, CONTRACT],
            {"status": {"states": [*STATUS["states"], {"code": "held", "label": "Held"}]}, "export": True},
            rules=[RULE, {"code": "COUNT_POS", "message": "Above zero.", "kind": "positive", "field": "count"}],
        )
        new = _spec(
            [REF, KIND, DUE, {**CONTRACT, "target": "contact"}],
            {"status": STATUS},
            rules=[{**RULE, "field": "kind"}],
        )

        _, problems = upgrade.compare(old, new)

        assert _codes(problems) == {
            (("code", "field_removed"), ("field", "count"), ("label", "Count")),
            (("code", "options_removed"), ("field", "kind"), ("label", "Kind")),
            (("code", "field_retyped"), ("field", "contract"), ("label", "Contract")),
            (("code", "state_removed"), ("state", "held")),
            (("code", "feature_removed"), ("feature", "export")),
            (("code", "rule_removed"), ("rule", "COUNT_POS")),
            (("code", "rule_changed"), ("rule", "REF_REQUIRED")),
        }

    def test_a_renamed_record_type_and_scope(self) -> None:
        old = _spec([REF])
        assert _codes(upgrade.compare(old, _spec([REF], entity={"name": "thing"}))[1]) == {
            (("code", "entity_renamed"),)
        }
        assert _codes(upgrade.compare(old, _spec([REF], entity={"project_scoped": False}))[1]) == {
            (("code", "scope_changed"),)
        }

    def test_the_table_speaks_for_required_fields_and_the_count(self) -> None:
        old = _spec([REF, COUNT])
        new = _spec(
            [REF, {**COUNT, "required": True}, {"name": "extra", "label": "Extra", "type": "text", "required": True}]
        )
        plan = layout.Plan(
            exists=True,
            records=4,
            problems=[
                layout.Problem("count", "Count", layout.NOW_REQUIRED, empty=2),
                layout.Problem("extra", "Extra", layout.NEW_REQUIRED),
            ],
        )

        _, problems = upgrade._verdict(old, new, plan)

        assert [p.as_dict() for p in problems] == [
            {"code": "field_now_required", "field": "count", "label": "Count", "empty": 2},
            {"code": "field_new_required", "field": "extra", "label": "Extra"},
        ]

    def test_the_status_column_is_named_once(self) -> None:
        old = _spec([REF], {"status": STATUS})
        plan = layout.Plan(exists=True, records=1, problems=[layout.Problem("status", "status", layout.REMOVED)])

        _, problems = upgrade._verdict(old, _spec([REF]), plan)

        assert [p.as_dict() for p in problems] == [{"code": "feature_removed", "feature": "status"}]

    def test_an_empty_register_refuses_only_another_table(self) -> None:
        old = _spec([REF, COUNT], {"export": True})
        empty = layout.Plan(exists=True, records=0, problems=[layout.Problem("count", "Count", layout.REMOVED)])

        assert upgrade._verdict(old, _spec([REF]), empty)[1] == []
        renamed = _spec([REF], entity={"name": "thing"})
        assert [p.code for p in upgrade._verdict(old, renamed, layout.Plan())[1]] == ["entity_renamed"]

    def test_the_refusal_carries_the_count_and_every_problem(self) -> None:
        refused = upgrade.refusal(3, [upgrade.Problem("field_removed", field="count", label="Count")])

        assert (refused.status, refused.code) == (409, "upgrade_not_additive")
        assert refused.params == {
            "records": 3,
            "problems": [{"code": "field_removed", "field": "count", "label": "Count"}],
        }
        assert "3 records" in str(refused) and "Nothing was changed" in str(refused)


class TestTheUpgradeToken:
    def test_an_install_token_does_not_upgrade_and_back(self) -> None:
        spec = _spec([REF])
        installing = review_token.issue(spec, USER)
        upgrading = review_token.issue(spec, USER, purpose=review_token.UPGRADE)

        review_token.verify(installing, spec, USER)
        review_token.verify(upgrading, spec, USER, purpose=review_token.UPGRADE)
        with pytest.raises(review_token.ReviewTokenInvalid, match="another action"):
            review_token.verify(installing, spec, USER, purpose=review_token.UPGRADE)
        with pytest.raises(review_token.ReviewTokenInvalid, match="another action"):
            review_token.verify(upgrading, spec, USER)

    def test_it_binds_the_spec(self) -> None:
        upgrading = review_token.issue(_spec([REF]), USER, purpose=review_token.UPGRADE)
        with pytest.raises(review_token.ReviewTokenInvalid, match="not the spec"):
            review_token.verify(upgrading, _spec([REF, COUNT]), USER, purpose=review_token.UPGRADE)


class TestWhichModuleIsUpgraded:
    @pytest.fixture
    def root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(upgrade, "runtime_modules_dir", lambda: tmp_path)
        return tmp_path

    def test_the_installed_spec_is_read_back(self, root: Path) -> None:
        spec = _spec([REF, COUNT])
        generator.write(spec, root)
        assert upgrade.installed_spec(spec.key) == spec

    def test_nothing_installed(self, root: Path) -> None:
        with pytest.raises(upgrade.UpgradeRefused) as refused:
            upgrade.installed_spec("rv_upgrade")
        assert (refused.value.status, refused.value.code) == (404, "not_installed")

    def test_quarantined(self, root: Path) -> None:
        spec = _spec([REF])
        generator.write(spec, refresh.quarantine_dir(root))
        with pytest.raises(upgrade.UpgradeRefused) as refused:
            upgrade.installed_spec(spec.key)
        assert (refused.value.status, refused.value.code) == (409, "module_quarantined")

    def test_unreadable(self, root: Path) -> None:
        spec = _spec([REF])
        generator.write(spec, root)
        (root / spec.key / "spec.json").write_text(json.dumps({"key": spec.key}), encoding="utf-8")
        with pytest.raises(upgrade.UpgradeRefused) as refused:
            upgrade.installed_spec(spec.key)
        assert (refused.value.status, refused.value.code) == (409, "module_unreadable")


class TestTheRoutes:
    async def test_a_spec_for_another_key_is_refused(self) -> None:
        from app.modules.module_builder import router
        from app.modules.module_builder.schemas import PreviewRequest

        with pytest.raises(HTTPException) as refused:
            await router.upgrade_preview("rv_other", PreviewRequest(spec=_spec([REF])), USER)
        assert refused.value.status_code == 422

    async def test_a_refusal_is_an_object_the_frontend_words(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.module_builder import router
        from app.modules.module_builder.schemas import UpgradeRequest

        spec = _spec([REF])

        async def refuse(key: str, spec: ModuleSpec, app: Any) -> upgrade.Outcome:
            raise upgrade.refusal(2, [upgrade.Problem("feature_removed", feature="export")])

        monkeypatch.setattr(upgrade, "upgrade", refuse)
        token = review_token.issue(spec, USER, purpose=review_token.UPGRADE)
        with pytest.raises(HTTPException) as refused:
            await router.upgrade_module(
                spec.key, UpgradeRequest(spec=spec, review_token=token), SimpleNamespace(app=None), USER
            )

        assert refused.value.status_code == 409
        detail = refused.value.detail
        assert detail["code"] == "upgrade_not_additive"
        assert detail["params"] == {"records": 2, "problems": [{"code": "feature_removed", "feature": "export"}]}
        assert detail["message"]

    async def test_an_install_token_is_refused_before_anything_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.module_builder import router
        from app.modules.module_builder.schemas import UpgradeRequest

        spec = _spec([REF])
        ran: list[str] = []

        async def record(key: str, spec: ModuleSpec, app: Any) -> upgrade.Outcome:
            ran.append(key)
            return upgrade.Outcome([], 0)

        monkeypatch.setattr(upgrade, "upgrade", record)
        with pytest.raises(HTTPException) as refused:
            await router.upgrade_module(
                spec.key,
                UpgradeRequest(spec=spec, review_token=review_token.issue(spec, USER)),
                SimpleNamespace(app=None),
                USER,
            )
        assert refused.value.status_code == 400
        assert ran == []

    async def test_the_vocabulary_says_upgrades_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.module_builder import router

        async def no_assistant(db: Any, user_id: str) -> bool:
            return False

        monkeypatch.setattr(router, "_assistant_available", no_assistant)
        assert (await router.vocabulary(None, USER)).upgrade is True
