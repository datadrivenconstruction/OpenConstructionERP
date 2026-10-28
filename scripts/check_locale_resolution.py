#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠LOCK: a catalogue must answer a regional locale the same way it answers its base language.

THIS IS A REGRESSION LOCK, NOT A BUG REPORT, and the distinction is the first
thing a reader deserves. It was written after measuring whether the defect it
guards is live today. It is not. Everything below is what that measurement
found, so that the next person can re-run it rather than re-trust it.

THE DEFECT. A catalogue keyed by base language (``de``, ``ru``, ``es``) that
looks a locale up by exact string match does not fail when handed ``de-AT``.
It misses the dict and silently answers in English, which on screen is
indistinguishable from a language nobody has translated yet. ``341d37ca7``
fixed three catalogues carrying it: ``modules/requirements/intl.py``,
``modules/risk/intl.py``, and ``modules/bcf/messages/``.

WHY IT IS NOT LIVE, measured rather than assumed. A regional code cannot reach
a catalogue through any production path that exists today:

  * The context path is clamped twice. ``AcceptLanguageMiddleware._resolve_locale``
    matches an incoming tag against ``SUPPORTED_LOCALES``, which holds base
    codes only, by exact-or-prefix match; and ``set_locale`` then stores
    ``resolve_locale(locale) or "en"`` rather than the code it was handed. So
    ``get_locale()`` cannot return a regional code, and every catalogue fed
    from it - which includes all seven ``MessageBundle`` catalogues and bcf's
    ``_locale_of`` - receives a base language or English.
  * The document path strips explicitly. ``resolve_document_locale`` takes the
    client-controlled ``?locale=`` value and the raw ``Accept-Language``
    header and reduces both with ``.split("-")[0]`` before matching.
  * The lookups that DO still resolve by exact match are all defended, but in
    two different ways, and the second is the one that makes this lock worth
    having. The baseline holds them; they fall into:

    - UNREACHABLE. Twelve of the sixteen have no production reference at
      all: their defining module and their own unit test, nothing else. No
      router, no service, no sibling module, so no request can reach them.
      ``reporting.intl.label`` has no reference anywhere, test included.
      Resolved by IMPORT rather than by name, over all 4307 files under
      ``backend/app`` and ``backend/tests``: collect what each file imports
      from a baseline module, both plain ``from M import name`` and ``from P
      import M`` followed by ``M.name``, then match references against that.
      A name grep was tried first and rejected as unusable, which is worth
      recording because it is the more obvious method: ``label`` alone
      returned 241 hits, nearly all SQLAlchemy ``func.count().label(...)``,
      and ``changeorders/intl.py`` defines its own ``status_label``, which a
      name grep happily attributes to ``daily_diary``. Both errors inflate
      the reachable set, so a grep cannot support a claim of UNreachability.
    - REACHED, BUT ONLY EVER WITH A STRIPPED CODE. The other four. ``report_translations``'s
      ``field_label`` and ``section_title`` and ``daily_diary``'s
      ``pdf_translations`` lookups are called from real export paths
      (``reporting/exporters.py``, ``reporting/renderer.py``,
      ``daily_diary/pdf_export.py``). They are safe only because every route
      that reaches them resolves the locale through ``resolve_report_locale``
      or ``resolve_pdf_locale`` first, both thin wrappers over
      ``resolve_document_locale``, which strips. The catalogue does not defend
      itself; its callers defend it.

So the failure mode is real, the code that carries it is real, and nothing can
currently trigger it. That second class is exactly why this is a lock and not
a curiosity: the invariant rests on a discipline at every call site, and one
new call site that forwards a raw ``?locale=`` value into ``field_label``
makes it live with no other change. The lock fires when someone does that,
when a regional code is added to ``SUPPORTED_LOCALES``, or when a new
catalogue resolves by exact match.

BEHAVIOURAL, NOT STRUCTURAL, and this was a deliberate choice. Five different
spellings of "strip the region" are already in the tree - ``_norm_lang``,
``_normalize_locale``, ``_lang_key``, ``lang.lower().startswith(...)``, and
``locale_candidates`` - so a source scan looking for a recognised idiom would
report a catalogue as broken for using a sixth. This asks the catalogue
instead: call the same function twice, once as ``de`` and once as ``de-AT``,
and require the same answer. A catalogue cannot pass that by accident and
cannot fail it for a spelling nobody anticipated.

