// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '@/shared/lib/api';
import { getClaimSubRollup } from '@/features/subcontractors/api';
import { getPaymentApplication, listContractDocuments, type PaymentApplication } from './api';
import { loadLenderPreparation } from './lenderDrawSources';

vi.mock('@/shared/lib/api', () => ({ apiGet: vi.fn() }));
vi.mock('@/features/subcontractors/api', () => ({ getClaimSubRollup: vi.fn() }));
vi.mock('./api', () => ({ getPaymentApplication: vi.fn(), listContractDocuments: vi.fn() }));

const context = { claimId: 'claim-1', contractId: 'contract-1', projectId: 'project-1' };
const application = {
  claim_id: 'claim-1', contract_id: 'contract-1', project_id: 'project-1', currency: 'EUR',
} as PaymentApplication;

describe('lender preparation source reads', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPaymentApplication).mockResolvedValue(application);
    vi.mocked(getClaimSubRollup).mockRejectedValue(new Error('module unavailable'));
    vi.mocked(listContractDocuments).mockResolvedValue([]);
    vi.mocked(apiGet).mockResolvedValue([]);
  });

  it('reads existing claim/contract scopes and distinguishes unavailable from an empty source', async () => {
    const draft = await loadLenderPreparation(context);
    expect(getPaymentApplication).toHaveBeenCalledWith('claim-1');
    expect(getClaimSubRollup).toHaveBeenCalledWith('claim-1');
    expect(listContractDocuments).toHaveBeenCalledWith('contract-1');
    expect(apiGet).toHaveBeenCalledWith('/v1/contracts/progress-claims/claim-1/lien-waivers');
    expect(draft.subcontractors).toEqual({ status: 'unavailable' });
    expect(draft.contract_documents).toEqual({ status: 'available', data: [] });
    expect(draft.claim_waivers).toEqual({ status: 'available', data: [] });
  });

  it('cannot produce a draft when the canonical application is denied or unavailable', async () => {
    const denied = new Error('403');
    vi.mocked(getPaymentApplication).mockRejectedValue(denied);
    await expect(loadLenderPreparation(context)).rejects.toBe(denied);
  });

  it('omits unavailable evidence without substituting fake amounts or empty successful results', async () => {
    vi.mocked(listContractDocuments).mockRejectedValue(new Error('403'));
    vi.mocked(apiGet).mockRejectedValue(new Error('503'));
    const draft = await loadLenderPreparation(context);
    expect(draft.application).toEqual(application);
    expect(draft.contract_documents).toEqual({ status: 'unavailable' });
    expect(draft.claim_waivers).toEqual({ status: 'unavailable' });
  });
});
