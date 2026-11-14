"""Build the README hero image from live app screenshots and the brand kit.

Two steps, run from the repo root:

    py -3 scripts/build_readme_hero.py capture --base http://127.0.0.1:5173
    py -3 scripts/build_readme_hero.py render

``capture`` signs in with the demo seed account and saves the source
screenshots to ``docs/screenshots/hero/src/``. ``render`` lays them out with
the ERP mark and writes ``docs/screenshots/hero-light.png`` and
``hero-dark.png``. Requires Playwright with Chromium.
"""

from __future__ import annotations

import argparse
import base64
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "screenshots" / "hero" / "src"
OUT = ROOT / "docs" / "screenshots"
MARK = ROOT / "frontend" / "public" / "brand" / "erp"

DEMO_USER = "demo@openconstructionerp.com"
DEMO_PASSWORD = "DemoPass1234!"  # public demo seed account, see README

PALETTE = {
    "light": {"bg": "#F0EEEB", "ink": "#181B1F", "muted": "#5B6068", "line": "rgba(24,27,31,.10)", "chip": "#FFFFFF"},
    "dark": {"bg": "#111316", "ink": "#F0EEEB", "muted": "#A3A7AD", "line": "rgba(240,238,235,.12)", "chip": "#1B1E22"},
}

STATS = ["190+ modules", "44 languages", "120,000+ cost items", "Self-hosted", "AGPL-3.0"]


def _api(page, path: str):
    """GET an API path from inside the logged-in page, using the app's own bearer token."""
    for attempt in range(5):
        try:
            return page.evaluate(
                """async (path) => {
                  const token = sessionStorage.getItem('oe_access_token') || localStorage.getItem('oe_access_token');
                  const r = await fetch('/api/v1/' + path, {headers: {Authorization: 'Bearer ' + token}});
                  return r.ok ? await r.json() : null;
                }""",
                path,
            )
        except Exception:  # the app may still be navigating after sign-in
            if attempt == 4:
                raise
            page.wait_for_timeout(3000)


def _items(data) -> list:
    return data if isinstance(data, list) else (data or {}).get("items", [])


def _pick_records(page) -> dict[str, str]:
    """Pick the richest demo records: most positions, a ready drawing, the largest ready model."""
    best = {
        "boq": (-1, None),
        "takeoff": (-1, None),
        "bim": (-1, None),
    }  # bim kept for ids only; headless WebGL never finishes parsing
    for proj in _items(_api(page, "projects/?limit=100")):
        q = f"project_id={proj['id']}"
        for b in _items(_api(page, f"boq/boqs/?{q}")):
            n = b.get("position_count") or 0
            if n > best["boq"][0]:
                best["boq"] = (n, b["id"])
        for d in _items(_api(page, f"dwg_takeoff/drawings/?{q}")):
            if d.get("status") == "ready" and best["takeoff"][1] is None:
                best["takeoff"] = (0, d["id"])
                best["takeoff_ctx"] = (0, [proj["id"], proj["name"]])
        for m in _items(_api(page, f"bim_hub/?{q}")):
            n = m.get("element_count") or 0
            if m.get("status") == "ready" and n > best["bim"][0]:
                best["bim"] = (n, m["id"])
    showcase = _showcase_project(page)
    if showcase:
        best["bim"] = (1, showcase["model"])
        best["project"] = (1, showcase["project"])
        best["project_name"] = (1, showcase["name"])
    best["boq_ctx"] = best.get("boq_ctx", (0, None))
    missing = [k for k, (_, v) in best.items() if v is None and k in ("boq", "takeoff")]
    if missing:
        raise SystemExit(f"no demo record found for: {missing}")
    print("records", {k: v for k, v in best.items()})
    return {k: v for k, (_, v) in best.items()}


def _showcase_project(page) -> dict | None:
    """The demo project with the largest ready BIM model that also has a schedule."""
    best = None
    for proj in _items(_api(page, "projects/?limit=100")):
        q = f"project_id={proj['id']}"
        if not _api(page, f"schedule/schedules/?{q}"):
            continue
        for m in _items(_api(page, f"bim_hub/?{q}")):
            n = m.get("element_count") or 0
            rank = n + (10**6 if "Residential House" in proj["name"] else 0)
            if m.get("status") == "ready" and (best is None or rank > best[0]):
                best = (rank, {"project": proj["id"], "name": proj["name"], "model": m["id"]})
    return best[1] if best else None