WHAT IT DOES NOT COVER, since a lock that overstates its reach is worse than
none. Only catalogues it can import and demonstrate are counted, and the
report prints that number rather than the number scanned, because the count
that can narrow silently is the one worth printing. A module whose table holds
no non-English string different from its English one cannot demonstrate the
defect either way and is reported as not-demonstrable rather than as a pass;
``compliance_ai`` is such a case today, legitimately - its catalogue is two
keys, ``OK`` and a product name, which are the same in both languages. This
lock also says nothing about whether a translation is complete or correct;
``scripts/check_validation_message_locale_coverage.py`` counts breadth and is
equally blind to depth.

Run it from the repo root:

    python scripts/check_locale_resolution.py
    python scripts/check_locale_resolution.py --write-baseline
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import itertools
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
APP_ROOT = BACKEND_ROOT / "app"
BASELINE_PATH = REPO_ROOT / "scripts" / "locale_resolution_baseline.json"

#: Parameter names that carry a locale into a lookup.
LANG_PARAMS = {"lang", "locale", "language", "lang_code", "locale_code"}

#: (base language, the same language with a region). The regional codes are
#: real ones a client would send, not invented, so a reader can recognise them.
PROBES = (
    ("de", "de-AT"),
    ("ru", "ru-RU"),
    ("es", "es-MX"),
    ("pt", "pt-BR"),
    ("zh", "zh-CN"),
)

#: Used only to recognise a dict that is keyed BY language rather than by
#: message key. Not a statement about what the platform supports.
KNOWN_LANGS = frozenset({"en", "de", "ru", "es", "pt", "fr", "it", "nl", "pl", "zh", "ja", "ko", "tr", "ar"})


#: This backend is PEP 695 source (``def f[T](...)``), which 3.11 cannot parse.
MINIMUM_PYTHON = (3, 12)


def require_supported_interpreter() -> None:
    """Refuse to run on an interpreter that cannot parse this backend.

    Not defensive tidiness - this was a real false result. Run under 3.11 the
    probe imported 75 of 76 modules and reported the 76th as an import failure
    with a SyntaxError, which reads exactly like a broken file in the tree. The
    file was fine; the interpreter was too old for its generic syntax. A gate
    whose population silently shrinks by one and still prints OK is worse than
    no gate, so this fails loudly instead of skipping.
    """
    if sys.version_info < MINIMUM_PYTHON:
        raise RuntimeError(
            f"this lock needs Python >= {'.'.join(map(str, MINIMUM_PYTHON))} to parse the backend "
            f"(PEP 695 generics); running {sys.version.split()[0]} would silently skip modules it "
            f"cannot import and still report OK. Use backend's .venv-run interpreter."
        )


def prepare_environment() -> None:
    """Make ``app.*`` importable and satisfy import-time settings validation.

    Idempotent, and called by both ``main`` and the test wrapper so a probe run
    behaves the same either way. ``setdefault`` rather than assignment: under
    pytest the conftest has already chosen a real database and must win. No
    connection is ever opened from here - these values only have to parse.
    """
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://probe:probe@127.0.0.1:5432/probe")
    os.environ.setdefault("DATABASE_SYNC_URL", "postgresql+psycopg2://probe:probe@127.0.0.1:5432/probe")
    require_supported_interpreter()
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))


def candidate_modules(app_root: Path = APP_ROOT) -> list[str]:
    """Dotted names of modules whose source could hold a locale-keyed table.

    A cheap text filter, not a parse: any file mentioning ``"en"`` alongside
    another language code is worth importing and asking. Over-collecting here
    is harmless because the probe simply reports "no locale table"; under-
    collecting would be invisible, which is why the filter is loose.
    """
    found: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if '"en"' not in text:
            continue
        if not any(f'"{code}"' in text for code in ("de", "ru", "es", "pt")):
            continue
        parts = path.relative_to(BACKEND_ROOT).with_suffix("").parts
        dotted = ".".join(parts)
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        if dotted not in found:
            found.append(dotted)
    return found


