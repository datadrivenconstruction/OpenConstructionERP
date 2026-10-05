// @ts-nocheck
/**
 * The multipart calls and the small helpers of the spreadsheet import.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, fetchWithAuth: vi.fn() };
});

import { ApiError, fetchWithAuth } from '@/shared/lib/api';
import {
  commitSpreadsheet,
  importErrorDetail,
  issueParams,
  previewSpreadsheet,
  readMapping,
  templateLanguageFor,
} from './tabularImport';
import { readExample } from './DateOrderChoice';

const FILE = new File(['Name\nA\n'], 'plan.csv', { type: 'text/csv' });

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('tabularImport calls', () => {
  beforeEach(() => vi.clearAllMocks());

  it('posts the preview as multipart with only the fields given', async () => {
    fetchWithAuth.mockResolvedValue(json(200, { sha256: 'x' }));
    await previewSpreadsheet({ projectId: 'p1', file: FILE, columnMapping: null, dateOrder: 'mdy' });
    const [url, init] = fetchWithAuth.mock.calls[0];
    expect(url).toBe('/api/v1/schedule/schedule/import/spreadsheet/preview/');
    const form = init.body as FormData;
    expect(form.get('project_id')).toBe('p1');
    expect((form.get('file') as File).name).toBe('plan.csv');
    expect(form.get('date_order')).toBe('mdy');
    expect(form.has('column_mapping')).toBe(false);
  });

  it('sends the confirmed client refs as a JSON list, and the schedule only when replacing', async () => {
    fetchWithAuth.mockImplementation(async () => json(201, { schedule_id: 's' }));
    await commitSpreadsheet({
      projectId: 'p1',
      file: FILE,
      expectedSha256: 'a'.repeat(64),
      target: 'new',
      scheduleId: 's1',
      name: '  Tower A ',
      clientVisibleRefs: ['A10', 'A20'],
    });
    let form = fetchWithAuth.mock.calls[0][1].body as FormData;
    expect(fetchWithAuth.mock.calls[0][0]).toBe('/api/v1/schedule/schedule/import/spreadsheet/commit/');
    expect(form.get('client_visible_refs')).toBe('["A10","A20"]');
    expect(form.get('target')).toBe('new');
    expect(form.has('schedule_id')).toBe(false);
    expect(form.get('name')).toBe('Tower A');
    expect(form.has('allow_duplicate')).toBe(false);

    await commitSpreadsheet({
      projectId: 'p1',
      file: FILE,
      expectedSha256: 'a'.repeat(64),
      target: 'replace',
      scheduleId: 's1',
      allowDuplicate: true,
      clientVisibleRefs: [],
    });
    form = fetchWithAuth.mock.calls[1][1].body as FormData;
    expect(form.get('schedule_id')).toBe('s1');
    expect(form.get('allow_duplicate')).toBe('true');
    expect(form.get('client_visible_refs')).toBe('[]');
  });

  it('throws an ApiError that keeps the detail code', async () => {
    fetchWithAuth.mockResolvedValue(json(409, { detail: { code: 'preview_mismatch', message: 'Preview it again' } }));
    const err = await previewSpreadsheet({ projectId: 'p1', file: FILE }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(importErrorDetail(err)).toEqual({ code: 'preview_mismatch', message: 'Preview it again' });
    expect(importErrorDetail(new Error('x'))).toBeNull();
    expect(importErrorDetail(new ApiError(500, 'x', { detail: 'plain text' }))).toBeNull();
  });
});

describe('tabularImport helpers', () => {
  it('picks the template language from the interface language', () => {
    expect(templateLanguageFor('de-AT')).toBe('de');
    expect(templateLanguageFor('pt_BR')).toBe('pt');
    expect(templateLanguageFor('ja')).toBe('en');
    expect(templateLanguageFor(undefined)).toBe('en');
  });

  it('turns issue params into interpolation values', () => {
    const out = issueParams(
      { field: 'start', cycle: ['A', 'B', 'A'], ignored: [3, 4], count: 2, by_code: { name_missing: 7 }, empty: null },
      (field) => `<${field}>`,
    );
    expect(out).toEqual({ field: '<start>', cycle: 'A → B → A', ignored: '3, 4', count: 2, by_code: 'name_missing: 7' });
  });

  it('reads the proposal of each column, empty for an unrecognised one', () => {
    expect(
      readMapping([
        { index: 0, header: 'ID', field: 'id', confidence: 1, tier: 'exact' },
        { index: 1, header: '?', field: null, confidence: 0, tier: 'none' },
      ]),
    ).toEqual({ 0: 'id', 1: '' });
  });

  it('writes the example date out both ways, and not at all when it is no date', () => {
    expect(readExample('03/04/2026', 'dmy')).toContain('2026');
    expect(readExample('03/04/2026', 'dmy')).not.toBe(readExample('03/04/2026', 'mdy'));
    expect(readExample('13/04/2026', 'mdy')).toBeNull();
    expect(readExample('next week', 'dmy')).toBeNull();
    expect(readExample(null, 'dmy')).toBeNull();
  });
});
