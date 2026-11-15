// Captures the README hero source shots from the public demo through its own "Try demo" flow.
// Usage: NODE_PATH=<dir with playwright> node scripts/readme_hero_capture.cjs [scenes] [outDir]
// scenes: comma list of bim,schedule,boq,takeoff (default all); outDir default docs/screenshots/hero/src.
// Then: py -3 scripts/build_readme_hero.py render
const { chromium } = require('playwright');
const BASE = 'https://openconstructionerp.com/demo';
const PID = 'f1a95000-0001-4a00-8b00-000000000001', PNAME = 'Residential House - Reference Build', MID = 'f1a95000-0003-4a00-8b00-000000000003';
const ONLY = (process.argv[2] || 'bim,schedule,boq,takeoff').split(',');
const OUT = process.argv[3] || 'docs/screenshots/hero/src';
require('fs').mkdirSync(OUT, { recursive: true });
const clean = (p) => p.evaluate(() => {
  for (const e of document.querySelectorAll('body *')) { const cs = getComputedStyle(e); if (cs.position !== 'fixed') continue; const r = e.getBoundingClientRect(); if (r.left > innerWidth * 0.5 && r.top > innerHeight * 0.55 && r.width < 320 && r.height < 120) e.style.display = 'none'; }
  for (const e of document.querySelectorAll('div,aside,section')) { const t = (e.innerText || '').trim(); if (t.startsWith('Filtered summary') && t.length < 1500) { let a = e; while (a && a !== document.body) { const pos = getComputedStyle(a).position; if (pos === 'fixed' || pos === 'absolute') { a.style.display = 'none'; break; } a = a.parentElement; } } }
  document.querySelectorAll('[data-testid=demo-read-only-dialog]').forEach(e => e.remove());
  for (const e of document.querySelectorAll('div.fixed')) if (/This is a public demo/.test(e.innerText || '')) e.remove();
  for (const e of document.querySelectorAll('button')) if (/^AI assistant$/.test((e.innerText || '').trim())) e.style.display = 'none';
  for (const e of document.querySelectorAll('[class*=toast], [role=status], [role=alert]')) e.style.display = 'none';
});
const api = (p, path) => p.evaluate(async (path) => { const t = sessionStorage.getItem('oe_access_token') || localStorage.getItem('oe_access_token'); const r = await fetch('/demo/api/v1/' + path, { headers: { Authorization: 'Bearer ' + t } }); return r.ok ? await r.json() : null; }, path);
const items = (d) => Array.isArray(d) ? d : ((d || {}).items || []);
let PARK = { x: 2, y: 2 };
const both = async (p, name, clipFn) => {
  for (const th of ['light', 'dark']) {
    await p.emulateMedia({ colorScheme: th }); await p.waitForTimeout(2500); await clean(p);
    await p.mouse.move(PARK.x, PARK.y, { steps: 5 }); await p.waitForTimeout(1200); await clean(p);
    await p.screenshot({ path: `${OUT}/${name}-${th}.png`, clip: await clipFn() });
  }
  console.log('shot', name);
};
(async () => {
  const b = await chromium.launch({ channel: 'chrome', args: ['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 1700, height: 1450 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(() => { try { localStorage.setItem('oe.tour_completed','1'); localStorage.setItem('oe.tour_completed.auto_started','1'); } catch(e){} });
  const p = await ctx.newPage(); p.setDefaultTimeout(240000);
  await p.goto(BASE + '/login', { waitUntil: 'commit', timeout: 240000 });
  await p.getByText('Try demo (no signup)').waitFor();
  if (!(await p.locator('button', { hasText: 'demo@openconstructionerp.com' }).count())) await p.getByText('Try demo (no signup)').click();
  await p.locator('button', { hasText: 'demo@openconstructionerp.com' }).first().click();
  await p.waitForFunction(() => sessionStorage.getItem('oe_access_token') || localStorage.getItem('oe_access_token'));
  await p.waitForTimeout(5000);
  { await clean(p); const ok = p.getByText('I understand, continue'); try { await ok.waitFor({ timeout: 6000 }); await ok.click({ force: true }); } catch (e) {}
    const open = p.getByRole('button', { name: /Open this demo/i }).first();
    try { await open.waitFor({ timeout: 20000 }); await open.click(); await p.waitForTimeout(8000); await clean(p); console.log('opened demo', p.url()); } catch (e) { console.log('no chooser', p.url()); } }
  const setProj = (id, name) => p.evaluate(([id, name]) => localStorage.setItem('oe_active_project', JSON.stringify({ id, name, boqId: null })), [id, name]);
  const go = async (route) => { await p.goto(BASE + route, { waitUntil: 'commit', timeout: 240000 }); try { await p.waitForLoadState('networkidle', { timeout: 60000 }); } catch (e) {} await p.waitForTimeout(3000); await clean(p); };
  let boq = null, draw = null;
  if (ONLY.includes('boq')) {
    let bestN = -1;
    for (const pr of items(await api(p, 'projects/?limit=100'))) {
      const q = 'project_id=' + pr.id;
      if (ONLY.includes('boq')) for (const x of items(await api(p, 'boq/boqs/?' + q))) { const n = x.position_count || 0; if (n > bestN) { bestN = n; boq = { id: x.id, pid: pr.id, name: pr.name }; } }
      if (ONLY.includes('takeoff') && !draw) for (const d of items(await api(p, 'dwg_takeoff/drawings/?' + q))) if (d.status === 'ready' && !draw) draw = { id: d.id, pid: pr.id, name: pr.name };
    }
    console.log('boq', JSON.stringify(boq), bestN, 'draw', JSON.stringify(draw));
  }
  if (ONLY.includes('bim')) {
    PARK = { x: 2, y: 2 };
    await setProj(PID, PNAME);
    await p.goto(`${BASE}/bim/${MID}`, { waitUntil: 'commit', timeout: 240000 });
    await p.waitForSelector('canvas', { state: 'attached' });
    let quiet = 0;
    for (let i = 0; i < 300 && quiet < 10; i++) { quiet = /loading 3d geometry/i.test(await p.innerText('body')) ? 0 : quiet + 1; await p.waitForTimeout(2000); }
    await p.waitForTimeout(5000); await clean(p);
    const box = await p.locator('canvas').first().boundingBox();
    await p.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
    for (let i = 0; i < 3; i++) { await p.mouse.wheel(0, -300); await p.waitForTimeout(400); }
    PARK = { x: 120, y: box.y + 300 };
    await p.waitForTimeout(3000);
    await both(p, 'bim', async () => ({ x: box.x + box.width * 0.58 - 450, y: box.y, width: 900, height: 754 }));
  }
  if (ONLY.includes('schedule')) {
    const sp = { id: 'bbaaf971-8c03-4289-ae78-c7734a35ae3a', name: 'Wohnanlage Berlin-Mitte' };
    await setProj(sp.id, sp.name); await go('/schedule');
    try { await p.getByText(/^Programme/).first().click({ timeout: 20000 }); await p.waitForTimeout(8000); await clean(p); } catch (e) { console.log('no programme row'); }
    const ACT = p.getByText(/^ACTIVITY$/i).first(); await ACT.waitFor({ timeout: 90000 });
    await ACT.evaluate((e) => e.scrollIntoView({ block: 'center' })); await p.waitForTimeout(1500);
    await both(p, 'schedule', async () => { const bx = await ACT.boundingBox(); return { x: bx.x - 18, y: bx.y - 16, width: 720, height: 289 }; });
  }
  if (ONLY.includes('boq') && boq) {
    await p.setViewportSize({ width: 1150, height: 900 });
    await setProj(boq.pid, boq.name); await go('/boq/' + boq.id);
    await p.waitForSelector('[data-testid=boq-grid]', { timeout: 240000 }); await p.waitForTimeout(4000); await clean(p);
    await both(p, 'boq', async () => { const g = await p.locator('[data-testid=boq-grid]').boundingBox(); const h = await p.getByText(/^Pos\.$/).first().boundingBox(); const w = Math.min(g.width, 760); return { x: g.x, y: h.y - 16, width: w, height: w / 2.49 }; });
    await p.setViewportSize({ width: 1700, height: 1450 });
  }
  if (ONLY.includes('takeoff')) {
    draw = { id: 'f1a95000-0004-4a00-8b00-000000000004', pid: PID, name: PNAME };
    await setProj(draw.pid, draw.name); await go('/dwg-takeoff?drawingId=' + draw.id);
    await p.waitForFunction(() => /LWPOLYLINE|A-ANNO/.test(document.body.innerText) && document.querySelector('canvas'), null, { timeout: 150000 });
    await p.waitForTimeout(8000); await clean(p);
    await both(p, 'takeoff', async () => ({ x: 285, y: 495, width: 1000, height: 402 }));
  }
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
