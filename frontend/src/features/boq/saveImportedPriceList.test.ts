// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/features/costs/regionalPriceListApi', () => ({
  uploadPriceList: vi.fn(async () => ({
    uploadId: 'up-1',
    preview: { source: { suggested_catalog_name: 'Elenco prezzi computo' }, counts: { rows: 42 } },
  })),
  importUploadedPriceList: vi.fn(async () => ({ imported: 42, catalog: 'Elenco prezzi computo' })),
}));

import { importUploadedPriceList, uploadPriceList } from '@/features/costs/regionalPriceListApi';
import { carriesPriceList, saveImportedPriceList } from './saveImportedPriceList';

describe('keeping the price list of an imported XPWE bill', () => {
  it('is offered only for XPWE bills', () => {
    expect(carriesPriceList('xpwe')).toBe(true);
    expect(carriesPriceList('gaeb')).toBe(false);
    expect(carriesPriceList(undefined)).toBe(false);
  });

  it('uploads the same file once and imports it under the suggested name and previewed count', async () => {
    const file = new File(['<PweDocumento/>'], 'computo.pwe');
    const saved = await saveImportedPriceList(file);
    expect(uploadPriceList).toHaveBeenCalledWith(file);
    expect(importUploadedPriceList).toHaveBeenCalledWith('up-1', 'Elenco prezzi computo', {}, 42);
    expect(saved.imported).toBe(42);
  });
});
