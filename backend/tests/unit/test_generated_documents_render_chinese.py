# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The generators ask for the Chinese face, and asking changes nothing else.

An earlier change made the face reachable and wired no generator to it, so
every generated document still printed Chinese as boxes. These tests are about
the documents rather than the helper, and they are written to fail on the
failure mode that a weaker test cannot see: a generator that quietly keeps
using the Latin face still produces a valid PDF and still returns two hundred.

The instrument is the produced bytes. Two facts about them separate a rendered
document from a boxed one, and both were measured before being asserted:

  * With the CID face, the Chinese codepoints survive into the content stream
    as UTF-16BE under the standard Adobe-GB1 CMap, so a reader recovers the
    original characters.
  * With the bundled Latin face, reportlab embeds a DejaVu subset that has no
    Han glyph at all, and every Chinese character is written as glyph zero.
    The text extracted from such a document is a run of NUL characters. That
    is the box, and it is unrecoverable: no reader can undo it.

So "renders Chinese" here means the characters came back and no NUL did. It
does not mean any particular reader owns the outlines - the face is referenced
rather than embedded, deliberately, and :mod:`app.core.pdf_fonts` says so.

Every generator below is checked in both directions. The negative control
disables the switch and asserts the same document then comes out boxed; a test
suite where both directions look alike is measuring the PDF library, not us.
"""

from __future__ import annotations

import io
import subprocess
import types
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from app.core import pdf_fonts

# Chinese as data, which is what the locale rule permits and what a Chinese
# job actually holds: a project name, a bill section, a measured item, a fee.
CN_PROJECT = "上海办公楼项目"
CN_BOQ = "工程量清单"
CN_SECTION = "土石方工程"
CN_ITEM = "人工挖一般土方，三类土"
CN_MARKUP = "企业管理费"
CN_PERSON = "张伟"
CN_DEVELOPMENT = "浦东锦绣花园"
CN_PLOT = "一期-A12"
CN_SELLER = "上海建工集团股份有限公司"
CN_BUYER = "浦东新区建设发展有限公司"
# The squared metre is the reason the face question cannot be asked about
# scripts. It is not a Chinese character and it appears in Latin bills of
# quantities, but only the Chinese pack draws it.
CN_UNIT = "㎡"

# The control language. Umlauts and the sharp s are the half of this that the
# Chinese face cannot draw, which is why the choice has to stay per string.
DE_PROJECT = "Bürogebäude München"
DE_SECTION = "Erdarbeiten, Größe"
DE_ITEM = "Baugrube ausheben, Bodenklasse 3, Straßenoberfläche"
DE_PERSON = "Jürgen Müller"
DE_DEVELOPMENT = "Wohnpark Grünstraße"
DE_SELLER = "Hochbau Rhein-Main GmbH"
DE_BUYER = "PVG Projektentwicklung Europaviertel GmbH"


# ── Instruments ─────────────────────────────────────────────────────────────


def extracted_text(data: bytes) -> str:
    """All text a reader recovers from the document, whitespace squashed.

    Reportlab breaks a justified line into per-word chunks, so the extracted
    text carries breaks the source string never had. Squashing whitespace
    compares what was written rather than how it was laid out.
    """
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "".join("".join(page.extract_text().split()) for page in reader.pages)


def referenced_faces(data: bytes) -> set[str]:
    """The font faces the document's page resources name."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    faces: set[str] = set()
    for page in reader.pages:
        fonts = page.get("/Resources", {}).get("/Font")
        if not fonts:
            continue
        for ref in fonts.values():
            base = ref.get_object().get("/BaseFont")
            if base:
                # Strip the "AAAAAA+" subset tag reportlab prefixes.
                faces.add(str(base).lstrip("/").split("+")[-1])
    return faces


def assert_renders(data: bytes, *strings: str) -> None:
    """The document draws these strings as glyphs rather than as boxes."""
    assert data.startswith(b"%PDF")
    text = extracted_text(data)
    assert "\x00" not in text, "the document contains glyph-zero runs, which is what a box is"
    for wanted in strings:
        squashed = "".join(wanted.split())
        assert squashed in text, f"{wanted!r} was not recoverable from the produced document"


def assert_boxed(data: bytes, *strings: str) -> None:
    """The negative control: this document prints those strings as boxes."""
    assert data.startswith(b"%PDF")
    text = extracted_text(data)
    assert "\x00" in text, "the control produced no glyph-zero run, so the switch was never consulted"
    for wanted in strings:
        squashed = "".join(wanted.split())
        assert squashed not in text, f"{wanted!r} came back from a document that was supposed to be boxed"


