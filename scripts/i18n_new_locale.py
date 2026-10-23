"""Bootstrap a new UI locale: work out what has to be translated, then assemble it.

Adding a language to this app is not "copy en.ts and translate it". Two facts
make that wrong, and both are measured rather than assumed by this script.

First, en.ts is not the full key set. English is supplied inline at the call
site as `t('key', { defaultValue: 'English' })`, so a key only reaches en.ts
when someone put it there. Every translated locale carries thousands of keys
English does not. Building a new locale from en.ts silently drops them and the
new language shows English on those screens forever.

Second, no single existing locale is the full key set either. Arabic carries
plural forms (_zero, _two, _few, _many) that a two-form language never asks
for, and the two-form locales are each missing a handful of ordinary keys that
some other locale has. Grounding a new language in one sibling inherits that
sibling's gaps.

So the target key set is computed: the union of every locale on disk, minus the
plural categories the new language does not have according to CLDR. Plural
category membership comes from the language itself, never from English.

The English source text for each key is harvested from three places in priority
order: en.ts, the `defaultValue` at the call site, and the English field beside
a `<name>Key` field in the case playbooks and module guides. `plan` reports what
each source covered and names the keys it found nothing for, because a key with
no English anywhere is a bug in its own right: an English reader sees the raw
key, and a translator has nothing to work from.

Usage:
    python scripts/i18n_new_locale.py plan     et
    python scripts/i18n_new_locale.py extract  et [--batch-size 400]
    python scripts/i18n_new_locale.py delta    et
    python scripts/i18n_new_locale.py assemble et
    python scripts/i18n_new_locale.py verify   et

`extract` is a ONE-TIME BOOTSTRAP. It writes the whole batch set fresh, with
English in every value, so running it again on a locale under translation would
rewrite finished work back to English - and `assemble` rebuilds the locale file
from those batches, which is how English reaches the shipped .ts. It therefore
refuses when any batch already holds a translated value, and `--force` is the
only way past that. To pick up the next batch, open the batch_NNN.json the first
extract already wrote; to take on keys that appeared since, use `delta`.

`assemble` is the step that publishes, so it carries the same refusal from the
other end: it overwrites the shipped .ts from the batches, and once it has, the
real translation is gone with nothing to resync from. It refuses when a key
reads as a translation in the file today and would read as its English source
afterwards. That is deliberately not a threshold on how English the corpus is -
a locale under translation is assembled repeatedly and legitimately carries
placeholders, because i18next falls back per key. `--force` is the way past it.

`delta` catches a locale's corpus up when target_keys() has moved since
extract() ran (new modules landed, or keys reached the shipped locales after
this locale's own extraction) - writes exactly the new keys to
batch_delta.json and updates _order.json, without touching any existing
batch_NNN.json.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "frontend" / "src" / "app" / "locales"
SRC = ROOT / "frontend" / "src"
WORK = ROOT / ".i18n-work"

# Suffixes that are CLDR plural categories. `_one` and `_other` are deliberately
# absent: every language has `other`, and `_other` is also a perfectly ordinary
# key name meaning the enum value "Other" (documents.type_other is "Other", not
# a plural form). Treating those two as category markers would both demand
# nonsense forms and delete real keys.
CATEGORY_SUFFIXES = ("_zero", "_two", "_few", "_many")

# `t('some.key')` and the Trans component's i18nKey. The word boundary before
# `t` keeps `split(`, `format(` and friends out.
LITERAL_CALL = re.compile(r"""\bt\(\s*['"`]([\w.-]+)['"`]""")
TRANS_KEY = re.compile(r"""i18nKey\s*=\s*\{?\s*['"`]([\w.-]+)['"`]""")
_LITERAL_KEYS: set[str] | None = None

# A key line carries a string value. The `"translation": {` wrapper does not,
# and counting it as a key puts a bogus entry named `translation` in the target.
KEY_LINE = re.compile(r'^\s*"([^"]+)":\s*"')

# A long value is sometimes wrapped onto its own line: `"key":` with nothing
# after the colon, value on the next line. KEY_LINE never matches that key
# line (no opening quote before end of line), so keys_of() would silently
# drop the key. Match it separately, key-only, no value needed.
KEY_LINE_WRAPPED = re.compile(r'^\s*"([^"]+)":\s*$')

# Whole-file version of the same value pattern used by english_sources() to
# read en.ts, permitting one optional line break (and its leading indent)
# between the colon and the opening quote so a wrapped value is not silently
# treated as absent.
KEY_VAL_MULTILINE = re.compile(
    r"""^[ \t]*"([^"]+)":[ \t]*\r?\n?[ \t]*(['"])((?:\\.|(?!\2)[^\\\n])*)\2,?[ \t]*\r?$""",
    re.MULTILINE,
)

# t('key', { ... defaultValue: 'text' ... }) with the options object brace-free.
DEFAULT_VALUE = re.compile(
    r"""['"]([A-Za-z0-9_.\-]+)['"]\s*,\s*\{[^{}]*?defaultValue:\s*(['"])((?:\\.|(?!\2)[^\\])*)\2""",
    re.DOTALL,
)

# <Trans i18nKey="key" defaults="text with <tag> markup"> carries its English the
# same way defaultValue does, just on a JSX component instead of a t() call.
# Stops at the next i18nKey so it can't bleed into a second Trans block.
TRANS_DEFAULTS = re.compile(
    r"""i18nKey\s*=\s*\{?\s*['"`]([\w.-]+)['"`](?:(?!i18nKey)[\s\S])*?\bdefaults\s*=\s*(['"])((?:\\.|(?!\2)[^\\\n])*)\2""",
)

# Data files name a key and its English text as two adjacent fields, and both the
# naming and the order vary: titleKey/titleDefault, labelKey/label, labelKey with
# a `fallback`, and moduleLabel/moduleLabelKey with the English one first. Quoting
# varies too, since the tree has no formatter. One regex per shape would miss a
# shape, so find every `<stem>Key` and pair it with its English sibling.
#
# Pairing is by token-sequence adjacency, not a character-distance window: tokenize
# every `field: "value"` in the file in file order, and for a `<stem>Key` token the
# paired English is whichever IMMEDIATE neighbor (next token preferred, since the
# file convention is key-field-then-value; previous token as fallback, for the
# reversed moduleLabel/moduleLabelKey shape) has field name `<stem>`, `<stem>Default`,
# `fallback`, or `default`. A window-based nearest-match was tried first and failed
# two ways: (1) a dense run of same-named sibling fields (every step's `label:`)
# made re.search's "first in window" not necessarily belong to this entry, and
# anchoring on distance-from-match still let a long value string on either side
# outweigh the real sibling; (2) a value long enough to run past the window
# (multi-sentence longDescDefault/whatDefault paragraphs) meant the closing quote
# never appeared inside the window at all, so the key silently got no source. Exact
# adjacency in the token stream has neither failure mode: there is no "nearest",
# only the one token actually sitting next to this key in the object literal.
#
# The gap between the colon and the opening quote admits comments as well as
# whitespace. A field whose value is long enough to sit on its own line often
# carries an explanation above it, and plain `\s*` stops dead at the first `/`,
# so the field produced no token at all - not a wrong pairing, an absent one,
# which then also shifted its neighbour out of reach. That is how the `why` text
# of the change-order playbook had no English source: a ten-line comment sits
# between `whyDefault:` and its paragraph, so `whyKey` saw `moduleLabel` as its
# next token and gave up. The `//` inside a URL is untouched by this, because
# the alternation is only ever tried before the opening quote, never inside a
# value that has already started.
_VALUE_GAP = r"(?:\s|//[^\r\n]*|/\*(?:(?!\*/)[\s\S])*\*/)*"
FIELD_TOKEN = re.compile(rf"""\b(\w+):{_VALUE_GAP}(['"])((?:\\[\s\S]|(?!\2).)*)\2""")


def sibling_pairs(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    tokens = [(m.group(1), m.group(3)) for m in FIELD_TOKEN.finditer(text)]
    for i, (field, value) in enumerate(tokens):
        if field.endswith("Key"):
            stem = field[: -len("Key")]
            # `en` joins the stem-derived names because a data file that spells
            # its own language out does not repeat the stem as well.
            names = (f"{stem}Default", stem, "fallback", "default", "en")
        elif field == "key":
            # `Record<State, { key: string; en: string }>` names the key field
            # `key` outright, with no stem to build a sibling name from, so the
            # loop above never sees it. Only `en` is accepted here: `key` is an
            # ordinary field name all over the tree (table columns, list item
            # identities) and pairing it with `label` or `default` would invent
            # English for things that are not i18n keys at all. A neighbour
            # literally named `en` is an English-beside-key pair by construction.
            names = ("en",)
        else:
            continue
        for j in (i + 1, i - 1):
            if 0 <= j < len(tokens) and tokens[j][0] in names:
                found.setdefault(value, tokens[j][1])
                break
    return found


HEADER = (
    "// Locale source. Edit this file directly: nothing generates it.\n"
    "// ../i18n-fallbacks.ts reads these files for tests, it does not produce them.\n"
    "\n"
    "const resource = {\n"
    '  "translation": {\n'
)
# Every existing locale widens to Record<string, string> rather than using
# `as const`. That is not a style preference: `as const` on 36k entries makes
# TypeScript build a literal type per key, and tsc in this repo already runs out
# of memory on the full project. Match the neighbours.
FOOTER = "  }\n} as { translation: Record<string, string> };\n\nexport default resource;\n"


def read(path: Path) -> str:
    """Read preserving line endings. Path.read_text has no newline= and would
    translate CRLF to LF, which turns a one-key edit into a whole-file diff."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def keys_of(path: Path) -> list[str]:
    keys = [m.group(1) for m in (KEY_LINE.match(line) for line in read(path).splitlines()) if m]
    keys += [m.group(1) for m in (KEY_LINE_WRAPPED.match(line) for line in read(path).splitlines()) if m]
    return keys


def locale_paths() -> list[Path]:
    return sorted(LOCALES.glob("*.ts"))


def plural_categories(code: str) -> set[str]:
    """Ask the language, through Node's ICU, which categories i18next will look for."""
    out = subprocess.run(
        [
            "node",
            "-e",
            f"process.stdout.write(new Intl.PluralRules({code!r}).resolvedOptions().pluralCategories.join(','))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.strip().split(","))


def target_keys(code: str) -> tuple[list[str], set[str]]:
    """The key set the new locale must carry, in a readable order.

    Order follows the locale that shares the new language's plural categories and
    has the most keys, so a reviewer can diff the new file against a sibling and
    see translations rather than reordering. Keys no sibling has are appended.
    """
    union: set[str] = set()
    per_file: dict[Path, list[str]] = {}
    for path in locale_paths():
        ks = keys_of(path)
        per_file[path] = ks
        union.update(ks)

    have = plural_categories(code)
    dropped = {k for k in union if s_of(k) and s_of(k) not in have and is_plural_family(k, union)}
    target = union - dropped

    template = max(per_file, key=lambda p: len(per_file[p]))
    ordered = [k for k in per_file[template] if k in target]
    ordered += sorted(target - set(ordered))
    return ordered, dropped


def s_of(key: str) -> str:
    for suffix in CATEGORY_SUFFIXES:
        if key.endswith(suffix):
            return suffix[1:]
    return ""


def literal_call_keys() -> set[str]:
    """Keys the source names in full, rather than letting i18next resolve them.

    A plural family is normally reached through the stem with a count, and
    i18next appends the category. Some call sites instead choose the form with a
    ternary and pass the whole key: CostsPage.tsx calls
    `t('costs_catalogs.fx_mismatch_many')` outright. Then the suffix is part of
    the name, i18next never resolves anything, and every language needs the key
    no matter which categories it has.
    """
    global _LITERAL_KEYS
    if _LITERAL_KEYS is None:
        found: set[str] = set()
        for path in SRC.rglob("*.ts*"):
            if LOCALES in path.parents:
                continue
            text = read(path)
            found.update(LITERAL_CALL.findall(text))
            found.update(TRANS_KEY.findall(text))
        _LITERAL_KEYS = found
    return _LITERAL_KEYS


def is_plural_family(key: str, union: set[str]) -> bool:
    """Whether a category-suffixed key really is one form of a plural family.

    The suffix alone does not settle it. Eight keys carried by all 29 locales end
    in a category word and are ordinary sentences: `dwg_compare.pick_two` is
    "Pick two different versions", `assembly.params.err_div_by_zero` is a
    division-by-zero error, `geo.overlays.crop_too_few` asks for three points.
    Dropping those from a two-form language would delete real strings, and the
    orphan gate would then fail on keys the new locale is missing.

    CLDR requires an `other` form of every language, and i18next writes `_one`
    beside it for the two-form case, so a genuine family has a sibling. A lone
    `_zero`/`_two`/`_few`/`_many` with neither sibling anywhere is a word, not a
    category.

    Having a sibling is still not enough. `costs_catalogs.fx_mismatch` has both
    `_one` and `_many`, which looks like a family, but the call site picks
    between them by name and never passes a count. Estonian has two categories,
    so the family reading dropped `_many` from it, and the orphan gate then
    failed on a key the language really does need. A key the source names in
    full is not a form of anything.
    """
    if key in literal_call_keys():
        return False
    stem = key[: -len(s_of(key)) - 1]
    return f"{stem}_other" in union or f"{stem}_one" in union


def english_sources() -> dict[str, tuple[str, str]]:
    """key -> (english text, where it came from). en.ts wins, then call sites."""
    found: dict[str, tuple[str, str]] = {}

    en = LOCALES / "en.ts"
    for m in KEY_VAL_MULTILINE.finditer(read(en)):
        found[m.group(1)] = (unescape(m.group(3)), "en.ts")

    for path in SRC.rglob("*.ts*"):
        if LOCALES in path.parents:
            continue
        text = read(path)
        for m in DEFAULT_VALUE.finditer(text):
            found.setdefault(m.group(1), (unescape(m.group(3)), "defaultValue"))
        for m in TRANS_DEFAULTS.finditer(text):
            found.setdefault(m.group(1), (unescape(m.group(3)), "Trans defaults"))
        for key, english in sibling_pairs(text).items():
            found.setdefault(key, (unescape(english), "playbook"))

    return found


def unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def escape(value: str) -> str:
    # Several inputs need to come out as one of a handful of canonical
    # two-character escapes (`\n`, `\t`, `\r`, `\"`): a real control
    # character (a translator who types an actual line break or tab into a
    # batch value gets one back from json.loads) and an already-literal
    # escape pair (extract's own encoding of an English string that carried
    # one of these, which most translators leave untouched since they're
    # only retyping the surrounding words). Escaping backslashes first turns
    # the second case into a doubled backslash - a translator who never
    # touched the marker still gets e.g. `\\t` in the .ts output, which
    # renders as a visible backslash-t instead of a tab. Walk the string
    # once so an existing escape pair is recognized and left alone before
    # the general backslash-doubling rule can reach it.
    RAW = {"\n": "\\n", "\t": "\\t", "\r": "\\r"}
    ALREADY_ESCAPED = {"n": "\\n", "t": "\\t", "r": "\\r", '"': '\\"'}
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch in RAW:
            out.append(RAW[ch])
            i += 1
        elif ch == "\\" and value[i + 1 : i + 2] in ALREADY_ESCAPED:
            out.append(ALREADY_ESCAPED[value[i + 1]])
            i += 2
        elif ch == "\\":
            out.append("\\\\")
            i += 1
        elif ch == '"':
            out.append('\\"')
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def cmd_plan(code: str) -> int:
    ordered, dropped = target_keys(code)
    sources = english_sources()
    have = plural_categories(code)
    missing = [k for k in ordered if k not in sources]
    by_source: dict[str, int] = {}
    for k in ordered:
        by_source[sources.get(k, ("", "MISSING"))[1]] = by_source.get(sources.get(k, ("", "MISSING"))[1], 0) + 1

    print(f"locale        {code}")
    print(f"plural forms  {', '.join(sorted(have))}")
    print(f"target keys   {len(ordered)}")
    print(f"dropped       {len(dropped)} key(s) whose plural category {code} does not have")
    for source, count in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"  english from {source:<14} {count}")
    if missing:
        out = WORK / code
        out.mkdir(parents=True, exist_ok=True)
        (out / "_no_english.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
        print(f"\n{len(missing)} key(s) have no English text anywhere. They need a human.")
        print(f"Full list: {out / '_no_english.txt'}")
        for k in missing[:20]:
            print(f"    {k}")
        if len(missing) > 20:
            print(f"    ... and {len(missing) - 20} more")
    return 0


def translated_batch_files(out: Path, sources: dict[str, tuple[str, str]]) -> list[tuple[Path, int]]:
    """Batch files under `out` that hold work, with how many keys each answers.

    A batch file starts life holding the English source for every key, so a
    value that still equals its source is a placeholder and a value that
    differs is somebody's translation. Counting the difference is the only way
    to tell the two apart: the files are the same shape either way, and their
    timestamps say when they were written, not whether anyone wrote in them.

    A file that cannot be parsed counts as holding work. A corrupt batch is a
    reason to stop and look, never a reason to assume it was empty.
    """
    carrying: list[tuple[Path, int]] = []
    for path in sorted(out.glob("batch_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            carrying.append((path, -1))
            continue
        answered = sum(1 for k, v in payload.items() if v and v != sources.get(k, ("", ""))[0])
        if answered:
            carrying.append((path, answered))
    return carrying


def cmd_extract(code: str, batch_size: int, force: bool = False) -> int:
    ordered, _ = target_keys(code)
    sources = english_sources()
    out = WORK / code
    out.mkdir(parents=True, exist_ok=True)

    # extract is a one-time bootstrap and the unlink below is unconditional, so
    # a second run rewrites every batch back to English. That is silent: the
    # command succeeds and prints a normal-looking batch count, and the damage
    # only becomes visible at the next assemble, which rebuilds the locale file
    # FROM these batches and would publish English over a finished translation.
    #
    # It has already happened once, to 65 uz batches. It was survivable only
    # because assemble had not run yet, so the values could be resynced out of
    # the live uz.ts. Once assemble runs there is nothing left to resync from.
    #
    # So refuse, and say what would be lost. Anyone who genuinely wants to
    # re-bootstrap can pass --force; nobody reaches for that by accident while
    # looking for the next batch to translate.
    carrying = translated_batch_files(out, sources)
    if carrying and not force:
        answered = sum(n for _, n in carrying if n > 0)
        unreadable = [p.name for p, n in carrying if n < 0]
        print(f"REFUSING: {len(carrying)} batch file(s) under {out} already hold work.")
        if answered:
            print(f"  {answered} key(s) are translated and this would rewrite them to English.")
        if unreadable:
            print(f"  unreadable, treated as holding work: {', '.join(unreadable)}")
        print("  extract is a one-time bootstrap. To pick up the next batch, open the")
        print("  batch_NNN.json the first extract already wrote. To catch a moved corpus")
        print(f"  up to new keys, run: {sys.argv[0]} delta {code}")
        print("  Pass --force only if you mean to throw this translation away.")
        return 1

    for stale in out.glob("batch_*.json"):
        stale.unlink()

    batches = 0
    for start in range(0, len(ordered), batch_size):
        chunk = ordered[start : start + batch_size]
        payload = {k: sources.get(k, ("", "MISSING"))[0] for k in chunk}
        path = out / f"batch_{start // batch_size:03d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        batches += 1

    (out / "_order.json").write_text(json.dumps(ordered, ensure_ascii=False), encoding="utf-8")
    print(f"{len(ordered)} key(s) in {batches} batch(es) under {out}")
    print("Translate each batch_NNN.json in place: keep the keys, replace the values.")
    return 0


def cmd_delta(code: str) -> int:
    """Catch a locale's corpus up to a target_keys() that moved since extract().

    extract() freezes _order.json at the moment it runs. The app keeps growing
    while a locale is mid-translation, so target_keys() computed fresh can
    diverge from that frozen list - new modules add keys nobody's corpus has,
    and keys that reached the already-shipped locales after this locale's
    extract() are in the same boat. verify() catches the symptom (keys
    missing); this catches it before translation and hands out exactly the
    delta, batch_NNN.json files and already-answered work untouched.
    """
    out = WORK / code
    order_path = out / "_order.json"
    if not order_path.exists():
        print(f"no {order_path} - run extract {code} first")
        return 1
    frozen = json.loads(order_path.read_text(encoding="utf-8"))
    frozen_set = set(frozen)

    live_ordered, _ = target_keys(code)
    live_set = set(live_ordered)

    new_keys = [k for k in live_ordered if k not in frozen_set]
    stale_keys = sorted(frozen_set - live_set)

    if stale_keys:
        print(f"{len(stale_keys)} key(s) in _order.json are no longer in the live target set:")
        for k in stale_keys[:20]:
            print(f"    {k}")
        print("These need removing from whichever batch_NNN.json carries them before assemble will pass.")

    if not new_keys:
        print(f"{code}: nothing new, _order.json already matches the live target set ({len(live_set)} keys).")
        return 0

    sources = english_sources()
    payload = {k: sources.get(k, ("", "MISSING"))[0] for k in new_keys}
    delta_path = out / "batch_delta.json"
    delta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    no_english = [k for k in new_keys if not payload[k]]

    # Append rather than replace: keeps every already-translated key's row
    # position stable in the eventual .ts output, so this touches only the
    # new tail instead of reshuffling the whole file.
    updated_order = [k for k in frozen if k in live_set] + new_keys
    order_path.write_text(json.dumps(updated_order, ensure_ascii=False), encoding="utf-8")

    print(f"{len(new_keys)} new key(s) written to {delta_path}")
    print(f"_order.json updated to {len(updated_order)} keys (existing order preserved, new keys appended).")
    if no_english:
        print(f"{len(no_english)} of the new keys have no English source (need a human): {no_english[:10]}")
    print("Translate batch_delta.json in place like any other batch, then assemble as usual.")
    return 0


def shipped_values(code: str) -> dict[str, str]:
    """What `code`.ts holds today, key -> value. Empty if it does not exist yet."""
    path = LOCALES / f"{code}.ts"
    if not path.exists():
        return {}
    return {m.group(1): unescape(m.group(3)) for m in KEY_VAL_MULTILINE.finditer(read(path))}


def cmd_assemble(code: str, force: bool = False) -> int:
    out = WORK / code
    order = json.loads((out / "_order.json").read_text(encoding="utf-8"))
    merged: dict[str, str] = {}
    for path in sorted(out.glob("batch_*.json")):
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            if key in merged:
                print(f"REFUSED {key} appears in more than one batch")
                return 1
            merged[key] = value

    missing = [k for k in order if k not in merged]
    extra = [k for k in merged if k not in set(order)]
    if missing or extra:
        print(f"REFUSED {len(missing)} key(s) missing, {len(extra)} not in the target set")
        for k in (missing + extra)[:10]:
            print(f"    {k}")
        return 1
    # An empty value is normally a translator skipping a key that needs a human
    # (the "no English anywhere" keys `plan` names). But a handful of keys are
    # blank in en.ts on purpose, e.g. an unlabelled table column - those must
    # not be forced to have a value that doesn't exist in English either.
    sources = english_sources()
    deliberately_blank = {k for k, (text, origin) in sources.items() if origin == "en.ts" and text == ""}
    untranslated = [k for k in order if not merged[k].strip() and k not in deliberately_blank]
    if untranslated:
        print(f"REFUSED {len(untranslated)} key(s) still have an empty value")
        for k in untranslated[:10]:
            print(f"    {k}")
        return 1

    # assemble is the step that publishes, and it overwrites the shipped .ts
    # from whatever the batches hold. Extract's own guard stops the batches
    # being wiped; this one stops a wiped set being written out over work that
    # is already in the file, because after that write there is nothing left to
    # resync from.
    #
    # The test is not "how much of this reads as English". A locale under
    # translation is assembled repeatedly and legitimately carries placeholders
    # for the batches nobody has reached yet - i18next falls back per key, so
    # shipping it half done is the working method, not a defect. Nor is it a
    # count: `delta` adds genuinely new keys as English and must stay allowed.
    #
    # What is never legitimate is a key that reads as a translation in the file
    # today and would read as its English source afterwards. That is the loss
    # itself, it needs no threshold, and it is zero on every honest assemble.
    shipped = shipped_values(code)
    would_lose = [
        k
        for k in order
        if k in shipped
        and shipped[k].strip()
        and shipped[k] != sources.get(k, ("",))[0]
        and merged[k] == sources.get(k, ("",))[0]
    ]
    if would_lose and not force:
        print(f"REFUSED {len(would_lose)} key(s) are translated in {LOCALES / f'{code}.ts'} today")
        print("  and would be written back to English by these batches.")
        for k in would_lose[:10]:
            print(f'    {k}: "{shipped[k]}" -> "{merged[k]}"')
        print("  The batches are behind the file, which is what a second `extract` leaves.")
        print("  Recover the values from the file itself before assembling. To take on keys")
        print(f"  that appeared since, run: {sys.argv[0]} delta {code}")
        print("  Pass --force only if you mean to throw those translations away.")
        return 1

    body = "".join(f'    "{key}": "{escape(merged[key])}",\n' for key in order)
    # CRLF, because every other locale file is CRLF and a lone LF file makes the
    # next tool that edits it produce a whole-file diff.
    text = (HEADER + body + FOOTER).replace("\n", "\r\n")
    with open(LOCALES / f"{code}.ts", "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print(f"wrote {LOCALES / f'{code}.ts'} with {len(order)} key(s)")
    return 0


def cmd_verify(code: str) -> int:
    path = LOCALES / f"{code}.ts"
    if not path.exists():
        print(f"FAIL {path} does not exist")
        return 1
    text = read(path)
    ordered, _ = target_keys(code)
    present = keys_of(path)

    problems: list[str] = []
    if len(present) != len(set(present)):
        seen: set[str] = set()
        dupes = sorted({k for k in present if k in seen or seen.add(k)})  # type: ignore[func-returns-value]
        problems.append(f"{len(dupes)} duplicate key(s), first: {dupes[:5]}")
    missing = sorted(set(ordered) - set(present))
    extra = sorted(set(present) - set(ordered))
    if missing:
        problems.append(f"{len(missing)} key(s) missing, first: {missing[:5]}")
    if extra:
        problems.append(f"{len(extra)} key(s) not in the target set, first: {extra[:5]}")
    if "\r\n" not in text:
        problems.append("file is not CRLF like every other locale")
    for bad in re.findall(r'^\s*"[^"]+":\s*"(?:\\.|[^"\\])*[^\\]"[^,\s]', text, re.MULTILINE):
        problems.append(f"unescaped quote near: {bad[:60]}")
        break

    # Everything above asks about the shape of the key set, and a bundle whose
    # every value is still the English placeholder has a perfect key set. That
    # is not hypothetical: hu.ts passed all of it while 74% of its values were
    # byte-identical to English. This is deliberately inside verify rather than
    # only in the CI guard, because verify is the command someone finishing a
    # locale actually types, and a check they have to remember to run separately
    # is a check that leaves the trap open. Imported here rather than at module
    # scope: the guard imports this module for its resolver, and importing it
    # back at the top would be a cycle.
    from check_locale_english_placeholder import check_locale

    population, placeholder = check_locale(code)
    problems += placeholder

    if problems:
        for p in problems:
            print(f"FAIL {p}")
        print(population)
        return 1
    print(f"OK {code}.ts carries {len(present)} key(s), CRLF, no duplicates")
    print(f"OK {population}")
    return 0


# Shapes sibling_pairs() has to keep resolving, each one abbreviated from the
# file where it was first found to be unresolved. A shape lives here rather than
# being asserted against the real file so that moving or rewording the original
# does not turn this into a test of that file's prose; what is pinned is the
# arrangement of fields, which is the thing that broke.
SIBLING_SHAPES: list[tuple[str, str, str, str]] = [
    (
        "stem-Key then stem-Default, adjacent",
        """
        { titleKey: "a.title", titleDefault: "Attach the proof" }
        """,
        "a.title",
        "Attach the proof",
    ),
    (
        "English first, key second (moduleLabel before moduleLabelKey)",
        """
        { moduleLabel: "Claims Evidence", moduleLabelKey: "nav.claims_evidence" }
        """,
        "nav.claims_evidence",
        "Claims Evidence",
    ),
    (
        "stem-Key, then stem-Default separated from its value by a line comment",
        """
        {
          whyKey: "a.why",
          whyDefault:
            // A ten-line note about why this sentence is worded as it is sat
            // here, and the field produced no token at all, so the key beside
            // it paired with whatever followed the object instead.
            "The gap you find today is one somebody can still fill.",
          moduleLabel: "Claims Evidence",
        }
        """,
        "a.why",
        "The gap you find today is one somebody can still fill.",
    ),
    (
        "stem-Key, then stem-Default separated from its value by a block comment",
        """
        { whatKey: "a.what", whatDefault: /* see above */ "Pull the daily reports" }
        """,
        "a.what",
        "Pull the daily reports",
    ),
    (
        "bare `key` beside `en`, the Record<..., { key, en }> badge table",
        """
        const STATE_LABEL: Record<StandingState, { key: string; en: string }> = {
          revoked: { key: 'tax_withholding.state_revoked', en: 'Revoked' },
          pending: { key: 'tax_withholding.state_pending', en: 'Recorded, not confirmed' },
        };
        """,
        "tax_withholding.state_pending",
        "Recorded, not confirmed",
    ),
    (
        "a value that contains // is a value, not the start of a comment",
        """{ docsKey: 'a.docs', docsDefault: 'https://example.invalid/a' }""",
        "a.docs",
        "https://example.invalid/a",
    ),
]

# Arrangements that must stay unresolved. Inventing English for these would put
# entries in the source map that are not i18n keys at all, and the map is what
# the placeholder gate measures its population against.
SIBLING_NON_SHAPES: list[tuple[str, str, str]] = [
    (
        "a table column identity beside its header is not a key beside its English",
        """{ key: 'unit_rate', label: 'Unit rate' }""",
        "unit_rate",
    ),
    (
        "a comment before a non-literal value must not reach past it to the next string",
        """
        {
          enabledKey: 'a.enabled',
          enabledDefault:
            // resolved at runtime, there is no English here
            someVariable,
          heading: 'Unrelated heading',
        }
        """,
        "a.enabled",
    ),
]


def cmd_selftest() -> int:
    """Pin the field arrangements english_sources() has to read English out of.

    Every one of these is a shape that resolved to nothing at some point, and an
    unresolved shape is silent by construction: the key keeps its English on
    every screen in every language, and no coverage check notices, because the
    key exists and carries a value. There is nothing to grep for, so the shapes
    have to be asserted.
    """
    failures = 0
    for name, text, key, english in SIBLING_SHAPES:
        got = sibling_pairs(text).get(key)
        if got != english:
            print(f"FAIL {name}: {key} resolved to {got!r}, expected {english!r}")
            failures += 1
    for name, text, key in SIBLING_NON_SHAPES:
        got = sibling_pairs(text).get(key)
        if got is not None:
            print(f"FAIL {name}: {key} should not resolve, got {got!r}")
            failures += 1
    if failures:
        print(f"{failures} of {len(SIBLING_SHAPES) + len(SIBLING_NON_SHAPES)} sibling shape(s) wrong")
        return 1
    print(f"OK {len(SIBLING_SHAPES)} sibling shape(s) resolve, {len(SIBLING_NON_SHAPES)} correctly do not")
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        return cmd_selftest()
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    action, code = sys.argv[1], sys.argv[2]
    if action == "plan":
        return cmd_plan(code)
    if action == "extract":
        size = 400
        if "--batch-size" in sys.argv:
            size = int(sys.argv[sys.argv.index("--batch-size") + 1])
        return cmd_extract(code, size, force="--force" in sys.argv)
    if action == "delta":
        return cmd_delta(code)
    if action == "assemble":
        return cmd_assemble(code, force="--force" in sys.argv)
    if action == "verify":
        return cmd_verify(code)
    print(f"unknown action {action!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
