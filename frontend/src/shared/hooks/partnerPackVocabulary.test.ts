// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The partner-pack vocabulary overlay.
 *
 * Two things here are easy to get wrong and invisible on screen when you do.
 *
 * The first is which code goes on the wire. A pack's locale file is a key of
 * ``additional_locales`` (``fr-CA``), while the language it is merged into is
 * the normalized one (``fr``). Fetching with the normalized code 404s, so the
 * assertions below check the request path, not just the resulting strings.
 *
 * The second is the clobber. ``loadLocaleResource`` merges a lazily fetched
 * locale chunk with ``overwrite=true``, so a chunk that lands after the overlay
 * silently erases the pack's words. That is reproduced literally: the test
 * writes a bundle the way ``loadLocaleResource`` writes one, and then asserts
 * the pack's words are still there.
 *
 * The real ``@/app/i18n`` singleton is used deliberately - ``normalizePackLocale``
 * and ``SUPPORTED_LANGUAGES`` are exactly what decides ``fr-CA`` -> ``fr``, and a
 * hand-written stand-in would assert the stand-in. Only the network is faked.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Only the network is faked. Everything else in the api module stays real —
// `@/app/i18n` pulls the module registry in behind it, and a half-populated
// stub would break imports that have nothing to do with this test.
vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(),
}));

import i18n from '@/app/i18n';
import { apiGet } from '@/shared/lib/api';

import {
  __resetPackVocabularyForTests,
  packVocabularyFrom,
  resolvePackVocabularyCode,
  revertPackVocabulary,
  syncPackVocabulary,
} from './partnerPackVocabulary';
import type { PartnerPackManifest } from './usePartnerPack';

const mockedApiGet = vi.mocked(apiGet);

function manifest(overrides: Partial<PartnerPackManifest> = {}): PartnerPackManifest {
  return {
    slug: 'batimatech-ca',
    partner_name: 'Test Partner',
    partner_url: null,
    pack_version: '1.0.0',
    description: '',
    default_locale: 'fr-CA',
    additional_locales: ['en-CA', 'fr-CA'],
    cwicr_regions: [],
    default_currency: 'CAD',
    default_tax_template: null,
    validation_rule_packs: [],
    validation_rule_sets: [],
    default_modules: [],
    hidden_modules: [],
    branding: {
      primary_color: '#000000',
      accent_color: null,
      has_logo: false,
      has_favicon: false,
      powered_by_text: '',
    },
    has_onboarding_script: false,
    metadata: {},
    ...overrides,
  };
}

/** Write a bundle exactly the way ``loadLocaleResource`` writes a locale chunk. */
function writeLocaleChunk(language: string, entries: Record<string, string>): void {
  i18n.addResourceBundle(language, 'translation', entries, false, true);
}

function bundleValue(language: string, key: string): string | undefined {
  const stored = i18n.store.data[language];
  const bundle = stored === undefined ? undefined : stored.translation;
  if (bundle === undefined || typeof bundle !== 'object') return undefined;
  return (bundle as Record<string, string>)[key];
}

/** Languages this file seeds, torn down so no test inherits another's store. */
const SEEDED = ['fr', 'de'];

beforeEach(() => {
  mockedApiGet.mockReset();
});

afterEach(() => {
  __resetPackVocabularyForTests();
  // Not ``removeResourceBundle``: that also drops 'translation' from the
  // instance's namespace list, which would take the rest of the file with it.
  for (const language of SEEDED) {
    const stored = i18n.store.data[language];
    if (stored !== undefined) delete stored.translation;
  }
});

describe('packVocabularyFrom', () => {
  it('reads the {_meta, translation} envelope most packs ship', () => {
    expect(
      packVocabularyFrom({
        _meta: { locale: 'fr-CA', fallback: 'en' },
        translation: { 'nav.boq': 'Bordereau de quantités' },
      }),
    ).toEqual({ 'nav.boq': 'Bordereau de quantités' });
  });

  it('reads a flat file that keeps its metadata under _meta', () => {
    expect(
      packVocabularyFrom({
        _meta: { locale: 'de' },
        'gaeb.title': 'GAEB Datenaustausch',
      }),
    ).toEqual({ 'gaeb.title': 'GAEB Datenaustausch' });
  });

  it('reads a flat file that keeps its metadata under $-prefixed fields', () => {
    expect(
      packVocabularyFrom({
        $schema_note: 'x',
        $locale: 'de',
        'common.formwork': 'Schalung',
      }),
    ).toEqual({ 'common.formwork': 'Schalung' });
  });

  it('drops non-string values rather than passing them to i18next', () => {
    expect(packVocabularyFrom({ translation: { a: 'ok', b: { c: 'nested' }, d: 3 } })).toEqual({
      a: 'ok',
    });
  });

  it('answers an empty map for anything that is not an object', () => {
    expect(packVocabularyFrom(null)).toEqual({});
    expect(packVocabularyFrom('not json')).toEqual({});
    expect(packVocabularyFrom(undefined)).toEqual({});
  });
});

