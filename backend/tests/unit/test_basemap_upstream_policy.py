# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Policy gate for every third-party host the basemap proxy talks to.

WHY THIS EXISTS. The basemap upstream was a keyless CARTO raster. It stopped
being keyless with no release, no notice and no failing check: it kept
answering 200, with the right number of bytes, with a decodable PNG of the
correct geography, and printed "API KEY REQUIRED" across the picture. Every
check we had asked the transport whether we were answered. None asked whether
we were answered with what we requested. The founder found it by looking at
the screen.

WHY THIS GATE IS NOT A PROBE. The obvious reaction is to fetch a tile in CI
and assert something about it. That is the wrong gate twice over. A live fetch
makes the build depend on somebody else's uptime, so it goes flaky, and a
flaky gate gets muted. Worse, the failure mode above is invisible to every
assertion a probe can cheaply make: status, length and decode were all green
on the watermarked tile. Only a human looking at pixels caught it.

So this gate asserts the thing that was actually decidable in advance and
never written down: WHICH HOSTS ARE WE ALLOWED TO PROXY, AND WHY. Each entry
below carries its licence and its usage policy in prose. Adding a host means
writing that paragraph, which is the review step that would have caught the
change of terms, because it forces somebody to go read them.

WHAT IT ASSERTS.
  1. Every external URL in the router points at an allowlisted host. Scanned
     out of the source rather than read off the imported constants, so a new
     constant added later is caught too. A test that reads the four names it
     already knows about cannot notice a fifth.
  2. No upstream URL carries an API key, token or access parameter. A keyless
     service that starts needing credentials must fail loudly here rather
     than quietly in the pixels.
  3. The hosts we deliberately refuse stay refused, with the reason recorded.
  4. The vendored MapLibre styles contain no external URL at all. A style JSON
     names the URLs the browser goes on to fetch: the vector source, the
     relief raster, the glyph template and the sprite base. If any one keeps
     its upstream host, the browser talks to that host directly and the map
     still renders, so the leak is invisible on screen.

Run: pytest backend/tests/unit/test_basemap_upstream_policy.py
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

_GEO_HUB = Path(__file__).resolve().parents[2] / "app" / "modules" / "geo_hub"
_ROUTER = _GEO_HUB / "router.py"
_STYLE_DIR = _GEO_HUB / "data" / "basemap_styles"

# A URL literal. Applied to STRING VALUES pulled out of the AST, never to
# raw source: comments and docstrings name the hosts we refuse in order to
# explain why we refuse them, and a scan that cannot tell an explanation
# from an instruction reads its own reasoning as the violation.
_URL_RE = re.compile(r"https://[^\s\"'`)\]}>,\\]+")
_HOST_RE = re.compile(r"https://([^/\s\"']+)")

# Query parameters that mean "this service is no longer keyless".
_CREDENTIAL_PARAMS = ("apikey", "api_key", "access_token", "access-token", "key=", "token=")


# ── The allowlist. Each entry must say what the licence is and what the
# usage policy says about proxying, because proxying is what we do. ──────
ALLOWED_UPSTREAMS: dict[str, str] = {
    "tiles.openfreemap.org": (
        "OpenFreeMap. Serves OpenStreetMap data as vector tiles under ODbL, "
        "plus public-domain Natural Earth relief rasters and the glyph and "
        "sprite assets the MapLibre styles need. Keyless and quota-free by "
        "stated policy, commercial use permitted, and no clause against "
        "proxying or caching. Decisive property: the whole stack is "
        "self-hostable, so an operator who outgrows the public endpoint "
        "repoints one constant rather than shopping for a new vendor. That "
        "is the property CARTO turned out not to have."
    ),
    "openconstructionerp.com": (
        "Our own project URL, sent as the User-Agent contact so an upstream "
        "operator can reach us before blocking us. Not a tile source."
    ),
    "www.openstreetmap.org": (
        "The ODbL copyright page, linked as attribution. A credit link, never fetched by the server."
    ),
    "openmaptiles.org": ("The tile schema, linked as attribution. A credit link, never fetched by the server."),
    "openfreemap.org": (
        "The tile provider's home page, linked as attribution. A credit link, never fetched by the server."
    ),
    "www.naturalearthdata.com": (
        "Natural Earth, public domain, linked as a courtesy credit for the "
        "relief imagery. A credit link, never fetched by the server."
    ),
}

# ── Hosts we refuse on purpose. Recorded so nobody re-adds one after
# measuring that it happens to answer today. ─────────────────────────────
REFUSED_UPSTREAMS: dict[str, str] = {
    "tile.openstreetmap.org": (
        "The OSMF Tile Usage Policy (operations.osmfoundation.org/policies/tiles) "
        "says 'We generally do not recommend putting your own caching proxy in "
        "front of tile.openstreetmap.org', warns that for commercial services "
        "'access may be withdrawn at any point', forbids prefetch and offline "
        "use, and blocks by User-Agent without notice. That these tiles answer "
        "200 today is not permission; measuring the response answers a "
        "different question than reading the terms."
    ),
    "basemaps.cartocdn.com": (
        "The upstream this whole change exists to remove. It now requires "
        "an API key and signals that by watermarking the image rather than "
        "by returning an error status. Its licence file states the hosted "
        "tiles are 'restricted to CARTO enterprise customers and Non-Profit "
        "GRANTS only and is not available for free public use'."
    ),
    "api.mapbox.com": "Requires an access token and bills per request.",
    "tiles.stadiamaps.com": "Requires an API key for non-local origins.",
    "server.arcgisonline.com": ("Terms restrict redistribution and proxying; not an open licence."),
}


