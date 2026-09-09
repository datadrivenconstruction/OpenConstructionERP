#!/usr/bin/env python3
"""Every route the app can serve has to be carried by the proxy allowlist.

The public origin serves two things from one hostname: the static marketing
site and the single-page application. Caddy decides which one a URL belongs to
from a single allowlist of top-level path segments, the ``path_regexp``
alternation inside the ``@apparoute`` matcher. A path whose first segment is in
that alternation is reverse-proxied to the app; everything else falls through
to ``try_files`` and the visitor gets the static site's 404. An SPA cannot set
an HTTP status, so this proxy-level list is a copy of a route table the app
owns, and the failure mode of a copy is drift.

The drift is not hypothetical and it is not small. On 2026-09-09 the whole
regional BOQ exchange feature, ``/regional-exchange`` and twenty country
screens, answered 404 on the public origin. The gate that exists for this
class of defect was run that same day and passed over all twenty one of them,
because it read ``<Route path="...">`` out of ``App.tsx`` and nothing else,
and those routes are contributed by a module manifest that builds its paths
from a table. Three other routes it did catch. Twenty four were missing; it
named three.

So the route side of the comparison now comes from ``scripts/app_routes.py``,
which reads App.tsx and every module manifest and resolves the computed paths
instead of skipping them. Anything it cannot resolve fails this gate rather
than being dropped, because a route nobody can enumerate is precisely the one
that reaches the public origin as a 404.

The allowlist side has two forms, and the difference matters:

  * ``--caddyfile <path>`` reads the alternation out of a real Caddyfile. This
    is the authoritative comparison and it is the one that needs the live file
    off the production host, so it cannot run in CI:
        scp root@openconstructionerp.com:/root/clawd/conference-chat/Caddyfile /tmp/Caddyfile.live
        python scripts/check_app_route_allowlist.py --caddyfile /tmp/Caddyfile.live
  * with no ``--caddyfile``, it compares against the committed mirror
    ``scripts/app_route_allowlist.txt``. CI has no access to the host, so this
    is what runs there. It catches the common case, a route added to the tree
    with nothing added to the proxy, on the same commit that adds the route.

The mirror is not a second source of truth about routes, and this is the one
thing not to get wrong about it. It is extracted from a real Caddyfile with
``--write-mirror --caddyfile <path>`` and never generated from the route
table. A mirror generated from the routes would agree with the routes by
construction and vouch for a proxy nobody had touched. If CI is red here, the
fix is to add the segment to the live Caddyfile, reload it, and then re-extract
the mirror from it, in that order.

Because a committed mirror can go stale against the host, there is a third
mode for the deploy step:

    python scripts/check_app_route_allowlist.py --compare-mirror --caddyfile /tmp/Caddyfile.live

which says nothing about routes and only asks whether the committed mirror
still matches the live allowlist.

Exit codes: 0 in sync, 1 drift found, 2 could not read an input or could not
find the allowlist. It never exits 0 on a failure to measure.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_routes import collect, population_lines, print_unresolved, require_self_test  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MIRROR = REPO_ROOT / "scripts" / "app_route_allowlist.txt"

# The alternation out of the @apparoute matcher. Scanning forward from the
# block opener rather than matching the block body: the body contains Caddy
# placeholders like {path}, so a "not a closing brace" match stops at the first
# one and never reaches path_regexp.
ALLOWLIST_RE = re.compile(r"@apparoute[\s\S]{0,4000}?path_regexp\s+\^/\(([^)]+)\)\(/\|\$\)")

MIRROR_HEADER = """\
# Top-level path segments the production reverse proxy forwards to the app.
#
# EXTRACTED FROM A CADDYFILE, NEVER GENERATED FROM THE ROUTE TABLE. This file
# is one half of a comparison; scripts/app_routes.py is the other half. If it
# were written from the routes it would agree with them by construction and
# would vouch for a proxy nobody had touched, which is the exact defect the
# comparison exists to catch.
#
# Regenerate only from a real Caddyfile, after the change is live:
#   scp root@openconstructionerp.com:/root/clawd/conference-chat/Caddyfile /tmp/Caddyfile.live
#   python scripts/check_app_route_allowlist.py --write-mirror --caddyfile /tmp/Caddyfile.live
#
# A red run of scripts/check_app_route_allowlist.py is fixed in the live
# Caddyfile first and here second. Editing this file to make CI green ships a
# route that still 404s for every visitor.
#
# Extracted from: {source} (sha256 {digest})
# Segments: {count}
"""


def read_caddy_allowlist(path: Path) -> set[str]:
    """The segment set out of a Caddyfile's @apparoute matcher."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read Caddyfile: {path}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    match = ALLOWLIST_RE.search(src)
    if not match:
        print(f"could not find the @apparoute path_regexp allowlist in {path}.", file=sys.stderr)
        print("either the block was renamed or the 404 handling was removed.", file=sys.stderr)
        raise SystemExit(2)
    segments = {s.strip() for s in match.group(1).split("|") if s.strip()}
    if not segments:
        print(f"the @apparoute allowlist in {path} is empty, which cannot be right.", file=sys.stderr)
        raise SystemExit(2)
    return segments


