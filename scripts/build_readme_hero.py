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
    return page.evaluate(
        """async (path) => {
          const token = sessionStorage.getItem('oe_access_token') || localStorage.getItem('oe_access_token');
          const r = await fetch('/api/v1/' + path, {headers: {Authorization: 'Bearer ' + token}});
          return r.ok ? await r.json() : null;
        }""",
        path,
    )


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
        for m in _items(_api(page, f"bim_hub/?{q}")):
            n = m.get("element_count") or 0
            if m.get("status") == "ready" and n > best["bim"][0]:
                best["bim"] = (n, m["id"])
    missing = [k for k, (_, v) in best.items() if v is None and k != "bim"]
    if missing:
        raise SystemExit(f"no demo record found for: {missing}")
    print("records", {k: v for k, v in best.items()})
    return {k: v for k, (_, v) in best.items()}


def _settle(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
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
        page.wait_for_selector("canvas", state="attached", timeout=150000)
        page.wait_for_function("() => !/Loading 3D geometry/i.test(document.body.innerText)", timeout=240000)
        page.wait_for_timeout(8000)
    else:
        page.wait_for_timeout(2500)
    body = page.inner_text("body").lower()
    if name == "dashboard":
        return
    for bad in ("drop your drawing", "no models", "not found", "loading 3d geometry"):
        if bad in body and name != "boq":
            raise SystemExit(f"{name}: page still shows '{bad}', refusing to save")
    if name == "boq" and "/boq/" not in page.url:
        raise SystemExit("boq: editor not opened")


def capture(base: str, theme: str) -> None:
    from playwright.sync_api import sync_playwright

    SRC.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
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
        page.goto(f"{base}/login")
        page.fill("input[type=email]", DEMO_USER)
        page.fill("input[type=password]", DEMO_PASSWORD)
        page.keyboard.press("Enter")
        page.wait_for_url(lambda u: "/login" not in u, timeout=60000)
        _settle(page)
        ids = _pick_records(page)
        routes = {
            "dashboard": "/",
            # takeoff and bim first: opening the BOQ switches the active project,
            # and those pages list only the active project's records.
            "takeoff": f"/dwg-takeoff?drawingId={ids['takeoff']}",
            "boq": f"/boq/{ids['boq']}",
        }
        for name, route in routes.items():
            page.goto(f"{base}{route}", wait_until="domcontentloaded", timeout=120000)
            _settle(page)
            _dismiss_dialogs(page)
            _wait_ready(page, name)
            _dismiss_dialogs(page)
            page.screenshot(path=str(SRC / f"{name}-{theme}.png"))
            print("captured", name, theme, page.url)
        browser.close()


def _data_uri(path: Path) -> str:
    kind = "svg+xml" if path.suffix == ".svg" else "png"
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()


def _html(theme: str) -> str:
    c = PALETTE[theme]
    mark = _data_uri(MARK / f"erp-mark-{theme}.svg")

    def shot(name: str) -> str:
        p = SRC / f"{name}-{theme}.png"
        if not p.exists():
            p = SRC / f"{name}-light.png"
        return _data_uri(p)

    stats = "".join(f"<li>{html.escape(s)}</li>" for s in STATS)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600;700&display=block" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:1920px;height:1080px;background:{c["bg"]};color:{c["ink"]};font-family:Onest,Inter,system-ui,sans-serif;
  overflow:hidden;position:relative;-webkit-font-smoothing:antialiased}}
.copy{{position:absolute;left:112px;top:150px;width:640px}}
.brand{{display:flex;align-items:center;gap:8px;font-size:21px;line-height:1;letter-spacing:-.005em}}
.brand img{{width:28px;height:28px}}
.brand b{{font-weight:600}}
h1{{margin-top:56px;font-size:76px;line-height:1.02;font-weight:600;letter-spacing:-.035em}}
h1 span{{color:#2987F8}}
p.lede{{margin-top:32px;font-size:26px;line-height:1.45;color:{c["muted"]};letter-spacing:-.005em;max-width:600px}}
ul{{list-style:none;display:flex;flex-wrap:wrap;gap:10px;margin-top:48px;max-width:620px}}
li{{font-size:18px;font-weight:500;padding:9px 16px;border-radius:999px;background:{c["chip"]};border:1px solid {c["line"]}}}
.win{{position:absolute;border-radius:18px;overflow:hidden;border:1px solid {c["line"]};background:{c["chip"]};
  box-shadow:0 1px 2px rgba(0,0,0,.06),0 24px 64px -16px rgba(16,24,40,.28)}}
.win img{{display:block;width:100%;height:auto}}
.w1{{left:800px;top:80px;width:1260px}}
.w2{{left:1330px;top:700px;width:620px}}
</style></head><body>
<div class="copy">
  <div class="brand"><img src="{mark}" alt=""><span>OpenConstruction<b>ERP</b></span></div>
  <h1>Estimate, plan and build <span>on open data.</span></h1>
  <p class="lede">BOQ, CAD and BIM takeoff, scheduling, 5D cost and tendering in one self-hosted platform.</p>
  <ul>{stats}</ul>
</div>
<div class="win w1"><img src="{shot("boq")}"></div>
<div class="win w2"><img src="{shot("takeoff")}"></div>
</body></html>"""


def render() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1.25)
            page.set_content(_html(theme), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            out = OUT / f"hero-{theme}.png"
            page.screenshot(path=str(out))
            print("wrote", out, out.stat().st_size // 1024, "KB")
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the README hero image.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--base", required=True)
    cap.add_argument("--theme", choices=("light", "dark", "both"), default="both")
    sub.add_parser("render")
    args = ap.parse_args()
    if args.cmd == "capture":
        for t in ("light", "dark") if args.theme == "both" else (args.theme,):
            capture(args.base.rstrip("/"), t)
    else:
        render()


if __name__ == "__main__":
    main()
