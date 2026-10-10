// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The two workspaces a building-services contractor uses: the installer's
// full menu and the site-records job profile a pilot starts on.
//
// `workspaces.test.ts` asks the questions that hold for any workspace (every
// row lands on a menu row, a tab row names a real tab). This file pins what
// these two are, and checks the things a menu can get wrong that nothing on
// screen would report: a row whose route no longer mounts, a row whose module
// the pack switches off, a row the profile's own module set hides, a heading
// or a label with no Turkish.

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  NAV_ITEM_BY_ROUTE,
  PRESET_WORKSPACES,
  effectiveCompanyPresetKey,
  resolveWorkspace,
  workspaceFor,
  workspaceSectionByRoute,
} from './workspaces';

function readRepoFile(fromFrontend: string): string {
  const candidates = [
    resolve(process.cwd(), fromFrontend),
    resolve(process.cwd(), 'frontend', fromFrontend),
  ];
  const found = candidates.find(existsSync);
  if (!found) throw new Error(`cannot find ${fromFrontend}, looked in ${candidates.join(' and ')}`);
  return readFileSync(found, 'utf8');
}

/** `"key": "value"` pairs of a locale file, read as text. */
function localePairs(file: string): Map<string, string> {
  const pairs = new Map<string, string>();
  const line = /^\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$/;
  for (const text of readRepoFile(`src/app/locales/${file}`).split(/\r?\n/)) {
    const match = line.exec(text);
    if (match) pairs.set(match[1]!, match[2]!);
  }
  return pairs;
}

const mep = workspaceFor('mep_contractor')!;
const siteRecords = workspaceFor('site_records')!;

const SITE_RECORDS_ROWS = [
  ['/', 'nav.dashboard'],
  ['/inbox', 'nav.inbox'],
  ['/projects', 'projects.title'],
  ['/daily-diary', 'nav.daily_diary'],
  ['/correspondence', 'correspondence.title'],
  ['/rfi', 'rfi.title'],
  ['/submittals', 'submittals.title'],
  ['/variations', 'nav.variations'],
  ['/variations?tab=eot', 'variations.tab_eot'],
  ['/files', 'nav.documents'],
  ['/contacts', 'contacts.title'],
];

const MEP_SECTIONS: Array<[string, string[]]> = [
  [
    'site_records',
    ['/daily-diary', '/correspondence', '/rfi', '/meetings', '/schedule', '/field-time', '/contacts'],
  ],
  ['engineering', ['/submittals', '/transmittals', '/sheets', '/files']],
  ['procurement', ['/procurement', '/rfq-bidding', '/site-logistics']],
  [
    'commercial',
    [
      '/contracts',
      '/subcontractors',
      '/progress',
      '/contracts?tab=claims',
      '/variations',
      '/variations?tab=eot',
      '/finance?tab=invoices',
      '/finance?tab=payments',
      '/tax-rates',
    ],
  ],
  ['estimating', ['/boq', '/quantities']],
  ['quality', ['/construction-control', '/ncr', '/punchlist', '/commissioning']],
  ['hse', ['/safety', '/hse-advanced']],
  ['handover', ['/closeout', '/defects-liability']],
];

describe('the site records workspace', () => {
  it('is the registers one person keeps, in this order', () => {
    expect(resolveWorkspace(siteRecords).map((item) => [item.to, item.labelKey])).toEqual(SITE_RECORDS_ROWS);
  });

  it('holds the five registers a pilot runs on', () => {
    const routes = siteRecords.rows.map((row) => row.to);
    for (const register of ['/daily-diary', '/correspondence', '/rfi', '/submittals', '/variations']) {
      expect(routes).toContain(register);
    }
  });

  it('is short enough to need no headings, and hides nothing from the rest', () => {
    expect(siteRecords.sections).toBeUndefined();
    expect(siteRecords.notForProfile).toBeUndefined();
    expect(siteRecords.rows.length).toBeLessThanOrEqual(12);
  });
});

