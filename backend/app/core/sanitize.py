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
