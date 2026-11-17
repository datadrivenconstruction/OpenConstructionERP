// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ContractSealCard, SealAsBasisAction, VariationSealPricing } from './SealedEstimateEntry';
import { archiveApi, type Policy, type SealSummary } from './api';

vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({
    t: (key: string, second?: string | { defaultValue?: string }) =>
      typeof second === 'string' ? second : (second?.defaultValue ?? key),
    i18n: { language: 'en' },
  }),
}));

const policy = (enabled: boolean): Policy => ({
  profile: enabled ? 'de' : 'neutral',
  enabled,
  term: 'Urkalkulation',
  methods: ['original_basis', 'cost_plus_markup'],
  require_breakdown: false,
  require_receipt: false,
  require_both_parties: true,
  internal_read: true,
  retention_years: 5,
  on_account_percent: null,
  attachment_presets: [],
  citations: [],
  tsa_configured: false,
});

const seal: SealSummary = {
  id: 's1',
  project_id: 'p1',
  contract_id: 'c1',
  contract_label: 'Main contract',
  source_boq_id: 'b1',
  label: 'Award estimate',
  basis_kind: 'award',
  status: 'sealed',
  deposit_mode: 'platform',
  profile: 'de',
  sealed_at: '2026-07-01T10:00:00Z',
  sealed_by_name: 'Estimator',
  award_total: '12033.28',
  currency: 'EUR',
  content_hash: 'a'.repeat(64),
  tsa_authority: null,
  receipt_status: 'external',
  openings: 2,
  positions: 3,
  with_breakdown: 3,
  supersedes_id: null,
  superseded_by: null,
  last_verified_at: null,
  last_verified_ok: null,
};

function mount(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('estimate editor entry', () => {
  it('offers to seal a locked estimate that has no seal', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(true));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([]);
    mount(<SealAsBasisAction projectId="p1" boqId="b1" locked />);
    expect(await screen.findByRole('button', { name: /Seal as contract basis/ })).toBeTruthy();
  });

  it('shows the seal instead of the action once the estimate is sealed', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(true));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([seal]);
    mount(<SealAsBasisAction projectId="p1" boqId="b1" locked />);
    const link = await screen.findByRole('link', { name: /Sealed/ });
    expect(link.getAttribute('href')).toBe('/estimate-archive/s1');
    expect(screen.queryByRole('button', { name: /Seal as contract basis/ })).toBeNull();
  });

  it('shows nothing where the market does not seal', async () => {
    const spy = vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(false));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([seal]);
    const { container } = mount(<SealAsBasisAction projectId="p1" boqId="b1" locked />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });
});

describe('contract drawer card', () => {
  it('names the seal with its fingerprint and openings', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(true));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([seal]);
    mount(<ContractSealCard projectId="p1" contractId="c1" />);
    expect(await screen.findByText('Award estimate')).toBeTruthy();
    expect(screen.getByText(/aaaaaaaa/)).toBeTruthy();
  });

  it('says there is no seal and offers to make one', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(true));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([]);
    mount(<ContractSealCard projectId="p1" contractId="c1" />);
    expect(await screen.findByText(/No sealed estimate/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Seal the award estimate/ })).toBeTruthy();
  });
});

describe('variation bill entry', () => {
  it('offers pricing from the seal and lists lines without a live seal', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(true));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([seal]);
    vi.spyOn(archiveApi, 'variationFindings').mockResolvedValue([
      { rule_id: 'estimate_archive.var_basis_no_seal', code: 'VAR_BASIS_NO_SEAL', severity: 'warning', message: 'Line L1 claims original basis but the contract has no seal.' },
    ]);
    mount(<VariationSealPricing projectId="p1" variationRequestId="v1" editable currency="EUR" />);
    expect(await screen.findByRole('button', { name: /Add from sealed estimate/ })).toBeTruthy();
    expect(await screen.findByText(/Line L1 claims original basis/)).toBeTruthy();
  });

  it('hides the source when the project has no live seal', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(true));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([{ ...seal, status: 'superseded' }]);
    vi.spyOn(archiveApi, 'variationFindings').mockResolvedValue([]);
    mount(<VariationSealPricing projectId="p1" variationRequestId="v1" editable currency="EUR" />);
    await waitFor(() => expect(archiveApi.seals).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /Add from sealed estimate/ })).toBeNull();
  });
});
