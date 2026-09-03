# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outbound: open a signed Outlook draft from register content.

The draft opens on the user's screen with their saved signature already
in place and the register email inserted above it; Send stays a human
act. ``GetInspector`` is touched BEFORE the body is edited - that is
what makes Outlook render the signature into a fresh item.
"""

from __future__ import annotations

import html as _html
import textwrap
from typing import Any

from app.core.app_branding import org_display_name
from app.core.email.textify import html_to_text
from app.modules.outlook_bridge.ps import run_outlook_script

#: Static script - all data arrives via the JSON payload (see ps.py).
_DRAFT_SCRIPT = r"""
param([string]$PayloadPath)
$ErrorActionPreference = 'Stop'
try {
  $p = Get-Content -Raw -Path $PayloadPath | ConvertFrom-Json
  $outlook = New-Object -ComObject Outlook.Application
  $mail = $outlook.CreateItem(0)
  # Touching the inspector BEFORE editing the body makes Outlook inject the
  # user's saved signature into HTMLBody, which we then insert above.
  $null = $mail.GetInspector
  $mail.To = ($p.to -join '; ')
  if ($p.cc)  { $mail.CC  = ($p.cc -join '; ') }
  if ($p.bcc) { $mail.BCC = ($p.bcc -join '; ') }
  $mail.Subject = $p.subject
  # -Encoding UTF8 is load-bearing: Windows PowerShell 5.1 reads ANSI by
  # default, and the html file is UTF-8 - without it every non-ASCII
  # character in the body went into the DRAFT ITSELF corrupted
  # (the middle dot became "A-circumflex dot" in real sent mail).
  $bodyHtml = Get-Content -Raw -Encoding UTF8 -Path $p.html_path
  $existing = $mail.HTMLBody
  $idx = $existing.IndexOf('<body')
  if ($idx -ge 0) {
    $close = $existing.IndexOf('>', $idx)
    $mail.HTMLBody = $existing.Substring(0, $close + 1) + $bodyHtml + $existing.Substring($close + 1)
  } else {
    $mail.HTMLBody = $bodyHtml + $existing
  }
  $attached = @()
  $missing = @()
  foreach ($f in @($p.attachments)) {
    if ($f -and (Test-Path $f)) { $null = $mail.Attachments.Add($f); $attached += $f }
    elseif ($f) { $missing += $f }
  }
  $mail.Display()
  $json = @{ ok = $true; attached = $attached; missing = $missing } | ConvertTo-Json -Compress
  Set-Content -Path $p._out_path -Value $json -Encoding UTF8
} catch {
  $json = @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
  try { $json | Set-Content -Path $p._out_path -Encoding UTF8 } catch {}
  Write-Output $json
  exit 1
}
"""


async def open_draft(
    *,
    to: list[str],
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str,
    html_body_path: str,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Open one Outlook draft. Returns the script's answer dict."""
    payload = {
        "to": [a for a in to if a],
        "cc": [a for a in (cc or []) if a],
        "bcc": [a for a in (bcc or []) if a],
        "subject": subject,
        "html_path": html_body_path,
        "attachments": [p for p in (attachment_paths or []) if p],
    }
    return await run_outlook_script(_DRAFT_SCRIPT, payload)


# ── Register email HTML (the planner livery) ─────────────────────────────

#: Field labels that NEVER leave the building. Stripped server-side as the
#: last line of defence, whatever the caller sent (the money rail).
INTERNAL_LABELS = frozenset(
    {
        "estimated value $",
        "cost $",
        "sell $",
        "margin",
        "cost impact $",
        "budget $",
    }
)


def strip_internal_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(k, v) for (k, v) in pairs if k.strip().lower() not in INTERNAL_LABELS]


# The planner email engine's design system, verbatim. Outlook renders HTML
# with the WORD engine: table-based layout only, ``bgcolor`` ATTRIBUTES
# beside inline styles, ``nowrap="nowrap"`` attributes not CSS, no margins
# on spans, valign for centring. Every rule below exists because Word
# strips the modern alternative.
_NAVY = "#12294A"
_NAVY2 = "#0C1D38"
_NAVYLINE = "#1E3358"
_ORANGE = "#E85322"
_SLATE = "#5B6878"
_INK = "#1F2937"
_TILE = "#F7F8FA"
_RULE = "#E2E8ED"
_PALE = "#A9B9D2"
#: Kept but no longer painted behind the card: the email sits on plain
#: white, left-aligned. Left here because other workspace surfaces reference
#: the same page grey, and deleting it invites someone to reintroduce a
#: different one.
_PAGE = "#EEF1F5"
_FONT = "Poppins,'Segoe UI',Arial,sans-serif"
_CARD_W = 700


