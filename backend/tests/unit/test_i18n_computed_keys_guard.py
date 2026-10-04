"""The computed-key guard sees the t() call sites whose key is not a literal.

scripts/check_i18n_orphan_keys.py reads `t('literal', {defaultValue})` and
resolves the key. Its regex requires a quoted string, so every call site that
builds its key at runtime is outside it: a template literal
(`price_breakdown.kind.${kind}`) or a variable (`t(item.labelKey, ...)`).
Both render the English defaultValue in all 40 languages when the key is
missing, which is the same silent failure the orphan guard exists to stop,
arriving through a door it cannot watch.

What is testable here splits three ways and the split is the point.

  * A template key cannot be resolved to its members, but the question "does
    en.ts hold ANY key under this prefix" is decidable without knowing them.
    An empty prefix means the whole family is unanswerable. That is the check.

  * A table pairing a literal key field with a defaultLabel IS resolvable, and
    it is the shape that let nav.credentials exist in no locale at all.

  * Everything else has to be counted and named rather than skipped. A guard
    that drops what it cannot resolve reads as coverage it does not have, so
    the residual counts are asserted here as hard as the findings are.

The last two tests are about the guard failing loudly on a broken scan. A
locale file that parses to nothing, or a source tree with no call sites, must
not print the same result as a clean run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_i18n_computed_keys.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_i18n_computed_keys", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because @dataclass resolves its own module
    # out of sys.modules while the class body is being processed, and a guard
    # loaded by path alone is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _tree(tmp_path: Path, sources: dict[str, str], en_keys: dict[str, str]) -> tuple[str, str]:
    """Write a miniature frontend tree and return (en glob, source glob)."""
    locales = tmp_path / "locales"
    locales.mkdir()
    body = "\n".join(f'  "{k}": "{v}",' for k, v in en_keys.items())
    (locales / "en.ts").write_text(f"export default {{\n{body}\n}};\n", encoding="utf-8")

    src = tmp_path / "src"
    src.mkdir()
    for name, text in sources.items():
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    return str(locales / "en.ts"), str(src / "**" / "*.ts*")


def _i18n_ts(tmp_path: Path) -> str:
    """A synthetic SUPPORTED_LANGUAGES fixture, so main() never opens the real one.

    main() reads --i18n-ts unconditionally, on every call, not only the ones
    that exercise in-progress/abandoned classification. Left at its default
    it is a path relative to the repo root, so it silently depends on
    whatever cwd pytest happened to start from, same failure shape as the
    --locales bug this file exists to close.
    """
    path = tmp_path / "i18n.ts"
    if not path.exists():
        path.write_text(
            "export const SUPPORTED_LANGUAGES = [\n  { code: 'en', label: 'English' },\n];\n",
            encoding="utf-8",
        )
    return str(path)


def _run(tmp_path, sources, en_keys, baseline=None):
    en, srcglob = _tree(tmp_path, sources, en_keys)
    locales_glob = str(tmp_path / "locales" / "*.ts")
    argv = [
        "--en",
        en,
        "--src",
        srcglob,
        "--locales",
        locales_glob,
        "--member-baseline",
        str(tmp_path / "member_absent.json"),
        "--i18n-ts",
        _i18n_ts(tmp_path),
    ]
    if baseline is not None:
        path = tmp_path / "baseline.json"
        path.write_text(baseline, encoding="utf-8")
        argv += ["--baseline", str(path)]
    else:
        argv += ["--baseline", str(tmp_path / "absent.json")]
    return guard.main(argv)


# --------------------------------------------------------------------------
# The template-literal class: an empty prefix is a decidable defect.
# --------------------------------------------------------------------------


def test_template_prefix_absent_from_en_is_caught(tmp_path, capsys):
    """The shape this guard was written for, and the one that shipped."""
    sources = {"Panel.tsx": ("const label = t(`price_breakdown.kind.${c.kind}`, { defaultValue: c.kind });\n")}
    code = _run(tmp_path, sources, {"boq.title": "Bill of quantities"})

    assert code == 1
    out = capsys.readouterr()
    assert "price_breakdown.kind." in out.out + out.err


def test_template_prefix_with_members_is_not_flagged(tmp_path, capsys):
    """A family that exists must stay silent, or the guard gets switched off."""
    sources = {"Panel.tsx": "t(`punch.status_${s}`, { defaultValue: s });\n"}
    code = _run(
        tmp_path,
        sources,
        {"punch.status_open": "Open", "punch.status_closed": "Closed"},
    )

    assert code == 0
    assert "punch.status_" not in capsys.readouterr().err


def test_template_key_without_a_default_value_is_out_of_scope(tmp_path):
    """No defaultValue means the raw key renders, which reports itself."""
    sources = {"Panel.tsx": "t(`nowhere.at_all_${x}`);\n"}
    # Something else must carry a defaultValue or the empty-scan tripwire fires.
    sources["Other.tsx"] = "t(`punch.status_${s}`, { defaultValue: s });\n"
    code = _run(tmp_path, sources, {"punch.status_open": "Open"})

    assert code == 0


def test_interpolation_at_the_head_leaves_no_prefix_to_check(tmp_path, capsys):
    """A key that starts with its variable is unresolvable and must say so."""
    sources = {
        "Panel.tsx": "t(`${scope}.title`, { defaultValue: 'Title' });\n",
        "Other.tsx": "t(`punch.status_${s}`, { defaultValue: s });\n",
    }
    code = _run(tmp_path, sources, {"punch.status_open": "Open"})

    out = capsys.readouterr().out
    assert code == 0
    # Counted and named, never silently dropped.
    assert "no static prefix" in out
    assert "1" in out


# --------------------------------------------------------------------------
# The prop class: a literal key paired with a defaultLabel IS resolvable.
# --------------------------------------------------------------------------


def test_default_label_table_with_a_missing_key_is_caught(tmp_path, capsys):
    """The nav.credentials shape: a key that exists in no locale at all."""
    sources = {
        "navCatalog.ts": (
            "export const NAV = [\n  { id: 'creds', labelKey: 'nav.credentials', defaultLabel: 'Credentials' },\n];\n"
        ),
        "Sidebar.tsx": "t(item.labelKey, { defaultValue: item.defaultLabel });\n",
    }
    code = _run(tmp_path, sources, {"nav.overview": "Overview"})

    assert code == 1
    out = capsys.readouterr()
    assert "nav.credentials" in out.out + out.err


@pytest.mark.parametrize(
    "field", ["defaultLabel", "defaultName", "defaultDesc", "defaultText", "defaultTitle", "defaultHelp"]
)
def test_every_default_field_name_the_tree_uses_forms_a_pair(tmp_path, field):
    """The same prop under six names, and a guard keyed to one calls it clean.

    voice/targets.ts writes defaultTitle beside titleKey, the guide tables write
    defaultDesc. Those are the nav.credentials shape with a different field name,
    so pairing only on defaultLabel would report a clean prop class while its
    siblings went unread.
    """
    sources = {
        "table.ts": f"[{{ titleKey: 'x.missing', {field}: 'M' }}]\n",
        "S.tsx": "t(item.titleKey, { defaultValue: item.x });\n",
    }
    assert _run(tmp_path, sources, {"x.other": "O"}) == 1


def test_default_value_alone_does_not_forge_a_pair(tmp_path):
    """`defaultValue` is the t() option, not a table's stand-in English.

    Pairing on it would let an unrelated key field elsewhere in the window form
    a spurious finding, so the call-site scan owns it and the table scan skips it.
    """
    sources = {
        "Page.tsx": ("const NAV = [{ labelKey: 'nav.overview' }];\nt(k, { defaultValue: 'Something' });\n"),
    }
    assert _run(tmp_path, sources, {"nav.overview": "Overview"}) == 0


def test_default_label_table_with_a_present_key_passes(tmp_path):
    sources = {
        "navCatalog.ts": (
            "export const NAV = [\n  { id: 'ov', labelKey: 'nav.overview', defaultLabel: 'Overview' },\n];\n"
        ),
        "Sidebar.tsx": "t(item.labelKey, { defaultValue: item.defaultLabel });\n",
    }
    assert _run(tmp_path, sources, {"nav.overview": "Overview"}) == 0


# --------------------------------------------------------------------------
# The residual: what the guard cannot resolve must be counted, not skipped.
# --------------------------------------------------------------------------


def test_unresolvable_variable_keys_are_counted_and_named(tmp_path, capsys):
    """A guard that silently skips these reads as coverage it does not have."""
    sources = {
        "Page.tsx": ("t(job.stage, { defaultValue: job.stage });\nt(entry.key, { defaultValue: 'x' });\n"),
        "Other.tsx": "t(`punch.status_${s}`, { defaultValue: s });\n",
    }
    code = _run(tmp_path, sources, {"punch.status_open": "Open"})

    out = capsys.readouterr().out
    assert code == 0
    assert "not checked" in out.lower()
    assert "job.stage" in out
    assert "entry.key" in out


# --------------------------------------------------------------------------
# Baseline behaviour, and refusing to pass on a broken scan.
# --------------------------------------------------------------------------


def test_baseline_suppresses_a_known_prefix_but_not_a_new_one(tmp_path, capsys):
    sources = {
        "A.tsx": "t(`known.gap_${x}`, { defaultValue: x });\n",
        "B.tsx": "t(`fresh.gap_${x}`, { defaultValue: x });\n",
    }
    code = _run(tmp_path, sources, {"other.key": "v"}, baseline='["known.gap_"]')

    assert code == 1
    err = capsys.readouterr().err
    assert "fresh.gap_" in err
    assert "known.gap_" not in err


def test_a_locale_that_parses_to_nothing_fails_rather_than_passes(tmp_path):
    """Silence about a file nobody could read is how the Thai defect lived."""
    en, srcglob = _tree(tmp_path, {"A.tsx": "t(`x.y_${z}`, {defaultValue: z});\n"}, {})
    Path(en).write_text("export default {};\n", encoding="utf-8")

    assert guard.main(["--en", en, "--src", srcglob, "--baseline", str(tmp_path / "n.json")]) == 2


def test_no_call_sites_is_a_broken_scan_not_a_clean_one(tmp_path):
    sources = {"A.tsx": "const nothing = 1;\n"}
    assert _run(tmp_path, sources, {"some.key": "v"}) == 2


def test_the_real_tree_parses_and_the_guard_reaches_a_verdict():
    """Against the shipping tree, not a fixture: the globs must still match.

    A guard whose defaults have rotted would pass every fixture test above and
    scan nothing in production. The globs are relative to the repo root, which
    is where pre-commit runs them and which is NOT the pytest working
    directory, so the path is resolved here rather than assumed.
    """
    sites = guard.collect(str(_REPO_ROOT / guard.DEFAULT_SOURCE_GLOB))
    assert len(sites.template) > 100, "template call sites vanished; check the glob"
    assert sites.pairs, "no labelKey/defaultLabel tables found; check the pair regex"


def test_a_wrong_working_directory_fails_rather_than_reporting_a_clean_scan():
    """The globs are relative, so the wrong cwd sees an empty tree.

    A tree walk that visits no files and prints OK is the failure this whole
    family of guards is built to avoid, so the empty scan has to exit non-zero.
    """
    assert guard.main(["--src", "no/such/tree/**/*.ts*", "--en", str(_REPO_ROOT / guard.DEFAULT_EN_PATH)]) == 2


@pytest.mark.parametrize("quote", ["'", '"'])
def test_both_quote_styles_of_key_field_resolve(tmp_path, quote):
    """en.ts is double-quoted but source tables are written either way."""
    sources = {
        "nav.ts": f"[{{ labelKey: {quote}nav.missing{quote}, defaultLabel: {quote}M{quote} }}]\n",
        "S.tsx": "t(item.labelKey, { defaultValue: item.defaultLabel });\n",
    }
    assert _run(tmp_path, sources, {"nav.other": "O"}) == 1


def test_a_plural_member_is_answered_by_the_form_the_language_uses():
    """`x_one` as a family member is owed as `x`, not as that one form.

    The prefix `boq.markup_` matched `boq.markup_band_count_one` in en.ts, and
    the guard then asked zh for that exact key. zh has one plural category,
    so i18next reads `_other` there and `_one` never exists. A locale with no
    form of the key at all is still missing it.
    """
    by_locale = {
        "en": {"x.count_one", "x.count_other"},
        "zh": {"x.count_other"},
        "de": {"x.count_one", "x.count_other"},
        "fr": set(),
    }
    bases = {"en": None, "zh": None, "de": None, "fr": None}
    assert guard.missing_locales("x.count_one", by_locale, bases) == ["fr"]
    assert guard.missing_locales("x.count_other", by_locale, bases) == ["fr"]