def _settle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=90000)
    except Exception:
        pass  # long-polling pages never go idle; readiness is checked per shot


def _dismiss_dialogs(page) -> None:
    for _ in range(3):
        btn = page.locator(
            "[role=dialog] button:has-text('Close'), [role=dialog] button:has-text('Skip'), "
            "[role=dialog] button:has-text('Got it'), [role=dialog] button[aria-label*='lose']"
        )
        if not btn.count():
            break
        try:
            btn.first.click(timeout=2000)
        except Exception:
            page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    page.keyboard.press("Escape")
    # info banners (tips, converter notices) eat the space the content needs
    for _ in range(6):
        x = page.locator("main button[aria-label*='ismiss' i], main button[aria-label='Collapse']")
        if not x.count():
            break
        try:
            x.first.click(timeout=1500)
        except Exception:
            break
        page.wait_for_timeout(300)


def _wait_ready(page, name: str) -> None:
    if name == "boq":
        page.wait_for_selector("[data-testid=boq-grid] [role=row], [data-testid=boq-grid] tr", timeout=60000)
        page.wait_for_function(
            "() => document.querySelectorAll('[data-testid=boq-grid] [role=row], [data-testid=boq-grid] tbody tr').length > 4",
            timeout=60000,
        )
        page.wait_for_timeout(2500)
    elif name == "takeoff":
        page.wait_for_function(
            "() => /LWPOLYLINE|A-ANNO/.test(document.body.innerText) && document.querySelector('canvas')",
            timeout=150000,
        )
        page.wait_for_timeout(8000)
    elif name == "bim":
        page.wait_for_selector("canvas", state="attached", timeout=300000)
        quiet = 0  # loading comes in phases: require 20 s without the loading text
        for _ in range(450):
            quiet = 0 if re.search("loading 3d geometry", page.inner_text("body"), re.I) else quiet + 1
            if quiet >= 10:
                break
            page.wait_for_timeout(2000)
        for label in ("Filtered summary", "Filter & Group"):  # clear the side panels for a clean model view
            try:
                page.locator(f"text={label}").first.locator("xpath=../..").locator("button").last.click(timeout=3000)
            except Exception:
                pass
        page.wait_for_timeout(6000)
    else:
        page.wait_for_function(
            "() => !document.querySelector('.animate-pulse, [class*=skeleton]') && !/^Loading/m.test(document.body.innerText)",
            timeout=180000,
        )
        page.wait_for_timeout(4000)
    body = page.inner_text("body").lower()
    if name == "dashboard":
        return
    for bad in (
        "drop your drawing",
        "no models",
        "not found",
        "loading 3d geometry",
        "could not load",
        "something went wrong",
    ):
        if bad in body and name != "boq":
            raise SystemExit(f"{name}: page still shows '{bad}', refusing to save")
    if name == "boq" and "/boq/" not in page.url:
        raise SystemExit("boq: editor not opened")


