// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeAll, describe, expect, it, vi } from 'vitest';

/**
 * A regional variant has to actually *download* the language it falls back to.
 *
 * `i18n.ts` has named the chain for a long time - `fallbackLng` maps es-MX to
 * ['es', 'en'] - and that map was correct and inert. It names a bundle; it does
 * not fetch one. `loadLocaleResource` imported the chunk for the code it was
 * given and nothing else, so an es-MX reader's lookup walked es-MX, then an `es`
 * bucket that was never loaded, then landed on English. The ~2700 `cases.*` keys
 * that `es.ts` carries and `es-MX.ts` does not rendered in English while a
 * complete Spanish translation sat in a chunk nobody requested. es-CL, es-CO and
 * pt-BR were all in the same position.
 *
 * `enUSFallsBackToEnglish.test.ts` could not catch this, and the reason is worth
 * keeping: it hand-adds both bundles and then asserts i18next's resolution order.
 * Resolution order was never the broken part. It is also the one variant whose
 * base is `en`, which ships in the main bundle and is in `loadedLocales` from the
 * start - so the only variant with a test was the only variant that worked.
 *
 * This file therefore probes the *store* after calling the real loader, which is
 * the thing only the loader change can produce, and only then checks resolution
 * in both directions.
 *
 * Every locale chunk is mocked. `localeKeyResolution.test.ts` records why the real
 * ones cannot be used: they are megabytes of object literal and handing one to the
 * vitest transform pipeline times the worker out - measured here at ~55s for
 * `en.ts` alone, which killed the pool worker outright before any assertion ran.
 * The stubs are shaped exactly the way a locale file is shaped, one `translation`
 * member of flat dotted keys, so `loadLocaleResource` consumes them by the same
 * path it consumes the real thing. That keeps the subject of the test where it
 * belongs: which chunks the loader decides to fetch, not what any language says.
 *
 * The fixtures go through `vi.hoisted` because `vi.mock` factories are hoisted
 * above ordinary `const` declarations, and `../i18n` imports `./locales/en`
 * statically - a plain const would still be in its temporal dead zone when that
 * factory runs.
 */

const { ONLY_IN_ES, IN_BOTH, ES, ES_MX, EN } = vi.hoisted(() => {
  const onlyInEs = 'cases.__probe_only_in_es';
  const inBoth = 'cases.__probe_in_both';
  // Annotated rather than inferred. A bare object literal keyed by these two
  // consts gets the narrow type `{ "cases.__probe_in_both": string }`, and then
  // reading it back with a `string`-typed key is an implicit any that `tsc -b`
  // rejects under strict mode. `Record<string, string>` is also the shape
  // `addResourceBundle` is handed, so it is the honest annotation here.
  /** Peninsular Spanish. Uses the Spain words for formwork and for cost. */
  const es: Record<string, string> = {
    [onlyInEs]: 'Encofrado y coste de la partida',
    [inBoth]: 'Certificacion de obra',
  };
  /** Mexican Spanish. Names the shared item the way Mexican practice names it. */
  const esMx: Record<string, string> = {
    [inBoth]: 'Estimacion de obra',
  };
  /** Final fallback. Only has to exist and be shaped right. */
  const en: Record<string, string> = {
    [onlyInEs]: 'Formwork and cost of the item',
    [inBoth]: 'Payment certificate',
  };
  return { ONLY_IN_ES: onlyInEs, IN_BOTH: inBoth, ES: es, ES_MX: esMx, EN: en };
});

vi.mock('../locales/es.ts', () => ({ default: { translation: ES } }));
vi.mock('../locales/es-MX.ts', () => ({ default: { translation: ES_MX } }));
vi.mock('../locales/en-US.ts', () => ({ default: { translation: {} } }));
vi.mock('../locales/en', () => ({ default: { translation: EN } }));

// Imported statically, not inside the hook: the module-level cost of `i18n.ts` is
// paid during collection, which is not charged against the 10s hook timeout.
import i18n, { loadLocaleResource } from '../i18n';

beforeAll(async () => {
  await loadLocaleResource('es-MX');
});

describe('a regional variant loads the base language it falls back to', () => {
  it('puts the base bundle in the store, not just in the fallback map', () => {
    // Asserted on the bundle's actual contents, not with `hasResourceBundle`.
    // That was the first thing written here and it passed against the unfixed
    // loader: i18next's `getResourceBundle` spreads a missing bundle into `{}`,
    // so the "is it there" question answers yes for a bucket nobody filled. The
    // key itself is the only form of the question that can come back no.
    const bundle = i18n.getResourceBundle('es', 'translation') as Record<string, string>;
    expect(bundle?.[ONLY_IN_ES]).toBe(ES[ONLY_IN_ES]);
  });

  it('still loads the variant itself', () => {
    const bundle = i18n.getResourceBundle('es-MX', 'translation') as Record<string, string>;
    expect(bundle?.[IN_BOTH]).toBe(ES_MX[IN_BOTH]);
  });

  // Direction one: the fallback fires at all.
  it('answers a key only Spain defines with the Spanish string', () => {
    // No `defaultValue` anywhere in this file. Every call site in the app passes
    // one, which is exactly why this defect was invisible on screen: a key that
    // resolves and a key that fails render the same English text. Without a
    // default, a failed lookup returns the key itself and the two outcomes differ.
    expect(i18n.t(ONLY_IN_ES, { lng: 'es-MX' })).toBe(ES[ONLY_IN_ES]);
    expect(i18n.t(ONLY_IN_ES, { lng: 'es-MX' })).not.toBe(EN[ONLY_IN_ES]);
  });

  // Direction two: the fallback is a fallback and not a replacement. This is the
  // half that catches a chain wired backwards, which would quietly overwrite
  // deliberate Mexican wording with peninsular Spanish while everything stayed
  // green - the variants exist precisely because a quantity surveyor in Mexico
  // City does not call it a `certificacion de obra`.
  it('keeps the Mexican wording for a key both files define', () => {
    expect(i18n.t(IN_BOTH, { lng: 'es-MX' })).toBe(ES_MX[IN_BOTH]);
    expect(i18n.t(IN_BOTH, { lng: 'es-MX' })).not.toBe(ES[IN_BOTH]);
  });

  it('has a probe that could tell the two apart in the first place', () => {
    // Guards the test itself: if these ever became equal the direction-two
    // assertion above would pass for the wrong reason.
    expect(ES[IN_BOTH]).not.toBe(ES_MX[IN_BOTH]);
    expect(ES[ONLY_IN_ES]).not.toBe(EN[ONLY_IN_ES]);
  });

  it('asks for no second chunk when the base is the bundled English one', async () => {
    // en-US derives base `en`, which is seeded into `loadedLocales` and ships in
    // the main bundle. Nothing extra should be fetched for it. Named here so the
    // `'en'` seed cannot be dropped later without a test going red.
    await expect(loadLocaleResource('en-US')).resolves.toBeUndefined();
    const bundle = i18n.getResourceBundle('en', 'translation') as Record<string, string>;
    expect(bundle?.[IN_BOTH]).toBe(EN[IN_BOTH]);
  });
});
