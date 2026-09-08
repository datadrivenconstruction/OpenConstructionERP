// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One amount, one reading, on every surface that shows it.
//
// The defect this was written from: the same record rendered `$180,174.28` on
// the bill of quantities and `180.174,28 $` on the finance register, inside one
// English UI. Nothing was random about it. The bill formats through
// `shared/lib/money`, which resolves the locale from the UI language, and the
// finance register formats through `<MoneyDisplay>`, which read a separate
// `numberLocale` preference whose default was the literal `'de-DE'`. Both
// surfaces were doing exactly what they were told; they were told different
// things.
//
// So this file asks the question the sibling gates cannot. They ask whether a
// call names a locale at all - `numbersAreWrittenInTheAppLanguage` catches the
// missing argument, `formattersReadTheLocalePerCall` catches the argument read
// once at chunk load. A call that confidently passes the WRONG locale satisfies
// both. That is the shape of this bug, and it is why finding it needed a
// screenshot rather than a gate.
//
// Two halves, in one file because they are one question:
//
//   * the rendering half checks that the money surfaces agree with the common
//     path, in a form derived from the locale rather than compared to a string.
//     A test that knows `$180,174.28` passes again the moment the seed amount
//     changes; a test that knows en-US groups with commas, points its decimals
//     and leads with the symbol keeps working on any amount.
//   * the census half checks that there is only one place the answer can come
//     from. Fixing the two rows in the screenshot would have left every other
//     surface free to invent its own locale, and we would be back here.
import { describe, it, expect, beforeEach, afterEach, afterAll } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { render, cleanup } from '@testing-library/react';
import i18next from 'i18next';

import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { QuantityDisplay } from '@/shared/ui/QuantityDisplay';
import { formatCurrency } from '@/shared/lib/money';
import { fmtWithCurrency } from '@/features/boq/boqHelpers';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

const SRC = join(__dirname, '..', '..', '..');

/**
 * The fixed point of the whole file: the language the reader picked, and the
 * locale tag their numbers therefore have to be written in. Taken straight
 * from `LOCALE_MAP` in `intlLocale.ts`, deliberately restated here rather than
 * imported - a test that derives its expectation from the same function it is
 * checking passes whatever that function returns.
 */
const LANGUAGES: [string, string][] = [
  // `en` claims no region and resolves to itself. The picker offers
  // `English (UK)` and `English (US)` beside it, so a reader with a preference
  // says which; a reader who picks plain English gets what CLDR gives
  // unqualified `en`, which is `$1,234.50` and a month-first date.
  ['en', 'en'],
  ['de', 'de-DE'],
  ['fr', 'fr-FR'],
  ['ja', 'ja-JP'],
];

/** Amounts, not an amount. The assertion must not depend on which one. */
const AMOUNTS = [180174.28, 225297.6, 3088.4, 0, -1234.5];

const originalLanguage = i18next.language;

function speak(language: string) {
  // The store is read through a selector, and `useIntlLocale` reads i18next at
  // render, so both are in place before the component mounts.
  i18next.language = language;
}

beforeEach(() => {
  localStorage.clear();
  usePreferencesStore.getState().resetPreferences();
});

afterEach(() => {
  cleanup();
});

afterAll(() => {
  i18next.language = originalLanguage;
});

/* ── The reading a locale actually prescribes ─────────────────────────────── */

interface Shape {
  group: string | undefined;
  decimal: string | undefined;
  symbolLeads: boolean;
}

/**
 * What this locale does to a number, asked of Intl rather than asserted from
 * memory. Returning the separators and the symbol position - the three things
 * that differed on the screenshot - lets the tests below state the rule
 * ("English groups on commas") without hardcoding any rendered amount.
 */
function shapeOf(locale: string, currency: string, amount: number): Shape {
  const parts = new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).formatToParts(amount);
  const symbolAt = parts.findIndex((p) => p.type === 'currency');
  const digitsAt = parts.findIndex((p) => p.type === 'integer');
  return {
    group: parts.find((p) => p.type === 'group')?.value,
    decimal: parts.find((p) => p.type === 'decimal')?.value,
    symbolLeads: symbolAt >= 0 && symbolAt < digitsAt,
  };
}

/** The money string a reader of `locale` is owed, computed, never quoted. */
function expectedMoney(locale: string, currency: string, amount: number): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

/* ── Half one: the surfaces agree, in the reader's language ───────────────── */

describe('a money surface is written in the language the reader is reading', () => {
  // Guards the guard. Every assertion below compares a rendered string against
  // an Intl-derived one, which would be satisfied by anything at all if the
  // test host shipped no locale data and Intl collapsed every locale onto one
  // output. Stating the differences explicitly means a hollow environment
  // fails here, loudly, instead of turning the rest of the file green.
  it('the locales under test genuinely disagree about how to write a number', () => {
    const en = shapeOf('en', 'USD', 180174.28);
    const de = shapeOf('de-DE', 'USD', 180174.28);

    expect(en.group).toBe(',');
    expect(en.decimal).toBe('.');
    expect(en.symbolLeads).toBe(true);

    expect(de.group).toBe('.');
    expect(de.decimal).toBe(',');
    expect(de.symbolLeads).toBe(false);
  });

  it.each(LANGUAGES)('MoneyDisplay writes %s money as %s prescribes', (language, tag) => {
    speak(language);
    for (const amount of AMOUNTS) {
      const { container } = render(<MoneyDisplay amount={amount} currency="USD" />);
      expect(container.textContent).toBe(expectedMoney(tag, 'USD', amount));
      cleanup();
    }
  });

  // The defect itself: `/boq` renders through `formatCurrency` and `/finance`
  // through `<MoneyDisplay>`. Whatever else changes, those two have to produce
  // one string for one amount.
  it.each(LANGUAGES)('the bill and the register agree in %s', (language, _tag) => {
    speak(language);
    for (const amount of AMOUNTS) {
      const { container } = render(<MoneyDisplay amount={amount} currency="USD" />);
      expect(container.textContent).toBe(formatCurrency(amount, 'USD'));
      cleanup();
    }
  });

  it('a quantity is written with the same separators as the money beside it', () => {
    speak('de');
    const { container } = render(<QuantityDisplay value={1234.5} unit="m³" precision={2} />);
    const expected = new Intl.NumberFormat('de-DE', {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(1234.5);
    expect(container.textContent).toContain(expected);
  });

  it('switching the language moves the numbers with it', () => {
    speak('en');
    const first = render(<MoneyDisplay amount={180174.28} currency="USD" />).container.textContent;
    cleanup();
    speak('de');
    const second = render(<MoneyDisplay amount={180174.28} currency="USD" />).container.textContent;

    expect(first).toBe(expectedMoney('en', 'USD', 180174.28));
    expect(second).toBe(expectedMoney('de-DE', 'USD', 180174.28));
    expect(first).not.toBe(second);
  });

  it('writes each of the three English entries the way that entry says', () => {
    // The decision, pinned as a decision rather than as one language's answer.
    // Plain English claims no region and resolves to itself; the two entries
    // beside it in the picker claim one and get it. This file has twice been
    // edited to say that `en` IS one of the regions - first American, then
    // British - and each time the entry that actually exists to be that region
    // was left with nothing of its own to say.
    //
    // The British half is what carries the test. `en` and `en-US` are
    // formatting twins, because CLDR has no region-free English and
    // unqualified `en` inherits the American reading, so an assertion that
    // only compared those two would pass under any of the three decisions.
    // en-GB is the one that differs, and it is asserted both ways: it must
    // write this amount `US$180,174.28`, and it must not write it the way the
    // neutral entry does.
    for (const [language, tag] of [
      ['en', 'en'],
      ['en-GB', 'en-GB'],
      ['en-US', 'en-US'],
    ] as const) {
      speak(language);
      const { container } = render(<MoneyDisplay amount={180174.28} currency="USD" />);
      expect(container.textContent, language).toBe(expectedMoney(tag, 'USD', 180174.28));
      cleanup();
    }

    expect(expectedMoney('en-GB', 'USD', 180174.28)).not.toBe(
      expectedMoney('en', 'USD', 180174.28),
    );
    expect(expectedMoney('en-US', 'USD', 180174.28)).toBe(
      expectedMoney('en', 'USD', 180174.28),
    );
  });
});

/* ── Half one, continued: an explicit choice still wins ───────────────────── */

describe('the number-format preference', () => {
  it('overrides the UI language when the reader has actually chosen one', () => {
    speak('en');
    usePreferencesStore.getState().setPreference('numberLocale', 'de-DE');
    const { container } = render(<MoneyDisplay amount={180174.28} currency="USD" />);
    expect(container.textContent).toBe(expectedMoney('de-DE', 'USD', 180174.28));
  });

  /**
   * The half of the contract that reads backwards, which nothing asserted.
   *
   * Everything else in this file checks that a number follows the reader.
   * "Follows the reader" has two clauses and only one of them was written
   * down: with no preference the number moves with the language, and with a
   * preference it stops moving with the language. The test above cannot see
   * the second clause, because it renders in exactly one language - a build
   * where the preference were ignored entirely and `de-DE` happened to be the
   * fallback would satisfy it. Reading the same amount in four languages is
   * what tells "the preference won" apart from "the preference agreed".
   */
  const readAcrossLanguages = (render1: () => string | null) =>
    LANGUAGES.map(([language]) => {
      speak(language);
      const text = render1();
      cleanup();
      return text;
    });

  const money = () => render(<MoneyDisplay amount={180174.28} currency="USD" />).container.textContent;

  it('holds a chosen format still while the language moves under it', () => {
    usePreferencesStore.getState().setPreference('numberLocale', 'de-DE');
    const readings = readAcrossLanguages(money);

    expect(new Set(readings).size).toBe(1);
    expect(readings[0]).toBe(expectedMoney('de-DE', 'USD', 180174.28));
  });

  it('and lets the same four languages move it when nothing was chosen', () => {
    // The negative control, without which the test above passes on a surface
    // that renders one frozen string for every reader.
    //
    // More than one rather than four: `en` and `ja-JP` write this amount the
    // same way, both grouping on commas with a leading bare symbol, so four
    // languages are only three readings and asserting four would be asserting
    // a fact about Japanese that is not true. The count is deliberately not
    // pinned either way - it has moved with each of this entry's decisions,
    // and it is a fact about which currency symbols ICU disambiguates for
    // whom rather than about the contract under test.
    expect(usePreferencesStore.getState().numberLocale).toBe('auto');
    const readings = readAcrossLanguages(money);

    expect(new Set(readings).size).toBeGreaterThan(1);
    expect(readings[0]).toBe(expectedMoney('en', 'USD', 180174.28));
    expect(readings[1]).toBe(expectedMoney('de-DE', 'USD', 180174.28));
  });

  it('holds a chosen format still for a quantity too, not only for money', () => {
    // The wave moved quantities as well as amounts, and a quantity reaches the
    // locale through a different component, so the contract is asserted on
    // both rather than assumed to carry across.
    usePreferencesStore.getState().setPreference('numberLocale', 'de-DE');
    const readings = readAcrossLanguages(
      () => render(<QuantityDisplay value={1234.5} unit="m³" precision={2} />).container.textContent,
    );

    expect(new Set(readings).size).toBe(1);
    const expected = new Intl.NumberFormat('de-DE', {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(1234.5);
    expect(readings[0]).toContain(expected);
  });

  // The half of the fix that is invisible from a fresh profile. `persist`
  // writes the whole preferences object on any change, so every browser that
  // ever set a currency has the old hardcoded `'de-DE'` written down. Changing
  // the default without reading that value back would have fixed the bug for
  // nobody who had ever used the app.
  // `setPreference` rebuilds the stored blob from `readPreferences()`, so what
  // lands back in localStorage is the migration's own output. Asserting there
  // exercises the real boot path rather than a helper exported for the test.
  const persisted = () => JSON.parse(localStorage.getItem('oe_preferences') as string);

  it('reads the pre-auto default out of an existing browser', () => {
    localStorage.setItem('oe_preferences', JSON.stringify({ currency: 'USD', numberLocale: 'de-DE' }));
    usePreferencesStore.getState().setPreference('vatRate', 19);
    expect(persisted().numberLocale).toBe('auto');
  });

  it('migrates once, so a de-DE chosen afterwards survives', () => {
    localStorage.setItem(
      'oe_preferences',
      JSON.stringify({ currency: 'USD', numberLocale: 'de-DE', _v: 2 }),
    );
    usePreferencesStore.getState().setPreference('vatRate', 19);
    expect(persisted().numberLocale).toBe('de-DE');
  });

  it('leaves a locale nobody could have got by default alone', () => {
    localStorage.setItem('oe_preferences', JSON.stringify({ numberLocale: 'ja-JP' }));
    usePreferencesStore.getState().setPreference('vatRate', 19);
    expect(persisted().numberLocale).toBe('ja-JP');
  });
});

/* ── Half two: only one place may answer the question ─────────────────────── */

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    // Locale files hold translated data, not formatting calls.
    if (name === 'node_modules' || name === 'locales' || name === '__tests__') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, found);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      found.push(full);
    }
  }
  return found;
}

