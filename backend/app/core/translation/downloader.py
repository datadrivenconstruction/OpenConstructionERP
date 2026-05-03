"""On-demand downloaders for MUSE bilingual dictionaries and IATE dumps.

The user triggers these from the UI — we never download anything at boot
or at first use. Both targets land as TSVs in
``~/.openestimate/translations/{muse,iate}/{src}-{tgt}.tsv`` so the
:mod:`app.core.translation.lookup` module finds them automatically.

MUSE
~~~~
Source: ``https://dl.fbaipublicfiles.com/arrival/dictionaries/{src}-{tgt}.txt``
License: Creative Commons BY-NC 4.0 (free for non-commercial), the source
file ships as plain-text ``source<space>target`` pairs. We re-emit as
TSV with a default weight of 1.0.

IATE
~~~~
The IATE EU termbase ships as TBX (XML, ~600MB). Users download the
``IATE_export.tbx.zip`` from `https://iate.europa.eu/` and pass the local
path to :func:`process_iate_tbx`. We then walk the TBX with
``defusedxml`` (already in base deps — XXE-safe), pull out
``<termEntry>`` blocks, and split into per-language-pair TSV files.

Progress callbacks
~~~~~~~~~~~~~~~~~~
All long-running downloaders accept ``on_progress: Callable[[float], None]``.
The float is in [0.0, 1.0]. Callbacks are best-effort — any exception
raised by the callback is logged and swallowed so a buggy UI handler
can't break the download.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from app.core.translation.paths import dictionary_dir

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[float], Any | Awaitable[Any]]


_MUSE_URL = "https://dl.fbaipublicfiles.com/arrival/dictionaries/{src}-{tgt}.txt"
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


# IATE allowlist — any URL passed to ``download_iate_dump`` must start
# with one of these prefixes. Without this, an authenticated user could
# weaponize the backend as an SSRF probe (cloud metadata, internal
# services, etc.).  Set the env var ``OE_IATE_EXTRA_HOSTS`` to a
# comma-separated list of additional ``https://host/`` prefixes to allow
# self-hosted mirrors per deployment.
_IATE_ALLOWED_PREFIXES: tuple[str, ...] = (
    "https://iate.europa.eu/",
    "https://datadrivenconstruction.io/",
    "https://openconstructionerp.com/",
    "https://github.com/datadrivenconstruction/",
    "https://raw.githubusercontent.com/datadrivenconstruction/",
)


def _iate_allowlist() -> tuple[str, ...]:
    """Resolve the IATE allowlist at call time so env-var overrides are honored."""
    import os  # noqa: PLC0415 — lazy so tests can monkeypatch via env

    extra_raw = os.environ.get("OE_IATE_EXTRA_HOSTS", "")
    extra: tuple[str, ...] = tuple(
        p.strip() for p in extra_raw.split(",") if p.strip().startswith("https://")
    )
    return _IATE_ALLOWED_PREFIXES + extra


async def _emit_progress(cb: ProgressCallback | None, value: float) -> None:
    if cb is None:
        return
    try:
        ret = cb(value)
        if asyncio.iscoroutine(ret):
            await ret
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("Progress callback raised: %s", exc)


async def download_muse_pair(
    src: str,
    tgt: str,
    *,
    root: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Download a MUSE bilingual dictionary and convert it to TSV.

    Args:
        src: ISO-639 source code (lowercase).
        tgt: ISO-639 target code (lowercase).
        root: Override translations root.
        on_progress: Optional progress callback, called with floats in [0, 1].

    Returns:
        Path to the written TSV file.

    Raises:
        ValueError: If the language pair is unknown to MUSE (404).
        httpx.HTTPError: For other network failures.
    """
    src = src.lower().strip()
    tgt = tgt.lower().strip()
    target_dir = dictionary_dir(root) / "muse"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{src}-{tgt}.tsv"

    url = _MUSE_URL.format(src=src, tgt=tgt)
    logger.info("Downloading MUSE pair %s-%s from %s", src, tgt, url)

    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code == 404:
                msg = f"MUSE dictionary not available for {src}-{tgt}"
                raise ValueError(msg)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length") or 0)
            received = 0
            tmp_path = out_path.with_suffix(".tsv.partial")

            with tmp_path.open("wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    fh.write(chunk)
                    received += len(chunk)
                    if total > 0:
                        await _emit_progress(on_progress, received / total)

    # Convert MUSE format (space-separated source/target pairs, one per
    # line) to TSV. Run in executor — the file may be 30-50MB.
    def _convert() -> None:
        with tmp_path.open("r", encoding="utf-8", errors="replace") as fin, \
             out_path.open("w", encoding="utf-8") as fout:
            fout.write("# MUSE bilingual dictionary, source: facebookresearch/MUSE\n")
            for raw in fin:
                line = raw.rstrip("\n\r")
                if not line:
                    continue
                # MUSE separator is a single space. Source can be multi-word
                # in some pairs but it's rare; split on first whitespace
                # block, treat the rest as the target.
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                src_w, tgt_w = parts
                fout.write(f"{src_w}\t{tgt_w}\t1.0\n")
        try:
            tmp_path.unlink()
        except OSError:
            pass

    await asyncio.get_running_loop().run_in_executor(None, _convert)
    await _emit_progress(on_progress, 1.0)
    logger.info("MUSE pair %s-%s ready at %s", src, tgt, out_path)
    return out_path


async def download_iate_dump(
    *,
    url: str | None = None,
    root: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Download the IATE TBX dump as a single bytes file.

    The TBX dump is large (~600MB) and is gated behind the IATE web UI in
    practice; this helper exists for cases where the user has a direct
    URL to a self-hosted mirror. For most users the workflow is:

      1. Download manually from https://iate.europa.eu/download-iate
      2. Call :func:`process_iate_tbx` with the local path

    Args:
        url: Direct URL to a TBX or TBX.zip mirror. Required.
        root: Override translations root.
        on_progress: Optional progress callback.

    Returns:
        Path to the downloaded file (still TBX, not yet parsed).
    """
    if not url:
        msg = (
            "IATE auto-download requires a direct URL. Download the TBX dump "
            "manually from https://iate.europa.eu/download-iate and call "
            "process_iate_tbx(local_path) instead."
        )
        raise ValueError(msg)

    # SSRF guard — the URL is user-supplied via the API. Without an
    # allowlist an authenticated user could pivot the backend to fetch
    # AWS metadata (169.254.169.254), internal services, or attacker-
    # controlled redirects. We pin to the official IATE host plus a small
    # set of mirrors; deployment-specific mirrors come from
    # ``OE_IATE_EXTRA_HOSTS``.
    allowed = _iate_allowlist()
    if not any(url.startswith(prefix) for prefix in allowed):
        raise ValueError(
            "IATE URL not in allowlist. Permitted prefixes: "
            + ", ".join(allowed)
            + ". Set OE_IATE_EXTRA_HOSTS env var to add deployment mirrors.",
        )

    target_dir = dictionary_dir(root) / "iate"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / "iate_export.tbx"

    # ``follow_redirects=False`` so an attacker can't bypass the
    # allowlist by setting up a 302 to ``http://169.254.169.254/...``.
    async with httpx.AsyncClient(
        timeout=_DOWNLOAD_TIMEOUT, follow_redirects=False,
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            received = 0
            with out_path.open("wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                    fh.write(chunk)
                    received += len(chunk)
                    if total > 0:
                        await _emit_progress(on_progress, received / total)
    await _emit_progress(on_progress, 1.0)
    return out_path


async def process_iate_tbx(
    tbx_path: str | Path,
    *,
    root: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Path]:
    """Parse a TBX file and split it into per-language-pair TSVs.

    For each ``<termEntry>`` we collect every ``<langSec xml:lang="…">``
    block, then for every ordered pair (src, tgt) of distinct languages
    we emit one row per (src_term, tgt_term) cross product. Output goes
    to ``~/.openestimate/translations/iate/{src}-{tgt}.tsv``.

    Args:
        tbx_path: Local path to the TBX file (already downloaded).
        root: Override translations root.
        on_progress: Optional progress callback. Reports raw bytes
                     processed against file size.

    Returns:
        Mapping ``{"en-bg": Path(...), ...}`` of pairs that received at
        least one entry.
    """
    tbx_path = Path(tbx_path)
    if not tbx_path.exists():
        msg = f"TBX file not found: {tbx_path}"
        raise FileNotFoundError(msg)

    target_dir = dictionary_dir(root) / "iate"
    target_dir.mkdir(parents=True, exist_ok=True)

    # XML parsing in an executor — the TBX is huge.
    def _parse() -> dict[str, Path]:
        from defusedxml import ElementTree as ET  # noqa: N817 — stdlib convention

        # Streaming iterparse keeps memory bounded.
        out_files: dict[str, Any] = {}  # pair -> open file handle
        out_paths: dict[str, Path] = {}

        try:
            context = ET.iterparse(str(tbx_path), events=("end",))
            for _event, elem in context:
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag != "termEntry":
                    continue
                # Collect terms grouped by language.
                lang_terms: dict[str, list[str]] = {}
                for lang_sec in elem.iter():
                    ltag = lang_sec.tag.rsplit("}", 1)[-1]
                    if ltag != "langSec":
                        continue
                    lang = (
                        lang_sec.get("{http://www.w3.org/XML/1998/namespace}lang")
                        or lang_sec.get("lang")
                        or ""
                    ).lower().split("-")[0]
                    if not lang:
                        continue
                    terms: list[str] = []
                    for term_node in lang_sec.iter():
                        ttag = term_node.tag.rsplit("}", 1)[-1]
                        if ttag == "term" and term_node.text:
                            t = term_node.text.strip()
                            if t:
                                terms.append(t)
                    if terms:
                        lang_terms.setdefault(lang, []).extend(terms)

                # Emit pairs.
                langs = list(lang_terms.keys())
                for src_lang in langs:
                    for tgt_lang in langs:
                        if src_lang == tgt_lang:
                            continue
                        pair_key = f"{src_lang}-{tgt_lang}"
                        if pair_key not in out_files:
                            p = target_dir / f"{pair_key}.tsv"
                            fh = p.open("w", encoding="utf-8")
                            fh.write(
                                "# IATE EU termbase, parsed from TBX dump\n"
                            )
                            out_files[pair_key] = fh
                            out_paths[pair_key] = p
                        fh = out_files[pair_key]
                        for s in lang_terms[src_lang]:
                            for t in lang_terms[tgt_lang]:
                                fh.write(f"{s}\t{t}\t1.0\n")

                # Free memory — iterparse retains the parsed tree by
                # default, which is fatal on a 600MB file.
                elem.clear()
        finally:
            for fh in out_files.values():
                try:
                    fh.close()
                except OSError:
                    pass

        return out_paths

    paths = await asyncio.get_running_loop().run_in_executor(None, _parse)
    await _emit_progress(on_progress, 1.0)
    logger.info("IATE TBX parsed into %d language pairs", len(paths))
    return paths


def list_downloaded(root: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Inspect the dictionary directory and report what's available.

    Returns:
        ``{"muse": [{"pair": "en-bg", "path": "...", "size_bytes": …,
                     "modified_at": "..."}], "iate": [...]}``
    """
    out: dict[str, list[dict[str, Any]]] = {"muse": [], "iate": []}
    base = dictionary_dir(root)
    for sub in ("muse", "iate"):
        d = base / sub
        if not d.exists():
            continue
        for tsv in sorted(d.glob("*.tsv")):
            try:
                stat = tsv.stat()
                out[sub].append(
                    {
                        "pair": tsv.stem,
                        "path": str(tsv),
                        "size_bytes": stat.st_size,
                        "modified_at": stat.st_mtime,
                    }
                )
            except OSError:
                continue
    return out
