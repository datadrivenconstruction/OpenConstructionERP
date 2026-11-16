# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Merge engine safety, markup, rules and text resolution of document templates."""

from __future__ import annotations

import uuid

import pytest

from app.core.doc_templates.markup import has_raw_html, to_html, to_plain, to_reportlab, unsafe_links
from app.core.doc_templates.merge import fields_in, malformed_tokens, render, unknown_fields
from app.core.doc_templates.registry import DocumentKind, MergeField, register_kind
from app.core.doc_templates.resolve import Published, resolve_text
from app.core.doc_templates.rules import check_blocks, has_errors

_DEFAULTS = {
    "en": {"title": "Letter of award", "intro": "Dear Sir or Madam,", "closing": "Kind regards"},
    "de": {
        "title": "Auftragserteilung",
        "intro": "Sehr geehrte Damen und Herren,",
        "closing": "Mit freundlichen Grüßen",
    },
}

KIND = DocumentKind(
    key="test.award",
    channel="pdf",
    module="tendering",
    label="Award letter",
    blocks=("title", "intro", "closing"),
    fields=(
        MergeField("package.name", "text", "Rohbau Haus B", "document"),
        MergeField("doc.total", "money", "1.248.300,00 €", "document"),
        MergeField("recipient.name", "text", "Bau AG", "recipient"),
    ),
    defaults=lambda lang: _DEFAULTS.get(lang, {}),
    languages=("en", "de"),
)

EMAIL = DocumentKind(
    key="test.mail",
    channel="email",
    module="rfi",
    label="RFI email",
    blocks=("subject", "body"),
    fields=(MergeField("rfi.number", sample="RFI-042"), MergeField("rfi.subject", sample="Footing depth at grid C4")),
    defaults=lambda lang: {"subject": "RFI {{rfi.number}}", "body": "Please answer."},
)


class TestMergeEngine:
    def test_known_field_is_replaced(self) -> None:
        assert render("Auftrag für {{package.name}}", {"package.name": "Rohbau Haus B"}) == "Auftrag für Rohbau Haus B"

    def test_spaces_inside_braces_are_allowed(self) -> None:
        assert render("{{ package.name }}", {"package.name": "X"}) == "X"

    def test_unknown_field_renders_empty_and_fails_validation(self) -> None:
        text = "Hello {{pkg}}"
        assert render(text, {"package.name": "X"}, KIND.field_paths) == "Hello "
        issues = check_blocks(KIND, {"intro": text})
        assert [i.rule_id for i in issues] == ["doctpl.unknown_merge_field"]
        assert issues[0].params == {"field": "pkg"}

    @pytest.mark.parametrize(
        "attempt",
        [
            "{{ package.__class__ }}",
            "{{ ''.__class__.__mro__ }}",
            "{{ config.items() }}",
            "{{ package.name | upper }}",
            "{{ 7*7 }}",
            "{{ lipsum.__globals__.os.popen('id').read() }}",
            "{{package['name']}}",
        ],
    )
    def test_injection_attempts_never_evaluate(self, attempt: str) -> None:
        out = render(f"A {attempt} B", {"package.name": "X", "config": "secret"}, KIND.field_paths)
        assert out == "A  B"
        assert malformed_tokens(attempt) or unknown_fields(attempt, KIND.field_paths)
        assert has_errors(check_blocks(KIND, {"intro": attempt}))

    def test_jinja_statements_are_plain_text(self) -> None:
        text = "{% for x in y %}{{ package.name }}{% endfor %}"
        assert render(text, {"package.name": "X"}, KIND.field_paths) == "{% for x in y %}X{% endfor %}"

    def test_format_braces_are_not_interpreted(self) -> None:
        assert render("{0.__class__} {package}", {"package": "X"}) == "{0.__class__} {package}"

    def test_undeclared_value_is_never_leaked(self) -> None:
        assert render("{{secret.key}}", {"secret.key": "s3cr3t"}, KIND.field_paths) == ""

    def test_fields_in_lists_paths_once(self) -> None:
        assert fields_in("{{a.b}} {{ a.b }} {{c}}") == ["a.b", "c"]

    def test_render_never_raises_on_odd_values(self) -> None:
        assert render("{{a}}", {"a": None}) == ""
        assert render(None, {}) == ""


