"""Input sanitization for user-supplied text.

We don't want to run user text through a full HTML sanitizer (``bleach``)
because most construction-ERP fields (project descriptions, BOQ positions,
RFI subjects) are *not* rich text — they're plain strings that occasionally
contain characters like ``<`` for dimensions ("beam <200mm"). Stripping all
HTML would mangle legitimate content.

Instead, this module removes the **dangerous** subset of HTML that attackers
use for stored XSS while leaving literal angle brackets alone:

  * ``<script>…</script>`` blocks  — content + tags removed
  * ``<iframe>``, ``<object>``, ``<embed>``, ``<svg>`` — content + tags removed
  * ``on*="…"`` event-handler attributes — attribute removed
  * ``javascript:`` / ``vbscript:`` / ``data:text/html`` URIs — replaced with ``#``

The result is safe to render with ``dangerouslySetInnerHTML`` or in plain
text contexts. Normal text like ``"beam <200mm section"`` survives verbatim.

Design constraints:
    - stdlib only (no ``bleach``, no ``html5lib``)
    - idempotent: ``strip_dangerous_html(strip_dangerous_html(s)) == strip_dangerous_html(s)``
    - never raises — bad input returns best-effort cleaned output
    - control characters (``\\x00..\\x1f`` except ``\\t \\n \\r``) rejected separately
      via :func:`reject_control_chars`, because silently stripping them would
      mask a misuse / encoding bug in the caller
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "DEFAULT_MAX_TEXT_LENGTH",
    "has_dangerous_html",
    "reject_control_chars",
    "safe_text",
    "sanitise_text",
    "strip_all_html_tags",
    "strip_dangerous_html",
]


# Max length for a free-text field. 10k covers description + notes fields
# comfortably; above that a request is almost certainly abuse.
DEFAULT_MAX_TEXT_LENGTH: Final[int] = 10_000


# Control characters that we outright reject — null bytes, bell, backspace,
# form feed, vertical tab, shift out/in, device-control, escape, etc.
# Tab (\x09), newline (\x0a), carriage return (\x0d) are *kept* — they show up
# in legitimate multi-line descriptions. 0x7f (DEL) is rejected.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Dangerous-HTML stripper
# ---------------------------------------------------------------------------

# Tags whose *entire content* must go with them. Scripts, iframes and SVG
# often embed active content that we don't want to store verbatim even
# for display purposes.
_BLOCK_TAG_RE = re.compile(
    r"<\s*(?P<tag>script|iframe|object|embed|svg|math|style|link|meta|base)\b[^>]*>"
    r".*?"
    r"<\s*/\s*(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)

# Unterminated / orphan opening tag that never gets closed. Runs to end of
# input — e.g. ``<script>alert(1)`` with the close stripped off to bypass
# the paired matcher above. Intentionally greedy (``.*``) so nothing after
# the opening can leak through.
_BLOCK_TAG_UNTERMINATED_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed|svg|math|style|link|meta|base)\b.*",
    re.IGNORECASE | re.DOTALL,
)

# Opening-only version for self-closing variants like
# ``<iframe src="evil.com" />`` that have no matching close tag and no
# body to drop.
_BLOCK_TAG_OPEN_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed|svg|math|style|link|meta|base)\b[^>]*/?>",
    re.IGNORECASE,
)

# Inline event handler attributes: ``onerror="…"``, ``onclick='…'``,
# ``onmouseover=...`` (no quotes). Covers the attribute anywhere inside a
# tag, space before required to avoid matching inside names like
# ``<custom-onfoo="x">``.
_EVENT_HANDLER_RE = re.compile(
    r"""\s+on[a-z]+                      # on-prefix event name
        \s*=\s*                          # =
        (?:
            "[^"]*"                      # double-quoted value
          | '[^']*'                      # single-quoted value
          | [^\s>]+                      # unquoted value (stops at space / >)
        )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Dangerous URI schemes inside ``href=`` / ``src=`` / ``action=``.