const PRODUCT_FILES = sourceFiles(SRC).map((f) => relative(SRC, f).replace(/\\/g, '/'));

/**
 * The tree, read once per file rather than once per file per test.
 *
 * The walk list above is already computed a single time; the contents were
 * not, and eight of the censuses below walk the whole tree, so a run of this
 * file made roughly seventeen thousand reads of two thousand files. In
 * isolation that is invisible - every one of those walks finishes inside half
 * a second. Under the full suite, with the machine saturated by a few hundred
 * test files at once, the same walks ran past the default fifteen-second
 * budget and four of them failed on time rather than on their assertion.
 *
 * That is the failure worth designing against, because a census that times out
 * reports nothing and a gate that reports nothing is not a gate. Nothing in
 * this file writes to the tree it reads, so the cache holds for the life of one
 * `vitest run` and no longer. It is NOT watch-safe: under `--watch` the module
 * survives edits to the files it has already read, so a re-run can answer from
 * a copy of the tree as it was when the watcher started. Trust a green result
 * under watch only after a full restart.
 */
const fileText = new Map<string, string>();
const read = (rel: string) => {
  const cached = fileText.get(rel);
  if (cached !== undefined) return cached;
  const text = readFileSync(join(SRC, rel), 'utf8');
  fileText.set(rel, text);
  return text;
};

/**
 * The locale argument of a formatter call: from `from` to the first comma or
 * closing bracket. Neither character occurs inside a BCP-47 tag or inside a
 * call to one of the resolvers, so this is the whole argument in every shape
 * the tree uses today.
 */
function localeArgument(source: string, from: number): string {
  const rest = source.slice(from);
  return rest.slice(0, Math.min(...[rest.indexOf(','), rest.indexOf(')')].filter((i) => i >= 0)));
}

/**
 * Every name a `const`, `let` or `var` in this file binds to something the
 * pattern matches.
 *
 * A gate that judges the argument text alone reads `new Intl.NumberFormat(
 * locale, ...)` as clean whatever `locale` holds, so `const locale =
 * getIntlLocale()` two lines above defeats it. That is not hypothetical: three
 * of the four sites this file caught on the day the resolution was added were
 * written that way, and the gate had already been reported green over them.
 *
 * Matching by name across the whole file is deliberate over-approximation. A
 * file that keeps a language `locale` and a number `locale` under one name gets
 * flagged, and being asked to give one of them a different name is the right
 * answer rather than a false alarm.
 */
function boundTo(source: string, pattern: RegExp): Set<string> {
  const names = new Set<string>();
  for (const match of source.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\n]+)/g)) {
    const [, name, bound] = match;
    if (name && bound && pattern.test(bound)) names.add(name);
  }
  return names;
}

/** Whether an argument reaches a resolver, directly or through a local name. */
function reaches(argument: string, pattern: RegExp, aliases: Set<string>): boolean {
  if (pattern.test(argument)) return true;
  const bare = argument.trim();
  return /^[A-Za-z_$][\w$]*$/.test(bare) && aliases.has(bare);
}

/**
 * The two resolvers, in every spelling that reaches them. `i18n.language` is
 * the third way to ask for the interface language and it belongs here for the
 * same reason the other two do: a formatter cannot be excused by which door it
 * used.
 */
const LANGUAGE = /\b(?:get|use)IntlLocale\b|\bi18n\.language\b/;
/**
 * `resolveNumberLocale` is in here because it is the resolver the other two are
 * written in terms of, not a fourth spelling of the same idea: the hook and the
 * snapshot both return `resolveNumberLocale(...)`. Leaving it out made the two
 * formatters the store builds for itself read as slots nobody could resolve.
 *
 * Widened after measuring every rule that reads this pattern, because one of
 * them is the backward rule and it sees seven times the sites the forward one
 * does. `resolveNumberLocale` appears in two files outside its own definition:
 * the store builds two `Intl.NumberFormat` on it, and `RegionalSettings` binds
 * it to a name used only as a `value` prop. Neither file contains a single
 * `toLocaleString` or `DateTimeFormat`, so the widening moves two slots out of
 * the unresolved column and changes no verdict anywhere else.
 */
const NUMBER_PREFERENCE = /\b(?:get|use)NumberLocale\b|\bresolveNumberLocale\b/;

/**
 * The expression a method was called on, as the eighty characters in front of
 * it. Enough to recognise a receiver and never enough to reach back into the
 * previous statement, which is what the rules below need, being anchored to
 * the end of it.
 */
function receiverOf(source: string, dot: number): string {
  return source.slice(Math.max(0, dot - 80), dot);
}

/**
 * Receivers nobody can argue about, in the two directions that matter.
 *
 * Deliberately narrow. `toLocaleString` on an ordinary variable stays unjudged
 * here, because the alternative is a gate holding opinions about whether
 * `period` is a number, which is wrong about somebody's field sooner or later,
 * and a gate that cries wolf gets weakened by the next person to meet it.
 */
/**
 * The eight files that build a document rather than a screen, and the number
 * of `toLocaleString` calls each one still hands the interface language.
 *
 * They are held deliberately. A screen is read by the person looking at it, so
 * its figures follow that person's number format. A printed report, a PDF and
 * an Excel or e-invoice export are read by whoever receives them, and the
 * locale their figures should follow is the recipient's, which the record
 * already carries as a country code. That rule does not exist yet, so these
 * files keep the language they had rather than being moved somewhere they
 * would have to move again. Of the thirty six counted here, six are dates,
 * which keep the language whatever the document rule turns out to be, twenty
 * seven are numbers waiting on it, and three the gate declines to call either
 * way and counts as unjudged.
 *
 * The list is closed against growth: a ninth file that formats a number on the
 * language fails the screen test below, because the exemption is these names
 * and nothing else. Shrinking it is the direction still on trust, and the
 * counts are written down so that trust has a number attached rather than
 * being a silence. A silence is what let this file claim once that the tree
 * was clean when it held 64 offenders.
 */
const DOCUMENT_BUILDERS: readonly (readonly [string, number])[] = [
  ['features/bim/BIMFilterReportModal.tsx', 2],
  ['features/bim/printReport.ts', 1],
  ['features/boq/exportExcel.ts', 1],
  ['features/contracts/ProgressClaimLineTable.tsx', 1],
  ['features/reporting/ReportingPage.tsx', 2],
  ['features/reports/ReportsPage.tsx', 26],
  ['modules/_shared/pdfBOQExport.ts', 1],
  ['modules/pdf-takeoff/TakeoffViewerModule.tsx', 2],
];

const DOCUMENT_FILES = new Set(DOCUMENT_BUILDERS.map(([file]) => file));

/**
 * What this test says when it fails, because the number on its own invites the
 * wrong repair. The counts describe the branch and this file reads the working
 * tree, so the likeliest cause of a red run is a drifted working copy, and the
 * cheapest thing a reader can do about that is edit the number until it goes
 * green. That is the one move which quietly grows the exemption, which is the
 * exact thing the list exists to stop, so the message names the cure instead of
 * leaving it to be worked out.
 */
const DRIFTED = [
  'A held document formats a different number of figures on the interface language',
  'than this list says it does. Two things cause that and they want opposite fixes.',
  '',
  '1. Your working copy has drifted from the branch. This test reads the working',
  '   tree while the counts describe the branch, so a converted or half converted',
  '   copy of one of these files fails here while CI stays green. Look before you',
  '   touch anything:',
  '',
  '     git diff HEAD -- frontend/src/<the file named in the diff below>',
  '',
  '   If that shows work you did not mean to keep, put the branch bytes back and',
  '   leave the number alone. Read the diff first: restoring throws away whatever',
  '   is on disk, and somebody else may be holding that file.',
  '',
  '2. You moved a figure to the recipient locale on purpose. Then this number is',
  '   what records it, and changing it here is the point rather than a chore.',
  '',
  'Editing the count to match a drifted disk is the one wrong answer of the two.',
].join('\n');

const CERTAINLY_A_DATE =
  /(?:new Date\([^()]*\)|Date\.now\(\)|parseISO\([^()]*\))$|\b\w*(?:_at|_date|At|Date)$/;
const CERTAINLY_A_NUMBER =
  /\.length$|\b(?:Number|parseFloat|parseInt)\([^()]*\)$|\b\w*(?:_count|_total|_sum|Count|Total|Sum)$/;

/**
 * Options that exist on one of the two formatters and not on the other.
 *
 * These decide the question outright where the receiver could not, and they do
 * it without anyone holding an opinion about what a field is called.
 * `maximumFractionDigits` is not a thing a date has.
 */
const NUMBER_OPTION =
  /\b(?:minimum|maximum)(?:Fraction|Integer|Significant)Digits\s*:|\b(?:useGrouping|notation|compactDisplay|currency|currencyDisplay|currencySign|unitDisplay|signDisplay|roundingMode|roundingIncrement)\s*:|\bstyle\s*:\s*['"](?:currency|decimal|percent|unit)['"]/;
const DATE_OPTION =
  /\b(?:year|month|day|weekday|hour|minute|second|timeZone|timeZoneName|dateStyle|timeStyle|era|hour12|hourCycle|dayPeriod|calendar|fractionalSecondDigits)\s*:/;

/** The second argument of a call, read by balancing brackets from the comma. */
function optionsArgument(source: string, from: number): string {
  const rest = source.slice(from);
  const comma = rest.indexOf(',');
  const close = rest.indexOf(')');
  if (comma < 0 || (close >= 0 && close < comma)) return '';
  let depth = 0;
  let i = comma + 1;
  for (; i < rest.length; i += 1) {
    const ch = rest[i] as string;
    if ('{[('.includes(ch)) depth += 1;
    else if ('}])'.includes(ch)) {
      if (depth === 0) break;
      depth -= 1;
    }
  }
  return rest.slice(comma + 1, i);
}

/**
 * The initialiser bound to a bare name, only when the file binds it once.
 *
 * Twice means two things share a name and this reading cannot say which one
 * reached the call, so it declines rather than picking. That refusal is load
 * bearing: `AuditLogPage` binds `d` twice and stays unjudged here, which is the
 * correct answer, not a gap to be closed.
 */
function declaredOnce(source: string, name: string): string | null {
  const bound = [...source.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\n]+)/g)]
    .filter((match) => match[1] === name)
    .map((match) => (match[2] as string).trim());
  return bound.length === 1 ? (bound[0] as string) : null;
}

/**
 * The type annotation on a bare name, only when the file writes it once.
 *
 * Once, not "all of them agree", because this is a text scan with no notion of
 * scope: an unrelated `value: number` in an interface at the top of the file
 * would otherwise answer for a `value` that came in as a prop. Requiring the
 * name to be annotated exactly once in the whole file is what makes the answer
 * about the receiver rather than about a coincidence of naming.
 */
function annotatedOnce(source: string, name: string): string | null {
  const written = [...source.matchAll(new RegExp(`\\b${name}\\s*\\??\\s*:\\s*([A-Za-z_$][\\w$]*)`, 'g'))].map(
    (match) => match[1] as string,
  );
  return written.length === 1 ? (written[0] as string) : null;
}

type Verdict = 'number' | 'date' | 'unjudged';

