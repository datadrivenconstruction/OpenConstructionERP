/**
 * OpenEstimate — Full UI/UX Deep Test Suite
 * ==========================================
 * Run: npx playwright test e2e/full-ux-test.spec.ts --headed
 */

import { test, expect, type Page } from '@playwright/test';

const BASE = 'http://localhost:5174';

// ── Helpers ──────────────────────────────────────────────────────────

async function login(page: Page) {
  await page.goto(`${BASE}/login`);
  // Pre-set tour as completed BEFORE login to prevent it from appearing
  await page.evaluate(() => localStorage.setItem('oe_tour_completed', 'true'));
  await page.getByRole('textbox', { name: 'Email' }).fill('demo@openestimator.io');
  await page.getByRole('textbox', { name: 'Password' }).fill('DemoPass1234!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL(`${BASE}/`);
  // Double-check tour dismissal
  await page.evaluate(() => localStorage.setItem('oe_tour_completed', 'true'));
  const skipBtn = page.getByTestId('onboarding-skip');
  if (await skipBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await skipBtn.click();
  }
  await page.waitForTimeout(1000);
}

// ══════════════════════════════════════════════════════════════════════
//  1. LOGIN & AUTH
// ══════════════════════════════════════════════════════════════════════

test.describe('1. Authentication', () => {
  test('Login page renders correctly', async ({ page }) => {
    await page.goto(`${BASE}/login`);
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Email' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Password' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByText('Create account')).toBeVisible();
    await expect(page.getByText('demo@openestimator.io')).toBeVisible();
  });

  test('Login with demo credentials works', async ({ page }) => {
    await login(page);
    expect(page.url()).toBe(`${BASE}/`);
  });

  test('Wrong password stays on login', async ({ page }) => {
    await page.goto(`${BASE}/login`);
    await page.getByRole('textbox', { name: 'Email' }).fill('demo@openestimator.io');
    await page.getByRole('textbox', { name: 'Password' }).fill('wrongpassword');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.waitForTimeout(2000);
    expect(page.url()).toContain('login');
  });
});

// ══════════════════════════════════════════════════════════════════════
//  2. DASHBOARD
// ══════════════════════════════════════════════════════════════════════

test.describe('2. Dashboard', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('Dashboard KPIs visible', async ({ page }) => {
    const main = page.locator('main');
    await expect(main.getByText('Total Value')).toBeVisible({ timeout: 5000 });
    await expect(main.getByText('Active Estimates')).toBeVisible();
    await expect(main.getByText('Quality Score')).toBeVisible();
  });

  test('Quick Actions buttons', async ({ page }) => {
    await page.waitForTimeout(3000);
    const main = page.locator('main');
    await expect(main.getByRole('button', { name: 'New Project' }).first()).toBeVisible({ timeout: 10000 });
  });

  test('System Status shows modules and rules', async ({ page }) => {
    await page.waitForTimeout(2000);
    const main = page.locator('main');
    await expect(main.getByText('Modules loaded')).toBeVisible({ timeout: 5000 });
    await expect(main.getByText('Validation rules')).toBeVisible();
    await expect(main.getByText('Languages')).toBeVisible();
  });

  test('Recent Projects list', async ({ page }) => {
    await expect(page.locator('main').getByText('Recent Projects')).toBeVisible({ timeout: 5000 });
  });
});

// ══════════════════════════════════════════════════════════════════════
//  3. PROJECTS
// ══════════════════════════════════════════════════════════════════════