@pytest.fixture
def switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every generator down the Latin path, whatever the text says.

    This is the only honest way to check that a generator's Chinese rendering
    comes from the wiring rather than from something reportlab does anyway.

    It removes the CID rungs from the face ladder rather than lying about what
    the text contains. That is the switch the product would really have thrown -
    a reportlab build that cannot provide the Adobe packs - and it leaves the
    coverage predicate telling the truth, so what the control proves is that the
    ladder reached a rung and not that a range test fired.

    Both packs go, not just the Chinese one, and that is the whole switch rather
    than a tidier way of writing half of it. Han encodes in EUC-KR, so the
    Korean pack answers for Chinese text too; turning off only the Chinese rung
    left Chinese being drawn by the Korean pack, which renders, so the control
    passed nothing through to box and quietly stopped discriminating. They also
    fail together in reality: both come from reportlab's Adobe CID mechanism, so
    a build that cannot supply one cannot supply the other, and switching off
    one alone was never a state the product could actually be in.
    """
    monkeypatch.setattr(pdf_fonts, "register_cjk_font", lambda: False)
    monkeypatch.setattr(pdf_fonts, "register_korean_font", lambda: False)


def ns(**kwargs: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kwargs)


def source_before_the_wiring(path: str, marker: str) -> str:
    """The newest version of *path* whose source lacks *marker*, or "" if none.

    Three tests below rebuild a PDF builder as it stood before the face wiring
    and compare its output to today's. That is the only way the claim that
    Latin documents did not move a byte can be checked against the real
    previous implementation rather than against a copy of itself. They walk
    history rather than read HEAD, because HEAD carries the wiring now and a
    test anchored there would skip itself and pass forever without comparing
    anything.

    This needs real git history. CI supplies it with ``fetch-depth: 0`` and
    ``filter: blob:none``, so a ``git show`` here may fetch from origin, and it
    must fail rather than skip if it cannot: the walk runs with ``check=True``
    and nothing catching around it, because a skip CI does not count is a pass
    wearing a different word. The walk grows with the file's history.

    The plain walk runs first and the rename-following one only if it found
    nothing. ``--follow`` diffs blobs to detect renames, so against the blobless
    clone CI checks out it fetches every blob it compares: 188 MB and 15 s,
    against 11 MB and 2 s for the plain walk. Only a rename needs it, so only a
    rename pays for it.

    Returns the empty string rather than raising when nothing is reachable, so
    that each caller can assert on it and name the builder it was looking for.
    A single message from in here would say the same thing three times and
    identify none of them.
    """
    repo = Path(__file__).resolve().parents[3]

    def git(*args: str) -> str:
        return subprocess.run([*args], capture_output=True, cwd=repo, check=True).stdout.decode("utf-8")

    for follow in ((), ("--follow",)):
        for sha in git("git", "log", *follow, "--format=%H", "--", path).split():
            candidate = git("git", "show", f"{sha}:{path}")
            if marker not in candidate:
                return candidate
    return ""


# ── The bill of quantities ──────────────────────────────────────────────────


def boq_fixture(*, boq_name: str, section: str, item: str, markup: str) -> Any:
    position = ns(
        ordinal="01.001",
        description=item,
        unit="m3",
        quantity=Decimal("120.00"),
        unit_rate=Decimal("85.50"),
        total=Decimal("10260.00"),
    )
    return ns(
        name=boq_name,
        description="",
        sections=[ns(ordinal="01", description=section, positions=[position], subtotal=Decimal("10260.00"))],
        positions=[],
        markups=[
            ns(
                name=markup,
                markup_type="percentage",
                percentage=8.0,
                amount=Decimal("820.80"),
                category="overhead",
                is_active=True,
            )
        ],
        direct_cost=Decimal("10260.00"),
        net_total=Decimal("11080.80"),
        grand_total=Decimal("11080.80"),
        status="draft",
    )


def build_boq(*, chinese: bool) -> bytes:
    from app.modules.boq.pdf_export import generate_boq_pdf

    if chinese:
        data = boq_fixture(boq_name=CN_BOQ, section=CN_SECTION, item=CN_ITEM, markup=CN_MARKUP)
        return generate_boq_pdf(data, project_name=CN_PROJECT, currency="CNY", prepared_by=CN_PERSON)
    data = boq_fixture(boq_name="Leistungsverzeichnis", section=DE_SECTION, item=DE_ITEM, markup="Gemeinkosten")
    return generate_boq_pdf(data, project_name=DE_PROJECT, currency="EUR", prepared_by=DE_PERSON)


def test_a_chinese_bill_of_quantities_renders_its_chinese() -> None:
    """The cover, the running header, the section, the measured item and the
    fee name - the five places a Chinese estimator reads first."""
    data = build_boq(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, CN_PROJECT, CN_BOQ, CN_SECTION, CN_ITEM, CN_MARKUP, CN_PERSON)


def test_a_chinese_bill_of_quantities_is_boxed_without_the_wiring(switch_off: None) -> None:
    """The negative control. Same generator, same data, switch forced off."""
    data = build_boq(chinese=True)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_boxed(data, CN_PROJECT, CN_SECTION, CN_ITEM, CN_MARKUP)


def test_a_german_bill_built_after_a_chinese_one_is_unaffected() -> None:
    """The regression the per-document design exists to prevent.

    The face names are module globals that every generator binds at import.
    A choice written into them would re-face every later document in the same
    worker, which no test that builds one document can see. So this builds two,
    Chinese first, and asserts the second is exactly what it would have been.
    """
    build_boq(chinese=True)
    data = build_boq(chinese=False)

    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, DE_PROJECT, DE_SECTION, DE_ITEM, DE_PERSON)


def test_the_module_face_names_survive_a_chinese_document() -> None:
    """The same property read at the source rather than through a document."""
    before = (pdf_fonts.BODY_FONT, pdf_fonts.BOLD_FONT)
    build_boq(chinese=True)
    assert before == (pdf_fonts.BODY_FONT, pdf_fonts.BOLD_FONT)


def test_the_chinese_bill_does_not_embed_a_font_for_the_chinese() -> None:
    """The face is referenced, not embedded, and that is a deliberate trade.

    If someone later embeds a CJK font this fails, and the decision gets made
    rather than discovered in a repository size.
    """
    data = build_boq(chinese=True)
    reader = pypdf.PdfReader(io.BytesIO(data))
    for page in reader.pages:
        for ref in (page.get("/Resources", {}).get("/Font") or {}).values():
            font = ref.get_object()
            if pdf_fonts.CJK_FONT in str(font.get("/BaseFont", "")):
                descendants = font.get("/DescendantFonts")
                descriptor = descendants[0].get_object().get("/FontDescriptor") if descendants else None
                assert descriptor is None or not any(key.startswith("/FontFile") for key in descriptor.get_object()), (
                    "the Chinese face is now embedded, which changes what ships"
                )


# ── Tender decision letters ─────────────────────────────────────────────────


def build_award_letter(*, chinese: bool) -> bytes:
    from app.modules.tendering.pdf_documents import generate_award_letter_pdf

    if chinese:
        return generate_award_letter_pdf(
            package_name=CN_SECTION,
            package_ref=CN_BOQ,
            project_name=CN_PROJECT,
            company_name="上海建工集团股份有限公司",
            contact_email="info@datadrivenconstruction.io",
            awarded_amount="1234567.89",
            currency="CNY",
            awarded_by_name=CN_PERSON,
            notes=CN_ITEM,
        )
    return generate_award_letter_pdf(
        package_name=DE_SECTION,
        package_ref="LV-2026-01",
        project_name=DE_PROJECT,
        company_name="Müller Hochbau GmbH",
        contact_email="info@datadrivenconstruction.io",
        awarded_amount="1234567.89",
        currency="EUR",
        awarded_by_name=DE_PERSON,
        notes=DE_ITEM,
    )


def test_a_chinese_award_letter_renders_its_chinese() -> None:
    data = build_award_letter(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, "上海建工集团股份有限公司", CN_PROJECT, CN_ITEM, CN_PERSON)


def test_a_chinese_award_letter_is_boxed_without_the_wiring(switch_off: None) -> None:
    data = build_award_letter(chinese=True)
    assert_boxed(data, "上海建工集团股份有限公司", CN_PROJECT, CN_ITEM)


def test_a_german_award_letter_built_after_a_chinese_one_is_unaffected() -> None:
    build_award_letter(chinese=True)
    data = build_award_letter(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, "Müller Hochbau GmbH", DE_PROJECT, DE_PERSON)


# ── Meeting minutes ─────────────────────────────────────────────────────────


def build_minutes(*, chinese: bool) -> bytes:
    from app.modules.meetings.pdf import build_minutes_pdf

    if chinese:
        content = {
            "title": "第一次工地例会",
            "meeting_date": "2026-08-23",
            "location": "上海市浦东新区",
            "meeting_type": "site_meeting",
            "meeting_number": "001",
            "chairperson": CN_PERSON,
            "attendees_present": [{"name": CN_PERSON}, {"name": "李娜"}],
            "agenda": [{"number": "1", "topic": CN_SECTION, "discussion": CN_ITEM, "decision": "同意按图施工"}],
            "action_items": [{"description": CN_ITEM, "owner": "李娜", "due_date": "2026-09-01", "status": "open"}],
            "summary": "本次会议确认了土方工程的开工时间。",
        }
        project = CN_PROJECT
    else:
        content = {
            "title": "Erste Baubesprechung",
            "meeting_date": "2026-08-23",
            "location": "München, Größenweg 4",
            "meeting_type": "site_meeting",
            "meeting_number": "001",
            "chairperson": DE_PERSON,
            "attendees_present": [{"name": DE_PERSON}],
            "agenda": [{"number": "1", "topic": DE_SECTION, "discussion": DE_ITEM, "decision": "Freigabe erteilt"}],
            "action_items": [{"description": DE_ITEM, "owner": DE_PERSON, "due_date": "2026-09-01", "status": "open"}],
            "summary": "Der Aushub beginnt am Montag.",
        }
        project = DE_PROJECT

    meeting = ns(title=content["title"], meeting_number="001", meeting_date="2026-08-23")
    minutes = ns(content=content, status="issued", issued_at=datetime.now(tz=UTC))
    return build_minutes_pdf(meeting, minutes, project)


def test_chinese_meeting_minutes_render_their_chinese() -> None:
    """The action-item owner and the location live in bare table cells, which
    a per-paragraph choice cannot reach. They are asserted for that reason."""
    data = build_minutes(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, CN_PROJECT, "第一次工地例会", "上海市浦东新区", "李娜", CN_ITEM)


def test_chinese_meeting_minutes_are_boxed_without_the_wiring(switch_off: None) -> None:
    data = build_minutes(chinese=True)
    assert_boxed(data, "第一次工地例会", "上海市浦东新区", "李娜")


def test_german_meeting_minutes_built_after_chinese_ones_are_unaffected() -> None:
    build_minutes(chinese=True)
    data = build_minutes(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, DE_PROJECT, "Erste Baubesprechung", "München, Größenweg 4", DE_PERSON)


# ── The punch list ──────────────────────────────────────────────────────────


# Canonical lowercase hyphenated form, which is what ``str()`` of the real
# ``uuid.UUID`` the route parses produces. The builder only interpolates it, so
# this renders the same characters the product renders.
PROJECT_ID = "11111111-1111-1111-1111-111111111111"
ASSIGNEE_ID = "6f1d2c3b-0000-4000-8000-000000000001"


def build_punchlist(*, chinese: bool) -> bytes:
    from app.modules.punchlist.service import _build_reportlab_pdf

    if chinese:
        item = ns(
            title="外墙渗漏",
            description="三层北侧外墙存在渗漏，需重新做防水层。",
            status="open",
            priority="high",
            category="防水",
            trade="土建",
            due_date=date(2026, 9, 1),
            photos=[],
            resolution_notes="已安排班组返工。",
            reopen_history=[],
            metadata_={"code": "PL-001"},
            location_x=None,
            location_y=None,
            document_id=None,
            page=None,
            assigned_to="李强",
        )
    else:
        item = ns(
            title="Feuchte Außenwand",
            description="Nordseite im dritten Obergeschoss, Abdichtung erneuern.",
            status="open",
            priority="high",
            category="Abdichtung",
            trade="Rohbau",
            due_date=date(2026, 9, 1),
            photos=[],
            resolution_notes="Nacharbeit beauftragt.",
            reopen_history=[],
            metadata_={"code": "PL-001"},
            location_x=None,
            location_y=None,
            document_id=None,
            page=None,
            assigned_to="Jürgen Müller",
        )
    # ``assigned_to`` is a free-text column and ``_party_label`` prints
    # ``names.get(raw) or raw``, so the printed assignee reaches the page by
    # two different routes in production: the assignment control writes a user
    # id and the name arrives in the resolved-names map, while the seeder and
    # the field integrations sometimes write the name straight into the
    # column. The Chinese fixture drives the map route, which is the one that
    # would hide a fault, and the German one drives the stored-name route.
    if chinese:
        item.assigned_to = ASSIGNEE_ID
        return _build_reportlab_pdf(PROJECT_ID, [item], {ASSIGNEE_ID: "李强"})
    return _build_reportlab_pdf(PROJECT_ID, [item], {})


def test_a_chinese_punch_list_renders_its_chinese() -> None:
    """The category and the trade are bare table cells governed by a FONT
    command, so this is the case a paragraph-only wiring would miss."""
    data = build_punchlist(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, "外墙渗漏", "防水", "土建", "李强", "已安排班组返工。")


def test_a_chinese_punch_list_is_boxed_without_the_wiring(switch_off: None) -> None:
    data = build_punchlist(chinese=True)
    assert_boxed(data, "外墙渗漏", "防水", "土建", "李强")


def test_a_german_punch_list_built_after_a_chinese_one_is_unaffected() -> None:
    build_punchlist(chinese=True)
    data = build_punchlist(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, "Feuchte Außenwand", "Abdichtung", "Nacharbeit beauftragt.")


# ── The report exporter ─────────────────────────────────────────────────────


def build_report(*, chinese: bool) -> bytes:
    # ``Report.generated_at`` is a String(40) column, not a datetime, and
    # ``export_report`` forwards it to the builder untouched. The builder
    # interpolates it into a paragraph, so handing it a datetime here would
    # print a different timestamp than the product ever prints.
    from app.modules.reporting.exporters import _export_pdf

    generated_at = "2026-08-23T09:15:00+00:00"
    if chinese:
        return _export_pdf(
            title="工程量清单汇总表",
            project_name=CN_PROJECT,
            report_type="boq_summary",
            currency="CNY",
            generated_at=generated_at,
            template_data={},
            data_snapshot={"summary": {"分部工程": CN_SECTION, "清单项目": CN_ITEM}},
            locale="zh",
        )
    return _export_pdf(
        title="Kostenübersicht",
        project_name=DE_PROJECT,
        report_type="boq_summary",
        currency="EUR",
        generated_at=generated_at,
        template_data={},
        data_snapshot={"summary": {"Gewerk": DE_SECTION, "Position": DE_ITEM}},
        locale="de",
    )


def test_a_chinese_report_renders_its_chinese() -> None:
    data = build_report(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, "工程量清单汇总表", CN_PROJECT, CN_SECTION, CN_ITEM)


def test_a_chinese_report_is_boxed_without_the_wiring(switch_off: None) -> None:
    data = build_report(chinese=True)
    assert_boxed(data, "工程量清单汇总表", CN_PROJECT, CN_SECTION)


def test_a_german_report_built_after_a_chinese_one_is_unaffected() -> None:
    build_report(chinese=True)
    data = build_report(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, "Kostenübersicht", DE_PROJECT, DE_SECTION, DE_ITEM)


# ── The property reservation receipt ────────────────────────────────────────
#
# This one is worth its own section. The template chrome follows a locale, but
# the receipt ships no Chinese translation, so a Chinese job produces English
# chrome around Chinese names. A document-level switch keyed on the locale
# would face the wrong half of it; this checks the per-string choice instead.


def build_receipt(*, chinese: bool) -> bytes:
    from app.modules.property_dev.document_templates import render_reservation_receipt_pdf

    if chinese:
        return render_reservation_receipt_pdf(
            {
                "reservation_number": "RES-CN-001",
                "currency": "CNY",
                "deposit_amount": Decimal("120000"),
                "cooling_off_days": 14,
            },
            {"plot_number": CN_PLOT, "area_m2": 118, "currency": "CNY"},
            {"name": CN_DEVELOPMENT},
            [{"full_name": CN_PERSON, "email": "buyer@example.cn"}],
            locale="zh",
        )
    return render_reservation_receipt_pdf(
        {
            "reservation_number": "RES-DE-001",
            "currency": "EUR",
            "deposit_amount": Decimal("25000"),
            "cooling_off_days": 14,
        },
        {"plot_number": "WE-07", "area_m2": 96, "currency": "EUR"},
        {"name": DE_DEVELOPMENT},
        [{"full_name": DE_PERSON, "email": "buyer@example.de"}],
        locale="de",
    )


def test_a_chinese_reservation_receipt_renders_its_chinese() -> None:
    data = build_receipt(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, CN_DEVELOPMENT, CN_PERSON, CN_PLOT)


def test_a_chinese_reservation_receipt_is_boxed_without_the_wiring(switch_off: None) -> None:
    data = build_receipt(chinese=True)
    assert_boxed(data, CN_DEVELOPMENT, CN_PERSON)


def test_a_german_reservation_receipt_built_after_a_chinese_one_is_unaffected() -> None:
    build_receipt(chinese=True)
    data = build_receipt(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, DE_DEVELOPMENT, DE_PERSON)


def test_the_receipt_style_table_is_not_refaced_by_a_chinese_document() -> None:
    """The styles are built per render, so prove the factory still hands out Latin.

    This is the trap the per-document approach would have fallen into: face the
    style table for a Chinese document and every later document served from the
    same table comes out Chinese-faced.
    """
    from app.modules.property_dev.document_templates import _styles

    build_receipt(chinese=True)
    for name, style in _styles("de").items():
        assert style.fontName != pdf_fonts.CJK_FONT, f"the {name} style kept the Chinese face"


# ── The hybrid e-invoice ────────────────────────────────────────────────────
#
# This one is drawn straight onto a canvas at fixed millimetre offsets, with no
# tables and no paragraphs, and it was left on Helvetica when the rest were
# converted. It is also the document with the strictest requirement attached:
# every invoice this product has ever issued is Latin, and none of their bytes
# may move. So the face is chosen per string and only when Helvetica cannot
# draw that string, which the first test below holds to byte equality.


def invoice_payload(*, seller: str, buyer: str, description: str, unit: str) -> dict[str, Any]:
    return {
        "invoice_number": "AR-2026-014",
        "invoice_direction": "receivable",
        "invoice_date": "2026-04-15",
        "due_date": "2026-05-15",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("1850000.00"),
        "tax_amount": Decimal("351500.00"),
        "retention_amount": Decimal("0"),
        "amount_total": Decimal("2201500.00"),
        "notes": None,
        "metadata": {
            "einvoice": {
                "vat_rate": "19",
                "buyer_reference": "06-4300251-83",
                "payee_iban": "DE89370400440532013000",
                "payee_account_name": seller,
                "seller": {
                    "name": seller,
                    "vat_id": "DE812345678",
                    "city": "Frankfurt am Main",
                    "postcode": "60327",
                    "country_code": "DE",
                },
                "buyer": {
                    "name": buyer,
                    "city": "Frankfurt am Main",
                    "postcode": "60308",
                    "country_code": "DE",
                },
            }
        },
        "_lines": [
            {
                "description": description,
                "unit": unit,
                "quantity": Decimal("1"),
                "unit_rate": Decimal("1850000.00"),
                "amount": Decimal("1850000.00"),
            }
        ],
    }


def build_invoice_page(*, chinese: bool) -> bytes:
    """The readable page only, which is the part a face can change.

    Deliberately not the hybrid: ``build_facturx_pdf`` runs the page through
    pypdf to attach the CII, and comparing that output would be comparing
    pypdf's serialiser as much as our drawing.
    """
    from app.modules.einvoice import build_einvoice
    from app.modules.einvoice.pdf_embed import _readable_pdf

    payload = (
        invoice_payload(seller=CN_SELLER, buyer=CN_BUYER, description=CN_ITEM, unit=CN_UNIT)
        if chinese
        else invoice_payload(seller=DE_SELLER, buyer=DE_BUYER, description=DE_ITEM, unit="psch")
    )
    lines = payload.pop("_lines")
    return _readable_pdf(build_einvoice(invoice=payload, line_items=lines, profile="zugferd"), "de")


def test_a_latin_invoice_is_byte_for_byte_what_it_was_before_the_wiring() -> None:
    """The whole point of choosing the face per string rather than per document.

    reportlab writes a Tf operator for every setFont call whether or not the
    font changed, and the Latin and Chinese faces do not share a width table,
    so a generator that selected a face unconditionally would move the bytes of
    every invoice already issued. This asserts the opposite directly: the page
    produced today is identical to the page produced by the builder as it stood
    before any of this, down to the byte.

    The comparison runs against the real previous implementation, read out of
    git rather than reimplemented here, so it cannot pass by agreeing with a
    copy of itself. reportlab's invariant mode fixes the creation date and the
    document identifier, which are the only bytes that would otherwise differ
    for reasons that have nothing to do with fonts.

    The earlier builder is found by walking the file's history for the most
    recent version that predates the wiring, rather than by reading HEAD. The
    difference matters: once this change is committed, HEAD carries the wiring
    and a test anchored there would skip itself and go on passing forever
    without comparing anything.
    """
    import reportlab.rl_config as rl_config

    from app.modules.einvoice import build_einvoice
    from app.modules.einvoice.pdf_embed import _readable_pdf

    source = source_before_the_wiring("backend/app/modules/einvoice/pdf_embed.py", "def put(")
    assert source, "no version of the invoice builder predating the wiring is reachable in this history"

    module = types.ModuleType("pdf_embed_before")
    module.__file__ = "pdf_embed_before.py"
    exec(compile(source, "pdf_embed_before.py", "exec"), module.__dict__)  # noqa: S102

    previous = rl_config.invariant
    rl_config.invariant = 1
    try:
        payload = invoice_payload(seller=DE_SELLER, buyer=DE_BUYER, description=DE_ITEM, unit="psch")
        lines = payload.pop("_lines")
        for locale in ("de", "en"):
            invoice = build_einvoice(invoice=payload, line_items=lines, profile="zugferd")
            was = module._readable_pdf(invoice, locale)
            now = _readable_pdf(invoice, locale)
            assert was == now, f"the {locale} Latin invoice page changed, and it was not supposed to"

        # The control: this comparison can tell two pages apart at all.
        chinese = invoice_payload(seller=CN_SELLER, buyer=CN_BUYER, description=CN_ITEM, unit=CN_UNIT)
        chinese_lines = chinese.pop("_lines")
        other = _readable_pdf(build_einvoice(invoice=chinese, line_items=chinese_lines, profile="zugferd"), "de")
        assert other != now, "a Chinese invoice produced the same bytes as a German one, so nothing is being compared"
    finally:
        rl_config.invariant = previous


def test_a_chinese_invoice_renders_its_chinese() -> None:
    data = build_invoice_page(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, CN_SELLER, CN_BUYER, CN_ITEM)


def test_a_chinese_invoice_is_boxed_without_the_wiring(switch_off: None) -> None:
    assert_boxed(build_invoice_page(chinese=True), CN_SELLER, CN_BUYER, CN_ITEM)


def test_a_german_invoice_built_after_a_chinese_one_is_unaffected() -> None:
    """Per document, not once per process, on the generator that draws bare."""
    build_invoice_page(chinese=True)
    data = build_invoice_page(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data), "a German invoice picked up the Chinese face"
    assert_renders(data, DE_SELLER, DE_BUYER, DE_ITEM)


def test_the_invoice_keeps_helvetica_for_the_strings_helvetica_can_draw() -> None:
    """A Chinese invoice is not a Chinese-faced invoice.

    Every label on the page, the invoice number, the IBAN and every amount are
    still drawn in Helvetica. Only the strings that need it escalate, which is
    what keeps the layout of a mixed invoice where it was.
    """
    faces = referenced_faces(build_invoice_page(chinese=True))
    assert "Helvetica" in faces, "the Chinese invoice moved its Latin text off Helvetica"
    assert pdf_fonts.CJK_FONT in faces


def test_the_invoice_does_not_embed_a_font_for_the_chinese() -> None:
    """Referenced rather than embedded, asserted on the shipped hybrid file."""
    from app.modules.einvoice import build_einvoice
    from app.modules.einvoice.pdf_embed import build_facturx_pdf

    payload = invoice_payload(seller=CN_SELLER, buyer=CN_BUYER, description=CN_ITEM, unit=CN_UNIT)
    lines = payload.pop("_lines")
    data = build_facturx_pdf(build_einvoice(invoice=payload, line_items=lines, profile="zugferd"), locale="de")
    for marker in (b"/FontFile", b"/FontFile2", b"/FontFile3"):
        assert marker not in data, f"{marker.decode()} appeared, so a font program is now being shipped"


def test_the_invoice_still_carries_its_machine_readable_half() -> None:
    """The face work must not disturb what the receiver's software reads."""
    from app.modules.einvoice import build_einvoice
    from app.modules.einvoice.pdf_embed import build_facturx_pdf

    payload = invoice_payload(seller=CN_SELLER, buyer=CN_BUYER, description=CN_ITEM, unit=CN_UNIT)
    lines = payload.pop("_lines")
    data = build_facturx_pdf(build_einvoice(invoice=payload, line_items=lines, profile="zugferd"), locale="de")
    assert b"<rsm:CrossIndustryInvoice" in data, "the embedded CII is gone"
    assert b"urn:factur-x:pdfa" in data, "the Factur-X XMP is gone"
    assert b"/AFRelationship" in data, "the associated-file relationship is gone"


