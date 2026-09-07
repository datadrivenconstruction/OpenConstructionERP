// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Sorting text is language-dependent and JavaScript's defaults are not.
//
// This file has to prove two different things, and they fail independently.
// The first block proves the HELPER is right: given names, `compareNames`
// orders them the way the reader's language orders them. The second block
// proves the WIRING: that the product's lists actually go through it. A helper
// test alone cannot tell a sweep that converted twenty call sites from one
// that converted none, because the helper is identical in both worlds.
//
// Every assertion here is written to FAIL against the `localeCompare(b)` this
// sweep replaced. That constraint is the point. `expect(sorted[0]).toBe('Ada')`
// passes just as well against code-unit order, so an English-only or
// ASCII-only assertion is not evidence of anything. What is pinned is always a
// DISAGREEMENT between two languages over the same input: German files Ärger
// under A, Swedish files it after Z, and no single locale-blind comparator can
// satisfy both. That property is what broke, so that property is what is
// asserted - not today's exact byte string, which belongs to the engine's CLDR
// data and moves between ICU versions.
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

import i18next from 'i18next';
import { afterAll, beforeEach, describe, expect, it } from 'vitest';

import { compareNames, sortNames, getCollator, __resetCollatorCache } from '../collator';

void i18next.init({ lng: 'en', resources: {}, initAsync: false });
const original = i18next.language;
afterAll(() => {
  void i18next.changeLanguage(original);
});
beforeEach(() => {
  __resetCollatorCache();
});

/* ── 1. The helper orders names in the language it is given ───────────── */

describe('the collator', () => {
  // The canonical disagreement. German treats Ä as a variant of A, so "Ärger"
  // files under A, before "Ost". Swedish and Danish treat Ä and Ö as their own
  // letters that come AFTER Z, so the same word files last. A comparator that
  // does not know which language it is in gets one of these wrong by
  // construction, and there is no third answer that satisfies both.
  const GERMANIC = ['Zebra', 'Ärger', 'Österreich', 'Apfel', 'Ost'];

  it('files a German umlaut under A and a Swedish one after Z', () => {
    const de = sortNames(GERMANIC, 'de');
    const sv = sortNames(GERMANIC, 'sv');

    expect(de.indexOf('Ärger')).toBeLessThan(de.indexOf('Ost'));
    expect(sv.indexOf('Ärger')).toBeGreaterThan(sv.indexOf('Zebra'));

    // Stated as the disagreement itself, so this cannot pass by both
    // languages quietly falling back to one shared answer.
    expect(de, 'German and Swedish must not agree on this input').not.toEqual(sv);
  });

  it('sorts Czech ch as one letter after h', () => {
    // "chata" is a hut. In Czech `ch` is a single letter filed after H, so it
    // comes AFTER "hora"; in English it is c-h and comes before.
    const cs = sortNames(['chata', 'hora', 'irsko'], 'cs');
    const en = sortNames(['chata', 'hora', 'irsko'], 'en');

    expect(cs.indexOf('chata')).toBeGreaterThan(cs.indexOf('hora'));
    expect(en.indexOf('chata')).toBeLessThan(en.indexOf('hora'));
  });

  it('applies Turkish dotted-i rules', () => {
    const tr = sortNames(['Isparta', 'Izmir', 'İstanbul'], 'tr');
    const en = sortNames(['Isparta', 'Izmir', 'İstanbul'], 'en');

    // Turkish ranks dotless I before dotted İ, so İstanbul lands last; English
    // has no such distinction and interleaves it.
    expect(tr[tr.length - 1]).toBe('İstanbul');
    expect(en).not.toEqual(tr);
  });

  it('orders embedded numbers the way a reader counts', () => {
    // Construction names carry numbers constantly - "Level 2", "Block 10".
    // Code-unit order puts 10 before 2 because it compares "1" against "2".
    expect(sortNames(['Block 10', 'Block 2', 'Block 1'], 'de')).toEqual([
      'Block 1',
      'Block 2',
      'Block 10',
    ]);
  });

  it('beats a bare sort on the input a bare sort gets wrong', () => {
    // The control. A default `.sort()` compares UTF-16 code units, which puts
    // every accented name after every unaccented one regardless of language.
    // German disagrees, and that disagreement is the whole defect.
    const codeUnit = [...GERMANIC].sort();
    expect(sortNames(GERMANIC, 'de')).not.toEqual(codeUnit);
  });

  it('sorts empty and missing names last instead of throwing', () => {
    const rows = ['Beta', '', 'Alpha', null, undefined];
    const sorted = [...rows].sort((a, b) => compareNames(a, b));
    expect(sorted.slice(0, 2)).toEqual(['Alpha', 'Beta']);
  });

  it('reuses one collator per locale rather than building one per comparison', () => {
    // Not decoration: a comparator runs O(n log n) times, and constructing an
    // `Intl.Collator` inside it is the cost that makes a locale-aware sort of
    // a long list slow. Identity is the only way to observe the cache.
    expect(getCollator('de')).toBe(getCollator('de'));
    expect(getCollator('de')).not.toBe(getCollator('sv'));
  });

  it('falls back instead of throwing on a malformed locale tag', () => {
    expect(() => sortNames(['b', 'a'], 'not a tag')).not.toThrow();
    expect(sortNames(['b', 'a'], 'not a tag')).toEqual(['a', 'b']);
  });
});

