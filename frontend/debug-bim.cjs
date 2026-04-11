/**
 * Headless deep test of /bim filter UX.
 *
 * Verifies:
 *  - Scene loads with mesh count > 0
 *  - Storey filter chips show parsed level numbers (not raw "01 - …")
 *  - "Buildings only" toggle hides annotation noise
 *  - Bucket sections expand/collapse
 *  - Click on a storey chip → mesh visibility drops
 *  - Click on a type chip inside a bucket → mesh visibility changes
 *  - Clear all → mesh visibility restored to full
 *  - FPS measurement
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const FRONTEND = 'http://localhost:5173';
const BACKEND = 'http://localhost:8000';
const EMAIL = 'demo@openestimator.io';
const PASSWORD = 'DemoPass1234!';
const PROJECT_ID = '8f49f039-a69e-43a2-97d3-4bba0f99759b';

const OUT = path.join(__dirname, 'debug-bim');
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });
const log = (...a) => console.log('[debug]', ...a);

/* ── helpers ─────────────────────────────────────────────────────────── */

/** Walk React fibers from the canvas to find the SceneManager ref. */
async function readScene(page) {
  return page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return { error: 'no canvas' };
    const fiberKey = Object.keys(canvas).find((k) => k.startsWith('__reactFiber'));
    if (!fiberKey) return { error: 'no fiber' };
    let fiber = canvas[fiberKey];
    let depth = 0;
    while (fiber && depth < 30) {
      if (fiber.memoizedState) {
        let hook = fiber.memoizedState;
        let hookIdx = 0;
        while (hook && hookIdx < 20) {
          const ms = hook.memoizedState;
          if (ms && ms.current && ms.current.scene) {
            const sm = ms.current;
            let mc = 0;
            let vmc = 0;
            sm.scene.traverse((o) => {
              if (o.type === 'Mesh') {
                mc++;
                if (o.visible) vmc++;
              }
            });
            return { mesh_count: mc, visible_mesh_count: vmc };
          }
          hook = hook.next;
          hookIdx++;
        }
      }
      fiber = fiber.return;
      depth++;
    }
    return { error: 'no scene found' };
  });
}

/** Dump every visible button in the filter sidebar (left column ≤ 340 px). */
async function dumpSidebarButtons(page) {
  return page.evaluate(() => {
    return Array.from(document.querySelectorAll('button'))
      .filter((b) => {
        if (b.offsetParent === null) return false;
        const rect = b.getBoundingClientRect();
        return rect.left < 340 && rect.width > 20;
      })
      .map((b) => {
        const rect = b.getBoundingClientRect();
        return {
          text: (b.textContent || '').trim().slice(0, 80),
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          w: Math.round(rect.width),
        };
      });
  });
}

/** Click the first sidebar button whose text matches the predicate. */
async function clickSidebarButton(page, matcher, label) {
  const result = await page.evaluate(
    ({ matcherSrc }) => {
      const matcher = new Function('return ' + matcherSrc)();
      const btns = Array.from(document.querySelectorAll('button')).filter((b) => {
        if (b.offsetParent === null) return false;
        const rect = b.getBoundingClientRect();
        return rect.left < 340 && rect.width > 20;
      });
      const target = btns.find((b) => matcher((b.textContent || '').trim()));
      if (!target) return { ok: false };
      target.click();
      return { ok: true, text: (target.textContent || '').trim() };
    },
    { matcherSrc: matcher.toString() },
  );
  log(`click[${label}]:`, JSON.stringify(result));
  await page.waitForTimeout(700);
  return result;
}