def locale_tables(module: object) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """Module-level translation tables, normalised to ``{name: [(key, {lang: str})]}``.

    Both orientations occur in this tree and are handled: ``{key: {lang: str}}``
    is the ``intl.py`` idiom, ``{lang: {key: str}}`` is the one
    ``report_translations.py`` uses. Recognising only the first would have
    silently skipped every catalogue written the other way round.
    """
    out: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for name, value in vars(module).items():
        if not isinstance(value, dict) or not value:
            continue
        inner = [v for v in value.values() if isinstance(v, dict) and v]
        if len(inner) != len(value):
            continue
        if not all(all(isinstance(s, str) for s in v.values()) for v in inner):
            continue

        outer_keys = {str(k) for k in value}
        if "en" in outer_keys and len(outer_keys & KNOWN_LANGS) >= 2:
            per_key: dict[str, dict[str, str]] = {}
            for lang, mapping in value.items():
                for key, text in mapping.items():
                    per_key.setdefault(str(key), {})[str(lang)] = text
            out[name] = list(per_key.items())
        elif any("en" in v and len(v) > 1 for v in inner):
            out[name] = [(str(k), v) for k, v in value.items() if isinstance(v, dict)]
    return out


#: Ceiling on argument combinations tried per function. Bounds the run without
#: narrowing it in practice: the largest real case needs a few dozen.
MAX_COMBINATIONS = 400


def argument_candidates(module: object) -> list[str]:
    """Plausible values for a non-locale parameter, harvested from the module.

    A lookup often takes more than a key and a locale. ``risk.intl.localize``
    takes ``(term, kind, lang)``, where ``kind`` selects which table to read;
    filling it with a message key made every call miss the table and return a
    fallback, so the probe compared two identical fallbacks and reported the
    function as fine. That is how the first version of this lock passed on a
    catalogue that was one of the three defects it was written for. So
    candidates are drawn from the string keys of every module-level dict, at
    both levels, which is where a discriminator like ``"category"`` lives.
    """
    seen: list[str] = []
    for name, value in vars(module).items():
        if name.startswith("__") or not isinstance(value, dict):
            continue
        for key, inner in value.items():
            if isinstance(key, str) and key not in seen:
                seen.append(key)
            if isinstance(inner, dict):
                for sub in inner:
                    if isinstance(sub, str) and sub not in seen:
                        seen.append(sub)
    return seen


def _call(func, params, lang_idx: int, filler: tuple[str, ...], lang: str):
    """Call ``func`` with ``lang`` in its locale slot and ``filler`` in the others."""
    args = []
    fill = list(filler)
    for i, param in enumerate(params):
        if i == lang_idx:
            args.append(lang)
        elif fill:
            args.append(fill.pop(0))
        else:
            args.append(param.default if param.default is not inspect.Parameter.empty else "")
    return func(*args)


def probe_module(dotted: str) -> dict[str, object]:
    """Ask one module's lookups whether a regional code reaches the base language."""
    try:
        module = importlib.import_module(dotted)
    except Exception as exc:  # noqa: BLE001 - any import failure is a reported skip
        return {
            "module": dotted,
            "status": "import-failed",
            "detail": f"{type(exc).__name__}: {exc}"[:120],
        }
    return probe_loaded_module(dotted, module)


def probe_bundles(module: object) -> tuple[list[str], dict[str, str], int]:
    """Ask any file-backed message bundle held by this module the same question.

    The third catalogue ``341d37ca7`` fixed was ``bcf``, which is a bundle
    rather than a dict literal: its strings live in ``messages/*.json`` and are
    loaded at runtime, so the table-scanning probe above cannot see it at all.
    bcf's defect was owning a private copy of the bundle class, and a copy is
    exactly where a shared fix stops arriving - so this duck-types on the
    behaviour (an object with ``translate`` and a ``messages_dir``) instead of
    on the class, and would catch the next private copy too.
    """
    unstripped: list[str] = []
    evidence: dict[str, str] = {}
    probes = 0
    for name, value in vars(module).items():
        # Duck-typed on the two things that define the behaviour, deliberately
        # NOT on a messages_dir attribute: the private copy bcf carried kept
        # its directory in a module-level constant and had no such attribute,
        # so requiring one made this blind to the exact catalogue it exists
        # for. Test a lock against the defect it was written for, not against
        # the shape of the fixed version.
        if not callable(getattr(value, "translate", None)):
            continue
        loaded = getattr(value, "_loaded", None)
        if not isinstance(loaded, dict):
            continue
        try:
            loader = getattr(value, "load", None)
            if callable(loader):
                loader()
            elif not loaded:
                value.translate("probe.load.trigger")
        except Exception:  # noqa: BLE001
            continue
        english = loaded.get("en") or {}
        for base, regional in PROBES:
            table = loaded.get(base) or {}
            key = next((k for k, text in table.items() if text != english.get(k)), None)
            if key is None:
                continue
            try:
                answer_base = value.translate(key, locale=base)
                answer_regional = value.translate(key, locale=regional)
            except Exception:  # noqa: BLE001
                continue
            probes += 1
            if answer_base != answer_regional and name not in unstripped:
                unstripped.append(name)
                evidence[name] = f"{base}={answer_base!s:.40} vs {regional}={answer_regional!s:.40}"
            break
    return unstripped, evidence, probes


