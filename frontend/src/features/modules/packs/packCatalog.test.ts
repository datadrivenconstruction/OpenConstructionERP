import { describe, expect, it } from 'vitest';
import {
  EMPTY_PACK_FILTERS,
  buildPackEntries,
  filterPackEntries,
  groupPackEntries,
  hasActivePackFilters,
  packFacetCounts,
  packLanguages,
  packStandards,
  parsePackFilters,
  writePackFilters,
  type PackFilters,
  type PackManifest,
} from './packCatalog';

function pack(slug: string, over: Partial<PackManifest> = {}): PackManifest {
  return {
    slug,
    type: 'country',
    partner_name: slug,
    partner_url: null,
    pack_version: '1.0.0',
    description: '',
    default_locale: 'en',
    additional_locales: [],
    cwicr_regions: [],
    default_currency: 'EUR',
    default_tax_template: null,
    validation_rule_packs: [],
    default_modules: [],
    hidden_modules: [],
    branding: { primary_color: '#000', accent_color: null, has_logo: false, has_favicon: false, powered_by_text: '' },
    has_onboarding_script: false,
    metadata: {},
    ...over,
  };
}

const PACKS: PackManifest[] = [
  pack('de-germany', {
    partner_name: 'Germany',
    default_locale: 'de-DE',
    metadata: { country: 'DE', classification_standard: 'din276' },
    validation_rule_sets: ['gaeb', 'project_governance'],
  }),
  pack('at-austria', { partner_name: 'Österreich', default_locale: 'de-AT', metadata: { country: 'AT' } }),
  pack('us-usa', {
    partner_name: 'United States',
    default_locale: 'en-US',
    additional_locales: ['es-US'],
    default_currency: 'USD',
    metadata: { country: 'US', classification_standard: 'masterformat' },
    default_modules: ['boq', 'costs'],
  }),
  pack('cn-china', { partner_name: 'China', default_locale: 'zh-CN', default_currency: 'CNY', metadata: { country: 'CN' } }),
  pack('jp-japan', { partner_name: 'Japan', default_locale: 'ja-JP', default_currency: 'JPY', metadata: { country: 'JP' } }),
  pack('infra', { type: 'industry', partner_name: 'Infrastructure', default_locale: 'en' }),
  pack('acme', { type: 'partner', partner_name: 'Acme Builders', default_locale: 'en-GB', metadata: { country: 'GB' } }),
  pack('demo', { type: 'showcase', partner_name: 'Showcase tower', default_locale: 'en', demo_template_ids: ['a', 'b'] }),
];

const entries = (home: string | null = null) =>
  buildPackEntries(PACKS, {
    nameOf: (p) => p.partner_name,
    countryNameOf: (iso) => ({ de: 'Deutschland', at: 'Österreich', us: 'Vereinigte Staaten' })[iso] ?? null,
    homeCountry: home,
  });

const f = (patch: Partial<PackFilters>): PackFilters => ({ ...EMPTY_PACK_FILTERS, ...patch });
const slugs = (list: { slug: string }[]) => list.map((e) => e.slug);

describe('pack facts', () => {
  it('lists recognised standards, classification first, and drops non-standard rule sets', () => {
    expect(packStandards(PACKS[0]!)).toEqual(['DIN 276', 'GAEB']);
  });

  it('reduces locales to base languages without repeats', () => {
    expect(packLanguages(pack('x', { default_locale: 'en-US', additional_locales: ['es-US', 'en_GB'] }))).toEqual([
      'en',
      'es',
    ]);
  });

  it('counts modules only when the pack switches a set on, and demo projects', () => {
    const list = entries();
    expect(list.find((e) => e.slug === 'us-usa')?.moduleCount).toBe(2);
    expect(list.find((e) => e.slug === 'de-germany')?.moduleCount).toBeNull();
    expect(list.find((e) => e.slug === 'demo')?.demoCount).toBe(2);
  });
});