/* ── 2. The helper follows the UI language, not the browser's ─────────── */

describe('the language the sort follows', () => {
  // This is the half a bare `localeCompare(b)` gets wrong even when it looks
  // right. With no locale argument it sorts in the RUNTIME's default locale,
  // which comes from the browser and the OS - not from the language picker in
  // this app. A reader who chose Swedish while running an English browser got
  // English collation on Swedish names. Switching i18next has to move the
  // answer, or the plumbing from the picker to the comparator is not connected.
  const WORDS = ['Zebra', 'Ärger', 'Ost'];

  it('re-orders the same list when the reader changes language', async () => {
    await i18next.changeLanguage('de');
    __resetCollatorCache();
    const asGerman = [...WORDS].sort((a, b) => compareNames(a, b));

    await i18next.changeLanguage('sv');
    __resetCollatorCache();
    const asSwedish = [...WORDS].sort((a, b) => compareNames(a, b));

    expect(asGerman, 'the picker moved but the order did not').not.toEqual(asSwedish);
    expect(asGerman.indexOf('Ärger')).toBeLessThan(asGerman.indexOf('Ost'));
    expect(asSwedish.indexOf('Ärger')).toBe(asSwedish.length - 1);
  });
});

/* ── 3. The rest of the product ───────────────────────────────────────── */

/**
 * Sites left comparing a NAME with no locale, each with the reason.
 *
 * This list may only shrink. Anything not on it is a defect the gate below
 * reports by path, so a new bypass cannot land quietly.
 */
const SORTED_BY_ENGLISH_NAME: ReadonlyArray<{ file: string; sites: number; why: string }> = [
  // `sortedCountries` is documented as ordering by the ENGLISH name, and the
  // picker it feeds shows that English name. Ordering English text by the
  // reader's alphabet would be a different decision than the one this function
  // records, so it is left alone deliberately rather than swept.
  { file: 'shared/lib/countries.ts', sites: 2, why: 'ordered by English name on purpose' },
];

/**
 * A key whose value a reader alphabetises.
 *
 * Deliberately narrow. Dates held as ISO strings (`period`, `created_at`),
 * identifiers (`id`, `code`, `sku`, `key`) and currency codes are all sorted
 * with `localeCompare` in this codebase and are all CORRECT that way: byte
 * order is the right order for an ISO date, and no reader alphabetises a
 * primary key. Counting those as defects is how a grep total gets mistaken
 * for a defect total.
 */
// The second alternative is not decoration. `typeLabel(a.record_type)
// .localeCompare(...)` carries its name-ness in the FUNCTION, not in the
// property, so a classifier that only reads the property access scores that
// line as `.record_type` and waves through a reverted label sort. This gate
// was written without it, and the revert drill below is what caught it.
const NAME_SHAPED =
  /\.(name|description|label|title|filename|caption|subject|[a-z]+_name|[a-zA-Z]*Name)\b|\b[a-zA-Z]*(Label|Name|Title|Description)\s*\(/;

/** `frontend/src`, whether vitest was started from the repo root or `frontend`. */
function sourceRoot(): string {
  const root = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')].find((p) =>
    existsSync(p),
  );
  if (!root) throw new Error(`cannot locate frontend/src from ${process.cwd()}`);
  return root;
}

/** Product code only. The helper's own module holds the fallback this routes through. */
function productFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry !== '__tests__' && entry !== 'node_modules') productFiles(full, out);
    } else if (
      /\.tsx?$/.test(entry) &&
      !/\.(test|spec)\.tsx?$/.test(entry) &&
      entry !== 'collator.ts'
    ) {
      out.push(full);
    }
  }
  return out;
}

/**
 * `localeCompare` calls that pass no locale at all.
 *
 * Parens are balanced rather than regex-matched, because the shape that
 * matters most - `typeLabel(a).localeCompare(typeLabel(b))` - wraps a call
 * inside the call, and a naive `\([^,)]*\)` skips exactly those.
 */
