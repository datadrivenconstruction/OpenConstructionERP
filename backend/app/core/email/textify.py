# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""HTML → readable plain text, with no dependencies.

Every message this platform generates is multipart: a text/html part and
a text/plain alternative beside it. The plain part is not decoration. A
gateway that strips HTML, a phone client set to plain text, a spam
filter scoring the two parts against each other and an accessibility
reader all read THAT one - and for a long time every register email put
a single stub line there ("This message requires an HTML-capable mail
client"), so a supplier whose client preferred plain text was sent an
RFQ containing no RFQ.

Where the structured content is still in hand the text part is BUILT
from it (``outbound.build_register_email_text``), because a document
rendered from its data reads better than one recovered from its markup.
This module is the fallback for the payloads that arrive as HTML and
nothing else - a captured original, a template-rendered notification.

It is deliberately small and regex-based: no bs4, no lxml, nothing that
can fail to install on a site's own server. It handles the shapes our
own HTML actually uses - the Word-engine table layout the register
emails are built from - rather than pretending to be a browser.
"""

from __future__ import annotations

import html as _html
import re

#: Whole elements whose CONTENT is not readable text.
_DROPPED = re.compile(r"(?is)<\s*(script|style|head|title)\b[^>]*>.*?<\s*/\s*\1\s*>")

_BR = re.compile(r"(?i)<\s*br\s*/?\s*>")
_LI_OPEN = re.compile(r"(?i)<\s*li\b[^>]*>")

#: A table cell ENDS at a separator, not a line break: "LABEL | value" is
#: how a two-column details row reads out loud. The trailing separator
#: each row is left with is trimmed per line below.
_CELL_END = re.compile(r"(?i)<\s*/\s*(td|th)\s*>")

#: Everything that ends a block ends a line.
_BLOCK = re.compile(
    r"(?i)<\s*/?\s*(tr|table|thead|tbody|p|div|h[1-6]|li|ul|ol|blockquote"
    r"|section|header|footer|article|pre|hr)\b[^>]*>"
)

_TAG = re.compile(r"(?s)<[^>]+>")
_RUN_OF_SPACES = re.compile(r"[ \t]{2,}")
_BLANK_RUN = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """One HTML body as plain text a person can read and reply to.

    Block tags become line breaks, ``<br>`` becomes one newline, table
    cells are joined with " | " and rows broken onto their own lines,
    list items get a leading "- ", every remaining tag is dropped and
    every entity is decoded - so no ``&nbsp;``, ``&#x27;`` or ``&middot;``
    survives into the part a human reads. Blank runs collapse to one
    blank line; the result is LF-only, so the mail library owns the CRLF.
    """
    if not html:
        return ""
    text = str(html)
    text = _DROPPED.sub(" ", text)
    text = _BR.sub("\n", text)
    text = _LI_OPEN.sub("\n- ", text)
    text = _CELL_END.sub(" | ", text)
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub("", text)
    # AFTER the tags are gone, never before: unescaping first would turn
    # "&lt;script&gt;" in somebody's quoted text into a tag the stripper
    # would then eat, silently deleting the words around it.
    text = _html.unescape(text)
    # &nbsp; decodes to U+00A0, which is not a space to anything that
    # wraps or trims text, and zero-width joiners are invisible litter.
    text = text.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines: list[str] = []
    for raw in text.split("\n"):
        line = _RUN_OF_SPACES.sub(" ", raw).strip()
        # A row ends "value | " and starts " | LABEL" only because the
        # separator belongs BETWEEN cells.
        line = line.strip("|").strip() if line in {"|", "||"} else line
        while line.endswith("|"):
            line = line[:-1].rstrip()
        while line.startswith("|"):
            line = line[1:].lstrip()
        lines.append(line)
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()
