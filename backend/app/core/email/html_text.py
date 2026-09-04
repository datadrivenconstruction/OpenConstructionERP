# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTML to plain text for the ``multipart/alternative`` text part.

Every outbound mail is authored as HTML and the plain-text alternative is
derived from it, so whatever this module drops is simply missing for a
recipient who reads plain text.  A hyperlink is the one thing that cannot
be dropped: the anchor text is a label, the ``href`` is the whole content.
A tag-stripping regex keeps the label and deletes the destination, which
turned the password-reset mail into the words "Reset password" with no
URL anywhere in the message - a plain-text reader could not reset their
password at all.

So the tags are parsed rather than pattern-matched.  ``html.parser`` is
stdlib, knows where an attribute value ends (a regex over ``<[^>]+>`` does
not: a ``>`` inside a quoted attribute cuts the tag in the wrong place),
and resolves character references itself, which is what makes ``&amp;`` in
a query string come back as ``&``.  The same choice was already made for
the inbound direction in ``app.modules.inbound_email.eml_parser``; that
extractor is not imported here because ``app.core`` must keep working when
an optional module is not installed, and because its contract differs -
it rebuilds line structure for a human reading a recovered body, while
this one produces the single flowed paragraph the MIME part has always
carried.

Anchors are rendered the way plain-text mail conventionally renders them,
the label followed by the target in angle brackets::

    Reset password <https://app.example.com/reset?token=abc&uid=42>

An anchor whose text already is the destination prints once, and an
anchor with no usable target (a bare fragment, ``javascript:``) prints its
text alone.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

__all__ = ["html_to_text"]

_WHITESPACE_RE = re.compile(r"\s+")

#: Elements whose text is markup machinery, never message content.
_SKIP = frozenset({"script", "style", "head", "title"})

#: Targets that mean nothing to a mail reader and are not worth printing.
_DEAD_SCHEMES = ("javascript:", "data:", "about:")

#: Stripped before comparing an anchor's text with its target, so that
#: ``<a href="mailto:info@x.io">info@x.io</a>`` is recognised as one thing
#: said twice rather than a label plus a separate address.
_COMPARABLE_SCHEMES = ("https://", "http://", "mailto:", "tel:")


def _canonical(value: str) -> str:
    """Reduce a URL to the part worth comparing (no scheme, no trailing slash)."""
    trimmed = value.strip().rstrip("/")
    lowered = trimmed.lower()
    for scheme in _COMPARABLE_SCHEMES:
        if lowered.startswith(scheme):
            return trimmed[len(scheme) :]
    return trimmed


class _PlainTextExtractor(HTMLParser):
    """Collect the readable text of a mail body, keeping link targets.

    Text is accumulated in fragments.  Every tag boundary contributes a
    space so adjacent elements never fuse into one word, and the result is
    whitespace-collapsed at the end - the plain part is a single flowed
    paragraph, which is what it has always been.

    Anchors are tracked on a stack of ``(href, first fragment index)``.  The
    index marks where the anchor's own text begins, so on the closing tag
    the text that was collected inside it can be compared with the target
    before deciding whether the target still needs printing.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._anchors: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        self._parts.append(" ")
        if tag == "a":
            # ``attrs`` values arrive with character references already
            # resolved, so a query string written ``&amp;`` in the HTML is
            # the ``&`` the recipient has to type.
            href = next((v.strip() for k, v in attrs if k == "href" and v), "")
            self._anchors.append((href, len(self._parts)))

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._anchors:
            href, start = self._anchors.pop()
            self._emit_target(href, "".join(self._parts[start:]))
        self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def _emit_target(self, href: str, anchor_text: str) -> None:
        """Append ``<href>`` unless it would be noise or a repetition."""
        if not href or href.startswith("#"):
            return
        if href.lower().startswith(_DEAD_SCHEMES):
            return
        seen = _WHITESPACE_RE.sub(" ", anchor_text).strip()
        if seen and _canonical(seen) == _canonical(href):
            return
        self._parts.append(f" <{href}>")

    def get_text(self) -> str:
        """Return the collected text as one whitespace-collapsed paragraph."""
        return _WHITESPACE_RE.sub(" ", "".join(self._parts)).strip()


def html_to_text(html: str) -> str:
    """Render *html* as the plain-text alternative of a mail body.

    Args:
        html: The rendered HTML body of an outgoing message.

    Returns:
        The readable text with every link target preserved, collapsed to a
        single flowed paragraph.  Malformed markup degrades to whatever text
        can be recovered rather than raising - the plain part must never be
        the reason a message fails to send.
    """
    parser = _PlainTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text()
