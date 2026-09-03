# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Allowlist sanitiser for HTML that arrived from outside the business.

A supplier's quote body is attacker-controlled text that we render in the
buyer's own session. The first version of this used two blocklist regexes
and both were trivially walked around:

* ``<img src=x onerror=...>`` has no closing tag, so a "strip the whole
  element" regex never matched it, and the handler fired.
* ``<script src="//evil/x.js">`` unclosed survived whole.
* ``<img src="//tracker/open.gif">`` is protocol-relative, so a pattern
  anchored on ``https?://`` missed it - the read receipt fired **and the
  viewer told the buyer remote content had been blocked**. Lying about a
  security control is worse than not having one.

Blocklists lose this game by construction: they have to enumerate every
attack, the allowlist only has to enumerate what a quote email needs.
This is a tokeniser-driven allowlist - unknown tag, unknown attribute or
unknown URL scheme is dropped, and anything genuinely dangerous takes its
text content with it.

No third-party dependency on purpose: this ships to a self-hosted box
that is often offline, and ``html.parser`` is in the standard library.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

#: Elements a formatted business email is allowed to use. Anything not
#: named here is dropped, though its text is kept (an unknown wrapper is
#: usually harmless markup around real words).
ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "div",
        "span",
        "hr",
        "pre",
        "blockquote",
        "center",
        "b",
        "strong",
        "i",
        "em",
        "u",
        "s",
        "strike",
        "small",
        "sub",
        "sup",
        "font",
        "code",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "dl",
        "dt",
        "dd",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "td",
        "th",
        "caption",
        "colgroup",
        "col",
        "a",
        "img",
    }
)

#: Elements whose CONTENT is dropped too. Keeping the text of a <script>
#: would paste its source into the page as visible words, and <svg> and
#: <math> carry their own scripting surface.
_DROP_WITH_CONTENT = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "applet",
        "svg",
        "math",
        "template",
        "noscript",
        "frame",
        "frameset",
        "form",
        "base",
        "link",
        "meta",
        "title",
        "head",
    }
)

_VOID = frozenset({"br", "hr", "img", "col"})

#: Attributes per element. Deliberately small - table geometry is what a
#: quote actually uses. Note the absence of ``style`` (it carries
#: ``url()``, ``expression()`` and positioning games) and of every
#: ``on*`` handler, which are what made this exploitable.
_GLOBAL_ATTRS = frozenset({"align", "valign", "dir", "lang", "title"})
_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "name", "target"}),
    "img": frozenset({"src", "alt", "width", "height", "border"}),
    "table": frozenset({"width", "border", "cellpadding", "cellspacing", "bgcolor"}),
    "col": frozenset({"width", "span"}),
    "colgroup": frozenset({"width", "span"}),
    "td": frozenset({"colspan", "rowspan", "width", "height", "bgcolor", "nowrap"}),
    "th": frozenset({"colspan", "rowspan", "width", "height", "bgcolor", "nowrap"}),
    "tr": frozenset({"bgcolor", "height"}),
    "font": frozenset({"color", "face", "size"}),
    "ol": frozenset({"start", "type"}),
}

#: Schemes an ``href`` may use. ``javascript:``/``vbscript:``/``data:``
#: are all absent on purpose.
_SAFE_HREF = ("http://", "https://", "mailto:", "tel:")

#: An inline image may only come from the message's own MIME parts
#: (``cid:``) or be embedded outright (``data:image/``). Both are already
#: in the file - neither one phones anybody when rendered.
_SAFE_IMG = ("cid:", "data:image/")

#: Whitespace INSIDE a scheme is how ``java\tscript:`` gets past a naive
#: prefix check: the browser strips control characters before parsing.
_URL_STRIP = re.compile(r"[\x00-\x20\x7f]+")

#: Any absolute or protocol-relative reference. Used only to report
#: honestly that something was removed.
_LOOKS_REMOTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.I)