describe('the MEP contractor workspace', () => {
  it('is these rows under these headings', () => {
    expect(mep.sections!.map((section) => [section.id, section.rows.map((row) => row.to)])).toEqual(
      MEP_SECTIONS,
    );
  });

  it('lists the basics, then the sections in order, and nothing else', () => {
    const expected = ['/', '/inbox', '/projects', ...MEP_SECTIONS.flatMap(([, routes]) => routes)];
    expect(mep.rows.map((row) => row.to)).toEqual(expected);
    // Every one resolves, so the menu draws as many rows as the list has.
    expect(resolveWorkspace(mep).map((item) => item.to)).toEqual(expected);
  });

  it('opens with the same registers the site records workspace is made of', () => {
    const own = new Set(mep.rows.map((row) => row.to));
    expect(siteRecords.rows.map((row) => row.to).filter((route) => !own.has(route))).toEqual([]);
  });

  it('shows one screen where several overlap', () => {
    const routes = new Set(mep.rows.map((row) => row.to));
    // [the one shown, the ones left under More modules]
    const overlaps: Array<[string, string[]]> = [
      ['/daily-diary', ['/field-reports']],
      ['/variations', ['/changeorders', '/moc']],
      ['/construction-control', ['/inspections', '/qms']],
      ['/procurement', ['/supplier-catalogs', '/tendering', '/bid-management']],
    ];
    for (const [shown, others] of overlaps) {
      expect(routes.has(shown), shown).toBe(true);
      for (const other of others) {
        expect(NAV_ITEM_BY_ROUTE.has(other), `${other} is not a menu row any more`).toBe(true);
        expect(routes.has(other), other).toBe(false);
      }
    }
  });

  it('files every sectioned row under exactly one heading', () => {
    const byRoute = workspaceSectionByRoute(mep);
    const sectioned = mep.sections!.flatMap((section) => section.rows.map((row) => row.to));
    expect(new Set(sectioned).size).toBe(sectioned.length);
    expect([...byRoute.keys()]).toEqual(sectioned);
    expect(new Set(mep.sections!.map((section) => section.id)).size).toBe(mep.sections!.length);
    // The basics carry no heading.
    for (const route of ['/', '/inbox', '/projects']) expect(byRoute.has(route)).toBe(false);
    expect(workspaceSectionByRoute(siteRecords).size).toBe(0);
  });
});

describe('rows a profile keeps out from under More modules', () => {
  const hidden = mep.notForProfile ?? [];

  it('are real menu rows, each named once', () => {
    expect(hidden.length).toBeGreaterThan(20);
    expect(hidden.filter((route) => !NAV_ITEM_BY_ROUTE.has(route))).toEqual([]);
    expect(new Set(hidden).size).toBe(hidden.length);
  });

  it('are never rows of the workspace itself', () => {
    const own = new Set(mep.rows.map((row) => row.to.split('?')[0]!));
    expect(hidden.filter((route) => own.has(route))).toEqual([]);
  });

  it('never take away a screen every profile keeps', () => {
    for (const route of ['/', '/projects', '/files', '/costs', '/boq', '/validation', '/contacts']) {
      expect(hidden).not.toContain(route);
    }
  });
});

describe('every row of every workspace', () => {
  const app = readRepoFile('src/app/App.tsx');
  const all = Object.values(PRESET_WORKSPACES).flatMap((workspace) =>
    workspace.rows.map((row) => ({ key: workspace.presetKey, to: row.to })),
  );

  it('opens a route the router mounts', () => {
    // The instrument first: a route known to be mounted, and one known not to be.
    expect(app.includes('path="/projects"')).toBe(true);
    expect(app.includes('path="/no-such-screen"')).toBe(false);
    const unmounted = all.filter(({ to }) => {
      const path = to.split('?')[0]!;
      return path !== '/' && !app.includes(`path="${path}"`);
    });
    expect(unmounted).toEqual([]);
    expect(app.includes('path="/"')).toBe(true);
  });

  it('is named in English and in Turkish', () => {
    const en = localePairs('en.ts');
    const tr = localePairs('tr.ts');
    expect(en.size).toBeGreaterThan(10_000);
    expect(tr.size).toBeGreaterThan(10_000);
    const keys = new Set<string>();
    for (const workspace of Object.values(PRESET_WORKSPACES)) {
      keys.add(workspace.labelKey);
      for (const section of workspace.sections ?? []) keys.add(section.labelKey);
      for (const item of resolveWorkspace(workspace)) keys.add(item.labelKey);
    }
    expect([...keys].filter((key) => !en.get(key))).toEqual([]);
    expect([...keys].filter((key) => !tr.get(key))).toEqual([]);
  });

  it('has a Turkish heading that is not the English one', () => {
    const en = localePairs('en.ts');
    const tr = localePairs('tr.ts');
    const same = mep.sections!.filter((section) => tr.get(section.labelKey) === en.get(section.labelKey));
    expect(same.map((section) => section.labelKey)).toEqual([]);
  });
});

