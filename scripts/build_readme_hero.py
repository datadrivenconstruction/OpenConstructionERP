"""Build the README hero image from live app screenshots and the brand kit.

Two steps, run from the repo root:

    py -3 scripts/build_readme_hero.py capture --base http://127.0.0.1:5173
    py -3 scripts/build_readme_hero.py render

``capture`` signs in with the demo seed account (the public demo can be captured
with ``scripts/readme_hero_capture.cjs`` instead, which uses its own "Try demo" flow) and saves the source
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

STATS = ["240+ modules", "44 languages", "120,000+ cost items", "Self-hosted", "AGPL-3.0"]


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
        page.wait_for_selector("[data-testid=boq-grid] [role=row], [data-testid=boq-grid] tr, .ag-row", timeout=240000)
        page.wait_for_function(
            "() => document.querySelectorAll('[data-testid=boq-grid] [role=row], [data-testid=boq-grid] tbody tr, .ag-row').length > 4",
            timeout=240000,
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
    elif name == "costs":
        page.get_by_placeholder(re.compile("Search by description", re.I)).fill("cable")
        page.wait_for_selector("text=/NYM-J/", timeout=120000)
        page.wait_for_timeout(2000)
        try:  # open the first result to show its resources
            page.get_by_text(re.compile(r"NYM-J 3.1\.5")).first.locator("xpath=preceding-sibling::*[1]").click(
                timeout=4000
            )
            page.wait_for_timeout(3000)
        except Exception:
            pass
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


def _box(page, locator):
    box = locator.first.bounding_box()
    if not box:
        raise SystemExit("scene anchor not found")
    return box


def _shoot(page, name: str, theme: str) -> None:
    """Save the scene, cropped to the part that reads well at README width."""
    out = str(SRC / f"{name}-{theme}.png")
    vw = page.viewport_size["width"]
    if name == "bim":
        # three times the pixel density, tight on the building; G hides the ground grid
        cdp = page.context.new_cdp_session(page)
        cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": vw, "height": page.viewport_size["height"], "deviceScaleFactor": 3, "mobile": False},
        )
        page.wait_for_timeout(4000)
        clip = {"x": 774, "y": 466, "width": 460, "height": 247}
        page.screenshot(path=str(SRC / f"bim-grid-{theme}.png"), clip=clip)
        page.keyboard.press("g")
        page.wait_for_timeout(2500)
        page.screenshot(path=out, clip=clip)
        cdp.send("Emulation.clearDeviceMetricsOverride")
        return
    if name == "boq":
        box = _box(page, page.locator("[data-testid=boq-grid]"))
        width = min(box["width"], vw - box["x"] - 4)
        clip = {"x": box["x"], "y": box["y"], "width": width, "height": width / 2.9}
    elif name == "costs":
        box = _box(page, page.get_by_placeholder(re.compile("Search by description", re.I)))
        width = min(1100, vw - box["x"] - 4)
        clip = {"x": box["x"] - 4, "y": box["y"] - 8, "width": width, "height": width / 3.1}
    elif name == "schedule":
        page.get_by_text("APRIL 2026").first.evaluate("(e) => e.scrollIntoView({block: 'start'})")
        page.wait_for_timeout(800)
        box = _box(page, page.get_by_text("APRIL 2026"))
        width = vw - box["x"] - 14
        clip = {"x": box["x"] - 8, "y": max(0, box["y"] - 8), "width": width, "height": width / 3.0}
    else:  # takeoff: the drawing canvas without the layers panel
        clip = {"x": 250, "y": 400, "width": 990, "height": 324}
    page.screenshot(path=out, clip=clip)


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
            "bim": (f"/bim/{ids['bim']}", "project"),
            "schedule": ("/schedule", "project"),
            "costs": ("/costs", "project"),
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
            if name == "boq":  # a narrower window makes the columns, and so the rows, read larger
                page.set_viewport_size({"width": 1300, "height": 900})
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
            _shoot(page, name, theme)
            if name == "boq":
                page.set_viewport_size({"width": 1600, "height": 1000})
            print("captured", name, theme, page.url)
        browser.close()


def _data_uri(path: Path) -> str:
    kind = "svg+xml" if path.suffix == ".svg" else "png"
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()


# (scene, caption, one-line proof, x, y, w, h); h includes the caption bar. Shots are cropped at capture time.
TILES = [
    ("bim", "BIM 3D takeoff", "Quantities straight from IFC and Revit models", 40, 212, 1060, 950),
    ("schedule", "4D schedule", "Gantt programme linked to the model", 1120, 212, 600, 303),
    ("boq", "BOQ editor", "Live totals, markups, GAEB and Excel export", 1120, 535, 600, 303),
    ("takeoff", "DWG takeoff", "Measure on drawings, link to the BOQ", 1120, 858, 600, 304),
]
CAPTION_H = 62


def _place(src: Path, w: int, h: int) -> str:
    """Cover the box with the shot, anchored top left, trimming the overflow."""
    from PIL import Image

    iw, ih = Image.open(src).size
    scale = max(w / iw, h / ih)
    return f"position:absolute;left:0;top:0;width:{iw * scale:.1f}px;height:{ih * scale:.1f}px"


def _html(theme: str) -> str:
    c = PALETTE[theme]
    mark = _data_uri(MARK / f"erp-mark-{theme}.svg")

    def shot_path(name: str) -> Path:
        p = SRC / f"{name}-{theme}.png"
        return p if p.exists() else SRC / f"{name}-light.png"

    stats = "".join(f"<li>{html.escape(s)}</li>" for s in STATS)
    tiles = "".join(
        f'<figure class="tile" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
        f'<div class="shot" style="height:{h - CAPTION_H}px"><img src="{_data_uri(shot_path(n))}" style="{_place(shot_path(n), w, h - CAPTION_H)}"></div>'
        f"<figcaption><b>{html.escape(cap)}</b><span>{html.escape(sub)}</span></figcaption></figure>"
        for n, cap, sub, x, y, w, h in TILES
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