def _router_source() -> str:
    return _ROUTER.read_text(encoding="utf-8")


def _router_string_literals() -> list[str]:
    """Every string the router evaluates, with docstrings left out.

    Comments never reach the AST, and docstrings are dropped explicitly, so
    what comes back is the text the module actually uses: URL templates,
    header values, f-string fragments. This is the difference between "the
    file mentions a host" and "the file fetches from a host".
    """
    tree = ast.parse(_router_source())
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def _style_fetch_urls(style_path: Path) -> list[tuple[str, str]]:
    """Every URL a style tells the browser to FETCH, as (json path, url).

    ``attribution`` is deliberately excluded and only ``attribution``. Those
    are credit links: the browser renders them as anchors and never requests
    them, and a licence link is supposed to point at the licensor. Every
    other string in the document is a fetch instruction.
    """
    out: list[tuple[str, str]] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "attribution":
                    continue
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            for url in _URL_RE.findall(node):
                out.append((path, url))

    walk(json.loads(style_path.read_text(encoding="utf-8")), "$")
    return out


def _style_files() -> list[Path]:
    return sorted(_STYLE_DIR.glob("*.json"))


def test_the_gate_reads_the_files_it_claims_to_check() -> None:
    """A gate whose inputs vanished would otherwise pass vacuously."""
    source = _router_source()
    assert len(source) > 10_000, "router.py is suspiciously small; path is probably wrong"
    literals = _router_string_literals()
    assert literals, "parsed no string literals, so the scan below proves nothing"
    assert any(_URL_RE.search(text) for text in literals), (
        "found no URL in any evaluated string. Either the upstreams moved out "
        "of this module or the AST walk is broken; both make this gate vacuous."
    )
    styles = _style_files()
    assert styles, f"no vendored styles under {_STYLE_DIR}"
    for path in styles:
        assert path.stat().st_size > 1_000, f"{path.name} is too small to be a real style"


def test_every_upstream_host_is_on_the_allowlist() -> None:
    """No URL may point somewhere whose terms nobody has written down."""
    found: dict[str, list[str]] = {}
    for text in _router_string_literals():
        for url in _URL_RE.findall(text):
            match = _HOST_RE.match(url)
            assert match, url
            found.setdefault(match.group(1), []).append(url)

    unknown = {host: urls for host, urls in found.items() if host not in ALLOWED_UPSTREAMS}
    assert not unknown, (
        "router.py names hosts that are not on the basemap allowlist: "
        f"{sorted(unknown)}. Add each to ALLOWED_UPSTREAMS together with its "
        "licence and what its usage policy says about proxying, or remove it. "
        "The paragraph is the point: writing it is the step that catches a "
        "service which has quietly stopped being keyless."
    )


def test_no_upstream_url_carries_a_credential() -> None:
    """A keyless service that starts wanting a key must fail here, loudly."""
    offenders = [
        url
        for text in _router_string_literals()
        for url in _URL_RE.findall(text)
        if any(param in url.lower() for param in _CREDENTIAL_PARAMS)
    ]
    assert not offenders, (
        f"basemap URLs carry what looks like a credential: {offenders}. The "
        "basemap must stay keyless: these routes are public because an <img> "
        "tag and a tile loader cannot attach an auth header."
    )


@pytest.mark.parametrize(("host", "reason"), sorted(REFUSED_UPSTREAMS.items()))
def test_refused_hosts_stay_refused(host: str, reason: str) -> None:
    """Each refusal keeps its recorded reason and stays out of the source."""
    assert reason.strip(), f"{host} is refused with no reason recorded"
    assert host not in ALLOWED_UPSTREAMS, f"{host} is on both lists"
    fetched = [url for text in _router_string_literals() for url in _URL_RE.findall(text)]
    offenders = [url for url in fetched if host in url]
    assert not offenders, f"router.py fetches from {host}, which we refuse: {reason}"


