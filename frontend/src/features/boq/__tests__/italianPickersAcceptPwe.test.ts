// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The XPWE reader parses a .pwe export and refuses the native .dcf project file
// with a message saying what to do, but only if a file picker lets the user
// choose those files. Every picker an Italian bill or price list goes through
// must offer them; the bill pickers also offer .dcf so its refusal is seen.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (path: string): string => readFileSync(resolve(__dirname, path), 'utf8');

/** The extensions of the first `accept` string literal found after `marker`. */
function acceptAfter(source: string, marker: string): string[] {
  const at = source.indexOf(marker);
  expect(at, `marker ${marker} not found`).toBeGreaterThanOrEqual(0);
  const match = /(?:accept=|ACCEPT = )["']([^"']+)["']/.exec(source.slice(at));
  expect(match, `no accept list after ${marker}`).not.toBeNull();
  return match![1]!.split(',').map((e) => e.trim());
}

describe('Italian import pickers', () => {
  it('the bill toolbar offers .pwe and .dcf', () => {
    const exts = acceptAfter(read('../BOQToolbar.tsx'), 'ref={importInputRef');
    expect(exts).toEqual(expect.arrayContaining(['.xpwe', '.pwe', '.dcf']));
  });

  it('the import preview dialog offers .pwe and .dcf', () => {
    const exts = acceptAfter(read('../ImportPreviewDialog.tsx'), 'accept=".xlsx');
    expect(exts).toEqual(expect.arrayContaining(['.xpwe', '.pwe', '.dcf']));
  });

  it('the regional price list import offers .pwe', () => {
    const exts = acceptAfter(read('../../costs/RegionalPriceListImport.tsx'), 'const ACCEPT');
    expect(exts).toEqual(expect.arrayContaining(['.xpwe', '.pwe']));
  });

  it('the New BOQ window lists the Italian formats among its import standards', () => {
    const source = read('../CreateBOQPage.tsx');
    const row = source.split('\n').find((line) => line.includes("'boq.import_region_it'"));
    expect(row, 'Italian import standard row').toBeTruthy();
    for (const ext of ['.xpwe', '.pwe', '.dcf']) expect(row).toContain(`'${ext}'`);
    expect(source).toMatch(/accept=\{IMPORT_ACCEPT\}/);
  });
});
