// Every route in App.tsx that a backend module owns must put the "Data paths"
// button on its page. The runtime test (modulePagesShowDataPaths) mounts only
// the shared header, so it cannot see a page with a hand-made header or a route
// the module map forgot. This one reads the sources: each route is resolved to
// its page file and that file (or a component it imports) must render
// PageHeader, ModuleGuideButton or DataPathsButton, and the route must resolve
// to an owning module. A route that is deliberately without a module or without
// the button is listed below with its reason.

import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { moduleForPath } from '@/features/data-paths/moduleMeta';
import { MODULE_REGISTRY } from '@/modules/_registry';

const SRC = resolve(__dirname, '../..');
const APP = resolve(SRC, 'app/App.tsx');
const BUTTON_TAG = /<(PageHeader|ModuleGuideButton|DataPathsButton)\b/;

/** Routes no backend module owns: the page is platform chrome, not a module. */
const NO_MODULE: Record<string, string> = {
  '/': 'dashboard redirect',
  '/share/:token': 'public share link, no app shell',
  '/buyer-portal/:token': 'public buyer portal, no app shell',
  '/login': 'authentication screen',
  '/login-next': 'authentication screen',
  '/register': 'authentication screen',
  '/auth/oidc/callback': 'authentication callback',
  '/forgot-password': 'authentication screen',
  '/auth/reset': 'authentication screen',
  '/auth/verify-email': 'authentication screen',
  '/onboarding': 'first-run wizard',
  '/onboarding/demo': 'first-run wizard',
  '/projects': 'project list, platform chrome',
  '/projects/new': 'project creation, platform chrome',
  '/projects/:projectId': 'project home, platform chrome',
  '/projects/:projectId/settings': 'project settings, platform chrome',
  '/templates': 'BOQ template library, part of the BOQ editor chrome',
  '/templates/:templateId': 'BOQ template editor',
  '/settings': 'user and platform settings',
  '/about': 'product information',
  '/how-it-works': 'product information',
  '/inside': 'product information',
  '/courses': 'learning area',
  '/videos': 'learning area',
  '/packs': 'solution pack catalogue',
  '/packs/focus': 'solution pack catalogue',
  '/packs/:slug': 'solution pack catalogue',
  '/modules': 'module manager',
  '/modules/developer-guide': 'module manager',
  '/modules/:moduleKey': 'generated module page, owner is the generated module itself',
  '/projects/:projectId/modules/:moduleKey': 'generated module page, owner is the generated module itself',
  '/modules/runtime/:moduleName': 'runtime module host, owner is the hosted module',
  '/setup/databases': 'installation setup',
  '/issues': 'cross-module hub over tasks, RFIs and punch items, no single owner',
  '/field': 'field worker mobile shell, no app shell',
  '/field/:token': 'field worker sign-in link, no app shell',
  '/eac/demo': 'admin-only primitives playground',
  '/styles-lab': 'admin-only design playground',
  '*': 'not-found page',
  '/data-paths': 'the data paths page itself',
  '/data-paths/:module': 'the data paths page itself',
};

/** Owned routes whose page deliberately has no header to hang the button on. */
const NO_BUTTON: Record<string, string> = {
  '/assemblies/new': 'modal dialog over the assemblies list',
  '/projects/:projectId/boq/new': 'creation dialog over the BOQ list',
  '/tendering': 'redirects to the tenders page, which has the button',
  '/rfq-bidding': 'redirects to the tenders page, which has the button',
  '/projects/:projectId/rfq-bidding': 'redirects to the tenders page, which has the button',
  '/tendering/bid/:token': 'public bidder portal, no app shell',
  '/portal/payments': 'external portal, no app shell',
  '/portal/home': 'external portal, no app shell',
  '/accounting-sync/oauth/callback': 'OAuth redirect target, closes itself',
};

function resolveFile(spec: string, from: string): string | null {
  const base = spec.startsWith('@/') ? resolve(SRC, spec.slice(2)) : resolve(dirname(from), spec);
  for (const c of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) if (existsSync(c)) return c;
  return null;
}

const app = readFileSync(APP, 'utf8');

type Table = Map<string, { spec: string; exp: string }>;

/** Component name -> import spec and export name, for static and lazy imports in App.tsx. */
function importTable(): Table {
  const table: Table = new Map();
  for (const m of app.matchAll(/import\s+(?:(\w+)\s*,?\s*)?(?:\{([^}]+)\})?\s*from\s+'([^']+)'/g)) {
    const spec = m[3] ?? '';
    if (m[1]) table.set(m[1], { spec, exp: 'default' });
    for (const part of (m[2] ?? '').split(',')) {
      const [name, alias] = part.trim().split(/\s+as\s+/);
      if (name) table.set(alias ?? name, { spec, exp: name });
    }
  }
  for (const m of app.matchAll(
    /const\s+(\w+)\s*=\s*lazy\(\s*\(\)\s*=>\s*import\(\s*'([^']+)'\s*\)(?:\s*\.then\(\s*\(?\w+\)?\s*=>\s*\(\{\s*default:\s*\w+\.(\w+))?/g,
  )) {
    table.set(m[1] ?? '', { spec: m[2] ?? '', exp: m[3] ?? 'default' });
  }
  return table;
}