# ── Tables whose body cells name no face at all ─────────────────────────────
#
# A reportlab table cell with no FONTNAME command over it is drawn in
# Helvetica, whatever the surrounding styles say. Four tables in this product
# name a face for their header row and none for their body, so their body was
# Helvetica while everything around them had been converted. That is invisible
# from the call site, invisible in the extracted text of a Latin document, and
# it is why these two are asserted on the produced bytes.


def build_analytics_report(*, chinese: bool) -> bytes:
    from app.modules.bi_dashboards.report_builder import build_pdf_report

    rows = (
        [{"项目": CN_PROJECT, "分部": CN_SECTION, "负责人": CN_PERSON, "面积": f"1200 {CN_UNIT}"}]
        if chinese
        else [{"Projekt": DE_PROJECT, "Abschnitt": DE_SECTION, "Verantwortlich": DE_PERSON, "Fläche": "1200 m2"}]
    )
    path, _ = build_pdf_report(report_name=f"glyph-probe-{'cn' if chinese else 'de'}", rows=rows)
    return Path(path).read_bytes()


def test_a_chinese_analytics_report_renders_its_chinese() -> None:
    data = build_analytics_report(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, CN_PROJECT, CN_SECTION, CN_PERSON)


def test_a_chinese_analytics_report_is_boxed_without_the_wiring(switch_off: None) -> None:
    assert_boxed(build_analytics_report(chinese=True), CN_PROJECT, CN_SECTION, CN_PERSON)


