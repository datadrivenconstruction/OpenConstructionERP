// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A total is written the way the column it sums is written.
//
// Measured on the published frames of /finance and /contracts, in German: the
// footer read `225.297,6 $` while the rows above it read `133.794,64 $`. One
// decimal against two, in the same column, on the two figures a reader is most
// likely to compare. On a euro project the same cell instead collapsed to
// `9,4 Mio. €`, and a four-figure total came out as `3088,4 $` - one decimal
// and no thousands separator - two rows under `3.013,85 $`.
//
// All three are one cause. The footers asked <MoneyDisplay> for `compact`, and
// that prop does two things at once: it turns on `notation: 'compact'` and it
// replaces the currency's own minor units with `[0, 1]` fraction digits. German
// has no short currency form below a million, so under a million the notation
// changes nothing and the digit override is all that survives - a full-length
// number written to one decimal, and, below ten thousand, without its grouping.
// Above a million the notation does fire and the figure collapses. Which of the
// three shapes a reader sees depends on the size of the total, so the same
// column disagrees with itself at different times of the project.
//
// The fix is not to make `compact` cleverer. It is that a column is compact all
// the way down or not at all, and a money column in a wide register is not.
//
// Two halves:
//
//   * the mechanism, rendered rather than argued: a compacted footer cannot
//     agree with the column above it, and this is stated as a property of the
//     rendered strings rather than as a quoted example, so it keeps meaning the
//     same thing when the amounts change;
//   * the census, because fixing the eleven footers that were wrong would leave
//     the twelfth free to be written the same way tomorrow.
//
// HOW TO WORK ON THE CENSUS, and this is not optional advice.
//
// A matcher that has never been shown to fail proves nothing when it passes. A
// green census means either "there is nothing to find" or "the reader went
// blind", and the two look identical from the outside. So the only way to
// learn anything about this file is to make the tree WRONG ON PURPOSE and
// watch: re-pin a formatter that was just fixed, run the census, and require
// it to name the file. If it stays green you have found a hole, not a clean
// tree.
//
// That method has caught this census twice, and neither time by reading it:
//
//   1. `statementAt` stopped at the first balanced bracket run, which for a
//      `function f(...)` is the PARAMETER LIST. Every function body came back
//      empty, so nothing could be convicted, and the census reported zero
//      offenders on a tree that held two. Closed by `declarationBody`, and
//      guarded by 'reads a function body past its parameter list'.
//
//   2. The body reader stopped one hop short of the engine. The BOQ resource
//      summary's footer names `fmtMoney`, a memo that delegates to
//      `createRSMoneyFormatter`, so the literal lived one call below. Reading
//      only the memo found no engine and CLEARED a surface that had been
//      deliberately re-pinned seconds earlier - the census went on calling it
//      "money and clean". Closed by expanding a body with the bodies of the
//      helpers it calls, and guarded by 'follows a helper that delegates to
//      another helper'.
//
// Both failures looked thorough. Both convicted nobody. Assume the next one
// does too, and go and break something to find it.
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { render, cleanup } from '@testing-library/react';

import { MoneyDisplay } from './MoneyDisplay';
import { MultiCurrencyTotal } from './MultiCurrencyTotal';
import { usePreferencesStore, type NumberLocale } from '@/stores/usePreferencesStore';

/**
 * The whole product tree, not just `features/`.
 *
 * A footer is a footer wherever it is written, and `modules/` carries one too.
 * The denominator each census prints is a count over this root, so widening
 * the root and widening what the numbers describe happen together.
 */
const SRC = join(__dirname, '..', '..');

/**
 * A budget column and its total, in the shape the register holds them: rows
 * that each carry their own currency, and a footer that sums them.
 */
const ROWS = [133_794.64, 91_502.96];
/** The same column an order of magnitude up, where compact notation fires. */
const LARGE_ROWS = [4_700_000, 4_700_000];

/**
 * Three of the locales the number-format preference actually offers, chosen
 * because they disagree about all three things that could hide the defect:
 * the decimal mark, the group separator, and which side the currency symbol
 * sits on. A locale outside that union is not a reader this product has.
 */
const READERS: NumberLocale[] = ['de-DE', 'en-US', 'fr-FR'];

interface Shape {
  /** How many digits follow the decimal separator of this locale. */
  fraction: number;
  /** The words in the string: a magnitude term like "Mio" shows up here. */
  words: string;
}

/**
 * The two things that differed on the frame, read off a rendered string.
 *
 * Deliberately not a comparison of the strings themselves - a total and a row
 * are different amounts and will never be equal. What has to be equal is how
 * they are written.
 */
function shapeOf(text: string, locale: string): Shape {
  const decimal =
    new Intl.NumberFormat(locale).formatToParts(1.5).find((p) => p.type === 'decimal')?.value ?? '.';
  const at = text.lastIndexOf(decimal);
  const fraction = at < 0 ? 0 : (text.slice(at + 1).match(/^\d+/)?.[0].length ?? 0);
  return { fraction, words: (text.match(/\p{L}+/gu) ?? []).join(' ') };
}

