// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/app/i18n', async () => {
  const { default: instance } = await import('i18next');
  const [{ default: en }, { default: ru }] = await Promise.all([
    import('@/app/locales/en'), import('@/app/locales/ru'),
  ]);
  await instance.init({ lng: 'en', fallbackLng: 'en', resources: { en, ru }, interpolation: { escapeValue: false } });
  return { default: instance };
});

import i18n from '@/app/i18n';
import { checkX89, downloadClaimInvoice, downloadX31, previewX31 } from './gaebSiteExchangeApi';
import { missingInvoiceFieldLabel } from './gaebInvoiceFieldText';

const file = new File(['<GAEB/>'], 'site.xml', { type: 'application/xml' });

function respond(body: unknown, status = 400) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  }));
}

afterEach(() => { vi.restoreAllMocks(); });

describe.each(['en', 'ru'])('GAEB site errors in %s', (language) => {
  it.each([['X31', previewX31], ['X89', checkX89]] as const)('translates a coded %s parse refusal', async (_phase, read) => {
    await i18n.changeLanguage(language);
    const fetch = respond({ detail: { code: 'gaeb_not_well_formed', params: { line: 2, column: 8 }, message: 'SERVER ENGLISH' } });
    await expect(read('bill-1', file)).rejects.toThrow(i18n.t('boq.import_error.gaeb_not_well_formed', { line: 2, column: 8 }));
    expect(new Headers(fetch.mock.calls[0]?.[1]?.headers).get('Accept-Language')).toBe(language);
  });

  it('translates an empty X31 export and tells the server the UI language', async () => {
    await i18n.changeLanguage(language);
    const fetch = respond({ detail: { code: 'gaeb_no_measured_quantities', params: {}, message: 'SERVER ENGLISH' } }, 422);
    await expect(downloadX31('bill-1', 'measured', 'Bill')).rejects.toThrow(i18n.t('boq.import_error.gaeb_no_measured_quantities'));
    expect(new Headers(fetch.mock.calls[0]?.[1]?.headers).get('Accept-Language')).toBe(language);
  });

  it('uses the preview field labels when an X89 export discovers missing fields', async () => {
    await i18n.changeLanguage(language);
    const fetch = respond({ detail: { code: 'gaeb_invoice_fields_missing', missing: ['creator.street', 'period_end'], message: 'SERVER ENGLISH' } }, 422);
    const error = await downloadClaimInvoice('claim-1', 'Claim').catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(Error);
    const message = (error as Error).message;
    expect(message).toContain(i18n.t('contracts.gaeb_invoice.missing_title'));
    expect(message).toContain(missingInvoiceFieldLabel(i18n.t.bind(i18n), 'creator.street'));
    expect(message).toContain(missingInvoiceFieldLabel(i18n.t.bind(i18n), 'period_end'));
    expect(message).not.toContain('SERVER ENGLISH');
    expect(new Headers(fetch.mock.calls[0]?.[1]?.headers).get('Accept-Language')).toBe(language);
  });
});

it.each([
  { detail: 'Legacy readable refusal' },
  { detail: { message: 'Legacy readable refusal' } },
  { detail: { code: 'future_code', message: 'Legacy readable refusal' } },
])('keeps an older or unknown server refusal readable', async (body) => {
  respond(body);
  await expect(previewX31('bill', file)).rejects.toThrow('Legacy readable refusal');
});

it('uses a localized fallback for a non-JSON upstream error', async () => {
  await i18n.changeLanguage('ru');
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>bad gateway</html>', { status: 502 }));
  await expect(checkX89('bill', file)).rejects.toThrow(i18n.t('boq.gaeb_site.upload_failed', { status: 502 }));
});

it('does not turn a successful preview into a mutation or a retry', async () => {
  const result = { matched: [], unmatched: [], items_in_file: 0 };
  const fetch = respond(result, 200);
  expect(await previewX31('bill', file)).toEqual(result);
  expect(fetch).toHaveBeenCalledTimes(1);
});