class TestMarkup:
    def test_value_cannot_become_markup(self) -> None:
        html = to_html("Hello {{recipient.name}}", {"recipient.name": "<script>x</script> **b**"}, None)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<strong>" not in html

    def test_raw_html_is_refused_and_escaped(self) -> None:
        text = "<img src=x onerror=alert(1)>"
        assert has_raw_html(text)
        assert "<img" not in to_html(text, {}, None)
        assert any(i.rule_id == "doctpl.raw_html" for i in check_blocks(KIND, {"intro": text}))

    def test_bold_italic_bullets_and_breaks(self) -> None:
        html = to_html("**Bold** and *it*\nnext\n\n- one\n- two", {}, None)
        assert "<strong>Bold</strong>" in html and "<em>it</em>" in html
        assert "<br/>" in html and "<ul><li>one</li><li>two</li></ul>" in html
        para = to_reportlab("**Bold**\n- item", {}, None)
        assert para == ["<b>Bold</b><br/>• item"]

    def test_links_only_https_and_mailto(self) -> None:
        assert unsafe_links("[a](https://x.io) [b](mailto:a@b.c) [c](javascript:void) [d](http://x)") == [
            "javascript:void",
            "http://x",
        ]
        html = to_html("[c](javascript:void)", {}, None)
        assert "href" not in html
        assert 'href="https://x.io"' in to_html("[a](https://x.io)", {}, None)

    def test_links_are_text_in_pdf(self) -> None:
        assert to_reportlab("[site](https://x.io)", {}, None) == ["site"]

    def test_plain_strips_markers(self) -> None:
        assert to_plain("RFI {{rfi.number}}: **{{rfi.subject}}**", EMAIL.samples(), EMAIL.field_paths) == (
            "RFI RFI-042: Footing depth at grid C4"
        )


class TestRules:
    def test_empty_email_subject_is_an_error(self) -> None:
        issues = check_blocks(EMAIL, {"subject": "  ", "body": "x"})
        assert [i.rule_id for i in issues] == ["doctpl.email_subject_empty"]

    def test_unsafe_link_is_an_error(self) -> None:
        issues = check_blocks(EMAIL, {"subject": "s", "body": "[x](ftp://a)"})
        assert [i.rule_id for i in issues] == ["doctpl.unsafe_link"]

    def test_block_size_cap(self) -> None:
        assert any(i.rule_id == "doctpl.block_too_long" for i in check_blocks(KIND, {"intro": "x" * 8001}))

    def test_unknown_block_is_refused(self) -> None:
        assert [i.rule_id for i in check_blocks(KIND, {"script": "x"})] == ["doctpl.unknown_block"]

    def test_register_kind_rejects_bad_blocks(self) -> None:
        bad = DocumentKind("t.bad", "pdf", "m", "Bad", ("subject",), (), lambda _l: {"subject": ""})
        with pytest.raises(ValueError, match="not allowed"):
            register_kind(bad)


class TestResolve:
    def test_no_template_prints_builtin_text_in_document_language(self) -> None:
        res = resolve_text(KIND, "de-DE", {})
        assert res.source == "default"
        assert res.blocks["title"] == "Auftragserteilung"

    def test_unknown_language_falls_back_to_english_builtin(self) -> None:
        res = resolve_text(KIND, "fi", {})
        assert res.blocks["title"] == "Letter of award"

    def test_published_text_wins_and_empty_block_takes_default(self) -> None:
        vid = uuid.uuid4()
        intro = "Sehr geehrte Damen und Herren, wir freuen uns, Ihnen den Auftrag für {{package.name}} zu erteilen."
        res = resolve_text(KIND, "de", {"de": Published(vid, {"intro": intro, "title": ""})})
        assert res.source == "published" and res.version_id == vid
        assert res.blocks["intro"] == intro
        assert res.blocks["title"] == "Auftragserteilung"

    def test_missing_translation_prints_primary_language_with_warning(self) -> None:
        vid = uuid.uuid4()
        res = resolve_text(KIND, "fr", {"de": Published(vid, {"intro": "Eigener Text"})}, primary_locale="de")
        assert res.source == "primary_language"
        assert res.blocks["intro"] == "Eigener Text"
        assert res.blocks["title"] == "Auftragserteilung"
        assert [w.rule_id for w in res.warnings] == ["doctpl.locale_fallback"]

    def test_broken_published_text_is_not_used(self) -> None:
        res = resolve_text(KIND, "de", {"de": Published(uuid.uuid4(), {"intro": "{{ x.__class__ }}"})})
        assert res.source == "default"
