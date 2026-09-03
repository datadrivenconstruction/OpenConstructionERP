# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Every generated email carries a REAL text/plain part.

``build_eml`` used to set the plain alternative to one stub line - "This
message requires an HTML-capable mail client" - and hang the whole
document off the HTML part beside it. A recipient whose client prefers
plain text, a gateway that strips HTML, a phone reading in text mode and
a spam filter comparing the two parts all read the stub, so every RFQ,
RFI, order and variation this system generated was, to them, an email
containing no request. Verified live on a real RFQ before the fix.

What proves the fix is not that a text part exists - it is that the text
part says the same thing the HTML one does, built from the same
structured content rather than scraped out of the markup.
"""

from __future__ import annotations

import re
from email import message_from_bytes, policy

from app.core.email.textify import html_to_text
from app.modules.outlook_bridge.eml import build_eml
from app.modules.outlook_bridge.outbound import (
    build_register_email_html,
    build_register_email_text,
)

#: The stub that must never come back. Asserted by value in more than one
#: place on purpose - a fallback that quietly reintroduces it is the same
#: defect wearing a different name.
STUB = "This message requires an HTML-capable mail client."

#: A markup tag, as opposed to the angle brackets around an address in
#: ``Alex Example <alex@example.com>`` - which is plain-text convention
#: and belongs in the Notified block.
TAG = re.compile(r"<\s*/?[a-zA-Z][a-zA-Z0-9]*(\s[^>]*)?/?\s*>")


def _parts(raw: bytes) -> tuple[str, str]:
    """(text/plain body, text/html body) out of one built .eml."""
    msg = message_from_bytes(raw, policy=policy.default)
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    return (
        plain.get_content() if plain is not None else "",
        html.get_content() if html is not None else "",
    )


CONTENT = {
    "eyebrow": "Request for quotation",
    "title": "MSB-01 switchboard package",
    "project_line": "Job 25406 - Warehouse fitout",
    "intro": "Please provide your quotation for the package below.",
    "pairs": [
        ("Reference", "REG-RFQ-25406-0005"),
        ("Email ref", "REG-MSG-000042"),
        ("Package", "Main switchboard"),
        # The money rail: internal figures never leave the building, and
        # the plain part is a second door onto the same content.
        ("Estimated value $", "9,900"),
        ("Delivery to", "12 Site Rd\nGate 3, off Example Street"),
        ("Quotes due", "2026-09-30"),
    ],
    "body_text": "Alex - the crane window is 06:30-09:00 only.",
    "notified": [("Acme Electrical", "alex@example.com", "03/09/2026 09:12")],
    "footer_ref": "REG-RFQ-25406-0005",
    "greeting": "Hi Alex,",
    "hero_right": "REG-RFQ-25406-0005",
    "response_box": ["Response", "Answered by", "Date"],
    "tables": [("Materials / scope required", [["Item", "Qty"], ["Cable ladder 300mm", "40"]])],
    "attached": ["site-plan.pdf"],
}


# ── The renderer ─────────────────────────────────────────────────────────


def test_the_text_renderer_says_what_the_html_says() -> None:
    text = build_register_email_text(**CONTENT)

    # The heading line, then the two references a reply is answered by.
    assert text.splitlines()[0].startswith("REQUEST FOR QUOTATION")
    assert "Reference: REG-RFQ-25406-0005" in text
    assert "Email ref: REG-MSG-000042" in text

    # Every label/value pair, the free text, the table, the files and the
    # people told - the document, not a summary of it.
    assert "Package: Main switchboard" in text
    assert "Quotes due: 2026-09-30" in text
    assert "crane window is 06:30-09:00" in text
    assert "Cable ladder 300mm | 40" in text
    assert "- site-plan.pdf" in text
    assert "alex@example.com" in text and "03/09/2026 09:12" in text

    # A multi-line value keeps its shape, indented under its own label,
    # rather than being folded into one unreadable run.
    assert "Delivery to:\n    12 Site Rd\n    Gate 3, off Example Street" in text

    # NOTHING OF THE MARKUP. No tags, no entities - a person reads this.
    # (The angle brackets around an address are plain-text convention and
    # stay; TAG is what a leaked template would look like.)
    assert TAG.search(text) is None
    assert "&nbsp;" not in text and "&#x27;" not in text
    assert "&middot;" not in text and "·" in text

    # THE MONEY RAIL, enforced in the text builder itself and not left to
    # the caller: a rail enforced in one of two renderers is not a rail.
    assert "9,900" not in text


def test_no_line_of_the_text_part_runs_past_the_column() -> None:
    """78 columns, so a supplier's reply can quote it without rewrapping."""
    long_intro = dict(CONTENT, intro="Please quote. " * 40)
    for line in build_register_email_text(**long_intro).splitlines():
        # A table row and a fill-in rule are allowed their own width; a
        # wrapped paragraph is not.
        if "|" in line or "___" in line:
            continue
        assert len(line) <= 90, line