/* ── main ────────────────────────────────────────────────────────────── */

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();

  const consoleMsgs = [];
  page.on('console', (msg) => consoleMsgs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', (err) => consoleMsgs.push(`[pageerror] ${err.message}`));

  // 1. Login via API just to warm session
  log('login API…');
  await page.request.post(`${BACKEND}/api/v1/users/auth/login/`, {
    headers: { 'Content-Type': 'application/json' },
    data: { email: EMAIL, password: PASSWORD },
  });

  // 2. Pre-set storage so the project context is ready
  await page.goto(`${FRONTEND}/login`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((pid) => {
    localStorage.setItem(
      'oe_active_project',
      JSON.stringify({ id: pid, name: 'Demo BIM', boqId: null }),
    );
    localStorage.setItem('oe_onboarding_completed', 'true');
    localStorage.setItem('oe_tour_completed', 'true');
  }, PROJECT_ID);

  // 3. UI login
  log('UI login…');
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2000);

  // 4. Navigate to /bim
  log('navigating to /bim…');
  await page.goto(`${FRONTEND}/bim?project=${PROJECT_ID}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForTimeout(2500);

  // 5. Dismiss onboarding tour
  for (let i = 0; i < 10; i++) {
    let dismissed = false;
    for (const text of [
      'Skip',
      'Skip tour',
      'Got it',
      'Got it!',
      'Maybe later',
      'Next',
      'Done',
      'Finish',
    ]) {
      const btn = page.locator(`button:has-text("${text}")`).first();
      if (await btn.isVisible().catch(() => false)) {
        await btn.click().catch(() => {});
        await page.waitForTimeout(200);
        dismissed = true;
        break;
      }
    }
    await page.evaluate(() => {
      const overlays = document.querySelectorAll(
        '[class*="tour"], [class*="onboard"], [data-tour]',
      );
      overlays.forEach((o) => o.remove());
    });
    if (!dismissed) break;
  }

  // 6. Wait for the DAE
  log('waiting for DAE (20 s)…');
  await page.waitForTimeout(20_000);
  await page.screenshot({ path: path.join(OUT, '01-loaded.png') });

  // 7. Initial scene snapshot
  const initial = await readScene(page);
  log('initial scene:', JSON.stringify(initial));
  if (initial.error || initial.mesh_count === 0) {
    log('FAIL: scene did not load — aborting test');
    fs.writeFileSync(path.join(OUT, 'console.log'), consoleMsgs.join('\n'));
    await browser.close();
    process.exit(1);
  }

  // 8. Inspect the storey + bucket UI
  log('--- sidebar dump (initial state) ---');
  const sidebar = await dumpSidebarButtons(page);
  fs.writeFileSync(path.join(OUT, 'sidebar.json'), JSON.stringify(sidebar, null, 2));
  // Print only the first 25 to keep the log short
  for (const b of sidebar.slice(0, 30)) {
    log(`  [${b.x},${b.y},w=${b.w}] "${b.text}"`);
  }

  const results = { initial };

  // 9. STOREY TEST — click the first storey chip with a level badge.
  //    Chip textContent is the badge + label + count concatenated with no
  //    spaces, e.g. "01Entry Level4,604". Match a 2-digit numeric badge.
  log('--- TEST 1: storey filter ---');
  await clickSidebarButton(
    page,
    (txt) => /^0\d[A-Z]/.test(txt),
    'storey-01',
  );
  results.afterStorey1 = await readScene(page);
  log('after storey1:', JSON.stringify(results.afterStorey1));
  await page.screenshot({ path: path.join(OUT, '02-after-storey.png') });

  // Click again to deselect
  await clickSidebarButton(
    page,
    (txt) => /^0\d[A-Z]/.test(txt),
    'storey-01-deselect',
  );
  results.afterClearStorey = await readScene(page);
  log('after deselect storey:', JSON.stringify(results.afterClearStorey));

  // 10. BUILDINGS-ONLY TOGGLE TEST — find the toggle button and click it
  log('--- TEST 2: buildings-only toggle ---');
  const togglesBefore = await readScene(page);
  log('before toggle:', JSON.stringify(togglesBefore));
  // The toggle is a small switch button with no text — need to find it differently
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button[role="switch"]'));
    if (btns[0]) btns[0].click();
  });
  await page.waitForTimeout(700);
  const afterToggleOff = await readScene(page);
  log('after toggle OFF (show all):', JSON.stringify(afterToggleOff));
  results.afterBuildingsOff = afterToggleOff;
  // Toggle back on
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button[role="switch"]'));
    if (btns[0]) btns[0].click();
  });
  await page.waitForTimeout(700);
  const afterToggleOn = await readScene(page);
  log('after toggle ON (buildings only):', JSON.stringify(afterToggleOn));
  results.afterBuildingsOn = afterToggleOn;

  // 11. TYPE FILTER TEST — click a "Walls" chip inside the Envelope bucket
  log('--- TEST 3: type filter (click "Walls") ---');
  // Find a chip with exact text starting with "Walls"
  await clickSidebarButton(
    page,
    (txt) => /^Walls\s*\d/.test(txt),
    'walls',
  );
  results.afterWalls = await readScene(page);
  log('after Walls:', JSON.stringify(results.afterWalls));
  await page.screenshot({ path: path.join(OUT, '03-after-walls.png') });

  // 12. CLEAR ALL TEST — click the "Clear all" link in the visible-count
  //     bar.  Use Playwright's direct text locator since this is a small
  //     text-link that may not match our generic sidebar dump filter.
  log('--- TEST 4: clear all ---');
  // Dump current buttons for debug
  const dump2 = await dumpSidebarButtons(page);
  fs.writeFileSync(path.join(OUT, 'sidebar-after-walls.json'), JSON.stringify(dump2, null, 2));
  log('  buttons containing "Clear":', JSON.stringify(dump2.filter((b) => /Clear/i.test(b.text))));
  // Try Playwright locator first
  try {
    const clear = page.locator('button:has-text("Clear all")').first();
    if (await clear.isVisible({ timeout: 1500 }).catch(() => false)) {
      await clear.click();
      log('  clicked via Playwright locator');
    } else {
      log('  Playwright locator did not find a visible "Clear all" button');
    }
  } catch (e) {
    log('  locator click failed:', e.message);
  }
  await page.waitForTimeout(700);
  results.afterClearAll = await readScene(page);
  log('after clear all:', JSON.stringify(results.afterClearAll));
  await page.screenshot({ path: path.join(OUT, '04-after-clear.png') });

  // 13. MULTI-CHIP OR TEST — click Doors (alone), check count.  Click
  //     Walls (additive), check that the count went UP.  This proves the
  //     filter has true OR semantics across types.
  log('--- TEST 5: multi-chip OR ---');
  await clickSidebarButton(page, (txt) => /^Doors\d/.test(txt), 'doors-only');
  results.afterDoors = await readScene(page);
  log('after Doors only:', JSON.stringify(results.afterDoors));
  await clickSidebarButton(page, (txt) => /^Walls\d/.test(txt), 'walls-add');
  results.afterDoorsAndWalls = await readScene(page);
  log('after Doors+Walls:', JSON.stringify(results.afterDoorsAndWalls));
  await page.screenshot({ path: path.join(OUT, '05-doors-and-walls.png') });

  // ── TEST 6: TOOLBAR camera presets
  log('--- TEST 6: camera presets ---');
  // Clear any active filter first via the existing locator path
  await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('button')).filter((b) =>
      /^Clear all$/i.test((b.textContent || '').trim()),
    );
    if (all[0]) (all[0]).click();
  });
  await page.waitForTimeout(500);
  // Snapshot camera position before clicking each preset
  async function readCamera() {
    return page.evaluate(() => {
      const canvas = document.querySelector('canvas');
      if (!canvas) return null;
      const fiberKey = Object.keys(canvas).find((k) => k.startsWith('__reactFiber'));
      if (!fiberKey) return null;
      let fiber = canvas[fiberKey];
      let depth = 0;
      while (fiber && depth < 30) {
        if (fiber.memoizedState) {
          let hook = fiber.memoizedState;
          let i = 0;
          while (hook && i < 20) {
            const ms = hook.memoizedState;
            if (ms && ms.current && ms.current.camera) {
              return {
                x: +ms.current.camera.position.x.toFixed(2),
                y: +ms.current.camera.position.y.toFixed(2),
                z: +ms.current.camera.position.z.toFixed(2),
              };
            }
            hook = hook.next;
            i++;
          }
        }
        fiber = fiber.return;
        depth++;
      }
      return null;
    });
  }

  const presets = ['Top view', 'Front view', 'Side view', 'Isometric view', 'Fit all'];
  const presetCameras = {};
  for (const p of presets) {
    const ok = await page.evaluate((title) => {
      const btn = Array.from(document.querySelectorAll('button')).find(
        (b) => (b.title || '') === title,
      );
      if (!btn) return false;
      btn.click();
      return true;
    }, p);
    log(`  ${p}: clicked=${ok}`);
    await page.waitForTimeout(500);
    const cam = await readCamera();
    presetCameras[p] = cam;
    log(`  ${p}: camera=`, JSON.stringify(cam));
  }
  results.presetCameras = presetCameras;
  await page.screenshot({ path: path.join(OUT, '06-after-presets.png') });

  // ── TEST 7: GRID TOGGLE
  log('--- TEST 7: grid toggle ---');
  const gridBefore = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const fiberKey = Object.keys(canvas).find((k) => k.startsWith('__reactFiber'));
    let fiber = canvas[fiberKey];
    let depth = 0;
    while (fiber && depth < 30) {
      if (fiber.memoizedState) {
        let hook = fiber.memoizedState;
        let i = 0;
        while (hook && i < 20) {
          const ms = hook.memoizedState;
          if (ms && ms.current && ms.current.scene) {
            const sm = ms.current;
            let visGrid = false;
            sm.scene.traverse((o) => {
              if (o.type === 'GridHelper') visGrid = o.visible;
            });
            return visGrid;
          }
          hook = hook.next;
          i++;
        }
      }
      fiber = fiber.return;
      depth++;
    }
    return null;
  });
  log('  grid visible before:', gridBefore);
  // Click the Hide grid / Show grid button
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find((b) =>
      /(Hide grid|Show grid)/.test(b.title || ''),
    );
    if (btn) btn.click();
  });
  await page.waitForTimeout(400);
  const gridAfter = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const fiberKey = Object.keys(canvas).find((k) => k.startsWith('__reactFiber'));
    let fiber = canvas[fiberKey];
    let depth = 0;
    while (fiber && depth < 30) {
      if (fiber.memoizedState) {
        let hook = fiber.memoizedState;
        let i = 0;
        while (hook && i < 20) {
          const ms = hook.memoizedState;
          if (ms && ms.current && ms.current.scene) {
            const sm = ms.current;
            let visGrid = null;
            sm.scene.traverse((o) => {
              if (o.type === 'GridHelper') visGrid = o.visible;
            });
            return visGrid;
          }
          hook = hook.next;
          i++;
        }
      }
      fiber = fiber.return;
      depth++;
    }
    return null;
  });
  log('  grid visible after:', gridAfter);
  results.gridToggle = { before: gridBefore, after: gridAfter };

  // ── TEST 7b: ELEMENT CLICK → details panel → Add to BOQ modal
  log('--- TEST 7b: element click → Add to BOQ ---');
  // Click an element in the explorer to programmatically select it via
  // the existing onElementClick handler. We pick the first wall in the
  // expanded "Envelope" bucket → Walls type → expand the group → click
  // an element. Simpler: use a test hook via React state.
  // Easiest approach: click anywhere on the canvas — the raycaster picks
  // the closest mesh. Then check if the properties panel opened.
  const canvasBox = await page.evaluate(() => {
    const c = document.querySelector('canvas');
    if (!c) return null;
    const r = c.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height };
  });
  if (canvasBox) {
    // Click center of canvas
    await page.mouse.click(canvasBox.x, canvasBox.y);
    await page.waitForTimeout(800);
    // Check if a properties panel appeared (look for "Linked BOQ positions" header)
    const detailsState = await page.evaluate(() => {
      const headers = Array.from(document.querySelectorAll('h3, h4'));
      const hasLinkedSection = headers.some((h) =>
        /Linked BOQ positions|Linked BOQ/i.test(h.textContent || ''),
      );
      const hasAddBtn = !!Array.from(document.querySelectorAll('button')).find(
        (b) => /Add to BOQ/i.test(b.textContent || ''),
      );
      const hasUnlinkBtn = !!Array.from(document.querySelectorAll('button')).find(
        (b) => /Remove link/i.test(b.title || ''),
      );
      return { hasLinkedSection, hasAddBtn, hasUnlinkBtn };
    });
    log('  details panel state:', JSON.stringify(detailsState));
    results.detailsPanel = detailsState;
    await page.screenshot({ path: path.join(OUT, '08-element-details.png') });

    // If Add to BOQ button is visible, click it and screenshot the modal
    if (detailsState.hasAddBtn) {
      await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll('button')).find((b) =>
          /Add to BOQ/i.test(b.textContent || ''),
        );
        if (btn) btn.click();
      });
      await page.waitForTimeout(1000);
      const modalState = await page.evaluate(() => {
        const headers = Array.from(document.querySelectorAll('h2'));
        const hasModalHeader = headers.some((h) =>
          /Add to BOQ/i.test(h.textContent || ''),
        );
        const tabs = Array.from(document.querySelectorAll('button')).filter(
          (b) =>
            /Link to existing|Create new position/i.test(b.textContent || ''),
        );
        return { hasModalHeader, tabCount: tabs.length };
      });
      log('  AddToBOQ modal:', JSON.stringify(modalState));
      results.addToBOQModal = modalState;
      await page.screenshot({ path: path.join(OUT, '09-add-to-boq-modal.png') });
      // Close the modal by clicking the X button or pressing Escape
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(300);
    }
  }

  // ── TEST 7c: SAVE AS GROUP modal — verify the new element-groups UX
  log('--- TEST 7c: save as group ---');
  // Re-apply a filter so the visible/total mismatch shows the button
  await clickSidebarButton(page, (txt) => /^Walls\d/.test(txt), 'walls-for-group');
  await page.waitForTimeout(400);
  // Click "Save as group"
  const saveBtnClicked = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find((b) =>
      /Save as group/i.test((b.textContent || '').trim()),
    );
    if (btn) {
      btn.click();
      return true;
    }
    return false;
  });
  log('  Save-as-group clicked:', saveBtnClicked);
  await page.waitForTimeout(700);
  const groupModalState = await page.evaluate(() => {
    const headers = Array.from(document.querySelectorAll('h2'));
    const hasHeader = headers.some((h) =>
      /Save current filter as group|Save.*group/i.test(h.textContent || ''),
    );
    const nameInput = !!document.querySelector('input[type="text"][placeholder*="Walls"]');
    const dynRadios = Array.from(document.querySelectorAll('input[type="radio"]'));
    return { hasHeader, nameInput, radioCount: dynRadios.length };
  });
  log('  SaveGroup modal:', JSON.stringify(groupModalState));
  results.saveGroupModal = groupModalState;
  await page.screenshot({ path: path.join(OUT, '11-save-group-modal.png') });
  // Close modal
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(300);
  // Clear filter
  await page.evaluate(() => {
    const all = Array.from(document.querySelectorAll('button')).filter((b) =>
      /^Clear all$/i.test((b.textContent || '').trim()),
    );
    if (all[0]) (all[0]).click();
  });
  await page.waitForTimeout(400);

  // ── TEST 9: STRESS TEST — clone the scene meshes 4x in-place to
  //    simulate a 4x bigger model (~21 760 meshes) and re-measure fps.
  log('--- TEST 9: stress test (clone scene 4×) ---');
  const stressResult = await page.evaluate(async () => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return { error: 'no canvas' };
    const fiberKey = Object.keys(canvas).find((k) => k.startsWith('__reactFiber'));
    if (!fiberKey) return { error: 'no fiber' };
    let fiber = canvas[fiberKey];
    let scene = null;
    let depth = 0;
    while (fiber && depth < 30) {
      if (fiber.memoizedState) {
        let hook = fiber.memoizedState;
        let i = 0;
        while (hook && i < 20) {
          const ms = hook.memoizedState;
          if (ms && ms.current && ms.current.scene) {
            scene = ms.current.scene;
            break;
          }
          hook = hook.next;
          i++;
        }
      }
      if (scene) break;
      fiber = fiber.return;
      depth++;
    }
    if (!scene) return { error: 'no scene' };

    // Find the bim_dae_geometry group and clone all its meshes 3 extra times
    let daeGroup = null;
    scene.traverse((o) => {
      if (o.name === 'bim_dae_geometry') daeGroup = o;
    });
    if (!daeGroup) return { error: 'no dae group' };

    const sourceMeshes = [];
    daeGroup.traverse((o) => {
      if (o.type === 'Mesh') sourceMeshes.push(o);
    });
    const baseCount = sourceMeshes.length;

    // Clone the meshes and add to a new group offset along x.  We use
    // SHALLOW cloning of geometry references so the clones share GPU
    // buffers — this is the realistic case for a model with repeated
    // structural elements (columns, panels, etc).
    for (let i = 1; i <= 3; i++) {
      const clone = daeGroup.clone(true);
      clone.position.x += i * 4; // tighter offset so all 4 fit in camera
      clone.name = `bim_dae_clone_${i}`;
      scene.add(clone);
    }

    // Force the camera to fit the new (4×) bbox so the renderer actually
    // has to draw every cloned mesh, not just frustum-cull most of them.
    // We poke the existing fiber to find the SceneManager and call zoomToFit.
    // This is a best-effort hack — if it fails the test still measures
    // the JS-iteration component.
    const fiberKey2 = Object.keys(canvas).find((k) => k.startsWith('__reactFiber'));
    if (fiberKey2) {
      let f2 = canvas[fiberKey2];
      let depth2 = 0;
      while (f2 && depth2 < 30) {
        if (f2.memoizedState) {
          let h2 = f2.memoizedState;
          let i2 = 0;
          while (h2 && i2 < 20) {
            const ms2 = h2.memoizedState;
            if (ms2 && ms2.current && ms2.current.zoomToFit) {
              ms2.current.zoomToFit();
              break;
            }
            h2 = h2.next;
            i2++;
          }
        }
        f2 = f2.return;
        depth2++;
      }
    }

    // Count total meshes now
    let total = 0;
    scene.traverse((o) => {
      if (o.type === 'Mesh') total++;
    });

    // Measure FPS for 2 s
    const fps = await new Promise((resolve) => {
      let frames = 0;
      const start = performance.now();
      function tick() {
        frames++;
        if (performance.now() - start < 2000) {
          requestAnimationFrame(tick);
        } else {
          resolve(Math.round((frames * 1000) / (performance.now() - start)));
        }
      }
      requestAnimationFrame(tick);
    });

    return { baseCount, total, fps };
  });
  log('  stress:', JSON.stringify(stressResult));
  results.stress = stressResult;
  await page.screenshot({ path: path.join(OUT, '10-stress-test.png') });

  // ── TEST 8: NAVIGATE to /bim/rules and verify it loads
  log('--- TEST 8: /bim/rules page ---');
  await page.goto(`${FRONTEND}/bim/rules`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(OUT, '07-rules-page.png') });
  const rulesPageInfo = await page.evaluate(() => {
    const h1 = document.querySelector('h1, h2');
    return {
      title: h1?.textContent?.slice(0, 80) || 'NO HEADER',
      hasButton: !!Array.from(document.querySelectorAll('button')).find((b) =>
        /New rule|Create.*rule|Add rule/i.test(b.textContent || ''),
      ),
      hasTable: !!document.querySelector('table'),
      bodyText: document.body.textContent?.slice(0, 300) || '',
    };
  });
  log('  /bim/rules:', JSON.stringify(rulesPageInfo, null, 2));
  results.rulesPage = rulesPageInfo;

  // 13. FPS measurement
  log('--- FPS measurement ---');
  const fps = await page.evaluate(async () => {
    return await new Promise((resolve) => {
      let frames = 0;
      const start = performance.now();
      function tick() {
        frames++;
        if (performance.now() - start < 2000) {
          requestAnimationFrame(tick);
        } else {
          resolve(Math.round((frames * 1000) / (performance.now() - start)));
        }
      }
      requestAnimationFrame(tick);
    });
  });
  log('fps:', fps);
  results.fps = fps;

  // 14. Verdict
  log('--- VERDICT ---');
  const verdict = [];
  const total = initial.mesh_count;
  if (total === 0) verdict.push('FAIL scene empty');
  if (results.afterStorey1.visible_mesh_count >= total)
    verdict.push('FAIL storey filter did not hide anything');
  else verdict.push(`PASS storey filter (${results.afterStorey1.visible_mesh_count}/${total} visible)`);
  if (results.afterClearStorey.visible_mesh_count !== total)
    verdict.push(`WARN clear storey did not restore all (${results.afterClearStorey.visible_mesh_count}/${total})`);
  else verdict.push('PASS clear storey restored full visibility');
  if (results.afterBuildingsOff.visible_mesh_count <= results.afterBuildingsOn.visible_mesh_count)
    verdict.push('FAIL buildings-only toggle had no effect');
  else verdict.push(`PASS buildings-only (off=${results.afterBuildingsOff.visible_mesh_count} on=${results.afterBuildingsOn.visible_mesh_count})`);
  if (results.afterWalls.visible_mesh_count >= results.afterBuildingsOn.visible_mesh_count)
    verdict.push('FAIL Walls filter did not narrow visibility');
  else verdict.push(`PASS Walls filter (${results.afterWalls.visible_mesh_count} visible)`);
  if (results.afterClearAll.visible_mesh_count < total - 500)
    verdict.push(`WARN clear all did not restore all (${results.afterClearAll.visible_mesh_count}/${total})`);
  else verdict.push(`PASS clear all (${results.afterClearAll.visible_mesh_count}/${total})`);
  if (results.afterDoors && results.afterDoorsAndWalls) {
    if (
      results.afterDoorsAndWalls.visible_mesh_count >
      results.afterDoors.visible_mesh_count
    ) {
      verdict.push(
        `PASS multi-chip OR (Doors=${results.afterDoors.visible_mesh_count}, +Walls=${results.afterDoorsAndWalls.visible_mesh_count})`,
      );
    } else {
      verdict.push('FAIL multi-chip OR did not increase visible count');
    }
  }
  verdict.push(`fps=${fps}`);
  for (const v of verdict) log(' ', v);

  fs.writeFileSync(path.join(OUT, 'console.log'), consoleMsgs.join('\n'));
  fs.writeFileSync(
    path.join(OUT, 'inspect.json'),
    JSON.stringify({ results, verdict, sidebar: sidebar.slice(0, 50) }, null, 2),
  );

  await browser.close();
  log('done.');
})().catch((err) => {
  console.error('FAIL:', err);
  process.exit(1);
});
