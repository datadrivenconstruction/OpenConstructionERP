// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Academy items against the product and the founder's rules: the
// generated data carries no money and no unknowns, every item points at a
// screen the app has, links follow the reader's language, a country's
// checklist is never shown to another country, and the popover never lists
// more than one paid item.

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { matchRoutes, type RouteObject } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { getAllModuleRoutes } from '@/modules/_registry';
import { ITEM_COUNT_BY_ROUTE } from './academyIndex.generated';
import { ACADEMY_ITEMS } from './academyItems.generated';
import type { AcademyItem } from './academyTypes';
import {
  academyUrlFor,
  filterItems,
  itemsForScreen,
  paletteItems,
  rankItems,
  visibleInMarket,
} from './academyItems';

const ROOT = [resolve(process.cwd(), '..'), process.cwd()].find((p) =>
  existsSync(resolve(p, 'frontend/src/app/App.tsx')),
)!;

function item(over: Partial<AcademyItem> & { id: string }): AcademyItem {
  return {
    kind: 'course',
    title: over.id,
    url: `https://openconstructionacademy.com/courses/${over.id}/`,
    languages: ['en', 'de', 'pt', 'fr'],
    contentLanguage: 'en',
    access: 'free',
    topics: [],
    routes: ['/boq'],
    ...over,
  };
}

describe('the generated academy items', () => {
  const source = readFileSync(resolve(ROOT, 'frontend/src/features/videos/academyItems.generated.ts'), 'utf8');
  const index = readFileSync(resolve(ROOT, 'frontend/src/features/videos/academyIndex.generated.ts'), 'utf8');

  it('carry no price, evidence, course code, currency sign or checkout wording', () => {
    for (const text of [source, index]) {
      expect(text).not.toMatch(/"(price|price_eur_internal|price_note|access_evidence|course_code)"/);
      expect(text).not.toContain('€');
      expect(text).not.toMatch(/checkout/i);
      expect(text).not.toMatch(/\bPro\b/);
    }
  });

  it('hold no video and no unknown access', () => {
    expect(ACADEMY_ITEMS.length).toBeGreaterThan(60);
    for (const i of ACADEMY_ITEMS) {
      expect(['course', 'lesson', 'checklist', 'article'], i.id).toContain(i.kind);
      expect(['free', 'paid'], i.id).toContain(i.access);
    }
  });

  it('name an ISO content language and an ISO market', () => {
    for (const i of ACADEMY_ITEMS) {
      expect(i.contentLanguage, i.id).toMatch(/^[a-z]{2,3}(-[A-Z]{2})?$/);
      if (i.market) expect(i.market, i.id).toMatch(/^[A-Z]{2}$/);
    }
    expect(ACADEMY_ITEMS.some((i) => i.market === 'UK')).toBe(false);
    expect(ACADEMY_ITEMS.some((i) => i.market === 'GB')).toBe(true);
  });

  it('point at screens the app renders', () => {
    const app = readFileSync(resolve(ROOT, 'frontend/src/app/App.tsx'), 'utf8');
    const paths = [...app.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]!);
    const routes: RouteObject[] = [...paths, ...getAllModuleRoutes().map((r) => r.path)].map((path) => ({ path }));
    for (const i of ACADEMY_ITEMS) {
      expect(i.routes.length, i.id).toBeGreaterThan(0);
      for (const r of i.routes) expect(matchRoutes(routes, r), `${i.id} -> ${r}`).not.toBeNull();
    }
  });

  it('count in the eager index exactly the market-free items of each route', () => {
    const expected: Record<string, number> = {};
    for (const i of ACADEMY_ITEMS) if (!i.market) for (const r of i.routes) expected[r] = (expected[r] ?? 0) + 1;
    expect(ITEM_COUNT_BY_ROUTE).toEqual(expected);
  });

  it('keep a title as it is on the site', () => {
    expect(ACADEMY_ITEMS.find((i) => i.id === 'course:ai-takeoff-verification')?.title).toBe(
      'AI-assisted take-off: verify before you price',
    );
  });
});

