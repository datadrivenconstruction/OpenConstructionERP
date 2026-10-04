"""An imported bill's codes satisfy the project's national code rule.

An Indian bill of quantities carries the CPWD DSR item number of every line
in its code column. The importer filed it under ``code`` and the rule
``cpwd.code_required`` reads ``cpwd``, so every line of a correctly coded
bill failed it. A Romanian project is imported beside it to hold the other
side: its code column is the national norm code, and it must not be copied
under ``din276``.

Run::

    cd backend
    python -m pytest tests/integration/test_boq_import_carries_the_code_under_the_national_key.py -v
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

_INDIAN_BILL = (
    b"Item No.,DSR Code,Description,Unit,Quantity,Rate\n"
    b"A,,EARTH WORK,,,\n"
    b"1,2.8.1,Earth work in excavation by mechanical means,cum,120.5,215.40\n"
    b"2,13.1.1,Cement plaster 12 mm thick in single coat,sqm,340,268.15\n"
)

_ROMANIAN_BILL = (
    "Nr. crt.,Simbol,Denumire,U.M.,Cantitate,Preț unitar\n"
    "1,CA01A1,Beton simplu în fundații,mc,12.5,450.00\n"
    "2,TSA02D1,Săpătură manuală în spații limitate,mc,40,85.50\n"
).encode()


@pytest_asyncio.fixture(scope="module")
async def shared_client():
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def shared_auth(shared_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"boqcodekey-{unique}@test.io"
    password = f"BoqCodeKey{unique}9"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Code Key Tester", "role": "admin"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await shared_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


async def _create_boq(client: AsyncClient, auth: dict[str, str], *, country: str, currency: str) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Code key {country} {uuid.uuid4().hex[:6]}",
            "description": "Project for the national code key import test",
            "region": country,
            "country_code": country,
            "currency": currency,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": resp.json()["id"], "name": "Bill", "description": "Imported bill"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _import(client: AsyncClient, auth: dict[str, str], boq_id: str, route: str, content: bytes) -> dict:
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/{route}/",
        files={"file": ("bill.csv", content, "text/csv")},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _lines(client: AsyncClient, auth: dict[str, str], boq_id: str) -> list[dict]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return [p for p in resp.json()["positions"] if p["unit"] not in ("", "section")]


def _results(body: dict, rule_id: str) -> list[dict]:
    """The inline validation results of one rule; the report itself must be there."""
    report = body.get("validation_report")
    assert report is not None, "inline import validation did not report"
    return [r for r in report.get("results", []) if r.get("rule_id") == rule_id]


def _by_description(lines: list[dict]) -> dict[str, dict]:
    return {p["description"]: p["classification"] or {} for p in lines}


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["auto", "excel"])
async def test_an_indian_bill_carries_its_dsr_codes_under_cpwd(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    route: str,
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth, country="IN", currency="INR")
    body = await _import(shared_client, shared_auth, boq_id, route, _INDIAN_BILL)
    assert body["errors"] == []

    lines = await _lines(shared_client, shared_auth, boq_id)
    assert sorted((p["classification"] or {}).get("cpwd") for p in lines) == ["13.1.1", "2.8.1"]

    # The report must exist and the rule must have run: an empty list of
    # failures also comes back when inline validation swallowed an exception
    # or the cpwd set was never selected.
    checked = _results(body, "cpwd.code_required")
    assert len(checked) == 2
    assert all(r["passed"] for r in checked)


@pytest.mark.asyncio
async def test_a_romanian_bill_keeps_its_norm_code_out_of_din276(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth, country="RO", currency="RON")
    body = await _import(shared_client, shared_auth, boq_id, "auto", _ROMANIAN_BILL)
    assert body["errors"] == []

    lines = await _lines(shared_client, shared_auth, boq_id)
    classifications = [p["classification"] or {} for p in lines]
    assert sorted(c.get("code") for c in classifications) == ["CA01A1", "TSA02D1"]
    assert [c for c in classifications if "din276" in c] == []


# A Russian smeta's justification column cites a GESN norm on one line, a
# regional price base item on the next and a supplier's price list on the
# third. Only the first is a norm code.
_RUSSIAN_SMETA = (
    "№ п/п;Обоснование;Наименование работ и затрат;Ед. изм.;Кол.;Цена\n"
    "1;ГЭСН06-01-001-01;Устройство бетонной подготовки;м3;12;5400\n"
    "2;ФССЦ-04.1.02.05-0006;Бетон тяжелый класса B15;м3;12;4800\n"
    "3;Прайс-лист;Доставка опалубки;шт;1;15000\n"
).encode()

_RUSSIAN_SMETA_WITHOUT_NORMS = (
    "№ п/п;Обоснование;Наименование работ и затрат;Ед. изм.;Кол.;Цена\n"
    "1;ФССЦ-04.1.02.05-0006;Бетон тяжелый класса B15;м3;12;4800\n"
    "2;Прайс-лист;Доставка опалубки;шт;1;15000\n"
).encode()

_TURKISH_KESIF = (
    "Sıra No;Poz No;Tanım;Birim;Miktar;Birim Fiyat\n"
    "1;15.150.1005;Makine ile her derinlikte yumuşak toprak kazısı;m3;120;240\n"
    "2;15.180.1003;Kazı fazlası toprağın nakli;m3;80;420\n"
).encode()

# One line per price bank. The ORSE code has the shape of a SINAPI code, so
# only the bank column tells the two apart.
_BRAZILIAN_ORCAMENTO = (
    "Item;Código;Banco;Descrição;Und;Quant.;Valor Unit;Total\n"
    "1;92873;SINAPI;Armação de pilar com aço CA-50;KG;350;12,50;4375,00\n"
    "2;5914359;SICRO3;Transporte com caminhão basculante;TKM;1200;1,20;1440,00\n"
    "3;COMP-01;PRÓPRIO;Mobilização de canteiro;UN;1;45000,00;45000,00\n"
    "4;00012;ORSE;Limpeza mecanizada do terreno;M2;500;3,10;1550,00\n"
).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["auto", "excel"])
async def test_a_russian_smeta_files_only_its_norm_codes_under_gesn(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    route: str,
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth, country="RU", currency="RUB")
    body = await _import(shared_client, shared_auth, boq_id, route, _RUSSIAN_SMETA)
    assert body["errors"] == []

    by_description = _by_description(await _lines(shared_client, shared_auth, boq_id))
    assert by_description["Устройство бетонной подготовки"]["gesn"] == "06-01-001-01"
    assert by_description["Устройство бетонной подготовки"]["code"] == "ГЭСН06-01-001-01"
    assert "gesn" not in by_description["Бетон тяжелый класса B15"]
    assert "gesn" not in by_description["Доставка опалубки"]
    assert by_description["Доставка опалубки"]["code"] == "Прайс-лист"

    # The norm code passes the format rule: before, the printed prefix failed
    # it on the one line that does cite a norm.
    formats = _results(body, "gesn.valid_code")
    assert len(formats) == 1
    assert formats[0]["passed"]
    # The two lines that cite no norm are still reported as uncoded, which is
    # what they are.
    required = _results(body, "gesn.code_required")
    assert sorted(r["passed"] for r in required) == [False, False, True]


@pytest.mark.asyncio
async def test_a_smeta_without_norm_codes_is_not_read_as_a_norm_estimate(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
) -> None:
    # Filing a price list under gesn made every flat line a "norm" line with
    # no resource breakdown, and the whole bill a Russian norm estimate.
    boq_id = await _create_boq(shared_client, shared_auth, country="RU", currency="RUB")
    body = await _import(shared_client, shared_auth, boq_id, "auto", _RUSSIAN_SMETA_WITHOUT_NORMS)
    assert body["errors"] == []

    lines = await _lines(shared_client, shared_auth, boq_id)
    assert [p for p in lines if "gesn" in (p["classification"] or {})] == []
    assert _results(body, "gesn.resource_breakdown") == []
    assert _results(body, "gesn.valid_code") == []
    assert len(_results(body, "gesn.code_required")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["auto", "excel"])
async def test_a_turkish_bill_carries_its_current_poz_numbers(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    route: str,
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth, country="TR", currency="TRY")
    body = await _import(shared_client, shared_auth, boq_id, route, _TURKISH_KESIF)
    assert body["errors"] == []

    lines = await _lines(shared_client, shared_auth, boq_id)
    assert sorted((p["classification"] or {}).get("birimfiyat") for p in lines) == ["15.150.1005", "15.180.1003"]

    for rule_id in ("birimfiyat.code_required", "birimfiyat.valid_poz"):
        checked = _results(body, rule_id)
        assert len(checked) == 2, rule_id
        assert all(r["passed"] for r in checked), rule_id


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["auto", "excel"])
async def test_a_brazilian_bill_files_only_its_sinapi_lines_under_sinapi(
    shared_client: AsyncClient,
    shared_auth: dict[str, str],
    route: str,
) -> None:
    boq_id = await _create_boq(shared_client, shared_auth, country="BR", currency="BRL")
    body = await _import(shared_client, shared_auth, boq_id, route, _BRAZILIAN_ORCAMENTO)
    assert body["errors"] == []

    by_description = _by_description(await _lines(shared_client, shared_auth, boq_id))
    assert by_description["Armação de pilar com aço CA-50"] == {"code": "92873", "banco": "SINAPI", "sinapi": "92873"}
    assert by_description["Transporte com caminhão basculante"] == {"code": "5914359", "banco": "SICRO3"}
    assert by_description["Mobilização de canteiro"] == {"code": "COMP-01", "banco": "PRÓPRIO"}
    assert by_description["Limpeza mecanizada do terreno"] == {"code": "00012", "banco": "ORSE"}

    # Every line passes the SINAPI code rule: the SINAPI line by its code, the
    # others by naming their bank, which is the exemption the rule was written
    # with and which no imported bill could reach while the bank was dropped.
    required = _results(body, "sinapi.code_required")
    assert len(required) == 4
    assert all(r["passed"] for r in required)
    formats = _results(body, "sinapi.valid_code")
    assert len(formats) == 1
    assert formats[0]["passed"]