@pytest.mark.parametrize("style_path", _style_files(), ids=lambda p: p.name)
def test_vendored_styles_are_same_origin_throughout(style_path: Path) -> None:
    """Every URL a style hands the browser must point back at our own origin."""
    external = _style_fetch_urls(style_path)
    assert not external, (
        f"{style_path.name} still hands the browser external URLs: {external}. "
        "The browser must reach tiles, glyphs and sprites through our own "
        "backend only: public tile hosts are blocked by name by ad and privacy "
        "blockers, which leaves the map a blank square, and a style that "
        "half-leaks still renders, so the regression is invisible."
    )

    # Every URL-bearing field must actually be present and same-origin, not
    # merely free of external hosts. An absent field leaks nothing and would
    # sail past the assertion above.
    style = json.loads(style_path.read_text(encoding="utf-8"))
    assert str(style.get("glyphs", "")).startswith("/api/"), "glyphs URL is not same-origin"
    assert str(style.get("sprite", "")).startswith("/api/"), "sprite URL is not same-origin"
    sources = style.get("sources") or {}
    assert sources, f"{style_path.name} declares no sources"
    for name, source in sources.items():
        urls = list(source.get("tiles") or [])
        if "url" in source:
            urls.append(source["url"])
        assert urls, f"source {name!r} in {style_path.name} declares no URL"
        for url in urls:
            assert url.startswith("/api/"), f"source {name!r} points at {url}"


def test_serving_a_style_rewrites_every_url_to_the_calling_origin() -> None:
    """The vendored file is host independent. The served response must not be.

    MapLibre fetches vector tiles, glyphs and sprites from a Web Worker, and a
    worker has no document base, so a root relative URL cannot resolve there.
    The relief raster loaded anyway because images are fetched on the main
    thread. Every response was 200, no request failed because none was made,
    and the map was a white rectangle.

    The same-origin assertion above passes on that broken state, because the
    file on disk was always correct. What was wrong was serving it unmodified.
    So this asserts on the rewrite itself, which is a pure function of the text
    and the origin and needs no server.
    """
    from app.modules.geo_hub.router import absolutise_style

    origin = "https://erp.example.org"
    for style_path in _style_files():
        served = absolutise_style(style_path.read_text(encoding="utf-8"), origin).decode("utf-8")
        assert '"/api/' not in served, (
            f"{style_path.name} still carries a root relative URL after rewriting. "
            "A Web Worker cannot resolve it and the map renders blank while "
            "every HTTP response stays green."
        )

        style = json.loads(served)
        urls = [str(style.get("glyphs", "")), str(style.get("sprite", ""))]
        for source in (style.get("sources") or {}).values():
            urls.extend(source.get("tiles") or [])
            if "url" in source:
                urls.append(source["url"])
        # glyphs, sprite and the vector source. The relief raster that used to
        # make a fourth was removed on purpose, see the test below.
        assert len(urls) >= 3, f"{style_path.name} yielded {len(urls)} URLs, too few to prove anything"
        for url in urls:
            assert url.startswith(f"{origin}/api/"), (
                f"{style_path.name} serves {url!r}, which is neither absolute nor ours"
            )


def test_the_street_styles_ship_and_include_a_dark_one() -> None:
    """Light, minimal and dark street styles are all vendored and allowlisted."""
    from app.modules.geo_hub.router import _STYLE_NAMES

    names = {path.stem for path in _style_files()}
    assert {"liberty", "positron", "dark"} <= names
    assert names == set(_STYLE_NAMES), (
        f"vendored files {sorted(names)} and the served allowlist {sorted(_STYLE_NAMES)} disagree; "
        "a file nobody can request is dead weight, a name with no file is a 404 map"
    )


@pytest.mark.parametrize("style_path", _style_files(), ids=lambda p: p.name)
def test_vendored_styles_draw_streets_not_relief(style_path: Path) -> None:
    """No raster or hillshade layer may sit under the street cartography.

    Upstream liberty blends Natural Earth shaded relief at 60 % opacity from
    zoom 0 to 7. Zoomed out to fit a few projects, that relief was most of the
    picture and the founder reported the maps as terrain maps. The vendor
    script now strips it; this keeps a refresh from bringing it back.
    """
    style = json.loads(style_path.read_text(encoding="utf-8"))
    kinds = {source.get("type") for source in (style.get("sources") or {}).values()}
    assert kinds == {"vector"}, f"{style_path.name} declares non-vector sources: {kinds}"
    offenders = [layer["id"] for layer in style["layers"] if layer.get("type") in {"raster", "hillshade"}]
    assert not offenders, f"{style_path.name} still draws relief layers: {offenders}"
    street_names = [
        layer["id"]
        for layer in style["layers"]
        if layer.get("source-layer") == "transportation_name" and "text-field" in (layer.get("layout") or {})
    ]
    assert street_names, f"{style_path.name} has no labelled street layer, so it would not show street names"


def test_the_upstream_can_be_pointed_at_a_self_hosted_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """``OE_BASEMAP_UPSTREAM`` repoints every proxied fetch; junk falls back."""
    from app.modules.geo_hub import router

    class _Settings:
        basemap_upstream = "https://tiles.example.internal/"

    monkeypatch.setattr(router, "get_settings", lambda: _Settings())
    assert router._basemap_upstream() == "https://tiles.example.internal"

    _Settings.basemap_upstream = ""
    assert router._basemap_upstream() == router._BASEMAP_UPSTREAM

    _Settings.basemap_upstream = "file:///etc/passwd"
    assert router._basemap_upstream() == router._BASEMAP_UPSTREAM