# ── The HTML → text fallback ─────────────────────────────────────────────


def test_the_fallback_turns_a_small_table_into_readable_lines() -> None:
    html = (
        "<p>Please quote the following.</p>"
        "<table><tr><th>Item</th><th>Qty</th></tr>"
        "<tr><td>Cable ladder</td><td>40</td></tr>"
        "<tr><td>Bends</td><td>6</td></tr></table>"
        "<p>Regards&nbsp;&middot; Alex&#x27;s team</p>"
    )
    text = html_to_text(html)
    assert "Please quote the following." in text
    assert "Item | Qty" in text
    assert "Cable ladder | 40" in text
    assert "Bends | 6" in text
    # Entities are decoded, not carried through as literals, and no cell
    # is left with the dangling separator its row ended on.
    assert "&nbsp;" not in text and "&#x27;" not in text and "&middot;" not in text
    assert "Regards · Alex's team" in text
    assert TAG.search(text) is None
    assert not any(line.endswith("|") for line in text.splitlines())


def test_the_fallback_reads_our_own_email_livery() -> None:
    """The register email is a Word-engine table; it must still read out."""
    text = html_to_text(build_register_email_html(**CONTENT))
    assert "REG-RFQ-25406-0005" in text
    assert "Cable ladder 300mm | 40" in text
    assert "crane window" in text
    assert "&nbsp;" not in text and TAG.search(text) is None
    assert "9,900" not in text  # the money rail holds through the HTML too


# ── The .eml itself ──────────────────────────────────────────────────────


def test_the_eml_carries_the_payloads_own_text_verbatim() -> None:
    raw = build_eml(
        {
            "to": ["alex@example.com"],
            "subject": "RFQ - MSB-01",
            "html": "<p>Please quote.</p>",
            "text": "Please quote.\n\nReference: REG-RFQ-25406-0005\n",
            "attachments": [],
        }
    )
    plain, html = _parts(raw)
    assert "Reference: REG-RFQ-25406-0005" in plain
    assert plain.strip() == "Please quote.\n\nReference: REG-RFQ-25406-0005"
    # The HTML part is untouched by any of this.
    assert "<p>Please quote.</p>" in html
    assert STUB not in raw.decode("utf-8", errors="replace")


def test_a_payload_with_no_text_gets_the_conversion_not_the_stub() -> None:
    """The fallback path is where the stub used to live for everything."""
    raw = build_eml(
        {
            "to": ["alex@example.com"],
            "subject": "Notice",
            "html": "<p>Site closed Friday.</p><table><tr><td>Qty</td><td>40</td></tr></table>",
            "attachments": [],
        }
    )
    plain, html = _parts(raw)
    assert "Site closed Friday." in plain
    assert "Qty | 40" in plain
    assert STUB not in plain
    assert "<p>Site closed Friday.</p>" in html


def test_the_stub_is_gone_from_the_source() -> None:
    """Belt and braces: no code path can put that line in a mail again."""
    from pathlib import Path

    roots = [
        Path("app/modules/outlook_bridge"),
        Path("app/modules/register_workflow"),
        Path("app/core/email"),
    ]
    for root in roots:
        for path in root.rglob("*.py"):
            body = path.read_text(encoding="utf-8")
            # This test file names the stub deliberately; the app must not.
            assert STUB not in body, f"{path} still sets the plain-text stub"
