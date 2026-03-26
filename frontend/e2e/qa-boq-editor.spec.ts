/**
 * QA Test -- BOQ Editor Page Comprehensive Testing
 *
 * Logs in with demo account, dismisses onboarding tour, navigates to project -> BOQ,
 * and thoroughly tests the BOQ Editor page.
 */
import { test, expect, type Page } from '@playwright/test';

const SCREENSHOT_DIR = '../screenshots/qa-boq-editor';
const DEMO_EMAIL = 'demo@openestimator.io';
const DEMO_PASSWORD = 'DemoPass1234!';

/** Dismiss onboarding tour by clicking Skip/X/Next repeatedly */
async function dismissOnboardingTour(page: Page) {
  for (let attempt = 0; attempt < 15; attempt++) {
    const tourDialog = page.locator('[data-testid="onboarding-tooltip"]');
    if ((await tourDialog.count()) === 0) break;

    // Try Skip Tour / Finish button first
    const skipBtn = page.locator('[data-testid="onboarding-tooltip"] button:has-text("Skip"), [data-testid="onboarding-tooltip"] button:has-text("Finish"), [data-testid="onboarding-tooltip"] button:has-text("Done")');
    if (await skipBtn.count() > 0) {
      await skipBtn.first().click({ force: true });
      await page.waitForTimeout(400);
      continue;
    }

    // Try X close button
    const closeX = page.locator('[data-testid="onboarding-tooltip"] button:has(svg)').first();
    if (await closeX.count() > 0) {
      await closeX.click({ force: true });
      await page.waitForTimeout(400);
      continue;
    }

    // Try Next button to advance
    const nextBtn = page.locator('[data-testid="onboarding-tooltip"] button:has-text("Next")');
    if (await nextBtn.count() > 0) {
      await nextBtn.first().click({ force: true });
      await page.waitForTimeout(400);
      continue;
    }

    // Nothing to click - break
    break;
  }
  await page.waitForTimeout(300);
}

