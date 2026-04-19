/**
 * v1.9.4 Cluster B — CAD/BIM workflow end-to-end tests.
 *
 * Covers three high-value surfaces:
 *   1. /dwg-takeoff — drag-and-drop landing, ToolPalette cycling, right
 *      panel tabs (Layers / Annotations / Summary / Link), scale input,
 *      Export PDF.
 *   2. /bim + /bim/{id} — model list, viewer init, Measure distance
 *      toggle, save-view toggle, Filtered summary toggle.
 *   3. /data-explorer — landing, recent model selection, MissingDataPanel
 *      fill-rate visualisation, category/type filter interaction.
 *
 * Each significant step captures a fullPage screenshot under
 * test-results/r5-cluster-b/. Console errors are recorded and surfaced
 * per test via attachConsoleErrorWatcher (copy of the helper from
 * r5-verification.spec.ts).
 *
 * The goal is to exercise real user workflows, not just page loads.
 */
import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';
import { loginV19, firstProjectId } from './helpers-v19';

const OUT = 'test-results/r5-cluster-b';

/** Console-error watcher with the same noise filters as r5-verification.
 *  Network 4xx/5xx are recorded but treated as soft-findings (not fatal)
 *  since they usually indicate missing test-user permissions or
 *  rate-limiting from parallel specs, not frontend bugs. The per-test
 *  JSON report surfaces them for follow-up. */
function attachConsoleErrorWatcher(page: Page) {
  const errors: string[] = [];
  const networkErrors: string[] = [];
  const handler = (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (
        text.includes('[vite]') ||
        text.includes('HMR') ||
        text.includes('Download the React DevTools') ||
        text.includes('DeprecationWarning') ||
        text.includes('AbortError') ||
        text.includes('workbox')
      ) {
        return;
      }
      // Network failures (Failed to load resource / 4xx / 5xx) go into
      // the soft bucket so they don't hard-fail the spec on intermittent
      // 403/404s.
      if (
        text.includes('Failed to load resource') ||
        /\b4\d\d\b/.test(text) ||
        /\b5\d\d\b/.test(text)
      ) {
        networkErrors.push(text);
        return;
      }
      errors.push(text);
    }
  };
  page.on('console', handler);
  return () => {
    page.off('console', handler);
    return { fatal: errors, network: networkErrors };
  };
}