/**
 * What a `toLocaleString` call is formatting, decided once for both directions.
 *
 * Both rules below need the same answer to the same question, and asking it
 * twice is how the two halves drift apart: a list of number-ish names and a
 * list of date-ish names maintained separately agree on the day they are
 * written and never again. So this is the only place either direction reads a
 * receiver, and the directions differ only in which verdict they call a fault.
 *
 * Four readings, tried in order of how little they assume:
 *
 *   1. the receiver itself, where it settles the matter (`rows.length`)
 *   2. the options argument, which names one formatter or the other outright
 *   3. the single initialiser of a bare receiver name in the same file
 *   4. the single type annotation of a bare receiver name in the same file
 *
 * Anything left over is `unjudged` and is counted, not guessed at. That is the
 * whole discipline: a gate holding opinions about whether `period` is a number
 * is wrong about somebody's field eventually, and a gate that cries wolf gets
 * weakened by the next person who meets it.
 *
 * The receiver must be a BARE name before readings 3 and 4 apply. `a.value`
 * ends in `value` too, and resolving that against an unrelated `const value`
 * elsewhere in the file is how a census turns into a wrong red.
 */
function verdictAt(source: string, dot: number, options: string): Verdict {
  const receiver = receiverOf(source, dot);
  if (CERTAINLY_A_NUMBER.test(receiver)) return 'number';
  if (CERTAINLY_A_DATE.test(receiver)) return 'date';

  const numberOption = NUMBER_OPTION.test(options);
  const dateOption = DATE_OPTION.test(options);
  if (numberOption !== dateOption) return numberOption ? 'number' : 'date';

  const bare = receiver.match(/(?:^|[^\w$.])([A-Za-z_$][\w$]*)\s*$/);
  if (!bare) return 'unjudged';
  const name = bare[1] as string;

  const initialiser = declaredOnce(source, name);
  if (initialiser !== null) {
    if (CERTAINLY_A_NUMBER.test(initialiser)) return 'number';
    if (CERTAINLY_A_DATE.test(initialiser)) return 'date';
    return 'unjudged';
  }
  const annotation = annotatedOnce(source, name);
  if (annotation === 'number') return 'number';
  if (annotation === 'Date') return 'date';
  return 'unjudged';
}