test.describe('3. Projects', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/projects`);
    await page.waitForTimeout(3000);
  });

  test('Project list loads', async ({ page }) => {
    await expect(page.locator('main').getByText('Total Projects')).toBeVisible({ timeout: 10000 });
  });

  test('Region and currency badges', async ({ page }) => {
    await page.waitForTimeout(2000);
    await expect(page.getByText('DIN 276').first()).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('EUR').first()).toBeVisible();
  });

  test('Search projects', async ({ page }) => {
    const input = page.getByPlaceholder('Search');
    await input.fill('Berlin');
    await page.waitForTimeout(1000);
    const results = await page.getByRole('heading', { level: 3 }).filter({ hasText: 'Berlin' }).count();
    expect(results).toBeGreaterThan(0);
  });

  test('Sort buttons work', async ({ page }) => {
    await page.waitForTimeout(2000);
    const nameBtn = page.locator('main').getByRole('button', { name: 'Name' });
    if (await nameBtn.isVisible()) {
      await nameBtn.click();
      await page.waitForTimeout(500);
    }
  });

  test('New Project button navigates', async ({ page }) => {
    await page.locator('main').getByRole('button', { name: 'New Project' }).click();
    await page.waitForURL('**/projects/new**', { timeout: 5000 });
  });
});

// ══════════════════════════════════════════════════════════════════════
//  4. BOQ EDITOR
// ══════════════════════════════════════════════════════════════════════

test.describe('4. BOQ Editor', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/boq`);
    await page.waitForTimeout(3000);
  });

  test('BOQ list page loads', async ({ page }) => {
    // Page should load and not redirect to login
    await page.waitForTimeout(3000);
    expect(page.url()).toContain('/boq');
    // Either shows stats or "New Estimate" button
    const hasContent = await page.locator('main').getByRole('button', { name: 'New Estimate' }).isVisible({ timeout: 15000 }).catch(() => false);
    expect(hasContent).toBe(true);
  });

  test('Open BOQ editor and see toolbar', async ({ page }) => {
    await page.waitForTimeout(3000);
    const boqCard = page.locator('main').locator('[cursor="pointer"]').first();
    if (await boqCard.isVisible({ timeout: 5000 }).catch(() => false)) {
      await boqCard.click();
      await page.waitForTimeout(8000);
      expect(page.url()).toMatch(/\/boq\//);
      await expect(page.getByRole('button', { name: 'Add Position' }).first()).toBeVisible({ timeout: 20000 });
    }
  });

  test('Validate stays on page (no redirect)', async ({ page }) => {
    await page.waitForTimeout(3000);
    const boqCard = page.locator('main').locator('[cursor="pointer"]').first();
    if (!await boqCard.isVisible({ timeout: 5000 }).catch(() => false)) return;
    await boqCard.click();
    await page.waitForSelector('button:has-text("Add Position")', { timeout: 20000 });
    const url = page.url();
    // Click validate (the button with shield icon)
    const validateArea = page.locator('button').filter({ hasText: /Validate|Checking/ }).first();
    if (await validateArea.isVisible({ timeout: 3000 }).catch(() => false)) {
      await validateArea.click();
      await page.waitForTimeout(3000);
      // Must still be on the same BOQ page
      expect(page.url()).toBe(url);
      expect(page.url()).not.toContain('/validation');
    }
  });

  test('Export menu has 4 formats', async ({ page }) => {
    await page.waitForTimeout(3000);
    const boqCard = page.locator('main').locator('[cursor="pointer"]').first();
    if (!await boqCard.isVisible({ timeout: 5000 }).catch(() => false)) return;
    await boqCard.click();
    await page.waitForSelector('button:has-text("Export")', { timeout: 20000 });
    await page.getByRole('button', { name: 'Export' }).first().click();
    await page.waitForTimeout(500);
    await expect(page.getByText('Excel (.xlsx)')).toBeVisible();
    await expect(page.getByText('CSV (.csv)')).toBeVisible();
    await expect(page.getByText('PDF')).toBeVisible();
    await expect(page.getByText('GAEB XML')).toBeVisible();
  });

  test('Paste from Excel button exists', async ({ page }) => {
    await page.waitForTimeout(3000);
    const boqCard = page.locator('main').locator('[cursor="pointer"]').first();
    if (!await boqCard.isVisible({ timeout: 5000 }).catch(() => false)) return;
    await boqCard.click();
    await page.waitForSelector('button:has-text("Add Position")', { timeout: 20000 });
    await expect(page.locator('[title*="Paste"]')).toBeVisible({ timeout: 5000 });
  });
});

// ══════════════════════════════════════════════════════════════════════
//  5. AI ESTIMATE
// ══════════════════════════════════════════════════════════════════════

test.describe('5. AI Estimate', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/ai-estimate`);
    await page.waitForTimeout(2000);
  });

  test('Title and subtitle', async ({ page }) => {
    await expect(page.locator('main').getByRole('heading', { name: 'AI Estimate' })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Create an estimate from any source')).toBeVisible();
  });

  test('5 tabs — no CAD', async ({ page }) => {
    await expect(page.getByRole('button', { name: /^Text/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Photo/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /PDF/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Excel/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Paste/ })).toBeVisible();
  });

  test('Text tab inputs', async ({ page }) => {
    await expect(page.locator('textarea')).toBeVisible();
    await expect(page.getByText('Currency')).toBeVisible();
    await expect(page.getByText('Standard')).toBeVisible();
    await expect(page.getByText('Building Type')).toBeVisible();
  });

  test('AI Connected badge', async ({ page }) => {
    await expect(page.getByText('AI Connected')).toBeVisible();
  });
});

// ══════════════════════════════════════════════════════════════════════
//  6. CAD/BIM TAKEOFF
// ══════════════════════════════════════════════════════════════════════

test.describe('6. CAD/BIM Takeoff', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/cad-takeoff`);
    await page.waitForTimeout(2000);
  });

  test('Title is CAD/BIM Takeoff', async ({ page }) => {
    await expect(page.locator('main').getByRole('heading', { name: 'CAD/BIM Takeoff' })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Extract quantities from 3D models')).toBeVisible();
  });

  test('File drop zone and converters', async ({ page }) => {
    await expect(page.getByText('Drop your file here')).toBeVisible();
    await expect(page.getByText('DDC Converter Modules')).toBeVisible();
    await expect(page.getByText('installed')).toBeVisible();
  });
});

