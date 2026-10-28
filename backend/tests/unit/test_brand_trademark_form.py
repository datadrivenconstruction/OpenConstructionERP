"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The gate that keeps the registered sign on a CAD tool named in a UI string.

The founder ruling of 2026-08-14 allows the authoring tool the converter reads
from to be named in UI strings, on the condition that the first mention in each
string carries the registered sign. ``scripts/check_no_brand_tokens.py`` grew a
second, hash-free check for that, and the interesting part is not that it finds
an unmarked name. It is the three shapes it must not get wrong.

A second mention inside the same string stays bare. "Revit templates read Revit
parameters" is correct trademark usage, so a check written per occurrence would
reject the exact wording the ruling produced and push an author into marking
every repetition.

A following hyphen is not an exemption. German, Dutch and the Nordic locales
compound the name into the next word, so the string reads Revit-Modelle, and the
sign belongs on the name itself: Revit(R)-Modelle. The earlier marketing script
skipped hyphenated forms because it was avoiding a repository slug, and carrying
that rule over here would decline to check roughly a third of the locales while
reporting green on them. Those are the locales where the mention is most likely
to be reintroduced by a translation pass, so the blind spot would sit exactly
where the risk is.

The repository slug is genuinely exempt. ``cad2data-Revit-IFC-DWG-DGN`` is part
of a URL that has to stay byte-exact, and marking it would break the link. The
exemption is anchored on that prefix rather than on looking slug-shaped, so a
new slug is reported rather than quietly permitted.

Locale files are not the whole UI. English also ships as i18n defaults written
into components, and ``guide.eac.selectors.body`` has no entry in any of the
forty locales, so its default is the only English that string will ever render.
A gate scoped to locale files reports green over exactly that. The second scan
therefore reads default-shaped lines anywhere under ``frontend/src``, and its
own risk is the opposite one: shouting at an identifier or a comment would get
the gate switched off, so those shapes are tested as hard as the findings are.

The live tree is asserted here on purpose, unlike the version-sync gate, which
leaves that to its CI job. The brand script runs in ``Brand Token Check``, a job
whose own workflow file carries the chronically red frontend build, whereas this
file runs under ``CI (PostgreSQL)``. Asserting the tree here is what makes the
ruling enforced rather than merely reported.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_no_brand_tokens.py"
LOCALE_DIR = REPO_ROOT / "frontend" / "src" / "app" / "locales"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

R = "®"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_no_brand_tokens", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


def _entry(value: str) -> str:
    return f'    "some.key": "{value}",'


def _scan(script, tmp_path: Path, value: str) -> list[tuple[int, str, str]]:
    probe = tmp_path / "probe.ts"
    probe.write_text(_entry(value), encoding="utf-8")
    return script._scan_trademark_form(probe)


@pytest.mark.parametrize(
    "value",
    [
        "Revit",
        "Supports CAD/BIM files (Revit, IFC, DWG, DGN)",
        "quantities from your IFC and Revit models",
        # The compound the hyphen rule would have skipped.
        "Mengen aus Ihren IFC- und Revit-Modellen",
        "Revit-Vorlagen prüfen die Parameter",
    ],
)
def test_unmarked_first_mention_is_reported(script, tmp_path, value):
    assert _scan(script, tmp_path, value) != []


@pytest.mark.parametrize(
    "value",
    [
        f"Revit{R}",
        f"Supports CAD/BIM files (Revit{R}, IFC, DWG, DGN)",
        f"Mengen aus Ihren IFC- und Revit{R}-Modellen",
        f"Open-source converters for Revit{R} (RVT), IFC, DWG and DGN",
        # Only the first mention takes the sign; the rest of the sentence is
        # ordinary prose and marking it again would be wrong.
        f"Revit{R} templates select by category and check Revit parameters",
        f"selected by IFC entity class or Revit{R} category. Revit templates read Revit parameters.",
    ],
)
def test_marked_first_mention_passes(script, tmp_path, value):
    assert _scan(script, tmp_path, value) == []


def test_repository_slug_is_exempt(script, tmp_path):
    value = "Installed git-blob SHA. Compared against the upstream cad2data-Revit-IFC-DWG-DGN repo."
    assert _scan(script, tmp_path, value) == []


def test_slug_exemption_does_not_cover_a_display_mention_on_the_same_line(script, tmp_path):
    # The slug is skipped, so the next mention is the first display one and is
    # still required to carry the sign. An exemption that swallowed the whole
    # line would be a hole big enough to hide any string that links to the repo.
    value = "See cad2data-Revit-IFC-DWG-DGN for the Revit converter"
    assert _scan(script, tmp_path, value) != []


