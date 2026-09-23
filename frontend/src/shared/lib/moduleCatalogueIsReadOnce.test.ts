// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The module catalogue is about 100 KB and was fetched twice on every cold
// load: the sidebar asked GET /v1/modules/ under ['system-modules'], and the
// dashboard asked GET /system/modules under ['modules'] for the same list in an
// envelope, only to read its length. Two keys means two cache entries, two
// requests, and an invalidation aimed at one that never reaches the other.
//
// This pins every React Query read of the catalogue to one key and one route,
// the route that also answers before login.

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

function srcRoot(): string {
  const candidates = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')];
  const hit = candidates.find((c) => existsSync(join(c, 'app', 'layout', 'Sidebar.tsx')));
  if (!hit) throw new Error(`no src root among ${candidates.join(', ')}`);
  return hit;
}

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === '__tests__' || name === 'tests') continue;
      sources(p, out);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(p);
    }
  }
  return out;
}

// queryKey: [...], followed by a queryFn that GETs the catalogue.
const READ = /queryKey:\s*(\[[^\]]*\]),\s*queryFn:\s*\(\)\s*=>\s*apiGet<[^(]*>\(\s*'(\/v1\/modules\/|\/system\/modules)'/g;

describe('the module catalogue', () => {
  const reads: Array<{ file: string; key: string; route: string }> = [];
  for (const file of sources(srcRoot())) {
    const text = readFileSync(file, 'utf8');
    for (const m of text.matchAll(READ)) {
      reads.push({ file, key: m[1]!.replace(/\s+/g, ''), route: m[2]! });
    }
  }

  it('is read somewhere, so the checks below are not vacuous', () => {
    // The sidebar, the dashboard (twice), the Modules page and the settings tab.
    expect(reads.length).toBeGreaterThanOrEqual(5);
    expect(reads.some((r) => r.file.endsWith('Sidebar.tsx'))).toBe(true);
    expect(reads.some((r) => r.file.endsWith('DashboardPage.tsx'))).toBe(true);
  });

  it('is cached under one key', () => {
    expect([...new Set(reads.map((r) => r.key))]).toEqual(["['system-modules']"]);
  });

  it('is fetched through one route', () => {
    expect([...new Set(reads.map((r) => r.route))]).toEqual(['/v1/modules/']);
  });
});