// ══════════════════════════════════════════════════════════════════════
//  7. COST DATABASE
// ══════════════════════════════════════════════════════════════════════

test.describe('7. Cost Database', () => {
  test('Page loads', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/costs`);
    await page.waitForTimeout(3000);
    // Should not be redirected to login
    expect(page.url()).toContain('/costs');
  });
});

// ══════════════════════════════════════════════════════════════════════
//  8. SETTINGS
// ══════════════════════════════════════════════════════════════════════

test.describe('8. Settings', () => {
  test('Settings page loads', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/settings`);
    await page.waitForTimeout(2000);
    // Header says Settings
    await expect(page.locator('header').getByText('Settings')).toBeVisible({ timeout: 5000 });
  });
});

// ══════════════════════════════════════════════════════════════════════
//  9. SIDEBAR NAVIGATION
// ══════════════════════════════════════════════════════════════════════

test.describe('9. Sidebar Navigation', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  test('All nav items visible', async ({ page }) => {
    await page.waitForTimeout(2000);
    const sidebar = page.locator('aside, [role="complementary"]').first();
    await expect(sidebar.getByText('Dashboard')).toBeVisible({ timeout: 5000 });
    await expect(sidebar.getByText('Projects')).toBeVisible();
    await expect(sidebar.getByText('Bill of Quantities')).toBeVisible();
    await expect(sidebar.getByText('AI Estimate')).toBeVisible();
    await expect(sidebar.getByText('CAD/BIM Takeoff')).toBeVisible();
    await expect(sidebar.getByText('Cost Database')).toBeVisible();
    await expect(sidebar.getByText('Modules')).toBeVisible();
    await expect(sidebar.getByText('Settings')).toBeVisible();
  });

  test('No Cost Benchmarks or Collaboration', async ({ page }) => {
    const nav = page.locator('nav');
    await expect(nav.getByText('Benchmarks')).toHaveCount(0);
    await expect(nav.getByText('Collaboration')).toHaveCount(0);
  });

  test('Nav links navigate correctly', async ({ page }) => {
    await page.locator('nav').getByText('Projects').click();
    await page.waitForURL('**/projects');
    await page.locator('nav').getByText('AI Estimate').click();
    await page.waitForURL('**/ai-estimate');
    await page.locator('nav').getByText('CAD/BIM Takeoff').click();
    await page.waitForURL('**/cad-takeoff');
  });
});

// ══════════════════════════════════════════════════════════════════════
//  10. ALL PAGES LOAD WITHOUT CONSOLE ERRORS
// ══════════════════════════════════════════════════════════════════════

test.describe('10. All Pages Load', () => {
  test.beforeEach(async ({ page }) => { await login(page); });

  const pages = [
    ['/', 'Dashboard'], ['/projects', 'Projects'], ['/boq', 'BOQ'],
    ['/ai-estimate', 'AI Estimate'], ['/cad-takeoff', 'CAD/BIM'],
    ['/costs', 'Costs'], ['/assemblies', 'Assemblies'], ['/catalog', 'Catalog'],
    ['/schedule', 'Schedule'], ['/5d', '5D Model'], ['/tendering', 'Tendering'],
    ['/validation', 'Validation'], ['/takeoff', 'Takeoff'], ['/modules', 'Modules'],
    ['/settings', 'Settings'], ['/quantities', 'Quantities'],
    ['/sustainability', 'Sustainability'], ['/reports', 'Reports'],
  ];

  for (const [path, name] of pages) {
    test(`${name} (${path}) — no errors`, async ({ page }) => {
      const errors: string[] = [];
      page.on('console', (msg) => {
        if (msg.type() === 'error' && !msg.text().includes('DevTools')) errors.push(msg.text());
      });
      await page.goto(`${BASE}${path}`);
      await page.waitForTimeout(2000);
      expect(page.url()).not.toContain('/login');
      expect(errors).toHaveLength(0);
    });
  }
});
