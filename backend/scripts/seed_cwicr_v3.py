# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Seed a fresh OpenConstructionERP install with CWICR v3 catalogues.

Solves the "fresh-install needs a human to visit /costs and click
Install for every region" problem from task #39 in the 2-day match
universalisation plan. Operators run this once after ``pip install
openconstructionerp`` + ``alembic upgrade head`` and the deployment
boots with the BGE-M3 v3 collections pre-loaded.

Usage::

    python -m scripts.seed_cwicr_v3 --regions USA_USD,GB_LONDON,DE_BERLIN
    python -m scripts.seed_cwicr_v3 --top-n 3
    python -m scripts.seed_cwicr_v3 --top-n 3 --dry-run

The script bypasses the FastAPI route layer on purpose — calling the
HTTP endpoint would require a running server, an auth token, and a
``costs.create`` permission. The underlying helpers
(:func:`restore_snapshot_file`, the cache-path helper, and the GitHub
download URL constant) are the same ones the route uses, so the
behaviour matches the in-app install button byte-for-byte.

Exit codes:

* ``0`` — all requested catalogues installed successfully.
* ``1`` — at least one catalogue failed (download or restore).
* ``2`` — argument error / unknown region id.
* ``3`` — no Qdrant server configured. Set ``CWICR_QDRANT_URL`` (or
  ``QDRANT_URL`` for single-server dev) before re-running, OR pass
  ``--dry-run`` to preview without contacting a server.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ``python scripts/seed_cwicr_v3.py`` adds the script's own dir to
# sys.path but not the package root. ``python -m scripts.seed_cwicr_v3``
# from ``backend/`` works without this shim, but the explicit path
# insert lets the script run either way — handy for one-shot ops.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.modules.costs.cwicr_v3_catalogue import (  # noqa: E402
    CWICR_V3_CATALOGUES,
    CwicrV3Catalogue,
    get_catalogue,
)
from app.modules.costs.qdrant_snapshot_loader import (  # noqa: E402
    restore_snapshot_file,
    server_collections,
)

# Mirror of router constants — duplicated rather than imported because
# ``app.modules.costs.router`` pulls FastAPI/auth/DB and we want a
# zero-FastAPI CLI surface. If either constant changes, update both —
# the unit tests assert the registry vs adapter mapping, so drift will
# surface there first.
_GITHUB_CWICR_BASE_URL = "https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR/raw/main"


def _v3_snapshot_cache_path(region: str) -> Path:
    """‌⁠‍Mirror of ``router._v3_snapshot_cache_path``.

    Kept in lockstep so a download issued by this CLI populates the
    same cache the in-app install button reads — repeat installs are
    free of network cost regardless of which entry-point triggered the
    first fetch.
    """
    return Path.home() / ".openestimator" / "cache" / "snapshots-v3" / f"{region}.snapshot"


def _resolve_qdrant_url() -> str | None:
    """‌⁠‍Mirror of ``router._v3_qdrant_url`` — prefers the dedicated v3 setting."""
    try:
        from app.config import get_settings
    except Exception as exc:
        print(f"WARN: could not read settings: {exc}", file=sys.stderr)
        return None

    s = get_settings()
    return getattr(s, "cwicr_qdrant_url", None) or getattr(s, "qdrant_url", None)


def _download_to_file(url: str, dest: Path, timeout: float = 600.0) -> None:
    """Stream a URL to ``dest`` with httpx + certifi (Windows-safe SSL).

    Same logic as ``router._download_to_file`` — copied here to avoid
    importing the FastAPI router module. See router.py:2560 for the
    Windows CA-store rationale (issue #104).
    """
    import httpx

    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "openconstructionerp-seed-cli"},
    ) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)


def _pick_top_n(n: int) -> list[CwicrV3Catalogue]:
    """Pick the N "most popular" available catalogues — deterministic.

    "Popular" here is a stand-in for an actual usage signal we don't
    have yet: sort the available rows by ``country_iso`` ascending and
    take the first N. Result is stable across runs and deployments,
    which is what an automation cares about. Once we have install
    telemetry the heuristic can grow into a real ranking.
    """
    available = sorted(
        (c for c in CWICR_V3_CATALOGUES if c.available),
        key=lambda c: c.country_iso,
    )
    return available[:n]


def _resolve_requested(regions_csv: str | None, top_n: int | None) -> tuple[list[CwicrV3Catalogue], list[str]]:
    """Resolve the user's selection into concrete catalogue rows.

    Returns ``(catalogues, errors)``. Unknown region ids land in the
    error list with a human-readable hint; the caller decides whether
    a partial run is acceptable. ``--top-n`` and ``--regions`` are
    mutually exclusive at the argparse layer so we don't have to
    reconcile them here.
    """
    errors: list[str] = []
    catalogues: list[CwicrV3Catalogue] = []

    if regions_csv:
        for raw in regions_csv.split(","):
            region = raw.strip()
            if not region:
                continue
            cat = get_catalogue(region)
            if cat is None:
                errors.append(
                    f"unknown region {region!r} — see backend/app/modules/costs/cwicr_v3_catalogue.py for the full list"
                )
                continue
            if not cat.available:
                errors.append(
                    f"{cat.region}: DDC has not yet published the v3 snapshot (marked available=False in the registry)"
                )
                continue
            catalogues.append(cat)
        return catalogues, errors

    if top_n is not None:
        picks = _pick_top_n(top_n)
        if not picks:
            errors.append(
                "no available v3 catalogues in the registry — check available=True flags in cwicr_v3_catalogue.py"
            )
        return picks, errors

    errors.append("must pass --regions <CSV> or --top-n N")
    return [], errors


