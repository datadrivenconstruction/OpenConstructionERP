// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// No colour utility may name the `accent`, `status` or `text` colour group.
//
// tailwind.config.js defines none of them. A class Tailwind does not know
// compiles to nothing: no CSS is emitted, no warning is printed, and both
// `tsc` and the build stay green. A primary button written as
// `bg-accent-primary text-white` shipped as white text on a transparent
// background, so the button was there and could not be seen. The tokens that
// exist are `oe-blue` for the brand accent and `semantic-{error,warning,
// success,info}` (plus their `-bg` tints) for status colours. Text colours
// live under `content` (`text-content-secondary`); `text-text-secondary`
// read as the same thing and rendered in the inherited colour on 87 lines.
//
// Deliberately narrow: only these three groups, which are the ones that have
// actually been used as if they existed. It is a source scan because there is
// no runtime seam that sees a class with no rule behind it.
//
// Run:  npx vitest run src/shared/lib/__tests__/noUndefinedColourTokens.test.ts

import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const SRC = join(__dirname, '..', '..', '..');
const SELF = join(__dirname, 'noUndefinedColourTokens.test.ts');

/**
 * A colour utility whose colour group is `accent`, `status` or `text`, with any
 * variant chain (`hover:`, `focus-visible:`, `aria-[...]:`), an optional `!`
 * and an optional `/NN` opacity. The leading boundary keeps test ids and CSS
 * variables such as `translation-status-error` or `--act-accent-subtle` out.
 */
const DEAD_COLOUR_UTILITY = new RegExp(
  '(?:^|[\\s"\'`{(])' +
    '(?:[^\\s"\'`]*:)?!?' +
    '(?:bg|text|border(?:-[trblxyse])?|ring(?:-offset)?|fill|stroke|divide|outline|' +
    'from|via|to|decoration|shadow|placeholder|caret|accent)' +
    '-(?:accent|status|text)-[\\w-]+(?:\\/\\d+)?',
  'g',
);

function findDeadUtilities(line: string): string[] {
  return [...line.matchAll(DEAD_COLOUR_UTILITY)].map((m) => m[0].trim().replace(/^[\s"'`{(]/, ''));
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(full) && full !== SELF) out.push(full);
  }
  return out;
}

describe('colour utilities name a colour group the Tailwind config defines', () => {
  it('the matcher catches the dead groups and leaves look-alikes alone', () => {
    for (const hit of [
      'className="hover:bg-accent-primary/10"',
      "'focus-visible:ring-accent-primary'",
      'className="p-1 group-hover:text-accent-primary"',
      "'border-status-error/30 bg-status-error/10'",
      "'aria-[invalid=true]:border-status-warning'",
      "'!text-status-success'",
      'className="text-xs text-text-secondary"',
      "'hover:text-text-primary'",
    ]) {
      expect(findDeadUtilities(hit), hit).not.toEqual([]);
    }
    for (const miss of [
      'data-testid="translation-status-error"',
      "style={{ background: 'var(--act-accent-subtle)' }}",
      'data-testid="bcf-status-select"',
      "'plot-status-pill'",
      "className=\"bg-oe-blue/10 text-semantic-error\"",
      "t('equipment.status-error')",
      'className="text-content-secondary"',
    ]) {
      expect(findDeadUtilities(miss), miss).toEqual([]);
    }
  });

  it('no source file uses an accent-*, status-* or text-* colour utility', () => {
    const files = walk(SRC);
    const scanned = new Set(files.map((f) => relative(SRC, f).split(sep).join('/')));
    // A wrong root would scan a corner of the tree and pass on nothing.
    expect(scanned.has('features/admin/PermissionsMatrixPage.tsx')).toBe(true);
    expect(files.length).toBeGreaterThan(1000);

    const offenders: string[] = [];
    for (const file of files) {
      const lines = readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        for (const cls of findDeadUtilities(line)) {
          offenders.push(`${relative(SRC, file).split(sep).join('/')}:${i + 1}  ${cls}`);
        }
      });
    }

    console.info(`[noUndefinedColourTokens] scanned ${files.length} files, ${offenders.length} dead utilities`);
    expect(offenders, `Unknown colour group; use oe-blue or semantic-*:\n${offenders.join('\n')}`).toEqual([]);
  });
});