/** The file that defines `exp`, following one `export { exp } from './x'` hop through a barrel. */
function definingFile(file: string, exp: string): string {
  const text = readFileSync(file, 'utf8');
  for (const m of text.matchAll(/export\s*\{([^}]+)\}\s*from\s*'([^']+)'/g)) {
    const names = (m[1] ?? '').split(',').map((s) => s.trim().split(/\s+as\s+/).pop());
    if (names.includes(exp)) return resolveFile(m[2] ?? '', file) ?? file;
  }
  return file;
}

function rendersButton(file: string, depth: number, seen: Set<string>): boolean {
  if (seen.has(file)) return false;
  seen.add(file);
  const text = readFileSync(file, 'utf8');
  if (BUTTON_TAG.test(text)) return true;
  if (depth === 0) return false;
  for (const m of text.matchAll(/from\s+'((?:\.|@\/)[^']*)'/g)) {
    const spec = m[1] ?? '';
    if (/shared\/ui|app\/layout/.test(spec)) continue;
    const next = resolveFile(spec, file);
    if (next && rendersButton(next, depth - 1, seen)) return true;
  }
  return false;
}

interface RouteFact {
  path: string;
  tags: string[];
}

/** `<Route path="x" element={...} />`, element text taken with balanced braces. */
function routes(): RouteFact[] {
  const out: RouteFact[] = [];
  for (const m of app.matchAll(/<Route\s+path="([^"]+)"\s+element=\{/g)) {
    let i = (m.index ?? 0) + m[0].length;
    let depth = 1;
    const start = i;
    while (i < app.length && depth > 0) {
      if (app[i] === '{') depth++;
      else if (app[i] === '}') depth--;
      i++;
    }
    const element = app.slice(start, i - 1);
    if (/<Navigate\b/.test(element) && !/<[A-Z]\w*Page\b/.test(element)) continue;
    out.push({ path: m[1] ?? '', tags: [...element.matchAll(/<([A-Z]\w*)/g)].map((t) => t[1] ?? '') });
  }
  return out;
}

const STRUCTURAL = new Set(['P', 'Suspense', 'LoadingScreen', 'AuthedHome', 'Navigate', 'RequireAuth', 'RequiresProject']);

/** Page components behind a tag; a route wrapper defined in App.tsx is followed into its body. */
function pageComponents(tags: string[], table: Table, seen = new Set<string>()): string[] {
  const out: string[] = [];
  for (const tag of tags) {
    if (STRUCTURAL.has(tag) || seen.has(tag)) continue;
    seen.add(tag);
    if (table.has(tag)) {
      out.push(tag);
      continue;
    }
    const def = new RegExp(`\\nfunction ${tag}\\(`).exec(app);
    if (def) {
      const next = app.indexOf('\nfunction ', def.index + 1);
      const body = app.slice(def.index, next === -1 ? undefined : next);
      out.push(...pageComponents([...body.matchAll(/<([A-Z]\w*)/g)].map((t) => t[1] ?? ''), table, seen));
    }
  }
  return out;
}

const table = importTable();
const allRoutes = routes();
const asUrl = (p: string) => p.replace(/:[A-Za-z]+/g, 'x');

describe('every module route in App.tsx carries the Data paths button', () => {
  it('parses a real route table', () => {
    expect(allRoutes.length).toBeGreaterThan(250);
  });

  it('maps every route to a backend module unless it is listed as platform chrome', () => {
    const unmapped = allRoutes
      .filter((r) => !moduleForPath(asUrl(r.path)) && !(r.path in NO_MODULE))
      .map((r) => r.path);
    expect(unmapped, `routes with no owning module (map them in moduleMeta or list them in NO_MODULE)`).toEqual([]);
  });

  it('puts the button in the source of every owned page', { timeout: 120_000 }, () => {
    const missing: string[] = [];
    for (const r of allRoutes) {
      if (!moduleForPath(asUrl(r.path)) || r.path in NO_BUTTON) continue;
      const comps = pageComponents(r.tags, table);
      const ok = comps.some((c) => {
        const { spec, exp } = table.get(c)!;
        const entry = resolveFile(spec, APP);
        if (!entry) return false;
        return rendersButton(definingFile(entry, exp), 3, new Set());
      });
      if (!ok) missing.push(`${r.path} (${comps.join(', ') || 'no page component found'})`);
    }
    expect(missing, 'owned pages without PageHeader, ModuleGuideButton or DataPathsButton').toEqual([]);
  });

  it('keeps the exception lists honest', () => {
    const paths = new Set(allRoutes.map((r) => r.path));
    const stale = [...Object.keys(NO_MODULE), ...Object.keys(NO_BUTTON)].filter((p) => p !== '/' && !paths.has(p));
    expect(stale, 'exceptions for routes that no longer exist').toEqual([]);
    const owned = Object.keys(NO_MODULE).filter((p) => p !== '/' && moduleForPath(asUrl(p)));
    expect(owned, 'listed as module-less but a module owns them').toEqual([]);
    const unowned = Object.keys(NO_BUTTON).filter((p) => !moduleForPath(asUrl(p)));
    expect(unowned, 'listed as button-less but no module owns them').toEqual([]);
  });

  it('gives every plugin menu row an owning module', () => {
    const orphan = MODULE_REGISTRY.flatMap((m) => m.navItems.map((i) => i.to)).filter((to) => !moduleForPath(to));
    expect(orphan).toEqual([]);
  });
});