function speakNumbers(locale: NumberLocale) {
  usePreferencesStore.setState({ numberLocale: locale });
}

beforeEach(() => {
  localStorage.clear();
  usePreferencesStore.getState().resetPreferences();
});

afterEach(() => {
  cleanup();
});

describe('the footer of a money column', () => {
  it.each(READERS)('is written like the cells above it in %s', (locale) => {
    speakNumbers(locale);
    for (const amounts of [ROWS, LARGE_ROWS]) {
      const cell = render(<MoneyDisplay amount={amounts[0]!} currency="EUR" />).container.textContent!;
      cleanup();
      const total = render(
        <MultiCurrencyTotal
          items={amounts.map((amount) => ({ amount, currency: 'EUR' }))}
          variant="inline"
        />,
      ).container.textContent!;
      cleanup();

      expect(shapeOf(total, locale), `total "${total}" against cell "${cell}"`).toEqual(
        shapeOf(cell, locale),
      );
    }
  });

  // Guards the guard, and states the defect. If `compact` were a neutral
  // space-saving choice the assertion above would pass either way, and this
  // file would be proving nothing. It is not neutral: it changes the reading
  // under a million and the notation over one, in the same column.
  it('could not be written like them while it was compacted', () => {
    speakNumbers('de-DE');

    const cell = render(<MoneyDisplay amount={ROWS[0]!} currency="USD" />).container.textContent!;
    cleanup();
    const compactedSmall = render(
      <MoneyDisplay amount={ROWS[0]! + ROWS[1]!} currency="USD" compact />,
    ).container.textContent!;
    cleanup();
    const compactedLarge = render(
      <MoneyDisplay amount={LARGE_ROWS[0]! + LARGE_ROWS[1]!} currency="USD" compact />,
    ).container.textContent!;
    cleanup();

    // Under a million: the same length as the rows, to a different precision.
    expect(shapeOf(compactedSmall, 'de-DE').fraction).not.toBe(shapeOf(cell, 'de-DE').fraction);
    expect(shapeOf(compactedSmall, 'de-DE').words).toBe(shapeOf(cell, 'de-DE').words);
    // Over a million: a magnitude word the column never uses.
    expect(shapeOf(compactedLarge, 'de-DE').words).not.toBe(shapeOf(cell, 'de-DE').words);
  });

  it('loses the thousands separator on a four-figure total', () => {
    // The third shape from the frame, and the one that looks like a grouping
    // bug rather than a precision one. `3088,4 $` two rows under `3.013,85 $`
    // is the same `compact` prop, not a locale's grouping rule.
    speakNumbers('de-DE');
    const grouped = render(<MoneyDisplay amount={3088.4} currency="USD" />).container.textContent!;
    cleanup();
    const compacted = render(
      <MoneyDisplay amount={3088.4} currency="USD" compact />,
    ).container.textContent!;
    cleanup();

    const group = new Intl.NumberFormat('de-DE').formatToParts(1234).find((p) => p.type === 'group')!.value;
    expect(grouped).toContain(group);
    expect(compacted).not.toContain(group);
  });
});

/* ── The census ───────────────────────────────────────────────────────────── */

function tsxFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) tsxFiles(full, found);
    else if (entry.endsWith('.tsx') && !entry.endsWith('.test.tsx')) found.push(full);
  }
  return found;
}

/**
 * The walk and the file contents, taken once for the whole file.
 *
 * Two censuses live here and each of them wants the same thousand files. Read
 * per test, that is several thousand syscalls, which is invisible in isolation
 * and is not invisible under a saturated suite - the sibling gate in
 * `shared/lib` lost four of its tree-walkers to the default fifteen-second
 * budget that way, and a census that times out reports nothing. Holds for the
 * life of one `vitest run`; not watch-safe, since the module outlives edits to
 * the files it has already read.
 */
const PRODUCT_TSX = tsxFiles(SRC);
const sourceCache = new Map<string, string>();
function sourceOf(file: string): string {
  const cached = sourceCache.get(file);
  if (cached !== undefined) return cached;
  const text = readFileSync(file, 'utf8');
  sourceCache.set(file, text);
  return text;
}

/** Every `<tfoot>…</tfoot>` region in a file, with the line it starts on. */
function footers(source: string): { text: string; line: number }[] {
  return [...source.matchAll(/<tfoot[\s\S]*?<\/tfoot>/g)].map((m) => ({
    text: m[0],
    line: source.slice(0, m.index).split('\n').length,
  }));
}