describe('resolvePackVocabularyCode', () => {
  it('finds the regional file for the base language it normalizes to', () => {
    // fr-CA is not in SUPPORTED_LANGUAGES, so the UI language is fr — and the
    // pack file that belongs to that language is still called fr-CA.
    expect(resolvePackVocabularyCode(['en-CA', 'fr-CA'], 'fr-CA', 'fr')).toBe('fr-CA');
    expect(resolvePackVocabularyCode(['en-NZ'], 'en-NZ', 'en')).toBe('en-NZ');
    expect(resolvePackVocabularyCode(['en-AU'], 'en-AU', 'en')).toBe('en-AU');
  });

  it('gives a region the UI ships its own file rather than the base language’s', () => {
    // en-GB used to belong in the case above, because the UI shipped no
    // British entry and uk-jct's file was merged into plain English. Now that
    // English (UK) is offered, the pack's file follows the reader who picked
    // it and stops reaching the reader who did not. Both halves are asserted:
    // without the second, folding en-GB back onto `en` would pass.
    expect(resolvePackVocabularyCode(['en-GB'], 'en-GB', 'en-GB')).toBe('en-GB');
    expect(resolvePackVocabularyCode(['en-GB'], 'en-GB', 'en')).toBeNull();
  });

  it('serves the pack’s second file when the user picks that language', () => {
    // batimatech-ca ships en-CA as well; india-cpwd ships only hi under an
    // English default. Both are unreachable if the overlay is bound to the
    // activation-time language instead of the current one.
    expect(resolvePackVocabularyCode(['en-CA', 'fr-CA'], 'fr-CA', 'en')).toBe('en-CA');
    expect(resolvePackVocabularyCode(['hi'], 'en', 'hi')).toBe('hi');
  });

  it('leaves a plain base-language pack exactly as it resolves today', () => {
    // bimhessen-de and doker-formwork declare `de` with no region at all. The
    // inheritance that already works must keep working.
    expect(resolvePackVocabularyCode(['de'], 'de', 'de')).toBe('de');
    expect(resolvePackVocabularyCode(['de'], 'de', 'en')).toBeNull();
  });

  it('answers null when the pack ships nothing for this language', () => {
    expect(resolvePackVocabularyCode([], 'en-GB', 'en')).toBeNull();
    expect(resolvePackVocabularyCode(['en-GB'], 'en-GB', 'ja')).toBeNull();
  });

  it('prefers an exact code, then the pack default, over sort order', () => {
    expect(resolvePackVocabularyCode(['es-419', 'es'], 'es-419', 'es')).toBe('es');
    // Neither is exact: es-CL and es-CO are both shipped by the UI, so make the
    // tie-break visible on codes that really do collapse to the same language.
    // en-AU and en-NZ are that pair now - the previous one used en-GB, which
    // stopped collapsing to `en` when English (UK) joined the picker, so the
    // tie it demonstrated no longer existed.
    expect(resolvePackVocabularyCode(['en-AU', 'en-NZ'], 'en-NZ', 'en')).toBe('en-NZ');
  });
});