def capture(base: str, theme: str, only: set[str] | None = None) -> None:
    from playwright.sync_api import sync_playwright

    SRC.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
        )
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
            color_scheme="dark" if theme == "dark" else "light",
        )
        ctx.add_init_script(
            "try{localStorage.setItem('oe.tour_completed','1');"
            "localStorage.setItem('oe.tour_completed.auto_started','1');}catch(e){}"
        )
        page = ctx.new_page()
        page.goto(f"{base}/login", wait_until="commit", timeout=120000)
        page.wait_for_selector("input[type=email]", timeout=180000)
        page.fill("input[type=email]", DEMO_USER)
        page.fill("input[type=password]", DEMO_PASSWORD)
        page.keyboard.press("Enter")
        page.wait_for_url(lambda u: "/login" not in u, wait_until="commit", timeout=180000)
        page.wait_for_function(
            "() => sessionStorage.getItem('oe_access_token') || localStorage.getItem('oe_access_token')", timeout=120000
        )
        _settle(page)
        page.wait_for_timeout(3000)
        ids = _pick_records(page)
        # takeoff first: opening the BOQ switches the active project, and the
        # drawing list shows only the active project's records.
        scenes = {
            "takeoff": (f"/dwg-takeoff?drawingId={ids['takeoff']}", "takeoff"),
            "boq": (f"/boq/{ids['boq']}", None),
            "cde": ("/cde", "project"),
            "bim": (f"/bim/{ids['bim']}", "project"),
            "schedule": ("/schedule", "project"),
            "costs": ("/costs", "project"),
            "validation": ("/validation", "project"),
        }
        for name, (route, ctx_key) in scenes.items():
            if only and name not in only:
                continue
            ctx = {"project": [ids.get("project"), ids.get("project_name")], "takeoff": ids.get("takeoff_ctx")}.get(
                ctx_key
            )
            if ctx and ctx[0]:
                page.evaluate(
                    "([id, name]) => localStorage.setItem('oe_active_project', JSON.stringify({id, name, boqId: null}))",
                    ctx,
                )
            page.goto(f"{base}{route}", wait_until="commit", timeout=120000)
            _settle(page)
            _dismiss_dialogs(page)
            if name == "schedule":
                page.get_by_text("Programme").first.click()
                page.wait_for_timeout(1500)
                _settle(page)
            try:
                _wait_ready(page, name)
            except BaseException:
                page.screenshot(path=str(SRC / f"{name}-failed.png"))
                raise
            _dismiss_dialogs(page)
            page.evaluate(
                """() => document.querySelectorAll('button, div, a').forEach((el) => {
                  const st = getComputedStyle(el);
                  if (st.position === 'fixed' && /AI assistant/i.test(el.innerText || '') && el.innerText.length < 40) {
                    el.style.display = 'none';
                  }
                })"""
            )
            # the sidebar and top bar are the same on every shot: keep the content
            page.screenshot(
                path=str(SRC / f"{name}-{theme}.png"), clip={"x": 250, "y": 54, "width": 1350, "height": 946}
            )
            print("captured", name, theme, page.url)
        browser.close()


def _data_uri(path: Path) -> str:
    kind = "svg+xml" if path.suffix == ".svg" else "png"
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()


# (scene, caption, one-line proof, x, y, w, h, zoom, zoom origin) on a 1760 x 1180 canvas; h includes the caption bar
TILES = [
    ("bim", "BIM 3D takeoff", "Quantities straight from IFC and Revit models", 40, 212, 1000, 620, 1.08, (0.58, 0.52)),
    ("schedule", "4D schedule", "Gantt programme tied to the model", 1060, 212, 660, 300, 1.2, (0.0, 1.0)),
    ("cde", "Common data environment", "ISO 19650 containers and approvals", 1060, 532, 660, 300, 1.25, (0.0, 0.66)),
    ("boq", "BOQ editor", "Live totals, markups, GAEB and Excel", 40, 852, 405, 300, 1.9, (0.33, 0.5)),
    ("costs", "Cost databases", "Rates and resources for every region", 465, 852, 405, 300, 1.9, (0.5, 0.8)),
    ("takeoff", "DWG takeoff", "Measure on drawings, link to the BOQ", 890, 852, 405, 300, 1.5, (0.28, 0.62)),
    ("validation", "Validation", "Rule checks before anything is issued", 1315, 852, 405, 300, 2.2, (0.1, 0.27)),
]
CAPTION_H = 62


SHOT_AR = 1350 / 946  # captured clip, width over height


def _place(w: int, h: int, zoom: float, focus: tuple[float, float]) -> str:
    """Absolute placement of a shot so that ``focus`` (fractions of the shot) is centred, clamped to the box."""
    width = w * zoom
    height = width / SHOT_AR
    left = min(0.0, max(w - width, w / 2 - focus[0] * width))
    top = min(0.0, max(h - height, h / 2 - focus[1] * height))
    return f"position:absolute;left:{left:.1f}px;top:{top:.1f}px;width:{width:.1f}px;height:auto"


