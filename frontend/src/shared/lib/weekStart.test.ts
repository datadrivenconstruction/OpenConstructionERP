// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Does every offered language get the day its week actually starts on?
 *
 * The defect this pins was a one-line collapse. `localeWeekStart` in
 * FieldReportsPage read the real CLDR value out of `Intl` and then returned
 * `info.firstDay === 7 ? 0 : 1`, folding all six non-Sunday answers into
 * Monday. That is correct for 40 of the 42 languages we offer and wrong for
 * the two that start their week on Saturday, and because it is right for
 * 95% of the population it survived every reading of the code.
 *
 * The census below reads `SUPPORTED_LANGUAGES` from the shipped module
 * rather than listing the codes here. A test that retypes the list it is
 * checking proves that two copies agree, not that the shipped one is right,
 * and it would keep passing on the day a language is added.
 *
 * It prints the population beside the verdict on purpose. "The helper is
 * correct" means nothing without the denominator it was measured over, and a
 * suite that quietly narrowed to three languages would otherwise still
 * report a pass.
 *
 * There are two populations here, and the difference between them is the
 * second defect this file now pins. A language code is not the locale the
 * reader is in: the product resolves `ar` to `ar-SA` before it writes a
 * single date, and ICU gives that tag a different first day from the bare
 * code - Sunday rather than Saturday. Everything below therefore runs twice,
 * once over the codes and once over the tags they resolve to, because a
 * census that only knew the codes stayed green while the grid disagreed with
 * the dates printed above it.
 *
 * Arabic is the only language in that state today, measured over all of them
 * rather than assumed. English used to be the second, while plain `en`
 * resolved to `en-GB`; it stopped being one when `en` was made
 * region-neutral and `en-GB` became an entry a reader picks for themselves,
 * which resolves to itself and so cannot disagree with itself.
 */
import { afterAll, describe, expect, it } from 'vitest';
import i18next from 'i18next';

import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { LOCALE_MAP, getIntlLocale } from './intlLocale';
import {
  FALLBACK_FIRST_DAY,
  getWeekStartsOn,
  toWeekStartsOn,
  weekStartFor,
  weekStartsOnFor,
  type CldrFirstDay,
} from './weekStart';

/** The reference answer, read straight from ICU rather than from our helper. */
function cldrFirstDay(tag: string): number | undefined {
  const loc = new Intl.Locale(tag) as Intl.Locale & {
    getWeekInfo?: () => { firstDay?: number };
    weekInfo?: { firstDay?: number };
  };
  const info = typeof loc.getWeekInfo === 'function' ? loc.getWeekInfo() : loc.weekInfo;
  return info?.firstDay;
}

const DAY_NAME: Record<number, string> = {
  1: 'Monday',
  2: 'Tuesday',
  3: 'Wednesday',
  4: 'Thursday',
  5: 'Friday',
  6: 'Saturday',
  7: 'Sunday',
};

const CODES = SUPPORTED_LANGUAGES.map((l) => l.code);

/**
 * The locale tag each offered language actually resolves to.
 *
 * Read through `LOCALE_MAP` rather than by calling `getIntlLocale` in a loop,
 * because that function answers for whatever language i18next currently holds
 * and the census wants all of them at once. It is the same map that function
 * reads, so the tags are the app's own.
 */
const TAGS = CODES.map((code) => LOCALE_MAP[code] ?? code);