def probe_loaded_module(dotted: str, module: object) -> dict[str, object]:
    """The probe itself, on a module object that is already loaded.

    Split from :func:`probe_module` so a test can point it at a historical
    version of a file loaded from disk. The red proof for this lock is three
    real catalogues as they stood before ``341d37ca7`` fixed them, which is
    stronger evidence than a synthetic fixture because those are the exact
    defects it exists to catch.
    """
    tables = locale_tables(module)
    unstripped, evidence, probes = probe_bundles(module)
    if not tables and not probes:
        return {"module": dotted, "status": "no-locale-table"}

    candidates = argument_candidates(module)
    # Compare against the module's own __name__ rather than the dotted label
    # the caller used. They are the same for an imported module and different
    # for one loaded from a file path, and hard-coding the label silently
    # skipped every function in the historical copies the red proof loads -
    # the probe reported "nothing to demonstrate" on a file that was the
    # defect, which is the most misleading answer it could have given.
    owner = getattr(module, "__name__", dotted)

    for fname, func in vars(module).items():
        if fname.startswith("_") or not inspect.isfunction(func):
            continue
        if getattr(func, "__module__", None) != owner:
            continue
        try:
            params = list(inspect.signature(func).parameters.values())
        except (TypeError, ValueError):
            continue
        lang_idx = next((i for i, p in enumerate(params) if p.name in LANG_PARAMS), None)
        if lang_idx is None:
            continue

        # A call only demonstrates anything if it reached a translation: the
        # base language must answer differently from English. Comparing table
        # contents instead, as the first draft did, accepts a call that missed
        # its table entirely and returned the same fallback twice.
        slots = len(params) - 1
        combos = itertools.product(candidates, repeat=slots) if slots else iter([()])
        demonstrated = False
        for tried, filler in enumerate(combos):
            if tried >= MAX_COMBINATIONS:
                break
            for base, regional in PROBES:
                try:
                    answer_en = _call(func, params, lang_idx, filler, "en")
                    answer_base = _call(func, params, lang_idx, filler, base)
                except Exception:  # noqa: BLE001 - a signature we cannot satisfy is not evidence
                    break
                if answer_en == answer_base:
                    continue
                try:
                    answer_regional = _call(func, params, lang_idx, filler, regional)
                except Exception:  # noqa: BLE001
                    continue
                probes += 1
                demonstrated = True
                if answer_base != answer_regional and fname not in unstripped:
                    unstripped.append(fname)
                    evidence[fname] = f"{base}={answer_base!s:.40} vs {regional}={answer_regional!s:.40}"
            if demonstrated:
                break

    if not probes:
        return {"module": dotted, "status": "not-demonstrable"}
    return {
        "module": dotted,
        "status": "probed",
        "probes": probes,
        "unstripped": unstripped,
        "evidence": evidence,
    }


