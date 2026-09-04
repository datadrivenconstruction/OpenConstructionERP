// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The list of languages we offer and the list every locale test iterates must
 * not drift apart.
 *
 * ``i18n-fallbacks.ts`` aggregates the per-locale resources so that tests can
 * iterate the locales without repeating forty imports. A locale missing from it
 * is not offered any less; it is simply invisible to every test that iterates
 * the object, which is how Kyrgyz, Greek and Ukrainian each went unchecked
 * while shipping.
 *
 * That file already carried a comment telling whoever enabled Uzbek to add the
 * import in the same commit. Uzbek was enabled, the import was not added, and
 * the locale shipped unchecked anyway. This test exists because a comment
 * recording a rule cannot enforce it.
 *
 * Both directions matter, so both are asserted. A language added to
 * ``SUPPORTED_LANGUAGES`` and forgotten here fails the first assertion; a
 * locale added here that nobody can select fails the second. Writing them as
 * exact set differences rather than as counts is deliberate: a count passes
 * again the moment two mistakes cancel out.
 */

import { describe, expect, it } from 'vitest';

import { SUPPORTED_LANGUAGES } from '../i18n';
import { fallbackResources } from '../i18n-fallbacks';

/**
 * Offered, but deliberately not aggregated.
 *
 * ``en-US`` is an overrides-only overlay rather than a full locale, so a test
 * that iterates the object would compare a deliberate ~1.6k key file against a
 * ~35k key one and report a gap that is the whole point of the file.
 */
const OFFERED_BUT_NOT_AGGREGATED = ['en-US'];

/**
 * Aggregated, but deliberately not offered.
 *
 * ``mn`` is kept here so the Mongolian file holds whatever coverage it has
 * while it waits for a native-speaker pass. It is the only locale in that
 * state; ``hu`` is not aggregated because it is not offered and has no
 * coverage to keep yet.
 */
const AGGREGATED_BUT_NOT_OFFERED = ['mn'];

describe('the offered languages and the fallback aggregator', () => {
  const offered = new Set(SUPPORTED_LANGUAGES.map((language) => language.code));
  const aggregated = new Set(Object.keys(fallbackResources));

  it('leaves no offered language out of the aggregator except the named overlay', () => {
    const missing = [...offered].filter((code) => !aggregated.has(code)).sort();

    expect(missing).toEqual([...OFFERED_BUT_NOT_AGGREGATED].sort());
  });

  it('aggregates nothing a user cannot select except the one waiting on review', () => {
    const extra = [...aggregated].filter((code) => !offered.has(code)).sort();

    expect(extra).toEqual([...AGGREGATED_BUT_NOT_OFFERED].sort());
  });

  it('names each exception rather than merely counting them', () => {
    // The counts are the weakest form of this check and are asserted only to
    // catch a rewrite that empties one of the lists above and leaves the two
    // set comparisons trivially true.
    expect(OFFERED_BUT_NOT_AGGREGATED).toHaveLength(1);
    expect(AGGREGATED_BUT_NOT_OFFERED).toHaveLength(1);
    expect(offered.size).toBeGreaterThan(40);
    expect(aggregated.size).toBeGreaterThan(40);
  });
});
