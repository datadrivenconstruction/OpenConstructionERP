# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The plural guard must take its call sites from code and not from prose.

``scripts/check_i18n_plural_forms.py`` excludes a key that is named literally
at a call site, on the sound reasoning that such a suffix belongs to the name
rather than to a plural. It found those names with a regex over
``frontend/src/**/*.ts*`` that did not know what a comment is, and a comment in
``pluralFormsAreChosenByI18nextNotByJavaScript.test.ts`` demonstrates the
anti-pattern that test forbids by writing two key names out in full. Both forms
of a complete key were therefore excluded from every locale at once, and the
guard reported 37 rows of a hole that does not exist. Each of the 37 was
checked against the locale file it named before this was written: every form
the guard called missing is present.

What makes that worth a test rather than a one-line fix is the direction the
repair can fail in. Blanking too little leaves today's noise, which is loud.
Blanking too much silently drops a real call site, the family disappears from
the counted population, and the guard stops asking about a key that genuinely
lacks a form. Nothing goes red in that case, and a guard that has gone quiet
looks exactly like a guard with nothing to report.

So the cases below come in opposed pairs. For every "a comment must not count"
there is a "code must still count", and the last pair is the one that catches
the obvious wrong implementation: a line comment stripped with a naive pattern
takes ``'https://example.test'`` for the start of a comment and swallows the
rest of the line, call site included.

The end to end pair does the same at the level of the verdict. One tree has a
real missing plural and must fail. The other has the complete key plus the
comment that used to break it and must pass. Before the repair the second tree
failed, which is the bug, and a repair that made the first tree pass would be
worse than the bug.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_i18n_plural_forms.py"