describe('week start, over every offered language', () => {
  it('has a language list to measure at all', () => {
    // The guard that keeps a green verdict honest. If the import ever yields
    // an empty or truncated list, every assertion below passes vacuously and
    // this suite becomes a no-op that reports success.
    expect(CODES.length, 'SUPPORTED_LANGUAGES came back empty').toBeGreaterThan(0);
    expect(
      CODES.length,
      `only ${CODES.length} languages parsed, the platform ships far more`,
    ).toBeGreaterThanOrEqual(40);
    expect(new Set(CODES).size, 'duplicate language codes').toBe(CODES.length);
  });

  it('at least one offered language genuinely starts its week on Saturday', () => {
    // The premise guard. This whole suite exists because a two-valued answer
    // cannot express Saturday. If ICU's data ever stopped putting any of our
    // languages on Saturday, the census below would keep passing while
    // testing nothing, and we would never learn the collapse had become
    // harmless. Better to go red and be told.
    const saturday = CODES.filter((c) => cldrFirstDay(c) === 6);
    expect(
      saturday.length,
      'no offered language starts on Saturday any more, so this suite no longer proves anything',
    ).toBeGreaterThan(0);
  });

  it('answers the real CLDR first day for every offered language', () => {
    const tally: Record<string, number> = {};
    const wrong: string[] = [];

    for (const code of CODES) {
      const expected = cldrFirstDay(code);
      const actual = weekStartFor(code);
      const name = DAY_NAME[expected ?? 0] ?? 'unknown';
      tally[name] = (tally[name] ?? 0) + 1;
      if (expected !== undefined && actual !== expected) {
        wrong.push(`${code}: wants ${name}(${expected}), helper said ${actual}`);
      }
    }

    const summary = Object.entries(tally)
      .sort((a, b) => b[1] - a[1])
      .map(([n, c]) => `${n} ${c}`)
      .join(', ');
    // Population beside the verdict, so a narrowed run cannot fake the
    // denominator.
    console.log(
      `[week start] ${CODES.length} languages offered: ${summary}. ` +
        `Correct: ${CODES.length - wrong.length}/${CODES.length}.`,
    );

    expect(wrong, `week start wrong for ${wrong.length} of ${CODES.length}`).toEqual([]);
  });

  it('does not collapse the answer to two values', () => {
    // The collapse this replaced returned only 0 or 1. Reintroducing it in
    // any form, here or at a call site, makes this red without depending on
    // which particular languages ICU puts on Saturday.
    const distinct = new Set(CODES.map((c) => weekStartsOnFor(c)));
    expect(
      distinct.size,
      `helper produced only ${distinct.size} distinct week starts across ${CODES.length} languages`,
    ).toBeGreaterThan(2);
    expect([...distinct].sort(), 'no language mapped to Saturday').toContain(6);
  });

  it('converts CLDR numbering to the getDay numbering at the boundary', () => {
    // The two conventions differ only at Sunday, which is exactly why mixing
    // them is easy and why one converter owns it.
    expect(toWeekStartsOn(7)).toBe(0);
    expect(toWeekStartsOn(1)).toBe(1);
    expect(toWeekStartsOn(6)).toBe(6);
    for (let d = 1; d <= 7; d += 1) {
      const converted = toWeekStartsOn(d as CldrFirstDay);
      expect(converted).toBeGreaterThanOrEqual(0);
      expect(converted).toBeLessThanOrEqual(6);
    }
  });

  it('has a fallback table that agrees with ICU for every offered language and tag', () => {
    // The map this replaced was unreachable on any engine implementing
    // weekInfo, so nothing ever contradicted it, and it had Arabic on Sunday
    // while the live path said Monday and generic Arabic is Saturday. Three
    // answers for one language. Checking the table against ICU here is what
    // stops it drifting back into being untested documentation.
    //
    // Over the tags as well as the codes, because on an engine with no week
    // data the tags are what `getWeekStartsOn` will hand this table, and one
    // of them - `ar-SA` - answers differently from the language it is a
    // region of. Asking only about codes would have let the fallback path sit
    // a day away from the `Intl` path for every Arabic reader. `en-GB` is in
    // the table for the same reason and is checked here too, but it arrives
    // as a code a reader picked rather than as something `en` resolved into.
    const wrong: string[] = [];
    const asked = [...new Set([...CODES, ...TAGS])];
    for (const locale of asked) {
      const expected = cldrFirstDay(locale);
      if (expected === undefined) continue;
      const exact = FALLBACK_FIRST_DAY[locale];
      const base = FALLBACK_FIRST_DAY[locale.split('-')[0] ?? ''];
      const viaFallback = exact ?? base ?? 1;
      if (viaFallback !== expected) {
        wrong.push(
          `${locale}: ICU says ${DAY_NAME[expected]}(${expected}), fallback says ${viaFallback}`,
        );
      }
    }
    // The denominator beside the verdict, as everywhere else in this file.
    console.log(
      `[week start] fallback checked over ${asked.length} locales ` +
        `(${CODES.length} codes, ${new Set(TAGS).size} distinct resolved tags).`,
    );
    expect(wrong, `fallback disagrees with ICU for ${wrong.length} locales`).toEqual([]);
  });

  it('answers Monday for an unknown or malformed tag rather than throwing', () => {
    expect(weekStartFor('zz')).toBe(1);
    expect(weekStartFor('not a tag!!')).toBe(1);
    expect(weekStartFor(undefined)).toBe(weekStartFor('en'));
    expect(weekStartFor('')).toBe(weekStartFor('en'));
  });
});

