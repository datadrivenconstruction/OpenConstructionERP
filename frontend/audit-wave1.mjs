// Wave 1 audit — wide browser walkthrough across the main routes.
// Captures: screenshots, console errors, network 4xx/5xx, route load failures.
// Output: qa-shots/audit-wave-1/  +  qa-shots/audit-wave-1/findings.json
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = 'http://127.0.0.1:8090';
const API = `${BASE}/api/v1`;
const SHOTS = path.resolve('qa-shots/audit-wave-1');
fs.mkdirSync(SHOTS, { recursive: true });

const findings = {
  startedAt: new Date().toISOString(),
  routes: [],
  consoleErrors: [],
  networkErrors: [],
  pageErrors: [],
};

async function tryLogin() {
  const r = await fetch(`${API}/users/auth/login/`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email: 'v19-e2e@openestimate.com', password: 'OpenEstimate2024!' }),
  });
  if (!r.ok) throw new Error('login failed: ' + r.status);
  return (await r.json()).access_token;
}

async function listProjects(token) {
  const r = await fetch(`${API}/projects/`, { headers: { Authorization: `Bearer ${token}` } });
  return r.ok ? r.json() : [];
}

async function shoot(page, name) {
  const file = path.join(SHOTS, `${name}.png`);
  try {
    await page.screenshot({ path: file, fullPage: true });
  } catch {
    await page.screenshot({ path: file }).catch(() => {});
  }
  return file;
}

async function visit(page, slug, route, opts = {}) {
  const url = `${BASE}${route}`;
  const start = Date.now();
  let status = 'ok';
  let error = null;
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 });
    if (opts.wait) await page.waitForTimeout(opts.wait);
    else await page.waitForTimeout(1500);
  } catch (e) {
    status = 'navigation-error';
    error = String(e?.message || e);
  }
  const file = await shoot(page, `${slug}`);
  const elapsed = Date.now() - start;
  console.log(`  → ${route}  (${status}, ${elapsed}ms)  ${path.basename(file)}`);
  findings.routes.push({ slug, route, url, status, error, elapsed, screenshot: file });
}

const ROUTES = [
  ['00-dashboard', '/'],
  ['01-projects', '/projects'],
  ['02-files', '/files'],
  ['03-files-document', '/files?kind=document'],
  ['04-files-bim', '/files?kind=bim_model'],
  ['05-files-dwg', '/files?kind=dwg_drawing'],
  ['06-files-photo', '/files?kind=photo'],
  ['07-boq', '/boq'],
  ['08-takeoff', '/takeoff'],
  ['09-dwg', '/dwg'],
  ['10-bim', '/bim'],
  ['11-bim-rules', '/bim-rules'],
  ['12-costs', '/costs'],
  ['13-assemblies', '/assemblies'],
  ['14-resources', '/resources'],
  ['15-quantity-rules', '/quantity-rules'],
  ['16-ai-estimate', '/ai-estimate'],
  ['17-ai-cost-advisor', '/ai-cost-advisor'],
  ['18-estimation-dashboard', '/estimation-dashboard'],
  ['19-ai-chat', '/ai-chat'],
  ['20-settings', '/settings'],
  ['21-modules', '/modules'],
  ['22-users', '/users'],
  ['23-about', '/about'],
];

(async () => {
  const token = await tryLogin();
  const projects = await listProjects(token);
  if (!projects.length) {
    console.log('no projects — skipping project-scoped routes');
  }
  const project = projects[0];
  console.log(`logged in, projects=${projects.length}, using=${project?.name || 'none'}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  // Capture console + network issues
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (text.includes('favicon') || text.includes('extension')) return;
      findings.consoleErrors.push({ url: page.url(), text });
    }
  });
  page.on('pageerror', (err) => {
    findings.pageErrors.push({ url: page.url(), error: String(err?.message || err) });
  });
  page.on('response', (r) => {
    const s = r.status();
    const u = r.url();
    if (s >= 400 && !u.includes('favicon')) {
      findings.networkErrors.push({ pageUrl: page.url(), status: s, url: u });
    }
  });

  // Bootstrap auth + active project
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(
    ({ token, project }) => {
      localStorage.setItem('oe_access_token', token);
      if (project) {
        localStorage.setItem(
          'oe_active_project',
          JSON.stringify({ id: project.id, name: project.name, boqId: project.default_boq_id || null }),
        );
      }
    },
    { token, project },
  );

  for (const [slug, route] of ROUTES) {
    await visit(page, slug, route);
  }

  findings.endedAt = new Date().toISOString();
  fs.writeFileSync(path.join(SHOTS, 'findings.json'), JSON.stringify(findings, null, 2));
  console.log(
    `\nfindings: console=${findings.consoleErrors.length} pageerr=${findings.pageErrors.length} net=${findings.networkErrors.length} routes=${findings.routes.length}`,
  );

  await browser.close();
})().catch((e) => {
  console.error('FATAL:', e);
  process.exit(1);
});