def _html(theme: str) -> str:
    c = PALETTE[theme]
    mark = _data_uri(MARK / f"erp-mark-{theme}.svg")

    def shot(name: str) -> str:
        p = SRC / f"{name}-{theme}.png"
        if not p.exists():
            p = SRC / f"{name}-light.png"
        return _data_uri(p)

    stats = "".join(f"<li>{html.escape(s)}</li>" for s in STATS)
    tiles = "".join(
        f'<figure class="tile" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
        f'<div class="shot" style="height:{h - CAPTION_H}px"><img src="{shot(n)}" style="{_place(w, h - CAPTION_H, z, focus)}"></div>'
        f"<figcaption><b>{html.escape(cap)}</b><span>{html.escape(sub)}</span></figcaption></figure>"
        for n, cap, sub, x, y, w, h, z, focus in TILES
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600;700&display=block" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:1760px;height:1192px;background:{c["bg"]};color:{c["ink"]};font-family:Onest,Inter,system-ui,sans-serif;
  overflow:hidden;position:relative;-webkit-font-smoothing:antialiased}}
.brand{{position:absolute;left:40px;top:34px;display:flex;align-items:center;gap:8px;font-size:19px;line-height:1}}
.brand img{{width:26px;height:26px}}
.brand b{{font-weight:600}}
h1{{position:absolute;left:40px;top:80px;font-size:60px;line-height:1.05;font-weight:600;letter-spacing:-.035em;white-space:nowrap}}
h1 span{{color:#2987F8}}
p.lede{{position:absolute;left:42px;top:152px;font-size:22px;color:{c["muted"]};letter-spacing:-.005em;white-space:nowrap}}
ul{{list-style:none;position:absolute;right:40px;top:92px;width:640px;display:flex;flex-wrap:wrap;gap:10px;justify-content:flex-end}}
li{{font-size:17px;font-weight:500;padding:8px 15px;border-radius:999px;background:{c["chip"]};border:1px solid {c["line"]}}}
.tile{{position:absolute;border-radius:16px;overflow:hidden;border:1px solid {c["line"]};background:{c["chip"]};
  box-shadow:0 1px 2px rgba(0,0,0,.06),0 18px 44px -18px rgba(16,24,40,.30)}}
.shot{{position:relative;overflow:hidden;border-bottom:1px solid {c["line"]}}}

figcaption{{height:{CAPTION_H}px;padding:0 18px;display:flex;flex-direction:column;justify-content:center;gap:2px}}
figcaption b{{font-size:19px;font-weight:600;letter-spacing:-.01em}}
figcaption span{{font-size:14.5px;color:{c["muted"]};white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
</style></head><body>
<div class="brand"><img src="{mark}" alt=""><span>OpenConstruction<b>ERP</b></span></div>
<h1>Estimate, plan and build <span>on open data.</span></h1>
<p class="lede">BOQ, BIM and CAD takeoff, 4D scheduling, 5D cost and tendering in one self-hosted platform.</p>
<ul>{stats}</ul>
{tiles}
</body></html>"""


def _shrink(path: Path) -> None:
    """Lossless re-encode with maximum zlib effort; the collage stays pixel-identical."""
    from PIL import Image

    Image.open(path).convert("RGB").save(path, optimize=True, compress_level=9)


def render() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1760, "height": 1192}, device_scale_factor=1)
            page.set_content(_html(theme), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            out = OUT / f"hero-{theme}.png"
            page.screenshot(path=str(out))
            _shrink(out)
            print("wrote", out, out.stat().st_size // 1024, "KB")
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the README hero image.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--base", required=True)
    cap.add_argument("--theme", choices=("light", "dark", "both"), default="both")
    cap.add_argument("--only", help="comma-separated scene names to re-capture")
    sub.add_parser("render")
    args = ap.parse_args()
    if args.cmd == "capture":
        for t in ("light", "dark") if args.theme == "both" else (args.theme,):
            capture(args.base.rstrip("/"), t, set(args.only.split(",")) if args.only else None)
    else:
        render()


if __name__ == "__main__":
    main()