def build_register_email_html(
    *,
    eyebrow: str,
    title: str,
    project_line: str,
    intro: str,
    pairs: list[tuple[str, str]],
    body_text: str = "",
    body_html: str = "",
    notified: list[tuple[str, ...]] | None = None,
    footer_ref: str = "",
    greeting: str = "Hi,",
    hero_right: str = "",
    response_box: list[str] | None = None,
    tables: list[tuple[str, list[list[str]]]] | None = None,
    attached: list[str] | None = None,
) -> str:
    """One register email in the planner livery the suppliers already know.

    Grey page, one centred white card, 4px orange bar, navy hero with an
    orange micro-caps eyebrow, navy2 project sub-bar with a 3px orange left
    border, 2px-navy-ruled section heads, zebra details, tiny slate footer.
    Table-based throughout - see the Word-engine rules above.

    ``notified`` is the (name, email, timestamp) list of every person this email is
    addressed to. Internal-only pairs are stripped here regardless of caller.
    """
    e = _html.escape
    pairs = strip_internal_pairs(pairs)

    def micro(t: str, colour: str) -> str:
        return (
            f'<div style="font-size:9px;font-weight:700;letter-spacing:2px;color:{colour};'
            f'text-transform:uppercase;font-family:{_FONT};">{e(t)}</div>'
        )

    def section_head(heading: str) -> str:
        return (
            f'<div style="font-size:17px;font-weight:700;color:{_NAVY};line-height:1.2;'
            f'font-family:{_FONT};">{e(heading)}</div>'
            f'<div style="height:2px;background:{_NAVY};margin:7px 0 0;font-size:0;line-height:0;">&nbsp;</div>'
        )

    def spacer(px: int) -> str:
        return f'<div style="height:{px}px;line-height:{px}px;font-size:0;">&nbsp;</div>'

    # ── Hero: orange bar row + navy row ──────────────────────────────────
    hero = (
        f'<tr><td bgcolor="{_ORANGE}" style="height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr>'
        f'<tr><td bgcolor="{_NAVY}" style="padding:16px 24px;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f'<td valign="middle">{micro(eyebrow, _ORANGE)}'
        f'<div style="font-size:26px;font-weight:700;color:#ffffff;line-height:1.15;margin-top:4px;'
        f'font-family:{_FONT};">{e(title)}</div></td>'
        f'<td align="right" valign="middle" nowrap="nowrap" style="white-space:nowrap;">'
        f'<div style="font-size:14px;font-weight:600;color:#ffffff;font-family:{_FONT};">{e(hero_right)}</div>'
        f"</td></tr></table></td></tr>"
    )

    # ── Sub-bar: navy2, 3px orange left border, the PROJECT line ─────────
    sub_bar = (
        f'<tr><td bgcolor="{_NAVY2}" style="padding:8px 24px;border-left:3px solid {_ORANGE};">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f'<td style="font-size:12px;color:#ffffff;font-family:{_FONT};">'
        f'<span style="font-size:9px;font-weight:700;letter-spacing:1.6px;color:{_ORANGE};'
        f'text-transform:uppercase;">Project</span>&nbsp;&nbsp;<b>{e(project_line)}</b></td>'
        f'<td align="right" nowrap="nowrap" style="font-size:10.5px;color:{_PALE};white-space:nowrap;'
        f'font-family:{_FONT};">{e(footer_ref)}</td></tr></table></td></tr>'
    )

    # ── Greeting + intro ─────────────────────────────────────────────────
    lead = (
        f'<tr><td style="padding:16px 24px 0;">'
        f'<div style="font-size:13px;color:{_INK};line-height:1.6;font-family:{_FONT};">{e(greeting)}</div>'
        f"{spacer(6)}"
        f'<div style="font-size:13px;color:{_INK};line-height:1.6;font-family:{_FONT};">{e(intro)}</div>'
        f"</td></tr>"
    )

    # ── Details: 2px-ruled head + zebra label/value rows ─────────────────
    detail_rows = "".join(
        f'<tr><td width="190" nowrap="nowrap" bgcolor="{_TILE if i % 2 else "#ffffff"}" '
        f'style="white-space:nowrap;padding:7px 10px;font-size:10.5px;font-weight:700;'
        f'letter-spacing:1.4px;color:{_SLATE};text-transform:uppercase;font-family:{_FONT};">{e(k)}</td>'
        f'<td bgcolor="{_TILE if i % 2 else "#ffffff"}" style="padding:7px 10px;font-size:11.5px;'
        f'color:{_INK};font-family:{_FONT};">{e(v)}</td></tr>'
        for i, (k, v) in enumerate(pairs)
        if str(v).strip()
    )
    details = (
        f'<tr><td style="padding:16px 24px 0;">{section_head("Details")}{spacer(8)}'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%">{detail_rows}</table></td></tr>'
        if detail_rows
        else ""
    )

    # ── Free-text body ───────────────────────────────────────────────────
    # ``body_html`` is the captured ORIGINAL of an inbound email, already
    # sanitised at capture time (register allowlist). It outranks the
    # flattened text: showing bare lines where the sender sent a formatted
    # document is how "the preview loses its formatting" happened.
    body_section = ""
    if body_html.strip():
        body_section = (
            f'<tr><td style="padding:16px 24px 0;">{section_head("Message")}{spacer(8)}'
            f'<div style="font-size:11.5px;color:{_INK};line-height:1.6;font-family:{_FONT};">{body_html}</div>'
            f"</td></tr>"
        )
    elif body_text.strip():
        paragraphs = "".join(
            f'<div style="font-size:11.5px;color:{_INK};line-height:1.6;font-family:{_FONT};">{e(line) or "&nbsp;"}</div>'
            for line in body_text.splitlines()
        )
        body_section = (
            f'<tr><td style="padding:16px 24px 0;">{section_head("Message")}{spacer(8)}{paragraphs}</td></tr>'
        )

    # ── Materials / scope tables (pasted Excel cells, kept as a table) ────
    # First row is the header; zebra body; th cells hard-nowrap per the
    # Word-engine rules.
    tables_html = ""
    for heading, rows_data in tables or []:
        if not rows_data:
            continue
        head_cells = "".join(
            f'<th align="left" nowrap="nowrap" style="white-space:nowrap;padding:6px 8px 6px 0;'
            f"border-bottom:2px solid {_NAVY};font-size:9px;font-weight:700;letter-spacing:1.8px;"
            f'color:{_SLATE};text-transform:uppercase;font-family:{_FONT};">{e(str(c))}</th>'
            for c in rows_data[0]
        )
        body_rows = "".join(
            f'<tr bgcolor="{_TILE if i % 2 else "#ffffff"}">'
            + "".join(
                f'<td style="padding:6px 8px 6px 0;font-size:10px;color:{_INK};'
                f'font-family:{_FONT};border-bottom:1px solid {_RULE};">{e(str(c))}</td>'
                for c in row
            )
            + "</tr>"
            for i, row in enumerate(rows_data[1:])
        )
        tables_html += (
            f'<tr><td style="padding:16px 24px 0;">{section_head(heading)}{spacer(8)}'
            f'<table cellpadding="0" cellspacing="0" border="0" width="100%">'
            f"<tr>{head_cells}</tr>{body_rows}</table></td></tr>"
        )

    # ── Response box: the paper form delivered by email ──────────────────
    # An RFI/variation/delay asks for something back IN WRITING; the
    # orange-bordered fill-in table is what makes "reply typed into the
    # box" the path of least resistance. Empty rows, deliberately tall.
    response_html = ""
    if response_box:
        response_rows = "".join(
            f'<tr><td width="190" nowrap="nowrap" style="white-space:nowrap;padding:10px;'
            f"font-size:10.5px;font-weight:700;letter-spacing:1.4px;color:{_SLATE};"
            f'text-transform:uppercase;font-family:{_FONT};border-bottom:1px solid {_RULE};">{e(label)}</td>'
            f'<td style="padding:10px;border-bottom:1px solid {_RULE};font-size:11.5px;'
            f'color:{_INK};font-family:{_FONT};">&nbsp;</td></tr>'
            for label in response_box
        )
        response_html = (
            f'<tr><td style="padding:16px 24px 0;">{section_head("Your response")}{spacer(8)}'
            f'<table cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="border:2px solid {_ORANGE};">{response_rows}</table>'
            f"{spacer(4)}"
            f'<div style="font-size:10.5px;color:{_SLATE};font-family:{_FONT};">'
            f"Please complete the box above and reply to this email.</div></td></tr>"
        )

    # ── Attached documents ───────────────────────────────────────────────
    # ONLY files that are actually riding this email are named. Listing a
    # file the draft could not carry is worse than listing none: the
    # reader goes looking for a drawing that was never there.
    attached_html = ""
    if attached:
        rows_a = "".join(
            f'<div style="font-size:11.5px;color:{_INK};font-family:{_FONT};padding:2px 0;">&#128206;&nbsp;{e(n)}</div>'
            for n in attached
        )
        attached_html = (
            f'<tr><td style="padding:16px 24px 0;">{section_head("Attached documents")}{spacer(8)}{rows_a}</td></tr>'
        )

    # ── Notified block ───────────────────────────────────────────────────
    notified_html = ""
    if notified:
        # NAME, ADDRESS, DATE AND TIME. "Notified: Acme Electrical" is
        # not a record of anything six weeks later - it does not say which
        # address it reached or when. A dispute about whether a supplier
        # was told, and when, is settled by this block, so it carries all
        # four. Entries may arrive as (name, date) from older callers or
        # as (name, email, stamp); both render.
        def _row(entry: tuple) -> str:
            name = entry[0] if len(entry) > 0 else ""
            email_addr = entry[1] if len(entry) > 2 else ""
            stamp = entry[-1] if entry else ""
            who = e(str(name))
            if email_addr:
                who += f'<span style="color:{_PALE};">&nbsp;&lt;{e(str(email_addr))}&gt;</span>'
            return (
                f'<tr><td style="padding:4px 10px 4px 0;font-size:10.5px;color:{_SLATE};'
                f'font-family:{_FONT};">{who}</td>'
                f'<td align="right" nowrap="nowrap" style="white-space:nowrap;padding:4px 0;'
                f'font-size:10.5px;color:{_SLATE};font-family:{_FONT};">'
                f"Notified:&nbsp;{e(str(stamp))}</td></tr>"
            )

        notified_rows = "".join(_row(tuple(entry)) for entry in notified)
        notified_html = (
            f'<tr><td style="padding:16px 24px 0;">{section_head("Notified")}{spacer(8)}'
            f'<table cellpadding="0" cellspacing="0" border="0" width="100%">{notified_rows}</table></td></tr>'
        )

    # ── Footer: 1px rule + slate meta ────────────────────────────────────
    footer = (
        f'<tr><td style="padding:18px 24px 18px;">'
        f'<div style="border-top:1px solid {_RULE};padding-top:10px;font-size:10.5px;color:{_SLATE};'
        f'line-height:1.6;font-family:{_FONT};">{e(org_display_name())}'
        + (f"&nbsp;&nbsp;&middot;&nbsp;&nbsp;{e(footer_ref)}" if footer_ref else "")
        + "</div></td></tr>"
    )

    # LEFT, ON WHITE. This used to be a centred card floating on a grey
    # page - a marketing-newsletter shape. It is a work document: it sits
    # against the left margin on plain white, the way everything else in
    # a supplier's inbox does, and the reading column stays at _CARD_W so
    # a full-width monitor does not stretch the lines to nothing.
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#ffffff" '
        f'style="background:#ffffff;padding:8px 0;"><tr><td align="left">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="{_CARD_W}" bgcolor="#ffffff" '
        f'style="width:{_CARD_W}px;font-family:{_FONT};color:{_INK};">'
        f"{hero}{sub_bar}{lead}{details}{tables_html}{body_section}{attached_html}{response_html}{notified_html}{footer}"
        f"</table></td></tr></table>"
    )


