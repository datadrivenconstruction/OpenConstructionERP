# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""End-to-end behaviour of the Cost Match API against a real database.

Walks the workflow the module exists for: paste a foreign bill, get a queue
back, work the queue by confirming, overriding and rejecting, then validate
what came out of it. Also pins the contract details that are easy to break
without noticing - money and confidence as strings, explanations rendered in
the reader's language, 404 rather than 403 on an id the caller cannot use, and
the closed-run guard.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

BASE = "/api/v1/cost-match"

WALL = "Reinforced concrete wall C30/37"
REBAR_DE = "Bewehrungsstahl"
NONSENSE = "Bituminous shingle underlay felt"


async def _create_run(
    client: AsyncClient,
    header: dict[str, str],
    project_id: str,
    lines: list[dict[str, object]],
    **overrides: object,
) -> dict:
    from tests.modules.cost_match.conftest import TEST_REGION, TEST_SOURCE

    payload: dict[str, object] = {
        "project_id": project_id,
        "name": f"Bill {uuid.uuid4().hex[:6]}",
        "source_label": "Foreign subcontractor",
        "source_locale": "en",
        "cost_source": TEST_SOURCE,
        "region": TEST_REGION,
        "lines": lines,
    }
    payload.update(overrides)
    response = await client.post(f"{BASE}/runs/", json=payload, headers=header)
    assert response.status_code == 201, response.text
    return response.json()


async def _results(client: AsyncClient, header: dict[str, str], run_id: str, **params: object) -> dict:
    response = await client.get(f"{BASE}/runs/{run_id}/results", params=params, headers=header)
    assert response.status_code == 200, response.text
    return response.json()


class TestHealth:
    async def test_health_endpoint_keeps_its_mounted_path(self, client: AsyncClient) -> None:
        """The loader's health roll-up reads this exact URL - do not move it."""
        response = await client.get(f"{BASE}/cost-match/_health")
        assert response.status_code == 200
        assert response.json()["module"] == "oe_cost_match"


