// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The diary PDF is fetched as a file, not through `apiGet`, so it carries no
// Accept-Language header. Until this the request named no language at all and
// a Turkish reader was handed the English form. The language now travels as
// ?locale=: the one the caller picked, or the interface language when the
// caller picked none. The route has no trailing slash
// (backend/app/modules/daily_diary/router.py).

import { describe, it, expect, vi, beforeEach } from 'vitest';

const downloadWithAuth = vi.fn(async (..._args: unknown[]) => undefined);
let uiLanguage: string | null = 'tr';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    activeLanguageTag: () => uiLanguage,
    downloadWithAuth: (...args: unknown[]) => downloadWithAuth(...args),
  };
});

import { downloadDiaryPdf } from './api';

function call(): unknown[] {
  return downloadWithAuth.mock.calls[0] ?? [];
}

beforeEach(() => {
  downloadWithAuth.mockClear();
  uiLanguage = 'tr';
});

describe('downloadDiaryPdf', () => {
  it('asks for the interface language when the caller names none', async () => {
    await downloadDiaryPdf('d-1', '2026-10-09');
    expect(downloadWithAuth).toHaveBeenCalledTimes(1);
    expect(call()[0]).toBe('/api/v1/daily-diary/diaries/d-1/pdf?locale=tr');
    // Only a fallback: the server names the file, in the document language.
    expect(call()[1]).toBe('diary-2026-10-09.pdf');
  });

  it('asks for the language the caller picked, over the interface language', async () => {
    await downloadDiaryPdf('d-1', '2026-10-09', 'de');
    expect(call()[0]).toBe('/api/v1/daily-diary/diaries/d-1/pdf?locale=de');
  });

  it('leaves the language to the server when the interface has none yet', async () => {
    uiLanguage = null;
    await downloadDiaryPdf('d-1');
    expect(call()[0]).toBe('/api/v1/daily-diary/diaries/d-1/pdf');
    expect(call()[1]).toBe('diary-d-1.pdf');
  });

  it('passes on the refusal, with what the server said', async () => {
    downloadWithAuth.mockRejectedValueOnce(new Error('Bu projeye erişim yetkiniz yok'));
    await expect(downloadDiaryPdf('d-1')).rejects.toThrow('Bu projeye erişim yetkiniz yok');
  });
});