def measure(app_root: Path = APP_ROOT) -> list[dict[str, object]]:
    return [probe_module(dotted) for dotted in candidate_modules(app_root)]


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, list[str]]:
    """Read the baseline, or say plainly why it could not be read.

    A missing baseline used to reach the caller as a bare FileNotFoundError
    traceback. That is still red, so it is not the worst failure available, but
    a crash and a verdict read very differently in a log and only one of them
    tells the reader what to do. Every other data-backed gate in scripts/
    answers an absent file with a defined outcome; this one was the exception.

    Deliberately NOT treated as an empty baseline. Empty would also be red, but
    red for the wrong reason: it would report sixteen known and accepted
    lookups as brand-new regressions and send someone hunting a change nobody
    made. A gate whose reds cannot be trusted is a gate that gets switched off.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RuntimeError(
            f"{path} is missing, so this lock cannot say anything about anything. It ships in "
            "the same commit as this script; if you are seeing this, the two were separated."
        ) from None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} is not valid JSON ({exc}); regenerate with --write-baseline") from None
    if "known_unstripped" not in payload:
        raise RuntimeError(f"{path} has no 'known_unstripped' key; regenerate it with --write-baseline")
    return {module: list(names) for module, names in payload["known_unstripped"].items()}


def write_baseline(results: list[dict[str, object]], path: Path = BASELINE_PATH) -> None:
    known = {
        str(r["module"]): sorted(r["unstripped"])  # type: ignore[arg-type]
        for r in results
        if r["status"] == "probed" and r["unstripped"]
    }
    payload = {
        "_comment": (
            "Functions that resolve a locale by exact match and so answer English for a regional "
            "code. Twelve have no production caller; the other four are reached only through "
            "resolve_document_locale, which strips first. See the module docstring of "
            "scripts/check_locale_resolution.py. This list may shrink, never grow."
        ),
        "known_unstripped": {module: known[module] for module in sorted(known)},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check(*, app_root: Path = APP_ROOT, baseline_path: Path = BASELINE_PATH) -> tuple[int, list[str]]:
    """Run the probe and the lock. Returns ``(exit_code, report_lines)``."""
    results = measure(app_root)
    baseline = load_baseline(baseline_path)

    probed = [r for r in results if r["status"] == "probed"]
    total_probes = sum(int(r["probes"]) for r in probed)  # type: ignore[arg-type]
    lines = [
        f"modules scanned:            {len(results)}",
        f"  probe actually executed:  {len(probed)}  <- the population this lock speaks for",
        f"  locale lookups asked:     {total_probes}",
        f"  no locale-keyed table:    {sum(1 for r in results if r['status'] == 'no-locale-table')}",
        f"  nothing to demonstrate:   {sum(1 for r in results if r['status'] == 'not-demonstrable')}",
        f"  import failed (skipped):  {sum(1 for r in results if r['status'] == 'import-failed')}",
    ]
    for r in results:
        if r["status"] == "import-failed":
            lines.append(f"    ! {r['module']}: {r['detail']}")

    failures: list[str] = []
    fixed: list[str] = []
    for r in probed:
        module = str(r["module"])
        found = set(r["unstripped"])  # type: ignore[arg-type]
        allowed = set(baseline.get(module, []))
        for name in sorted(found - allowed):
            failures.append(
                f"REGRESSION: {module}.{name} answers a regional locale in English "
                f"({r['evidence'][name]}) - strip the region before the lookup"  # type: ignore[index]
            )
        fixed.extend(f"{module}.{name}" for name in sorted(allowed - found))

    probed_modules = {str(r["module"]) for r in probed}
    for module in sorted(set(baseline) - probed_modules):
        failures.append(
            f"REGRESSION: {module} is in the baseline but could not be probed this run - "
            f"the lock has stopped watching it, which is not the same as it passing"
        )

    known_total = sum(len(v) for v in baseline.values())
    lines.append(f"known unstripped lookups carried in the baseline: {known_total}")

    if failures:
        lines.extend(failures)
        return 1, lines

    if fixed:
        lines.append(f"now strips the region and can leave the baseline: {sorted(fixed)} - run --write-baseline")

    lines.append(
        f"OK: {len(probed)} catalogues probed with {total_probes} lookups, "
        f"no catalogue outside the {known_total}-entry baseline answers a regional locale in English"
    )
    return 0, lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Locale-resolution regression lock.")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Record today's unstripped lookups and exit 0.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help="Baseline file to check against. Exists so a test can run this lock in its own "
        "interpreter against its own baseline: importing the whole app in-process to answer a "
        "gate question can change what later tests in the same session see.",
    )
    args = parser.parse_args()

    prepare_environment()

    if args.write_baseline:
        results = measure()
        write_baseline(results)
        known = load_baseline()
        print(f"{BASELINE_PATH.relative_to(REPO_ROOT)}: recorded {sum(len(v) for v in known.values())} lookup(s)")
        for module in sorted(known):
            print(f"  {module}: {known[module]}")
        return 0

    try:
        exit_code, lines = check(baseline_path=args.baseline)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