class TestSubmitBatch:
    @pytest.mark.parametrize("submitted", ["omitted", "null", "forged"])
    @pytest.mark.parametrize("claim", ["actor", "tenant", "non_uuid"])
    async def test_run_tenant_comes_from_authenticated_scope(
        self, client, header, project_id, cost_base, monkeypatch, submitted, claim
    ):
        from app.config import get_settings
        from app.database import async_session_factory
        from app.modules.cost_match import events
        from app.modules.cost_match.models import MatchRun
        from app.modules.cost_match.service import event_bus
        from app.modules.users.models import User
        from app.modules.users.service import create_access_token

        me = await client.get("/api/v1/users/me", headers=header)
        assert me.status_code == 200, me.text
        actor = uuid.UUID(me.json()["id"])
        trusted = str(uuid.uuid4()) if claim == "tenant" else "external-tenant-key"
        async with async_session_factory() as session:
            user = await session.get(User, actor)
            token = create_access_token(user, get_settings(), {} if claim == "actor" else {"tenant_id": trusted})
        scoped_header = {"Authorization": f"Bearer {token}"}
        expected = str(actor) if claim == "actor" else trusted if claim == "tenant" else None
        published = []
        monkeypatch.setattr(
            event_bus,
            "publish_detached",
            lambda name, data, **kwargs: published.append((name, data)),
        )
        fields = {} if submitted == "omitted" else {"tenant_id": None if submitted == "null" else str(uuid.uuid4())}
        run = await _create_run(
            client, scoped_header, project_id, [{"description": WALL, "unit": "m3", "quantity": "1"}], **fields
        )
        assert run["tenant_id"] == expected
        assert run["created_by"] == str(actor)
        async with async_session_factory() as session:
            stored = await session.get(MatchRun, uuid.UUID(run["id"]))
            assert (str(stored.tenant_id) if stored.tenant_id else None) == expected
        completed = [data for name, data in published if name == events.MATCH_COMPLETED]
        assert len(completed) == 1
        assert completed[0]["run_id"] == run["id"]
        assert completed[0]["tenant_id"] == expected

    async def test_tenant_attribution_does_not_grant_access_to_a_foreign_project(
        self, client, header, project_id, cost_base
    ):
        from sqlalchemy import func, select

        from app.config import get_settings
        from app.database import async_session_factory
        from app.modules.cost_match.models import MatchRun
        from app.modules.users.models import User
        from app.modules.users.service import create_access_token

        owner = (await client.get("/api/v1/users/me", headers=header)).json()["id"]
        async with async_session_factory() as session:
            stranger = User(
                email=f"cost-match-stranger-{uuid.uuid4().hex}@test.invalid",
                hashed_password="unused-signed-token-fixture",
                role="editor",
                is_active=True,
            )
            session.add(stranger)
            await session.commit()
            token = create_access_token(stranger, get_settings(), {"tenant_id": owner})
            before = await session.scalar(select(func.count()).select_from(MatchRun))
        response = await client.post(
            f"{BASE}/runs/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "project_id": project_id,
                "tenant_id": owner,
                "lines": [{"description": WALL, "unit": "m3", "quantity": "1"}],
            },
        )
        assert response.status_code == 404, response.text
        async with async_session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(MatchRun)) == before

    async def test_a_batch_comes_back_as_a_queue(self, client: AsyncClient, header, project_id, cost_base) -> None:
        run = await _create_run(
            client,
            header,
            project_id,
            [
                {"description": WALL, "unit": "m3", "quantity": "44.3", "source_ref": "SUB-014"},
                {"description": REBAR_DE, "unit": "kg", "quantity": "3200"},
                {"description": NONSENSE, "unit": "m2", "quantity": "310"},
            ],
        )
        assert run["item_count"] == 3
        assert run["status"] == "matched"
        counts = run["counts"]
        assert counts["total"] == 3
        assert counts["exact"] == 1
        assert counts["high_confidence"] == 1
        assert counts["unmatched"] == 1
        # Nothing is applied by matching alone: the whole batch is pending.
        assert counts["pending"] == 3
        assert counts["confirmed"] == 0
        assert counts["queue_length"] == 1

    async def test_results_carry_their_evidence(self, client: AsyncClient, header, project_id, cost_base) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        page = await _results(client, header, run["id"])
        assert page["total"] == 1
        item = page["items"][0]
        assert item["tier"] == "exact"
        assert item["suggested_code"] == "CM-C30-WALL"
        # Decimal-as-string on the wire, never a JSON number.
        assert item["confidence"] == "1.0000"
        assert item["suggested_rate"] == "185.0000"
        assert item["source_quantity"] == "44.300"
        assert "exact_match" in item["reason_codes"]
        assert item["explanation"]
        assert item["decision_state"] == "pending"
        assert item["decisions"] == []

    async def test_the_explanation_follows_the_reader_not_the_database(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        """Reason codes are stored; the sentence is rendered per reader."""
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        english = (await _results(client, header, run["id"], locale="en"))["items"][0]
        german = (await _results(client, header, run["id"], locale="de"))["items"][0]
        assert english["reason_codes"] == german["reason_codes"]
        assert english["explanation"] != german["explanation"]

    async def test_an_empty_batch_is_rejected(self, client: AsyncClient, header, project_id) -> None:
        response = await client.post(
            f"{BASE}/runs/",
            json={"project_id": project_id, "name": "empty", "lines": []},
            headers=header,
        )
        assert response.status_code == 422

    async def test_authentication_is_required(self, client: AsyncClient, project_id) -> None:
        response = await client.post(f"{BASE}/runs/", json={"project_id": project_id, "lines": []})
        assert response.status_code in (401, 403)


class TestReviewQueue:
    async def test_the_queue_holds_only_what_needs_a_person(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        run = await _create_run(
            client,
            header,
            project_id,
            [
                {"description": WALL, "unit": "m3", "quantity": "44.3"},
                {"description": NONSENSE, "unit": "m2", "quantity": "310"},
                {"description": "Stahlbetonwand", "unit": "m3", "quantity": "12"},
            ],
        )
        response = await client.get(f"{BASE}/runs/{run['id']}/review-queue", headers=header)
        assert response.status_code == 200, response.text
        page = response.json()
        tiers = {item["tier"] for item in page["items"]}
        assert tiers == {"unmatched", "needs_review"}
        assert page["total"] == 2

    async def test_results_can_be_filtered_by_tier(self, client: AsyncClient, header, project_id, cost_base) -> None:
        run = await _create_run(
            client,
            header,
            project_id,
            [
                {"description": WALL, "unit": "m3", "quantity": "44.3"},
                {"description": NONSENSE, "unit": "m2", "quantity": "310"},
            ],
        )
        page = await _results(client, header, run["id"], tier="exact")
        assert page["total"] == 1
        assert page["items"][0]["tier"] == "exact"

    async def test_an_unknown_tier_filter_is_refused(self, client: AsyncClient, header, project_id, cost_base) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        response = await client.get(
            f"{BASE}/runs/{run['id']}/results",
            params={"tier": "definitely_matched"},
            headers=header,
        )
        assert response.status_code == 422


class TestDecisions:
    async def test_confirm_override_and_reject(self, client: AsyncClient, header, project_id, cost_base) -> None:
        run = await _create_run(
            client,
            header,
            project_id,
            [
                {"description": WALL, "unit": "m3", "quantity": "44.3"},
                {"description": "Stahlbetonwand", "unit": "m3", "quantity": "12"},
                {"description": NONSENSE, "unit": "m2", "quantity": "310"},
            ],
        )
        items = (await _results(client, header, run["id"]))["items"]
        confirmed, overridden, rejected = items

        response = await client.post(
            f"{BASE}/results/{confirmed['id']}/decision",
            json={"decision": "confirmed", "note": "matches the spec"},
            headers=header,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["seq"] == 1
        assert body["decided_code"] == "CM-C30-WALL"
        assert body["decided_rate"] == "185.0000"
        assert body["confidence_at_decision"] == "1.0000"
        assert body["decided_by"]

        response = await client.post(
            f"{BASE}/results/{overridden['id']}/decision",
            json={"decision": "overridden", "cost_item_id": str(cost_base["CM-FORMWORK"])},
            headers=header,
        )
        assert response.status_code == 201, response.text
        assert response.json()["decided_code"] == "CM-FORMWORK"

        response = await client.post(
            f"{BASE}/results/{rejected['id']}/decision",
            json={"decision": "rejected", "note": "nothing in this base fits"},
            headers=header,
        )
        assert response.status_code == 201, response.text
        assert response.json()["decided_cost_item_id"] is None

        run_body = (await client.get(f"{BASE}/runs/{run['id']}", headers=header)).json()
        counts = run_body["counts"]
        assert counts["confirmed"] == 1
        assert counts["overridden"] == 1
        assert counts["rejected"] == 1
        assert counts["pending"] == 0
        assert counts["queue_length"] == 0

    async def test_a_change_of_mind_is_visible(self, client: AsyncClient, header, project_id, cost_base) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        result_id = (await _results(client, header, run["id"]))["items"][0]["id"]
        await client.post(
            f"{BASE}/results/{result_id}/decision",
            json={"decision": "confirmed"},
            headers=header,
        )
        await client.post(
            f"{BASE}/results/{result_id}/decision",
            json={"decision": "overridden", "cost_item_id": str(cost_base["CM-REBAR"])},
            headers=header,
        )
        history = await client.get(f"{BASE}/results/{result_id}/decisions", headers=header)
        assert history.status_code == 200, history.text
        rows = history.json()
        assert [row["seq"] for row in rows] == [1, 2]
        assert [row["decision"] for row in rows] == ["confirmed", "overridden"]

        detail = (await client.get(f"{BASE}/results/{result_id}", headers=header)).json()
        assert detail["decision_state"] == "overridden"
        assert len(detail["decisions"]) == 2
        # The original suggestion is not rewritten by the override.
        assert detail["suggested_code"] == "CM-C30-WALL"

    async def test_confirming_a_line_with_no_suggestion_is_422(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        run = await _create_run(
            client, header, project_id, [{"description": NONSENSE, "unit": "m2", "quantity": "310"}]
        )
        result_id = (await _results(client, header, run["id"]))["items"][0]["id"]
        response = await client.post(
            f"{BASE}/results/{result_id}/decision",
            json={"decision": "confirmed"},
            headers=header,
        )
        assert response.status_code == 422

    async def test_an_override_onto_an_unknown_item_is_404_not_403(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        result_id = (await _results(client, header, run["id"]))["items"][0]["id"]
        response = await client.post(
            f"{BASE}/results/{result_id}/decision",
            json={"decision": "overridden", "cost_item_id": str(uuid.uuid4())},
            headers=header,
        )
        assert response.status_code == 404

    async def test_a_closed_run_refuses_rulings_with_409(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        result_id = (await _results(client, header, run["id"]))["items"][0]["id"]
        closed = await client.patch(f"{BASE}/runs/{run['id']}", json={"status": "closed"}, headers=header)
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"

        response = await client.post(
            f"{BASE}/results/{result_id}/decision",
            json={"decision": "confirmed"},
            headers=header,
        )
        assert response.status_code == 409

        reopened = await client.patch(f"{BASE}/runs/{run['id']}", json={"status": "matched"}, headers=header)
        assert reopened.status_code == 200
        response = await client.post(
            f"{BASE}/results/{result_id}/decision",
            json={"decision": "confirmed"},
            headers=header,
        )
        assert response.status_code == 201


class TestValidation:
    async def test_a_run_with_an_open_queue_reports_it(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        response = await client.post(f"{BASE}/runs/{run['id']}/validate", headers=header)
        assert response.status_code == 200, response.text
        report = response.json()
        fired = {finding["rule_id"] for finding in report["findings"]}
        assert "cost_match.review_queue_cleared" in fired

    async def test_a_dimension_trap_is_an_error_on_the_line(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        """The whole point: a word-for-word match priced in the wrong unit."""
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m2", "quantity": "80"}])
        result_id = (await _results(client, header, run["id"]))["items"][0]["id"]
        await client.post(
            f"{BASE}/results/{result_id}/decision",
            json={"decision": "confirmed"},
            headers=header,
        )
        response = await client.post(f"{BASE}/results/{result_id}/validate", headers=header)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["status"] == "errors"
        assert "cost_match.unit_dimension_matches" in {f["rule_id"] for f in report["findings"]}

    async def test_a_run_report_folds_in_every_line(self, client: AsyncClient, header, project_id, cost_base) -> None:
        run = await _create_run(
            client,
            header,
            project_id,
            [
                {"description": WALL, "unit": "m2", "quantity": "80"},
                {"description": REBAR_DE, "unit": "kg", "quantity": "3200"},
            ],
        )
        items = (await _results(client, header, run["id"]))["items"]
        for item in items:
            await client.post(
                f"{BASE}/results/{item['id']}/decision",
                json={"decision": "confirmed"},
                headers=header,
            )
        report = (await client.post(f"{BASE}/runs/{run['id']}/validate", headers=header)).json()
        fired = {finding["rule_id"] for finding in report["findings"]}
        assert "cost_match.unit_dimension_matches" in fired
        assert "cost_match.review_queue_cleared" not in fired
        assert report["status"] == "errors"


class TestLifecycleAndAccess:
    async def test_runs_are_listed_per_project_with_live_counts(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        response = await client.get(f"{BASE}/runs/", params={"project_id": project_id}, headers=header)
        assert response.status_code == 200, response.text
        rows = response.json()
        listed = {row["id"]: row for row in rows}
        assert run["id"] in listed
        assert listed[run["id"]]["counts"]["total"] == 1

    async def test_deleting_a_run_takes_its_results_with_it(
        self, client: AsyncClient, header, project_id, cost_base
    ) -> None:
        run = await _create_run(client, header, project_id, [{"description": WALL, "unit": "m3", "quantity": "44.3"}])
        result_id = (await _results(client, header, run["id"]))["items"][0]["id"]
        response = await client.delete(f"{BASE}/runs/{run['id']}", headers=header)
        assert response.status_code == 204, response.text
        assert (await client.get(f"{BASE}/runs/{run['id']}", headers=header)).status_code == 404
        assert (await client.get(f"{BASE}/results/{result_id}", headers=header)).status_code == 404

    @pytest.mark.parametrize(
        "path",
        [
            "/runs/{unknown}",
            "/runs/{unknown}/results",
            "/runs/{unknown}/review-queue",
            "/results/{unknown}",
            "/results/{unknown}/decisions",
        ],
    )
    async def test_unknown_ids_are_404_never_403(self, client: AsyncClient, header, path: str) -> None:
        """Probing for a UUID must never reveal whether it exists."""
        response = await client.get(f"{BASE}{path.format(unknown=uuid.uuid4())}", headers=header)
        assert response.status_code == 404, response.text
