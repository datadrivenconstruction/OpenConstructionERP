// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Installing a country pack worked on the server and showed nothing in the app:
// the header went on saying no pack was active and the example projects did not
// appear. Nothing had failed. Every reader of that state is a React Query entry
// with a five minute stale time, and the install invalidated the wrong half of
// them.
//
// The active pack is read through two sibling keys, ['partner-pack', 'current']
// and ['partner-pack', 'installed'], and invalidation matches by PREFIX. Naming
// one sibling leaves the other alone, and the one nobody named is the one the
// header chip reads. So the first test here is about the keys themselves, using
// the real hooks rather than copies of their keys, because a test that repeats
// the key it is checking cannot notice the key moving.
//
// The second test is on the call sites. The behaviour above is only correct if
// the places that finish an install actually ask for the prefix, and one of
// those places, the background installer the onboarding flow uses, was asking
// for nothing at all.

import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock('@/shared/lib/api', () => api);

import { usePartnerPack, useInstalledPacks } from '@/shared/hooks/usePartnerPack';

function pick(...candidates: string[]): string {
  const hit = candidates.find((c) => existsSync(c));
  if (!hit) throw new Error(`none of these exist: ${candidates.join(', ')}`);
  return hit;
}

function source(relative: string): string {
  return readFileSync(
    pick(resolve(process.cwd(), relative), resolve(process.cwd(), `frontend/${relative}`)),
    'utf8',
  );
}

beforeEach(() => {
  cleanup();
  api.apiGet.mockReset();
  api.apiGet.mockResolvedValue({ active: false, active_slug: null, installed: [] });
});

describe('the keys an install has to invalidate', () => {
  it('reaches the header chip through the prefix and not through its sibling', async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    // Both real hooks, so the keys under test are the shipped ones. The chip in
    // the header renders useInstalledPacks; the boot-time co-brand hook renders
    // usePartnerPack.
    renderHook(() => usePartnerPack(), { wrapper });
    renderHook(() => useInstalledPacks(), { wrapper });
    await waitFor(() => {
      expect(qc.getQueryCache().getAll()).toHaveLength(2);
    });

    const matched = (queryKey: string[]) =>
      qc
        .getQueryCache()
        .findAll({ queryKey })
        .map((q) => (q.queryKey as string[]).join('/'))
        .sort();

    // Both siblings really are under the one prefix, and both really are
    // distinct entries. If either half of this stops holding, the fix below is
    // aimed at the wrong thing.
    expect(matched(['partner-pack'])).toEqual(['partner-pack/current', 'partner-pack/installed']);

    // The defect, pinned from the other side: the narrow key the install used
    // to name cannot reach the chip. This has to keep failing for the narrow
    // key, or the test would pass for a codebase that never fixed anything.
    expect(matched(['partner-pack', 'current'])).toEqual(['partner-pack/current']);
    expect(matched(['partner-pack', 'current'])).not.toContain('partner-pack/installed');
  });
});

describe('the places that finish a pack install', () => {
  // Every path that leaves a pack applied or removed. The banner is here
  // because the onboarding install is driven by a module-scoped function with
  // no component around it, so the banner is the only observer of that stream
  // that can reach the query cache.
  const SITES = [
    'src/features/modules/PartnerPackApplyDialog.tsx',
    'src/features/modules/PartnerPackDeactivateDialog.tsx',
    'src/features/modules/partnerPacks.ts',
    'src/shared/ui/BackgroundInstallBanner.tsx',
  ];

  const invalidations = (relative: string) =>
    source(relative)
      .split('\n')
      .filter((line) => line.includes('invalidateQueries('))
      .map((line) => line.trim());

  it.each(SITES)('%s asks for the whole partner-pack prefix', (relative) => {
    const lines = invalidations(relative);
    expect(lines.length).toBeGreaterThan(0);
    expect(lines.some((l) => l.includes("queryKey: ['partner-pack']"))).toBe(true);
  });

  it.each(SITES)('%s does not settle for the current-only sibling', (relative) => {
    // Asserted on the invalidation lines alone. The comments in these files
    // quote the narrow key on purpose, to explain why it was wrong.
    expect(
      invalidations(relative).filter((l) => l.includes("['partner-pack', 'current']")),
    ).toEqual([]);
  });

  it.each(SITES)('%s refreshes the project list too', (relative) => {
    // The backend scopes the project listing to the active pack the instant it
    // is applied.
    if (relative.includes('partnerPacks.ts')) return; // shared helper, no project view
    const lines = invalidations(relative);
    expect(lines.some((l) => l.includes("queryKey: ['projects']"))).toBe(true);
  });

  // Applying a pack enables and disables modules. A header that updates over a
  // stale sidebar is only half the report, so every site has to reach the
  // query the sidebar actually reads its module list through.
  //
  // This used to assert that each site named ['modules'], and it passed while
  // the sidebar read ['system-modules']. Prefix matching does not cross those
  // two keys, so the invalidation the test guarded never reached the sidebar.
  // The key is therefore read out of the sidebar's own source here, and the
  // match is left to React Query rather than to a string comparison.
  const literalKey = (text: string): unknown[] | null => {
    try {
      const parsed: unknown = JSON.parse(text.replace(/'/g, '"'));
      return Array.isArray(parsed) ? parsed : null;
    } catch {
      return null; // a key built from a variable, not a literal
    }
  };

  const sidebarModulesKey = (): unknown[] => {
    const src = source('src/app/layout/Sidebar.tsx');
    const m = src.match(/queryKey:\s*(\[[^\]]*\]),\s*queryFn:\s*\(\)\s*=>\s*apiGet<[^>]*>\('\/v1\/modules\/'\)/);
    if (!m) throw new Error('Sidebar.tsx no longer reads the module list the way this test expects');
    const key = literalKey(m[1]!);
    if (!key) throw new Error(`Sidebar.tsx module list key is not a literal: ${m[1]}`);
    return key;
  };

  it.each(SITES)('%s reaches the module list the sidebar reads', (relative) => {
    const sidebarKey = sidebarModulesKey();
    const qc = new QueryClient();
    qc.setQueryData(sidebarKey, []);
    const keys = invalidations(relative)
      .map((l) => l.match(/queryKey:\s*(\[[^\]]*\])/)?.[1])
      .filter((k): k is string => Boolean(k))
      .map(literalKey)
      .filter((k): k is unknown[] => k !== null);
    const reached = keys.some((k) =>
      qc
        .getQueryCache()
        .findAll({ queryKey: k })
        .some((q) => JSON.stringify(q.queryKey) === JSON.stringify(sidebarKey)),
    );
    expect(reached).toBe(true);
  });
});