describe('no table footer in the product', () => {
  it('asks for a compacted figure under a column that is not compacted', () => {
    const offenders: string[] = [];
    for (const file of PRODUCT_TSX) {
      for (const foot of footers(sourceOf(file))) {
        if (/\bcompact\b/.test(foot.text)) {
          offenders.push(`${relative(SRC, file).replace(/\\/g, '/')}:${foot.line}`);
        }
      }
    }
    expect(offenders, `out of ${PRODUCT_TSX.length} files`).toEqual([]);
  }, 60_000);

  // The census walks a real tree and its reader really finds footers. Without
  // this, a wrong path or a regex that never matches is indistinguishable from
  // a clean codebase.
  it('really read the source tree, and really recognises a footer', () => {
    expect(PRODUCT_TSX.length).toBeGreaterThan(900);
    const withFooter = PRODUCT_TSX.filter((f) => footers(sourceOf(f)).length > 0);
    expect(withFooter.length).toBeGreaterThan(5);
    expect(footers('<table><tfoot><td compact /></tfoot></table>')).toHaveLength(1);
  }, 60_000);
});

/* ── The second cause: a footer that owns its formatter ─────────────────────── */

/**
 * The census above finds one way a total stops agreeing with its column, and it
 * was green on a tree where a total was wrong.
 *
 * `compact` is a prop, and the leveling matrix never used it. Its footer built a
 * private `Intl.NumberFormat` pinned to zero decimals at both ends while the
 * cells above it were written to two, so a euro package printed `2.235 €`
 * directly under `1.234,50` - the sum rounded away from the very figures it
 * summed, in the same column. A matcher looking for the word `compact` cannot
 * see that, and this tree carries footers in twenty-six files.
 *
 * So this second census asks a different question, and asks it of the footer
 * alone rather than of the footer against its rows: does money reach this cell
 * through a formatter the file BUILT ITSELF with a hardcoded number of decimal
 * places? How many minor units a currency has is a property of the currency -
 * CLDR keeps it in `currencyData`, and `formatCurrency` and
 * `currencyFractionDigits` read it from there - so a digit literal written next
 * to money is a claim about every currency the screen will ever be handed, and
 * it is wrong for the yen, the forint and the dinar at the same time. Two rows
 * agreeing with each other is not the standard. Agreeing with the currency is.
 *
 * Handing `{ maximumFractionDigits: 0 }` to the SHARED formatter is not this
 * defect and is deliberately not flagged. That surface asked the resolver and
 * then asked it to round a summary, which is a display decision the resolver
 * validates and which leaves the symbol, the grouping and the locale correct.
 * The order-of-magnitude estimate does precisely that, in its rows and in its
 * total alike, and calling it a defect would be reading the literal instead of
 * the question the literal answers.
 *
 * The blind spot is named rather than implied. A money column that mentions no
 * currency anywhere near itself is indistinguishable in source from a column of
 * plain numbers, so this census cannot classify it as money and does not
 * pretend to. Those footers land in the `plain` bucket, which is printed, and
 * the count of money footers is asserted from below so the day the classifier
 * stops recognising money is a red day rather than a quiet one.
 */