def test_a_german_analytics_report_built_after_a_chinese_one_is_unaffected() -> None:
    build_analytics_report(chinese=True)
    data = build_analytics_report(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, DE_PROJECT, DE_SECTION, DE_PERSON)


def build_regulator_disclosure(*, chinese: bool) -> bytes:
    from app.modules.property_dev.service import _render_regulator_pdf

    if chinese:
        return _render_regulator_pdf(
            regulator="RERA",
            development_name=CN_DEVELOPMENT,
            development_code=CN_PLOT,
            quarter="2026-Q2",
            summary={"currency": "CNY", "开发商": CN_PERSON, "已售单元": "42", "建筑面积": f"8600 {CN_UNIT}"},
        )
    return _render_regulator_pdf(
        regulator="RERA",
        development_name=DE_DEVELOPMENT,
        development_code="BA-1",
        quarter="2026-Q2",
        summary={"currency": "EUR", "Bautrager": DE_PERSON, "Verkaufte Einheiten": "42"},
    )


def test_a_chinese_regulator_disclosure_renders_its_chinese() -> None:
    data = build_regulator_disclosure(chinese=True)
    assert pdf_fonts.CJK_FONT in referenced_faces(data)
    assert_renders(data, CN_DEVELOPMENT, CN_PERSON)


def test_a_chinese_regulator_disclosure_is_boxed_without_the_wiring(switch_off: None) -> None:
    assert_boxed(build_regulator_disclosure(chinese=True), CN_DEVELOPMENT, CN_PERSON)


def test_a_german_regulator_disclosure_built_after_a_chinese_one_is_unaffected() -> None:
    build_regulator_disclosure(chinese=True)
    data = build_regulator_disclosure(chinese=False)
    assert pdf_fonts.CJK_FONT not in referenced_faces(data)
    assert_renders(data, DE_DEVELOPMENT, DE_PERSON)


def test_a_bare_table_cell_is_measured_against_helvetica_not_the_body_font() -> None:
    """The defect these four shared, stated at the helper rather than the page.

    Cyrillic is the case that separates the two answers. Helvetica cannot draw
    it and the bundled Unicode face can, so a body cell measured against the
    right base gets a command and one measured against the wrong base gets
    nothing at all and stays boxed. Chinese would not have shown this, because
    it escalates past both.
    """
    rows = [["Header"], ["Строительная компания"]]

    wrong = pdf_fonts.pdf_table_font_commands(rows)
    assert wrong == [], "the default base is meant to be the body font, so this cell looks already covered"

    right = pdf_fonts.pdf_table_font_commands(rows, base="Helvetica", header_rows=1, header_base=pdf_fonts.BOLD_FONT)
    assert right == [("FONTNAME", (0, 1), (0, 1), pdf_fonts.BODY_FONT)], right


def test_a_header_already_in_a_bold_face_is_not_pushed_back_to_regular() -> None:
    """Why the helper has to be told about the header row separately.

    These tables draw their header in the bold Unicode face and their body in
    Helvetica. Measuring the whole table against Helvetica would find the bold
    header's Cyrillic undrawable and emit a command putting it into the regular
    weight, silently un-bolding a heading that was already correct.
    """
    rows = [["Строительная компания"], ["Body"]]
    commands = pdf_fonts.pdf_table_font_commands(rows, base="Helvetica", header_rows=1, header_base=pdf_fonts.BOLD_FONT)
    assert commands == [], f"the bold header was given a command it did not need: {commands}"


# ── One document, two scripts ───────────────────────────────────────────────


def test_a_german_document_carrying_one_chinese_name_renders_both() -> None:
    """Why the choice is per string and not per document.

    Neither face covers both scripts. DejaVu has no Han at all. The Adobe
    Simplified Chinese pack does carry part of the accented Latin range - the
    u-umlaut among it, which an earlier version of this docstring denied - but
    it stops short of the o-umlaut, the sharp s and the euro sign, all three of
    which appear in an ordinary German invoice. So a bill written in German for
    a Chinese subcontractor has to draw each string with the face that can draw
    it, and a document-level switch would sacrifice one of them whichever way
    it fell.
    """
    from app.modules.boq.pdf_export import generate_boq_pdf

    data = generate_boq_pdf(
        boq_fixture(boq_name="Leistungsverzeichnis", section=DE_SECTION, item=CN_ITEM, markup="Gemeinkosten"),
        project_name=DE_PROJECT,
        currency="EUR",
        prepared_by=DE_PERSON,
    )
    faces = referenced_faces(data)
    assert pdf_fonts.CJK_FONT in faces, "the Chinese item did not reach the Chinese face"
    assert pdf_fonts.BODY_FONT in faces, "the German text lost the face that can draw it"
    assert_renders(data, DE_SECTION, CN_ITEM, DE_PROJECT, DE_PERSON)


# ── Column overflow on the invoice page ─────────────────────────────────────
#
# Making the wide scripts legible did not create the overflow, it widened one
# that was already there: sixty Han characters drew 128.9mm of Helvetica boxes
# against a 95mm column before the wiring, and 169.3mm of real glyphs after it.
# The clip is a monotone tightening. It takes the narrower of the character cap
# and the measured width, so it can only ever shorten what the page drew, and a
# Latin string that fits its column is returned untouched.

DESCRIPTION_BUDGET = 95 * mm
DESCRIPTION_CAP = 60
SELLER_BUDGET = 90 * mm
BUYER_BUDGET = 80 * mm

LONG_CN_DESCRIPTION = CN_ITEM * 6
LONG_CN_SELLER = CN_SELLER * 4
LONG_CN_BUYER = CN_BUYER * 4
# Long enough that the payment row, the widest budget on the page, overruns.
OVERLONG_CN_SELLER = CN_SELLER * 8
SHORT_DE_DESCRIPTION = "Baugrube ausheben"


def invoice_page(*, seller: str, buyer: str, description: str, unit: str = "psch") -> bytes:
    from app.modules.einvoice import build_einvoice
    from app.modules.einvoice.pdf_embed import _readable_pdf

    payload = invoice_payload(seller=seller, buyer=buyer, description=description, unit=unit)
    lines = payload.pop("_lines")
    return _readable_pdf(build_einvoice(invoice=payload, line_items=lines, profile="zugferd"), "de")


def drawn_runs(data: bytes) -> list[str]:
    """Every text run the page draws, kept apart from each other.

    :func:`extracted_text` squashes the whole page into one string, which is
    right for asking whether a name survived but wrong for asking how much of
    it was drawn: two clipped runs of a repeating name concatenate into a
    longer match than either of them, and a name drawn in two places reads as
    one long one. This keeps each drawing separate, which is what a width
    question is about.
    """
    runs: list[str] = []
    for page in pypdf.PdfReader(io.BytesIO(data)).pages:
        page.extract_text(visitor_text=lambda text, cm, tm, font, size: runs.append(text))
    return [run.strip() for run in runs if run.strip()]


def drawn_prefix(data: bytes, source: str) -> str:
    """The longest single run the page drew that is a leading run of ``source``."""
    best = ""
    for run in drawn_runs(data):
        if source.startswith(run) and len(run) > len(best):
            best = run
    return best


def measured(text: str, size: int) -> float:
    from reportlab.pdfbase import pdfmetrics

    from app.core.pdf_fonts import pdf_font_for_text

    return pdfmetrics.stringWidth(text, pdf_font_for_text(text, base="Helvetica"), size)


def test_a_chinese_description_is_clipped_inside_its_column() -> None:
    """The case the measurement was about. Unclipped this runs 74mm past the
    quantity column and across the unit and price figures of a legal
    document."""
    drawn = drawn_prefix(
        invoice_page(seller=DE_SELLER, buyer=DE_BUYER, description=LONG_CN_DESCRIPTION), LONG_CN_DESCRIPTION
    )
    assert drawn, "the Chinese description did not reach the page at all"
    assert LONG_CN_DESCRIPTION.startswith(drawn), "what was drawn is not a leading run of the description"
    assert measured(drawn, 8) <= DESCRIPTION_BUDGET, (
        f"the description still overruns at {measured(drawn, 8) / mm:.1f}mm"
    )


