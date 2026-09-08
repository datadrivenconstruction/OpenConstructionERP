// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The round trip: format a number the way this product shows it to a reader,
 * feed that exact string back to the parser, and get the number back.
 *
 * Display and entry are mirrors of one another and only display was ever
 * tested. A locale whose formatter writes `1.234,56` and whose parser reads
 * `1.234` is not a formatting bug or a parsing bug, it is the pair being
 * wrong together, and no test that looks at only one half can see it.
 *
 * The locale list is READ FROM `SUPPORTED_LANGUAGES`, never written out here.
 * A hand-copied list silently stops covering the languages added after it, and
 * the next language this product ships has to be covered by this file on the
 * day it ships, not on the day someone remembers to extend an array.
 */
import { describe, it, expect } from 'vitest';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { parseDecimalInput, normalizeDecimalSeparators, toDecimalPayloadString } from './parseDecimal';

const LOCALES = SUPPORTED_LANGUAGES.map((l) => l.code);

/**
 * Amounts that have exactly one correct reading in every locale we ship.
 *
 * `1000` is deliberately NOT here, and the reason is the test below it: in a
 * dot-grouping locale `Intl` writes it `1.000`, which is also how a person
 * writes one-point-zero-zero-zero. That collision is real and unresolvable
 * from the string alone, so it is asserted on purpose further down rather
 * than hidden inside a skip. `1000000` IS here: it formats as `1.000.000`,
 * two groups, which no decimal reading can claim.
 */
const AMOUNTS = [0.5, 1.5, 48.6, 999.5, 1234.56, 1234567.89, 1000000];

describe('locale round trip', () => {
  it('measures every language the product offers, counted from the source', () => {
    // The denominator, printed beside the verdict. A gate whose population
    // silently went to zero would otherwise pass by measuring nothing.
    expect(LOCALES.length).toBeGreaterThan(30);
    expect(new Set(LOCALES).size).toBe(LOCALES.length);
    expect(AMOUNTS.length).toBeGreaterThan(0);
  });

  it.each(LOCALES)('%s: a formatted amount parses back to itself', (locale) => {
    for (const amount of AMOUNTS) {
      const shown = new Intl.NumberFormat(locale).format(amount);
      expect(
        parseDecimalInput(shown),
        `${locale}: formatted ${amount} as "${shown}"`,
      ).toBe(amount);
    }
  });

  it('reads the Indian grouping this product formats Indian bills with', () => {
    // marketNumberLocale.ts exists so an Indian workspace prints
    // 47,65,79,722.78 instead of 476,579,722.78. The parser used to reject
    // the whole-rupee form of exactly that, because its grouped-comma shape
    // only knew 3-digit groups. Amounts with a fraction always worked, so
    // every example anyone tried by hand looked fine.
    expect(parseDecimalInput('10,00,000')).toBe(1000000);
    expect(parseDecimalInput('47,65,79,722')).toBe(476579722);
    expect(parseDecimalInput('47,65,79,722.78')).toBe(476579722.78);
    expect(parseDecimalInput('1,00,000')).toBe(100000);
    // The Western shape must keep working alongside it.
    expect(parseDecimalInput('1,000')).toBe(1000);
    expect(parseDecimalInput('1,234,567')).toBe(1234567);
  });

  it('resolves the one shape that has two honest readings, and says which', () => {
    // `1.000` in de-DE is one thousand to a formatter and one-point-zero to
    // someone typing a quantity. The product cannot have both. It chooses the
    // decimal reading, because that is what a person entering a figure into a
    // cell means, and it has been the grid's entry format from the start.
    // Consequence, recorded here so it is a decision and not a surprise: a
    // grouped whole thousand copied off a German screen and pasted back reads
    // as 1. Typing `1000`, or `1.000,00`, is unambiguous and reads correctly.
    expect(parseDecimalInput('1.000')).toBe(1);
    expect(parseDecimalInput('1000')).toBe(1000);
    expect(parseDecimalInput('1.000,00')).toBe(1000);
    // Two or more dot groups cannot be a decimal, so they do collapse.
    expect(parseDecimalInput('1.000.000')).toBe(1000000);
  });
});

describe('the separator a user actually types', () => {
  it('reads a decimal comma as a fraction, not as a whole number', () => {
    expect(parseDecimalInput('1,5')).toBe(1.5);
    expect(parseDecimalInput('48,60')).toBe(48.6);
    expect(parseDecimalInput('-5,25')).toBe(-5.25);
    // The dangerous shape this whole file exists for: parseFloat returns 1
    // here, silently, and the entry looks like it was accepted.
    expect(parseFloat('1,5')).toBe(1);
  });

  it('reads both grouping conventions and a space-grouped amount', () => {
    expect(parseDecimalInput('1.234,56')).toBe(1234.56);
    expect(parseDecimalInput('1,234.56')).toBe(1234.56);
    expect(parseDecimalInput('1 234,56')).toBe(1234.56);
    expect(parseDecimalInput('1 234,56')).toBe(1234.56);
    expect(parseDecimalInput('1 234,56')).toBe(1234.56);
  });

  it('rejects rather than truncates, so a typo cannot store a prefix', () => {
    for (const bad of ['10abc', '1.2.3', '', '--', 'abc', 'Infinity', '0x10']) {
      expect(parseDecimalInput(bad), `should reject ${JSON.stringify(bad)}`).toBeNull();
    }
  });

  it('folds the digits our own formatter emits for bn and fa', () => {
    // Intl renders 1234.56 as these strings under those two languages, so the
    // product refusing to read them back is the product contradicting itself.
    expect(parseDecimalInput(new Intl.NumberFormat('bn').format(1234.56))).toBe(1234.56);
    expect(parseDecimalInput(new Intl.NumberFormat('fa').format(1234.56))).toBe(1234.56);
    // ar is NOT in that set: it resolves to Latin digits. Asserted so nobody
    // "fixes" a fold that was never needed.
    expect(new Intl.NumberFormat('ar').format(1234.56)).toMatch(/^[0-9.,\u00A0\u202F]+$/);
  });
});

describe('toDecimalPayloadString', () => {
  it('sends the dot-decimal spelling of what the user typed', () => {
    expect(toDecimalPayloadString('48,60')).toBe('48.60');
    expect(toDecimalPayloadString('1.234,56')).toBe('1234.56');
    expect(toDecimalPayloadString('19,5')).toBe('19.5');
  });

  it('keeps the exact digits rather than round-tripping through a float', () => {
    // String(Number(x)) would rewrite these. Money crosses the wire as a
    // string precisely so it does not.
    expect(toDecimalPayloadString('30,50')).toBe('30.50');
    expect(normalizeDecimalSeparators('1.234,5678901234567890')).toBe('1234.5678901234567890');
  });

  it('falls back for blank and passes unparseable input to the server', () => {
    expect(toDecimalPayloadString('')).toBe('0');
    expect(toDecimalPayloadString('   ')).toBe('0');
    expect(toDecimalPayloadString('', '1')).toBe('1');
    // Not silently turned into a number the user never typed.
    expect(toDecimalPayloadString('abc')).toBe('abc');
  });
});
