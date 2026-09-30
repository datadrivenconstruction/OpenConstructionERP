// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project page's Import button posts to the route that reads a bill natively.
//
// A user in Hungary imported their bills from the project page and "did not get
// a good result". That button posted to the deprecated smart route, which read
// a spreadsheet's item sheet on its own: a Hungarian chapter workbook lost its
// item codes and its sections, the import was never validated, and a dropped
// .xls did nothing at all. An .xls is read natively now, like an .xlsx. The bill editor's import dialog already posted to
// /import/auto/, so the same file gave two different bills depending on which
// button the user found first.
//
// The dialog is an unexported component of a very large page, so the check
// reads the source: the route the page posts to, the language it asks the
// server to answer in, and that a file it cannot take is refused out loud. Each
// assertion has a control that fails if the source could not be read at all.

import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')].find((p) =>
  existsSync(join(p, 'features/projects/ProjectDetailPage.tsx')),
);

function page(): string {
  if (!SRC) throw new Error('frontend/src not found from the test working directory');
  return readFileSync(join(SRC, 'features/projects/ProjectDetailPage.tsx'), 'utf8');
}

describe('project page import', () => {
  it('posts to the auto route and never to the deprecated smart route', () => {
    const source = page();
    expect(source.length).toBeGreaterThan(10_000);
    expect(source).toContain('/import/auto/');
    expect(source).not.toContain('/import/smart/');
  });

  it('asks the server to answer in the UI language', () => {
    const source = page();
    const call = source.slice(source.indexOf('async function importFileToBoq'), source.indexOf('export function formatCurrency'));
    expect(call).toContain('/import/auto/');
    expect(call).toContain("'Accept-Language'");
  });

  it('takes an .xls and refuses a file it cannot take with a message', () => {
    const source = page();
    const list = source.slice(source.indexOf('const SUPPORTED_EXTENSIONS'), source.indexOf('];', source.indexOf('const SUPPORTED_EXTENSIONS')));
    expect(list).toContain("'.xlsx'");
    expect(list).toContain("'.xls'");
    expect(source).not.toContain('import.legacy_xls');
    expect(source).toContain("t('import.unsupported_type'");
    expect(source).toContain('setRejected(');
  });

  it('words the import report through the shared issue wording', () => {
    const source = page();
    expect(source).toContain("from '@/features/boq/importIssueText'");
    expect(source.match(/importIssueText\(/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
  });
});
