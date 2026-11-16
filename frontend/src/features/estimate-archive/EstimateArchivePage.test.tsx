import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EstimateArchivePage } from './EstimateArchivePage';
import { archiveApi, type Policy, type SealSummary } from './api';

vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({
    t: (key: string, second?: string | { defaultValue?: string }) =>
      typeof second === 'string' ? second : (second?.defaultValue ?? key),
    i18n: { language: 'en' },
  }),
}));
vi.mock('@/shared/ui/PageHeader', () => ({
  PageHeader: ({ actions }: { actions?: React.ReactNode }) => <div>{actions}</div>,
}));
vi.mock('@/shared/hooks/useActiveProjectId', () => ({ useActiveProjectId: () => 'p1' }));

const policy = (enabled: boolean, profile = 'de'): Policy => ({
  profile,
  enabled,
  term: 'Urkalkulation',
  methods: ['original_basis', 'cost_plus_markup'],
  require_breakdown: true,
  require_receipt: true,
  require_both_parties: true,
  internal_read: true,
  retention_years: 10,
  on_account_percent: null,
  attachment_presets: [],
  citations: [],
  tsa_configured: false,
});

const seal: SealSummary = {
  id: 's1',
  project_id: 'p1',
  contract_id: null,
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
  openings: 1,
  positions: 3,
  with_breakdown: 3,
  supersedes_id: null,
  superseded_by: null,
  last_verified_at: null,
  last_verified_ok: null,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <EstimateArchivePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(archiveApi, 'kpis').mockResolvedValue({
    seals: 1,
    awaiting_receipt: 0,
    openings_in_progress: 0,
    openings_this_year: 1,
    positions_without_breakdown: 0,
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('EstimateArchivePage', () => {
  it('lists the seal with its label and a short fingerprint', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(true));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([seal]);
    renderPage();
    expect(await screen.findByText('Award estimate')).toBeTruthy();
    expect(screen.getAllByText(/aaaaaaaa/).length).toBeGreaterThan(0);
  });

  it('says the market does not use seals when the profile has them off', async () => {
    vi.spyOn(archiveApi, 'policy').mockResolvedValue(policy(false, 'neutral'));
    vi.spyOn(archiveApi, 'seals').mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/not part of this project's market profile/)).toBeTruthy();
  });
});