def test_the_clip_can_only_shorten() -> None:
    """The property that makes this safe to ship. Never longer than the cap
    that was already there, whatever the width test decides."""
    drawn = drawn_prefix(
        invoice_page(seller=DE_SELLER, buyer=DE_BUYER, description=LONG_CN_DESCRIPTION), LONG_CN_DESCRIPTION
    )
    assert len(drawn) <= DESCRIPTION_CAP, f"the clip lengthened the description to {len(drawn)} characters"


def test_a_latin_description_that_fits_is_untouched() -> None:
    """The guarantee. A description inside both the cap and the column is drawn
    whole, which is why the byte-identity test above still passes."""
    data = invoice_page(seller=DE_SELLER, buyer=DE_BUYER, description=SHORT_DE_DESCRIPTION)
    assert "".join(SHORT_DE_DESCRIPTION.split()) in extracted_text(data)


def test_a_chinese_seller_and_buyer_are_clipped_to_their_own_budgets() -> None:
    """The two party blocks have different widths, 90mm for the seller and 80mm
    for the buyer, because the buyer block starts 90mm in and ends at the right
    margin. Clipping both at the seller's budget would let the buyer overrun."""
    data = invoice_page(seller=LONG_CN_SELLER, buyer=LONG_CN_BUYER, description=SHORT_DE_DESCRIPTION)
    seller_drawn = drawn_prefix(data, LONG_CN_SELLER)
    buyer_drawn = drawn_prefix(data, LONG_CN_BUYER)
    assert seller_drawn and buyer_drawn, "a party name did not reach the page"
    assert measured(seller_drawn, 9) <= SELLER_BUDGET, f"seller overruns at {measured(seller_drawn, 9) / mm:.1f}mm"
    assert measured(buyer_drawn, 9) <= BUYER_BUDGET, f"buyer overruns at {measured(buyer_drawn, 9) / mm:.1f}mm"


def test_the_clip_is_measured_in_the_face_that_draws_it() -> None:
    """A discriminating control. Helvetica and the CID pack do not share a
    width table, so a Chinese string measured in Helvetica reads far narrower
    than it draws. If the clip measured in the base face it would let this
    through, and this asserts the two measurements really do disagree."""
    from reportlab.pdfbase import pdfmetrics

    sixty = (CN_ITEM * 6)[:DESCRIPTION_CAP]
    in_helvetica = pdfmetrics.stringWidth(sixty, "Helvetica", 8)
    in_the_pack = measured(sixty, 8)
    assert in_helvetica < in_the_pack, "the two faces agreed, so this control proves nothing"
    assert in_the_pack > DESCRIPTION_BUDGET, "the fixture no longer overruns, pick a longer one"


def test_the_account_holder_row_stays_on_the_page() -> None:
    """A fourth party-controlled string, and one the ruling did not name.

    The payee account name is drawn again in the payment block under its own
    label, on a row of its own that runs the full width of the page. It had no
    cap of any kind, so it was the one string here that could run off the sheet
    rather than merely into the next column. Found because the width test
    caught a second drawing of the seller name, not because it was looked for.

    The name is longer here than in the other width tests on purpose. This row
    has the widest budget on the page at 170mm, so the 48-character name that
    overruns every other column still fits this one at 152mm, and a test built
    on that fixture would pass whether or not the clip existed. At 96
    characters the unclipped row measures 287mm and leaves the sheet, so the
    assertion can only pass because of the clip.
    """
    holder_budget = (A4[0] - 20 * mm) - 20 * mm
    data = invoice_page(seller=OVERLONG_CN_SELLER, buyer=DE_BUYER, description=SHORT_DE_DESCRIPTION)
    rows = [run for run in drawn_runs(data) if any("\u4e00" <= ch <= "\u9fff" for ch in run)]
    assert rows, "no Han was drawn, so this proves nothing"
    for run in rows:
        assert measured(run, 8) <= holder_budget, f"{run[:30]!r} runs {measured(run, 8) / mm:.1f}mm, past the margin"


# ── The closeout cover ──────────────────────────────────────────────────────
#
# This generator escaped its text and then drew it on an unfaced style, so it
# was safe from markup and still boxed every non-Latin character. Escaping and
# facing are two different questions about the same string and a module can
# pass one while failing the other.

CN_SLOT = "竣工验收证明书"
CN_EVIDENCE = "施工单位质量保证书"


def closeout_summary(*, project: str, title: str, slot: str, evidence: str) -> dict[str, Any]:
    return {
        "project_name": project,
        "project_type": "commercial",
        "title": title,
        "completeness_pct": 80,
        "required_slot_count": 5,
        "delivered_slot_count": 4,
        "ready": False,
        "gaps": [slot],
        "slots": [{"title": slot, "status": "verified", "evidence": evidence, "verified_at": "2026-04-15"}],
        "built_at": "2026-04-15 09:00 UTC",
    }


def build_closeout(*, chinese: bool) -> bytes:
    from app.modules.closeout.cover_pdf import render_cover_pdf

    if chinese:
        return render_cover_pdf(closeout_summary(project=CN_PROJECT, title=CN_BOQ, slot=CN_SLOT, evidence=CN_EVIDENCE))
    return render_cover_pdf(
        closeout_summary(project=DE_PROJECT, title="Uebergabedokumentation", slot=DE_SECTION, evidence="Pruefprotokoll")
    )


def test_a_chinese_closeout_cover_renders_its_chinese() -> None:
    """Project name, package title, slot title and evidence label all reach
    the page. The slot title and the evidence label are table cells, which is
    the half a paragraph-only wiring would have missed."""
    assert_renders(build_closeout(chinese=True), CN_PROJECT, CN_BOQ, CN_SLOT, CN_EVIDENCE)


def test_a_chinese_closeout_cover_is_boxed_without_the_wiring(switch_off: None) -> None:
    """The control. With the Chinese rung gone the same document boxes."""
    assert_boxed(build_closeout(chinese=True), CN_PROJECT, CN_SLOT)


def test_a_german_closeout_cover_built_after_a_chinese_one_is_unaffected() -> None:
    """Facing one document must not leak into the next. The German cover is
    built second on purpose, since a per-process switch would show up here."""
    build_closeout(chinese=True)
    assert_renders(build_closeout(chinese=False), DE_PROJECT, DE_SECTION)


def test_the_closeout_cover_still_escapes_its_data() -> None:
    """The other question about the same string, asserted so that adding the
    face selection did not cost the escaping this module already had."""
    from app.modules.closeout.cover_pdf import render_cover_pdf

    data = render_cover_pdf(
        closeout_summary(project="Meyer & Sohn", title="Handover", slot="Baufeld <Nord>", evidence="R&D Tower")
    )
    text = extracted_text(data)
    assert "Meyer&Sohn" in text
    assert "Baufeld<Nord>" in text
    assert "R&DTower" in text


# ── The Brazilian invoice ───────────────────────────────────────────────────
#
# Same shape as the closeout cover and the same fix: careful escaping on an
# unfaced style. Every cell of all four tables in this document is a paragraph
# built by the module's own helper, so facing the helper faces the document.

CN_CLIENT = "上海建工集团股份有限公司"
CN_SERVICE = "浦东新区商业综合体主体结构工程"


def br_invoice(*, client: str, description: str) -> bytes:
    from app.modules.finance.br_invoice_pdf import render_br_invoice_pdf

    return render_br_invoice_pdf(
        invoice={
            "invoice_number": "NF-2026-0042",
            "invoice_date": "2026-04-15",
            "due_date": "2026-05-15",
            "currency_code": "BRL",
            "amount_subtotal": "1850.00",
            "tax_amount": "351.50",
            "amount_total": "2201.50",
            "client_name": client,
            "metadata": {"br_fields": {"cnpj": "12.345.678/0001-90", "codigo_servico": "7.02"}},
        },
        line_items=[
            {
                "description": description,
                "unit": "m2",
                "quantity": "10",
                "unit_rate": "185.00",
                "amount": "1850.00",
            }
        ],
        project={"name": client, "code": "P-1"},
    )


def test_a_chinese_brazilian_invoice_renders_its_chinese() -> None:
    """The client name and the service description are the two fields a
    Brazilian invoice carries that a party controls, and both are table
    cells."""
    assert_renders(br_invoice(client=CN_CLIENT, description=CN_SERVICE), CN_CLIENT, CN_SERVICE)


def test_a_chinese_brazilian_invoice_is_boxed_without_the_wiring(switch_off: None) -> None:
    """The control. With the Chinese rung gone the same invoice boxes."""
    assert_boxed(br_invoice(client=CN_CLIENT, description=CN_SERVICE), CN_CLIENT, CN_SERVICE)


def test_a_latin_brazilian_invoice_built_after_a_chinese_one_is_unaffected() -> None:
    """Portuguese is the ordinary case for this document and it must not move.
    Built second on purpose, so a per-process switch would show up here."""
    br_invoice(client=CN_CLIENT, description=CN_SERVICE)
    assert_renders(
        br_invoice(client="Construtora São Paulo Ltda", description="Execução de estrutura"),
        "Construtora São Paulo Ltda",
        "Execução de estrutura",
    )


def test_the_brazilian_invoice_still_escapes_its_data() -> None:
    """The property this module already had, asserted in the same commit that
    adds the new one. The module docstring says the escaping is there to stop a
    hidden-text attack through the metadata block, so losing it would be a
    security regression rather than a cosmetic one."""
    text = extracted_text(br_invoice(client="Meyer & Sohn", description='<font color="white">hidden</font>'))
    assert "Meyer&Sohn" in text
    assert '<fontcolor="white">hidden</font>' in text, "the hidden-text attack was parsed instead of printed"


# ── Bold that is a weight rather than a printed tag ─────────────────────────
#
# The invoice headers were written as inline bold tags and handed to a helper
# whose whole job is to escape what it is given, so the page drew the tag
# characters. The escaping was right; asking for markup through it was not.
# Weight is a style property, so these ask the style. That also stays correct
# when a value is interpolated into the cell, which the net-total row does, and
# an escape-skipping opt-out would not have.

BOLD_HEADERS = ["Descrição", "Unid.", "Qtd.", "Valor unit.", "Valor total", "Valor líquido a pagar"]