def _install_one(
    cat: CwicrV3Catalogue,
    *,
    qdrant_url: str,
    dry_run: bool = False,
) -> bool:
    """Download + restore one catalogue. Returns True on success.

    On any failure logs an ERROR and returns False — the caller
    aggregates and decides the final exit code. We deliberately do
    NOT raise; one bad region shouldn't tank a multi-region seed run.
    """
    log = logging.getLogger("seed_cwicr_v3")

    cache_path = _v3_snapshot_cache_path(cat.region)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    needs_download = not cache_path.exists() or cache_path.stat().st_size < 1_000_000
    if needs_download:
        url = f"{_GITHUB_CWICR_BASE_URL}/{cat.ddc_path}"
        log.info(
            "[%s] downloading from DDC (~%d MB): %s",
            cat.region,
            cat.size_mb,
            url,
        )
        if dry_run:
            log.info("[%s] DRY-RUN: would download to %s", cat.region, cache_path)
        else:
            try:
                _download_to_file(url, cache_path)
            except Exception as exc:
                cache_path.unlink(missing_ok=True)
                log.error("[%s] download failed: %s", cat.region, exc)
                return False
            if not cache_path.exists() or cache_path.stat().st_size < 1_000_000:
                cache_path.unlink(missing_ok=True)
                log.error(
                    "[%s] downloaded file too small or missing — DDC may not have published this snapshot yet",
                    cat.region,
                )
                return False
    else:
        log.info(
            "[%s] using cached snapshot %s (%.1f MB)",
            cat.region,
            cache_path,
            cache_path.stat().st_size / 1e6,
        )

    if dry_run:
        log.info(
            "[%s] DRY-RUN: would restore into collection %s",
            cat.region,
            cat.collection,
        )
        return True

    try:
        ok = restore_snapshot_file(
            qdrant_url=qdrant_url,
            collection_name=cat.collection,
            snapshot_path=cache_path,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        log.error("[%s] restore failed: %s", cat.region, exc)
        return False

    if not ok:
        log.error("[%s] Qdrant rejected the snapshot upload — see server logs", cat.region)
        return False

    log.info(
        "[%s] installed into collection %s",
        cat.region,
        cat.collection,
    )
    return True


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seed_cwicr_v3",
        description="Install one or more CWICR v3 BGE-M3 catalogues into Qdrant.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--regions",
        default=None,
        help="Comma-separated region ids, e.g. USA_USD,GB_LONDON,DE_BERLIN",
    )
    g.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Install the N most popular available catalogues (deterministic by country_iso)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve catalogues and print what would happen without downloading or restoring",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="DEBUG-level logging",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("seed_cwicr_v3")

    catalogues, errors = _resolve_requested(args.regions, args.top_n)
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    if not catalogues:
        return 2

    qdrant_url = _resolve_qdrant_url()
    if not qdrant_url and not args.dry_run:
        print(
            "FAIL: no Qdrant server configured. Set CWICR_QDRANT_URL "
            "(or QDRANT_URL for single-server dev) and ensure the server "
            "is reachable. Use --dry-run to preview without contacting a server.",
            file=sys.stderr,
        )
        return 3

    log.info(
        "Seeding %d catalogue(s)%s: %s",
        len(catalogues),
        " (DRY-RUN)" if args.dry_run else "",
        ", ".join(c.region for c in catalogues),
    )

    if qdrant_url and not args.dry_run:
        before = server_collections(qdrant_url=qdrant_url)
        log.info("Qdrant pre-flight: %d collection(s) currently present", len(before))

    succeeded: list[str] = []
    failed: list[str] = []
    for cat in catalogues:
        if _install_one(cat, qdrant_url=qdrant_url or "", dry_run=args.dry_run):
            succeeded.append(cat.region)
        else:
            failed.append(cat.region)

    print()
    print(f"Installed ({len(succeeded)}): {', '.join(succeeded) if succeeded else '(none)'}")
    if failed:
        print(f"Failed   ({len(failed)}): {', '.join(failed)}")

    if qdrant_url and not args.dry_run:
        after = server_collections(qdrant_url=qdrant_url)
        v3 = sorted(c for c in after if c.startswith("cwicr_") and c.endswith("_v3"))
        print(f"v3 collections on server now: {v3 or '(none)'}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