/** Every `toLocaleString` in a file whose locale reaches `pattern`, judged. */
function judgedCalls(source: string, pattern: RegExp): { line: number; verdict: Verdict }[] {
  const aliases = boundTo(source, pattern);
  const calls: { line: number; verdict: Verdict }[] = [];
  for (const match of source.matchAll(/\.toLocaleString\(/g)) {
    const after = match.index + match[0].length;
    if (!reaches(localeArgument(source, after), pattern, aliases)) continue;
    calls.push({
      line: source.slice(0, match.index).split('\n').length,
      verdict: verdictAt(source, match.index, optionsArgument(source, after)),
    });
  }
  return calls;
}

/**
 * A census line, so a run says what it did not judge as well as what it did.
 *
 * Written straight to stdout rather than through `console.log`, which is the
 * obvious way to do this and does not work here: vitest intercepts console and
 * hands it to the reporter, and on a green run the default reporter prints
 * nothing, so the census was invisible in exactly the case it exists for. It
 * only reappeared under `--disableConsoleIntercept`, which nobody passes. A
 * report that reaches no reader is the same thing as no report, and this file
 * already carries one lesson about a gate that printed a confident answer
 * having looked at nothing.
 */
function census(label: string, counted: Verdict[]): void {
  const of = (v: Verdict) => counted.filter((c) => c === v).length;
  const line = `${label}: ${counted.length} seen, ${of('number')} numbers, ${of('date')} dates, ${of('unjudged')} unjudged`;
  process.stdout.write(`${line}\n`);
}

/**
 * What the gate can see in the locale slot of a formatter, which is a different
 * question from what the formatter is formatting.
 *
 * The rules below judge a slot by reading it, and every reading they do assumes
 * the resolver is in the slot as visible text, either called there or bound to a
 * name this same file declares. A slot holding a function parameter defeats all
 * of it, because the answer was decided in another file by whoever called in.
 * That is not a corner: `measurement-format.ts` fell in it. Its formatters read
 * `new Intl.NumberFormat(locale, opts)` where `locale` is the parameter of a
 * caching helper, so for as long as those functions defaulted to the interface
 * language the gate looked straight at them and saw nothing to say.
 *
 * So the slot gets a class of its own for "could not resolve", and the census
 * prints it. An offender list is only an answer if you also know how much of
 * the population it was drawn from, and until this existed an empty list read
 * as "clean everywhere" when part of what it meant was "unread".
 *
 * Measured when written, on the whole tree: 108 `Intl.NumberFormat`, of which 93
 * reach the preference, 1 is a literal, 1 takes the browser default and 13 are
 * unresolved; and 19 `Intl.DateTimeFormat`, of which 8 reach the language, 1
 * takes the default and 10 are unresolved. The date side is mostly unresolved
 * because `formatters.ts` and the Gantt helpers take their locale as a
 * parameter, which is the correct shape for them and unreadable from here all
 * the same. Unreadable is not the same as wrong, and the census says unresolved
 * rather than anything stronger for that reason.
 */
type Slot = 'language' | 'preference' | 'literal' | 'none' | 'unresolved';

function slotClass(argument: string, langAliases: Set<string>, prefAliases: Set<string>): Slot {
  const argued = argument.trim();
  if (argued === '' || argued === 'undefined') return 'none';
  if (LANGUAGE.test(argued)) return 'language';
  if (NUMBER_PREFERENCE.test(argued)) return 'preference';
  if (/^['"]/.test(argued)) return 'literal';
  if (/^[A-Za-z_$][\w$]*$/.test(argued)) {
    if (langAliases.has(argued)) return 'language';
    if (prefAliases.has(argued)) return 'preference';
  }
  return 'unresolved';
}

function slotCensus(label: string, counted: Slot[]): void {
  const of = (s: Slot) => counted.filter((c) => c === s).length;
  const line =
    `${label}: ${counted.length} slots, ${of('language')} language, ${of('preference')} preference, ` +
    `${of('literal')} literal, ${of('none')} browser default, ${of('unresolved')} unresolved`;
  process.stdout.write(`${line}\n`);
}

/**
 * The two files allowed to read the raw preference: the store, which owns it
 * and turns it into an answer, and the settings screen, which has to show the
 * reader what they picked. Everywhere else asks `useNumberLocale`.
 */
const MAY_READ_THE_PREFERENCE = [
  'stores/usePreferencesStore.ts',
  'features/settings/RegionalSettings.tsx',
];

/**
 * A locale tag written into a formatter, argued one line at a time.
 *
 * The snippet is matched against the file, so an exemption covers the line it
 * was argued for and expires the moment that line changes - the same discipline
 * the `toFixed` allowlist uses next door.
 */
const HARDCODED_LOCALE_ALLOWED: readonly { file: string; snippet: string; why: string }[] = [
  {
    file: 'shared/lib/money.ts',
    snippet: "const resolved = new Intl.NumberFormat('en-US', {",
    why:
      'A probe, not a rendering. It asks Intl how many decimal places a currency ' +
      'has and reads `resolvedOptions()`; nothing it produces reaches a screen. ' +
      'CLDR currency digits do not vary by locale, so the tag is a constant here ' +
      'in the same way `2` is.',
  },
];

describe('there is one place the number locale comes from', () => {
  it('no surface reads the raw preference behind the resolver', () => {
    const offenders = PRODUCT_FILES.filter(
      (f) => !MAY_READ_THE_PREFERENCE.includes(f) && /\bs\.numberLocale\b/.test(read(f)),
    );
    expect(offenders).toEqual([]);
  });

  it('no formatter is handed a locale tag written into the source', () => {
    // `new Intl.NumberFormat('de-DE'` and `(1234).toLocaleString('en-US'` alike:
    // a quoted BCP-47 tag in the locale position of anything that formats.
    const pattern =
      /(?:new Intl\.(?:NumberFormat|DateTimeFormat)|\.toLocaleString|\.toLocaleDateString|\.toLocaleTimeString)\(\s*(['"`])([a-z]{2}(?:-[A-Za-z0-9]+)*)\1/g;

    const offenders: string[] = [];
    for (const file of PRODUCT_FILES) {
      const source = read(file);
      for (const match of source.matchAll(pattern)) {
        const line = source.slice(0, match.index).split('\n').length;
        const argued = HARDCODED_LOCALE_ALLOWED.some(
          (a) => a.file === file && source.includes(a.snippet),
        );
        if (!argued) offenders.push(`${file}:${line} ${match[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  }, 60_000);

  // The lesson of the defect above, applied to this file's own instrument.
  //
  // The test before this one anchors the tag to the opening bracket, so it sees
  // `new Intl.NumberFormat('de-DE'` and is blind to
  // `new Intl.NumberFormat(ctx.locale ?? 'de-DE'`, which is the same literal
  // doing the same thing one operator later. That is exactly how the bill grid
  // came to name two languages in its fallbacks while every gate stayed green:
  // a scope defined by the shape of an argument cannot see a wrong argument of
  // another shape. So this reads the whole locale position instead.
  it('no formatter has a locale tag hidden in its fallback either', () => {
    const opener =
      /(?:new Intl\.(?:NumberFormat|DateTimeFormat)|\.toLocaleString|\.toLocaleDateString|\.toLocaleTimeString)\(/g;
    const tag = /(['"`])[a-z]{2}(?:-[A-Za-z0-9]+)*\1/;

    const offenders: string[] = [];
    for (const file of PRODUCT_FILES) {
      const source = read(file);
      for (const match of source.matchAll(opener)) {
        // The locale argument runs to the first comma or the closing bracket,
        // whichever comes first. Neither appears inside a BCP-47 tag.
        const rest = source.slice(match.index + match[0].length);
        const end = Math.min(...[rest.indexOf(','), rest.indexOf(')')].filter((i) => i >= 0));
        const arg = rest.slice(0, end);
        const found = tag.exec(arg);
        if (!found) continue;
        const argued = HARDCODED_LOCALE_ALLOWED.some(
          (a) => a.file === file && source.includes(a.snippet),
        );
        if (!argued) {
          offenders.push(`${file}:${source.slice(0, match.index).split('\n').length} ${match[0]}${arg.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  }, 60_000);

  // An allowlist that outlives the line it was written for is a blank cheque.
  it('every argued exemption still matches its line', () => {
    const stale = HARDCODED_LOCALE_ALLOWED.filter((a) => !read(a.file).includes(a.snippet));
    expect(stale).toEqual([]);
  });

  // Single source of truth, counted over the tree rather than shown by example.
  //
  // Naming the formatters that were wrong on the day this was written would
  // gate the ninth one and let the tenth in, which is the mistake the sibling
  // gate above already made once: it looked for a call with no locale argument
  // at all and was therefore blind to a call with the wrong one. So this counts
  // a property of every number formatter instead - which resolver it binds -
  // and it is a property a new formatter cannot avoid having.
  //
  // `new Intl.NumberFormat(` here, and `x.toLocaleString(` in the pair after
  // it. That method is one name on `Number` and on `Date`, so its shape alone
  // cannot say which rule a call is under: of the 347 in the tree, 304 are
  // numbers and 43 are dates, and separating them took reading every one. So
  // the two tests below judge only receivers nobody can argue about, a `new
  // Date(...)` on one side and a `.length` on the other, and leave the middle
  // unjudged on purpose.
  it('no number formatter is built on the interface language', () => {
    // 2119 product files and 108 number formatters among them when this was
    // written. The file count is asserted because a walker that silently stops
    // finding files would otherwise pass on an empty set, which is the one way
    // a census can be green for the wrong reason.
    expect(PRODUCT_FILES.length).toBeGreaterThan(1800);

    const offenders: string[] = [];
    const slots: Slot[] = [];
    for (const file of PRODUCT_FILES) {
      const source = read(file);
      const aliases = boundTo(source, LANGUAGE);
      const prefAliases = boundTo(source, NUMBER_PREFERENCE);
      for (const match of source.matchAll(/new Intl\.NumberFormat\(/g)) {
        const argument = localeArgument(source, match.index + match[0].length);
        slots.push(slotClass(argument, aliases, prefAliases));
        if (reaches(argument, LANGUAGE, aliases)) {
          offenders.push(`${file}:${source.slice(0, match.index).split('\n').length}`);
        }
      }
    }
    slotCensus('number formatters, by the locale slot the gate can read', slots);

    // Floors, not exact counts, for the same reason the walks below use them:
    // this reads the working tree while the numbers describe the branch. What
    // they defend is the one way an empty offender list lies, which is a walk
    // that found nothing to look at. A resolver that had quietly stopped
    // resolving would report every slot unresolved and an empty offender list
    // with it, so the second floor is the one that matters.
    expect(slots.length, 'the walk found no number formatters at all').toBeGreaterThan(80);
    expect(
      slots.filter((s) => s !== 'unresolved').length,
      'the slot reader resolved almost nothing, so an empty offender list means nothing',
    ).toBeGreaterThan(slots.length / 2);
    expect(offenders).toEqual([]);
  }, 60_000);

  it('and no date formatter is built on the number preference', () => {
    // The same rule read backwards, because "every number in the reader's
    // language" is easy to over-apply. A month name is not a number, the date
    // preference is a separate setting, and pointing the number locale at
    // `Intl.DateTimeFormat` answers a question nobody asked.
    const offenders: string[] = [];
    const slots: Slot[] = [];
    for (const file of PRODUCT_FILES) {
      const source = read(file);
      const aliases = boundTo(source, NUMBER_PREFERENCE);
      const langAliases = boundTo(source, LANGUAGE);
      for (const match of source.matchAll(/new Intl\.DateTimeFormat\(/g)) {
        const argument = localeArgument(source, match.index + match[0].length);
        slots.push(slotClass(argument, langAliases, aliases));
        if (reaches(argument, NUMBER_PREFERENCE, aliases)) {
          offenders.push(`${file}:${source.slice(0, match.index).split('\n').length}`);
        }
      }
    }
    slotCensus('date formatters, by the locale slot the gate can read', slots);

    // No floor on the resolved share here, and that is deliberate rather than
    // an omission. Most of these slots are parameters by design: `formatters.ts`
    // and the Gantt helpers are given a locale by their callers, which is the
    // right shape for a shared helper and unreadable from this distance. A floor
    // would be asserting that the tree is written in a style it is not written
    // in. The count still has to be non-empty, because that failure mode is the
    // walker, not the style.
    expect(slots.length, 'the walk found no date formatters at all').toBeGreaterThan(10);
    expect(offenders).toEqual([]);
  }, 60_000);

  it('reads the locale slot in every shape it claims to, and admits the rest', () => {
    const language = new Set(['uiLocale']);
    const preference = new Set(['chosen']);
    const at = (argument: string) => slotClass(argument, language, preference);

    expect(at('getIntlLocale()')).toBe('language');
    expect(at('useNumberLocale()')).toBe('preference');
    expect(at('resolveNumberLocale(numberLocale')).toBe('preference');
    expect(at('uiLocale')).toBe('language');
    expect(at('chosen')).toBe('preference');
    expect(at("'de-DE'")).toBe('literal');
    expect(at('')).toBe('none');
    expect(at('undefined')).toBe('none');
    // The reading this class was added for. A parameter is a slot whose answer
    // was decided in another file, and the honest report is that the gate does
    // not know, which is what kept `measurement-format.ts` invisible while it
    // formatted every takeoff quantity in the interface language.
    expect(at('locale')).toBe('unresolved');

    // `i18n.language` is a defect in a number formatter's slot, and it is
    // asserted here rather than only described above the rule. It is the third
    // door to the interface language and the one with no resolver in its name,
    // so a reader looking for `getIntlLocale` alone would walk past it. The
    // rule is written as a prohibition on number formatters, which is why this
    // asks the classifier and not a list of date formatters that are allowed.
    expect(at('i18n.language')).toBe('language');
    expect(reaches('i18n.language', LANGUAGE, new Set())).toBe(true);
  });

  it('the classifier answers the shapes it claims to, and refuses the rest', () => {
    // The rule has teeth and knows where they stop. Every reading `verdictAt`
    // performs is exercised here, in both answers and in its refusal, because
    // the census below reports a number either way and a classifier that had
    // quietly stopped resolving anything would report a tidy one.
    const at = (source: string, options = '') =>
      verdictAt(source + '.toLocaleString(', source.length, options);

    // 1. the receiver itself
    expect(at('rows.length')).toBe('number');
    expect(at('summary.item_count')).toBe('number');
    expect(at('row.updated_at')).toBe('date');
    // 2. the options argument, where the receiver said nothing
    expect(at('{value', '{ maximumFractionDigits: 2 }')).toBe('number');
    expect(at('{when', "{ dateStyle: 'medium' }")).toBe('date');
    // 3. the single initialiser of a bare name
    expect(at('const d = new Date(iso);\n  return d')).toBe('date');
    expect(at('const n = Number(raw);\n  return n')).toBe('number');
    // 4. the single annotation of a bare name
    expect(at('const fmt = (n: number) => n')).toBe('number');
    // Including the shape that decided how reading 4 is written. `QtyTile`
    // annotates its receiver inside a destructured props object type, not in a
    // parameter list, so the tempting restriction to `(` or `,` before the name
    // would refuse it. Occurrence-uniqueness is what makes the answer safe
    // instead, and this fixture is here so that a future tightening to a
    // parameter-list rule fails rather than silently dropping the site.
    expect(at('}: {\n  label: string;\n  value: number;\n  unit: string;\n}) {\n  return value')).toBe('number');
    // And the counterpart it depends on: annotated twice, so no longer an
    // answer about this receiver but a coincidence of naming.
    expect(at('interface Row { value: number }\n  const f = (value: string) => value')).toBe('unjudged');
    // and the refusals, which are the point of counting rather than guessing
    expect(at('const total = pick(a, b);\n  return total')).toBe('unjudged');
    expect(at('let d = a;\n  let d = b;\n  return d')).toBe('unjudged');
    // a dotted receiver is never resolved against a same-named local
    expect(at('const value = Number(raw);\n  return item.value')).toBe('unjudged');
  });

  it('no number a screen writes by hand is written in the interface language', () => {
    const offenders: string[] = [];
    const counted: Verdict[] = [];
    for (const file of PRODUCT_FILES) {
      if (DOCUMENT_FILES.has(file)) continue;
      const source = read(file);
      if (!source.includes('.toLocaleString(')) continue;
      for (const { line, verdict } of judgedCalls(source, LANGUAGE)) {
        counted.push(verdict);
        if (verdict === 'number') offenders.push(`${file}:${line}`);
      }
    }
    // What the run judged and what it declined to judge, printed rather than
    // implied. An empty offender list means one of two very different things -
    // every number is in the right place, or nothing was recognised as a
    // number - and only the census tells them apart. On the branch this was
    // written against it reads 37 seen, 0 numbers, 35 dates, 2 unjudged.
    census('screens, on the interface language', counted);
    // Floors, not literals. The counts describe the branch while this walk
    // reads the working tree, so an exact number turns red on a teammate's
    // half converted copy with no way to tell that from a real regression,
    // and the cheap repair is to edit the number until it goes green. A floor
    // says the only two things worth failing on: the walk found sites at all,
    // and the classifier still resolves most of them rather than having
    // quietly decayed into answering `unjudged` to everything, which is the
    // state in which the offender list below is empty for the wrong reason.
    expect(counted.length).toBeGreaterThan(20);
    expect(counted.filter((v) => v !== 'unjudged').length).toBeGreaterThan(counted.length / 2);
    expect(offenders).toEqual([]);
  }, 60_000);

  it('and every document held back is held at the count it was held at', () => {
    // An exemption keyed to a path outlives the path. A file that is renamed
    // or split stops being exempt and nobody is told, so the names are checked
    // against the same walk the rule above uses.
    //
    // The count beside each name is what makes the exemption shrinkable. A
    // name on its own says this file is allowed, in any amount and for good. A
    // name and a number say this file is allowed twenty six times, so a twenty
    // seventh fails, and so does a twenty fifth: moving one of these to the
    // recipient's locale is a change somebody has to write down here, which is
    // the whole point of holding them by name instead of by rule.
    const held: string[] = [];
    const counted: Verdict[] = [];
    for (const [file] of DOCUMENT_BUILDERS) {
      expect(PRODUCT_FILES).toContain(file);
      const source = read(file);
      const calls = judgedCalls(source, LANGUAGE);
      for (const { verdict } of calls) counted.push(verdict);
      held.push(`${file} ${calls.length}`);
    }
    expect(held, DRIFTED).toEqual(DOCUMENT_BUILDERS.map(([file, count]) => `${file} ${count}`));
    expect(DOCUMENT_FILES.size).toBe(DOCUMENT_BUILDERS.length);

    census('documents, held on the interface language', counted);

    // What is actually waiting on the document rule, counted instead of
    // subtracted. This file used to say six of the thirty six were dates and
    // "the other thirty are numbers", which was arithmetic rather than a
    // reading: the walk could recognise the six and had no way to look at the
    // rest. Reading the options argument and the local declarations answers
    // twenty seven of them outright and still cannot answer three, so the
    // claim is now twenty seven numbers and three the gate declines to call.
    //
    // These are exact rather than floors, and that is safe here for a reason
    // that does not hold in the two rules above: `held` has already pinned the
    // per-file totals, so once it passes the composition of those totals is
    // fixed too. A drifted working copy fails on `held` first, with the
    // message that tells the reader not to edit the number.
    //
    // That safety rests on one condition, so here it is by name: `held` and
    // these three counts come out of the same walk in the same test, both from
    // `judgedCalls`. Split them into two tests, or count them from two walks,
    // and the exact numbers below stop being pinned by anything and start
    // failing on drift with the wrong message. Keep them together or make them
    // floors.
    const of = (v: Verdict) => counted.filter((c) => c === v).length;
    expect(of('date'), 'a date keeps the interface language whichever way the document rule goes').toBe(6);
    expect(of('number'), 'these are the figures the recipient rule will have to move').toBe(27);
    expect(of('unjudged'), 'the gate declines to call these, and says so rather than guessing').toBe(3);
  }, 60_000);

  it('and no date it writes by hand is written in the number format', () => {
    // The direction the wave that moved 283 numbers could have broken. A date
    // handed the number preference goes on printing, in the wrong month name,
    // and nothing else in this file would have noticed. The date and time
    // methods need no receiver rule at all: what they format is in the name.
    expect(CERTAINLY_A_DATE.test('new Date(row.created)')).toBe(true);
    expect(CERTAINLY_A_DATE.test('row.updated_at')).toBe(true);
    expect(CERTAINLY_A_DATE.test('rows.length')).toBe(false);

    const offenders: string[] = [];
    const counted: Verdict[] = [];
    for (const file of PRODUCT_FILES) {
      const source = read(file);
      if (!source.includes('.toLocale')) continue;
      const aliases = boundTo(source, NUMBER_PREFERENCE);
      for (const match of source.matchAll(/\.toLocale(?:Date|Time|)String\(/g)) {
        const after = match.index + match[0].length;
        if (!reaches(localeArgument(source, after), NUMBER_PREFERENCE, aliases)) continue;
        const line = source.slice(0, match.index).split('\n').length;
        // The date and time methods need no receiver rule at all: what they
        // format is in the name, so they are a fault here whatever they hold.
        if (match[0] !== '.toLocaleString(') {
          offenders.push(`${file}:${line}`);
          continue;
        }
        const verdict = verdictAt(source, match.index, optionsArgument(source, after));
        counted.push(verdict);
        if (verdict === 'date') offenders.push(`${file}:${line}`);
      }
    }
    // The same census, and it reads very differently from the one above. This
    // direction sees the whole tree rather than the screens alone, and the
    // preference is where the wave put almost everything, so most of what it
    // walks it cannot judge: on the branch this was written against, 269 seen,
    // 83 numbers, 0 dates, 186 unjudged. That share is the honest state of the
    // rule and it is printed rather than rounded up to a clean claim.
    census('everywhere, on the number preference', counted);
    expect(counted.length).toBeGreaterThan(100);
    // Deliberately a low floor: unlike the screens rule, this direction judges
    // a minority of what it sees, and pretending otherwise is what a tidy
    // number would do.
    expect(counted.filter((v) => v === 'number').length).toBeGreaterThan(40);
    expect(offenders).toEqual([]);
  }, 60_000);

  it('the store never hands the raw preference straight to a formatter', () => {
    const store = read('stores/usePreferencesStore.ts');
    expect(store).not.toMatch(/new Intl\.NumberFormat\(\s*numberLocale\b/);
    expect(store).toMatch(/new Intl\.NumberFormat\(resolveNumberLocale\(/);
  });
});

/* ── Half three: the bill is a surface like any other ─────────────────────── */

/**
 * Why this half exists when the two halves above already passed.
 *
 * They compared `<MoneyDisplay>` against `formatCurrency`, and both were right.
 * The bill of quantities called neither. It called `fmtWithCurrency`, a second
 * implementation of the same idea, and handed it a locale derived from the
 * project's region rather than from the reader. So the pair under test agreed
 * while the pair on the screen did not, and the gate stayed green through a
 * defect it was written for. A test of two things that already agree cannot
 * find the third thing that does not.
 *
 * The fix is structural rather than a matching pair of edits: `fmtWithCurrency`
 * now delegates, and the bill reads the same locale as everything else. These
 * assertions hold the shape of that, so the second implementation cannot grow
 * back.
 */

/** Amount and currency of readings caught on the registers, as data. */
const REGISTER_FIXTURES: readonly (readonly [number, string])[] = [
  [1543500, 'GBP'],
  [3091300, 'USD'],
  [906890, 'BRL'],
];

/**
 * The last codes on which the two surfaces disagreed, kept as data.
 *
 * They resolved the decimal count from different sources: the register read a
 * static ISO 4217 list, the bill read what the
 * engine holds, and CLDR gives these five zero decimals where ISO gives two.
 * That was never a contest between two tables, it was a contest between a table
 * and a reader - a Hungarian does not write forints with fillér - and on a
 * screen the reader wins, so the register asks the engine now as well. The
 * opposite rule holds for a document, which is read by a bank rather than by
 * our user, and is written down with the code that writes one, in
 * `money_decimals` in the backend einvoice rules.
 *
 * Eleven other codes used to sit beside these - BHD CLP ISK JOD JPY KRW KWD OMR
 * TND UGX VND - because the bill asked for two decimals on everything, showing
 * cents on yen and hiding a digit on dinars.
 */
const ONCE_DISAGREED = ['COP', 'HUF', 'IDR', 'LBP', 'PKR'];

/** Every currency the project form offers, read from the form itself. */
function offeredCurrencies(): string[] {
  const source = read('features/projects/CreateProjectPage.tsx');
  const codes: string[] = [];
  for (const m of source.matchAll(/value: '([A-Z]{3})'/g)) {
    // The group is always present when the pattern matched, but the index
    // signature does not know that and the build is the only gate that cares.
    if (m[1]) codes.push(m[1]);
  }
  return [...new Set(codes)];
}

/** What `<MoneyDisplay>` puts on the screen for this amount. */
function registerReading(amount: number, currency: string): string {
  const { container } = render(<MoneyDisplay amount={amount} currency={currency} />);
  const text = container.textContent ?? '';
  cleanup();
  return text;
}

describe('the bill and the finance register cannot be told different things', () => {
  it.each(LANGUAGES)('%s writes one amount one way on both surfaces', (language, tag) => {
    speak(language);
    for (const [amount, currency] of REGISTER_FIXTURES) {
      expect(fmtWithCurrency(amount, tag, currency)).toBe(registerReading(amount, currency));
    }
  });

  it('the reader who picked a format is obeyed on both, not just on one', () => {
    // The screenshot pair in one line: an English UI with German numbers. The
    // bill used to answer the project's region here and the register the
    // preference, which is how one record read two ways inside one session.
    speak('en');
    usePreferencesStore.getState().setPreference('numberLocale', 'de-DE');
    for (const [amount, currency] of REGISTER_FIXTURES) {
      const bill = fmtWithCurrency(amount, 'de-DE', currency);
      expect(bill).toBe(registerReading(amount, currency));
      expect(bill).not.toBe(expectedMoney('en', currency, amount));
    }
  });

  it('no currency the product offers reads differently on the two surfaces', () => {
    speak('en');
    const disagree = offeredCurrencies().filter(
      // `en` because `speak('en')` above is what the register will resolve.
      // Naming a tag the UI is not in makes this pass or fail on whether the
      // two tags happen to agree about a symbol, which is not the question.
      (code) => fmtWithCurrency(1234.5, 'en', code) !== registerReading(1234.5, code),
    );
    expect(disagree).toEqual([]);
  });

  it('gives the codes that used to disagree the digit count the engine gives', () => {
    speak('en');
    for (const code of ONCE_DISAGREED) {
      // Asked of Intl rather than written out. "The forint has no fillér" is
      // an opinion, and the whole point of the ruling is that the opinion
      // belongs to CLDR: a test that spells the digits out would go on
      // passing while the product argued with the reader.
      const digits = new Intl.NumberFormat('en', { style: 'currency', currency: code })
        .resolvedOptions().maximumFractionDigits;
      expect(registerReading(1234.5, code), code).toBe(
        new Intl.NumberFormat('en', {
          style: 'currency',
          currency: code,
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        }).format(1234.5),
      );
    }
  });

  it('the bill does not resolve its locale from the project region', () => {
    // The screen follows its reader. The document half of the rule - a GAEB
    // file, a PDF offer, an invoice, all read by somebody who is not our user -
    // is real and unbuilt, and when it is built it will key off the country
    // code the project stores. What it may not do is come back here.
    const page = read('features/boq/BOQEditorPage.tsx');
    expect(page).toMatch(/const locale = useNumberLocale\(\)/);
    const regionResolvers = PRODUCT_FILES.filter((f) => /getLocaleForRegion/.test(read(f)));
    expect(regionResolvers).toEqual([]);
  }, 60_000);

  it('there is one money formatter, and the bill helper is a name for it', () => {
    // The adapter may keep the argument order eleven bill surfaces already use.
    // It may not grow a formatter of its own again.
    const helpers = read('features/boq/boqHelpers.ts');
    const body = helpers.slice(helpers.indexOf('export function fmtWithCurrency'));
    expect(body.slice(0, body.indexOf('\n}'))).not.toMatch(/new Intl\.NumberFormat/);
  });
});

/* ── Half three: one answer for how many decimals a currency gets ─────────── */

/**
 * The one module allowed to work out how many minor units a currency has.
 *
 * It used to be two. `<MoneyDisplay>` took the count from a static ISO 4217
 * table the tree carried at `shared/ui/currencyMinorUnits`, `formatCurrency`
 * asked the formatting engine, and each file carried a comment arguing that it
 * was the correct one. They agreed on every currency the product offers except
 * the five in `ONCE_DISAGREED` above, where CLDR says the currency has no
 * subunit in circulation and ISO says it has two. So one amount read
 * `1234,50 Ft` on the finance register and `1235 Ft` on the bill, and both
 * files were right about their own rule.
 *
 * The tests above pin the outcome: those five codes, those two surfaces. That
 * is a fact about today and it is worth pinning, but it does not stop a third
 * surface from working the count out for itself tomorrow. This half pins the
 * property instead. Whatever the number turns out to be, one module derives it
 * and everything else asks that module, because a second source cannot
 * disagree with the first if it never gets written.
 *
 * The document half of the rule is deliberately out of scope here. An invoice
 * declares its amount to a bank and a tax office rather than to our user, so it
 * follows ISO rather than the reader's convention, and it is stated and acted
 * on in `money_decimals` in the backend einvoice rules. Nothing on a screen is
 * a document, and nothing under this directory should start reading that rule.
 */
const MINOR_UNIT_RESOLVER = 'shared/lib/money.ts';

/**
 * Sites that ask an engine how many minor units a currency has.
 *
 * The question has one shape in JavaScript: build a currency-styled
 * `Intl.NumberFormat` and read `resolvedOptions()` back off it. The window is
 * the 400 characters before the read, which is wider than any option object in
 * this tree and narrower than the gap to an unrelated formatter. Reading
 * backwards rather than forwards is deliberate: the style and the currency are
 * always written before the call is resolved, never after.
 */
function minorUnitProbes(source: string): number[] {
  const found: number[] = [];
  for (const match of source.matchAll(/resolvedOptions\s*\(\s*\)/g)) {
    const before = source.slice(Math.max(0, match.index - 400), match.index);
    if (/style\s*:\s*['"]currency['"]/.test(before)) found.push(match.index);
  }
  return found;
}

/**
 * A static table from ISO codes to digit counts, which is what the deleted file
 * was and what must not come back.
 *
 * Three entries rather than one. A lone `'EUR': 2` is far more likely to be a
 * rate, a fixture or a column width than a currency table, and a table worth
 * the name covers more than a single code. Measured across the whole tree when
 * this was written: zero files.
 */
function currencyDigitTableEntries(source: string): number {
  return (source.match(/['"][A-Z]{3}['"]\s*:\s*\d\b/g) || []).length;
}

/** The text of every `new Intl.NumberFormat(...)` call, brace and paren matched. */
function numberFormatCalls(source: string): { text: string; index: number }[] {
  const calls: { text: string; index: number }[] = [];
  for (const match of source.matchAll(/new Intl\.NumberFormat\(/g)) {
    let depth = 1;
    for (let i = match.index + match[0].length; i < source.length; i++) {
      if (source[i] === '(') depth++;
      else if (source[i] === ')') {
        depth--;
        if (depth === 0) {
          calls.push({ text: source.slice(match.index, i), index: match.index });
          break;
        }
      }
    }
  }
  return calls;
}

/**
 * Formatters that pin an arbitrary currency to two decimal places.
 *
 * This is the deleted table's answer written out by hand. `minimumFractionDigits`
 * and `maximumFractionDigits` both at 2, on a currency the call receives as a
 * variable, is a claim that every currency that can arrive here has two minor
 * units, which is the exact claim the ruling settled against. It prints
 * `1235,00 Ft` for a currency with no fillér, and unlike a ceiling on its own it
 * does so even when the amount is a whole number: `maximumFractionDigits: 2`
 * with no floor inherits the currency's own minimum, so it only leaks a digit
 * on an amount that already had a fraction.
 *
 * A matching pair at 0 is not the same claim and is not counted. Rounding a
 * chart axis or a headline tile to whole units is a decision about that tile,
 * taken by somebody who can see it, and it is right for every currency rather
 * than wrong for five of them.
 *
 * Judged by count and by owning file rather than by a snippet, because these
 * five lines sit in files other people are editing and a snippet exemption
 * expires the moment the line moves. A count and a file set survive a
 * reformat, and still fail on a sixth site or a new file.
 *
 * `pinsAHardcodedCeiling` below now subsumes this one: a pair of two and two is
 * a hardcoded ceiling of two, so anything failing here fails there as well.
 * Both are kept and both name the site, because the two say different things to
 * whoever reads the failure - this one says "you wrote the count down twice",
 * that one says "you wrote it down at all" - and because deleting a green gate
 * to remove an overlap is a trade of coverage for tidiness.
 */
function pinsTwoDecimalsOnAnyCurrency(text: string): boolean {
  if (!/style\s*:\s*['"]currency['"]/.test(text)) return false;
  // The property has two spellings and both had to be read: `currency: code`
  // and the shorthand `currency`, which two of the five sites use. Matching
  // only the first spelling silently passed them, which is the same shape of
  // miss this whole file is about. The leading `[{,]` keeps the pattern off the
  // `'currency'` inside `style: 'currency'`, which is a value and not a key.
  const currency = text.match(/(?:[{,]|^)\s*currency\s*(?::\s*(['"][A-Za-z]{3}['"]|[\w$.]+)|(?=\s*[,}]))/);
  // A literal code is a statement about that one currency, made by somebody who
  // knew which it was. A variable, shorthand included, makes it a statement
  // about every currency that can reach the call.
  if (!currency) return false;
  // Bound to a local before it is asked about. Whether narrowing reaches
  // through an element access is a question about the compiler, and this
  // reader should not need the answer to be right.
  const named = currency[1];
  if (named !== undefined && /^['"]/.test(named)) return false;
  const minimum = text.match(/minimumFractionDigits\s*:\s*(\d+)/);
  const maximum = text.match(/maximumFractionDigits\s*:\s*(\d+)/);
  return Boolean(minimum && maximum && minimum[1] === '2' && maximum[1] === '2');
}

/**
 * The digit options of a currency-styled formatter, read exactly as written.
 *
 * `null` means the rule below has no opinion about this call: it is not
 * currency-styled, or its currency is a literal ISO code. A literal code is a
 * statement about one currency by somebody who could see which one it was. The
 * same words with a variable in that slot are a statement about every currency
 * that can reach the call, and only that version is worth gating.
 */
interface DigitBounds {
  /** `maximumFractionDigits` as the source writes it, `null` when unstated. */
  ceiling: string | null;
  /**
   * Every number the ceiling expression names.
   *
   * A ternary names two of them, and the rule takes the largest, because
   * `maximumFractionDigits: compact ? 1 : 2` pins two on the branch that is not
   * compact - which is exactly where it was found. Empty when the expression
   * names none, which is how a ceiling computed elsewhere reads
   * (`maximumFractionDigits: digits`); those are counted and printed rather
   * than judged, because a matcher that silently drops what it cannot read is
   * the failure this whole file is about.
   */
  ceilingNumbers: number[];
  /** Whether a floor is stated at all, at any value. */
  hasFloor: boolean;
  /** Compact notation, where a low ceiling is the point rather than a mistake. */
  compact: boolean;
}

function digitBoundsOf(text: string, where: string): DigitBounds | null {
  if (!/style\s*:\s*['"]currency['"]/.test(text)) return null;
  // Both spellings, for the reason the detector above gives: the shorthand
  // `currency` is what several of these sites use, and reading only
  // `currency: code` passes them without a word.
  const currency = text.match(/(?:[{,]|^)\s*currency\s*(?::\s*(['"][A-Za-z]{3}['"]|[\w$.]+)|(?=\s*[,}]))/);
  if (!currency) return null;
  // Bound to a local before it is asked about. Whether narrowing reaches
  // through an element access is a question about the compiler, and this
  // reader should not need the answer to be right.
  const named = currency[1];
  if (named !== undefined && /^['"]/.test(named)) return null;
  // To the first comma or brace, which ends the property in every shape this
  // tree writes, a ternary included. An expression carrying its own comma - a
  // call with two arguments - is cut short here and lands in the unreadable
  // bucket rather than being judged on half of itself.
  const ceiling = text.match(/maximumFractionDigits\s*:\s*([^,}\n]+)/);
  // A matched pattern whose capture group is missing is not a call without a
  // ceiling, and the difference is the whole gate. Silently reading `undefined`
  // here would leave `written` null, which files the call under "leaves the
  // count to the currency", which empties the convicted list, which is a green
  // and blind gate - the exact failure this file exists to prevent. So it says
  // so, and names the site, rather than being asserted away with a `!` that
  // moves the same blindness to runtime.
  const captured = ceiling ? ceiling[1] : undefined;
  if (ceiling && captured === undefined) {
    throw new Error(
      `${where}: the ceiling pattern matched but captured nothing. The reader is broken, ` +
        'not the code it was reading. Fix the group before trusting any census this prints.',
    );
  }
  const written = captured === undefined ? null : captured.trim();
  return {
    ceiling: written,
    ceilingNumbers: written ? (written.match(/\d+/g) || []).map(Number) : [],
    hasFloor: /minimumFractionDigits\s*:/.test(text),
    compact: /notation\s*:\s*['"]compact['"]/.test(text),
  };
}

/**
 * A ceiling of two or more on the decimals with no floor under it.
 *
 * The shape reads as "at most two decimals" and is not that. Under
 * `style: 'currency'` an absent `minimumFractionDigits` is not zero: the engine
 * takes the floor from the currency's own minor units and then clamps it down
 * to the ceiling if it sits above. So the ceiling changes nothing at all for a
 * currency with two - a euro amount of 1234.50 prints `1.234,50 €` with this
 * shape and without it - and it is wrong in both directions for every currency
 * that has a different number:
 *
 *   * a currency with none inherits a floor of zero and keeps the ceiling of
 *     two, so 1234.50 yen prints `1.234,5 ¥`, a tenth of a unit the yen does
 *     not have;
 *   * a currency with three has its floor clamped down to two, so the third
 *     digit of a dinar disappears.
 *
 * That EUR and USD are unaffected is what makes this worth a gate rather than a
 * grep. It reads as correct on the two currencies a developer is most likely to
 * open the page in, and a fixture in either of them passes against the broken
 * code, so the shape survives review and survives its own tests.
 *
 * A ceiling below two is a different statement and is not counted. Rounding a
 * chart axis or a headline tile to whole units, or to one decimal under compact
 * notation, is a decision about that tile taken by somebody who can see it, and
 * it is right for every currency rather than wrong for some of them. That is a
 * property of the number written down, not of which file wrote it, which is why
 * there is no list of blessed sites here: a sixth legitimate whole-unit tile
 * needs no permission from this file, and a sixth two-decimal ceiling gets none.
 *
 * THE FLOOR IS NOT PART OF THE RULE, and that is the part worth reading twice.
 * The shape has three spellings and a census that counted one of them was blind
 * to the other two: a literal ceiling, a ceiling behind an expression
 * (`compact ? 1 : 2`, found that way), and a ceiling of two under a floor of
 * zero. The third escapes a rule that wants no floor and escapes the pair
 * detector above, which wants two and two. It is not a milder version of the
 * other two either. On a currency with two minor units `minimumFractionDigits:
 * 0, maximumFractionDigits: 2` drops a digit the currency requires (1234.50
 * euro prints `1.234,5 €`); on a currency with none it invents one (`1.234,5
 * ¥`); on a currency with three it truncates. Three classes, three different
 * wrongs, and no reading under which it is right.
 *
 * So the rule is about the ceiling alone: a number of two or more, written down
 * at a call that serves whatever currency reaches it, is a claim about how many
 * minor digits that currency has - and only the currency knows that. Zero and
 * one are not that claim; they are claims about the tile, true for every
 * currency. That is why two is the boundary and why the floor does not enter.
 *
 * Stated that way ON PURPOSE, rather than as "a floor of zero is forbidden".
 * Somebody wanting a summary tile to drop the minor unit on a whole amount is
 * asking a real question, and it is the founder's open one. The honest spelling
 * of that wish is `minimumFractionDigits: 0` with no ceiling at all, or with a
 * ceiling the resolver supplies, and both pass this rule untouched. The gate
 * takes no position on the question; it only refuses the answer that hardcodes
 * the count.
 *
 * A rule of "the floor and the ceiling must not straddle the currency's own
 * count" was considered and does not survive contact with the tree: under
 * `maximumFractionDigits: 0` the engine defaults the floor to two on a euro and
 * clamps it down, which is a straddle by any literal reading and is exactly the
 * whole-unit tile this file deliberately spares. The wording would convict five
 * correct sites, so it is not the wording.
 *
 * Known false positive, unhit today and cheap to recognise when it lands: the
 * ceiling is read as "every number inside the expression", so an identifier
 * carrying a digit (`max2`, `DIGITS_2`) would be read as the number in it. The
 * answer then is to name the constant without the digit or to teach this reader
 * the constant, not to widen the rule.
 */
function pinsAHardcodedCeiling(text: string, where: string): boolean {
  const bounds = digitBoundsOf(text, where);
  if (!bounds || bounds.ceilingNumbers.length === 0) return false;
  return Math.max(...bounds.ceilingNumbers) >= 2;
}

/**
 * Why a one-sided digit override needs a fallback around it, and what "around"
 * can honestly be read to mean.
 *
 * A currency-styled formatter that writes one bound and leaves the other to the
 * currency is the only shape whose legality depends on the engine. The revision
 * that made a defaulted floor clamp down to a written ceiling is recent enough
 * that a desktop build on an older WebKit still reaches the previous rule, where
 * the same call is a `RangeError` thrown from inside render - the shape of issue
 * 391, and the reason `shared/lib/fractionDigits.ts` exists. Five of these
 * survive such an engine today only because each sits inside a try with a real
 * fallback, which nothing was checking and nobody had written down.
 *
 * WHICH ENGINE VERSION IS THE BOUNDARY IS NOT MEASURED. It is stated here as
 * unmeasured rather than rounded to safe. What is measured is that the desktop
 * build names a minimum system old enough to reach engines predating the
 * revision, that no browserslist or build target narrows that, and that the
 * clamp behaves on the engine this tree is developed against.
 *
 * The verdict is lexical and it is deliberately generous about where the
 * fallback lives, because the two shapes in this tree are not the same shape:
 * a catch that returns, and an empty catch with a comment whose function returns
 * below the try. The second is the better of the two and a rule demanding a
 * `return` inside the catch would convict it. So the question asked is "does the
 * catch path reach a value", answered as: there is a catch, it does not rethrow,
 * and a `return` exists either in the catch or between the catch and the end of
 * the enclosing function.
 *
 * The end of the function rather than the end of the nearest block, and that
 * distinction was not theoretical: the first version of this rule stopped at the
 * nearest brace and convicted `features/insights/charts.tsx`, whose try sits two
 * ifs deep with its fallback on the last line of the function. Control leaves
 * both of those blocks on the catch path, so a reader that stops at the first
 * one reports a correct site as exposed - the exact false conviction this rule
 * would be worthless with.
 *
 * WHAT IT CANNOT SEE, named rather than implied. It reads one function's text.
 * A formatter whose fallback lives one hop away in a helper, or whose only try
 * sits in a caller, reads as uncontained here and would have to be argued rather
 * than silently passed - which is the safe direction for this particular rule.
 *
 * Its scope is also narrower than the risk, on purpose but worth knowing: it
 * asks `digitBoundsOf`, which declines to speak about a formatter naming a
 * literal ISO code, and a one-sided override on a literal code would throw on an
 * old engine exactly the same way. There are none in this tree today - every one
 * of the fourteen currency-styled formatters takes its code from a variable - so
 * widening it now would be writing a rule against an empty set. If a literal one
 * appears, widen this rather than assuming it inherited the protection.
 */
type Containment = 'contained' | 'no try' | 'no catch' | 'rethrows' | 'no fallback';

/**
 * The same text with every string, template, comment and regex body replaced by
 * spaces, one space per character, so offsets still line up.
 *
 * Every verdict below is a brace count across a whole function body, which is a
 * much wider span than anything else this file reads, and a lone brace inside a
 * string or a comment anywhere in that span moves the boundary silently. Silent
 * is the problem: the verdict comes back wrong rather than absent, and it comes
 * back wrong in the direction that convicts correct code. This tree already
 * writes the shape - `/^[A-Z]{3}$/` sits between the try and the call in two of
 * the six sites, and only balances by luck - so the reader blanks first and
 * counts after. Blanking a template whole, interpolations included, is safe
 * here: their braces are balanced by construction, and no `return` statement
 * lives inside one.
 */
function codeOnly(text: string): string {
  const out = text.split('');
  const blank = (from: number, to: number) => {
    for (let i = from; i < to && i < out.length; i++) if (out[i] !== '\n') out[i] = ' ';
  };
  let i = 0;
  let prev = '';
  let prev2 = '';
  while (i < text.length) {
    const c = text[i];
    const next = text[i + 1];
    if (c === '/' && next === '/') {
      const end = text.indexOf('\n', i);
      blank(i, end === -1 ? text.length : end);
      i = end === -1 ? text.length : end;
      continue;
    }
    if (c === '/' && next === '*') {
      const end = text.indexOf('*/', i + 2);
      blank(i, end === -1 ? text.length : end + 2);
      i = end === -1 ? text.length : end + 2;
      continue;
    }
    // A slash is a regex only where a value may start. After a name, a literal
    // or a closing bracket it is division, and blanking to the next slash there
    // would eat real code. `<` is deliberately not on the list: this tree is
    // full of JSX, and reading the slash of `</div>` as a regex would blank
    // everything up to the next slash on the line. `=>` is on it, because
    // `x => /^[A-Z]/.test(x)` is written here and its braces would count.
    const opensAValue = prev === '' || '(,=:[!&|?{;+-*%^~'.includes(prev) || (prev === '>' && prev2 === '=');
    if (c === '/' && opensAValue) {
      let j = i + 1;
      let closed = -1;
      let inClass = false;
      for (; j < text.length && text[j] !== '\n'; j++) {
        if (text[j] === '\\') {
          j++;
          continue;
        }
        if (text[j] === '[') inClass = true;
        else if (text[j] === ']') inClass = false;
        else if (text[j] === '/' && !inClass) {
          closed = j;
          break;
        }
      }
      if (closed !== -1) {
        blank(i, closed + 1);
        i = closed + 1;
        prev2 = prev;
        prev = '/';
        continue;
      }
    }
    if (c === "'" || c === '"' || c === '`') {
      let j = i + 1;
      for (; j < text.length; j++) {
        if (text[j] === '\\') {
          j++;
          continue;
        }
        if (text[j] === c) break;
      }
      blank(i, Math.min(j + 1, text.length));
      i = j + 1;
      prev2 = prev;
      prev = c;
      continue;
    }
    if (c !== undefined && c.trim() !== '') {
      prev2 = prev;
      prev = c;
    }
    i++;
  }
  return out.join('');
}

function blockAfter(source: string, open: number): number {
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}') {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/**
 * Whether the brace at `openBrace` opens a function body rather than a block.
 *
 * A control statement and a function both put `) {` on the page, so the answer
 * is the word in front of the matching `(`, not the shape of the punctuation.
 * Reading only the punctuation calls `if (/^[A-Z]{3}$/.test(code)) {` a
 * function, which is precisely the line standing between one real site and its
 * fallback.
 */
function opensAFunction(source: string, openBrace: number): boolean {
  let i = openBrace - 1;
  while (i >= 0 && /\s/.test(source[i] ?? '')) i--;
  if (i >= 1 && source[i] === '>' && source[i - 1] === '=') return true;
  if (source[i] !== ')') return false;
  let depth = 0;
  for (; i >= 0; i--) {
    if (source[i] === ')') depth++;
    else if (source[i] === '(') {
      depth--;
      if (depth === 0) break;
    }
  }
  // An unmatched paren leaves `i` at -1, and `slice(start, -1)` is the whole
  // string bar its last character rather than nothing - a boundary that would
  // hand the test below the tail of the file to judge. Said out loud because it
  // reads like an empty slice.
  if (i < 0) return true;
  // The text in front of the paren is tested for a trailing control keyword
  // rather than having a word pulled out of it and defaulted. A verdict that
  // arrives through `?? ''` is the shape this file exists to catch: it turns
  // "the reader found nothing" into an answer, and here that answer narrows the
  // span the containment rule searches, which convicts correct code.
  return !/\b(if|for|while|switch|catch)\s*$/.test(source.slice(Math.max(0, i - 40), i));
}

/** The closing brace of the innermost function body containing `index`. */
function enclosingFunctionEnd(source: string, index: number): number {
  let depth = 0;
  for (let i = index; i >= 0; i--) {
    const c = source[i];
    if (c === '}') depth++;
    else if (c === '{') {
      if (depth > 0) depth--;
      else if (opensAFunction(source, i)) {
        const end = blockAfter(source, i);
        return end === -1 ? source.length : end;
      }
    }
  }
  return source.length;
}

function containmentOf(text: string, index: number): Containment {
  const source = codeOnly(text);
  // The innermost `try {` whose block holds the call. Walking the list backwards
  // reaches the innermost first, which is the one whose catch would run.
  const tries = [...source.slice(0, index).matchAll(/\btry\s*\{/g)];
  for (let t = tries.length - 1; t >= 0; t--) {
    const found = tries[t];
    if (found?.index === undefined) continue;
    // The brace is found by searching forward rather than by measuring `found[0]`.
    // Whether a match array's zeroth group counts as always-present is a question
    // about the compiler's lib, and a reader should not rest a verdict on the
    // answer to that.
    const open = source.indexOf('{', found.index);
    if (open === -1) continue;
    const close = blockAfter(source, open);
    if (close === -1 || index <= open || index >= close) continue;
    if (!/^\s*catch\b/.test(source.slice(close + 1, close + 40))) return 'no catch';
    const catchOpen = source.indexOf('{', close + 1);
    if (catchOpen === -1) return 'no catch';
    const catchClose = blockAfter(source, catchOpen);
    if (catchClose === -1) return 'no catch';
    const body = source.slice(catchOpen, catchClose + 1);
    if (/\bthrow\b/.test(body)) return 'rethrows';
    if (/\breturn\b/.test(body)) return 'contained';
    // An empty catch is fine when the function goes on to produce a value, and
    // the value is not necessarily in the block the try sits in: one real site
    // has its try nested two ifs deep and its fallback at the end of the
    // function. Control leaves each of those blocks in turn on the catch path,
    // so the span that matters runs from the catch to the end of the function
    // rather than to the end of the nearest brace.
    const end = enclosingFunctionEnd(source, catchClose);
    return /\breturn\b/.test(source.slice(catchClose + 1, end)) ? 'contained' : 'no fallback';
  }
  return 'no try';
}

/** Exactly one of the two bounds written down: the engine-dependent shape. */
function isOneSided(bounds: DigitBounds): boolean {
  const hasCeiling = bounds.ceiling !== null;
  return hasCeiling !== bounds.hasFloor;
}

/**
 * What the reader makes of the one formatter a self-test fixture holds.
 *
 * Every step here is proven rather than assumed, and the reason is the same
 * reason the self-tests exist at all. `calls[0]!` on a list that came back
 * empty, or `?.` on a reading that came back null, both turn a reader that has
 * stopped reading into an assertion that still passes. That is the exact shape
 * this file is written to catch in other people's code, so it does not get to
 * live in the file's own scaffolding. A fixture that stops parsing says which
 * fixture it was and stops the run.
 */
function fixtureBounds(source: string): DigitBounds {
  const where = `self-test fixture: ${source}`;
  const calls = numberFormatCalls(source);
  const only = calls[0];
  if (calls.length !== 1 || only === undefined) {
    throw new Error(`${where}: expected one Intl.NumberFormat call, the reader found ${calls.length}`);
  }
  const bounds = digitBoundsOf(only.text, where);
  if (bounds === null) {
    throw new Error(`${where}: the reader declined a fixture it exists to read`);
  }
  return bounds;
}

/** One match, kept as its parts rather than as a `file:line` string. */
interface Site {
  file: string;
  line: number;
}

/** The 1-based line `index` falls on, for a census a person has to act on. */
function siteAt(file: string, source: string, index: number): Site {
  return { file, line: source.slice(0, index).split('\n').length };
}

const label = (site: Site) => `${site.file}:${site.line}`;

/**
 * Where that shape still lives, and how much of it each file may hold.
 *
 * These are money surfaces that never asked anybody: they predate the resolver
 * and were not part of the register-versus-bill disagreement, so routing them
 * is a separate change on files that are currently being edited elsewhere. They
 * are listed here so the gate below is a debt with an address rather than a
 * bare number.
 *
 * A ceiling per file rather than one total, because a total cannot see a site
 * moving between two files that are both already named. Counting per file
 * costs nothing in churn: a count changes only when somebody adds or removes
 * one of these calls, which is the event worth failing on. Reformatting, or
 * any other edit to these four files, moves the line numbers and leaves every
 * count where it was.
 *
 * A file absent from this map has a ceiling of zero, so the shape appearing
 * anywhere new fails wherever it lands. Fixing one of the five lowers a count
 * and keeps passing, which is the direction this is meant to move.
 */
// Empty on purpose, and this is the whole point of a ratchet. It once budgeted
// five sites across four files, which was honest while those five existed. They
// are gone: all four surfaces now go through the shared resolver, so the census
// below finds nothing. A budget that outlives the thing it was budgeting for is
// worse than no budget, because the assertion is `count > ceiling` and a
// ceiling of five over a real count of zero passes while five regressions walk
// back in unremarked. The gate was green and toothless at the same time.
//
// With no entries every file has a ceiling of zero, so the first site to
// reappear anywhere fails, which is what this test was written to do.
const PINS_TWO_DECIMALS: Readonly<Record<string, number>> = {};

describe('one module decides how many decimals a currency gets', () => {
  it('nothing but the resolver asks an engine for a currency digit count', () => {
    // The denominator is asserted for the same reason the census next door
    // asserts it: a walker that quietly stopped finding files would report an
    // empty offender list, and an empty list is the answer this test gives when
    // it passes. A gate that examined nothing must not be able to look like a
    // gate that examined everything.
    expect(PRODUCT_FILES.length).toBeGreaterThan(1800);

    const sites: Site[] = [];
    for (const file of PRODUCT_FILES) {
      const source = read(file);
      for (const index of minorUnitProbes(source)) {
        sites.push(siteAt(file, source, index));
      }
    }
    const owners = [...new Set(sites.map((site) => site.file))];

    process.stdout.write(
      `minor units: ${PRODUCT_FILES.length} files scanned, ${sites.length} engine probe(s) ` +
        `in ${owners.length} file(s): ${sites.map(label).join(', ') || 'none'}\n`,
    );
    expect(owners).toEqual([MINOR_UNIT_RESOLVER]);
  }, 60_000);

  it('no module keeps a currency table of its own', () => {
    const tables = PRODUCT_FILES.filter((file) => currencyDigitTableEntries(read(file)) >= 3);
    process.stdout.write(
      `minor units: ${tables.length} static code-to-digit table(s) across ${PRODUCT_FILES.length} files\n`,
    );
    expect(tables).toEqual([]);
  }, 60_000);

  it('no new surface pins an arbitrary currency to two decimals', () => {
    const sites: Site[] = [];
    for (const file of PRODUCT_FILES) {
      const source = read(file);
      for (const call of numberFormatCalls(source)) {
        if (pinsTwoDecimalsOnAnyCurrency(call.text)) {
          sites.push(siteAt(file, source, call.index));
        }
      }
    }

    const perFile = new Map<string, number>();
    for (const site of sites) perFile.set(site.file, (perFile.get(site.file) ?? 0) + 1);

    process.stdout.write(
      `minor units: ${sites.length} site(s) pinning any currency to two decimals, ` +
        `in ${perFile.size} file(s): ${sites.map(label).join(', ') || 'none'}\n`,
    );

    // The probe has to be shown to still recognise the shape. An empty result
    // is the answer this test gives when it passes, and it is also the answer a
    // matcher gives after it has quietly stopped matching, so the two are
    // indistinguishable from the count alone. PRODUCT_FILES.length guards the
    // walker in the test above; this guards the probe, by handing it the exact
    // thing it exists to catch and requiring it to catch it.
    // Both polarities, because a probe that says yes to everything is as
    // useless as one that says no to everything, and the census alone cannot
    // tell either of them from a clean tree.
    const offending =
      "new Intl.NumberFormat(locale, { style: 'currency', currency, " +
      'minimumFractionDigits: 2, maximumFractionDigits: 2 })';
    const innocent =
      "new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR', " +
      'minimumFractionDigits: 2, maximumFractionDigits: 2 })';
    const flags = (source: string) => numberFormatCalls(source).filter((c) => pinsTwoDecimalsOnAnyCurrency(c.text));
    expect(flags(offending)).toHaveLength(1);
    // A literal code is a statement about one currency by someone who knew
    // which. Flagging it too would make the probe unusable and the ceiling of
    // zero unmeetable.
    expect(flags(innocent)).toHaveLength(0);

    // A ratchet, not an allowlist: one comparison that pins which files may
    // carry this shape and how many each may carry. The budget is empty now, so
    // every file has a ceiling of zero and any site fails wherever it lands.
    const overBudget = [...perFile]
      .filter(([file, count]) => count > (PINS_TWO_DECIMALS[file] ?? 0))
      .map(([file, count]) => `${file}: ${count} of at most ${PINS_TWO_DECIMALS[file] ?? 0}`);
    expect(overBudget).toEqual([]);
  }, 60_000);

  /**
   * WHAT THIS ONE DOES NOT SEE, stated because a partial detector believed to
   * be a whole one is worse than none.
   *
   * It reads one call at a time, in one file, and it only looks at calls that
   * say `style: 'currency'`. A digit count pinned one hop away is invisible to
   * it by construction. The worked example is `features/boq/ResourceSummary.tsx`,
   * whose table hands its money to `fmtMoney`, a `useMemo` over
   * `createRSMoneyFormatter`, and the formatter lives in there - with no
   * `style: 'currency'` at all, because that column prints the ISO code in its
   * own cell. Every part of that is invisible here twice over: the wrong file,
   * and the wrong shape. It reads clean today because the helper asks
   * `currencyFractionDigits`, and if somebody re-pinned it to a literal 2 this
   * test would stay green while the table went wrong.
   *
   * That shape is covered, by `shared/ui/aTotalIsWrittenLikeItsColumn.test.tsx`,
   * which follows the hop into the helper and judges its body. It found the
   * ResourceSummary shape by re-pinning that file on purpose and watching its
   * own census stay green, which is the only way anybody learns anything about
   * a matcher. Neither file replaces the other and neither should grow into
   * the other's job.
   */
  it('no surface hardcodes a ceiling of two or more on a currency it does not name', () => {
    // The denominator, asserted for the reason its neighbours assert one: an
    // empty offender list is what this test prints when it passes, and it is
    // also what a walker prints after it has quietly stopped finding files.
    expect(PRODUCT_FILES.length).toBeGreaterThan(1800);

    const convicted: Site[] = [];
    const spared: string[] = [];
    const unreadable: string[] = [];
    const currencyDecides: string[] = [];

    for (const file of PRODUCT_FILES) {
      const source = read(file);
      for (const call of numberFormatCalls(source)) {
        // The site is named before the reader runs, so a reader that fails on
        // this call can say which one it was.
        const at = label(siteAt(file, source, call.index));
        const bounds = digitBoundsOf(call.text, at);
        if (!bounds) continue;
        if (bounds.ceiling === null) currencyDecides.push(`${at}${bounds.hasFloor ? ' min written' : ''}`);
        else if (bounds.ceilingNumbers.length === 0) unreadable.push(`${at} max=${bounds.ceiling}`);
        // The verdict comes from the probe the self-test below exercises, not
        // from a second copy of its rule written out here. Two copies drift,
        // and the one under test is never the one that decided.
        else if (pinsAHardcodedCeiling(call.text, at)) convicted.push(siteAt(file, source, call.index));
        else spared.push(`${at} max=${bounds.ceiling}${bounds.hasFloor ? ' min written' : ''}${bounds.compact ? ' compact' : ''}`);
      }
    }

    const seen = convicted.length + spared.length + unreadable.length + currencyDecides.length;
    // The whole census by name, on every run, passing or failing. A count with
    // no names attached cannot be acted on and cannot be audited, and the sites
    // this rule deliberately does not judge are the ones a reader most needs to
    // see: they are where the next one of these will be written.
    process.stdout.write(
      `minor units: ${seen} currency-styled formatter(s) on a variable currency; ` +
        `${convicted.length} hardcode a ceiling of two or more: ` +
        `${convicted.map(label).join(', ') || 'none'}\n` +
        `minor units: ${spared.length} ceiling(s) below two, outside the rule: ${spared.join(', ') || 'none'}\n` +
        `minor units: ${unreadable.length} ceiling(s) this rule cannot read: ${unreadable.join(', ') || 'none'}\n` +
        `minor units: ${currencyDecides.length} leaving the count to the currency: ` +
        `${currencyDecides.join(', ') || 'none'}\n`,
    );
    expect(seen).toBeGreaterThanOrEqual(12);

    // Both polarities, on the probe itself. A green census means either "there
    // is nothing to find" or "the reader went blind", and the two are the same
    // from the outside. Each string below is a shape that exists in this tree,
    // written out rather than described, so the probe has to answer them all.
    const flags = (source: string) =>
      numberFormatCalls(source).filter((c) => pinsAHardcodedCeiling(c.text, `self-test fixture: ${source}`));
    // Convicted: the plain shape, on the shorthand spelling several sites use.
    expect(flags("new Intl.NumberFormat(locale, { style: 'currency', currency, maximumFractionDigits: 2 })")).toHaveLength(1);
    // Convicted: the same claim behind a ternary. The branch that is not
    // compact pins two, and reading only the first number would spare it.
    expect(
      flags(
        "new Intl.NumberFormat(locale, { style: 'currency', currency: code, " +
          "notation: compact ? 'compact' : 'standard', maximumFractionDigits: compact ? 1 : 2 })",
      ),
    ).toHaveLength(1);
    // Spared: whole units, and one decimal under compact notation. Both are
    // decisions about a tile, and both are right for every currency.
    expect(flags("new Intl.NumberFormat(locale, { style: 'currency', currency: code, maximumFractionDigits: 0 })")).toHaveLength(0);
    expect(
      flags(
        "new Intl.NumberFormat(locale, { style: 'currency', currency: code, " +
          "notation: 'compact', maximumFractionDigits: 1 })",
      ),
    ).toHaveLength(0);
    // Convicted: the third spelling, and the reason this rule stopped asking
    // about the floor. A floor of zero under a ceiling of two is not a milder
    // version of the bare ceiling; it drops a digit the euro requires, invents
    // one the yen does not have, and truncates the dinar. It was real: the
    // preferences store carried exactly this and was deleted rather than
    // repaired, which is why the count below can be zero.
    expect(
      flags(
        "new Intl.NumberFormat(locale, { style: 'currency', currency: safe, " +
          'minimumFractionDigits: 0, maximumFractionDigits: 2 })',
      ),
    ).toHaveLength(1);
    // Spared: both bounds come from the resolver, so nothing here is a guess
    // about the currency. This is the shape the rule pushes work towards.
    expect(
      flags(
        "new Intl.NumberFormat(locale, { style: 'currency', currency: code, " +
          'minimumFractionDigits: digits, maximumFractionDigits: digits })',
      ),
    ).toHaveLength(0);
    // Spared, and this one carries the founder's open question: a floor of zero
    // with no ceiling is the honest spelling of "drop the minor unit when the
    // amount is whole". The engine takes the ceiling from the currency, so the
    // wish is expressed without anybody guessing the count. The gate has no
    // opinion on whether a tile should want that; it only refuses the answer
    // that writes the count down.
    expect(
      flags("new Intl.NumberFormat(locale, { style: 'currency', currency: code, minimumFractionDigits: 0 })"),
    ).toHaveLength(0);
    // Spared: a literal code, a statement about one currency by somebody who
    // knew which one. Flagging it would make a ceiling of zero unmeetable.
    expect(flags("new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 })")).toHaveLength(0);
    // Spared: no ceiling at all, which is the shape this rule pushes towards.
    expect(flags("new Intl.NumberFormat(locale, { style: 'currency', currency: code })")).toHaveLength(0);
    // Not convicted, and not silently dropped either: a ceiling computed
    // elsewhere is unreadable here and belongs in the census as unreadable.
    const derived = "new Intl.NumberFormat(locale, { style: 'currency', currency: code, maximumFractionDigits: digits })";
    expect(flags(derived)).toHaveLength(0);
    expect(fixtureBounds(derived).ceilingNumbers).toEqual([]);

    // A ceiling this rule cannot read is the same claim as one it can, made in
    // a way nobody can check. There are none today, so it is pinned at none:
    // the first one has to be argued in a review rather than land unseen.
    //
    // The legitimate first occupant of this bucket is easy to predict: a ceiling
    // the resolver supplies, `maximumFractionDigits: currencyFractionDigits(code)`,
    // which is correct and unreadable at the same time. When that lands, the
    // answer is to teach this reader to recognise the resolver call, not to
    // relax the assertion. Relaxing it gives up the only signal that separates a
    // computed ceiling from a hardcoded one wearing a variable's name.
    expect(unreadable).toEqual([]);

    // No budget, no allowlist, no named exemptions. Every file has a ceiling of
    // zero, so the shape fails wherever it appears, and the sites this rule
    // spares are spared by what they say rather than by where they live.
    expect(convicted.map(label)).toEqual([]);
  }, 60_000);

  /**
   * The containment that keeps the surviving one-sided overrides legal, which
   * was load-bearing before anybody knew it was there.
   *
   * See the note on `containmentOf` for what a one-sided override is, why its
   * legality depends on the engine, why the engine version boundary is stated as
   * unmeasured rather than assumed safe, and what this reader cannot see. The
   * short version: five sites survive a pre-revision engine only because each
   * sits inside a try with a fallback, and deleting one of those try blocks
   * reintroduces issue 391 on somebody's older machine without anybody touching
   * a formatter. That is not a change a reviewer would flag, which is the whole
   * argument for asserting it here.
   */
  it('every one-sided digit override sits inside a fallback', () => {
    expect(PRODUCT_FILES.length).toBeGreaterThan(1800);

    const contained: string[] = [];
    const exposed: string[] = [];

    for (const file of PRODUCT_FILES) {
      const source = read(file);
      for (const call of numberFormatCalls(source)) {
        const at = label(siteAt(file, source, call.index));
        const bounds = digitBoundsOf(call.text, at);
        if (!bounds || !isOneSided(bounds)) continue;
        const verdict = containmentOf(source, call.index);
        if (verdict === 'contained') contained.push(at);
        else exposed.push(`${at} ${verdict}`);
      }
    }

    process.stdout.write(
      `minor units: ${contained.length + exposed.length} one-sided override(s); ` +
        `${exposed.length} without a fallback: ${exposed.join(', ') || 'none'}\n` +
        `minor units: contained: ${contained.join(', ') || 'none'}\n`,
    );

    // The population, not just the file count. An `isOneSided` that stopped
    // recognising the shape would find nothing to judge, report nothing exposed
    // and pass - which is the same output as a tree where every site is
    // contained. Six today; the floor sits just under it so removing one site is
    // allowed and losing the reader is not.
    expect(contained.length + exposed.length).toBeGreaterThanOrEqual(5);

    // The blanker first, since every verdict rests on it. Two directions: a
    // brace that is code survives, a brace that is text does not, and the length
    // is unchanged so the offsets the verdicts use still point where they did.
    // A blanker that blanked everything would make every fixture below pass.
    const braces = (s: string) => codeOnly(s).match(/[{}]/g) ?? [];
    expect(codeOnly("if (x) { s = '}'; }")).toHaveLength(19);
    expect(braces("if (x) { s = '}'; }")).toEqual(['{', '}']);
    expect(braces('if (x) { /* } */ }')).toEqual(['{', '}']);
    expect(braces('if (x) { if (/[}]/.test(y)) z(); }')).toEqual(['{', '}']);
    expect(braces('const t = `a ${b} c`; { }')).toEqual(['{', '}']);
    // Division is not a regex. Reading it as one would blank to the next slash
    // and take real braces with it.
    expect(braces('const r = a / b; { c / d; }')).toEqual(['{', '}']);
    // JSX closing tags are not regexes either, which is why `<` is not on the
    // list of characters a value may start after.
    expect(braces('<div>{a}</div>;<p>{b}</p>')).toEqual(['{', '}', '{', '}']);

    // The reader, in both directions, on the shapes this tree actually writes
    // and on the three that would fool a brace counter. A verdict of "contained"
    // for everything is what this test prints when it passes and is also what a
    // broken reader prints, so the reader answers for itself first.
    const only = (source: string) => containmentOf(source, source.indexOf('new Intl.NumberFormat'));
    const call = "new Intl.NumberFormat(l, { style: 'currency', currency: c, maximumFractionDigits: 0 }).format(v)";

    // Contained, shape one: the catch returns.
    expect(only(`function f() { try { return ${call}; } catch { return String(v); } }`)).toBe('contained');
    // Contained, shape two: an empty catch and a return below the try. This is
    // the better of the two shapes and the reason the rule does not demand a
    // return inside the catch - two real sites are written this way.
    expect(only(`function f() { try { return ${call}; } catch { /* fall through */ } return plain(v); }`)).toBe(
      'contained',
    );
    // Contained, shape three: the same, with the try nested inside two ifs and
    // the fallback at the end of the function. This is `charts.tsx`, and the
    // first version of this rule convicted it.
    expect(
      only(
        `function f() { if (a) { if (/^[A-Z]{3}$/.test(c)) { try { return ${call}; } ` +
          `catch { /* fall through */ } } } return plain(v); }`,
      ),
    ).toBe('contained');
    // Exposed for the same nesting with no fallback anywhere in the function,
    // so the widened span is not simply answering "contained" to everything.
    expect(
      only(`function f() { if (a) { if (b) { try { return ${call}; } catch { report(); } } } }`),
    ).toBe('no fallback');
    // Exposed, and each for its own reason, so a reader that collapsed the three
    // into one verdict would be caught here.
    expect(only(`function f() { return ${call}; }`)).toBe('no try');
    expect(only(`function f() { try { return ${call}; } catch (e) { throw e; } }`)).toBe('rethrows');
    expect(only(`function f() { try { return ${call}; } catch { report(); } }`)).toBe('no fallback');

    // Adversarial: a brace inside a string, inside a comment, and inside a regex
    // between the try and the call. Each one moves the block boundary a brace
    // counter computes, and each would flip a verdict rather than raise an
    // error, which is the failure this rule would be worthless with.
    expect(only(`function f() { try { const s = '{'; return ${call}; } catch { return String(v); } }`)).toBe(
      'contained',
    );
    expect(only(`function f() { try { /* } */ return ${call}; } catch { return String(v); } }`)).toBe('contained');
    expect(only(`function f() { try { return ${call}; } catch { if (/[}]/.test(x)) return '0'; return String(v); } }`)).toBe(
      'contained',
    );

    expect(exposed).toEqual([]);
  }, 60_000);
});