def test_the_key_is_not_display_text(script, tmp_path):
    # An identifier may spell the name; only the value is shown to a user.
    probe = tmp_path / "probe.ts"
    probe.write_text('    "bim.filterRevitCategories": "RVT categories",', encoding="utf-8")
    assert script._scan_trademark_form(probe) == []


def test_a_line_that_is_not_a_locale_entry_is_ignored(script, tmp_path):
    probe = tmp_path / "probe.ts"
    probe.write_text("// Revit categories are read from the converted model\n", encoding="utf-8")
    assert script._scan_trademark_form(probe) == []


def test_the_gate_is_wired_to_locale_paths(script, tmp_path, monkeypatch):
    # Detection is worth nothing if main() never routes a locale file into it,
    # so drive the entrypoint against a tree shaped like the real one.
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)
    locales = tmp_path / "frontend" / "src" / "app" / "locales"
    locales.mkdir(parents=True)
    probe = locales / "xx.ts"

    probe.write_text(_entry("Supports Revit, IFC, DWG"), encoding="utf-8")
    assert script.main([str(probe)]) == 1

    probe.write_text(_entry(f"Supports Revit{R}, IFC, DWG"), encoding="utf-8")
    assert script.main([str(probe)]) == 0


def test_every_shipped_locale_carries_the_mark(script):
    # The statement about the repository, not about the code.
    paths = sorted(LOCALE_DIR.glob("*.ts"))

    # A directory that resolved wrong would scan nothing and report clean, so
    # establish that the corpus was really read before trusting an empty result.
    assert len(paths) >= 29, f"only {len(paths)} locale file(s) under {LOCALE_DIR}"
    stems = {p.stem for p in paths}
    text_of = {p.stem: p.read_text(encoding="utf-8") for p in paths}

    def base_of(stem: str) -> str | None:
        """The language file a regional variant resolves through, if any.

        Derived from the code rather than mirrored from the fallback map in
        frontend/src/app/i18n.ts, because i18next expands a two-part code into
        ['en-US', 'en'] on its own before it ever consults that map. A mirrored
        table is a second copy of a decision and the copy is the one that goes
        stale, which is how the orphan guard came to demand a full keyspace of
        an overlay.
        """
        if "-" not in stem:
            return None
        base = stem.split("-", 1)[0]
        return base if base in stems else None

    # A locale that names the tool must mark it, and a full locale that names it
    # nowhere has had the mention translated away, which is the regression this
    # assertion was written for. A regional overlay is the one case where naming
    # it nowhere is correct: en-US carries 1499 keys against English's 33771,
    # every one of them a word that actually differs, and it says nothing about
    # CAD tools because it has nothing different to say. Demanding a marked
    # mention there would be satisfied only by copying an English string into an
    # overlay whose entire purpose is to hold what is not the same, and the mark
    # the reader sees would still be the one in en.ts. So a variant is excused
    # when its base carries the mark, and only then: strip the mark from en.ts
    # and both files fail, which is the direction that matters.
    unmarked = [
        p.name
        for p in paths
        if f"Revit{R}" not in text_of[p.stem] and not (base_of(p.stem) and f"Revit{R}" in text_of[base_of(p.stem)])  # type: ignore[index]
    ]
    assert unmarked == [], f"locale(s) carrying no marked mention at all: {unmarked}"

    offenders = [
        f"{path.name}:{lineno} {key}" for path in paths for lineno, key, _name in script._scan_trademark_form(path)
    ]
    assert offenders == [], f"{len(offenders)} unmarked UI string(s): {offenders[:10]}"


def test_an_overlay_is_only_excused_while_its_base_carries_the_mark(script, tmp_path, monkeypatch):
    """The carve-out above must not become a hole the base can fall through.

    A variant that names the tool nowhere is reading its base's marked mention.
    That stops being true the moment the base loses the mark, and at that point
    both files are wrong and both have to say so, or the exemption would quietly
    protect exactly the regression it was carved around.
    """
    locales = tmp_path / "frontend" / "src" / "app" / "locales"
    locales.mkdir(parents=True)
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)

    (locales / "en.ts").write_text(_entry(f"Supports Revit{R}, IFC, DWG"), encoding="utf-8")
    (locales / "en-US.ts").write_text(_entry("Bill of quantities"), encoding="utf-8")

    assert script.main([str(locales / "en-US.ts")]) == 0

    # The overlay is unchanged; only the base lost its mark.
    (locales / "en.ts").write_text(_entry("Supports Revit, IFC, DWG"), encoding="utf-8")
    assert script.main([str(locales / "en.ts")]) == 1


def _scan_lines(script, tmp_path: Path, source: str) -> list[tuple[int, str]]:
    probe = tmp_path / "Probe.tsx"
    probe.write_text(source, encoding="utf-8")
    return script._scan_component_defaults(probe)