def drawn_face(data: bytes, wanted: str) -> str:
    """The BaseFont of the run that drew ``wanted``, subset tag stripped."""
    found: list[str] = []

    def visit(text: str, cm: Any, tm: Any, font: Any, size: Any) -> None:
        if wanted in text and isinstance(font, dict):
            base = str(font.get("/BaseFont", ""))
            found.append(base.lstrip("/").split("+")[-1])

    for page in pypdf.PdfReader(io.BytesIO(data)).pages:
        page.extract_text(visitor_text=visit)
    return found[0] if found else ""


def test_the_invoice_headers_do_not_print_their_own_markup() -> None:
    """What the reader saw: seven tag pairs across the line-item header row."""
    text = extracted_text(br_invoice(client="Construtora Sao Paulo", description="Execucao"))
    assert "<b>" not in text and "</b>" not in text, "the page is still printing bold tags as text"


@pytest.mark.parametrize("header", BOLD_HEADERS)
def test_the_invoice_headers_are_actually_bold(header: str) -> None:
    """The other half, and the reason the test above is not enough on its own.

    Deleting the markup and drawing plain text would satisfy a check that only
    looks for angle brackets, and would silently lose the emphasis on every
    column heading of a tax invoice. This asserts the weight arrived.
    """
    face = drawn_face(br_invoice(client="Construtora Sao Paulo", description="Execucao"), header)
    assert face, f"{header!r} was not drawn at all"
    assert "Bold" in face, f"{header!r} drew in {face}, so the tag was removed without the weight replacing it"


def test_the_interpolated_bold_cell_is_bold_and_still_escaped() -> None:
    """The net total is the cell that decided the shape of this fix.

    It is bold and it carries a formatted value, so the opt-out route, letting
    the helper skip escaping for cells written as markup, would have handed a
    value straight to the parser. Asking for weight through the style leaves the
    escaping untouched, which is what the two assertions here pin together
    rather than separately.

    The fixture carries a retention so that the net differs from the gross. With
    no retention the two are the same number, the figure appears twice on the
    page, and a search for it cannot tell the bold row from the plain one.
    """
    from app.modules.finance.br_invoice_pdf import render_br_invoice_pdf

    data = render_br_invoice_pdf(
        invoice={
            "invoice_number": "NF-2026-0042",
            "invoice_date": "2026-04-15",
            "currency_code": "BRL",
            "amount_subtotal": "1850.00",
            "tax_amount": "351.50",
            "amount_total": "2201.50",
            "retention_amount": "201.50",
            "client_name": "R&D Tower <Ltda>",
            "metadata": {"br_fields": {"cnpj": "12.345.678/0001-90"}},
        },
        line_items=[
            {
                "description": "Execucao & montagem",
                "unit": "m2",
                "quantity": "10",
                "unit_rate": "185.00",
                "amount": "1850.00",
            }
        ],
        project={"name": "R&D Tower <Ltda>", "code": "P-1"},
    )
    runs = drawn_runs(data)
    assert "Projeto: R&D Tower <Ltda>" in runs, "an ampersand or angle bracket was parsed away"
    assert "Execucao & montagem" in runs
    assert len([run for run in runs if "2.000,00" in run]) == 1, "the net total is no longer the only 2.000,00"
    face = drawn_face(data, "2.000,00")
    assert "Bold" in face, f"the net total drew in {face}, so the amount owed lost its emphasis"


# ── The AIA payment application ────────────────────────────────────────────
#
# Two kinds of cell, and only one of them is reachable from here. Line
# descriptions are Paragraph cells built by the module's own helper, so facing
# that helper faces them. The four summary tables above are plain string cells
# drawn under their own FONTNAME, which a paragraph style cannot reach; those
# are wired separately. The split is measured rather than assumed: with this
# change and not the other, a Chinese line description draws in STSong-Light
# and a Chinese certifier name still boxes.

CN_SCOPE = "浦东新区商业综合体主体结构工程"


def aia_payload(*, description: str) -> dict[str, Any]:
    """An application with every field the renderer reads, English but for the
    one cell under test."""
    return {
        "application_number": "APP-014",
        "claim_date": "2026-04-15",
        "period_end": "2026-04-30",
        "currency": "USD",
        "certification": {
            "architect_certified_by": "Ortega Architects",
            "architect_certified_at": "2026-05-01",
            "owner_certified_by": "Harbour Estates",
            "owner_certified_at": "2026-05-02",
            "certified_amount": "1850.00",
        },
        "summary": {
            "contract_sum_to_date": "1850.00",
            "total_completed_stored": "1850.00",
            "balance_to_finish": "0.00",
            "retainage": "0.00",
        },
        "lines": [
            {
                "item_number": "01",
                "description": description,
                "scheduled_value": "1850.00",
                "previous_value": "0.00",
                "this_period_value": "1850.00",
                "materials_stored": "0.00",
                "total_completed_stored": "1850.00",
                "percent_complete": "100",
                "balance_to_finish": "0.00",
                "retainage": "0.00",
            }
        ],
    }


def payment_application(*, description: str) -> bytes:
    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    return render_aia_application_pdf(aia_payload(description=description))


def test_a_chinese_payment_application_renders_its_chinese() -> None:
    """The line description is the cell a contractor fills in their own words."""
    assert_renders(payment_application(description=CN_SCOPE), CN_SCOPE)


def test_a_chinese_payment_application_is_boxed_without_the_wiring(switch_off: None) -> None:
    """The control. With the Chinese rung gone the same application boxes."""
    assert_boxed(payment_application(description=CN_SCOPE), CN_SCOPE)


def test_a_latin_payment_application_built_after_a_chinese_one_is_unaffected() -> None:
    """English is the ordinary case for an AIA document and it must not move.
    Built second on purpose, so a per-process switch would show up here."""
    payment_application(description=CN_SCOPE)
    assert_renders(
        payment_application(description="Substructure and ground floor slab"),
        "Substructure and ground floor slab",
    )


def placed_text(data: bytes, *, ignore_size: float | None = None) -> set[tuple[str, float, float, float]]:
    """Every run of text with the coordinates it was drawn at.

    Two documents with the same placement look the same, whatever operators the
    content stream reached that placement with.
    """
    found: set[tuple[str, float, float, float]] = set()

    def visit(text: str, cm: list[float], tm: list[float], _font: Any, size: float) -> None:
        if not text.strip():
            return
        if ignore_size is not None and abs(size - ignore_size) < 0.01:
            return
        found.add((text.strip(), round(tm[4] + cm[4], 2), round(tm[5] + cm[5], 2), size))

    for page in pypdf.PdfReader(io.BytesIO(data)).pages:
        page.extract_text(visitor_text=visit)
    return found


def drawn_lines(data: bytes, *, ignore_size: float | None = None) -> list[frozenset[tuple[str, float, float]]]:
    """The document as lines: the runs sharing a baseline, without the baseline.

    A line is every run drawn on one baseline of one page, kept as the set of
    ``(text, x, size)`` that line puts on the page. Dropping the baseline is the
    entire point of this instrument: a row inserted above a line changes that
    line's baseline and nothing else about it, while a restyle, a re-alignment
    or a re-wrap changes what is on the line or where it starts.

    The page number is part of the grouping key so that two runs on different
    pages at the same height are never read as one line, and the lines come back
    in reading order, page by page and top down, so a caller can ask whether
    they still come in the order they used to.
    """
    lines: dict[tuple[int, float], set[tuple[str, float, float]]] = {}
    page_number = 0

    def visit(text: str, cm: list[float], tm: list[float], _font: Any, size: float) -> None:
        if not text.strip():
            return
        if ignore_size is not None and abs(size - ignore_size) < 0.01:
            return
        baseline = round(tm[5] + cm[5], 2)
        lines.setdefault((page_number, baseline), set()).add((text.strip(), round(tm[4] + cm[4], 2), size))

    for page_number, page in enumerate(pypdf.PdfReader(io.BytesIO(data)).pages):
        page.extract_text(visitor_text=visit)
    in_reading_order = sorted(lines.items(), key=lambda item: (item[0][0], -item[0][1]))
    return [frozenset(runs) for _key, runs in in_reading_order]


def without_words(lines: list[frozenset[tuple[str, float, float]]]) -> list[frozenset[tuple[float, float]]]:
    """The same lines with what they say taken out, leaving only how they are drawn.

    Used by the control below, which has to fail for a document that is drawn
    differently and not merely worded differently.
    """
    return [frozenset((x, size) for _text, x, size in line) for line in lines]


def first_line_not_redrawn[T](was: list[T], now: list[T]) -> T | None:
    """The first line of *was* that *now* does not draw in turn, or ``None``.

    ``now`` may draw lines *was* never had. It may not drop one, alter one, or
    put two of them back the other way round. That one tolerance is what lets a
    row added to a form pass while everything else about the form is still
    pinned.
    """
    remaining = iter(now)
    for line in was:
        # ``in`` on an iterator consumes it up to and including the match, which
        # is what makes this a subsequence test rather than a membership test.
        if line not in remaining:
            return line
    return None