def read_mirror(path: Path) -> set[str]:
    """The committed copy of the allowlist."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"cannot read the committed allowlist mirror: {path}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("regenerate it from a live Caddyfile, see this script's header.", file=sys.stderr)
        raise SystemExit(2) from exc
    segments = {line.strip() for line in lines if line.strip() and not line.startswith("#")}
    if not segments:
        print(f"the committed allowlist mirror {path} carries no segments.", file=sys.stderr)
        raise SystemExit(2)
    return segments


def write_mirror(path: Path, segments: set[str], source: Path) -> None:
    """Write the mirror, stamped with the digest of the Caddyfile it came from.

    The name of the source file says nothing useful: it is whatever the person
    scp'd it to. The digest identifies the exact bytes, so a later reader can
    hold a Caddyfile next to this file and tell whether it is the one.
    """
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    body = MIRROR_HEADER.format(source=source.name, digest=digest, count=len(segments))
    body += "\n".join(sorted(segments)) + "\n"
    path.write_text(body, encoding="utf-8")


def route_segments(table) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Split the routes into what the allowlist can carry and what it cannot.

    Returns the segment to routes map, the routes covered by the origin's own
    handling, and the routes that cannot be allowlisted at all.

    Two routes are covered elsewhere and are counted rather than dropped in
    silence: the root ``/``, which the origin serves as the landing page, and
    the catch-all ``*``, which has no segment to put in an alternation.

    A route whose FIRST segment is a parameter is a different thing entirely.
    It has no literal segment either, so it cannot appear in the alternation
    and it 404s on the public origin for every value the parameter takes, and
    no amount of editing the Caddyfile fixes it. There is none in the tree
    today. If one ever appears, this names it and fails, because being quiet
    about a route that cannot be carried is the failure this gate exists for.

    Everything else contributes, including routes owned by a module that ships
    switched off. Module enablement is client side, so a visitor who turns a
    module on still has to get through Caddy to reach its screens, and a
    segment missing from the allowlist 404s before the app is ever asked.
    """
    wanted: dict[str, list[str]] = {}
    served_elsewhere: list[str] = []
    unallowlistable: list[str] = []
    for route in table.routes:
        label = f"{route.path} ({route.source}, {route.origin})"
        segment = route.segment
        if not segment or segment == "*":
            served_elsewhere.append(label)
            continue
        if segment.startswith(":"):
            unallowlistable.append(label)
            continue
        wanted.setdefault(segment, []).append(label)
    return wanted, served_elsewhere, unallowlistable