describe('syncPackVocabulary', () => {
  it('fetches the pack’s own locale code, not the language it merges into', async () => {
    mockedApiGet.mockResolvedValue({ translation: { 'nav.boq': 'Bordereau de quantités' } });
    writeLocaleChunk('fr', { 'nav.boq': 'Devis quantitatif' });

    await syncPackVocabulary(manifest(), 'fr');

    expect(mockedApiGet).toHaveBeenCalledTimes(1);
    expect(mockedApiGet).toHaveBeenCalledWith('/v1/partner-pack/locale/fr-CA');
    expect(bundleValue('fr', 'nav.boq')).toBe('Bordereau de quantités');
  });

  it('issues no request for a pack that ships no locale file', async () => {
    await syncPackVocabulary(manifest({ additional_locales: [], default_locale: 'en-US' }), 'en');
    expect(mockedApiGet).not.toHaveBeenCalled();
  });

  it('issues no request when nothing the pack ships matches the language', async () => {
    await syncPackVocabulary(manifest({ additional_locales: ['de'], default_locale: 'de' }), 'fr');
    expect(mockedApiGet).not.toHaveBeenCalled();
  });

  it('leaves the base locale intact when the declared file is missing', async () => {
    // china-gbt50500 declares locales/zh.json and does not ship it, so this
    // 404 is the tree as it stands, not a hypothetical.
    mockedApiGet.mockRejectedValue(new Error('404 Not Found'));
    writeLocaleChunk('de', { 'gaeb.title': 'GAEB XML 3.3 Import / Export' });

    await expect(
      syncPackVocabulary(manifest({ slug: 'china-gbt50500', additional_locales: ['de'], default_locale: 'de' }), 'de'),
    ).resolves.toBeUndefined();

    expect(bundleValue('de', 'gaeb.title')).toBe('GAEB XML 3.3 Import / Export');
  });

  it('survives a locale chunk that lands on top of it afterwards', async () => {
    mockedApiGet.mockResolvedValue({ translation: { 'nav.boq': 'Bordereau de quantités' } });
    await syncPackVocabulary(manifest(), 'fr');
    expect(bundleValue('fr', 'nav.boq')).toBe('Bordereau de quantités');

    // The lazy fr chunk resolves now, overwrite=true, straight over our keys.
    writeLocaleChunk('fr', { 'nav.boq': 'Devis quantitatif', 'nav.costs': 'Base de données de coûts' });

    expect(bundleValue('fr', 'nav.boq')).toBe('Bordereau de quantités');
    expect(bundleValue('fr', 'nav.costs')).toBe('Base de données de coûts');
  });

  it('changes what t() answers, not merely what the store holds', async () => {
    // The store assertions above prove the bundle was written. This one walks
    // the resolution path a component actually uses: `useTranslation().t`
    // delegates straight to `i18n.t`. `nav.coordination_hub` is the sidebar
    // entry for /coordination (navCatalog.ts) and that page's breadcrumb
    // (CoordinationHubPage.tsx), so this is a pack's reading of a string an
    // nzs user has in front of them.
    //
    // nzs rather than uk-jct, which this used to name: uk-jct declares en-GB,
    // and en-GB became a UI language of its own, so its overlay now lands on
    // the en-GB bundle rather than on this one. en-NZ still has no entry in
    // SUPPORTED_LANGUAGES and so still normalizes to `en`, which is the shape
    // this test is about.
    expect(i18n.t('nav.coordination_hub')).toBe('Coordination Hub');

    mockedApiGet.mockResolvedValue({
      translation: { 'nav.coordination_hub': 'Coordination Centre' },
    });
    await syncPackVocabulary(
      manifest({ slug: 'nzs', additional_locales: ['en-NZ'], default_locale: 'en-NZ' }),
      'en',
    );

    expect(i18n.t('nav.coordination_hub')).toBe('Coordination Centre');

    revertPackVocabulary();
    expect(i18n.t('nav.coordination_hub')).toBe('Coordination Hub');
  });

  it('does not re-fetch a locale it has already applied', async () => {
    mockedApiGet.mockResolvedValue({ translation: { 'nav.boq': 'Bordereau de quantités' } });
    await syncPackVocabulary(manifest(), 'fr');
    await syncPackVocabulary(manifest(), 'fr');
    expect(mockedApiGet).toHaveBeenCalledTimes(1);
  });
});

describe('revertPackVocabulary', () => {
  it('restores the string the pack displaced', async () => {
    writeLocaleChunk('fr', { 'nav.boq': 'Devis quantitatif' });
    mockedApiGet.mockResolvedValue({ translation: { 'nav.boq': 'Bordereau de quantités' } });

    await syncPackVocabulary(manifest(), 'fr');
    expect(bundleValue('fr', 'nav.boq')).toBe('Bordereau de quantités');

    revertPackVocabulary();
    expect(bundleValue('fr', 'nav.boq')).toBe('Devis quantitatif');
  });

  it('deletes a key the pack introduced rather than leaving it behind', async () => {
    writeLocaleChunk('fr', { 'nav.boq': 'Devis quantitatif' });
    mockedApiGet.mockResolvedValue({
      translation: { 'partner_pack.header_chip': 'Édition Québec' },
    });

    await syncPackVocabulary(manifest(), 'fr');
    expect(bundleValue('fr', 'partner_pack.header_chip')).toBe('Édition Québec');

    revertPackVocabulary();
    expect(bundleValue('fr', 'partner_pack.header_chip')).toBeUndefined();
    expect(bundleValue('fr', 'nav.boq')).toBe('Devis quantitatif');
  });

  it('restores the pre-chunk value, not its own words, after a clobber round-trip', async () => {
    // The snapshot must survive the re-merge that follows a late chunk, or
    // deactivation writes the pack's own strings back as if they were the
    // originals.
    writeLocaleChunk('fr', { 'nav.boq': 'Devis quantitatif' });
    mockedApiGet.mockResolvedValue({ translation: { 'nav.boq': 'Bordereau de quantités' } });
    await syncPackVocabulary(manifest(), 'fr');

    writeLocaleChunk('fr', { 'nav.boq': 'Devis quantitatif' });
    expect(bundleValue('fr', 'nav.boq')).toBe('Bordereau de quantités');

    revertPackVocabulary();
    expect(bundleValue('fr', 'nav.boq')).toBe('Devis quantitatif');
  });

  it('undoes an overlay that was merged into English', async () => {
    // aus and nzs both normalize to `en`, and resetPackLocale switching the
    // app to English cannot undo them - English never reloads. uk-jct was on
    // that list until en-GB became a UI language of its own; its overlay now
    // lands on the en-GB bundle instead, which is a different arrangement and
    // not the one this test is about.
    const before = bundleValue('en', 'nav.coordination_hub');
    mockedApiGet.mockResolvedValue({
      translation: { 'nav.coordination_hub': 'Coordination Centre' },
    });

    await syncPackVocabulary(
      manifest({ slug: 'nzs', additional_locales: ['en-NZ'], default_locale: 'en-NZ' }),
      'en',
    );
    expect(bundleValue('en', 'nav.coordination_hub')).toBe('Coordination Centre');

    revertPackVocabulary();
    expect(bundleValue('en', 'nav.coordination_hub')).toBe(before);
  });
});