_DANGEROUS_URI_RE = re.compile(
    r"""(?P<attr>(?:href|src|action|formaction|xlink:href)\s*=\s*)
        (?P<quote>['"]?)
        \s*
        (?:
            javascript
          | vbscript
          | data\s*:\s*text/html
          | livescript
          | mocha
        )
        \s*:
        [^'">\s]*
        (?P=quote)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def strip_dangerous_html(value: str) -> str:
    """Remove XSS-dangerous HTML from *value*, return the cleaned string.

    Never raises. Empty / ``None``-ish input returns ``""``.
    """
    if not value:
        return ""
    # 1. Drop paired blocks (``<script>`` … ``</script>``) — content has to
    # go because the browser would execute it otherwise.
    cleaned = _BLOCK_TAG_RE.sub("", value)
    # 2. Drop orphan openings that never get closed (``<script>alert(1)``
    # at EOF). This runs to end-of-string so nothing leaks through.
    cleaned = _BLOCK_TAG_UNTERMINATED_RE.sub("", cleaned)
    # 3. Catch remaining self-closing / attribute-only variants.
    cleaned = _BLOCK_TAG_OPEN_RE.sub("", cleaned)
    # 4. Remove event-handler attributes from whatever tags remain.
    cleaned = _EVENT_HANDLER_RE.sub("", cleaned)
    # 5. Neutralise dangerous URI schemes — replace with ``href="#"``.
    cleaned = _DANGEROUS_URI_RE.sub(r'\g<attr>\g<quote>#\g<quote>', cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Response-layer plain-text strip (BUG-MATH04)
# ---------------------------------------------------------------------------
#
# Applied at the *output* layer (response models) on free-text BOQ / project
# fields. Input validators only strip *dangerous* HTML — that leaves benign
# tags like ``<b>`` or ``<u>`` in storage. If a frontend ever wraps such a
# field in ``dangerouslySetInnerHTML`` (some BOQ panels historically did),
# even benign tags become an injection foothold once attacker-controlled
# attribute fuzzing finds a ReportLab / browser-parser corner case.
#
# The response-layer strip is therefore deliberately stronger:
#
#   * removes the *content* of script/style/iframe/etc. blocks entirely
#     (``<script>alert(1)</script>foo`` → ``foo``)
#   * removes the *tags* of every other element while preserving their text
#     (``<b>Bold</b> text`` → ``Bold text``)
#   * decodes basic numeric and named HTML entities so consumers see real
#     text, not ``&amp;`` (matters for downstream search / OCR / exports)
#
# Stored data is left untouched — only the API JSON output is sanitised.
# This keeps ``BOQCreate.description = "beam <200mm"`` round-tripping
# visually intact (literal ``<`` survives because ``<200mm`` is not a tag
# pattern — there's no closing ``>`` paired with a tag-name lead char).

# A real opening or closing HTML tag: starts with ``<`` then either ``/`` or
# an ASCII letter, then anything up to the next ``>``. The leading ``[A-Za-z/]``
# guard is what saves literal ``"<200mm"`` style text from being eaten.
_ANY_HTML_TAG_RE = re.compile(r"<[A-Za-z/][^>]*>")

# Block tags whose *body* must be dropped along with the tags themselves.
# Same set as ``_BLOCK_TAG_RE`` above; duplicated as a separate compiled
# pattern so the two stripping flows can evolve independently.
_DESTRUCTIVE_BLOCK_RE = re.compile(
    r"<\s*(?P<tag>script|iframe|object|embed|svg|math|style|link|meta|base)\b[^>]*>"
    r".*?"
    r"<\s*/\s*(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)

# Unterminated destructive opener — same rationale as ``_BLOCK_TAG_UNTERMINATED_RE``
# but kept local so the two flows don't share state.
_DESTRUCTIVE_BLOCK_UNTERMINATED_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed|svg|math|style|link|meta|base)\b.*",
    re.IGNORECASE | re.DOTALL,
)

# A small set of named entities seen in legitimate construction text. Anything
# beyond this stays escaped (we'd rather show ``&xyz;`` than guess).
_NAMED_ENTITIES: Final[dict[str, str]] = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
    "nbsp": "\u00a0",
}

_NUMERIC_ENTITY_RE = re.compile(r"&#(\d+);")
_HEX_ENTITY_RE = re.compile(r"&#[xX]([0-9a-fA-F]+);")
_NAMED_ENTITY_RE = re.compile(r"&([a-zA-Z]+);")


def _decode_entities(text: str) -> str:
    """Decode the small set of HTML entities we care about.

    Stdlib ``html.unescape`` would also work, but it's eager — it would
    decode ``&copy;`` and friends, and those are rare enough in BOQ /
    project text that we'd rather leave them untouched and easy to spot.
    """

    def _num(match: re.Match[str]) -> str:
        try:
            cp = int(match.group(1))
        except ValueError:
            return match.group(0)
        if 0 < cp <= 0x10FFFF:
            try:
                return chr(cp)
            except (ValueError, OverflowError):
                return match.group(0)
        return match.group(0)

    def _hex(match: re.Match[str]) -> str:
        try:
            cp = int(match.group(1), 16)
        except ValueError:
            return match.group(0)
        if 0 < cp <= 0x10FFFF:
            try:
                return chr(cp)
            except (ValueError, OverflowError):
                return match.group(0)
        return match.group(0)

    def _named(match: re.Match[str]) -> str:
        return _NAMED_ENTITIES.get(match.group(1).lower(), match.group(0))

    text = _NUMERIC_ENTITY_RE.sub(_num, text)
    text = _HEX_ENTITY_RE.sub(_hex, text)
    text = _NAMED_ENTITY_RE.sub(_named, text)
    return text


def strip_all_html_tags(value: str) -> str:
    """Strip every HTML tag and return plain text only.

    Stronger than :func:`strip_dangerous_html`:

    * ``<script>x</script>`` → ``''`` (body dropped along with the tags)
    * ``<b>Bold</b> text``    → ``Bold text``
    * ``<div><span>hi</span></div>`` → ``hi``
    * ``"beam <200mm"``       → ``"beam <200mm"`` (no tag pattern, kept)
    * ``"a < b > c"``          → ``"a < b > c"`` (same — literal math, not tags)
    * trailing whitespace from removed tags is collapsed

    Never raises; ``None`` / empty input returns ``""``.
    """
    if not value:
        return ""
    # 1. Drop destructive blocks with their content first — otherwise the
    # generic tag stripper would leave the body behind ("alert(1)").
    cleaned = _DESTRUCTIVE_BLOCK_RE.sub("", value)
    cleaned = _DESTRUCTIVE_BLOCK_UNTERMINATED_RE.sub("", cleaned)
    # 2. Strip every remaining real HTML tag (opening, closing, self-closing).
    # The regex requires a tag-name lead character so literal ``"<200mm"``
    # survives unscathed.
    cleaned = _ANY_HTML_TAG_RE.sub("", cleaned)
    # 3. Decode the small entity subset — stored ``&amp;`` should display
    # as ``&`` once the tags are gone.
    cleaned = _decode_entities(cleaned)
    # 4. Collapse runs of whitespace introduced by tag removal but keep
    # newlines (multi-line descriptions are legitimate). Tabs collapse to
    # single space; multiple spaces collapse to one.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    return cleaned.strip()


def sanitise_text(value: str | None) -> str | None:
    """Plain-text-only sanitiser for response model fields (BUG-MATH04).

    Wraps :func:`strip_all_html_tags` with ``None``-passthrough so it can
    be plugged into Pydantic ``@field_validator(mode="after")`` for
    optional fields without an extra branch in every validator.

    Returns ``None`` if input is ``None`` (preserves "field not set" vs
    "field set to empty"); empty string returns ``""``.
    """
    if value is None:
        return None
    return strip_all_html_tags(value)


def has_dangerous_html(value: str) -> bool:
    """Return True if *value* contains any of the patterns we'd strip.

    Useful for schema validators that would rather reject the whole
    request with a 422 than silently swallow content.
    """
    if not value:
        return False
    return bool(
        _BLOCK_TAG_RE.search(value)
        or _BLOCK_TAG_UNTERMINATED_RE.search(value)
        or _BLOCK_TAG_OPEN_RE.search(value)
        or _EVENT_HANDLER_RE.search(value)
        or _DANGEROUS_URI_RE.search(value)
    )


# ---------------------------------------------------------------------------
# Control-char rejection
# ---------------------------------------------------------------------------


def reject_control_chars(value: str, field: str = "value") -> str:
    """Return *value* stripped; raise ValueError if it contains control chars.

    Used by Pydantic field validators to catch intermediate-form-data-leak
    style bugs where binary payloads end up in text columns.
    """
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{field} contains control characters")
    return value.strip()


# ---------------------------------------------------------------------------
# High-level helper combining both
# ---------------------------------------------------------------------------


def safe_text(
    value: str,
    *,
    field: str = "value",
    max_length: int = DEFAULT_MAX_TEXT_LENGTH,
    strip_html: bool = True,
) -> str:
    """Sanitise free-text user input.

    - Strips leading/trailing whitespace.
    - Rejects control characters (``ValueError``).
    - Enforces a length cap (``ValueError`` if exceeded).
    - Removes XSS-dangerous HTML (script/iframe/on* handlers/dangerous URIs).

    Keeps literal ``<`` / ``>`` / quotes so text like ``"beam <200mm"``
    round-trips exactly.
    """
    cleaned = reject_control_chars(value, field=field)
    if len(cleaned) > max_length:
        raise ValueError(
            f"{field} exceeds maximum length of {max_length} characters"
        )
    if strip_html:
        cleaned = strip_dangerous_html(cleaned)
    return cleaned