def print_unallowlistable(routes: list[str]) -> None:
    sys.stdout.flush()
    print("", file=sys.stderr)
    print(
        f"UNALLOWLISTABLE: {len(routes)} route(s) begin with a parameter segment.",
        file=sys.stderr,
    )
    print(
        "A segment allowlist can only carry literals, so these 404 on the public origin for "
        "every value the parameter takes and no Caddyfile edit fixes that:",
        file=sys.stderr,
    )
    for route in sorted(routes):
        print(f"  {route}", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Give the route a literal first segment, or move the app to a path prefix of its own. "
        "Do not add it to a skip list: a route nobody can reach is the defect this gate exists "
        "to name.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--caddyfile", help="a real Caddyfile to read the allowlist from")
    parser.add_argument(
        "--write-mirror",
        action="store_true",
        help="rewrite scripts/app_route_allowlist.txt from --caddyfile",
    )
    parser.add_argument(
        "--compare-mirror",
        action="store_true",
        help="only compare the committed mirror against --caddyfile, ignore the routes",
    )
    args = parser.parse_args(argv)

    if (args.write_mirror or args.compare_mirror) and not args.caddyfile:
        print("--write-mirror and --compare-mirror both need --caddyfile.", file=sys.stderr)
        return 2

    if args.write_mirror:
        caddy_path = Path(args.caddyfile).resolve()
        segments = read_caddy_allowlist(caddy_path)
        # A mirror the current tree already contradicts is refused rather than
        # written. The obvious way to hurt yourself here is to extract from a
        # Caddyfile that lags the host, of which there are several copies about;
        # that would install a mirror short of routes the app serves, and the
        # next run would be red for a reason that has nothing to do with the
        # commit that turned it red. If this refuses, the live Caddyfile is
        # genuinely missing routes, which is the finding, not an obstacle.
        require_self_test()
        table = collect()
        if table.unresolved:
            print_unresolved(table)
            return 1
        wanted, _served, unallowlistable = route_segments(table)
        if unallowlistable:
            print_unallowlistable(unallowlistable)
            return 1
        short = sorted(segment for segment in wanted if segment not in segments)
        if short:
            sys.stdout.flush()
            print("", file=sys.stderr)
            print(
                f"REFUSING TO WRITE: {caddy_path} is missing {len(short)} segment(s) the app router serves.",
                file=sys.stderr,
            )
            for segment in short:
                print(f"  /{segment}", file=sys.stderr)
            print("", file=sys.stderr)
            print(
                "Either this Caddyfile is not the live one, or the live one has not been "
                "updated yet. Fix the proxy first, then extract from it.",
                file=sys.stderr,
            )
            return 1
        write_mirror(MIRROR, segments, caddy_path)
        print(f"wrote {MIRROR} with {len(segments)} segments extracted from {caddy_path}")
        print(f"checked against {len(wanted)} segments the current route table needs")
        return 0

    if args.compare_mirror:
        caddy_path = Path(args.caddyfile).resolve()
        live = read_caddy_allowlist(caddy_path)
        mirror = read_mirror(MIRROR)
        print(f"live allowlist   : {caddy_path} ({len(live)} segments)")
        print(f"committed mirror : {MIRROR} ({len(mirror)} segments)")
        only_live = sorted(live - mirror)
        only_mirror = sorted(mirror - live)
        if not only_live and not only_mirror:
            print("OK: the committed mirror matches the live allowlist exactly.")
            return 0
        sys.stdout.flush()
        print("", file=sys.stderr)
        print("MIRROR DRIFT: the committed copy no longer matches the live Caddyfile.", file=sys.stderr)
        for segment in only_live:
            print(f"  live only  : {segment}", file=sys.stderr)
        for segment in only_mirror:
            print(f"  mirror only: {segment}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Re-extract with --write-mirror --caddyfile <the live file>.", file=sys.stderr)
        return 1

    # Same reason as everywhere else this collector is used: a set of patterns
    # that has stopped matching returns a short list of routes, and a short list
    # of routes agrees with any allowlist at all.
    require_self_test()

    table = collect()
    for line in population_lines(table):
        print(line)

    if table.unresolved:
        print_unresolved(table)
        return 1

    if args.caddyfile:
        source = Path(args.caddyfile).resolve()
        allowed = read_caddy_allowlist(source)
        origin = f"Caddyfile {source}"
    else:
        source = MIRROR
        allowed = read_mirror(MIRROR)
        origin = f"committed mirror {MIRROR}"

    wanted, served_elsewhere, unallowlistable = route_segments(table)
    print(f"allowlist source       : {origin}")
    print(f"segments in allowlist  : {len(allowed)}")
    print(f"segments routes need   : {len(wanted)}")
    print(
        f"routes with no segment : {len(served_elsewhere)} served by the origin itself, "
        f"{len(unallowlistable)} that no allowlist can carry"
    )

    if unallowlistable:
        print_unallowlistable(unallowlistable)
        return 1

    missing = sorted(segment for segment in wanted if segment not in allowed)
    # Not an error: the allowlist deliberately carries segments from a shipped
    # bundle the current source no longer declares, so a build that is still
    # live keeps working. Reported so the list can be trimmed deliberately.
    extra = sorted(segment for segment in allowed if segment not in wanted)
    print(f"allowlist-only segments: {len(extra)} (kept on purpose, an older bundle may still use them)")

    if missing:
        # Flush first. The population above went to stdout, this goes to stderr,
        # and into a pipe stdout is block buffered while stderr is not, so a CI
        # log would otherwise carry the verdict first and the numbers behind it.
        sys.stdout.flush()
        print("", file=sys.stderr)
        print(
            f"DRIFT: {len(missing)} segment(s) the app router serves are NOT in the allowlist.",
            file=sys.stderr,
        )
        print("Each of these answers the static site's 404 instead of loading the app:", file=sys.stderr)
        for segment in missing:
            print(f"  /{segment}", file=sys.stderr)
            for route in sorted(wanted[segment]):
                print(f"      declared by {route}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "Add them to the @apparoute path_regexp alternation in the live Caddyfile, validate, "
            "reload, then re-extract the mirror with --write-mirror.",
            file=sys.stderr,
        )
        return 1

    print("")
    print("OK: every top-level segment the app router serves is carried by the allowlist.")
    if not args.caddyfile:
        print("This compared against the committed mirror, not the live host. The mirror can be")
        print("stale; --compare-mirror --caddyfile <live file> is what checks that.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