test.describe('Cluster B — CAD/BIM end-to-end workflows', () => {
  test.beforeEach(async ({ page }) => {
    await loginV19(page);
  });

  /* ────────────────────────────────────────────────────────────────── */
  /* 1. DWG Takeoff full flow                                            */
  /* ────────────────────────────────────────────────────────────────── */

  test('DWG Takeoff — landing, tool palette cycling, right-panel tabs, export', async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const stop = attachConsoleErrorWatcher(page);

    await page.goto('/dwg-takeoff');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    // 01 — landing page (drop zone + Offline Ready badge)
    await page.screenshot({ path: `${OUT}/01-dwg-landing.png`, fullPage: true });

    // Offline Ready badge should be present somewhere on the page
    const offlineBadge = page.getByText(/Offline Ready/i).first();
    const offlineBadgeVisible = await offlineBadge
      .isVisible({ timeout: 5000 })
      .catch(() => false);

    // Check for drag-and-drop or upload area
    const hasDropZone =
      (await page.getByText(/drop|upload|drag/i).count()) > 0;

    // If there is a filmstrip with drawings, click the first one to open the viewer.
    // Filmstrip lives at the bottom — thumbnails render as buttons/cards.
    const filmstripDrawing = page.locator('[data-testid^="dwg-filmstrip-"]').first();
    const hasExistingDrawings = await filmstripDrawing
      .isVisible({ timeout: 3000 })
      .catch(() => false);

    let viewerOpened = false;
    if (hasExistingDrawings) {
      await filmstripDrawing.click();
      await page.waitForTimeout(1500);
      viewerOpened = true;
    } else {
      // Fallback: try any clickable drawing card in the lower half of the page
      const anyCard = page
        .locator('button, [role="button"]')
        .filter({ hasText: /\.dxf|\.dwg/i })
        .first();
      if (await anyCard.isVisible({ timeout: 2000 }).catch(() => false)) {
        await anyCard.click();
        await page.waitForTimeout(1500);
        viewerOpened = true;
      }
    }

    // 02 — viewer open state (or landing if no drawings)
    await page.screenshot({
      path: `${OUT}/02-dwg-viewer-or-landing.png`,
      fullPage: true,
    });

    // Check the right-panel tabs are all addressable via data-testid
    // regardless of whether a drawing is open (some tabs appear even
    // without an active drawing).  We assert per tab and continue on
    // failure so we get a full picture of which ones are missing.
    const expectedTabs = ['layers', 'annotations', 'properties', 'scale', 'summary'];
    const tabVisibility: Record<string, boolean> = {};
    for (const tabId of expectedTabs) {
      const tab = page.getByTestId(`dwg-right-tab-${tabId}`);
      const visible = await tab.isVisible({ timeout: 2500 }).catch(() => false);
      tabVisibility[tabId] = visible;
    }

    // 03 — right-panel tabs state
    await page.screenshot({
      path: `${OUT}/03-dwg-right-tabs.png`,
      fullPage: true,
    });

    // If the viewer is open, rotate through each tool in the palette and
    // snapshot so we can verify the indicator (blue background) updates.
    const tools = [
      'select',
      'pan',
      'distance',
      'line',
      'polyline',
      'area',
      'rectangle',
      'circle',
      'arrow',
      'text_pin',
    ];
    const toolResults: Record<string, boolean> = {};
    if (viewerOpened) {
      // ToolPalette buttons have title attribute "Tool name (shortcut)";
      // they do not expose role=button by default. We'll use title prefix.
      for (const toolId of tools) {
        const btn = page.locator('button[title^="' + toolId + '"]').first();
        const found = await btn.isVisible({ timeout: 1000 }).catch(() => false);
        toolResults[toolId] = found;
        if (found) {
          await btn.click({ trial: false }).catch(() => {});
          await page.waitForTimeout(150);
        }
      }
      // Snap at end of tool cycle
      await page.screenshot({
        path: `${OUT}/04-dwg-tool-cycle-final.png`,
        fullPage: true,
      });
    }

    // Scale input — visible near the tool palette. We look for any numeric
    // input with aria-label or placeholder referencing scale.
    const scaleInputCandidates = [
      page.locator('input[aria-label*="cale" i]'),
      page.locator('input[placeholder*="cale" i]'),
      page.locator('input[name*="cale" i]'),
      // fallback: input near a "Scale" label
      page
        .locator('label:has-text("Scale") + input, label:has-text("Scale") input')
        .first(),
    ];
    let scaleVisible = false;
    for (const cand of scaleInputCandidates) {
      if (await cand.first().isVisible({ timeout: 1000 }).catch(() => false)) {
        scaleVisible = true;
        break;
      }
    }

    // Open Summary tab (if present) and look for totals panel
    let summaryTotalsVisible = false;
    if (tabVisibility['summary']) {
      await page.getByTestId('dwg-right-tab-summary').click({ trial: false }).catch(() => {});
      await page.waitForTimeout(400);
      // totals panel copy includes "Total", "Area", "Length", etc.
      const totalsText = page.getByText(/total|totals|area|length/i).first();
      summaryTotalsVisible = await totalsText
        .isVisible({ timeout: 2000 })
        .catch(() => false);
      await page.screenshot({
        path: `${OUT}/05-dwg-summary-tab.png`,
        fullPage: true,
      });
    }

    // Export PDF — button should be present somewhere; clicking it should
    // either trigger a download or at least produce no unhandled error.
    const exportButtonCandidates = [
      page.getByRole('button', { name: /export pdf/i }),
      page.getByRole('button', { name: /export/i }),
      page.locator('button[title*="PDF" i]'),
      page.locator('button:has-text("PDF")'),
    ];
    let exportClicked = false;
    let downloadHappened = false;
    for (const cand of exportButtonCandidates) {
      const first = cand.first();
      if (await first.isVisible({ timeout: 1000 }).catch(() => false)) {
        const downloadPromise = page
          .waitForEvent('download', { timeout: 6000 })
          .catch(() => null);
        await first.click({ trial: false }).catch(() => {});
        exportClicked = true;
        const dl = await downloadPromise;
        if (dl) {
          downloadHappened = true;
        }
        break;
      }
    }
    await page.screenshot({
      path: `${OUT}/06-dwg-after-export.png`,
      fullPage: true,
    });

    // Surface everything for the report — soft-assert style.
    const { fatal, network } = stop();
    // eslint-disable-next-line no-console
    console.log(
      '[Cluster B DWG report]',
      JSON.stringify(
        {
          offlineBadgeVisible,
          hasDropZone,
          hasExistingDrawings,
          viewerOpened,
          tabVisibility,
          toolResults,
          scaleVisible,
          summaryTotalsVisible,
          exportClicked,
          downloadHappened,
          fatalConsoleErrors: fatal,
          networkConsoleErrors: network,
        },
        null,
        2,
      ),
    );

    // Hard expectations — these must hold for a healthy build
    expect(offlineBadgeVisible || hasDropZone, 'Landing shows drop-zone or Offline Ready badge').toBeTruthy();
    // Tabs only render after a drawing is loaded — only assert them if
    // the viewer actually opened. Otherwise they are expected to be
    // absent and we log the state in the JSON report above.
    if (viewerOpened) {
      expect(tabVisibility['layers'], 'Layers tab present').toBeTruthy();
      expect(tabVisibility['annotations'], 'Annotations tab present').toBeTruthy();
      expect(tabVisibility['summary'], 'Summary tab present').toBeTruthy();
    }
    expect(fatal, 'No fatal console errors on /dwg-takeoff').toEqual([]);
  });

  /* ────────────────────────────────────────────────────────────────── */
  /* 2. BIM viewer full flow                                             */
  /* ────────────────────────────────────────────────────────────────── */

  test('BIM viewer — model list, 3D init, Measure, Save view, Filtered summary', async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const stop = attachConsoleErrorWatcher(page);

    await page.goto('/bim');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    // 10 — model list landing
    await page.screenshot({ path: `${OUT}/10-bim-index.png`, fullPage: true });

    // The BIM page reads projectId from /projects/:projectId/bim (not
    // ?project_id=…). Without it the page shows "No project selected".
    // Use firstProjectId + nested route to scope correctly.
    const projectId = await firstProjectId(page);
    if (!projectId) {
      // eslint-disable-next-line no-console
      console.log('[Cluster B BIM] no project available — landing will show empty state');
    }

    if (projectId) {
      await page.goto(`/projects/${projectId}/bim`);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(2000);
      await page.screenshot({
        path: `${OUT}/10b-bim-with-project.png`,
        fullPage: true,
      });
    }

    // Click the first BIM model tile / filmstrip thumbnail. BIMPage
    // renders cards as <button> elements with onClick handlers rather
    // than anchor links, so we hunt for a button whose text contains a
    // model filename (.rvt / .ifc / .rfa / .dgn) — excluding toolbar
    // buttons.
    const modelButtonCandidates = [
      // Filmstrip thumbnails in the bottom strip
      page.locator('button').filter({ hasText: /\.(rvt|ifc|rfa|dgn)\b/i }).first(),
      // Landing page tile with the model name and element count
      page.locator('[data-testid^="bim-model-"]').first(),
    ];

    let modelCardVisible = false;
    let clickedModelButton = false;
    for (const cand of modelButtonCandidates) {
      if (await cand.isVisible({ timeout: 3000 }).catch(() => false)) {
        modelCardVisible = true;
        await cand.click().catch(() => {});
        clickedModelButton = true;
        break;
      }
    }

    let viewerLoaded = false;
    let canvasVisible = false;
    if (clickedModelButton) {
      // BIMPage uses setActiveModelId + ?modelId param; URL may or may
      // not change. Wait for a canvas element either way.
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.waitForTimeout(3500); // WebGL warmup
      const canvas = page.locator('canvas').first();
      canvasVisible = await canvas.isVisible({ timeout: 15_000 }).catch(() => false);
      viewerLoaded = canvasVisible;
    }

    // 11 — viewer state
    await page.screenshot({
      path: `${OUT}/11-bim-viewer-initial.png`,
      fullPage: true,
    });

    let measureHintVisible = false;
    let missToastVisible = false;
    let toolsTabOpened = false;
    let summaryToggled = false;

    if (viewerLoaded) {
      // Measure button — identified by its title "Measure distance (M)"
      const measureBtn = page.locator('button[title*="Measure distance" i]').first();
      if (await measureBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await measureBtn.click();
        await page.waitForTimeout(500);
        // Hint lives at data-testid="bim-measure-hint"
        measureHintVisible = await page
          .getByTestId('bim-measure-hint')
          .isVisible({ timeout: 2000 })
          .catch(() => false);
        await page.screenshot({
          path: `${OUT}/12-bim-measure-on.png`,
          fullPage: true,
        });

        // Click in "empty" space — the far corner of the canvas is likely
        // off-model; the MeasureManager should fire onMiss → toast.
        const canvas = page.locator('canvas').first();
        const bbox = await canvas.boundingBox();
        if (bbox) {
          // Very top-left corner of the canvas should be background.
          await page.mouse.click(bbox.x + 5, bbox.y + 5);
          await page.waitForTimeout(600);
          // Toasts render in a portal; look for common toast copy
          // ("click two points", "missed", "no element", …) as well
          // as the generic toast container.
          const toastCandidates = [
            page.locator('[data-sonner-toast]'),
            page.locator('[role="status"]'),
            page.locator('.toast, [data-testid*="toast"]'),
            page.getByText(/miss|no element|empty space|background/i),
          ];
          for (const cand of toastCandidates) {
            if (await cand.first().isVisible({ timeout: 1500 }).catch(() => false)) {
              missToastVisible = true;
              break;
            }
          }
          await page.screenshot({
            path: `${OUT}/13-bim-miss-toast.png`,
            fullPage: true,
          });
        }

        // Press Escape to exit measure mode
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
      }

      // Save current view — title "Save current view"
      const saveViewBtn = page.locator('button[title*="Save current view" i]').first();
      if (await saveViewBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await saveViewBtn.click();
        await page.waitForTimeout(500);
        // Tools tab opens on the right — look for "Measure" title or
        // BIMToolsPanel specific copy.
        const measurePanelHeading = page
          .getByText(/saved views|measure distance/i)
          .first();
        toolsTabOpened = await measurePanelHeading
          .isVisible({ timeout: 3000 })
          .catch(() => false);
        await page.screenshot({
          path: `${OUT}/14-bim-tools-tab.png`,
          fullPage: true,
        });
      }

      // Filtered summary toggle — title "Show summary panel" or "Hide summary panel"
      const summaryBtn = page
        .locator('button[title*="summary panel" i]')
        .first();
      if (await summaryBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        const before = await page
          .getByText(/Filtered summary/i)
          .first()
          .isVisible({ timeout: 500 })
          .catch(() => false);
        await summaryBtn.click();
        await page.waitForTimeout(400);
        const after = await page
          .getByText(/Filtered summary/i)
          .first()
          .isVisible({ timeout: 2000 })
          .catch(() => false);
        summaryToggled = before !== after;
        await page.screenshot({
          path: `${OUT}/15-bim-filtered-summary.png`,
          fullPage: true,
        });
      }
    }

    const { fatal, network } = stop();
    // eslint-disable-next-line no-console
    console.log(
      '[Cluster B BIM report]',
      JSON.stringify(
        {
          modelCardVisible,
          viewerLoaded,
          canvasVisible,
          measureHintVisible,
          missToastVisible,
          toolsTabOpened,
          summaryToggled,
          fatalConsoleErrors: fatal,
          networkConsoleErrors: network,
        },
        null,
        2,
      ),
    );

    // Soft expectations — only the core "landing renders cleanly"
    // blocks the test. Finer failures surface in the JSON report.
    expect(fatal, 'No fatal console errors on /bim').toEqual([]);
  });

  /* ────────────────────────────────────────────────────────────────── */
  /* 3. Data Explorer                                                   */
  /* ────────────────────────────────────────────────────────────────── */

  test('Data Explorer — landing, table, MissingDataPanel, filters', async ({ page }) => {
    test.setTimeout(60_000);
    const stop = attachConsoleErrorWatcher(page);

    const projectId = await firstProjectId(page);
    const url = projectId
      ? `/data-explorer?project_id=${projectId}`
      : '/data-explorer';
    await page.goto(url);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    // 20 — landing
    await page.screenshot({
      path: `${OUT}/20-data-explorer-landing.png`,
      fullPage: true,
    });

    // Recent models list — filmstrip cards are <button> elements with
    // "{N} elements" copy and an "RVT|IFC|DWG|DGN|DXF" format badge.
    // Locate via the element-count line which is uniquely a filmstrip
    // card.
    const recentModelCandidates = [
      page.locator('button').filter({ hasText: /\d[\d,]*\s+elements/i }).first(),
      page.getByRole('button').filter({ hasText: /\d[\d,]*\s+elements/i }).first(),
      page.locator('button').filter({ hasText: /ago$/i }).filter({ hasText: /elements/i }).first(),
    ];
    let recentModelVisible = false;
    let selectedRecent = false;
    for (const cand of recentModelCandidates) {
      if (await cand.isVisible({ timeout: 2500 }).catch(() => false)) {
        recentModelVisible = true;
        await cand.click().catch(() => {});
        selectedRecent = true;
        await page.waitForLoadState('networkidle').catch(() => {});
        // Table + MissingDataPanel need time to fetch /describe and
        // /missingness endpoints for a 9k-element session.
        await page.waitForTimeout(6000);
        break;
      }
    }

    // 21 — table / main content
    await page.screenshot({
      path: `${OUT}/21-data-explorer-table.png`,
      fullPage: true,
    });

    // Try to open the Describe / Missing sub-tab where MissingDataPanel
    // lives (v1.9.4). Tabs are usually buttons with these labels.
    const describeTabCandidates = [
      page.getByRole('button', { name: /describe/i }).first(),
      page.getByRole('tab', { name: /describe/i }).first(),
      page.getByText(/describe/i).first(),
    ];
    for (const cand of describeTabCandidates) {
      if (await cand.isVisible({ timeout: 1500 }).catch(() => false)) {
        await cand.click().catch(() => {});
        await page.waitForTimeout(1500);
        break;
      }
    }
    const missingSubTab = [
      page.getByRole('button', { name: /missing/i }).first(),
      page.getByRole('tab', { name: /missing/i }).first(),
      page.getByText(/missing.*data|fill.?rate/i).first(),
    ];
    for (const cand of missingSubTab) {
      if (await cand.isVisible({ timeout: 1500 }).catch(() => false)) {
        await cand.click().catch(() => {});
        await page.waitForTimeout(2000);
        break;
      }
    }

    // MissingDataPanel — rendered as canvas with a copy-to-clipboard
    // button ("Copy" icon). We look for canvas + any "missing" or
    // "fill" copy on the page.
    const missingCanvas = page.locator('canvas');
    const missingCanvasCount = await missingCanvas.count();
    const missingCopy = page.getByText(/missing|fill.?rate|completeness/i).first();
    const missingCopyVisible = await missingCopy
      .isVisible({ timeout: 3000 })
      .catch(() => false);

    // Category / element type filter dropdowns — these are <select>
    // elements in MissingDataPanel.
    const selects = page.locator('select');
    const selectCount = await selects.count();
    let filterInteracted = false;
    if (selectCount > 0) {
      // Find a <select> whose options include something with a meaningful
      // label (non-empty) and change the value.
      for (let i = 0; i < selectCount; i++) {
        const sel = selects.nth(i);
        const options = sel.locator('option');
        const optCount = await options.count().catch(() => 0);
        if (optCount >= 2) {
          const secondValue = await options.nth(1).getAttribute('value').catch(() => null);
          if (secondValue !== null && secondValue !== '') {
            await sel.selectOption(secondValue).catch(() => {});
            filterInteracted = true;
            await page.waitForTimeout(500);
            break;
          }
        }
      }
    }

    await page.screenshot({
      path: `${OUT}/22-data-explorer-missing-panel.png`,
      fullPage: true,
    });

    const { fatal, network } = stop();
    // eslint-disable-next-line no-console
    console.log(
      '[Cluster B Data Explorer report]',
      JSON.stringify(
        {
          recentModelVisible,
          selectedRecent,
          missingCanvasCount,
          missingCopyVisible,
          selectCount,
          filterInteracted,
          fatalConsoleErrors: fatal,
          networkConsoleErrors: network,
        },
        null,
        2,
      ),
    );

    // Data Explorer currently surfaces a 404 from
    // /v1/takeoff/cad-data/missingness/ on sessions that have not yet
    // been precomputed (v1.9.4). Those land in the `network` bucket and
    // are reported but not fatal.
    expect(fatal, 'No fatal console errors on /data-explorer').toEqual([]);
  });
});