def _load_gate():
    """Import the guard by path, the way the repo's other script tests do."""
    spec = importlib.util.spec_from_file_location("check_i18n_plural_forms", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _tree(root: Path, source: str, locales: dict[str, str]) -> None:
    """A miniature frontend: one source file and the locale files named."""
    features = root / "frontend" / "src" / "features"
    features.mkdir(parents=True)
    (features / "sample.tsx").write_text(source, encoding="utf-8")
    locale_dir = root / "frontend" / "src" / "app" / "locales"
    locale_dir.mkdir(parents=True)
    for name, body in locales.items():
        (locale_dir / f"{name}.ts").write_text(body, encoding="utf-8")


def _sites(root: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> tuple[set[str], set[str]]:
    """``_call_sites`` over a tree holding exactly ``source``."""
    _tree(root, source, {"en": 'export default {\n  "a.b_one": "x",\n}\n'})
    monkeypatch.chdir(root)
    return gate._call_sites()


class TestAKeyInProseIsNotACallSite:
    """The half that was wrong: a name written in a comment is not a call."""

    def test_a_line_comment_naming_a_key_does_not_exclude_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        literal, _ = _sites(tmp_path, monkeypatch, "// never write t('a.b_one') by hand\nt('z.z');\n")
        assert "a.b_one" not in literal, "a key named in a comment was read as a literal call site"

    def test_a_block_comment_naming_a_key_does_not_exclude_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        literal, _ = _sites(tmp_path, monkeypatch, "/**\n * Bad: t('a.b_one')\n */\nt('z.z');\n")
        assert "a.b_one" not in literal, "a key named in a block comment was read as a literal call site"

    def test_a_counted_call_shown_in_a_comment_does_not_join_the_population(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other scan, which never misfired but is fed from the same text.

        A base that only an example mentions would have the guard demanding
        plural forms for a family no screen can reach.
        """
        _, counted = _sites(tmp_path, monkeypatch, "// for example t('e.f', { count: n })\nt('z.z');\n")
        assert "e.f" not in counted, "a counted call shown in a comment was read as a real one"


class TestCodeStillCounts:
    """The half that a careless repair breaks, where failure is silent."""

    def test_a_real_counted_call_is_still_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, counted = _sites(tmp_path, monkeypatch, "const n = 2;\nt('a.b', { count: n });\n")
        assert "a.b" in counted, "the guard lost a real counted call and would now be silent about it"

    def test_the_es6_shorthand_is_still_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, counted = _sites(tmp_path, monkeypatch, "const count = 2;\nt('a.b', { defaultValue: 'x', count });\n")
        assert "a.b" in counted, "the shorthand spelling stopped being counted"

    def test_a_url_in_a_string_does_not_take_the_call_beside_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case that catches the obvious wrong implementation.

        Two slashes inside a string literal start no comment. A repair written
        as a bare line-comment strip blanks from the middle of the URL to the
        end of the line and takes the call with it, and nothing anywhere goes
        red, because a call site that vanishes only ever removes findings.

        The URL and the call share a line deliberately. With the two on
        separate lines a naive strip damages only the URL's own line and this
        passes over the very implementation it exists to reject, which was
        true of the first version of this test.
        """
        source = "const n = 2;\nconst u = 'https://example.test/x'; t('c.d', { count: n }); // real\n"
        literal, counted = _sites(tmp_path, monkeypatch, source)
        assert "c.d" in literal, "a URL in a string swallowed the call site that followed it"
        assert "c.d" in counted, "a URL in a string swallowed the counted call that followed it"

    def test_a_key_named_literally_in_code_is_still_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exclusion itself must survive: it is why the guard is usable.

        ``agents.pick_one`` is an instruction to pick one, not a plural of
        ``agents.pick``. The guard tells those apart by asking whether the
        whole name appears at a call site, and losing that would report every
        key with an unlucky ending.
        """
        literal, _ = _sites(tmp_path, monkeypatch, "t('agents.pick_one');\n")
        assert "agents.pick_one" in literal, "a key named literally in code stopped being excluded"


class TestTheVerdict:
    """The same opposition again, at the level of the exit code."""

    _COUNTED_CALL = "const n = 2;\nt('files.imported', { count: n });\n"
    _EN = 'export default {\n  "files.imported_one": "one file",\n  "files.imported_other": "{{count}} files",\n}\n'

    def _run(self, root: Path, monkeypatch: pytest.MonkeyPatch, source: str, ru: str) -> int:
        _tree(root, source, {"en": self._EN, "ru": ru})
        monkeypatch.chdir(root)
        return gate.main()

    def test_a_genuinely_missing_form_still_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Russian takes four categories, so two forms is a real hole."""
        ru = 'export default {\n  "files.imported_one": "a",\n  "files.imported_other": "b",\n}\n'
        assert self._run(tmp_path, monkeypatch, self._COUNTED_CALL, ru) == 1

    def test_a_complete_key_named_in_a_comment_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The reported bug, reduced: complete everywhere, failed anyway."""
        ru = (
            "export default {\n"
            '  "files.imported_one": "a",\n'
            '  "files.imported_few": "b",\n'
            '  "files.imported_many": "c",\n'
            '  "files.imported_other": "d",\n'
            "}\n"
        )
        source = "// wrong: t('files.imported_one') vs t('files.imported_many')\n" + self._COUNTED_CALL
        assert self._run(tmp_path, monkeypatch, source, ru) == 0

    def test_the_comment_was_what_broke_it(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pins the cause, not just the symptom.

        The same complete tree fails when the guard is handed the raw source,
        which is what it did before. Without this, a repair that passed the
        case above for some unrelated reason would look correct.
        """
        monkeypatch.setattr(gate, "_blank_comments", lambda text: text)
        ru = (
            "export default {\n"
            '  "files.imported_one": "a",\n'
            '  "files.imported_few": "b",\n'
            '  "files.imported_many": "c",\n'
            '  "files.imported_other": "d",\n'
            "}\n"
        )
        source = "// wrong: t('files.imported_one') vs t('files.imported_many')\n" + self._COUNTED_CALL
        assert self._run(tmp_path, monkeypatch, source, ru) == 1


def test_the_real_tree_no_longer_reports_the_key_the_comment_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The product's own locales, checked rather than reasoned about.

    This is the finding stated as an assertion: the guard is run over the real
    tree and must not name the key the comment used to exclude. It is kept
    apart from the fixtures above because it is the only case here that can go
    red because somebody deleted a plural form for real, and when it does the
    message should point at the locales rather than at this repair.
    """
    monkeypatch.chdir(_REPO_ROOT)

    assert gate.main() == 0

    printed = capsys.readouterr().out
    assert "connectors.just_imported" not in printed, (
        "the guard still reports a key whose forms are present in every locale that needs them"
    )
