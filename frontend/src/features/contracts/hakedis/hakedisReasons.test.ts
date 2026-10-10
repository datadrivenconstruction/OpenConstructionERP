// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every reason a certificate line can be held for has a sentence on screen.
//
// The reason vocabulary is closed and the server owns it: `REASON_KEYS` and
// `CONSUMER_REASON_KEYS` in `backend/app/core/payment_taxes/calc.py`. The
// screen words a held line from its key (`hakedis.reason.<key>`), so a key
// added on the server with no locale line would show the server's fallback
// sentence in the wrong language, and nothing would report it: the key is
// assembled at run time, where the orphan-key scan cannot see it.
//
// The vocabulary is read from the Python source at run time, not copied here,
// so a new key fails this test the day it is added. The sentences are also
// held to the printed ones (`HAKEDIS_LABELS` in `hakedis_layout.py`), so the
// screen and the printed certificate never give two wordings of one reason.

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

function locate(candidates: string[]): string {
  const found = candidates.map((path) => resolve(process.cwd(), path)).find(existsSync);
  if (!found) throw new Error(`cannot find any of: ${candidates.join(', ')}`);
  return found;
}

const CALC = locate(['../backend/app/core/payment_taxes/calc.py', 'backend/app/core/payment_taxes/calc.py']);
const LAYOUT = locate([
  '../backend/app/modules/contracts/hakedis_layout.py',
  'backend/app/modules/contracts/hakedis_layout.py',
]);
const LOCALES = locate(['src/app/locales', 'frontend/src/app/locales']);

/** The string members of one module-level tuple of the Python source. */
function tupleOf(source: string, name: string): string[] {
  const start = source.indexOf(`\n${name}: tuple[str, ...] = (`);
  if (start < 0) throw new Error(`${name} is not defined the way this test reads it`);
  const end = source.indexOf('\n)', start);
  const body = source.slice(start, end);
  const members: string[] = [];
  for (const line of body.split('\n').slice(2)) {
    const match = /^\s*"([a-z_]*)",/.exec(line);
    if (match && match[1] !== undefined) members.push(match[1]);
  }
  return members;
}

/** The server's reason keys, less the empty one that marks an ordinary value. */
function serverReasonKeys(): string[] {
  const source = readFileSync(CALC, 'utf8');
  const keys = [...tupleOf(source, 'REASON_KEYS'), ...tupleOf(source, 'CONSUMER_REASON_KEYS')];
  return keys.filter((key) => key !== '');
}

/** The printed sentences of one language: `reason.<key>` to its Python string. */
function printedSentences(language: 'tr' | 'en'): Map<string, string> {
  const source = readFileSync(LAYOUT, 'utf8');
  // The two tables are module-level dicts, `_TR` and `_EN`, closed by a brace in column one.
  const start = source.indexOf(`\n_${language.toUpperCase()}: dict[str, str] = {`);
  if (start < 0) throw new Error(`hakedis_layout.py has no ${language} label table this test can read`);
  const table = source.slice(start, source.indexOf('\n}', start));
  const sentences = new Map<string, string>();
  const pattern = /^\s*"reason\.([a-z_]+)":\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'),?\s*$/gm;
  for (const match of table.matchAll(pattern)) {
    const key = match[1];
    const text = match[2] ?? match[3];
    if (key !== undefined && text !== undefined) sentences.set(key, text.replace(/\\(["'])/g, '$1'));
  }
  return sentences;
}

/** The `hakedis.reason.*` lines of one locale file. */
function screenSentences(code: 'tr' | 'en'): Map<string, string> {
  const source = readFileSync(resolve(LOCALES, `${code}.ts`), 'utf8');
  const sentences = new Map<string, string>();
  const pattern = /^\s*"hakedis\.reason\.([a-z_]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$/gm;
  for (const match of source.matchAll(pattern)) {
    const key = match[1];
    const text = match[2];
    if (key !== undefined && text !== undefined) sentences.set(key, text.replace(/\\"/g, '"'));
  }
  return sentences;
}

/** A Python `{name}` placeholder as i18next writes it. */
function asScreenText(printed: string): string {
  return printed.replace(/\{([a-z_]+)\}/g, '{{$1}}');
}

describe('hakedis reason sentences', () => {
  const keys = serverReasonKeys();

  it('reads the whole server vocabulary', () => {
    // Guards the reader itself: an empty or short list would pass everything below.
    expect(keys.length).toBeGreaterThanOrEqual(41);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toContain('not_chosen');
    expect(keys).toContain('not_entered');
    expect(keys).toContain('stamp_duty_base_unknown');
    expect(keys).toContain('other');
  });

  it.each(['en', 'tr'] as const)('has a sentence for every reason key in %s', (code) => {
    const screen = screenSentences(code);
    const missing = keys.filter((key) => !(screen.get(key) ?? '').trim());
    expect(missing).toEqual([]);
  });

  it.each(['en', 'tr'] as const)('words every reason as the printed certificate does in %s', (code) => {
    const printed = printedSentences(code);
    const screen = screenSentences(code);
    // The printed table must really have been read, or the comparison is empty.
    expect(printed.size).toBeGreaterThanOrEqual(keys.length);
    const drifted = keys
      .filter((key) => printed.has(key))
      .filter((key) => screen.get(key) !== asScreenText(printed.get(key) ?? ''));
    expect(drifted).toEqual([]);
    expect(keys.filter((key) => !printed.has(key))).toEqual([]);
  });

  it('carries no sentence for a key the server does not know', () => {
    for (const code of ['en', 'tr'] as const) {
      const stray = [...screenSentences(code).keys()].filter((key) => !keys.includes(key));
      expect(stray).toEqual([]);
    }
  });
});