def _clean_url(value: str, allowed: tuple[str, ...]) -> str | None:
    """The URL if its scheme is allowed, else ``None``."""
    cleaned = _URL_STRIP.sub("", value or "")
    lowered = cleaned.lower()
    if lowered.startswith(allowed):
        return cleaned
    # A relative link (no scheme, no leading //) is harmless and common
    # in quoted replies. Everything else - including "//host/x" - goes.
    if ":" not in lowered.split("/")[0] and not lowered.startswith("//"):
        return cleaned or None
    return None


class _Sanitiser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open_tags: list[str] = []
        self._skip_depth = 0
        self._skip_tag = ""
        self.blocked_remote = False

    # -- helpers ---------------------------------------------------------
    def _attrs_for(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        allowed = _ATTRS.get(tag, frozenset()) | _GLOBAL_ATTRS
        parts: list[str] = []
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            value = raw_value if raw_value is not None else ""
            # ``on*`` never reaches the allowlist anyway; checked
            # explicitly so the intent survives an edit to _ATTRS.
            if name.startswith("on") or name not in allowed:
                if name in ("src", "background", "srcset", "poster", "style", "href") or name.startswith("on"):
                    if _LOOKS_REMOTE.match(_URL_STRIP.sub("", value)):
                        self.blocked_remote = True
                continue
            if name in ("href", "src"):
                safe = _clean_url(value, _SAFE_HREF if name == "href" else _SAFE_IMG)
                if safe is None:
                    if _LOOKS_REMOTE.match(_URL_STRIP.sub("", value)):
                        self.blocked_remote = True
                    continue
                value = safe
            parts.append(f'{name}="{escape(value, quote=True)}"')
        if tag == "a" and any(p.startswith('href="http') for p in parts):
            # An external link opened from an email viewer should not be
            # able to reach back through window.opener.
            parts.append('rel="noopener noreferrer nofollow"')
        return (" " + " ".join(parts)) if parts else ""

    # -- parser callbacks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag in _DROP_WITH_CONTENT:
            # ``<script src=...>`` unclosed used to survive whole. Now the
            # rest of the document is dropped with it, which is the safe
            # way round: a truncated quote is readable, an executed one
            # is a session.
            self._skip_depth = 1
            self._skip_tag = tag
            if tag in ("script", "iframe", "object", "embed", "link"):
                self.blocked_remote = True
            return
        if tag not in ALLOWED_TAGS:
            return
        rendered = self._attrs_for(tag, attrs)
        if tag in _VOID:
            self.out.append(f"<{tag}{rendered}>")
            return
        self.out.append(f"<{tag}{rendered}>")
        self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth or tag in _DROP_WITH_CONTENT or tag not in ALLOWED_TAGS:
            if tag in _DROP_WITH_CONTENT:
                self.blocked_remote = self.blocked_remote or tag in ("script", "iframe", "object", "embed", "link")
            return
        self.out.append(f"<{tag}{self._attrs_for(tag, attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if not self._skip_depth:
                    self._skip_tag = ""
            return
        if tag in _VOID or tag not in ALLOWED_TAGS or tag not in self.open_tags:
            return
        # Close back to the matching tag so a stray </td> cannot unbalance
        # the surrounding page.
        while self.open_tags:
            open_tag = self.open_tags.pop()
            self.out.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.out.append(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        # Conditional comments are executable in Outlook/IE-derived
        # renderers, and nothing in a quote needs a comment to survive.
        return

    def handle_decl(self, decl: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def result(self) -> str:
        while self.open_tags:
            self.out.append(f"</{self.open_tags.pop()}>")
        return "".join(self.out)


def sanitise_html(raw: str) -> tuple[str, bool]:
    """``(safe_html, something_remote_was_removed)``.

    The flag is the honest version of what the viewer used to claim: it
    is true only when a remote reference or an active element was
    actually taken out.
    """
    if not raw:
        return "", False
    parser = _Sanitiser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # pragma: no cover - malformed input must not 500
        # Degrade to text: better a plain-looking quote than a traceback
        # in the reader's face, and never the raw HTML as a fallback.
        return escape(raw, quote=False), True
    return parser.result(), parser.blocked_remote