# ── The same email, as plain text ────────────────────────────────────────

#: Where a plain-text line wraps. 78 leaves room for the "> " a client
#: adds when the supplier replies with the original quoted.
TEXT_WIDTH = 78

#: How far a continuation, or a second line of one value, is indented.
_TEXT_INDENT = "    "


def _text_heading(heading: str) -> list[str]:
    """A section head the way plain text does one: caps over a rule."""
    label = heading.upper()
    return ["", label, "-" * len(label)]


def _text_pair(label: str, value: str) -> list[str]:
    """``Label: value``, wrapped - a multi-line value on its own lines.

    A pasted paragraph or address block keeps its shape: the label
    announces it and the value sits underneath, indented, rather than
    being folded into one long run that loses where the lines were.
    """
    label = " ".join(str(label or "").split())
    raw = str(value or "")
    lines = [ln.rstrip() for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln.strip()]
    if len(lines) <= 1:
        one = lines[0].strip() if lines else ""
        return textwrap.wrap(
            f"{label}: {one}",
            width=TEXT_WIDTH,
            subsequent_indent=_TEXT_INDENT,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [f"{label}:"]
    out = [f"{label}:"]
    for ln in lines:
        out.extend(
            textwrap.wrap(
                ln.strip(),
                width=TEXT_WIDTH,
                initial_indent=_TEXT_INDENT,
                subsequent_indent=_TEXT_INDENT + "  ",
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [_TEXT_INDENT]
        )
    return out


def _text_paragraph(value: str) -> list[str]:
    """Free text, wrapped, with its own blank lines kept."""
    out: list[str] = []
    for ln in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not ln.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(ln.strip(), width=TEXT_WIDTH, break_long_words=False, break_on_hyphens=False))
    return out


def build_register_email_text(
    *,
    eyebrow: str,
    title: str,
    project_line: str,
    intro: str,
    pairs: list[tuple[str, str]],
    body_text: str = "",
    body_html: str = "",
    notified: list[tuple[str, ...]] | None = None,
    footer_ref: str = "",
    greeting: str = "Hi,",
    hero_right: str = "",
    response_box: list[str] | None = None,
    tables: list[tuple[str, list[list[str]]]] | None = None,
    attached: list[str] | None = None,
) -> str:
    """The SAME email as text/plain, built from the same structured data.

    Not a strip of the HTML. The HTML is a Word-engine table layout -
    flattening it gives a reader the label and the value on separate
    lines, the response box as a column of empty cells and the footer
    entity-encoded. Rendering the source data twice means the plain part
    reads like a document somebody wrote, and the two parts cannot drift:
    ``build_item_email`` hands both builders one dict of content.

    Same signature as :func:`build_register_email_html` deliberately, and
    the same money rail - ``strip_internal_pairs`` runs here too, so the
    text alternative can never carry an estimate the HTML withheld.
    """
    pairs = strip_internal_pairs(pairs)
    lines: list[str] = []

    # The heading line: what the subject says, so a reader scrolling a
    # plain-text client knows what this is before anything else.
    head = " - ".join(x for x in [str(eyebrow or "").upper(), str(title or ""), str(hero_right or "")] if x)
    if head:
        lines.append(head)
    if project_line:
        lines.extend(_text_pair("Project", project_line))
    if greeting:
        lines.extend(["", str(greeting)])
    if intro:
        lines.append("")
        lines.extend(_text_paragraph(intro))

    detail = [(k, v) for k, v in pairs if str(v).strip()]
    if detail:
        lines.extend(_text_heading("Details"))
        for k, v in detail:
            lines.extend(_text_pair(k, v))

    for heading, rows_data in tables or []:
        if not rows_data:
            continue
        lines.extend(_text_heading(heading))
        header = [str(c).strip() for c in rows_data[0]]
        lines.append(" | ".join(header))
        lines.append("-" * min(TEXT_WIDTH, max(12, len(" | ".join(header)))))
        for row in rows_data[1:]:
            lines.append(" | ".join(str(c).strip() for c in row))

    # The captured original arrives as markup and only as markup; that is
    # the one place the fallback converter belongs inside this builder.
    body = str(body_text or "").strip() or html_to_text(body_html)
    if body.strip():
        lines.extend(_text_heading("Message"))
        lines.extend(_text_paragraph(body))

    if attached:
        lines.extend(_text_heading("Attached documents"))
        lines.extend(f"- {n}" for n in attached)

    if response_box:
        lines.extend(_text_heading("Your response"))
        lines.extend(_text_paragraph("Please complete the lines below and reply to this email."))
        lines.append("")
        for label in response_box:
            lines.append(f"{label}: " + "_" * max(12, TEXT_WIDTH - len(str(label)) - 2))

    if notified:
        lines.extend(_text_heading("Notified"))
        for entry in notified:
            entry = tuple(entry)
            name = str(entry[0]) if entry else ""
            address = str(entry[1]) if len(entry) > 2 else ""
            stamp = str(entry[-1]) if entry else ""
            who = f"{name} <{address}>" if address else name
            lines.append(f"{who}  Notified: {stamp}".rstrip())

    # The footer is the middle dot the HTML writes as &middot; - here it
    # is the character itself, because nothing decodes entities for the
    # person reading the plain part.
    lines.extend(["", "--"])
    lines.append("  ·  ".join(x for x in [org_display_name(), str(footer_ref or "")] if x))

    # LF only, no trailing blanks: the mail library owns the CRLF, and a
    # run of empty lines is how a plain part starts looking like a fault.
    text = "\n".join(lines).replace("\r", "")
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n"