function localeBlindCalls(src: string): string[] {
  const needle = '.localeCompare(';
  const hits: string[] = [];
  for (let i = src.indexOf(needle); i !== -1; i = src.indexOf(needle, i + 1)) {
    let depth = 1;
    let commas = 0;
    let j = i + needle.length;
    for (; j < src.length && depth > 0; j++) {
      const ch = src[j]!;
      if (ch === '(' || ch === '[' || ch === '{') depth++;
      else if (ch === ')' || ch === ']' || ch === '}') depth--;
      else if (ch === ',' && depth === 1) commas++;
    }
    if (depth === 0 && commas === 0) hits.push(src.slice(src.lastIndexOf('\n', i) + 1, j).trim());
  }
  return hits;
}

describe('the rest of the product', () => {
  const root = sourceRoot();
  const files = productFiles(root);

  const blind = new Map<string, string[]>();
  for (const file of files) {
    const hits = localeBlindCalls(readFileSync(file, 'utf8'));
    if (hits.length) blind.set(file.slice(root.length + 1).replace(/\\/g, '/'), hits);
  }

  const named = new Map<string, number>();
  for (const [file, hits] of blind) {
    const n = hits.filter((h) => NAME_SHAPED.test(h.split('.localeCompare(')[0]!)).length;
    if (n > 0) named.set(file, n);
  }

  const allSites = [...blind.values()].reduce((a, h) => a + h.length, 0);
  const nameSites = [...named.values()].reduce((a, b) => a + b, 0);
  const population = `${nameSites} name-shaped of ${allSites} locale-blind localeCompare calls in ${files.length} product files`;

  it('measures a population big enough for the assertions below to mean anything', () => {
    // Guards the instrument, not the product. A walk that resolved the wrong
    // root, or a scanner that quietly stopped matching, returns empty maps and
    // every assertion after this one passes while checking nothing at all.
    // These are assertions, not preconditions, so an empty input is RED here
    // rather than silently green further down.
    expect(files.length, `walked too few files: ${population}`).toBeGreaterThan(2000);
    expect(allSites, `scanner matched nothing: ${population}`).toBeGreaterThan(50);

    // The classifier has to be shown to select, not just to run. The recorded
    // exception is the control: if `NAME_SHAPED` stops recognising `.name`,
    // this drops to zero and the "no unrecorded bypasses" test below would
    // pass against a scanner that sees nothing.
    expect(nameSites, `classifier selected nothing: ${population}`).toBeGreaterThan(0);
  });

  it('routes every list of names through the collator, except the recorded ones', () => {
    const recorded = new Set(SORTED_BY_ENGLISH_NAME.map((e) => e.file));
    const unrecorded = [...named.keys()].filter((f) => !recorded.has(f)).sort();

    expect(
      unrecorded,
      `${population}. These order names a reader scans with a comparator that ` +
        'does not know the reader\'s language: with no locale argument, ' +
        '`localeCompare` uses the BROWSER\'s locale, not the one picked in this ' +
        'app. German files Ärger under A, Swedish files it after Z, and this ' +
        'gets one of them wrong. Use `compareNames` (or `useNameCollator` in a ' +
        'component, so the list re-sorts when the language changes) from ' +
        '@/shared/lib/collator. If the value is a date, a code or an id rather ' +
        'than something a reader alphabetises, it is out of population already; ' +
        'if it is a name kept in another language on purpose, add it to ' +
        'SORTED_BY_ENGLISH_NAME with the reason.',
    ).toEqual([]);
  });

  it('holds each recorded exclusion at exactly the count it was recorded with', () => {
    const moved = SORTED_BY_ENGLISH_NAME.filter((e) => (named.get(e.file) ?? 0) !== e.sites).map(
      (e) => `${e.file}: recorded ${e.sites} (${e.why}), found ${named.get(e.file) ?? 0}`,
    );
    expect(
      moved,
      `${population}. A count moved. If you converted one, lower the count or ` +
        'drop the entry: this list may only shrink.',
    ).toEqual([]);
  });

  it('keeps the collator helper reachable from the call sites that were converted', () => {
    // The other direction of the same claim. The census above goes red when a
    // BAD shape appears; this goes red when the GOOD one disappears, which is
    // what a revert looks like - the bypass count stays flat because the
    // reverted site fails the name-shape test on some other key.
    const importers = files.filter((f) =>
      /from '@\/shared\/lib\/collator'/.test(readFileSync(f, 'utf8')),
    );
    expect(
      importers.length,
      `${population}. No product file imports the collator, so either the sweep ` +
        'was reverted wholesale or the helper moved without its call sites.',
    ).toBeGreaterThan(20);
  });
});