describe('URL state', () => {
  it('round-trips every filter and keeps foreign params', () => {
    const filters = f({ q: 'din', types: ['industry', 'country'], region: 'europe', lang: 'de', status: 'active', sort: 'name' });
    const params = writePackFilters(new URLSearchParams('tab=packs'), filters);
    expect(params.get('tab')).toBe('packs');
    expect(params.get('type')).toBe('country,industry');
    expect(parsePackFilters(params)).toEqual({ ...filters, types: ['country', 'industry'] });
  });

  it('omits defaults so the plain page keeps a plain URL', () => {
    expect(writePackFilters(new URLSearchParams(), EMPTY_PACK_FILTERS).toString()).toBe('');
  });

  it('drops unknown values instead of trusting a hand-edited link', () => {
    const parsed = parsePackFilters(new URLSearchParams('type=bogus,partner&region=mars&lang=x1&status=gone&sort=random'));
    expect(parsed).toEqual(f({ types: ['partner'] }));
  });

  it('does not count sort as a filter', () => {
    expect(hasActivePackFilters(f({ sort: 'region' }))).toBe(false);
    expect(hasActivePackFilters(f({ q: '  ' }))).toBe(false);
    expect(hasActivePackFilters(f({ lang: 'de' }))).toBe(true);
  });
});

describe('filtering', () => {
  const list = entries();

  it('searches name, translated country, currency, language and standard, accent-folded', () => {
    expect(slugs(filterPackEntries(list, f({ q: 'osterreich' }), null))).toEqual(['at-austria']);
    expect(slugs(filterPackEntries(list, f({ q: 'deutschland' }), null))).toEqual(['de-germany']);
    expect(slugs(filterPackEntries(list, f({ q: 'jpy' }), null))).toEqual(['jp-japan']);
    expect(slugs(filterPackEntries(list, f({ q: 'masterformat' }), null))).toEqual(['us-usa']);
    expect(slugs(filterPackEntries(list, f({ q: 'din 276' }), null))).toEqual(['de-germany']);
  });

  it('combines type, region, language and status', () => {
    expect(slugs(filterPackEntries(list, f({ types: ['industry', 'showcase'] }), null))).toEqual(['infra', 'demo']);
    expect(slugs(filterPackEntries(list, f({ region: 'europe' }), null))).toEqual(['de-germany', 'at-austria', 'acme']);
    expect(slugs(filterPackEntries(list, f({ region: 'europe', lang: 'de' }), null))).toEqual([
      'de-germany',
      'at-austria',
    ]);
    expect(slugs(filterPackEntries(list, f({ status: 'active' }), 'us-usa'))).toEqual(['us-usa']);
    expect(filterPackEntries(list, f({ status: 'available' }), 'us-usa')).toHaveLength(PACKS.length - 1);
  });

  it('counts each facet against the other filters, not itself', () => {
    const counts = packFacetCounts(list, f({ types: ['country'] }), 'de-germany');
    // Type chips still show what switching would find.
    expect(counts.types).toEqual({ country: 5, industry: 1, partner: 1, showcase: 1 });
    expect(counts.regions.europe).toBe(2);
    expect(counts.langs.get('de')).toBe(2);
    expect(counts.status).toEqual({ active: 1, available: 4 });
  });

  it('filters a few hundred packs quickly', () => {
    const many = buildPackEntries(
      Array.from({ length: 400 }, (_, i) => pack(`p${i}`, { partner_name: `Pack ${i}`, metadata: { country: 'FR' } })),
      { nameOf: (p) => p.partner_name },
    );
    const start = performance.now();
    for (let i = 0; i < 50; i += 1) filterPackEntries(many, f({ q: `pack ${i}` }), null);
    expect(performance.now() - start).toBeLessThan(500);
  });
});

describe('grouping', () => {
  it('puts the reader’s own market first when recommended', () => {
    const groups = groupPackEntries(entries('at'), 'recommended', 'en');
    expect(groups.map((g) => g.id)).toEqual(['home', 'americas', 'china', 'europe', 'rest', 'cross-region']);
    expect(slugs(groups[0]!.entries)).toEqual(['at-austria']);
  });

  it('groups by region without the guess and sorts by country inside', () => {
    const groups = groupPackEntries(entries('at'), 'region', 'en');
    expect(groups.map((g) => g.id)).not.toContain('home');
    expect(slugs(groups.find((g) => g.id === 'europe')!.entries)).toEqual(['de-germany', 'at-austria', 'acme']);
  });

  it('draws one flat A-Z list when sorted by name', () => {
    const groups = groupPackEntries(entries(), 'name', 'en');
    expect(groups).toHaveLength(1);
    expect(groups[0]!.id).toBe('all');
    expect(groups[0]!.entries[0]!.name).toBe('Acme Builders');
  });

  it('returns no sections for no packs', () => {
    expect(groupPackEntries([], 'name')).toEqual([]);
    expect(groupPackEntries([], 'recommended')).toEqual([]);
  });
});
