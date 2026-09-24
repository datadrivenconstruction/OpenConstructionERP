// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A translation that drops an interpolation placeholder renders a sentence
 * with a hole in it, and nothing else we own can see it.
 *
 * The orphan gate asks whether a key is answered; this one is. `tsc` asks
 * whether the value is a string; it is. A reader skimming the locale file sees
 * a fluent sentence, because the sentence is fluent - it just no longer says
 * which profile is about to be deleted or how many modules are about to switch
 * off. Measured when this was written: 2760 English keys carry a placeholder,
 * and across the other forty-four files exactly one had genuinely lost one, a
 * French delete confirmation that named no profile and promised permanence
 * where every other language promised the opposite.
 *
 * Getting to that single finding took three corrections, each of which had the
 * first draft reporting dozens of translations as broken when the translation
 * was right and the gate was wrong:
 *
 *   1. **Compare like with like inside a plural family.** The pair that forced
 *      this was `costs_catalogs.fx_mismatch`, where English wrote one form as
 *      "Item currency {{itemCurrency}}" and the other as "{{count}} of the
 *      selected items are priced in {{itemCurrencies}}". Different forms of
 *      one key can be different sentences naming different variables, so the
 *      reference has to be the English form of the same category, and only
 *      then the nearest form of the same plurality class. That particular pair
 *      has since been renamed to `_single` and `_multiple`, because a compound
 *      condition on the selection was choosing between them and they were
 *      never plural forms at all, but the rule it taught still holds for the
 *      families that are.
 *   2. **Keys English does not carry.** `pipeline.palette.no_match` lives in
 *      forty-one locale files and in none of `en.ts`, because English renders
 *      the call site's `defaultValue`. Nothing in the locale files can serve
 *      as the reference, so it comes from what a majority of the translations
 *      agree on, which is the same evidence a reader would use.
 *   3. **Forms that stand for one quantity.** Arabic's `_zero` for the takeoff
 *      toast reads "no item was created" and names neither the number nor the
 *      first row, because at zero there is no first row. That is better
 *      writing than English manages, not a defect. `_one` and `_two` likewise
 *      often spell the number out, so `count` may be absent there.
 *
 * An extra placeholder is always a defect: i18next leaves an unknown name in
 * the output verbatim, so `{{naem}}` reaches the screen as those eight
 * characters.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const LOCALE_DIR = join(process.cwd(), 'src', 'app', 'locales');
