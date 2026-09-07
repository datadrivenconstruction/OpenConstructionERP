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
 */
import { describe, expect, it } from 'vitest';

import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import {
  FALLBACK_FIRST_DAY,
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

  it('has a fallback table that agrees with ICU for every offered language', () => {
    // The map this replaced was unreachable on any engine implementing
    // weekInfo, so nothing ever contradicted it, and it had Arabic on Sunday
    // while the live path said Monday and the truth was Saturday. Three
    // answers for one language. Checking the table against ICU here is what
    // stops it drifting back into being untested documentation.
    const wrong: string[] = [];
    for (const code of CODES) {
      const expected = cldrFirstDay(code);
      if (expected === undefined) continue;
      const exact = FALLBACK_FIRST_DAY[code];
      const base = FALLBACK_FIRST_DAY[code.split('-')[0] ?? ''];
      const viaFallback = exact ?? base ?? 1;
      if (viaFallback !== expected) {
        wrong.push(
          `${code}: ICU says ${DAY_NAME[expected]}(${expected}), fallback says ${viaFallback}`,
        );
      }
    }
    expect(wrong, `fallback disagrees with ICU for ${wrong.length} languages`).toEqual([]);
  });

  it('answers Monday for an unknown or malformed tag rather than throwing', () => {
    expect(weekStartFor('zz')).toBe(1);
    expect(weekStartFor('not a tag!!')).toBe(1);
    expect(weekStartFor(undefined)).toBe(weekStartFor('en'));
    expect(weekStartFor('')).toBe(weekStartFor('en'));
  });
});
