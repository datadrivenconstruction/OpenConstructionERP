# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project catalogue workflow end to end against a real database.

The worked example: copy a 185.00 EUR wall rate from the regional database,
price this job at 172.50, price a 10 m3 bill line from it, then the database
moves to 190.00 and the estimator decides. The master row must never move
because of anything done in the project.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.modules.project_catalogue.conftest import TEST_REGION, master_rate, set_source_rate

BASE = "/api/v1/project-catalogue"


async def _import(client: AsyncClient, header: dict, project_id: str, cost_item_id: uuid.UUID) -> dict:
    response = await client.post(
        f"{BASE}/projects/{project_id}/items/import",
        json={"source_type": "cost_item", "source_ids": [str(cost_item_id)]},
        headers=header,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _items(client: AsyncClient, header: dict, project_id: str, **params: str) -> dict:
    response = await client.get(f"{BASE}/projects/{project_id}/items", params=params, headers=header)
    assert response.status_code == 200, response.text
    return response.json()


async def _bill_line(client: AsyncClient, header: dict, project_id: str, quantity: float = 10) -> str:
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": project_id, "name": "Main bill"}, headers=header)
    assert boq.status_code == 201, boq.text
    boq_id = boq.json()["id"]
    position = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Concrete wall",
            "unit": "m3",
            "quantity": quantity,
            "unit_rate": "150.00",
        },
        headers=header,
    )
    assert position.status_code == 201, position.text
    return position.json()["id"]


async def _position(client: AsyncClient, header: dict, position_id: str) -> dict:
    response = await client.get(f"/api/v1/boq/positions/{position_id}", headers=header)
    assert response.status_code == 200, response.text
    return response.json()


class TestCopyAndOverride:
    async def test_copy_keeps_provenance_and_is_in_sync(self, client, header, project_id, wall_item) -> None:
        body = await _import(client, header, project_id, wall_item)
        assert body["added"] == 1
        item = body["items"][0]
        assert item["rate"] == "185.00"
        assert item["source_rate"] == "185.00"
        assert item["source_id"] == str(wall_item)
        assert TEST_REGION in item["source_label"]
        assert item["status"] == "in_sync"

    async def test_second_copy_of_the_same_row_is_skipped(self, client, header, project_id, wall_item) -> None:
        await _import(client, header, project_id, wall_item)
        again = await _import(client, header, project_id, wall_item)
        assert (again["added"], again["skipped"]) == (0, 1)
        assert (await _items(client, header, project_id))["total"] == 1

    async def test_local_edit_overrides_and_leaves_master_untouched(
        self, client, header, project_id, wall_item
    ) -> None:
        item = (await _import(client, header, project_id, wall_item))["items"][0]
        response = await client.patch(f"{BASE}/items/{item['id']}", json={"rate": "172.50"}, headers=header)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "overridden"
        assert body["deviation_percent"] == "-6.8"
        assert await master_rate(wall_item) == "185.00"

    async def test_slipped_decimal_saves_with_a_warning(self, client, header, project_id, wall_item) -> None:
        item = (await _import(client, header, project_id, wall_item))["items"][0]
        response = await client.patch(f"{BASE}/items/{item['id']}", json={"rate": "1725.00"}, headers=header)
        assert response.status_code == 200, response.text
        rules = {w["rule_id"] for w in response.json()["warnings"]}
        assert "project_catalogue.override_plausible" in rules

    async def test_negative_rate_is_refused(self, client, header, project_id, wall_item) -> None:
        item = (await _import(client, header, project_id, wall_item))["items"][0]
        response = await client.patch(f"{BASE}/items/{item['id']}", json={"rate": "-5"}, headers=header)
        assert response.status_code == 422, response.text