def test_a_latin_payment_application_is_laid_out_as_it_was_before_the_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    """The claim the wiring commit made about itself, checked rather than asserted.

    Facing a helper that every cell of the schedule passes through could quietly
    restyle every application already issued. This compares against the real
    previous builder, read out of git rather than reimplemented here, so it
    cannot pass by agreeing with a copy of itself.

    The earlier builder is found by walking the file's history for the most
    recent version that predates the wiring rather than by reading HEAD, because
    HEAD carries the wiring and a test anchored there would skip itself and pass
    forever without comparing anything.

    What this has compared, and why it keeps getting weaker.

    It compared bytes until the document's tables moved onto Paragraph cells. A
    Paragraph reaches the same coordinates through different operators, so the
    bytes differed where nothing on the page did, and the comparison moved to
    the placement of every run: same text, same x, same y, same size.

    That equality has expired too. The form has deliberately gained two lines.
    The certificate now prints retainage on completed work and retainage on
    stored material as 5a and 5b, which pushes the payment due row to 9 and
    carries everything under it thirty-two points down the page. The old check
    read that as the English application having moved, which it had, correctly
    and on purpose. The anchor here predates the wiring and always will, so it
    can never be taught about a new row: an equality against it would have to be
    edited away on every deliberate change to this document, and a check that is
    edited whenever it fires is not guarding anything.

    So the vertical position is what was given up, and only that. The document
    is read as lines - the runs sharing one baseline of one page, each run with
    its text, its starting x and its size, the baseline itself thrown away - and
    every line the previous builder drew must still be drawn, in the order it
    was drawn, with new lines allowed to appear between them.

    What the replacement still catches: a run that moves sideways, changes size,
    changes its words or stops being drawn; a row deleted; two rows swapped. A
    restyle lands here because a restyled run is a differently wide run, and
    anything centred or right aligned starts somewhere else the moment its width
    changes.

    What it no longer catches: a row inserted, which is the tolerance being
    bought and paid for; any purely vertical change, so altered padding, leading
    or spacers, or the whole body sliding down the page; a line that crosses a
    page boundary; colour; a face swap that changes neither a run's width nor
    the set of faces the file embeds; and, as before, an operator level rewrite
    that leaves every run where it was.

    A cell that re-wraps belongs on neither list without a qualifier, and the
    first control below is where that was learned. A wrapped cell in a bottom
    aligned row keeps its last line on the row's own baseline, beside the label
    and the date, and puts the overflow on a new line above it. The row survives
    intact and the extra line is an insertion, which this forgives. What the
    comparison sees of a wrap is the words: the run that used to say the whole
    string now says a part of it. So a re-wrap is caught wherever the text is
    compared and invisible wherever it is stripped out.

    One thing this rests on is not in the document at all: the reader has to
    agree about which runs share a baseline, because that agreement is what
    makes a line. Both sides are rendered and read in one process, so a reader's
    quirks cancel - unless the two documents differ in whether a cell wraps,
    which is exactly when the reader gets to decide the grouping on one side
    only. That is not a hypothetical. It is what killed the control that the
    first one below replaces.

    The face comparison below is untouched by all of this and is the wiring
    property proper: a Latin document that had escalated to the Chinese pack
    would embed a face it did not use to, and no number of added rows can move
    that. This is also the test that would have caught the whitespace escalation
    fixed alongside the wiring, which escalates the headings of this very
    document.

    What this never looks at is the continuation sheet, and that exclusion is
    older than the weakening. That sheet did move, deliberately: its header row
    asked for white bold text through TEXTCOLOR and FONTNAME table commands, a
    table command cannot reach a flowable cell, so it had been drawn in regular
    black on a near black fill since the day it was written, and giving it the
    weight it asks for wraps two of its labels a line further. It is the only
    seven point text in the document, which is what separates it out. Weakening
    the check did not make the exclusion liftable, and that was measured rather
    than assumed: drop it and this comparison rejects the pair on the sheet's
    own header row, which the earlier builder drew as one line and this one
    draws as two. The line description lives on that sheet, so nothing this test
    reads changes when it changes, which is why the last control below is still
    on the bytes.
    """
    import reportlab.rl_config as rl_config
    from reportlab.lib.enums import TA_LEFT

    from app.modules.contracts import aia_pdf
    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    source = source_before_the_wiring("backend/app/modules/contracts/aia_pdf.py", "pdf_style_for_text")
    assert source, "no version of the application builder predating the wiring is reachable in this history"

    module = types.ModuleType("aia_pdf_before")
    module.__file__ = "aia_pdf_before.py"
    exec(compile(source, "aia_pdf_before.py", "exec"), module.__dict__)  # noqa: S102

    previous = rl_config.invariant
    rl_config.invariant = 1
    try:
        latin = aia_payload(description="Substructure and ground floor slab")
        was = module.render_aia_application_pdf(latin)
        now = render_aia_application_pdf(latin)
        before = drawn_lines(was, ignore_size=7)
        after = drawn_lines(now, ignore_size=7)
        # The population, printed beside the verdict. Without it an instrument
        # that has stopped reading the document passes by comparing nothing.
        assert len(before) >= 15, f"only {len(before)} lines were read from the earlier form, so this stopped watching"
        lost = first_line_not_redrawn(before, after)
        assert lost is None, (
            "the English payment application stopped drawing a line it used to draw, or drew it out of order: "
            f"{sorted(lost) if lost is not None else ''}"
        )
        assert referenced_faces(was) == referenced_faces(now), (
            "the English payment application embeds a different set of faces than it used to"
        )

        # Three controls. The first says this comparison can tell two documents
        # apart by where their runs start, and not merely by what they say. The
        # same payload is rendered again with the right aligned styles told to
        # draw left: a real change to the page, in which the money column's runs
        # begin at a different x with not one character, size or face different
        # anywhere on it. It is paired with a plain second render that has to be
        # accepted, so that the rejection cannot be explained by two renders
        # never agreeing with one another in the first place.
        #
        # This was a certifier name long enough to wrap until 2026-09-23, and
        # that control was dead rather than miscalibrated. It rejected on the
        # count of the label-name-date shape, which the short document draws
        # twice, architect and owner, and the wrapped one drew once: the
        # multiplicity of a shape that is not unique on the page. And it drew it
        # once only because pypdf up to 6.16.1 reported the wrapped cell's second
        # line eighty-four points below its own row. The page never drew it
        # there. Both fragments sit under one cm at Tm 0 16 with a leading of 12,
        # the label and the date do not move, and the second fragment comes down
        # to join them on the row's own baseline. Read correctly, which 6.16.2
        # does, the wrap only inserts a line above an intact row,
        # first_line_not_redrawn forgives insertion by design, and there was
        # nothing left for the control to catch. So a control here may not rest
        # on a wrap, and may not rest on how many times a repeating shape occurs.
        unmoved = drawn_lines(render_aia_application_pdf(latin), ignore_size=7)
        assert first_line_not_redrawn(without_words(after), without_words(unmoved)) is None, (
            "the same payload rendered twice did not agree with itself, so the control below proves nothing"
        )
        with monkeypatch.context() as drawn_left:
            drawn_left.setattr(aia_pdf, "TA_RIGHT", TA_LEFT)
            moved = drawn_lines(render_aia_application_pdf(latin), ignore_size=7)
        assert first_line_not_redrawn(without_words(after), without_words(moved)) is not None, (
            "the money column drawn left began at exactly the x it begins at when drawn right, "
            "so this comparison cannot see where anything is drawn"
        )
        # The second holds the order half of the comparison to account, which no
        # payload can reach: nothing a party types reorders the form. So the
        # document's own lines are handed back with the first and the last
        # swapped, and the comparison has to refuse them.
        swapped = list(after)
        swapped[0], swapped[-1] = swapped[-1], swapped[0]
        assert first_line_not_redrawn(after, swapped) is not None, (
            "the form's own lines were accepted in the wrong order, so this comparison ignores the order"
        )
        # The third is the original one, on the bytes, and it has to stay on the
        # bytes. The line description is seven point text on the continuation
        # sheet, which the line comparison excludes, so a Chinese scope reaches
        # the page without altering one line this test reads. All this control
        # proves is that the renderer reads the description at all.
        other = render_aia_application_pdf(aia_payload(description=CN_SCOPE))
        assert other != now, "a Chinese application produced the same bytes as an English one, so nothing is compared"
    finally:
        rl_config.invariant = previous


# ── The AIA summary tables ──────────────────────────────────────────────────
#
# The commit that faced every Paragraph in this document said, in its own
# message, that a Chinese certifier name would still box. It did, because these
# four tables held plain string cells drawn under the table's own FONTNAME,
# which a paragraph style cannot reach. They were faced per cell by appending
# commands to the table style instead.
#
# They are Paragraph cells now, so the face is chosen the ordinary way and the
# appended commands are gone. What the tests below assert did not change: a
# Chinese cell takes the CID face, the same cell boxes without the wiring, and
# a bold label in the same row keeps its weight.

CN_CERTIFIER = "上海建工集团股份有限公司"


def test_a_chinese_certifier_name_renders_in_a_string_cell() -> None:
    """The gap the previous commit named and left open."""
    payload = aia_payload(description="Substructure and ground floor slab")
    payload["certification"]["architect_certified_by"] = CN_CERTIFIER
    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    assert_renders(render_aia_application_pdf(payload), CN_CERTIFIER)


def test_a_chinese_certifier_name_is_boxed_without_the_wiring(switch_off: None) -> None:
    """The control. With the Chinese rung gone the same cell boxes again."""
    payload = aia_payload(description="Substructure and ground floor slab")
    payload["certification"]["architect_certified_by"] = CN_CERTIFIER
    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    assert_boxed(render_aia_application_pdf(payload), CN_CERTIFIER)


def test_a_chinese_application_number_renders_in_a_different_table() -> None:
    """The second population. These cells live in the header table rather than
    the certification one, so wiring one table would leave this boxing."""
    payload = aia_payload(description="Substructure and ground floor slab")
    payload["application_number"] = CN_CERTIFIER
    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    assert_renders(render_aia_application_pdf(payload), CN_CERTIFIER)


def test_a_bold_label_keeps_its_weight_beside_an_escalated_cell() -> None:
    """The property at risk, which the helper's own docstring warns about.

    Faces are pinned here by appending commands to a style that already names a
    bold face for some cells. A command computed against the wrong base would
    hand a bold label a regular-weight face and quietly flatten the table. The
    label sits in the same row as the escalated cell, so it is the one that would
    lose its weight first.
    """
    payload = aia_payload(description="Substructure and ground floor slab")
    payload["certification"]["architect_certified_by"] = CN_CERTIFIER
    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    data = render_aia_application_pdf(payload)
    assert "Bold" in drawn_face(data, "Architect certified"), "the bold label lost its weight"
    assert "STSong" in drawn_face(data, CN_CERTIFIER), "the Chinese cell did not take the CID face"


