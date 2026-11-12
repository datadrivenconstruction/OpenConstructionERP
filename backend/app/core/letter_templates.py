# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Registry of editable letter texts.

A module that writes a letter or an email to someone outside the platform
(award letter, rejection notice, invitation to tender) registers a
:class:`LetterTemplate` here: a key such as ``tendering.award_letter``, the
placeholders the letter offers and the default wording per language. The
``letter_templates`` module stores what users change; this file only knows the
shipped defaults and the rules every text obeys, so it imports nothing from the
database layer.

Text model, deliberately small so an estimator can read it:

* four fields per language: ``subject`` (file title or email subject),
  ``heading`` (the line printed above the body), ``body`` (paragraphs separated
  by a blank line) and ``closing`` (the sign-off above the sender's name);
* placeholders are ``{name}``. A known placeholder is replaced, an unknown one
  is printed as written and never raises;
* a line whose placeholder has no value is left out, so an optional fact
  (a deadline that was never set) does not leave half a sentence behind.

Renderers escape the substituted result themselves; the values here are plain
text.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

__all__ = [
    "PLACEHOLDER_RE",
    "LetterIssue",
    "LetterTemplate",
    "LetterText",
    "Placeholder",
    "all_templates",
    "check_text",
    "default_text",
    "get_template",
    "placeholders_in",
    "register_template",
    "render",
    "split_paragraphs",
    "template_language",
]

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: Field length caps, enforced by :func:`check_text` and the API schema.
MAX_LINE = 500
MAX_BODY = 20_000

FIELDS: tuple[str, ...] = ("subject", "heading", "body", "closing")


@dataclass(frozen=True)
class Placeholder:
    """One value a letter can insert.

    Attributes:
        name: The token inside braces, e.g. ``amount`` for ``{amount}``.
        sample: Value used by the editor preview.
        required: Saving a text without it raises a warning.
    """

    name: str
    sample: str
    required: bool = False


@dataclass(frozen=True)
class LetterText:
    """The editable wording of one letter in one language."""

    subject: str = ""
    heading: str = ""
    body: str = ""
    closing: str = ""

    def as_dict(self) -> dict[str, str]:
        """The four fields as a plain dict."""
        return {"subject": self.subject, "heading": self.heading, "body": self.body, "closing": self.closing}


@dataclass(frozen=True)
class LetterIssue:
    """A validation finding on a letter text.

    ``severity`` is ``error`` (save refused) or ``warning`` (saved, shown).
    """

    code: str
    severity: str
    field: str
    placeholder: str = ""


@dataclass(frozen=True)
class LetterTemplate:
    """A registered letter.

    Attributes:
        key: Stable id, ``<module>.<letter>``.
        module: Module that owns and renders the letter (for grouping).
        kind: ``pdf`` or ``email``.
        placeholders: Values the renderer supplies.
        defaults: Shipped wording per language code.
        default_language: Fallback language, must be in *defaults*.
        preview: Optional ``(text, language) -> (bytes, media_type)`` renderer
            with sample values, used by the editor's live preview.
    """

    key: str
    module: str
    kind: str
    placeholders: tuple[Placeholder, ...]
    defaults: Mapping[str, LetterText]
    default_language: str = "en"
    preview: Callable[[LetterText, str], tuple[bytes, str]] | None = field(default=None, compare=False)

    @property
    def languages(self) -> tuple[str, ...]:
        """Languages with shipped defaults."""
        return tuple(self.defaults)

    @property
    def placeholder_names(self) -> frozenset[str]:
        """Names of every placeholder this letter offers."""
        return frozenset(p.name for p in self.placeholders)

    def samples(self) -> dict[str, str]:
        """Sample values for a preview."""
        return {p.name: p.sample for p in self.placeholders}


_REGISTRY: dict[str, LetterTemplate] = {}


def register_template(template: LetterTemplate) -> LetterTemplate:
    """Register (or replace) a letter. Idempotent per key."""
    if template.default_language not in template.defaults:
        raise ValueError(f"{template.key}: no default text in {template.default_language}")
    _REGISTRY[template.key] = template
    return template


def get_template(key: str) -> LetterTemplate | None:
    """The registered letter for *key*, or ``None``."""
    return _REGISTRY.get(key)


def all_templates() -> list[LetterTemplate]:
    """Every registered letter, ordered by module then key."""
    return sorted(_REGISTRY.values(), key=lambda t: (t.module, t.key))


def template_language(template: LetterTemplate, language: str | None) -> str:
    """Reduce *language* (``de-AT``, ``DE``) to one the letter ships, else its default."""
    if not language:
        return template.default_language
    primary = language.strip().lower().split("-")[0].split("_")[0]
    return primary if primary in template.defaults else template.default_language


def default_text(template: LetterTemplate, language: str | None) -> LetterText:
    """Shipped wording for *language*, falling back to the default language."""
    return template.defaults[template_language(template, language)]


def placeholders_in(text: str) -> list[str]:
    """Placeholder names used in *text*, in order, without duplicates."""
    seen: dict[str, None] = {}
    for match in PLACEHOLDER_RE.finditer(text or ""):
        seen.setdefault(match.group(1), None)
    return list(seen)


def render(text: str, values: Mapping[str, str | None]) -> str:
    """Substitute placeholders in *text*.

    Known names are replaced by their value. A line that uses a known name
    whose value is empty or ``None`` is dropped. Unknown names stay as written.
    Never raises.
    """
    out: list[str] = []
    for line in (text or "").split("\n"):
        names = [m.group(1) for m in PLACEHOLDER_RE.finditer(line)]
        if any(n in values and not (values[n] or "").strip() for n in names):
            continue
        out.append(PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), line))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def split_paragraphs(text: str) -> list[str]:
    """Split rendered text into paragraphs on blank lines."""
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def check_text(template: LetterTemplate, text: LetterText) -> list[LetterIssue]:
    """Validate a letter text against its template.

    Rules: empty body (error), field too long (error), unknown placeholder
    (error, it would print as ``{name}``), required placeholder missing from
    every field (warning, the user may phrase it out on purpose).
    """
    issues: list[LetterIssue] = []
    if not (text.body or "").strip():
        issues.append(LetterIssue("empty_body", "error", "body"))
    for name in FIELDS:
        value = getattr(text, name) or ""
        cap = MAX_BODY if name == "body" else MAX_LINE
        if len(value) > cap:
            issues.append(LetterIssue("too_long", "error", name))
        for ph in placeholders_in(value):
            if ph not in template.placeholder_names:
                issues.append(LetterIssue("unknown_placeholder", "error", name, ph))
    used = {ph for name in FIELDS for ph in placeholders_in(getattr(text, name) or "")}
    for ph in template.placeholders:
        if ph.required and ph.name not in used:
            issues.append(LetterIssue("missing_required", "warning", "body", ph.name))
    return issues
