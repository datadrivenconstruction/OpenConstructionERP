"""Check every pinned DDC converter package against the live release it is downloaded from.

The auto-installer refuses a package whose digest differs from the pin in
``backend/app/core/converter_source.py``. Upstream can re-upload assets under an
existing tag, which silently breaks every installed version at once. This check
reads each pinned release's checksum file and asset list over the network and
fails when a digest or a size no longer matches, so the drift is caught on a
schedule and before a release, not by a user.

    python scripts/check_converter_pins.py            # all hosts
    GITHUB_TOKEN=... python scripts/check_converter_pins.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(
    os.environ.get("CONVERTER_SOURCE")
    or ROOT / "backend" / "app" / "core" / "converter_source.py"
)


def _load_source():
    # Load the module by path: it is stdlib-only, so no backend import chain runs.
    spec = importlib.util.spec_from_file_location("converter_source", SOURCE)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _get(url: str, *, api: bool = False) -> bytes:
    headers = {"User-Agent": "openconstructionerp-pin-check"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if api:
        headers["Accept"] = "application/vnd.github+json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=60
    ) as resp:
        return resp.read()


def main() -> int:
    cs = _load_source()
    env: dict[str, str] = {}  # the shipped pins, never a local override
    repo = cs.resolve_converter_repo(env)
    sums_cache: dict[tuple[str, str], dict[str, str]] = {}
    sizes_cache: dict[str, dict[str, int]] = {}
    problems: list[str] = []
    checked = 0
    for pkg in cs.all_packages():
        tag = (
            cs.package_tag(pkg, env)
            if hasattr(cs, "package_tag")
            else cs.resolve_converter_tag(env)
        )
        key = (tag, pkg.checksums_asset)
        if key not in sums_cache:
            text = _get(
                cs.release_asset_url(pkg.checksums_asset, repo=repo, tag=tag)
            ).decode("utf-8", "replace")
            sums_cache[key] = cs.parse_sha256sums(text)
        if tag not in sizes_cache:
            rel = json.loads(
                _get(
                    f"https://api.github.com/repos/{repo}/releases/tags/{tag}", api=True
                )
            )
            sizes_cache[tag] = {
                a["name"]: int(a["size"]) for a in rel.get("assets", [])
            }
        published = sums_cache[key].get(pkg.asset)
        size = sizes_cache[tag].get(pkg.asset)
        where = f"{pkg.asset} ({pkg.platform_key}, {tag})"
        if size is None:
            problems.append(f"{where}: asset is missing from the release")
        elif size != pkg.size_bytes:
            problems.append(f"{where}: size pinned {pkg.size_bytes}, published {size}")
        if published is None:
            problems.append(f"{where}: not listed in {pkg.checksums_asset}")
        elif published != pkg.sha256.lower():
            problems.append(
                f"{where}: sha256 pinned {pkg.sha256}, published {published}"
            )
        checked += 1
    if problems:
        print(f"{len(problems)} converter pin problem(s) in {checked} packages:")
        for p in problems:
            print(f"  {p}")
        print(
            "Repin backend/app/core/converter_source.py from the release's own checksum file."
        )
        return 1
    print(f"converter pins OK: {checked} packages match their releases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