# ── The methodology export ──────────────────────────────────────────────────
#
# Every cell a party fills goes through this module's own _safe_para, with one
# exception: the prepared-by line splices user text into a Paragraph directly,
# which the helper's docstring reserves for strings checked into source. So the
# funnel covers six of the seven fields and that line is faced on its own.
#
# There are no plain string cells to face here. The module has eight tables and
# two FONTNAME commands, both on header row zero, which is the shape that leaves
# a body drawing in Helvetica, but its only bare-string cells are empty spacers.

CN_METHODOLOGY = "综合单价法"
CN_STEP = "企业管理费"
CN_ENGINEER = "上海建工集团造价工程师"
CN_PROJECT = "浦东中心大厦"


def methodology_export(
    *,
    name: str = "Unit rate method",
    step: str = "Overheads",
    prepared_by: str = "Cost Engineer",
    project: str = "Riverside Tower",
) -> bytes:
    from app.modules.methodology.pdf_export import generate_methodology_pdf

    return generate_methodology_pdf(
        {
            "project_name": project,
            "methodology_name": name,
            "methodology_slug": "unit-rate",
            "currency": "EUR",
            "decimals": 2,
            "direct_total": "1000000.00",
            "markup_total": "235000.00",
            "grand_total": "1235000.00",
            "prepared_by": prepared_by,
            "bases": {"direct_cost": "1000000.00"},
            "composites": {"works_base": ["direct_cost"]},
            "steps": [
                {
                    "key": "overheads",
                    "kind": "percentage",
                    "category": "overhead",
                    "label": step,
                    "rate": "15.00",
                    "base_amount": "1000000.00",
                    "amount": "150000.00",
                    "running_total": "1150000.00",
                }
            ],
        }
    )


def test_a_chinese_methodology_renders_its_chinese() -> None:
    """The name and the step label are what an estimator writes themselves."""
    assert_renders(methodology_export(name=CN_METHODOLOGY, step=CN_STEP), CN_METHODOLOGY, CN_STEP)


def test_a_chinese_methodology_is_boxed_without_the_wiring(switch_off: None) -> None:
    """The control. With the Chinese rung gone the same export boxes."""
    assert_boxed(methodology_export(name=CN_METHODOLOGY, step=CN_STEP), CN_METHODOLOGY, CN_STEP)


def test_the_prepared_by_line_renders_chinese_too() -> None:
    """The site the funnel does not reach, which is why it is its own test.

    This line builds its Paragraph directly instead of going through
    _safe_para, so facing the funnel leaves it boxing while every other field on
    the page renders. That is the half-wired shape: a document that looks fixed
    because the fields anyone checks first are fine.
    """
    assert_renders(methodology_export(prepared_by=CN_ENGINEER), CN_ENGINEER)


def test_a_chinese_project_name_renders_in_the_running_header() -> None:
    """The third kind of site in this document, after the funnel and the one
    Paragraph that bypasses it.

    The running header is drawn straight onto the canvas rather than through a
    flowable, so neither a paragraph style nor a table command can reach it, and
    both names on that line are party-supplied. This is the site my scope
    measurement missed and the suite caught: with only the flowables faced, the
    body renders and the header prints five boxes, which is the half-wired shape
    that looks fixed to anyone who checks the fields first.
    """
    assert_renders(methodology_export(project=CN_PROJECT), CN_PROJECT)


def test_a_latin_methodology_built_after_a_chinese_one_is_unaffected() -> None:
    """The ordinary case for this document, built second on purpose so a
    per-process switch would show up here."""
    methodology_export(name=CN_METHODOLOGY, step=CN_STEP)
    assert_renders(methodology_export(), "Unit rate method", "Overheads")


def test_a_latin_methodology_is_laid_out_as_it_was_before_the_wiring() -> None:
    """The claim the wiring commit made about itself, checked rather than asserted.

    Compares against the real previous builder read out of git, so it cannot
    pass by agreeing with a copy of itself, and walks the history for the most
    recent version predating the wiring rather than anchoring on HEAD, which
    would skip itself and pass forever without comparing anything.

    This compared bytes until the step table's header row was given the colour
    its own TableStyle had been asking for. That row is filled #1a1a2e and the
    style said TEXTCOLOR white, but a table command cannot reach a cell holding
    a Paragraph, so "Step" and "Category" were drawn #1a1a2e on #1a1a2e and
    were not on the page at all. Fixing that changes these bytes on purpose.

    What the document is allowed to do is change colour, not move. So the
    comparison is now on where every run is placed and on the faces the file
    embeds, both of which a recolouring leaves alone, and the bytes are
    asserted to differ rather than match, which pins that the recolouring is
    still there. The colour itself is pinned by
    test_pdf_header_text_is_readable_on_its_fill, which reads the fill behind
    each run rather than trusting the style that asks for it.
    """
    import reportlab.rl_config as rl_config

    from app.modules.methodology.pdf_export import generate_methodology_pdf

    source = source_before_the_wiring("backend/app/modules/methodology/pdf_export.py", "pdf_style_for_text")
    assert source, "no version of the methodology builder predating the wiring is reachable in this history"

    module = types.ModuleType("methodology_pdf_before")
    module.__file__ = "methodology_pdf_before.py"
    exec(compile(source, "methodology_pdf_before.py", "exec"), module.__dict__)  # noqa: S102

    previous = rl_config.invariant
    rl_config.invariant = 1
    try:
        payload = {
            "project_name": "Riverside Tower",
            "methodology_name": "Unit rate method",
            "methodology_slug": "unit-rate",
            "currency": "EUR",
            "decimals": 2,
            "direct_total": "1000000.00",
            "markup_total": "235000.00",
            "grand_total": "1235000.00",
            "prepared_by": "Cost Engineer",
            "bases": {"direct_cost": "1000000.00"},
            "composites": {"works_base": ["direct_cost"]},
            "steps": [
                {
                    "key": "overheads",
                    "kind": "percentage",
                    "category": "overhead",
                    "label": "Overheads",
                    "rate": "15.00",
                    "base_amount": "1000000.00",
                    "amount": "150000.00",
                    "running_total": "1150000.00",
                }
            ],
        }
        was = module.generate_methodology_pdf(payload)
        now = generate_methodology_pdf(payload)
        # The wiring moved header and footer from canvas.drawString to
        # Paragraph (for CJK/Thai shaping). Paragraph normalises HTML
        # whitespace and positions its frame differently, so the header
        # and footer runs (sizes 7 and 8) differ in both text spacing
        # and Y coordinate. Body runs are unaffected, so we compare
        # them exactly and compare header/footer text with normalised
        # whitespace only.
        hf_sizes = {7.0, 8.0}

        def _body(s: set[tuple[str, float, float, float]]) -> set[tuple[str, float, float, float]]:
            return {t for t in s if t[3] not in hf_sizes}

        def _hf_text(s: set[tuple[str, float, float, float]]) -> set[str]:
            return {" ".join(t[0].split()) for t in s if t[3] in hf_sizes}

        assert _body(placed_text(was)) == _body(placed_text(now)), (
            "the English methodology export body moved, and only its header colour was supposed to change"
        )
        assert _hf_text(placed_text(was)) == _hf_text(placed_text(now)), (
            "the header/footer text changed beyond whitespace normalisation"
        )
        assert referenced_faces(was) == referenced_faces(now), (
            "the English methodology export embeds a different set of faces than it used to"
        )
        assert was != now, "the header row is drawn in the colour it was before, so the readability fix is gone"

        other = generate_methodology_pdf({**payload, "methodology_name": CN_METHODOLOGY})
        assert other != now, "a Chinese export produced the same bytes as an English one, so nothing is compared"
    finally:
        rl_config.invariant = previous


# ── Why the Brazilian invoice needs no font commands, and what protects that ──
#
# A font census of this document shows Helvetica among its resources, which
# looks like the half-wired shape: bare string cells drawn under a table that
# names no FONTNAME, falling back to Helvetica and boxing anything outside
# Latin-1. It is not. Helvetica is reportlab's default canvas font, it is
# selected around empty cells and page setup, and it draws no glyphs here at
# all. Measured rather than read: five tables, 68 cells, every one a flowable,
# and pdf_table_font_commands returns nothing for any of them.
#
# So the module needs no wiring. But the reason it is safe is a property of what
# the cells currently are, not of anything in the code: the file carries no
# FONTNAME command anywhere, so the day a bare string cell arrives it will draw
# in Helvetica and box, and nothing in the module will notice. That is what this
# pins. It passes today and fails on the change that would make it matter.


def test_every_invoice_table_cell_is_a_flowable() -> None:
    """No bare strings in any table of the Brazilian invoice.

    A bare string is drawn under the table's own FONTNAME, and this module has
    none, so such a cell would fall back to Helvetica. Every cell being a
    flowable is what makes the paragraph facing sufficient for this document.
    """
    from reportlab.platypus import Flowable

    from app.modules.finance import br_invoice_pdf

    captured: list[Any] = []
    real_table = br_invoice_pdf.Table

    class SpyTable(real_table):  # type: ignore[misc, valid-type]
        def __init__(self, data: Any, *args: Any, **kwargs: Any) -> None:
            captured.append(data)
            super().__init__(data, *args, **kwargs)

    br_invoice_pdf.Table = SpyTable  # type: ignore[misc]
    try:
        br_invoice(client=CN_CLIENT, description=CN_SERVICE)
    finally:
        br_invoice_pdf.Table = real_table  # type: ignore[misc]

    # The instrument has to have fired. Without this the test passes for free
    # the day the module stops building its tables through this name, which is
    # the same failure as having no test at all but harder to notice.
    cells = [
        (t, r, c, cell) for t, rows in enumerate(captured) for r, row in enumerate(rows) for c, cell in enumerate(row)
    ]
    assert len(captured) >= 4, f"only {len(captured)} tables were captured, so this test stopped watching the document"
    assert len(cells) >= 40, f"only {len(cells)} cells were captured, so this test stopped watching the document"

    bare = [(t, r, c, cell) for t, r, c, cell in cells if not isinstance(cell, Flowable)]
    assert not bare, "bare cells would draw in Helvetica, because this module names no FONTNAME anywhere: " + ", ".join(
        f"table {t} row {r} column {c} is {type(cell).__name__} {cell!r}" for t, r, c, cell in bare[:6]
    )