@pytest.mark.parametrize(
    "source",
    [
        "  defaultValue: 'Supports CAD/BIM files (Revit, IFC, DWG, DGN)',",
        "  defaultLabel: 'Revit',",
        "  revit: { key: 'rulePacks.format_revit', fallback: 'Revit' },",
        # The shape that carries most of the long English: the hint names the
        # field on one line and the string sits on the next.
        "  bodyDefault:\n    'Match by IFC class, Revit category, or by level.',",
    ],
)
def test_an_unmarked_i18n_default_is_reported(script, tmp_path, source):
    assert _scan_lines(script, tmp_path, source) != []


@pytest.mark.parametrize(
    "source",
    [
        f"  defaultValue: 'Supports CAD/BIM files (Revit{R}, IFC, DWG, DGN)',",
        f"  bodyDefault:\n    'Match by IFC class, Revit{R} category, or by level.',",
        # A repository link and a marked default share one line in AboutPage.
        f"  {{ href: 'https://github.com/ddc/cad2data-Revit-IFC-DWG-DGN', desc: t('k', "
        f"{{ defaultValue: 'Pipeline: Revit{R} to data' }}) }},",
    ],
)
def test_a_marked_i18n_default_passes(script, tmp_path, source):
    assert _scan_lines(script, tmp_path, source) == []


def test_a_comment_is_not_display_text(script, tmp_path):
    # This exact line lives in suggestQuantityFromBIM.ts. It explains why the
    # default property lookup is case-tolerant, and a gate that demanded a
    # trademark sign inside a code comment would be gone by Friday.
    source = "  // default keys (Revit/IFC mix `NetVolume` vs `netVolume`).\n"
    assert _scan_lines(script, tmp_path, source) == []


def test_a_trailing_comment_is_not_display_text(script, tmp_path):
    source = "  defaultValue: 'RVT shared-parameter', // Revit exports this as .txt\n"
    assert _scan_lines(script, tmp_path, source) == []


def test_an_identifier_without_a_default_is_ignored(script, tmp_path):
    source = "const RevitCategory = pickCategory(element);\nexport type RevitParam = string;\n"
    assert _scan_lines(script, tmp_path, source) == []


def test_the_component_scan_is_wired_into_main(script, tmp_path, monkeypatch):
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)
    feature = tmp_path / "frontend" / "src" / "features" / "demo"
    feature.mkdir(parents=True)
    probe = feature / "DemoPage.tsx"

    probe.write_text("  defaultValue: 'Supports Revit, IFC',", encoding="utf-8")
    assert script.main([str(probe)]) == 1

    probe.write_text(f"  defaultValue: 'Supports Revit{R}, IFC',", encoding="utf-8")
    assert script.main([str(probe)]) == 0


def test_every_shipped_component_default_carries_the_mark(script):
    paths = [
        path
        for suffix in ("*.ts", "*.tsx")
        for path in FRONTEND_SRC.rglob(suffix)
        if LOCALE_DIR not in path.parents and "__tests__" not in path.parts
    ]

    # Same anti-vacuity guard as the locale sweep: a corpus that resolved wrong
    # scans nothing and reports clean. A file known to hold a marked default
    # proves the reader is looking at the shipped tree, not an empty one.
    assert len(paths) >= 100, f"only {len(paths)} component file(s) under {FRONTEND_SRC}"
    known = FRONTEND_SRC / "features" / "bim_requirements" / "RulePackLibrary.tsx"
    assert known.is_file() and f"Revit{R}" in known.read_text(encoding="utf-8")

    offenders = [
        f"{path.relative_to(FRONTEND_SRC).as_posix()}:{lineno}"
        for path in paths
        for lineno, _name in script._scan_component_defaults(path)
    ]
    assert offenders == [], f"{len(offenders)} unmarked i18n default(s): {offenders[:10]}"


# ── Third surface: a literal written straight into the page ──────────────────
# Neither a locale value nor an i18n default. A radio label, a format map and a
# thrown message each reached users this way, so the first two scans reported
# green over text a translator never saw either.

SEED_PACKS = "frontend/src/features/bim_requirements/SEED_PACKS.ts"


