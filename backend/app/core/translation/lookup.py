"""MUSE + IATE lookup tables — phrase-aware matching against TSV files.

Files live under ``~/.openestimate/translations/{muse,iate}/{src}-{tgt}.tsv``
in the format ``source_word<TAB>target_word<TAB>weight``. Header lines
starting with ``#`` are ignored. The user downloads these on demand via the
``downloader`` module — this file never touches the network.

Phrase strategy
~~~~~~~~~~~~~~~
For an input phrase ``"Concrete C30/37 Wall"`` we try in order:

1. **Whole-phrase exact** lookup (case-insensitive, normalised whitespace).
2. **Whole-phrase fuzzy** match via rapidfuzz (>= 90 score).
3. **Per-token translation** — look up each whitespace token, but skip
   tokens that look like a code (digits, punctuation, mixed alphanumerics
   like ``C30/37`` or ``L=2.5m``). Codes are passed through unchanged.
4. If fewer than half the lexical tokens were translated, return ``None``
   and let the cascade move to the next tier.

The returned confidence is weighted by how many of the lexical tokens were
hit and whether the match was exact or fuzzy.
"""

from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from pathlib import Path

from app.core.translation.paths import dictionary_dir

logger = logging.getLogger(__name__)


# Tokens that look like codes / measurements / pure numbers should be
# preserved verbatim and not counted against translation coverage.
_CODE_RE = re.compile(
    r"^("
    r"[+\-]?\d+([.,]\d+)?"  # numbers
    r"|[A-Z][A-Z0-9]*[/\-][A-Z0-9./\-]+"  # codes like C30/37, EN-1992
    r"|[A-Z]\d+([./\-]\d+)*"  # codes like B25, M16, F90
    r"|[\d.,/\-+]+[A-Za-z]+\d*"  # 2.5m, 24cm, 8mm
    r"|[A-Z]+\d+"  # IPE100, HEA200
    r")$"
)
_PUNCT_RE = re.compile(r"^[\W_]+$", flags=re.UNICODE)
_TOKEN_SPLIT_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _is_code(token: str) -> bool:
    if not token:
        return True
    if _PUNCT_RE.match(token):
        return True
    return bool(_CODE_RE.match(token))


@lru_cache(maxsize=64)
def _load_tsv(path_str: str) -> dict[str, tuple[str, float]]:
    """Load a TSV dictionary into a normalised lookup dict.

    Cached on a per-path basis. Returns an empty dict when the file is
    missing — the caller then falls through to the next tier.
    """
    path = Path(path_str)
    if not path.exists():
        return {}
    out: dict[str, tuple[str, float]] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.rstrip("\n\r")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                src = _normalise(parts[0])
                tgt = parts[1].strip()
                try:
                    weight = float(parts[2]) if len(parts) > 2 else 1.0
                except ValueError:
                    weight = 1.0
                if not src or not tgt:
                    continue
                # Keep highest-weight entry per source phrase.
                prev = out.get(src)
                if prev is None or prev[1] < weight:
                    out[src] = (tgt, weight)
    except OSError as exc:
        logger.debug("Could not read dictionary %s: %s", path, exc)
        return {}
    return out


def _dictionary_path(
    dictionary: str, src: str, tgt: str, root: str | None = None
) -> Path:
    return dictionary_dir(root) / dictionary / f"{src}-{tgt}.tsv"


async def lookup_phrase(
    text: str,
    src: str,
    tgt: str,
    *,
    dictionary: str = "muse",
    root: str | None = None,
) -> tuple[str, float] | None:
    """Translate a phrase via the named on-disk dictionary.

    Returns ``(translated_text, confidence)`` on hit, ``None`` on miss
    (file absent or insufficient coverage).
    """
    path = _dictionary_path(dictionary, src, tgt, root)

    # File I/O off the event loop — TSVs may be 100k+ lines.
    table = await asyncio.get_running_loop().run_in_executor(
        None, _load_tsv, str(path)
    )
    if not table:
        return None

    # 1. Whole-phrase exact match.
    norm = _normalise(text)
    if norm in table:
        translated, weight = table[norm]
        # Exact phrase = high confidence; weight is auxiliary.
        return translated, min(1.0, 0.95 + 0.05 * min(weight, 1.0))

    # 2. Whole-phrase fuzzy match (rapidfuzz). We MUST use ``fuzz.ratio``
    #    (full-string similarity), not the default ``WRatio`` / partial
    #    matching — partial-ratio would happily match "concrete c30/37
    #    wall" against the dictionary key "concrete" with score 100, which
    #    is a false positive that defeats per-token fallback below.
    try:
        from rapidfuzz import fuzz, process

        keys = list(table.keys())
        match = process.extractOne(
            norm, keys, scorer=fuzz.ratio, score_cutoff=90
        )
        if match is not None:
            best_key, score, _ = match
            translated, _w = table[best_key]
            return translated, score / 100.0
    except ImportError:  # pragma: no cover — rapidfuzz is in base deps
        pass

    # 3. Per-token translation, code-aware.
    tokens = _TOKEN_SPLIT_RE.split(text.strip())
    if not tokens:
        return None

    out_tokens: list[str] = []
    lexical_total = 0
    lexical_hit = 0
    for tok in tokens:
        if _is_code(tok):
            # Pass codes / numbers / punctuation through unchanged.
            out_tokens.append(tok)
            continue
        lexical_total += 1
        norm_tok = _normalise(tok)
        if norm_tok in table:
            translated, _w = table[norm_tok]
            out_tokens.append(translated)
            lexical_hit += 1
        else:
            out_tokens.append(tok)  # leave untranslated; report low coverage

    if lexical_total == 0:
        # Pure-code phrase ("C30/37"). Treat as a perfect translation —
        # the codes are preserved verbatim.
        return " ".join(out_tokens), 1.0

    coverage = lexical_hit / lexical_total
    if coverage < 0.5:
        return None

    # Coverage scales confidence. Token-level matches are inherently
    # less reliable than full-phrase matches, so cap at 0.85.
    confidence = 0.5 + 0.35 * coverage
    return " ".join(out_tokens), round(confidence, 4)
