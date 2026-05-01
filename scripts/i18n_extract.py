"""Extract EN source + per-lang missing/bleed maps from i18n-fallbacks.ts.

Output written under ``./tmp/i18n/``:
  - en-source.json                    — { key: en_value } (all EN keys)
  - missing-{lang}.json               — { key: en_value } for keys lang is
                                        missing OR has bleed (same as EN
                                        and looks like English).
  - state.json                        — summary stats per lang.

Sets up the parallel-agent pipeline: each agent reads its missing-{lang}.json,
translates, writes patch-{lang}.json. The merge step (``i18n_apply.py``)
reads all patches and rewrites i18n-fallbacks.ts in one pass.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src" / "app" / "i18n-fallbacks.ts"
OUT = ROOT / "tmp" / "i18n"
OUT.mkdir(parents=True, exist_ok=True)


# Each language block in i18n-fallbacks.ts looks like:
#   <code>: {
#     translation: {
#       <kebab-key>: '<value>',
#       ...
#     },
#   },
#
# Capture the language block boundaries by their two-letter code header.
LANG_BLOCK_RE = re.compile(
    r"^\s{2}([a-z]{2,3}):\s*\{\s*$\s+translation:\s*\{",
    re.MULTILINE,
)
# A single key:value entry inside a translation block. Values are usually
# single-quoted; we tolerate escaped quotes and multi-line via a non-greedy
# match terminated at the unescaped trailing quote + comma. Keys are the
# usual i18next dot/underscore form.
KEY_RE = re.compile(
    r"^\s+'([^']+)':\s*'((?:\\'|[^'])*)',?\s*$",
    re.MULTILINE,
)


def parse_blocks(source: str) -> dict[str, dict[str, str]]:
    """Return ``{lang: {key: value}}`` for every language in the file."""
    blocks: dict[str, dict[str, str]] = {}

    starts = [(m.group(1), m.start()) for m in LANG_BLOCK_RE.finditer(source)]
    for i, (lang, pos) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(source)
        chunk = source[pos:end]
        kv: dict[str, str] = {}
        for m in KEY_RE.finditer(chunk):
            key = m.group(1)
            val = m.group(2).encode().decode("unicode_escape", errors="replace")
            # strip trailing/leading whitespace; preserve internal
            kv[key] = val
        blocks[lang] = kv
    return blocks


# Heuristic: a value is "English bleed" when it equals the EN value AND
# looks like English prose — at least 2 ASCII word tokens, none of which
# are obvious code/identifiers/URLs/placeholders. Cyrillic, Han, Hiragana,
# Katakana, Hangul, Devanagari, Thai, Arabic etc. are non-Latin so any
# such char in the value disqualifies it from "bleed."
WORD_RE = re.compile(r"[A-Za-z]{2,}")
NON_LATIN_RE = re.compile(r"[Ѐ-ӿ֐-׿؀-ۿऀ-ॿ฀-๿぀-ヿ㐀-䶿一-鿿가-힯]")


def looks_english(value: str) -> bool:
    if not value or not value.strip():
        return False
    if NON_LATIN_RE.search(value):
        return False
    # ignore values that are mostly placeholders/code/URLs
    stripped = re.sub(r"\{\{[^}]+\}\}|\{[^}]+\}|<[^>]+>|https?://\S+", "", value)
    words = WORD_RE.findall(stripped)
    if len(words) < 2:
        return False
    # Skip identifiers / acronyms-only
    real_words = [w for w in words if not w.isupper()]
    return len(real_words) >= 1


def main() -> None:
    source = SRC.read_text(encoding="utf-8")
    blocks = parse_blocks(source)
    if "en" not in blocks:
        raise SystemExit("EN block not found")
    en = blocks["en"]
    (OUT / "en-source.json").write_text(
        json.dumps(en, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    state: dict[str, dict[str, int]] = {}
    for lang, kv in blocks.items():
        if lang == "en":
            continue
        missing: dict[str, str] = {}
        bleed_count = 0
        for k, en_v in en.items():
            v = kv.get(k)
            if v is None:
                missing[k] = en_v
                continue
            if v == en_v and looks_english(v):
                missing[k] = en_v
                bleed_count += 1
        state[lang] = {
            "total": len(kv),
            "bleed": bleed_count,
            "missing_or_bleed": len(missing),
        }
        (OUT / f"missing-{lang}.json").write_text(
            json.dumps(missing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (OUT / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote en-source.json + {len(state)} missing-{{lang}}.json files to {OUT}")
    for lang, s in sorted(state.items(), key=lambda kv: -kv[1]["missing_or_bleed"]):
        print(f"  {lang}: {s['missing_or_bleed']:>4} keys to fix (bleed={s['bleed']})")


if __name__ == "__main__":
    main()