/* ── The grid and the dates above it come from one answer ─────────────────── */

/**
 * `getWeekStartsOn` resolves the language the way every other reader-facing
 * format does, through `getIntlLocale`.
 *
 * It used to read `i18next.language` raw, which is a second answer to the
 * question `intlLocale` exists to answer once. Nothing was red: the census
 * above measured bare codes, the helper agreed with ICU about those codes,
 * and the disagreement lived entirely in the gap between the code and the tag
 * the product had already chosen for it. An Arabic reader got Saudi dates
 * over a grid that began on Saturday.
 *
 * The named case below has to fail in both directions - red if the wiring is
 * reverted to the raw language, red if the resolution changes underneath and
 * nobody revisits this - so it states the tag's answer and denies the bare
 * code's. One row is all the product has: measured over every offered
 * language, Arabic is the only one whose code and resolved tag disagree about
 * the first day of the week. The row is therefore guarded rather than
 * trusted, and the assertion that actually holds the contract is the census
 * over the whole set at the end of this block.
 */
describe('the week start follows the resolved locale, not the raw language', () => {
  const originalLanguage = i18next.language;
  const setLanguage = (lang: string) => {
    (i18next as unknown as { language: string }).language = lang;
  };
  afterAll(() => setLanguage(originalLanguage));

  /** Language, the tag it resolves to, the bare code's rival answer. */
  const DIVERGING: [string, string, string][] = [
    ['ar', 'ar-SA', 'ar'],
  ];

  it('has languages whose code and tag genuinely disagree, or it proves nothing', () => {
    // Guards the guard. Every assertion below is "the tag wins over the code",
    // which is satisfied by anything at all on a pair that agrees. If ICU ever
    // stops splitting this one, this suite is measuring nothing and should be
    // told so rather than left green. The list is also asserted non-empty,
    // because it has already lost a member once - English, when `en` was made
    // region-neutral - and an empty table would leave every loop below
    // iterating nothing and passing.
    expect(DIVERGING.length).toBeGreaterThan(0);
    for (const [lang, tag, bare] of DIVERGING) {
      expect(LOCALE_MAP[lang], `${lang} no longer resolves to ${tag}`).toBe(tag);
      expect(
        cldrFirstDay(tag),
        `${tag} and ${bare} now start their week on the same day`,
      ).not.toBe(cldrFirstDay(bare));
    }
  });

  it.each(DIVERGING)('gives a %s reader the week %s starts, not the one %s starts', (lang, tag, bare) => {
    setLanguage(lang);
    expect(getIntlLocale()).toBe(tag);
    expect(getWeekStartsOn()).toBe(weekStartsOnFor(tag));
    expect(getWeekStartsOn()).not.toBe(weekStartsOnFor(bare));
  });

  it('agrees with the resolved locale for every offered language, not only the two', () => {
    // The population beside the verdict. Naming two languages fixes two
    // languages; the contract is that the grid and the tag never part company
    // for anybody, including whoever is added next.
    const wrong: string[] = [];
    for (const code of CODES) {
      setLanguage(code);
      const tag = getIntlLocale();
      const fromTag = weekStartsOnFor(tag);
      if (getWeekStartsOn() !== fromTag) {
        wrong.push(`${code} resolves to ${tag}, which starts ${fromTag}, but the app said ${getWeekStartsOn()}`);
      }
    }
    console.log(
      `[week start] grid follows the resolved tag for ${CODES.length - wrong.length}/${CODES.length} offered languages.`,
    );
    expect(wrong, `grid and dates disagree for ${wrong.length} languages`).toEqual([]);
  });
});
