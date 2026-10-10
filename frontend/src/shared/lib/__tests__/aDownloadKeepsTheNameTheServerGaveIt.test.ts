// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The file name of a download is the server's business. The backend sends it
// twice (backend/app/core/content_disposition.py): a lossy ASCII form under
// `filename` and the real UTF-8 name under `filename*`. A reader that takes
// the first one saves "Istanbul Veri Merkezi" for a project called "İstanbul
// Veri Merkezi", and a reader with a greedy pattern saves the whole header
// tail as the name. These hold `downloadWithAuth` to the real name, and the
// document helpers to the query the export routes read.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { downloadWithAuth } from '@/shared/lib/api';
import {
  defaultDocumentLocale,
  documentExportUrl,
  documentLocaleName,
  downloadRecordPdf,
  downloadRegister,
} from '@/shared/lib/documentExport';

/** The header exactly as `attachment_disposition` builds it. */
function disposition(ascii: string, real: string): string {
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(real)}`;
}

const fetchMock = vi.fn();
let savedAs: string[] = [];

function respondWith(headers: Record<string, string>, ok = true, body: unknown = null) {
  fetchMock.mockResolvedValue({
    ok,
    status: ok ? 200 : 403,
    headers: new Headers(headers),
    blob: async () => new Blob(['x']),
    json: async () => body,
  });
}

beforeEach(() => {
  savedAs = [];
  vi.stubGlobal('fetch', fetchMock);
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:x');
  globalThis.URL.revokeObjectURL = vi.fn();
  // jsdom cannot navigate; record the name each download was saved under.
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    savedAs.push(this.download);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

describe('the name a download is saved under', () => {
  it('is the UTF-8 name, with its Turkish letters, not the ASCII stand-in', async () => {
    respondWith({
      'Content-Disposition': disposition(
        'Istanbul Veri Merkezi - yazisma gunlugu.pdf',
        'İstanbul Veri Merkezi - yazışma günlüğü.pdf',
      ),
    });
    await downloadWithAuth('/api/v1/correspondence/export/', 'fallback.pdf');
    expect(savedAs).toEqual(['İstanbul Veri Merkezi - yazışma günlüğü.pdf']);
  });

  it('keeps every letter the two alphabets disagree on: ç ğ ı İ ö ş ü', async () => {
    const real = 'Çığ Şantiyesi İÖÜ ığüşöç.xlsx';
    respondWith({ 'Content-Disposition': disposition('Cig Santiyesi IOU igusoc.xlsx', real) });
    await downloadWithAuth('/api/v1/submittals/export/', 'fallback.xlsx');
    expect(savedAs).toEqual([real]);
  });

  it('is the plain name when that is the only one sent', async () => {
    respondWith({ 'Content-Disposition': 'attachment; filename="onay-belgeleri-takip-listesi.xlsx"' });
    await downloadWithAuth('/api/v1/submittals/export/', 'fallback.xlsx');
    expect(savedAs).toEqual(['onay-belgeleri-takip-listesi.xlsx']);
  });

  it('falls back to the plain name when the encoded one cannot be decoded', async () => {
    respondWith({ 'Content-Disposition': `attachment; filename="rfi_log.pdf"; filename*=UTF-8''rfi%E0%A4%A.pdf` });
    await downloadWithAuth('/api/v1/rfi/export/register/', 'fallback.pdf');
    expect(savedAs).toEqual(['rfi_log.pdf']);
  });

  it('is the caller fallback when the response names no file', async () => {
    respondWith({});
    await downloadWithAuth('/api/v1/rfi/export/register/', 'rfi-log.pdf');
    expect(savedAs).toEqual(['rfi-log.pdf']);
  });

  it('is nothing at all when the server refuses: the message is thrown instead', async () => {
    respondWith({}, false, { detail: 'Bu projeye erişim yetkiniz yok' });
    await expect(downloadWithAuth('/api/v1/rfi/export/register/', 'rfi-log.pdf')).rejects.toThrow(
      'Bu projeye erişim yetkiniz yok',
    );
    expect(savedAs).toEqual([]);
  });
});

describe('the query a document route is asked with', () => {
  it('carries the project, the format and the language for a register', async () => {
    respondWith({});
    await downloadRegister('/v1/submittals/export/', 'p-1', 'pdf', 'tr', 'submittal-register');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/submittals/export/?project_id=p-1&format=pdf&locale=tr');
    expect(savedAs).toEqual(['submittal-register.pdf']);
  });

  it('carries only the language for the form of one record', async () => {
    respondWith({});
    await downloadRecordPdf('/v1/submittals/s-1/export/pdf/', 'en', 'submittal');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/submittals/s-1/export/pdf/?locale=en');
  });

  it('leaves out a parameter that has no value and keeps the trailing slash', () => {
    expect(documentExportUrl('/v1/rfi/export/register/', { project_id: 'p-1', locale: undefined, basis: '' })).toBe(
      '/api/v1/rfi/export/register/?project_id=p-1',
    );
    expect(documentExportUrl('/v1/rfi/export/register/')).toBe('/api/v1/rfi/export/register/');
  });
});

describe('the language a document is offered in first', () => {
  it('is the interface language when the document exists in it', () => {
    expect(defaultDocumentLocale(['en', 'tr'], 'tr')).toBe('tr');
    expect(defaultDocumentLocale(['en', 'tr'], 'tr-TR')).toBe('tr');
    expect(defaultDocumentLocale(['en', 'de', 'tr'], 'de')).toBe('de');
  });

  it('is English when it does not, which is what the server would print anyway', () => {
    expect(defaultDocumentLocale(['en', 'tr'], 'de')).toBe('en');
    expect(defaultDocumentLocale(['en', 'tr'], null)).toBe('en');
  });

  it('names each language the way its readers do', () => {
    expect(documentLocaleName('tr')).toBe('Türkçe');
    expect(documentLocaleName('en')).toBe('English');
  });
});