describe('the Academy URL', () => {
  const it1 = item({ id: 'a', languages: ['en', 'de', 'pt'] });

  it('takes the interface language as a prefix', () => {
    expect(academyUrlFor(it1, 'de')).toBe('https://openconstructionacademy.com/de/courses/a/');
  });

  it('tries the full tag, then the base language', () => {
    expect(academyUrlFor(it1, 'pt-BR')).toBe('https://openconstructionacademy.com/pt/courses/a/');
    const both = item({ id: 'b', languages: ['pt', 'pt-BR'] });
    expect(academyUrlFor(both, 'pt-BR')).toBe('https://openconstructionacademy.com/pt-BR/courses/b/');
  });

  it('falls back to the English address, with no tracking parameters', () => {
    expect(academyUrlFor(it1, 'ja')).toBe(it1.url);
    expect(academyUrlFor(it1, 'en')).toBe(it1.url);
    expect(academyUrlFor(it1, 'en-GB')).toBe(it1.url);
    expect(academyUrlFor(it1, 'de')).not.toContain('?');
  });
});

describe('market', () => {
  const hr = item({ id: 'hr', kind: 'checklist', market: 'HR' });
  const open = item({ id: 'open' });

  it('hides a country checklist from another country and shows it to its own', () => {
    expect(visibleInMarket(hr, { market: 'DE' })).toBe(false);
    expect(visibleInMarket(hr, { market: 'HR' })).toBe(true);
    expect(visibleInMarket(hr, { market: null })).toBe(false);
    expect(visibleInMarket(open, { market: 'DE' })).toBe(true);
  });

  it('shows everything when the reader chose any country', () => {
    expect(visibleInMarket(hr, { market: null, anyMarket: true })).toBe(true);
  });

  it('applies to the hub filter and the palette too', () => {
    const items = [hr, open];
    const filters = { kind: null, topic: null, track: null, route: null, query: '' };
    expect(filterItems(filters, { language: 'en', market: 'DE' }, items).map((i) => i.id)).toEqual(['open']);
    expect(filterItems(filters, { language: 'en', market: 'HR' }, items).map((i) => i.id)).toEqual(['hr', 'open']);
    expect(paletteItems('hr', { language: 'en', market: 'DE' }, 'en', items).map((i) => i.id)).toEqual([]);
  });
});

describe('ranking in the popover', () => {
  const reader = { language: 'en', market: null };

  it('puts the reader language first, then kind, then free before paid', () => {
    const items = [
      item({ id: 'paid-course', access: 'paid' }),
      item({ id: 'de-course', contentLanguage: 'de' }),
      item({ id: 'article', kind: 'article' }),
      item({ id: 'checklist', kind: 'checklist' }),
      item({ id: 'free-course' }),
    ];
    expect(rankItems(items, reader).map((i) => i.id)).toEqual([
      'free-course',
      'paid-course',
      'checklist',
      'article',
      'de-course',
    ]);
  });

  it('puts the reader market before kind', () => {
    const items = [item({ id: 'course' }), item({ id: 'hr', kind: 'checklist', market: 'HR' })];
    expect(rankItems(items, { language: 'en', market: 'HR' }).map((i) => i.id)).toEqual(['hr', 'course']);
  });

  it('lists three rows at most and one paid item at most', () => {
    const items = [
      item({ id: 'p1', access: 'paid' }),
      item({ id: 'p2', access: 'paid' }),
      item({ id: 'f1', kind: 'checklist' }),
      item({ id: 'f2', kind: 'article' }),
      item({ id: 'f3', kind: 'article' }),
    ];
    const shown = itemsForScreen('/boq', reader, 3, items);
    expect(shown.map((i) => i.id)).toEqual(['p1', 'f1', 'f2']);
    expect(shown.filter((i) => i.access === 'paid')).toHaveLength(1);
  });

  it('skips items of other screens', () => {
    expect(itemsForScreen('/finance', reader, 3, [item({ id: 'x' })])).toEqual([]);
  });
});

describe('palette rows', () => {
  it('need two characters and a match, and stop at three', () => {
    const items = ['clash a', 'clash b', 'clash c', 'clash d', 'other'].map((title) => item({ id: title, title }));
    expect(paletteItems('c', { language: 'en', market: null }, 'en', items)).toEqual([]);
    expect(paletteItems('clash', { language: 'en', market: null }, 'en', items)).toHaveLength(3);
  });

  it('find the BIM course by "clash"', () => {
    const hits = paletteItems('clash', { language: 'en', market: null }, 'en', ACADEMY_ITEMS);
    expect(hits.some((i) => i.id === 'course:ashbrook-bim-clash-detection')).toBe(true);
  });
});
