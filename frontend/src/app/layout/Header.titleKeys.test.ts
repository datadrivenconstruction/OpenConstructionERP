// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One screen, one name: the top bar and the page's own heading.
//
// A route names itself twice. `App.tsx` passes an English `title` which
// `Header` resolves through `TITLE_I18N_MAP` and prints in the top bar and the
// browser tab. The page then renders its own `<h1>`, usually as `PageHeader
// srTitle`. Both are supposed to be the same words in every language.
//
// Nothing checked that, and both places said so in prose. `TITLE_I18N_MAP` was
// documented as mirroring the sidebar so the three "can never disagree";
// `PageHeader.srTitle` was documented as the heading "visually the top bar
// shows it". Measured 2026-08-17: 42 routes disagreed, 9 of which have since
// been fixed. That is the whole reason this file exists. A comment asserting an
// invariant reads as though someone verified it, so it actively stops the next
// reader from checking, and an invariant with no instrument decays silently.
//
// The failure is worse than untidy. The h1 is `sr-only`, so it is read by a
// screen reader and never by a sighted user, while the top bar is read by a
// sighted user and is not the heading. On `/site-prep` the two said "Site prep"
// and "Site Mobilisation": the same screen shipped under two names to two
// audiences, and neither audience could see both names to report it.
//
// The baseline is a shrink list, not an allowlist. Every entry names both keys,
// so a route that changes one goes red, and a route that gets FIXED also goes
// red, because a fixed route has to leave the list. Nothing may be added.

import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { isModuleI18nKey } from '@/modules/_i18n';

// `TITLE_I18N_MAP` is read out of the source rather than imported. Importing
// `./Header` pulls the whole app graph (stores, router, icon set) into a worker
// that only ever needed a lookup table, and the worker timed out before it
// finished loading, which the runner reports as "no tests" beside a green
// summary for the other files. Parsing keeps the test a leaf. `isModuleI18nKey`
// is imported for real because it has no imports of its own and reimplementing
// its regex here would let the two drift apart silently.

/**
 * Routes whose top bar and page heading already disagreed when this gate
 * landed, as [top bar key, h1 key]. 33 routes. Shrinks only.
 *
 * Grouped by what a reader actually experiences, because "the keys differ" is
 * not a reason to accept anything. The first group shows two different English
 * names on one screen. The second shows one English name through two keys,
 * which is invisible to an English reviewer and visible to most other readers:
 * 16 of these 18 render differently in at least one shipped locale.
 */
