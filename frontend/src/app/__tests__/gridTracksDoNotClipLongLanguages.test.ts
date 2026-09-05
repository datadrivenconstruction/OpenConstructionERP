// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Arbitrary grid templates must not let a long language push the page sideways.
//
// A bare `2fr` track is `minmax(auto, 2fr)`, and that `auto` minimum resolves
// to min-content. Where two such tracks share a row, the longer language walks
// one of them past its share, the ratio stops applying, and the row grows past
// the viewport. Measured on the project header at a 1440 viewport: German
// resolved `grid-cols-[3fr_2fr]` to "462.953px 955.328px" and
// documentElement.scrollWidth reached 1704 with maxScrollLeft 0, so the
// overflowing content was not merely off to the side, it was unreachable.
// `minmax(0, 2fr)` removes the floor and the row keeps its ratio.
//
// This is a source assertion rather than a computed-style one, and that is not
// a shortcut. jsdom has no layout engine: `getComputedStyle(el).gridTemplateColumns`
// returns whatever was set, never a resolved track list, and Tailwind classes
// are not compiled under vitest at all, so a test that read computed style here
// would pass without ever measuring anything. The honest instrument at this
// level is the class string itself.
//
// Run:  npx vitest run src/app/__tests__/gridTracksDoNotClipLongLanguages.test.ts

import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const SRC = join(__dirname, '..', '..');

/** An arbitrary Tailwind track list, e.g. `grid-cols-[minmax(0,3fr)_2fr]`. */
const TEMPLATE = /grid-(?:cols|rows)-\[[^\]]*\]/g;

/**
 * A whole track that is nothing but a fraction, e.g. `2fr` or `1.4fr`.
 *
 * Anchored at both ends against a single track rather than run as a regex over
 * the template, because the first draft did the latter and reported
 * `minmax(0,1.4fr)` as bare: `\d*\.?\d+fr` also matches the `.4fr` inside it,
 * and at that offset the `minmax(0,` lookbehind no longer applies. Splitting
 * into tracks first removes the class of bug rather than one instance.
 *
 * A track written `minmax(60px,0.6fr)` is correctly not bare. The defect is
 * the automatic `auto` minimum resolving to min-content; an explicit floor,
 * even a non-zero one, is a decision about width rather than an accident of
 * how long the reader's language is.
 */
const WHOLE_FR_TRACK = /^\d+(?:\.\d+)?fr$/;

/** Tailwind writes the spaces between tracks as underscores. */
function tracksOf(template: string): string[] {
  const inner = template.slice(template.indexOf('[') + 1, -1);
  return inner.split('_');
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx$/.test(full)) out.push(full);
  }
  return out;
}

interface Hit {
  where: string;
  template: string;
  bare: number;
}

function collect(): { all: Hit[]; multiFr: Hit[] } {
  const all: Hit[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, 'utf8');
    const lines = source.split('\n');
    lines.forEach((line, i) => {
      for (const template of line.match(TEMPLATE) ?? []) {
        const bare = tracksOf(template).filter((tr) => WHOLE_FR_TRACK.test(tr)).length;
        all.push({
          where: `${relative(SRC, file).split(sep).join('/')}:${i + 1}`,
          template,
          bare,
        });
      }
    });
  }
  return { all, multiFr: all.filter((h) => h.bare >= 2) };
}

describe('arbitrary grid track lists', () => {
  const { all, multiFr } = collect();

  it('still fires on the template that was actually measured clipping', () => {
    // The instrument proving itself, in the same run as the verdict. A source
    // scan that quietly stopped matching would otherwise report a clean tree
    // and a clean tree is exactly what a broken detector also reports. These
    // are the strings from before and after the fix at
    // ProjectDetailPage.tsx:657 and :1789.
    const bareCount = (template: string) =>
      tracksOf(template).filter((tr) => WHOLE_FR_TRACK.test(tr)).length;
    expect(bareCount('grid-cols-[3fr_2fr]')).toBe(2);
    expect(bareCount('grid-cols-[minmax(0,3fr)_minmax(0,2fr)]')).toBe(0);
    // And the near miss that made the first draft of this file accuse three
    // innocent templates: the `.4fr` inside a wrapped `1.4fr` is not a track.
    expect(bareCount('grid-cols-[minmax(0,1.4fr)_120px_minmax(0,1.8fr)]')).toBe(0);
    expect(bareCount('grid-cols-[minmax(60px,0.6fr)_minmax(0,2fr)]')).toBe(0);
  });

  it('scans a non-empty population of arbitrary templates', () => {
    // The denominator, printed next to the verdict on purpose. A regex that
    // stopped matching would make the assertion below pass over nothing.
    expect(all.length).toBeGreaterThanOrEqual(60);
  });

  it('never lets two bare fractional tracks share one template', () => {
    // Two or more bare `fr` tracks is the measured mechanism: each charges its
    // min-content floor against the other's share. One bare `fr` beside fixed
    // or `auto` tracks carries a smaller version of the same risk and is left
    // alone here, because narrowing it changes sizing nobody has measured.
    const offenders = multiFr.map((h) => `${h.where} ${h.template}`);
    expect(offenders).toEqual([]);
  });

  it('writes every track list as valid CSS', () => {
    // Tailwind joins arbitrary track lists with `_`, not `,`. A comma survives
    // into the stylesheet as `grid-template-columns: 1fr,1fr,auto`, which is
    // invalid, so the browser drops the whole declaration and the row silently
    // collapses to one implicit column. Nothing throws and nothing is red.
    const commas = all
      .filter((h) => h.template.includes(','))
      .filter((h) => !/minmax\(|repeat\(/.test(h.template))
      .map((h) => `${h.where} ${h.template}`);
    expect(commas).toEqual([]);
  });
});