def _norm(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _scan_display(script, tmp_path: Path, source: str, norm: str = "x.tsx"):
    probe = tmp_path / "Probe.tsx"
    probe.write_text(source, encoding="utf-8")
    return script._scan_display_literals(probe, norm)


@pytest.mark.parametrize(
    "source",
    [
        "  cad: 'Revit (.rvt), IFC (.ifc), DWG (.dwg)',",
        "  {fmt === 'revit' ? 'Revit' : 'IFC'}",
        "  throw new Error('This mesh has no Revit ElementId.');",
        "    description: 'Match by Revit category',",
    ],
)
def test_an_unmarked_display_literal_is_reported(script, tmp_path, source):
    assert _scan_display(script, tmp_path, source) != []


@pytest.mark.parametrize(
    "source",
    [
        f"  cad: 'Revit{R} (.rvt), IFC (.ifc), DWG (.dwg)',",
        f"  {{fmt === 'revit' ? 'Revit{R}' : 'IFC'}}",
        # Second mention in the same string stays bare, as everywhere else.
        f"  label: 'Revit{R} templates read Revit parameters',",
        # A format token is not a product name and is never marked.
        "  accept: '.rvt,.ifc,.dwg,.dgn',",
    ],
)
def test_a_marked_display_literal_passes(script, tmp_path, source):
    assert _scan_display(script, tmp_path, source) == []


def test_a_template_literal_is_not_scanned(script, tmp_path):
    # SEED_PACKS.ts embeds whole YAML documents in backticks. The first mention
    # inside one lands in that document's `#` comment, which this rule cannot
    # read as a comment; the documents are marked in data/bim_rules/*.yaml.
    source = (
        "const PACK = `# Revit cost-classification completeness (DIN 276).\n"
        "#\n"
        "# Every element modelled in Revit must carry a code.\n"
        "  name: DIN 276 Cost-Group Completeness (Revit)\n"
        "`;\n"
    )
    assert _scan_display(script, tmp_path, source) == []


def test_a_rule_pack_name_is_identity_but_its_description_is_not(script, tmp_path):
    # The closed decision, asserted from both sides in one test so neither half
    # can be relaxed without the other failing.
    source = (
        "    name: 'DIN 276 Cost-Group Completeness (Revit)',\n"
        "    description:\n"
        "      'Verifies that every Revit wall carries a code.',\n"
    )
    hits = _scan_display(script, tmp_path, source, norm=SEED_PACKS)
    assert [line for line, _ in hits] == [3], hits


def test_the_identity_exemption_does_not_widen_beyond_that_file(script, tmp_path):
    # A `name:` field in any other component is ordinary display text. Without
    # this, "name is identity" becomes a way to leave anything unmarked.
    source = "    name: 'DIN 276 Cost-Group Completeness (Revit)',\n"
    assert _scan_display(script, tmp_path, source, norm="frontend/src/x.tsx") != []


def test_a_test_fixture_is_not_a_display_string(script):
    # `__tests__` alone missed the sibling convention, and an unmarked fixture
    # in BIMConverterVerifyGate.test.tsx sat inside the scanned set unreported.
    assert script._is_test_path("frontend/src/features/bim/X.test.tsx")
    assert script._is_test_path("frontend/src/features/bim/X.spec.ts")
    assert script._is_test_path("frontend/src/app/__tests__/x.ts")
    assert not script._is_test_path("frontend/src/features/bim/BIMTestPage.tsx")


def test_the_shipped_release_notes_stay_out_of_it(script):
    # Ruled 2026-08-14: a release note records what was written that day. The
    # file still holds unmarked mentions, which is what makes this meaningful.
    changelog = REPO_ROOT / "frontend" / "src" / "features" / "about" / "Changelog.tsx"
    assert changelog.is_file()
    assert script._scan_display_literals(changelog, _norm(changelog)) != []
    assert _norm(changelog) in script._ARCHIVE_FILES


def test_the_display_scan_is_wired_into_main(script, tmp_path, monkeypatch):
    monkeypatch.setattr(script, "REPO_ROOT", tmp_path)
    feature = tmp_path / "frontend" / "src" / "features" / "demo"
    feature.mkdir(parents=True)
    probe = feature / "DemoPage.tsx"

    probe.write_text("  const label = 'Revit category';", encoding="utf-8")
    assert script.main([str(probe)]) == 1

    probe.write_text(f"  const label = 'Revit{R} category';", encoding="utf-8")
    assert script.main([str(probe)]) == 0


def test_every_shipped_display_literal_carries_the_mark(script):
    paths = [
        path
        for suffix in ("*.ts", "*.tsx")
        for path in FRONTEND_SRC.rglob(suffix)
        if LOCALE_DIR not in path.parents and not script._is_test_path(_norm(path))
    ]
    assert len(paths) >= 100, f"only {len(paths)} component file(s) under {FRONTEND_SRC}"
    seeded = REPO_ROOT / SEED_PACKS
    assert seeded.is_file() and f"Revit{R}" in seeded.read_text(encoding="utf-8")

    offenders = [
        f"{_norm(path)}:{lineno}"
        for path in paths
        if _norm(path) not in script._ARCHIVE_FILES
        for lineno, _name in script._scan_display_literals(path, _norm(path))
    ]
    assert offenders == [], f"{len(offenders)} unmarked display string(s): {offenders[:10]}"
