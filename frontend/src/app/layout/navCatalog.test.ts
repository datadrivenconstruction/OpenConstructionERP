// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// routeIcons.ts says in its own header that it MIRRORS the nav definitions and
// that the two must be kept in sync by hand. That sentence has been there since
// the map was written and nothing has ever checked it, so this does.
//
// The claim under test is narrow on purpose: for every screen the menu offers,
// asking the route-icon map about that exact path returns the same glyph the
// menu row draws. Where the map has no entry for a path it answers with the
// parent module's icon, which is the behaviour detail routes rely on, so a
// disagreement here is a real one rather than a gap.

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { navGroups } from './navCatalog';
import { getRouteIcon } from './routeIcons';
import { MODULE_REGISTRY } from '@/modules/_registry';
import { CORE_ACTIONS } from '@/app/actions/coreActions';

describe('the screen catalogue and the route-icon map', () => {
  it('agree on the icon for every screen the menu offers', () => {
    const disagreements: string[] = [];
    for (const group of navGroups) {
      for (const item of group.items) {
        const fromMap = getRouteIcon(item.to);
        if (fromMap !== item.icon) {
          disagreements.push(
            `${item.to}: menu draws ${item.icon.displayName ?? item.icon.name}, ` +
            `map answers ${fromMap ? (fromMap.displayName ?? fromMap.name) : 'nothing'}`,
          );
        }
      }
    }
    expect(disagreements).toEqual([]);
  });

  it('gives every screen a route, a label key and an icon', () => {
    const broken: string[] = [];
    for (const group of navGroups) {
      for (const item of group.items) {
        if (!item.to.startsWith('/')) broken.push(`${item.labelKey}: route ${item.to}`);
        if (!item.labelKey) broken.push(`${item.to}: no label key`);
        if (!item.icon) broken.push(`${item.to}: no icon`);
      }
    }
    expect(broken).toEqual([]);
  });

  it('lists each route once, so a screen has one home in the menu', () => {
    const seen = new Map<string, string>();
    const twice: string[] = [];
    for (const group of navGroups) {
      for (const item of group.items) {
        const first = seen.get(item.to);
        if (first) twice.push(`${item.to} in both ${first} and ${group.id}`);
        else seen.set(item.to, group.id);
      }
    }
    expect(twice).toEqual([]);
  });
});

// A menu row and the screen behind it live in different files, and one of them
// can be switched off while the app runs. Routes reach the router from two
// places: the static <Route> list in App.tsx, and the manifests under
// src/modules, which ModuleRoutes mounts only for modules that are enabled.
// The sidebar, meanwhile, hides a row only when the row names a module. So a
// row whose screen is module-owned and that names no module survives its own
// route being unmounted, and the click lands on the catch-all Not Found.
//
// Both sources have to be read together. Checking the menu against App.tsx
// alone reports four working screens as dead, which is how the gap below was
// first mis-diagnosed. App.tsx is read as text rather than imported: importing
// it would pull the entire application into the test worker.
//
// Resolved from the working directory rather than `import.meta.url`, which this
// vitest config rewrites to a bare drive root on Windows. Runs from `frontend/`
// under `npm test` and from the repo root under a workspace run.
const APP_CANDIDATES = [
  resolve(process.cwd(), 'src/app/App.tsx'),
  resolve(process.cwd(), 'frontend/src/app/App.tsx'),
];
const APP_PATH = APP_CANDIDATES.find(existsSync);
if (!APP_PATH) throw new Error(`cannot find App.tsx, looked in ${APP_CANDIDATES.join(' and ')}`);
const APP_SOURCE = readFileSync(APP_PATH, 'utf8');
const staticRoutes = new Set<string>();
for (const match of APP_SOURCE.matchAll(/<Route\s[^>]*?path=["']([^"']+)["']/g)) {
  if (match[1]) staticRoutes.add(match[1]);
}

// A menu target and a manifest path may both carry a query string
// (`/takeoff?tab=measurements`); the router matches on the path in front of it.
const bare = (path: string): string => path.split(/[?#]/)[0] ?? path;

const moduleRoutes = new Map<string, string>();
for (const manifest of MODULE_REGISTRY) {
  for (const route of manifest.routes) moduleRoutes.set(bare(route.path), manifest.id);
}

const navItems = navGroups.flatMap((group) => group.items);

describe('the screen catalogue and the routes that mount those screens', () => {
  it('offers no screen the router cannot mount', () => {
    // If the regex above ever stops matching, every row looks dead at once;
    // say so plainly instead of reporting the whole menu as broken.
    expect(staticRoutes.size).toBeGreaterThan(100);

    const dead: string[] = [];
    for (const item of navItems) {
      const path = bare(item.to);
      if (!staticRoutes.has(path) && !moduleRoutes.has(path)) {
        dead.push(`${item.to} (${item.labelKey}): no <Route> in App.tsx and no module declares it`);
      }
    }
    expect(dead).toEqual([]);
  });

  it('names the module behind a screen that only that module provides', () => {
    const silent: string[] = [];
    for (const item of navItems) {
      const path = bare(item.to);
      // A statically routed screen is there whatever the module does, so the
      // row is free to stay. Only a module-owned screen can disappear.
      if (staticRoutes.has(path)) continue;
      const owner = moduleRoutes.get(path);
      if (!owner) continue; // already reported as unmountable above
      if (!item.moduleKey) {
        silent.push(`${item.to}: mounted by module '${owner}' and names no moduleKey, so the row outlives its screen`);
      } else if (item.moduleKey !== owner) {
        silent.push(`${item.to}: names module '${item.moduleKey}' but '${owner}' mounts it`);
      }
    }
    expect(silent).toEqual([]);
  });

  // The sidebar is not the only surface that offers a screen. The command
  // palette runs actions that open pages too, and the same rule has to hold
  // there: a module-owned page is offered only under that module's key. Menu
  // rows become actions straight from navGroups, so the core and module
  // actions with their own path are what is left to check.
  it('lets the command palette offer no page its module has switched off', () => {
    const entries = [
      ...CORE_ACTIONS,
      ...MODULE_REGISTRY.flatMap((m) => (m.actions ?? []).map((a) => ({ ...a, moduleKey: a.moduleKey ?? m.id }))),
    ]
      .filter((a) => a.path && !a.path.includes(':projectId'))
      .map((a) => ({ path: a.path as string, moduleKey: a.moduleKey }));
    expect(entries.length).toBeGreaterThan(3);

    const silent: string[] = [];
    for (const entry of entries) {
      const path = bare(entry.path);
      if (staticRoutes.has(path)) continue;
      const owner = moduleRoutes.get(path);
      if (!owner) {
        silent.push(`${entry.path}: the palette offers a page with no route at all`);
      } else if (entry.moduleKey !== owner) {
        silent.push(`${entry.path}: mounted by module '${owner}', palette says ${entry.moduleKey ? `'${entry.moduleKey}'` : 'nothing'}`);
      }
    }
    expect(silent).toEqual([]);
  });
});