const PAIR = /"((?:[^"\\]|\\.)*)":\s*"((?:[^"\\]|\\.)*)"/g;
const PLACEHOLDER = /\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g;

/** Suffixes i18next appends when a key is counted. */
const PLURAL_SUFFIXES = ['_zero', '_one', '_two', '_few', '_many', '_other'] as const;

/** Forms standing for a single quantity, which may spell the number out. */
const FIXED_QUANTITY = ['_zero', '_one', '_two'] as const;

/** Forms covering a range of quantities, which have to carry the number. */
const RANGE_QUANTITY = ['_other', '_many', '_few'] as const;

function entries(code: string): Map<string, string> {
  const text = readFileSync(join(LOCALE_DIR, `${code}.ts`), 'utf8');
  const out = new Map<string, string>();
  for (const [, key, value] of text.matchAll(PAIR)) {
    // Locale files also hold ordinary object literals; a translation key
    // always carries a dot and never a space.
    if (key!.includes('.') && !key!.includes(' ')) out.set(key!, value!);
  }
  return out;
}

function placeholders(value: string): Set<string> {
  return new Set([...value.matchAll(PLACEHOLDER)].map((m) => m[1]!));
}

const localeCodes = readdirSync(LOCALE_DIR)
  .filter((f) => f.endsWith('.ts') && f !== 'index.ts')
  .map((f) => f.slice(0, -3));

const byLocale = new Map(localeCodes.map((code) => [code, entries(code)]));
const english = byLocale.get('en')!;

/**
 * English keys to consult for `key`, best first: the same plural category,
 * then the other forms of the same plurality class, then the other class,
 * then the unsuffixed key.
 */
function preference(key: string): string[] {
  const suffix = PLURAL_SUFFIXES.find((s) => key.endsWith(s));
  if (suffix === undefined) return [key];
  const base = key.slice(0, -suffix.length);
  const near: readonly string[] = FIXED_QUANTITY.includes(suffix as never)
    ? FIXED_QUANTITY
    : RANGE_QUANTITY;
  const far: readonly string[] = near === FIXED_QUANTITY ? RANGE_QUANTITY : FIXED_QUANTITY;
  return [
    key,
    ...near.map((s) => base + s).filter((k) => k !== key),
    ...far.map((s) => base + s),
    base,
  ];
}

/**
 * The placeholders a translation of `key` is expected to carry, or null when
 * there is no evidence either way.
 *
 * Memoised because the answer depends only on the key, and the fallback walks
 * every locale file. Recomputing it per entry per test took over two minutes
 * and tripped the fifteen second limit; the same work done once takes seconds.
 */
const expectedCache = new Map<string, Set<string> | null>();

function expectedFor(key: string): Set<string> | null {
  const cached = expectedCache.get(key);
  if (cached !== undefined) return cached;
  const answer = computeExpected(key);
  expectedCache.set(key, answer);
  return answer;
}

function computeExpected(key: string): Set<string> | null {
  for (const name of preference(key)) {
    const value = english.get(name);
    if (value !== undefined) return placeholders(value);
  }
  const votes = new Map<string, number>();
  let carriers = 0;
  for (const [code, map] of byLocale) {
    if (code === 'en') continue;
    const value = map.get(key);
    if (value === undefined) continue;
    carriers += 1;
    for (const name of placeholders(value)) votes.set(name, (votes.get(name) ?? 0) + 1);
  }
  if (carriers < 3) return null;
  const agreed = new Set<string>();
  for (const [name, count] of votes) if (count * 2 > carriers) agreed.add(name);
  return agreed;
}

interface Comparison {
  code: string;
  key: string;
  want: Set<string>;
  got: Set<string>;
  missing: string[];
}

/**
 * Every locale entry paired with the placeholders its English owes it, built
 * once for the whole file rather than per test.
 */
const comparisons: Comparison[] = [];
for (const [code, map] of byLocale) {
  if (code === 'en') continue;
  for (const [key, value] of map) {
    const want = expectedFor(key);
    if (want === null) continue;
    const got = placeholders(value);
    comparisons.push({ code, key, want, got, missing: [...want].filter((p) => !got.has(p)) });
  }
}

const pluralCategories = new Map<string, Set<string>>(
  localeCodes.map((code) => [
    code,
    new Set<string>(new Intl.PluralRules(code).resolvedOptions().pluralCategories),
  ]),
);

describe('every translation keeps the placeholders its sentence needs', () => {
  it('is looking at the whole tree, so a silent zero cannot pass as agreement', () => {
    expect(localeCodes.length, 'no locale files found').toBeGreaterThan(40);
    expect(english.size, 'en.ts parsed to almost nothing').toBeGreaterThan(30000);
    // Counted through `placeholders`, not `PLACEHOLDER.test`: a global regex
    // carries `lastIndex` between calls, so testing it in a filter would skip
    // every other string and the population would read as half its true size.
    const carrying = [...english.values()].filter((v) => placeholders(v).size > 0).length;
    expect(carrying, 'no English value parsed as carrying a placeholder').toBeGreaterThan(2000);
    const compared = comparisons.filter((c) => c.want.size > 0).length;
    expect(compared, 'nothing was actually compared').toBeGreaterThan(20000);
  });

  it('never loses a placeholder its language cannot do without', () => {
    const lost: string[] = [];
    for (const { code, key, missing } of comparisons) {
      if (missing.length === 0) continue;
      // A zero form is a different sentence: it says nothing happened, and it
      // has nothing to name. The count of these is pinned below.
      if (key.endsWith('_zero')) continue;
      // A singular or dual may write the number as a word or a digit.
      const onlyCount = missing.length === 1 && missing[0] === 'count';
      if (onlyCount && (key.endsWith('_one') || key.endsWith('_two'))) continue;
      lost.push(`${code} ${key}: missing ${missing.join(', ')}`);
    }
    expect(lost, `translations missing a placeholder:\n  ${lost.join('\n  ')}`).toEqual([]);
  });

  it('never invents a placeholder nothing supplies', () => {
    const invented: string[] = [];
    for (const { code, key, want, got } of comparisons) {
      const extra = [...got].filter((p) => !want.has(p));
      if (extra.length > 0) invented.push(`${code} ${key}: unknown ${extra.join(', ')}`);
    }
    expect(invented, `placeholders no caller supplies:\n  ${invented.join('\n  ')}`).toEqual([]);
  });

  it('grants the plural exemptions only to languages that have the form', () => {
    // The two exemptions above are linguistic, so they are pinned to the
    // language's own CLDR categories rather than to a count that would drift.
    // A `_zero` exemption handed to a language with no zero category, or a
    // `_two` exemption to one with no dual, would mean the exemption had
    // stopped describing grammar and started describing whoever edited last.
    const wrongly: string[] = [];
    for (const { code, key, missing } of comparisons) {
      if (missing.length === 0) continue;
      const suffix = FIXED_QUANTITY.find((s) => key.endsWith(s));
      if (suffix === undefined) continue;
      const category = suffix.slice(1);
      if (!pluralCategories.get(code)?.has(category)) {
        wrongly.push(`${code} ${key}: ${code} has no ${category} category`);
      }
    }
    expect(wrongly, `exemptions handed to the wrong language:\n  ${wrongly.join('\n  ')}`).toEqual(
      [],
    );
  });

  it('keeps the exemptions rare enough to stay readable one by one', () => {
    // Measured at the time of writing: 31 zero forms, all Arabic, and 93
    // singular or dual forms that spell the number out. Headroom for growth,
    // not for a policy change: a jump past these means someone started
    // dropping the number from forms that cover a range. 18.0.0 added the AI
    // dock, whose `_one` sentences read "one change" in words in most
    // languages, which took the singular count to 214.
    let zeroForms = 0;
    let spelledOut = 0;
    for (const { key, missing } of comparisons) {
      if (missing.length === 0) continue;
      if (key.endsWith('_zero')) zeroForms += 1;
      else if (missing.length === 1 && missing[0] === 'count') spelledOut += 1;
    }
    expect(zeroForms, 'zero forms dropping a placeholder').toBeLessThanOrEqual(60);
    expect(spelledOut, 'singular or dual forms spelling the number out').toBeLessThanOrEqual(240);
  });
});