const SPLIT_BASELINE: Record<string, [string, string]> = {
  // Two different names in English, so any reader can see both and pick.
  '/bim': ['nav.bim_viewer', 'bim.landing_hero_title'],
  '/bim/:modelId': ['nav.bim_viewer', 'bim.landing_hero_title'],
  '/projects/:projectId/bim': ['nav.bim_viewer', 'bim.landing_hero_title'],
  '/projects/:projectId/bim/:modelId': ['nav.bim_viewer', 'bim.landing_hero_title'],
  '/coordination': ['nav.coordination_hub', 'coordination.title'],
  '/assets': ['nav.assets', 'assets.title'],
  '/templates': ['nav.templates', 'boq.templates'],
  '/deadlines': ['deadlines.title', 'deadlines.register_title'],
  '/issues': ['nav.issues', 'issues.title'],
  '/credentials': ['nav.credentials', 'credentials.page_title'],
  '/projects/:projectId/credentials': ['nav.credentials', 'credentials.page_title'],
  '/module-builder': ['nav.module_builder', 'module_builder.title'],
  '/users': ['sidebar.admin_grid.users', 'users.management'],
  '/admin/audit-log': ['sidebar.admin_grid.audit', 'admin.audit_log_title'],

  // One name in English, two keys. `/clash` and `/progress` agree in all 42
  // locales today and are the cheapest to collapse; the rest already drift.
  '/clash': ['nav.clash_detection', 'clash.title'],
  '/progress': ['nav.progress', 'progress.title'],
  '/plan-room': ['nav.plan_room', 'plan_room.title'],
  '/assemblies': ['nav.assemblies', 'assemblies.title'],
  '/assemblies/library': ['nav.assembly_library', 'assemblies.library.title'],
  '/dwg-takeoff': ['nav.dwg_takeoff', 'dwg_takeoff.hero_title'],
  '/schedule': ['nav.schedule', 'schedule.title'],
  '/5d': ['nav.5d_cost_model', 'costmodel.title'],
  '/tendering': ['nav.tendering', 'tendering.title'],
  '/photos': ['nav.photos', 'photos.title'],
  '/files/transmittals': ['transmittals.title', 'files.transmittals.title'],
  '/punchlist': ['nav.punchlist', 'punch.title'],
  '/field-reports': ['nav.field_reports', 'fieldreports.title'],
  '/project-intelligence': ['nav.estimation_dashboard', 'project_intelligence.page_title_v191'],
  '/payroll': ['nav.payroll', 'payroll.title'],
  '/cost-benchmarks': ['nav.cost_benchmarks', 'cost_benchmarks.title'],
  '/projects/:projectId/payroll': ['nav.payroll', 'payroll.title'],
  '/portfolio/capacity': ['nav.capacity_planning', 'capacity.title'],
  '/portfolio/leveling': ['nav.resource_leveling', 'leveling.title'],
  '/notifications': ['nav.notifications', 'notifications.title'],
};

/**
 * Routes that name themselves nowhere: no `TITLE_I18N_MAP` entry and no `<h1>`.
 * The top bar prints the English literal from `App.tsx` untranslated and the
 * page offers a screen reader no heading at all.
 *
 * These seven are internal or developer surfaces rather than shipped modules,
 * which is why they were never named, and each line says which.
 */
const UNNAMED_BASELINE: Record<string, string> = {
  '/chat/admin': 'operator diagnostics for the chat service',
  '/schedule/:id/cpm': 'a view mode of /schedule rather than a module of its own',
  '/files/search': 'a results surface reached from search, never from the sidebar',
  '/markups/compare': 'a comparison view opened from a document, not a destination',
  '/eac/demo': 'component gallery for the EAC primitives',
  '/styles-lab': 'internal component gallery',
  '/property-dev/dashboards/:key': 'renders a dashboard whose name is the record',
};

/**
 * Routes whose page names itself but whose title has no map entry, so the top
 * bar falls back to the English literal and stays English in every language.
 */
const UNTRANSLATED_TOPBAR_BASELINE: Record<string, string> = {
  '/admin/webhook-targets': 'administrator surface, added without a map entry',
  '/modules/developer-guide': 'developer documentation page',
  '/geo/admin': 'administrator surface, added without a map entry',
};

/** Resolve `frontend/src` whether vitest was started at `frontend/` or the repo root. */
function findSrcRoot(): string {
  const root = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')].find((p) =>
    existsSync(join(p, 'app/App.tsx')),
  );
  expect(root, 'could not locate frontend/src from the test working directory').toBeTruthy();
  return root!;
}

/**
 * The three shapes a page uses to state its own heading. `PageHeader srTitle`
 * is the convention; two pages write the element themselves, and looking only
 * for the convention reported them as having no heading at all.
 */
const H1_SHAPES = [
  /srTitle=\{t\(\s*'([^']+)'/,
  /<h1[^>]*sr-only[^>]*>\s*\{t\(\s*'([^']+)'/,
  /<h1[^>]*>\s*\{t\(\s*'([^']+)'/,
];

interface RouteFacts {
  path: string;
  title: string;
  topbarKey: string | null;
  h1Key: string | null;
}

