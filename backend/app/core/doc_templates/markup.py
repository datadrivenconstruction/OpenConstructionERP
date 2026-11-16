# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The small text format of document blocks, converted by us, never by a browser.

Supported: ``**bold**``, ``*italic*``, a single line break, a blank line
between paragraphs, ``- `` bullet lines and, in email only, ``[label](url)``
links whose URL starts with ``https://`` or ``mailto:``. Raw HTML is refused by
validation and, should it reach a renderer anyway, is printed as text because
the template is escaped before any markup is applied. Merge values are escaped
on their own and inserted last, so a value can never become markup.
"""

from __future__ import annotations

import html
import re
from collections.abc import Collection, Mapping

from app.core.doc_templates.merge import TOKEN_RE, render

__all__ = ["has_raw_html", "paragraphs", "to_html", "to_plain", "to_reportlab", "unsafe_links"]

_HTML_RE = re.compile(r"<\s*/?\s*[A-Za-z!?]")
_LINK_RE = re.compile(r"\[([^\]\n]{1,200})\]\(([^)\s]{1,500})\)")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC_RE = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_SAFE_SCHEMES = ("https://", "mailto:")


def has_raw_html(text: str | None) -> bool:
    """Whether *text* contains something that looks like an HTML tag."""
    return bool(_HTML_RE.search(text or ""))


def unsafe_links(text: str | None) -> list[str]:
    """Link targets that are not ``https://`` or ``mailto:``."""
    return [m.group(2) for m in _LINK_RE.finditer(text or "") if not m.group(2).lower().startswith(_SAFE_SCHEMES)]


def paragraphs(text: str | None) -> list[str]:
    """Split on blank lines; empty paragraphs are dropped."""
    return [p.strip("\n") for p in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n")) if p.strip()]


def _values_escaped(values: Mapping[str, object]) -> dict[str, str]:
    return {k: html.escape("" if v is None else str(v), quote=True) for k, v in values.items()}


def _inline(escaped: str, *, links: bool, bold_tag: str, italic_tag: str) -> str:
    def _link(match: re.Match[str]) -> str:
        label, url = match.group(1), html.unescape(match.group(2))
        if links and url.lower().startswith(_SAFE_SCHEMES):
            return f'<a href="{html.escape(url, quote=True)}">{label}</a>'
        return label

    out = _LINK_RE.sub(_link, escaped)
    out = _BOLD_RE.sub(lambda m: f"<{bold_tag}>{m.group(1)}</{bold_tag}>", out)
    return _ITALIC_RE.sub(lambda m: f"<{italic_tag}>{m.group(1)}</{italic_tag}>", out)


def to_reportlab(text: str | None, values: Mapping[str, object], known: Collection[str] | None = None) -> list[str]:
    """One reportlab ``Paragraph`` markup string per paragraph. Never raises."""
    escaped_values = _values_escaped(values)
    out: list[str] = []
    for para in paragraphs(text):
        lines = []
        for line in para.split("\n"):
            bullet = _BULLET_RE.match(line)
            body = html.escape(bullet.group(1) if bullet else line, quote=False)
            body = _inline(body, links=False, bold_tag="b", italic_tag="i")
            lines.append(("• " + body) if bullet else body)
        out.append(render("<br/>".join(lines), escaped_values, known))
    return out


def to_html(text: str | None, values: Mapping[str, object], known: Collection[str] | None = None) -> str:
    """Email HTML for *text*: ``<p>`` per paragraph, ``<ul>`` for bullet runs. Never raises."""
    escaped_values = _values_escaped(values)
    parts: list[str] = []
    for para in paragraphs(text):
        lines = para.split("\n")
        if all(_BULLET_RE.match(line) for line in lines):
            items = "".join(
                "<li>"
                + _inline(
                    html.escape(_BULLET_RE.match(line).group(1), quote=False),
                    links=True,
                    bold_tag="strong",
                    italic_tag="em",
                )
                + "</li>"  # type: ignore[union-attr]
                for line in lines
            )
            parts.append(f"<ul>{items}</ul>")
            continue
        body = "<br/>".join(
            _inline(html.escape(line, quote=False), links=True, bold_tag="strong", italic_tag="em") for line in lines
        )
        parts.append(f"<p>{body}</p>")
    return render("".join(parts), escaped_values, known)


def to_plain(text: str | None, values: Mapping[str, object], known: Collection[str] | None = None) -> str:
    """Plain text with markup markers removed (subjects, file titles). Never raises."""
    raw = render(text, values, known) if TOKEN_RE.search(text or "") else (text or "")
    raw = _LINK_RE.sub(lambda m: m.group(1), raw)
    raw = _BOLD_RE.sub(lambda m: m.group(1), raw)
    return _ITALIC_RE.sub(lambda m: m.group(1), raw).strip()
