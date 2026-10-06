// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every code a bill import can be refused or annotated with has a wording in
// en.ts, so none reaches the reader as the server's English sentence.
//
// The codes are read from the backend sources, not typed here: a code added
// to an importer without a wording fails this file. The backend half
// (tests/unit/test_boq_import_errors_are_coded.py) checks every refusal in the
// importers passes a literal ``code=``, so the walk below sees all of them.
//
// Run:  npx vitest run src/features/boq/importFailureText.test.ts

import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import en from '@/app/locales/en';
import { alreadyImported, asImportFailure, importFailureFromBody, importFailureText } from './importFailureText';
import { importIssueText } from './importIssueText';

function findRepoRoot(): string {
  const root = [resolve(process.cwd(), '..'), process.cwd()].find((p) =>
    existsSync(join(p, 'backend/app/modules/boq/importers/_base.py')),
  );
  expect(root, 'could not locate the repo root from the test working directory').toBeTruthy();
  return root!;
}

const ROOT = findRepoRoot();
const BOQ = join(ROOT, 'backend/app/modules/boq');
const read = (path: string): string => readFileSync(path, 'utf8');
const IMPORTERS = readdirSync(join(BOQ, 'importers'))
  .filter((name) => name.endsWith('.py'))
  .map((name) => read(join(BOQ, 'importers', name)));

const all = (source: string, pattern: RegExp): string[] => [...source.matchAll(pattern)].map((m) => m[1]!);

/** Codes a whole file is refused with: every ``code="..."`` in the importers, the default, and the route's own. */
function refusalCodes(): string[] {
  const codes = new Set<string>();
  for (const source of IMPORTERS) for (const code of all(source, /\bcode="([a-z0-9_]+)"/g)) codes.add(code);
  for (const file of ['gaeb_common.py', 'gaeb_x31.py', 'gaeb_x89.py', 'gaeb_exchange_router.py']) {
    for (const code of all(read(join(BOQ, file)), /\bcode="([a-z0-9_]+)"/g)) codes.add(code);
  }
  // The alternate side of the route's basis-dependent export refusal.
  codes.add('gaeb_no_quantities');
  for (const code of all(read(join(BOQ, 'importers/_base.py')), /code: str = "([a-z0-9_]+)"/g)) codes.add(code);
  for (const file of ['router.py', 'import_jobs.py']) {
    for (const code of all(read(join(BOQ, file)), /"code": "(import_[a-z0-9_]+)"/g)) codes.add(code);
  }
  return [...codes].sort();
}

/** Codes of the notes an XPWE import lists line by line. */
function xpweIssueCodes(): string[] {
  const source = read(join(BOQ, 'importers/xpwe.py'));
  const codes = new Set([
    ...all(source, /"code": "(xpwe_[a-z0-9_]+)"/g),
    ...all(source, /notes\.add\(\s*"(xpwe_[a-z0-9_]+)"/g),
  ]);
  return [...codes].sort();
}

const table = en.translation as Record<string, string>;
function t(key: string, opts?: Record<string, unknown>): string {
  const template = table[key] ?? String(opts?.defaultValue ?? key);
  return template.replace(/{{(\w+)}}/g, (_, name: string) => String(opts?.[name] ?? ''));
}

describe('import refusal codes', () => {
  it('finds the codes in the backend sources', () => {
    const codes = refusalCodes();
    expect(codes).toContain('xpwe_not_well_formed');
    expect(codes).toContain('workbook_password_protected');
    expect(codes).toContain('import_parse_failed');
    expect(codes).toContain('import_parse_unexpected');
    expect(codes).toContain('import_already_done');
    expect(codes.length).toBeGreaterThan(20);
  });

  it.each(refusalCodes())('words %s from en.ts, not from the server', (code) => {
    expect(table[`boq.import_error.${code}`], `add boq.import_error.${code} to en.ts`).toBeTruthy();
    const text = importFailureText(
      { code, params: { line: 3, column: 7, root: 'Altro', columns: [2, 5], field: 'quantity', width: 4, imported_at: '2026-10-01T09:30:00+00:00', format: 'GAEB X31', phase: 'X83', expected: 'X31', element: 'BoQ', extensions: '.x31, .xml' }, message: 'SERVER' },
      t,
      'FALLBACK',
    );
    expect(text).not.toContain('SERVER');
    expect(text).not.toMatch(/{{\w+}}/);
  });
});

describe('XPWE note codes', () => {
  it('finds the codes in the importer', () => {
    expect(xpweIssueCodes()).toEqual(expect.arrayContaining(['xpwe_price_out_of_range', 'xpwe_duplicate_item_id']));
  });

  it.each(xpweIssueCodes())('words %s from en.ts, not from the server', (code) => {
    // A note that carries a count is worded in plural forms.
    const key = `boq.import_issue.${code}`;
    expect(table[key] ?? table[`${key}_other`], `add ${key} to en.ts`).toBeTruthy();
    const text = importIssueText(
      { code, ordinal: '2.1', ref: '7', first: '1.1', value: 12, computed: 1, declared: 2, text: '2x', count: 3, amount: -236.3, encoding: 'cp1252', message: 'SERVER', error: 'SERVER' },
      t,
    );
    expect(text).not.toContain('SERVER');
  });
});

describe('importFailureText', () => {
  it('names where a malformed file broke', () => {
    expect(importFailureText({ code: 'xpwe_not_well_formed', params: { line: 12, column: 4 }, message: 'x' }, t, '')).toBe(
      'The XPWE file is not well-formed XML: it breaks off at line 12, column 4.',
    );
  });

  it('keeps the server text for a code it has no wording for, and the fallback for nothing at all', () => {
    expect(importFailureText({ code: 'something_new', message: 'Server words' }, t, 'Import failed')).toBe('Server words');
    expect(importFailureText({}, t, 'Import failed')).toBe('Import failed');
  });

  it('reads only a coded detail out of a response body', () => {
    expect(importFailureFromBody({ detail: 'plain' }, t, 'F')).toBeNull();
    expect(importFailureFromBody({ detail: [{ msg: 'x' }] }, t, 'F')).toBeNull();
    expect(importFailureFromBody({ detail: { code: 'spreadsheet_empty_file', params: {}, message: 'x' } }, t, 'F')).toBe(
      'The file is empty.',
    );
    expect(asImportFailure(null)).toBeNull();
  });

  it('tells an earlier import of the file from any other conflict', () => {
    const done = { detail: { code: 'import_already_done', params: { imported_at: '2026-10-01T09:30:00+00:00' }, message: 'x' } };
    expect(alreadyImported(409, done)).not.toBeNull();
    expect(alreadyImported(400, done)).toBeNull();
    expect(alreadyImported(409, { detail: 'The bill is locked.' })).toBeNull();
    expect(importFailureText(alreadyImported(409, done)!, t, '')).toMatch(/^This file was already imported into this bill on .+\.$/);
  });
});