describe('a workspace row and the modules behind it', () => {
  const sidebar = readRepoFile('src/app/layout/Sidebar.tsx');
  const routeMapSource = sidebar.slice(
    sidebar.indexOf('const ROUTE_BACKEND_MODULE'),
    sidebar.indexOf('\n};', sidebar.indexOf('const ROUTE_BACKEND_MODULE')),
  );
  /** route -> backend module, for the routes owned by exactly one module. */
  const routeModule = new Map(
    [...routeMapSource.matchAll(/'([^']+)':\s*'(oe_[a-z0-9_]+)'/g)].map((m) => [m[1]!, m[2]!]),
  );

  const packManifest = readRepoFile(
    '../packs/turkey-tr-mep/src/openconstructionerp_turkey_tr_mep/manifest.py',
  );
  const hiddenBlock = /hidden_modules=\[([\s\S]*?)\n {4}\],/.exec(packManifest)?.[1] ?? '';
  const hiddenModules = [...hiddenBlock.matchAll(/"(oe_[a-z0-9_]+)"/g)].map((m) => m[1]!);

  const presets = readRepoFile('../backend/app/core/onboarding_presets.py');
  const coreBlock = /_CORE_MODULES:\s*list\[str\]\s*=\s*\[([\s\S]*?)\n\]/.exec(presets)?.[1] ?? '';
  const core = new Set([...coreBlock.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]!));
  /** The functional modules a preset switches on, read from the registry. */
  function presetModules(key: string): Set<string> {
    const after = presets.slice(presets.indexOf(`"${key}": CompanyPreset(`));
    const listed = /enabled_modules=\[([\s\S]*?)\n\s*\],/.exec(after)?.[1] ?? '';
    return new Set([...listed.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]!));
  }

  it('reads the three sources it is about to compare', () => {
    expect(routeModule.size).toBeGreaterThan(60);
    expect(routeModule.get('/contracts')).toBe('oe_contracts');
    expect(hiddenModules.length).toBe(24);
    expect(core.has('projects')).toBe(true);
    expect(presetModules('mep_contractor').has('submittals')).toBe(true);
    expect(presetModules('site_records').has('daily_diary')).toBe(true);
  });

  it('is never backed by a module the pack switches off', () => {
    const off = new Set(hiddenModules);
    const dead = [mep, siteRecords].flatMap((workspace) =>
      workspace.rows
        .map((row) => ({ to: row.to, module: routeModule.get(row.to) ?? routeModule.get(row.to.split('?')[0]!) }))
        .filter(({ module }) => module !== undefined && off.has(module)),
    );
    expect(dead).toEqual([]);
  });

  it('is never hidden by the module set of its own profile', () => {
    // The sidebar drops a row whose `moduleKey` the profile left off, without
    // a word. A key the registry does not govern is always on.
    const lost: string[] = [];
    for (const workspace of [mep, siteRecords]) {
      const on = presetModules(workspace.presetKey);
      for (const item of resolveWorkspace(workspace)) {
        if (item.moduleKey && !on.has(item.moduleKey) && !core.has(item.moduleKey)) {
          lost.push(`${workspace.presetKey}: ${item.to} needs ${item.moduleKey}`);
        }
      }
    }
    expect(lost).toEqual([]);
  });

  it('leaves the menu when the pack switches its module off, for every hidden module that has a row', () => {
    // A row with no entry in the route map stays in the menu and opens a
    // screen whose API is gone. These three had none.
    expect(routeModule.get('/funding')).toBe('oe_funding');
    expect(routeModule.get('/rebar-schedule')).toBe('oe_rebar_schedule');
    expect(routeModule.get('/value')).toBe('oe_value');
    const rowOwners = new Set(routeModule.values());
    const withRow = hiddenModules.filter((name) => rowOwners.has(name)).sort();
    expect(withRow).toEqual([
      'oe_architecture_map',
      'oe_carbon',
      'oe_certified_payroll',
      'oe_formwork',
      'oe_funding',
      'oe_payment_clock',
      'oe_rebar_schedule',
      'oe_temporary_works',
      'oe_value',
    ]);
  });
});

describe('whose profile the menu follows', () => {
  it('is the user\'s own choice, whatever the pack says', () => {
    expect(effectiveCompanyPresetKey('site_records', 'mep_contractor')).toBe('site_records');
    expect(effectiveCompanyPresetKey('estimator', 'mep_contractor')).toBe('estimator');
  });

  it('is the pack\'s profile for a user who has chosen none', () => {
    expect(effectiveCompanyPresetKey(null, 'mep_contractor')).toBe('mep_contractor');
    expect(effectiveCompanyPresetKey(undefined, 'mep_contractor')).toBe('mep_contractor');
    expect(effectiveCompanyPresetKey('', 'mep_contractor')).toBe('mep_contractor');
    expect(workspaceFor(effectiveCompanyPresetKey(null, 'mep_contractor'))).toBe(mep);
  });

  it('is nobody\'s when neither names one', () => {
    expect(effectiveCompanyPresetKey(null, null)).toBeNull();
    expect(effectiveCompanyPresetKey(null, undefined)).toBeNull();
    expect(effectiveCompanyPresetKey(undefined, '')).toBeNull();
  });
});