test.describe('BOQ Editor QA', () => {
  test.setTimeout(240_000);

  test('Complete BOQ Editor QA Test', async ({ page }) => {
    const consoleErrors: string[] = [];
    const consoleWarnings: string[] = [];
    const networkErrors: string[] = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(`[console.error] ${msg.text()}`);
      if (msg.type() === 'warning') consoleWarnings.push(`[console.warn] ${msg.text()}`);
    });
    page.on('pageerror', (err) => consoleErrors.push(`[pageerror] ${err.message}`));
    page.on('response', (resp) => {
      if (resp.status() >= 400) networkErrors.push(`[${resp.status()}] ${resp.url()}`);
    });

    // ═══════════════════════════════════════════════════════════════════
    // STEP 1: LOGIN
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 1: LOGIN ===');
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `${SCREENSHOT_DIR}/01-login-page.png`, fullPage: true });

    // Try "Try demo account" button
    const demoBtn = page.locator('button:has-text("demo"), button:has-text("Demo")');
    if (await demoBtn.count() > 0) {
      await demoBtn.first().click();
      await page.waitForTimeout(500);
    }

    // Fill credentials
    const emailInput = page.locator('input[type="email"]');
    const passwordInput = page.locator('input[type="password"], #login-password');
    if (await emailInput.count() > 0) await emailInput.fill(DEMO_EMAIL);
    if (await passwordInput.count() > 0) await passwordInput.first().fill(DEMO_PASSWORD);

    // Click Login
    const loginBtn = page.locator('button[type="submit"]');
    if (await loginBtn.count() > 0) await loginBtn.click();

    await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15000 }).catch(() => {});
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(2000);
    await dismissOnboardingTour(page);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/02-after-login.png`, fullPage: true });
    console.log(`After login URL: ${page.url()}`);

    // ═══════════════════════════════════════════════════════════════════
    // STEP 2: NAVIGATE TO PROJECT DETAIL
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 2: NAVIGATE TO PROJECTS ===');
    await page.goto('/projects');
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(2000);
    await dismissOnboardingTour(page);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/03-projects-page.png`, fullPage: true });

    // Click first project card (use force to bypass any overlay)
    const projectCard = page.locator('[class*="cursor-pointer"]').first();
    await projectCard.click({ force: true });
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(2000);
    await dismissOnboardingTour(page);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/04-project-detail.png`, fullPage: true });
    console.log(`Project detail URL: ${page.url()}`);

    // ═══════════════════════════════════════════════════════════════════
    // STEP 3: CLICK ON A BOQ ITEM TO OPEN EDITOR
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 3: OPEN BOQ EDITOR ===');

    // The BOQ items are in the "Bill of Quantities" section. Each BOQ has a button
    // with onClick={() => navigate(`/boq/${boq.id}`)} inside a div with hover:bg-surface-secondary
    // Click on the BOQ name text which is a <button> with class text-left
    const boqNameBtn = page.locator('button.text-left >> text=Kostenberechnung').first();
    if (await boqNameBtn.count() > 0) {
      console.log('Found BOQ name button, clicking...');
      await boqNameBtn.click({ force: true });
    } else {
      // Fallback: click on any BOQ row element
      const boqRow = page.locator('.hover\\:bg-surface-secondary').first();
      if (await boqRow.count() > 0) {
        console.log('Found BOQ row, clicking...');
        await boqRow.click({ force: true });
      } else {
        // Last resort: directly navigate using known BOQ list API
        console.log('Navigating to /boq page instead...');
        await page.goto('/boq');
        await page.waitForLoadState('networkidle').catch(() => {});
        await page.waitForTimeout(2000);
        await dismissOnboardingTour(page);

        // Click first BOQ from the list
        const boqListItem = page.locator('[class*="cursor-pointer"]').first();
        if (await boqListItem.count() > 0) {
          await boqListItem.click({ force: true });
        }
      }
    }

    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(3000);
    await dismissOnboardingTour(page);

    // Verify we're on the BOQ editor page
    const currentUrl = page.url();
    console.log(`After BOQ click URL: ${currentUrl}`);

    // If still not on editor, try getting BOQ ID from API and navigating directly
    if (!currentUrl.match(/\/boq\/[0-9a-f-]{36}/)) {
      console.log('Not on BOQ editor, trying API-based navigation...');
      // Get project ID from URL
      const projectMatch = currentUrl.match(/\/projects\/([0-9a-f-]+)/);
      if (projectMatch) {
        const projectId = projectMatch[1];
        // Fetch BOQ list for this project from the page context
        const boqId = await page.evaluate(async (pid) => {
          try {
            const resp = await fetch(`/api/v1/boqs?project_id=${pid}`);
            const data = await resp.json();
            if (data && data.length > 0) return data[0].id;
          } catch { /* ignore */ }
          return null;
        }, projectId);

        if (boqId) {
          console.log(`Found BOQ ID: ${boqId}, navigating directly`);
          await page.goto(`/boq/${boqId}`);
          await page.waitForLoadState('networkidle').catch(() => {});
          await page.waitForTimeout(3000);
          await dismissOnboardingTour(page);
        }
      }

      // Another fallback: try the /boq list page
      if (!page.url().match(/\/boq\/[0-9a-f-]{36}/)) {
        await page.goto('/boq');
        await page.waitForLoadState('networkidle').catch(() => {});
        await page.waitForTimeout(2000);
        await dismissOnboardingTour(page);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/05-boq-list-page.png`, fullPage: true });

        // Try clicking any BOQ item
        const anyBoqLink = page.locator('a[href*="/boq/"]').first();
        if (await anyBoqLink.count() > 0) {
          await anyBoqLink.click({ force: true });
          await page.waitForLoadState('networkidle').catch(() => {});
          await page.waitForTimeout(3000);
          await dismissOnboardingTour(page);
        }
      }
    }

    console.log(`BOQ Editor URL: ${page.url()}`);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/06-boq-editor-initial.png`, fullPage: true });

    // ═══════════════════════════════════════════════════════════════════
    // STEP 4: WAIT FOR BOQ EDITOR TO FULLY LOAD
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 4: WAIT FOR EDITOR ===');

    // Wait for AG Grid or main content
    await page.waitForSelector('.ag-root-wrapper, .ag-root, [class*="ag-"]', { timeout: 15000 })
      .catch(() => console.log('WARNING: AG Grid not found'));
    await page.waitForTimeout(2000);

    // Set viewport to 1920x1080 for comprehensive screenshots
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/07-boq-editor-full-1920.png`, fullPage: true });
    await page.screenshot({ path: `${SCREENSHOT_DIR}/08-boq-editor-viewport.png` });

    // ═══════════════════════════════════════════════════════════════════
    // STEP 5: TOOLBAR BUTTONS INVENTORY
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 5: TOOLBAR BUTTONS ===');

    const allButtons = page.locator('button:visible');
    const buttonCount = await allButtons.count();
    console.log(`Visible buttons on page: ${buttonCount}`);

    const buttonInfo: string[] = [];
    for (let i = 0; i < buttonCount; i++) {
      const text = (await allButtons.nth(i).textContent())?.trim() || '';
      const ariaLabel = (await allButtons.nth(i).getAttribute('aria-label')) || '';
      const title = (await allButtons.nth(i).getAttribute('title')) || '';
      const disabled = await allButtons.nth(i).isDisabled();
      if (text || ariaLabel || title) {
        buttonInfo.push(`[${i}] text="${text.substring(0, 60)}" aria="${ariaLabel}" title="${title}" disabled=${disabled}`);
      }
    }
    console.log('Button inventory:\n' + buttonInfo.join('\n'));

    // Capture toolbar area
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/09-top-toolbar.png`,
      clip: { x: 0, y: 0, width: 1920, height: 250 },
    });

    // ═══════════════════════════════════════════════════════════════════
    // STEP 6: AG GRID ANALYSIS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 6: AG GRID ANALYSIS ===');

    const agGrid = page.locator('.ag-root-wrapper').first();
    const hasAgGrid = (await agGrid.count()) > 0;
    console.log(`AG Grid present: ${hasAgGrid}`);

    if (hasAgGrid) {
      await agGrid.screenshot({ path: `${SCREENSHOT_DIR}/10-ag-grid.png` });

      // Headers
      const headers = page.locator('.ag-header-cell');
      const headerCount = await headers.count();
      const headerTexts: string[] = [];
      for (let i = 0; i < headerCount; i++) {
        headerTexts.push((await headers.nth(i).textContent())?.trim() || '');
      }
      console.log(`Grid headers (${headerCount}): ${headerTexts.join(' | ')}`);

      // Rows
      const rows = page.locator('.ag-row');
      const rowCount = await rows.count();
      console.log(`Grid rows: ${rowCount}`);

      if (rowCount > 0) {
        await rows.first().screenshot({ path: `${SCREENSHOT_DIR}/11-first-row.png` });
        for (let i = 0; i < Math.min(rowCount, 3); i++) {
          console.log(`  Row ${i}: "${(await rows.nth(i).textContent())?.substring(0, 120)}"`);
        }
      }

      // Empty overlay
      const overlay = page.locator('.ag-overlay-no-rows-wrapper');
      if (await overlay.count() > 0) {
        console.log(`Grid overlay text: "${await overlay.textContent()}"`);
      }
    } else {
      // Check for any table/grid elements as fallback
      const tables = page.locator('table');
      console.log(`Tables: ${await tables.count()}`);
      const divGrid = page.locator('[role="grid"], [role="treegrid"]');
      console.log(`Grid-role elements: ${await divGrid.count()}`);
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 7: AI FEATURE BUTTONS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 7: AI FEATURE BUTTONS ===');

    // Search for all AI-related buttons
    const aiSelectors = {
      'Suggest Rate': 'button:has-text("Suggest Rate"), button:has-text("suggest rate")',
      'Classify': 'button:has-text("Classify"), button:has-text("classify")',
      'Anomalies': 'button:has-text("Anomal"), button:has-text("anomal")',
      'AI Chat': 'button:has-text("AI"), button:has-text("Chat")',
      'Auto-classify': 'button:has-text("Auto")',
      'Generate': 'button:has-text("Generate")',
      'Smart': 'button:has-text("Smart")',
    };

    for (const [name, sel] of Object.entries(aiSelectors)) {
      const btn = page.locator(sel);
      const count = await btn.count();
      if (count > 0) {
        let visibleCount = 0;
        for (let i = 0; i < count; i++) {
          if (await btn.nth(i).isVisible()) visibleCount++;
        }
        console.log(`AI button "${name}": ${count} found, ${visibleCount} visible`);
      }
    }

    // Test each AI button that is visible
    // Suggest Rate
    const suggestRateBtn = page.locator('button:visible:has-text("Suggest Rate")');
    if (await suggestRateBtn.count() > 0) {
      console.log('--- Testing Suggest Rate ---');
      const disabled = await suggestRateBtn.first().isDisabled();
      console.log(`  Disabled: ${disabled}`);
      await suggestRateBtn.first().scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SCREENSHOT_DIR}/12-suggest-rate.png` });

      if (!disabled) {
        await suggestRateBtn.first().click({ force: true });
        await page.waitForTimeout(3000);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/13-after-suggest-rate.png`, fullPage: true });
      }
    } else {
      console.log('Suggest Rate button: NOT VISIBLE');
    }

    // Classify
    const classifyBtn = page.locator('button:visible:has-text("Classify")');
    if (await classifyBtn.count() > 0) {
      console.log('--- Testing Classify ---');
      const disabled = await classifyBtn.first().isDisabled();
      console.log(`  Disabled: ${disabled}`);
      await classifyBtn.first().scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SCREENSHOT_DIR}/14-classify.png` });

      if (!disabled) {
        await classifyBtn.first().click({ force: true });
        await page.waitForTimeout(3000);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/15-after-classify.png`, fullPage: true });
      }
    } else {
      console.log('Classify button: NOT VISIBLE');
    }

    // Check Anomalies
    const anomalyBtn = page.locator('button:visible:has-text("Anomal"), button:visible:has-text("Check Anomal")');
    if (await anomalyBtn.count() > 0) {
      console.log('--- Testing Anomalies ---');
      const disabled = await anomalyBtn.first().isDisabled();
      console.log(`  Disabled: ${disabled}`);
      await anomalyBtn.first().scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SCREENSHOT_DIR}/16-anomalies.png` });

      if (!disabled) {
        await anomalyBtn.first().click({ force: true });
        await page.waitForTimeout(3000);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/17-after-anomalies.png`, fullPage: true });
      }
    } else {
      console.log('Anomalies button: NOT VISIBLE');
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 8: RIGHT SIDEBAR / PANELS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 8: RIGHT SIDEBAR PANELS ===');

    // Screenshot right 40% of screen
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/18-right-side.png`,
      clip: { x: 1920 * 0.6, y: 0, width: 1920 * 0.4, height: 1080 },
    });

    // Check specific panel headings
    const panelNames = [
      'Cost Breakdown', 'Resource Summary', 'Activity', 'Quality', 'Tips',
      'Version', 'Comment', 'Classification', 'Sensitivity', 'Risk',
      'AI Chat', 'Estimate Class', 'Summary',
    ];

    for (const name of panelNames) {
      const elem = page.locator(`text="${name}"`);
      const found = await elem.count() > 0;
      if (found) {
        const visible = await elem.first().isVisible();
        console.log(`Panel "${name}": found=${found}, visible=${visible}`);
      }
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 9: ADD POSITION
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 9: ADD POSITION ===');

    const addBtn = page.locator('button:visible:has-text("Add Position"), button:visible:has-text("Add Row"), button:visible:has-text("position")').first();
    if (await addBtn.count() > 0) {
      const btnText = await addBtn.textContent();
      console.log(`Found Add button: "${btnText?.trim()}"`);

      const rowsBefore = await page.locator('.ag-row').count();
      console.log(`Rows before: ${rowsBefore}`);

      await addBtn.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `${SCREENSHOT_DIR}/19-add-position-btn.png` });

      await addBtn.click({ force: true });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/20-after-add-position.png`, fullPage: true });

      const rowsAfter = await page.locator('.ag-row').count();
      console.log(`Rows after: ${rowsAfter} (${rowsAfter > rowsBefore ? 'ADDED' : 'NO CHANGE'})`);
    } else {
      console.log('No Add Position button found');

      // Check for floating action button
      const fab = page.locator('button[class*="fixed"], button[class*="bottom"]');
      if (await fab.count() > 0) {
        console.log('Found potential FAB buttons');
      }
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 10: EXPORT BUTTONS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 10: EXPORT BUTTONS ===');

    const exportKeywords = ['Export', 'PDF', 'Excel', 'GAEB', 'Download', 'CSV'];
    for (const kw of exportKeywords) {
      const btn = page.locator(`button:visible:has-text("${kw}")`);
      const count = await btn.count();
      if (count > 0) {
        const text = await btn.first().textContent();
        console.log(`Export "${kw}": found, text="${text?.trim()}"`);
      }
    }

    // Click main Export button if exists
    const exportBtn = page.locator('button:visible:has-text("Export")').first();
    if (await exportBtn.count() > 0) {
      await exportBtn.click({ force: true });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/21-export-dropdown.png`, fullPage: true });
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 11: INLINE CELL EDITING
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 11: INLINE EDITING ===');

    if (hasAgGrid) {
      // Try double-clicking description cell
      const descCell = page.locator('.ag-cell[col-id="description"]').first();
      if (await descCell.count() > 0) {
        await descCell.dblclick();
        await page.waitForTimeout(1000);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/22-desc-editing.png`, fullPage: true });
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
      }

      // Try quantity cell
      const qtyCell = page.locator('.ag-cell[col-id="quantity"]').first();
      if (await qtyCell.count() > 0) {
        await qtyCell.dblclick();
        await page.waitForTimeout(1000);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/23-qty-editing.png`, fullPage: true });
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
      }

      // Try unit_rate cell
      const rateCell = page.locator('.ag-cell[col-id="unit_rate"]').first();
      if (await rateCell.count() > 0) {
        await rateCell.dblclick();
        await page.waitForTimeout(1000);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/24-rate-editing.png`, fullPage: true });
        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
      }
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 12: BREADCRUMB
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 12: BREADCRUMB ===');

    const breadcrumb = page.locator('nav[aria-label*="bread" i], [class*="breadcrumb" i], [class*="Breadcrumb"]');
    if (await breadcrumb.count() > 0) {
      await breadcrumb.first().screenshot({ path: `${SCREENSHOT_DIR}/25-breadcrumb.png` });
      console.log(`Breadcrumb: "${(await breadcrumb.first().textContent())?.trim()}"`);
    } else {
      console.log('No breadcrumb found');
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 13: SUMMARY / TOTALS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 13: SUMMARY / TOTALS ===');

    // Look for summary section at bottom
    const summaryArea = page.locator(':has-text("Net Total"), :has-text("Gross Total"), :has-text("Subtotal"), :has-text("Grand Total")');
    const summaryCount = await summaryArea.count();
    console.log(`Summary/total elements: ${summaryCount}`);

    // Screenshot bottom of page
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/26-bottom-area.png`,
      clip: { x: 0, y: 1080 * 0.7, width: 1920, height: 1080 * 0.3 },
    });

    // ═══════════════════════════════════════════════════════════════════
    // STEP 14: UNDO/REDO
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 14: UNDO/REDO ===');

    const undoBtn = page.locator('button:visible:has-text("Undo"), button:visible[title*="Undo" i], button:visible[aria-label*="undo" i]');
    const redoBtn = page.locator('button:visible:has-text("Redo"), button:visible[title*="Redo" i], button:visible[aria-label*="redo" i]');
    console.log(`Undo button: ${await undoBtn.count() > 0}`);
    console.log(`Redo button: ${await redoBtn.count() > 0}`);

    // Test Ctrl+Z
    await page.keyboard.press('Control+z');
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/27-after-undo.png` });

    // ═══════════════════════════════════════════════════════════════════
    // STEP 15: SEARCH/FILTER IN GRID
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 15: SEARCH/FILTER ===');

    const searchInput = page.locator('input[placeholder*="search" i], input[placeholder*="filter" i], input[type="search"]').first();
    if (await searchInput.count() > 0) {
      console.log('Search input found');
      await searchInput.scrollIntoViewIfNeeded();
      await searchInput.fill('Beton');
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/28-search-beton.png`, fullPage: true });
      await searchInput.fill('');
      await page.waitForTimeout(500);
    } else {
      console.log('No search input found');
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 16: COST DATABASE MODAL
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 16: COST DATABASE MODAL ===');

    const costDbBtn = page.locator('button:visible:has-text("Cost Database"), button:visible:has-text("Browse Cost"), button:visible:has-text("Search Cost")');
    if (await costDbBtn.count() > 0) {
      console.log('Cost Database button found');
      await costDbBtn.first().click({ force: true });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/29-cost-db-modal.png`, fullPage: true });
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);
    } else {
      console.log('Cost Database button: NOT FOUND');
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 17: ASSEMBLY PICKER MODAL
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 17: ASSEMBLY PICKER ===');

    const assemblyBtn = page.locator('button:visible:has-text("From Assembly")');
    if (await assemblyBtn.count() > 0) {
      console.log('Assembly button found');
      await assemblyBtn.first().click({ force: true });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/30-assembly-modal.png`, fullPage: true });

      // Close modal by removing it from DOM (safest approach)
      await page.evaluate(() => {
        document.querySelectorAll('.fixed.inset-0').forEach(el => el.remove());
      });
      await page.waitForTimeout(500);
    } else {
      console.log('Assembly button: NOT FOUND');
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 18: VERSION HISTORY
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 18: VERSION HISTORY ===');

    const versionBtn = page.locator('button:visible:has-text("Version"), button:visible:has-text("History")');
    if (await versionBtn.count() > 0) {
      console.log('Version/History button found');
      await versionBtn.first().click({ force: true });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/31-version-history.png`, fullPage: true });
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);
    } else {
      console.log('Version/History button: NOT FOUND');
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 19: RIGHT-CLICK CONTEXT MENU
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 19: CONTEXT MENU ===');

    if (hasAgGrid) {
      // Ensure no modal is blocking - remove any overlay from DOM
      await page.evaluate(() => {
        document.querySelectorAll('.fixed.inset-0, [class*="fixed inset-0"]').forEach(el => el.remove());
      });
      await page.waitForTimeout(500);

      const firstRow = page.locator('.ag-row').first();
      if (await firstRow.count() > 0) {
        await firstRow.click({ button: 'right', force: true });
        await page.waitForTimeout(1000);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/32-context-menu.png`, fullPage: true });

        const contextMenu = page.locator('.ag-menu, [class*="context-menu" i], [role="menu"]');
        console.log(`Context menu visible: ${await contextMenu.count() > 0}`);
        if (await contextMenu.count() > 0) {
          const menuText = await contextMenu.first().textContent();
          console.log(`Context menu items: "${menuText?.substring(0, 200)}"`);
        }

        await page.keyboard.press('Escape');
        await page.waitForTimeout(300);
      }
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 20: SECTION COLLAPSE/EXPAND
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 20: SECTION COLLAPSE/EXPAND ===');

    const groupRows = page.locator('.ag-group-expanded, .ag-group-contracted');
    console.log(`Expandable group rows: ${await groupRows.count()}`);

    if (await groupRows.count() > 0) {
      await groupRows.first().click({ force: true });
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/33-section-toggled.png`, fullPage: true });
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 21: COLUMN SORT
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 21: COLUMN SORT ===');

    if (hasAgGrid) {
      const sortableHeaders = page.locator('.ag-header-cell-sortable');
      console.log(`Sortable columns: ${await sortableHeaders.count()}`);

      if (await sortableHeaders.count() > 0) {
        await sortableHeaders.first().click();
        await page.waitForTimeout(500);
        await page.screenshot({ path: `${SCREENSHOT_DIR}/34-after-sort.png`, fullPage: true });
      }
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 22: BATCH SELECTION
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 22: BATCH SELECTION ===');

    const checkboxes = page.locator('.ag-selection-checkbox, .ag-checkbox input[type="checkbox"]');
    console.log(`Selection checkboxes: ${await checkboxes.count()}`);

    // ═══════════════════════════════════════════════════════════════════
    // STEP 23: TOASTS / NOTIFICATIONS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 23: TOASTS ===');

    const toasts = page.locator('[class*="toast" i], [role="status"], [class*="notification" i]');
    const toastCount = await toasts.count();
    let visibleToasts = 0;
    for (let i = 0; i < toastCount; i++) {
      if (await toasts.nth(i).isVisible()) {
        visibleToasts++;
        const text = await toasts.nth(i).textContent();
        console.log(`Toast ${i}: "${text?.trim()}"`);
      }
    }
    console.log(`Toasts: ${toastCount} total, ${visibleToasts} visible`);

    // ═══════════════════════════════════════════════════════════════════
    // STEP 24: RESPONSIVE TESTS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 24: RESPONSIVE ===');

    // Tablet
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/35-tablet.png`, fullPage: true });

    // Mobile
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/36-mobile.png`, fullPage: true });

    // Back to desktop
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(1000);

    // ═══════════════════════════════════════════════════════════════════
    // STEP 25: ERROR STATES
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 25: ERROR STATES ===');

    const errorElems = page.locator('[class*="error" i]:visible, [role="alert"]:visible, .text-red-500:visible, .text-red-600:visible');
    const errCount = await errorElems.count();
    console.log(`Visible error elements: ${errCount}`);

    for (let i = 0; i < Math.min(errCount, 5); i++) {
      const text = await errorElems.nth(i).textContent();
      console.log(`  Error ${i}: "${text?.substring(0, 200)}"`);
      try {
        await errorElems.nth(i).screenshot({ path: `${SCREENSHOT_DIR}/37-error-${i}.png` });
      } catch { /* */ }
    }

    // Loading spinners still visible
    const spinners = page.locator('.animate-spin:visible, .animate-pulse:visible, [class*="skeleton" i]:visible');
    console.log(`Visible spinners/loading: ${await spinners.count()}`);

    // ═══════════════════════════════════════════════════════════════════
    // STEP 26: KEYBOARD SHORTCUTS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 26: KEYBOARD SHORTCUTS ===');

    // Ctrl+S
    await page.keyboard.press('Control+s');
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/38-after-ctrl-s.png` });

    // ═══════════════════════════════════════════════════════════════════
    // STEP 27: RECALCULATE
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 27: RECALCULATE ===');

    const recalcBtn = page.locator('button:visible:has-text("Recalc"), button:visible:has-text("recalc"), button:visible:has-text("Refresh")');
    if (await recalcBtn.count() > 0) {
      console.log('Recalculate button found');
      await recalcBtn.first().click({ force: true });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/39-after-recalc.png`, fullPage: true });
    } else {
      console.log('Recalculate button: NOT FOUND');
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 28: FINAL SCREENSHOTS
    // ═══════════════════════════════════════════════════════════════════
    console.log('=== STEP 28: FINAL SCREENSHOTS ===');

    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/40-final-full.png`, fullPage: true });
    await page.screenshot({ path: `${SCREENSHOT_DIR}/41-final-viewport.png` });

    // Scroll to see all content
    await page.evaluate(() => window.scrollTo(0, 999999));
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/42-scrolled-bottom.png` });

    // ═══════════════════════════════════════════════════════════════════
    // SUMMARY
    // ═══════════════════════════════════════════════════════════════════
    console.log('\n\n======================================================================');
    console.log('QA TEST SUMMARY');
    console.log('======================================================================');
    console.log(`Final URL: ${page.url()}`);
    console.log(`Console errors: ${consoleErrors.length}`);
    consoleErrors.forEach((e) => console.log(`  ERR: ${e.substring(0, 400)}`));
    console.log(`Console warnings: ${consoleWarnings.length}`);
    consoleWarnings.slice(0, 5).forEach((w) => console.log(`  WARN: ${w.substring(0, 200)}`));
    console.log(`Network errors (4xx/5xx): ${networkErrors.length}`);
    networkErrors.forEach((e) => console.log(`  NET: ${e}`));
    console.log('======================================================================');
  });
});
