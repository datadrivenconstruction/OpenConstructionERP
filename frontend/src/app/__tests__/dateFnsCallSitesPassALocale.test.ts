// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every date-fns call that prints a word must name the reader's language.
//
// The render test beside `DateDisplay` proves one component asks for a locale.
// This one states the rule for the whole tree, because the defect it replaces
// was four independent call sites making the same omission, and a per-component
// test only ever covers the component someone thought to write it for.
//
// Deliberately a source scan. There is no runtime seam that sees a call which
// was never made, and the failure mode is an argument that is absent, not one
// that is wrong. Printing the population next to the verdict is the point: a
// pass here means nothing unless the denominator is visibly non-zero.
//
// Run:  npx vitest run src/app/__tests__/dateFnsCallSitesPassALocale.test.ts

import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const SRC = join(__dirname, '..', '..');

/**
 * date-fns helpers whose output is words in a language.
 *
 * `format` is handled separately below, because most of its call sites ask for
 * `yyyy-MM-dd` for a query parameter or a React key, where a locale would be a
 * bug rather than a fix.
 *
 * `formatDuration` is deliberately absent even though date-fns publishes one.
 * We have a helper of the same name in `@/shared/lib/duration` that takes `t`
 * as its first argument and is already localised, and the first draft of this
 * test reported its call site in `DwgTakeoffPage` as a defect. A scan that
 * matches a spelling instead of a binding accuses the wrong code, so the
 * import resolution below is the load-bearing part of this file: only the
 * names a file actually imports from date-fns are ever examined.
 */
const WORD_PRODUCING_CALLS = [
  'formatDistanceToNowStrict',
  'formatDistanceToNow',
  'formatDistanceStrict',
  'formatDistance',
  'formatRelative',
];

/**
 * `format` patterns that render a name rather than a number.
 *
 * `M`/`MM` are digits and `d`, `y`, `H`, `m`, `s` never produce words, so a
 * pattern built only from those is language-neutral and correctly omits the
 * locale. `MMM` and longer are month names, `E`/`c` are weekday names, `LLL`
 * is the standalone month, `a`/`b`/`B` the day period, `do` the ordinal.
 */
const WORD_PRODUCING_TOKENS = /MMM|LLL|E{1,6}|c{3,6}|\bdo\b|a{1,5}|b{1,5}|B{1,5}|G{1,5}|Q{3,5}|q{3,5}/;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(full) && !/\.test\.tsx?$/.test(full)) out.push(full);
  }
  return out;
}

/** Returns the source of one call, from its open paren to the matching close. */
function callText(source: string, openParenIndex: number): string {
  let depth = 0;
  for (let i = openParenIndex; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === '(') depth += 1;
    else if (ch === ')') {
      depth -= 1;
      if (depth === 0) return source.slice(openParenIndex, i + 1);
    }
  }
  return source.slice(openParenIndex);
}

/** Every call of `name(` in `source`, as balanced-paren substrings. */
function callsOf(source: string, name: string): string[] {
  const found: string[] = [];
  const re = new RegExp(`(?<![A-Za-z0-9_$.])${name}\\s*\\(`, 'g');
  let m: RegExpExecArray | null;
  while ((m = re.exec(source))) {
    found.push(callText(source, m.index + m[0].length - 1));
  }
  return found;
}

/**
 * date-fns export name → the local name it is bound to in this file.
 *
 * Reads the `import { … } from 'date-fns'` clause so `format as dfFormat` is
 * followed, and so a same-named helper from anywhere else is not.
 */
function dateFnsBindings(source: string): Map<string, string> {
  const bindings = new Map<string, string>();
  const clause = /import\s*\{([^}]*)\}\s*from\s*'date-fns'/gs;
  let m: RegExpExecArray | null;
  while ((m = clause.exec(source))) {
    for (const raw of (m[1] ?? '').split(',')) {
      const part = raw.replace(/\/\/.*$/gm, '').trim();
      if (!part || part.startsWith('type ')) continue;
      const [exported, local] = part.split(/\s+as\s+/).map((s) => s.trim());
      if (exported) bindings.set(exported, local || exported);
    }
  }
  return bindings;
}

const files = walk(SRC)
  .map((path) => ({ path, source: readFileSync(path, 'utf8') }))
  .map((f) => ({ ...f, bindings: dateFnsBindings(f.source) }))
  .filter((f) => f.bindings.size > 0);

describe('date-fns call sites', () => {
  it('scans a non-empty population of files that import date-fns', () => {
    // The denominator. A resolution change that stopped matching any file
    // would otherwise turn every assertion below into a silent pass.
    expect(files.length).toBeGreaterThanOrEqual(5);
  });

  it('passes a locale to every helper that renders words', () => {
    const offenders: string[] = [];
    let scanned = 0;
    for (const { path, source, bindings } of files) {
      for (const name of WORD_PRODUCING_CALLS) {
        const local = bindings.get(name);
        if (!local) continue;
        for (const call of callsOf(source, local)) {
          scanned += 1;
          if (!call.includes('locale:')) {
            offenders.push(`${relative(SRC, path).split(sep).join('/')}: ${name}`);
          }
        }
      }
    }
    expect(scanned, 'no word-producing date-fns calls were found at all').toBeGreaterThan(0);
    expect(offenders).toEqual([]);
  });

  it('passes a locale to every format() whose pattern renders a name', () => {
    const offenders: string[] = [];
    let scanned = 0;
    let patternsSeen = 0;
    for (const { path, source, bindings } of files) {
      const local = bindings.get('format');
      if (!local) continue;
      for (const call of callsOf(source, local)) {
        // Second argument is the pattern; only quoted literals are readable
        // here, and every one of ours is a literal.
        const pattern = /,\s*(['"])([^'"]*)\1/.exec(call)?.[2];
        if (pattern === undefined) continue;
        patternsSeen += 1;
        if (!WORD_PRODUCING_TOKENS.test(pattern)) continue;
        scanned += 1;
        if (!call.includes('locale:')) {
          offenders.push(`${relative(SRC, path).split(sep).join('/')}: format(…, '${pattern}')`);
        }
      }
    }
    // Two denominators. The first says the scan reached real `format` calls at
    // all; the second says the token list still recognises a name-rendering
    // one, which is what a pass here actually depends on.
    expect(patternsSeen, 'no date-fns format() patterns were read at all').toBeGreaterThan(5);
    expect(scanned, 'no name-rendering format() patterns were found at all').toBeGreaterThan(0);
    expect(offenders).toEqual([]);
  });
});
