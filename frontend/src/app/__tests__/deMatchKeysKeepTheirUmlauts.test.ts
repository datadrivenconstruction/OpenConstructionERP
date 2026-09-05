// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The German match strings lost their diacritics in one bad batch.
//
// Nineteen values under `match.*` shipped as `Ubereinstimmung`,
// `Uberprufung`, `Ubersetzt` and friends, while the correct spelling appeared
// hundreds of times elsewhere in the same file. That rules out an encoding
// fault and leaves a batch that was written without them, which no gate we own
// can see: the value is present, non-empty, German-shaped and not an English
// leak, so every coverage check calls it translated.
//
// The two things this test has to get right, because both are ways of being
// wrong that look like being right:
//
//  1. A half fix. `Uberprufung` is missing two diacritics and
//     `Ubereinstimmungsvorschlage` is missing an Ü and an ä. Restoring only the
//     capital leaves `Überprufung`, which a "does Ü appear" check calls fixed.
//     The half-fixed forms are therefore asserted absent by name.
//  2. A fix by pattern. `Umfang` and `Unterzeilen` genuinely start with a bare
//     capital U and sit under the same prefix. Any rule broad enough to catch
//     all nineteen breaks these two, so they are asserted present as controls.
//
// Run:  npx vitest run src/app/__tests__/deMatchKeysKeepTheirUmlauts.test.ts

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const DE = readFileSync(join(__dirname, '..', 'locales', 'de.ts'), 'utf8');

/** The correct spellings, written out. Working from a list is the point. */
const CORRECT = [
  'Übereinstimmung',
  'Übereinstimmungen',
  'Übereinstimmungseinstellungen',
  'Übereinstimmungsvorschläge',
  'Übereinstimmungsvorschlägen',
  'Überprüfung',
  'Übersetzt',
  'Übersetzungskaskade',
];

/** The stripped forms as they shipped. */
const BROKEN = [
  'Ubereinstimmung',
  'Ubereinstimmungen',
  'Ubereinstimmungseinstellungen',
  'Ubereinstimmungsvorschlage',
  'Ubereinstimmungsvorschlagen',
  'Uberprufung',
  'Ubersetzt',
  'Ubersetzungskaskade',
];

/** Restored at the front and still stripped inside. The trap. */
const HALF_FIXED = ['Überprufung', 'Übereinstimmungsvorschlage"', 'Übereinstimmungsvorschlagen'];

/** German words that really do begin with a bare capital U. */
const CONTROLS = ['Umfang', 'Unterzeilen'];

const count = (needle: string) => DE.split(needle).length - 1;

describe('de.ts match strings', () => {
  it.each(CORRECT)('spells %s with its diacritics', (word) => {
    expect(count(word)).toBeGreaterThan(0);
  });

  it.each(BROKEN)('no longer contains the stripped form %s', (word) => {
    expect(count(word)).toBe(0);
  });

  it.each(HALF_FIXED)('does not contain the half-repaired form %s', (word) => {
    expect(count(word)).toBe(0);
  });

  it.each(CONTROLS)('leaves %s alone, because a bare U is correct there', (word) => {
    // Fails if someone ever repairs this by pattern instead of by spelling.
    expect(count(word)).toBeGreaterThan(0);
  });

  it('has no stripped-diacritic form left anywhere under match.', () => {
    // The line-level sweep the word list above cannot do on its own: it would
    // miss a nineteenth spelling nobody thought to enumerate.
    const offenders = DE.split('\n')
      .map((line, i) => ({ line, n: i + 1 }))
      .filter(({ line }) => /^\s*"(cost_)?match\./.test(line))
      .filter(({ line }) => /\bU(bereinstimmung|berprufung|bersetz|berschreib|bertrag)/.test(line))
      .map(({ line, n }) => `de.ts:${n} ${line.trim().slice(0, 80)}`);
    expect(offenders).toEqual([]);
  });
});