/** The literal-to-key pairs of `TITLE_I18N_MAP`, read out of `Header.tsx`. */
function readTitleMap(srcRoot: string): Record<string, string> {
  const header = readFileSync(join(srcRoot, 'app/layout/Header.tsx'), 'utf8');
  const body = header.slice(header.indexOf('TITLE_I18N_MAP'));
  const map: Record<string, string> = {};
  for (const m of body.matchAll(/^\s*'((?:[^'\\]|\\.)*)':\s*'([^']+)',/gm)) {
    map[m[1]!] = m[2]!;
  }
  return map;
}

function readRoutes(srcRoot: string, titleMap: Record<string, string>): RouteFacts[] {
  const app = readFileSync(join(srcRoot, 'app/App.tsx'), 'utf8');

  // The same two steps `resolvePageTitleKey` takes in Header.tsx: the map wins,
  // and a title that is already a module key stands for itself.
  const resolveTitleKey = (title: string): string | null =>
    titleMap[title] ?? (isModuleI18nKey(title) ? title : null);

  const modules = new Map<string, string>();
  for (const m of app.matchAll(/const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\('([^']+)'\)/g)) {
    modules.set(m[1]!, m[2]!);
  }
  for (const m of app.matchAll(/^import\s+\{([^}]*)\}\s+from\s+'([^']+)';/gm)) {
    for (const raw of m[1]!.split(',')) {
      const name = raw.trim();
      if (name && !modules.has(name)) modules.set(name, m[2]!);
    }
  }

  const h1Cache = new Map<string, string | null>();
  const h1For = (component: string): string | null => {
    const spec = modules.get(component);
    if (!spec || !spec.startsWith('@/')) return null;
    const base = join(srcRoot, spec.slice(2));
    const file = [base + '.tsx', base + '.ts', join(base, 'index.tsx'), join(base, 'index.ts')].find(
      (p) => existsSync(p),
    );
    if (!file) return null;
    if (!h1Cache.has(file)) {
      const text = readFileSync(file, 'utf8');
      let found: string | null = null;
      for (const shape of H1_SHAPES) {
        const hit = shape.exec(text);
        if (hit) {
          found = hit[1]!;
          break;
        }
      }
      h1Cache.set(file, found);
    }
    return h1Cache.get(file) ?? null;
  };

  const routes: RouteFacts[] = [];
  for (const m of app.matchAll(/path="([^"]+)"\s+element=\{([\s\S]{0,300}?)\}\s*\/>/g)) {
    const element = m[2]!;
    const title = /title="([^"]*)"/.exec(element)?.[1];
    if (title === undefined) continue;
    const component = /<(\w+)\s*\/>/.exec(element)?.[1];
    routes.push({
      path: m[1]!.startsWith('/') ? m[1]! : `/${m[1]!}`,
      title,
      topbarKey: resolveTitleKey(title),
      h1Key: component ? h1For(component) : null,
    });
  }
  return routes;
}