/** A literal fraction-digit count, the thing a currency is supposed to decide. */
const DIGIT_PIN = /(?:min|max)imumFractionDigits:\s*(\d+)\b/;
const TO_FIXED = /\.toFixed\(\s*(\d+)\s*\)/;
const OWN_ENGINE = /new Intl\.NumberFormat/;
/** Any route that ends in the shared money module, component or function. */
const SHARED_MONEY =
  /<(MoneyDisplay|MultiCurrencyTotal)\b|\b(formatCurrency|formatCompactCurrency|currencyFractionDigits|fmtWithCurrency|fmtFixed)\s*\(/;
/**
 * Substring, not a word boundary. `totalsByCurrency[code]` names a currency and
 * `\bCurrency\b` does not see it, which is how a real money footer read as a
 * column of plain numbers while this was being written.
 */
const CURRENCY = /currenc/i;

interface Formatter {
  /** Builds its own `Intl.NumberFormat`, or reaches for `toFixed`. */
  ownEngine: boolean;
  /** The literal digit count it pins, when it pins one. */
  pin?: string;
  /** Names a currency anywhere in its body. */
  money: boolean;
  /** Formats numbers at all, by any route. */
  formats: boolean;
  /** The reader could not recover a body. Not innocence - failure. */
  unread: boolean;
}

/** Index of the bracket closing the run that opens at or after `from`. */
function skipBalanced(src: string, from: number, open: string, close: string): number {
  let depth = 0;
  for (let i = from; i < src.length; i++) {
    const c = src[i];
    if (c === '/' && src[i + 1] === '/') {
      const nl = src.indexOf('\n', i);
      if (nl < 0) return -1;
      i = nl;
    } else if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      if (end < 0) return -1;
      i = end + 1;
    } else if (c === "'" || c === '"' || c === '`') {
      const quote = c;
      i++;
      while (i < src.length && src[i] !== quote) i += src[i] === '\\' ? 2 : 1;
    } else if (c === open) {
      depth++;
    } else if (c === close) {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/**
 * The source text of one declaration.
 *
 * Two shapes, because a single scan cannot read both. A `function f(...)` keeps
 * its body AFTER the parameter list, so a scanner that stops at the first
 * balanced bracket run returns the parameters and never sees the body - which
 * is not a hypothetical: an earlier draft of this census did exactly that and
 * reported zero offenders on a tree that had two. An arrow may have no braces
 * at all, so its statement ends at the first top-level `;` instead.
 *
 * A fixed-size window is deliberately not used. The helper that started all
 * this is a hundred and forty characters of `try`/`catch` and would fall off
 * the end of any window chosen to look reasonable.
 */
function declarationBody(src: string, start: number, isFunction: boolean): string {
  if (isFunction) {
    const params = skipBalanced(src, src.indexOf('(', start), '(', ')');
    if (params < 0) return '';
    const open = src.indexOf('{', params);
    if (open < 0) return '';
    const close = skipBalanced(src, open, '{', '}');
    return close < 0 ? '' : src.slice(start, close + 1);
  }
  let depth = 0;
  for (let i = src.indexOf('=', start) + 1; i < src.length; i++) {
    const c = src[i];
    if (c === '/' && src[i + 1] === '/') {
      const nl = src.indexOf('\n', i);
      if (nl < 0) return src.slice(start);
      i = nl;
    } else if (c === "'" || c === '"' || c === '`') {
      const quote = c;
      i++;
      while (i < src.length && src[i] !== quote) i += src[i] === '\\' ? 2 : 1;
    } else if (c === '(' || c === '[' || c === '{') {
      depth++;
    } else if (c === ')' || c === ']' || c === '}') {
      depth--;
      if (depth < 0) return src.slice(start, i);
    } else if (c === ';' && depth === 0) {
      return src.slice(start, i);
    }
  }
  return src.slice(start);
}

/**
 * Every formatter a file declares, judged by its body and never by its name.
 *
 * A name matcher is blind to the helper called `money`, which is a real one on
 * this tree, and a helper called `formatSomething` may format nothing at all.
 * What makes a declaration a formatter is that it builds an engine, calls
 * `toFixed`, or delegates to the shared money module.
 */
function localFormatters(source: string): Map<string, Formatter> {
  const bodies = new Map<string, string>();
  const declaration = /(?:export\s+)?(?:function\s+(\w+)\s*\(|const\s+(\w+)\s*=\s*(?=[^=;\n]))/g;
  for (const m of source.matchAll(declaration)) {
    const name = m[1] ?? m[2]!;
    bodies.set(name, declarationBody(source, m.index, m[1] !== undefined));
  }

  /**
   * A body plus the bodies of the local helpers it calls, to a fixed depth.
   *
   * A single-level reader is not enough, and this is not hypothetical: the BOQ
   * resource summary holds `const fmtMoney = useMemo(() => createRSMoneyFormatter(...))`,
   * so the engine and its digit count live one hop away in
   * `createRSMoneyFormatter`. Reading only the memo body sees no engine at all
   * and clears the surface - the census called it "money and clean" while a
   * deliberately re-pinned count sat one call below, which is how this was
   * found. Following the hop is the difference between judging the formatter
   * and judging the name in front of it.
   *
   * Depth is capped and visits are recorded, so a helper pair that calls each
   * other cannot spin here.
   */
  const expand = (name: string, depth: number, seen: Set<string>): string => {
    const body = bodies.get(name) ?? '';
    if (depth === 0 || body.length === 0) return body;
    seen.add(name);
    let text = body;
    for (const called of callsIn(body)) {
      if (seen.has(called) || !bodies.has(called)) continue;
      text += `\n${expand(called, depth - 1, seen)}`;
    }
    return text;
  };

  const out = new Map<string, Formatter>();
  for (const [name, body] of bodies) {
    const full = expand(name, 3, new Set());
    const ownEngine = OWN_ENGINE.test(full) || TO_FIXED.test(full);
    out.set(name, {
      ownEngine,
      pin: full.match(DIGIT_PIN)?.[1] ?? full.match(TO_FIXED)?.[1],
      money: CURRENCY.test(full),
      formats: ownEngine || SHARED_MONEY.test(full),
      // Emptiness is judged on the declaration itself. A helper that simply
      // calls nothing is not unread; one whose own body would not parse is.
      unread: body.length === 0,
    });
  }
  return out;
}

/**
 * The `<td>` cells of a footer.
 *
 * The unit of judgement is the cell, not the footer, because a totals row is
 * routinely money in one column and a quantity in the next. Judging the footer
 * whole convicts the quantity formatter of a currency it never touches.
 */
function cellsOf(footer: string): string[] {
  const found = [...footer.matchAll(/<td\b[\s\S]*?<\/td>/g)].map((m) => m[0]);
  return found.length ? found : [footer];
}

/** Identifiers called in a region: the `x` of `x(`, never the `y` of `x.y(`. */
function callsIn(region: string): string[] {
  const seen = [...region.matchAll(/(^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(/g)].map((m) => m[2]!);
  return [...new Set(seen)].filter(
    (n) => !/^(if|for|while|switch|catch|return|typeof|new|map|filter|reduce)$/.test(n),
  );
}

/** Formatter instances: the `x` of `x.format(`, which no call matcher sees. */
function receiversIn(region: string): string[] {
  return [...new Set([...region.matchAll(/\b([A-Za-z_$][\w$]*)\.format\s*\(/g)].map((m) => m[1]!))];
}

interface Verdict {
  /** Why this footer offends, in words, one entry per cause. */
  reasons: string[];
  /** Formatters the reader could not resolve. Neither guilty nor cleared. */
  unknown: string[];
  money: boolean;
  formats: boolean;
}

/** Read one footer against the file that declares its helpers. */
function auditFooter(source: string, footer: string): Verdict {
  const local = localFormatters(source);
  const imported = new Set(
    [...source.matchAll(/import\s*\{([^}]+)\}\s*from/g)].flatMap((m) =>
      m[1]!.split(',').map((s) => s.trim().split(/\s+as\s+/).pop()!.trim()),
    ),
  );
  const reasons: string[] = [];
  const unknown: string[] = [];
  let money = false;
  let formats = false;

  for (const cell of cellsOf(footer)) {
    const named = [...callsIn(cell), ...receiversIn(cell)];
    const helpers = named.map((n) => [n, local.get(n)] as const);
    // The currency may be named by the helper, by the arguments, or by the
    // markup that prints the ISO code in its own span beside the number.
    const isMoney =
      CURRENCY.test(cell) ||
      /<(MoneyDisplay|MultiCurrencyTotal)\b/.test(cell) ||
      helpers.some(([, h]) => h?.money);
    if (isMoney) money = true;
    if (SHARED_MONEY.test(cell) || OWN_ENGINE.test(cell)) formats = true;

    if (isMoney && OWN_ENGINE.test(cell)) {
      const pin = cell.match(DIGIT_PIN)?.[1];
      if (pin !== undefined) reasons.push(`an inline Intl.NumberFormat pinned to ${pin}`);
    }
    for (const [name, helper] of helpers) {
      if (helper) {
        if (helper.formats) formats = true;
        if (helper.unread) unknown.push(`${name}() has a body this reader could not recover`);
        if (isMoney && helper.ownEngine && helper.pin !== undefined) {
          reasons.push(`${name}() builds its own formatter pinned to ${helper.pin}`);
        }
      } else if (/^(fmt|format)/i.test(name) || /Format|Money|Currency/.test(name)) {
        formats = true;
        if (/Money|Currency/i.test(name)) money = true;
        if (!imported.has(name)) unknown.push(`${name}() resolves to nothing in this file`);
      }
    }
  }
  return { reasons: [...new Set(reasons)], unknown: [...new Set(unknown)], money, formats };
}

interface Census {
  offenders: string[];
  unresolved: string[];
  /** Footers that carry money and ask the currency for its digits. */
  clean: string[];
  /** Footers this census cannot read as money. Printed, never hidden. */
  plain: string[];
  files: number;
  footerFiles: number;
  regions: number;
}

/**
 * Walked once for the whole file. Eight censuses over two thousand files is
 * seventeen thousand reads, and under a saturated suite that is the difference
 * between a gate and a timeout.
 */
function census(root: string): Census {
  const out: Census = {
    offenders: [],
    unresolved: [],
    clean: [],
    plain: [],
    files: 0,
    footerFiles: 0,
    regions: 0,
  };
  const files = root === SRC ? PRODUCT_TSX : tsxFiles(root);
  out.files = files.length;
  for (const file of files) {
    const source = sourceOf(file);
    const found = footers(source);
    if (!found.length) continue;
    out.footerFiles++;
    const rel = relative(root, file).replace(/\\/g, '/');
    for (const foot of found) {
      out.regions++;
      const at = `${rel}:${foot.line}`;
      const verdict = auditFooter(source, foot.text);
      // Every footer lands in exactly one named bucket. Nothing is skipped:
      // the earlier draft of this census skipped a footer whose row and total
      // formatters both read as "none", which is how the wrong one hid.
      if (verdict.unknown.length) out.unresolved.push(`${at}  ${verdict.unknown.join('; ')}`);
      else if (verdict.reasons.length) out.offenders.push(`${at}  ${verdict.reasons.join('; ')}`);
      else if (verdict.money) out.clean.push(at);
      else out.plain.push(`${at}  ${verdict.formats ? 'formats, no currency named' : 'no formatter'}`);
    }
  }
  return out;
}

const TREE = census(SRC);

/** The denominator, carried into every failure so a number is never bare. */
const SUMMARY = [
  `${TREE.files} .tsx files, ${TREE.footerFiles} of them carrying a <tfoot>,`,
  `${TREE.regions} footer regions:`,
  `${TREE.offenders.length} offending, ${TREE.clean.length} money and clean,`,
  `${TREE.plain.length} with no currency this census can see, ${TREE.unresolved.length} unresolved.`,
  `\nno currency visible:\n  ${TREE.plain.join('\n  ')}`,
].join(' ');

// The denominator, available without having to make the gate red first. An
// upper bound at zero is only good news while the matcher can still see, so
// the count is worth reading on a green run too.
//
// Caveat worth knowing before you go looking for this: vitest's DEFAULT
// reporter withholds stdout from a file whose tests all passed, so on a green
// run this line appears only under `--reporter=verbose`. It always appears
// when something here fails, because every assertion below carries `SUMMARY`
// in its own message rather than relying on this.
console.log(`[footer census] ${SUMMARY}`);

/**
 * A footer written the way the leveling matrix was written before this was
 * fixed - a verbatim reduction of it, kept as the control that matters most,
 * because a synthetic offender only proves the matcher can catch something
 * somebody wrote to be caught.
 */
const THE_FOOTER_THIS_GATE_WAS_WRITTEN_FOR = `
function formatNumber(n: number, decimals = 2): string {
  return new Intl.NumberFormat(getNumberLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}
function formatCurrency(amount: number, currency?: string): string {
  const code = (currency || '').trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(code)) {
    return new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  }
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      style: 'currency',
      currency: code,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return \`\${amount.toFixed(0)} \${code}\`;
  }
}
export function LevelingMatrix() {
  return (
    <table>
      <tbody>
        <tr><td>{formatNumber(row.reference_total)}</td></tr>
      </tbody>
      <tfoot>
        <tr><td>{formatCurrency(Number(bs.leveled_amount), bs.currency || matrixCurrency)}</td></tr>
      </tfoot>
    </table>
  );
}
`;

/** The same footer after the fix: it asks, and the answer is the currency's. */
const THE_SAME_FOOTER_ASKING_THE_CURRENCY = `
import { currencyFractionDigits, formatCurrency as formatMoney } from '@/shared/lib/money';
function formatCurrency(amount: number, currency?: string): string {
  return formatMoney(amount, currency);
}
export function LevelingMatrix() {
  return (
    <table>
      <tfoot>
        <tr><td>{formatCurrency(Number(bs.leveled_amount), bs.currency || matrixCurrency)}</td></tr>
      </tfoot>
    </table>
  );
}
`;

/**
 * Surfaces this census names and does not fix, keyed by file rather than by
 * line so that somebody else editing above one of them does not turn this gate
 * red for a reason that has nothing to do with money.
 *
 * It is empty, and the intent is that it stays that way. The catalogue was the
 * one entry here: `fmt` was a private two-decimal formatter shared by thirteen
 * call sites across four components and took no currency at all. It looked
 * like a baseline candidate until the call sites were actually resolved one by
 * one, at which point every single one turned out to have the currency already
 * in scope - as a prop, on the resource, or printed as a sibling node right
 * beside the number. It was fixed instead of excused.
 *
 * That is the lesson worth leaving behind: "this needs a bigger change" is a
 * claim about call sites, and it is cheap to check. Resolve them before you
 * write an entry here.
 */
const KNOWN_AND_UNFIXED: Record<string, string> = {};

/**
 * The `plain` bucket, read by a human, with the verdict written down.
 *
 * This exists because "no currency this census can see" is a statement about
 * the census, not about the file, and a reader scanning eleven such entries has
 * no way to tell a genuine quantity footer from a money footer whose currency
 * is simply resolved somewhere the matcher does not look. Left unannotated, the
 * honest limitation does the work of a hiding place - which is the exact
 * failure this whole file was written to prevent, one bucket over.
 *
 * Only the entries that format something are listed. The rest print raw counts
 * and have no formatter at all, so there is nothing in them to get wrong.
 *
 * This list has already earned itself once. `features/boq/ResourceSummary.tsx`
 * sat in `plain` reading as innocent: its formatter's body said nothing about
 * currency and its footer cell said only `total_cost`, so the matcher filed it
 * as a column of plain numbers while it was summing money at a pinned two
 * decimals. A hand pass found it, not the instrument. It has since been fixed
 * and now classifies as money and clean, which is why it is no longer listed.
 *
 * Keep the shape in mind when you add an entry: the bucket is still
 * STRUCTURALLY able to hide that exact defect again, because a helper can
 * always be written whose body names no currency. What bounds the exposure is
 * not the matcher but the test below, which refuses to let a NEW formatting
 * footer land here without a human writing down what they found.
 */
const HAND_INSPECTED: Record<string, string> = {
  'features/assemblies/AssemblyEditorPage.tsx':
    'CORRECT. Its fmt is built from currencyFractionDigits(assembly?.currency); the ' +
    'census cannot see it because the currency is resolved outside the footer cell.',
  'features/takeoff/components/MeasurementLedger.tsx':
    'CORRECT. Quantities and item counts only; the file names no currency anywhere.',
  'features/survey/StagedPanel.tsx':
    'CORRECT. Cut and fill volumes in cubic metres per stage; the footer sums earthwork volumes, not money.',
  'features/rebar-schedule/RebarSchedulePage.tsx':
    'CORRECT. Bar counts and total weight in kg; the footer sums physical quantities, not money.',
  'features/delivery_model/ComparisonPanel.tsx':
    'CORRECT. The sum of the criteria weights (must reach 100) and a weighted score from 1 to 5 ' +
    'per compared form; the comparison holds no amount and the file names no currency anywhere.',
  'features/equipment/components/TelematicsTab.tsx':
    'CORRECT. Hours, percentages, litres and kg CO2 are quantities; the one money column (hire_cost) ' +
    'is a bare decimal because the telematics payload carries no currency to name, and it goes through ' +
    'fmtNumber like the rows above it.',
};

describe('no money footer in the product', () => {
  it('pins a digit count of its own instead of asking the currency', () => {
    const fresh = TREE.offenders.filter(
      (entry) => !Object.keys(KNOWN_AND_UNFIXED).some((file) => entry.startsWith(`${file}:`)),
    );
    expect(fresh, `offenders, out of ${SUMMARY}`).toEqual([]);
  }, 60_000);

  it('has not quietly outgrown the exceptions on the books', () => {
    // A ratchet, not an amnesty. Every entry has to keep being true, so the day
    // a baselined file is fixed this goes red and the entry comes out. Without
    // it the list would be a place for a defect to retire to.
    //
    // This is not theoretical: the list held the catalogue, the catalogue was
    // fixed, and this test is what failed to say so. It survives an empty list
    // on purpose, because the next entry is the one it has to catch.
    const stillThere = Object.keys(KNOWN_AND_UNFIXED).filter((file) =>
      TREE.offenders.some((entry) => entry.startsWith(`${file}:`)),
    );
    expect(stillThere, `the exception list has gone stale, out of ${SUMMARY}`).toEqual(
      Object.keys(KNOWN_AND_UNFIXED),
    );
  }, 60_000);

  it('has a written verdict for every footer it could not read as money', () => {
    // The direction that matters: a new footer that formats something without a
    // currency the census can see must not be able to slip into `plain` and
    // read as innocent. It lands here as a red test until somebody looks at it
    // and writes down what they found. That is the only defence against a
    // blind spot, because by definition the matcher cannot defend against it.
    const needVerdict = TREE.plain
      .filter((entry) => entry.endsWith('formats, no currency named'))
      .map((entry) => entry.split(':')[0]!);
    expect(
      needVerdict.filter((file) => !(file in HAND_INSPECTED)),
      `formatting footers with no recorded verdict, out of ${SUMMARY}`,
    ).toEqual([]);

    // And the reverse, so a note cannot outlive the thing it describes.
    //
    // The message has to say what to do, because the most likely way to get
    // here is by doing the right thing: fix `ResourceSummary`, its footer stops
    // being unreadable, and this goes red at the moment of the repair. A
    // ratchet that punishes the fix it asks for is worse than no ratchet, so
    // the remedy is spelled out rather than left to be worked out.
    expect(
      Object.keys(HAND_INSPECTED).filter((file) => !needVerdict.includes(file)),
      'a verdict below no longer matches any footer this census cannot read. ' +
        'If you just fixed one, delete its entry from HAND_INSPECTED - that is the ' +
        `whole remedy. Census: ${SUMMARY}`,
    ).toEqual([]);
  }, 60_000);

  it('leaves this census nothing it could not resolve', () => {
    // An unreadable formatter is not a clean one. If this list is ever
    // non-empty the census is guessing, and the count above is worth nothing.
    expect(TREE.unresolved, `unresolved, out of ${SUMMARY}`).toEqual([]);
  }, 60_000);
});

describe('the footer census', () => {
  it('walked a real tree and found real footers to judge', () => {
    // Floors, not equalities: a new footer must not be able to make this pass
    // by shrinking what the matcher recognises. Every one of these can only go
    // up as the product grows, and a drop means the reader broke.
    expect(TREE.files, `files walked, out of ${SUMMARY}`).toBeGreaterThan(900);
    expect(TREE.footerFiles, `files with a footer, out of ${SUMMARY}`).toBeGreaterThan(20);
    expect(TREE.regions, `footer regions, out of ${SUMMARY}`).toBeGreaterThan(30);
    // The one that catches a classifier going blind. Offenders reaching zero
    // is only good news while money is still being recognised as money.
    expect(TREE.clean.length, `money footers recognised, out of ${SUMMARY}`).toBeGreaterThan(15);
  }, 60_000);

  it('catches the footer it was written for, and clears the fix', () => {
    const before = auditFooter(
      THE_FOOTER_THIS_GATE_WAS_WRITTEN_FOR,
      footers(THE_FOOTER_THIS_GATE_WAS_WRITTEN_FOR)[0]!.text,
    );
    expect(before.reasons.join(' ')).toContain('builds its own formatter pinned to 0');
    expect(before.unknown).toEqual([]);

    const after = auditFooter(
      THE_SAME_FOOTER_ASKING_THE_CURRENCY,
      footers(THE_SAME_FOOTER_ASKING_THE_CURRENCY)[0]!.text,
    );
    expect(after.reasons, 'the delegating footer was convicted').toEqual([]);
    expect(after.money, 'the delegating footer stopped reading as money').toBe(true);
  });

  it('spares a quantity column and a rounded summary asked of the resolver', () => {
    // A quantity is not money and its two decimals are a measurement, not a
    // currency's minor units - even when the money column beside it is wrong.
    const quantity = `
      function formatQty(n: number, unit?: string) {
        return new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 2 }).format(n) + unit;
      }
      <table><tfoot><tr><td>{formatQty(o.total_area, 'm2')}</td></tr></tfoot></table>
    `;
    expect(auditFooter(quantity, footers(quantity)[0]!.text).reasons).toEqual([]);

    // The order-of-magnitude estimate: the digits are pinned, but they are
    // pinned by asking the shared resolver to round, which keeps the symbol,
    // the grouping and the locale the currency's.
    const rounded = `
      import { formatCurrency } from '@/shared/lib/money';
      <table><tfoot><tr><td>
        {formatCurrency(result.total, currency, undefined, { maximumFractionDigits: 0 })}
      </td></tr></tfoot></table>
    `;
    const verdict = auditFooter(rounded, footers(rounded)[0]!.text);
    expect(verdict.reasons, 'a rounded summary through the resolver was convicted').toEqual([]);
    expect(verdict.money).toBe(true);
  });

  it('follows a helper that delegates to another helper', () => {
    // The blind spot that cleared a re-pinned formatter. The footer names
    // `fmtMoney`, whose own body holds no engine at all - it hands off to
    // `createRSMoneyFormatter`, and the pinned count lives there. A reader
    // that stops at the first body sees a memo, finds nothing to convict, and
    // reports the surface as money and clean.
    //
    // This is the shape of the BOQ resource summary, reduced. It was found by
    // re-pinning that file on purpose and watching the census stay green, not
    // by reading the census, which is why the control is kept verbatim rather
    // than described.
    const indirect = `
      function createRSMoneyFormatter(locale: string, currency?: string) {
        return new Intl.NumberFormat(locale, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });
      }
      const fmtMoney = useMemo(() => createRSMoneyFormatter(locale, currency), [locale, currency]);
      <table><tfoot><tr><td>{fmtMoney.format(rows.reduce((s, r) => s + r.total_cost, 0))}</td></tr></tfoot></table>
    `;
    expect(
      auditFooter(indirect, footers(indirect)[0]!.text).reasons,
      'a pin one call away from the footer went unseen',
    ).toEqual(['fmtMoney() builds its own formatter pinned to 2']);

    // The same shape, asking the currency. Following the hop must not turn
    // into convicting everything it reaches.
    const fixed = indirect
      .replace('minimumFractionDigits: 2', 'minimumFractionDigits: digits')
      .replace('maximumFractionDigits: 2', 'maximumFractionDigits: digits');
    expect(
      auditFooter(fixed, footers(fixed)[0]!.text).reasons,
      'following the hop convicted a formatter that asks the currency',
    ).toEqual([]);
  });

  it('reads a helper by its body, not by its name', () => {
    // Both halves of the same lesson. `money()` formats money and no name
    // matcher would look at it; `formatThing()` is named like a formatter and
    // pins nothing. The census has to be right about both.
    const byBody = `
      const money = (v: number) => new Intl.NumberFormat(loc, { maximumFractionDigits: 0 }).format(v);
      <table><tfoot><tr><td>{money(totals.paid)} {currency}</td></tr></tfoot></table>
    `;
    expect(auditFooter(byBody, footers(byBody)[0]!.text).reasons.join(' ')).toContain(
      'money() builds its own formatter pinned to 0',
    );

    const innocent = `
      import { formatCurrency } from '@/shared/lib/money';
      const formatThing = (v: number, currency: string) => formatCurrency(v, currency);
      <table><tfoot><tr><td>{formatThing(totals.paid, currency)}</td></tr></tfoot></table>
    `;
    expect(auditFooter(innocent, footers(innocent)[0]!.text).reasons).toEqual([]);
  });

  it('reads a function body past its parameter list', () => {
    // The bug that made an earlier draft of this census report zero offenders
    // on a tree with two: the reader stopped at the first balanced bracket run,
    // which for a `function` is the PARAMETERS, and every body came back empty.
    const source = `function f(a: number, b?: string): string { return HERE; }`;
    expect(declarationBody(source, 0, true)).toContain('HERE');
    // And the other shape, which has no braces to balance at all.
    const arrow = `const g = (n: number) => new Intl.NumberFormat(loc).format(n);`;
    expect(declarationBody(arrow, 0, false)).toContain('Intl.NumberFormat');
  });

  it('splits a footer into cells, so one column cannot convict another', () => {
    const mixed = `
      function formatQty(n: number) { return new Intl.NumberFormat(loc, { maximumFractionDigits: 2 }).format(n); }
      <table><tfoot><tr>
        <td>{formatQty(o.area)}</td>
        <td><MoneyDisplay amount={o.total} currency={o.currency} /></td>
      </tr></tfoot></table>
    `;
    expect(cellsOf(footers(mixed)[0]!.text)).toHaveLength(2);
    expect(auditFooter(mixed, footers(mixed)[0]!.text).reasons).toEqual([]);
  });
});