class TestMovedSource:
    async def _overridden(self, client, header, project_id, wall_item) -> str:
        item = (await _import(client, header, project_id, wall_item))["items"][0]
        await client.patch(f"{BASE}/items/{item['id']}", json={"rate": "172.50"}, headers=header)
        await set_source_rate(wall_item, "190.00")
        return item["id"]

    async def test_moved_source_is_shown(self, client, header, project_id, wall_item) -> None:
        await self._overridden(client, header, project_id, wall_item)
        body = await _items(client, header, project_id)
        assert body["summary"]["source_changed"] == 1
        item = body["items"][0]
        assert (item["status"], item["current_source_rate"], item["rate"]) == ("source_changed", "190.00", "172.50")

    async def test_take_source(self, client, header, project_id, wall_item) -> None:
        await self._overridden(client, header, project_id, wall_item)
        response = await client.post(
            f"{BASE}/projects/{project_id}/items/sync", json={"action": "take_source"}, headers=header
        )
        assert response.json() == {"updated": 1, "skipped": 0}
        item = (await _items(client, header, project_id))["items"][0]
        assert (item["status"], item["rate"], item["source_rate"]) == ("in_sync", "190.00", "190.00")

    async def test_keep_local(self, client, header, project_id, wall_item) -> None:
        await self._overridden(client, header, project_id, wall_item)
        response = await client.post(
            f"{BASE}/projects/{project_id}/items/sync", json={"action": "keep_local"}, headers=header
        )
        assert response.json()["updated"] == 1
        item = (await _items(client, header, project_id))["items"][0]
        assert (item["status"], item["rate"], item["source_rate"]) == ("overridden", "172.50", "190.00")

    async def test_validation_reports_the_moved_source(self, client, header, project_id, wall_item) -> None:
        await self._overridden(client, header, project_id, wall_item)
        response = await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)
        assert response.status_code == 200, response.text
        rules = {f["rule_id"] for f in response.json()["findings"]}
        assert "project_catalogue.source_current" in rules


class TestBillLines:
    async def test_apply_prices_the_line_and_push_follows_an_edit(self, client, header, project_id, wall_item) -> None:
        item = (await _import(client, header, project_id, wall_item))["items"][0]
        await client.patch(f"{BASE}/items/{item['id']}", json={"rate": "172.50"}, headers=header)
        position_id = await _bill_line(client, header, project_id)

        candidates = await client.get(f"{BASE}/items/{item['id']}/positions", headers=header)
        assert [c["id"] for c in candidates.json()["items"]] == [position_id]

        applied = await client.post(
            f"{BASE}/items/{item['id']}/apply", json={"position_ids": [position_id]}, headers=header
        )
        assert applied.json()["applied"] == 1, applied.text
        line = await _position(client, header, position_id)
        assert float(line["unit_rate"]) == 172.5
        assert float(line["total"]) == 1725.0
        assert line["metadata"]["project_catalogue_item_id"] == item["id"]

        await client.patch(f"{BASE}/items/{item['id']}", json={"rate": "180.00"}, headers=header)
        listed = (await _items(client, header, project_id))["items"][0]
        assert (listed["linked_positions"], listed["stale_positions"]) == (1, 1)

        pushed = await client.post(f"{BASE}/items/{item['id']}/push", headers=header)
        assert pushed.json()["applied"] == 1
        line = await _position(client, header, position_id)
        assert float(line["total"]) == 1800.0
        assert (await _items(client, header, project_id))["items"][0]["stale_positions"] == 0

    async def test_line_of_another_project_is_skipped(self, client, header, project_id, wall_item) -> None:
        item = (await _import(client, header, project_id, wall_item))["items"][0]
        other = await client.post("/api/v1/projects/", json={"name": "Other", "currency": "EUR"}, headers=header)
        foreign = await _bill_line(client, header, other.json()["id"])
        applied = await client.post(
            f"{BASE}/items/{item['id']}/apply", json={"position_ids": [foreign]}, headers=header
        )
        assert (applied.json()["applied"], applied.json()["skipped"]) == (0, 1)


class TestOwnRatesAndAccess:
    async def test_own_rate_in_foreign_currency_warns(self, client, header, project_id) -> None:
        response = await client.post(
            f"{BASE}/projects/{project_id}/items",
            json={"code": "OWN-1", "description": "Site cleaning", "unit": "h", "rate": "35", "currency": "usd"},
            headers=header,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert (body["status"], body["currency"]) == ("manual", "USD")
        assert "project_catalogue.currency_matches_project" in {w["rule_id"] for w in body["warnings"]}

    async def test_search_marks_rows_already_copied(self, client, header, project_id, wall_item) -> None:
        await _import(client, header, project_id, wall_item)
        response = await client.get(
            f"{BASE}/projects/{project_id}/sources",
            params={"q": "Reinforced concrete wall", "region": TEST_REGION, "limit": 100},
            headers=header,
        )
        assert response.status_code == 200, response.text
        hit = next(h for h in response.json()["items"] if h["source_id"] == str(wall_item))
        assert hit["already_added"] is True

    async def test_foreign_project_is_404(self, client, header, stranger, project_id, wall_item) -> None:
        item = (await _import(client, header, project_id, wall_item))["items"][0]
        assert (await client.get(f"{BASE}/projects/{project_id}/items", headers=stranger)).status_code == 404
        assert (
            await client.patch(f"{BASE}/items/{item['id']}", json={"rate": "1"}, headers=stranger)
        ).status_code == 404