describe('switching from one pack to another', () => {
  // nzs and aus both normalize to `en`, so their overlays land on the same
  // bundle. nzs renames the subcontractor screen and aus does not, which is
  // exactly the shape that leaks: applying a pack does not reload the app, so
  // the outgoing pack's words are still live when the next one arrives.
  //
  // The pair used to be uk-jct and aus. uk-jct declares en-GB, and en-GB is a
  // UI language now, so it no longer shares a bundle with the Australasian
  // packs and cannot demonstrate a collision on one. The pair has to be two
  // packs whose regions the UI does NOT ship, or the test is measuring
  // nothing; en-NZ and en-AU are both in that state.
  const nzs = manifest({ slug: 'nzs', additional_locales: ['en-NZ'], default_locale: 'en-NZ' });
  const aus = manifest({ slug: 'aus', additional_locales: ['en-AU'], default_locale: 'en-AU' });

  it('takes the outgoing pack’s words off screen instead of merging on top', async () => {
    const beforeHub = bundleValue('en', 'nav.coordination_hub');
    const beforeSubs = bundleValue('en', 'nav.subcontractors');

    mockedApiGet.mockResolvedValueOnce({
      translation: {
        'nav.coordination_hub': 'Coordination Centre',
        'nav.subcontractors': 'Subcontractors',
      },
    });
    await syncPackVocabulary(nzs, 'en');
    expect(bundleValue('en', 'nav.subcontractors')).toBe('Subcontractors');

    // The Australian pack says nothing about subcontractors, so that key has to
    // go back to the app's own English rather than keep the New Zealand wording.
    mockedApiGet.mockResolvedValueOnce({
      translation: { 'nav.coordination_hub': 'Coordination Centre' },
    });
    await syncPackVocabulary(aus, 'en');

    expect(bundleValue('en', 'nav.subcontractors')).toBe(beforeSubs);
    expect(bundleValue('en', 'nav.coordination_hub')).toBe('Coordination Centre');

    revertPackVocabulary();
    expect(bundleValue('en', 'nav.coordination_hub')).toBe(beforeHub);
    expect(bundleValue('en', 'nav.subcontractors')).toBe(beforeSubs);
  });

  it('clears the outgoing pack even when the incoming one ships nothing for this language', async () => {
    // The hole the same-language case cannot reach. batimatech-ca is active
    // with French vocabulary on screen; the user applies nzs, which ships
    // only en-NZ. That resolves to no file for `fr`, so nothing would merge and
    // an early return would leave Quebec wording under the incoming pack.
    const before = bundleValue('fr', 'nav.boq');
    mockedApiGet.mockResolvedValueOnce({
      translation: { 'nav.boq': 'Bordereau de quantités' },
    });
    await syncPackVocabulary(manifest(), 'fr');
    expect(bundleValue('fr', 'nav.boq')).toBe('Bordereau de quantités');

    await syncPackVocabulary(nzs, 'fr');
    expect(bundleValue('fr', 'nav.boq')).toBe(before);
  });

  it('reverts to the original wording after a swap, not to the first pack’s', async () => {
    const before = bundleValue('en', 'nav.phase_estimation');

    mockedApiGet.mockResolvedValueOnce({ translation: { 'nav.phase_estimation': 'Estimating' } });
    await syncPackVocabulary(nzs, 'en');
    mockedApiGet.mockResolvedValueOnce({ translation: { 'nav.phase_estimation': 'Pricing' } });
    await syncPackVocabulary(aus, 'en');
    expect(bundleValue('en', 'nav.phase_estimation')).toBe('Pricing');

    revertPackVocabulary();
    expect(bundleValue('en', 'nav.phase_estimation')).toBe(before);
  });
});
