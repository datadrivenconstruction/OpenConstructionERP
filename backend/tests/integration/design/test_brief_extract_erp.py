"""R5 inside the ERP: real PDF text, real DXF through the takeoff parser, endpoints, agent tool."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from .conftest import LINK, make_project, make_user
from .test_brief_extract import FIX, Replay

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/design"


def _pdf(path: Path, pages: list[list[str]]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in pages:
        y = 800
        for line in lines:
            c.drawString(60, y, line)
            y -= 18
        c.showPage()
    c.save()


def _dxf(path: Path, texts: list[tuple[str, str]]) -> None:
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for i, (layer, text) in enumerate(texts):
        if layer not in doc.layers:
            doc.layers.add(layer)
        msp.add_text(text, dxfattribs={"layer": layer, "insert": (0, i * 5), "height": 2.5})
    msp.add_lwpolyline([(0, 0), (34, 0), (34, 12), (0, 12)], close=True, dxfattribs={"layer": "WALLS"})
    doc.saveas(str(path))


async def _document(project_id, owner, path: Path, *, mime: str, category: str) -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.documents.models import Document

    did = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Document(
                id=did,
                project_id=project_id,
                name=path.name,
                file_path=str(path),
                mime_type=mime,
                category=category,
                file_size=path.stat().st_size,
                uploaded_by=str(owner),
            )
        )
        await s.commit()
    return did


async def test_pdf_text_is_read_per_page_and_cited(tmp_path):
    from app.modules.design.brief_parse import anchor_quote, extract_candidates
    from app.modules.design.brief_sources import split_pages
    from app.modules.file_search.extractors import extract_text

    pdf = tmp_path / "beschreibung.pdf"
    _pdf(
        pdf,
        [
            ["Projektbeschreibung Mehrfamilienhaus", "Adresse: Leipzig, Deutschland"],
            ["Anzahl der Geschosse: 5", "BGF: 4.250 m2", "Stellplaetze: 40"],
        ],
    )
    pages = split_pages(extract_text(pdf.read_bytes(), "application/pdf").text)
    assert len(pages) == 2
    cands = {c.pointer: c for c in extract_candidates(pages, document_id="d")}
    assert cands["/massing/floors_above"].page == 2 and cands["/massing/floors_above"].value == 5
    assert cands["/massing/gross_floor_area_m2"].value == 4250
    assert cands["/country"].page == 1
    assert anchor_quote(pages, "Anzahl der Geschosse: 5", 1) == (2, "Anzahl der Geschosse: 5")


async def test_dxf_goes_through_the_takeoff_parser(tmp_path):
    from app.modules.design.brief_parse import extract_candidates
    from app.modules.design.brief_sources import cad_pages
    from app.modules.dwg_takeoff.dxf_processor import parse_dxf
    from app.modules.dwg_takeoff.service import _normalize_entity

    dxf = tmp_path / "grundriss.dxf"
    _dxf(dxf, [("TEXT", "Anzahl der Geschosse: 6"), ("TEXT", "BGF: 3.100 m2"), ("DIM", "Aufzug")])
    entities = [_normalize_entity(e, i) for i, e in enumerate(parse_dxf(str(dxf))["entities"])]
    pages = cad_pages(entities)
    assert len(pages) == 1 and "[layer TEXT]" in pages[0] and "Anzahl der Geschosse: 6" in pages[0]
    cands = {c.pointer: c for c in extract_candidates(pages, document_id="d", kind="drawing")}
    assert cands["/massing/floors_above"].value == 6 and cands["/massing/floors_above"].kind == "drawing"
    assert cands["/massing/gross_floor_area_m2"].value == 3100 and cands["/massing/lift"].value is True


async def test_extract_endpoint_with_pdf_dxf_text_and_replayed_model(client, tmp_path, monkeypatch):
    from app.modules.design import brief_api

    uid, h = await make_user(client)
    pid = await make_project(uid)
    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        p = await s.get(Project, pid)
        p.country_code, p.locale = "DE", "de"
        await s.commit()
    pdf = tmp_path / "leipzig.pdf"
    _pdf(
        pdf,
        [
            ["Projektbeschreibung", "Mehrfamilienhaus, Adresse: Leipzig, Deutschland"],
            [
                "Anzahl der Geschosse: 5",
                "Konstruktion: Mauerwerk mit Bodenplatte, Flachdach.",
                "Geschosshoehe: 3,0 m",
                "Budget: 4,5 Mio. EUR",
            ],
        ],
    )
    dxf = tmp_path / "plan.dxf"
    _dxf(dxf, [("TEXT", "BGF: 4.250,0 m2")])
    d_pdf = await _document(pid, uid, pdf, mime="application/pdf", category="specification")
    d_dxf = await _document(pid, uid, dxf, mime="application/octet-stream", category="drawing")

    reply = json.dumps(
        {
            "fields": [
                {
                    "pointer": "/structure/system",
                    "value": "masonry",
                    "document_id": str(d_pdf),
                    "page": 1,
                    "quote": "Konstruktion: Mauerwerk mit Bodenplatte",
                },
                {
                    "pointer": "/massing/lift",
                    "value": True,
                    "document_id": str(d_pdf),
                    "page": 2,
                    "quote": "Lift mit 8 Personen",
                },
            ]
        }
    )
    replay = Replay(reply)

    async def fake(session, user_id, editor=False):
        return replay

    monkeypatch.setattr(brief_api, "provider_completer", fake)
    r = await client.post(
        f"{BASE}/projects/{pid}/brief/extract",
        headers=h,
        json={"document_ids": [str(d_pdf), str(d_dxf)], "text": "Es gibt 2 Untergeschosse.", "use_ai": True},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    brief, prov = out["brief"], out["brief"]["provenance"]
    assert brief["schema"] == "ddc-brief/1" and brief["project_id"] == str(pid)
    assert brief["country"] == "DE" and prov["/country"]["sources"][0]["document_id"] == str(d_pdf)
    assert prov["/locale"]["status"] == "default"
    assert brief["massing"]["floors_above"] == 5 and prov["/massing/floors_above"]["sources"][0]["page"] == 2
    assert brief["massing"]["gross_floor_area_m2"] == 4250
    assert prov["/massing/gross_floor_area_m2"]["sources"][0]["kind"] == "drawing"
    assert brief["massing"]["floors_below"] == 2
    assert prov["/massing/floors_below"]["sources"][0] == {"kind": "text", "page": 1, "quote": "2 Untergeschosse"}
    assert brief["structure"]["system"] == "masonry"
    assert out["used_model"] and any(x["pointer"] == "/massing/lift" for x in out["rejected"])
    assert {q["pointer"] for q in brief["questions"]} == {"/depth_level"}
    assert all(e["status"] in ("proposed", "default") for e in prov.values())

    # answer the question; the field becomes confirmed by the caller
    q = brief["questions"][0]
    a = await client.post(
        f"{BASE}/projects/{pid}/brief/answers",
        headers=h,
        json={"brief": brief, "answers": [{"question_id": q["id"], "value": "D2"}]},
    )
    assert a.status_code == 200, a.text
    done = a.json()
    assert done["depth_level"] == "D2" and "questions" not in done
    assert done["provenance"]["/depth_level"]["status"] == "confirmed"
    assert done["provenance"]["/depth_level"]["confirmed_by"] == str(uid)
    bad = await client.post(
        f"{BASE}/projects/{pid}/brief/answers",
        headers=h,
        json={"brief": brief, "answers": [{"question_id": q["id"], "value": "D9"}]},
    )
    assert bad.status_code == 422


async def test_extract_endpoint_without_provider_and_foreign_document(client, tmp_path, monkeypatch):
    from app.modules.design import brief_api

    async def none(session, user_id, editor=False):
        return None

    monkeypatch.setattr(brief_api, "provider_completer", none)
    uid, h = await make_user(client)
    pid = await make_project(uid)
    other_uid, _ = await make_user(client)
    other = await make_project(other_uid)
    txt = tmp_path / "x.txt"
    txt.write_text("Bürogebäude, Anzahl der Geschosse: 12", encoding="utf-8")
    foreign = await _document(other, other_uid, txt, mime="text/plain", category="other")
    mine = await _document(pid, uid, txt, mime="text/plain", category="other")
    r = await client.post(
        f"{BASE}/projects/{pid}/brief/extract", headers=h, json={"document_ids": [str(foreign), str(mine)]}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["used_model"] is False and any("No AI provider" in n for n in out["notes"])
    assert any("is not in this project" in n for n in out["notes"])
    assert out["brief"]["massing"]["floors_above"] == 12 and out["brief"]["use"]["category"] == "office"
    empty = await client.post(f"{BASE}/projects/{pid}/brief/extract", headers=h, json={})
    assert empty.status_code == 422


async def test_extraction_is_for_the_erp_not_for_link_tokens(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    code = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers={**h, **LINK})
    tok = (
        await client.post(
            f"{BASE}/link/exchange", json={"code": code.json()["code"], "client": {"name": "t"}}, headers=LINK
        )
    ).json()["token"]
    r = await client.post(
        f"{BASE}/projects/{pid}/brief/extract",
        headers={"Authorization": f"Bearer {tok}"},
        json={"text": "Hotel mit 3 Geschossen"},
    )
    assert r.status_code == 403
    nobody = await client.post(f"{BASE}/projects/{pid}/brief/extract", json={"text": "x"})
    assert nobody.status_code in (401, 403)


async def test_agent_tool_returns_proposals_and_respects_access(client, tmp_path):
    from app.modules.ai_agents.base import global_tool_registry
    from app.modules.design.brief_api import register_tool

    register_tool()
    tool = global_tool_registry.get("propose_design_brief")
    assert tool is not None
    uid, _ = await make_user(client)
    pid = await make_project(uid)
    stranger, _ = await make_user(client)
    ok = await tool.run(
        {"project_id": str(pid), "text": "Schule mit 3 Geschossen", "__agent_context__": {"user_id": str(uid)}}
    )
    assert ok["status"] == "proposal" and ok["brief"]["massing"]["floors_above"] == 3
    assert ok["brief"]["provenance"]["/massing/floors_above"]["status"] == "proposed"
    denied = await tool.run({"project_id": str(pid), "text": "x", "__agent_context__": {"user_id": str(stranger)}})
    assert denied["error"] == "unavailable"
    assert (await tool.run({"project_id": str(pid), "text": "x"}))["error"] == "unavailable"
    assert FIX.exists()