describe('page title keys', () => {
  const srcRoot = findSrcRoot();
  const titleMap = readTitleMap(srcRoot);
  const routes = readRoutes(srcRoot, titleMap);

  // A parser that matches nothing reports a clean bill of health for every
  // check below it, so prove the population before trusting any verdict about
  // it. These floors are far under the live figures (257 routes, 184 entries).
  it('actually read the routes and the map', () => {
    expect(routes.length, 'no routed titles parsed out of App.tsx').toBeGreaterThan(200);
    expect(Object.keys(titleMap).length, 'TITLE_I18N_MAP parsed as empty').toBeGreaterThan(150);
    expect(titleMap['Bill of Quantities'], 'a known entry parsed wrong').toBe('boq.title');
    expect(
      routes.filter((r) => r.h1Key !== null).length,
      'no page heading keys found; the h1 shapes stopped matching',
    ).toBeGreaterThan(50);
  });

  it('titleKeyAgreement: the top bar and the page heading name one screen once', () => {
    const failures: string[] = [];
    const seen = new Set<string>();

    for (const route of routes) {
      if (route.topbarKey === null || route.h1Key === null) continue;
      const baseline = SPLIT_BASELINE[route.path];

      if (route.topbarKey !== route.h1Key) {
        if (baseline && baseline[0] === route.topbarKey && baseline[1] === route.h1Key) {
          seen.add(route.path);
          continue;
        }
        failures.push(
          `${route.path} (title "${route.title}") shows "${route.topbarKey}" in the top bar and ` +
            `"${route.h1Key}" as the page heading. Point both at the key the module names ` +
            `itself by, normally <module>.title.` +
            (baseline
              ? ` Baselined as [${baseline.join(', ')}], so one of the two keys moved.`
              : ''),
        );
      } else if (baseline) {
        seen.add(route.path);
        failures.push(
          `${route.path} now agrees on "${route.topbarKey}" but is still in SPLIT_BASELINE. ` +
            `Delete the entry so the list keeps shrinking.`,
        );
      }
    }

    for (const path of Object.keys(SPLIT_BASELINE)) {
      if (!seen.has(path)) {
        failures.push(
          `${path} is in SPLIT_BASELINE but no route by that name has both a top bar key and a ` +
            `page heading any more. Delete the entry.`,
        );
      }
    }

    expect(failures, `\n  - ${failures.join('\n  - ')}\n`).toEqual([]);
  });

  // Without this the gate would pass by ignorance: a screen that names itself
  // nowhere has no two keys to disagree, and silence would read as agreement.
  it('every routed screen states a name somewhere', () => {
    const failures: string[] = [];
    const seen = new Set<string>();

    for (const route of routes) {
      if (route.topbarKey !== null || route.h1Key !== null) {
        if (UNNAMED_BASELINE[route.path]) {
          failures.push(
            `${route.path} now names itself, but is still in UNNAMED_BASELINE. Delete the entry.`,
          );
          seen.add(route.path);
        }
        continue;
      }
      seen.add(route.path);
      if (UNNAMED_BASELINE[route.path]) continue;
      failures.push(
        `${route.path} (title "${route.title}") has no TITLE_I18N_MAP entry and no page heading, ` +
          `so its top bar stays English everywhere and a screen reader gets no heading. Add a ` +
          `map entry and a PageHeader srTitle naming the same key.`,
      );
    }

    for (const path of Object.keys(UNNAMED_BASELINE)) {
      if (!seen.has(path)) {
        failures.push(`${path} is in UNNAMED_BASELINE but no longer routes a title. Delete it.`);
      }
    }

    expect(failures, `\n  - ${failures.join('\n  - ')}\n`).toEqual([]);
  });

  it('every routed title can be translated at all', () => {
    const failures: string[] = [];
    const seen = new Set<string>();

    for (const route of routes) {
      if (route.topbarKey !== null) {
        if (UNTRANSLATED_TOPBAR_BASELINE[route.path]) {
          failures.push(
            `${route.path} now resolves to "${route.topbarKey}" but is still in ` +
              `UNTRANSLATED_TOPBAR_BASELINE. Delete the entry.`,
          );
          seen.add(route.path);
        }
        continue;
      }
      if (route.h1Key === null) continue; // counted by the check above
      seen.add(route.path);
      if (UNTRANSLATED_TOPBAR_BASELINE[route.path]) continue;
      failures.push(
        `${route.path} (title "${route.title}") has no TITLE_I18N_MAP entry, so the top bar ` +
          `prints that English literal in every language while the page heading says ` +
          `"${route.h1Key}". Map the title onto the heading's key.`,
      );
    }

    for (const path of Object.keys(UNTRANSLATED_TOPBAR_BASELINE)) {
      if (!seen.has(path)) {
        failures.push(
          `${path} is in UNTRANSLATED_TOPBAR_BASELINE but no longer matches. Delete it.`,
        );
      }
    }

    expect(failures, `\n  - ${failures.join('\n  - ')}\n`).toEqual([]);
  });
});
