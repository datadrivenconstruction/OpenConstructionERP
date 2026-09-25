// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// No surface abbreviates a year.
//
// Measured on the published frames: the programme printed "05 Mar 26" in its
// date columns and "Aug 26" along its month axis, on a schedule running from
// 2026 into 2028. Two digits are cheap to write and expensive to read - the
// row already carries a two-digit day either side of the month, so the reader
// has to decide which of the two numbers is the year before they can use
// either, and they have to decide it again on the next row.
//
// Everywhere else in the product a date reads "Aug 12, 2026". Those two
// surfaces were the whole exception, which is why this is a census rather than
// two local fixes: the point is not that the two known sites were corrected,
// it is that the next date column starts from the same answer.
//
// If a surface ever genuinely needs the short form - a chart axis so dense
// that four digits will not fit - the honest move is to delete this test and
// say why in the message, not to slip the option past it. The rule is a
// decision, and a decision should be visible when it is reversed.
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..', '..', '..');

/** `year: '2-digit'`, in either quote style, however it is spaced. */
const ABBREVIATED_YEAR = /\byear\s*:\s*(['"])2-digit\1/;

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, found);
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

// The tree is walked, read and scanned once, here, while the file is collected.
// Doing it inside the test put two thousand cold reads on the per-test clock,
// and under a loaded suite that alone ran past the timeout, so the census
// reported nothing. Collection has no per-test timeout.
const FILES = sourceFiles(SRC);
const OFFENDERS: string[] = [];
for (const file of FILES) {
  const text = readFileSync(file, 'utf8');
  text.split('\n').forEach((line, i) => {
    if (ABBREVIATED_YEAR.test(line)) {
      OFFENDERS.push(`${relative(SRC, file).replace(/\\/g, '/')}:${i + 1}`);
    }
  });
}

describe('a year on screen', () => {
  it('is never written as two digits', () => {
    expect(OFFENDERS).toEqual([]);
  });

  // Guards the guard. A census that walks the wrong directory, or one whose
  // pattern never matched anything in the first place, is green for a reason
  // that has nothing to do with the codebase being right.
  it('the census reads the source tree and its pattern matches the shape it names', () => {
    expect(FILES.length).toBeGreaterThan(500);
    expect(ABBREVIATED_YEAR.test("  { month: 'short', year: '2-digit' },")).toBe(true);
    expect(ABBREVIATED_YEAR.test('    ...(withYear ? { year: "2-digit" as const } : {}),')).toBe(true);
    expect(ABBREVIATED_YEAR.test("  { month: 'short', year: 'numeric' },")).toBe(false);
  });
});
