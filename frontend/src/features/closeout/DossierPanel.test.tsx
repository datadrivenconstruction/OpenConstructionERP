import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as api from './api';
import { DossierPanel } from './DossierPanel';

vi.mock('./api', () => ({
  checkDossier: vi.fn(),
  downloadDossier: vi.fn(),
  getDossierConfig: vi.fn(),
  listDossiers: vi.fn(),
  listDossierTargets: vi.fn(),
  putDossierConfig: vi.fn(),
  requestDossier: vi.fn(),
  resendDelivery: vi.fn(),
}));
vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

function wrap(child: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{child}</QueryClientProvider>);
}

const baseCheck = {
  scope: { kind: 'project', value: null },
  punch_total: 2,
  punch_open: 1,
  commissioning_systems: 0,
  acceptance_bound: false,
  acceptance_signed: false,
  categories: {},
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getDossierConfig).mockResolvedValue({
    required_categories: ['as_built'],
    require_punch_resolved: true,
    require_punch_photos: true,
    require_commissioning_complete: true,
    require_signed_acceptance: true,
    require_verified_evidence: false,
    share_expires_in_days: 30,
  });
  vi.mocked(api.listDossiers).mockResolvedValue([]);
  vi.mocked(api.listDossierTargets).mockResolvedValue([]);
});

describe('DossierPanel', () => {
  it('blocks assembly while the checklist has errors', async () => {
    vi.mocked(api.checkDossier).mockResolvedValue({
      ...baseCheck,
      check_status: 'errors',
      results: [{ rule_id: 'closeout.dossier_punch_resolved', severity: 'error', message: 'Punch open' }],
    } as api.DossierCheck);
    wrap(<DossierPanel packageId="pk" projectId="p1" categoryLabel={(c) => c} canSignOff={false} />);
    await waitFor(() => expect(screen.getByText('Punch open')).toBeTruthy());
    expect((screen.getByTestId('dossier-assemble') as HTMLButtonElement).disabled).toBe(true);
  });

  it('assembles a passing dossier for download', async () => {
    vi.mocked(api.checkDossier).mockResolvedValue({ ...baseCheck, check_status: 'passed', results: [] } as api.DossierCheck);
    vi.mocked(api.requestDossier).mockResolvedValue({} as api.Dossier);
    wrap(<DossierPanel packageId="pk" projectId="p1" categoryLabel={(c) => c} canSignOff={false} />);
    await waitFor(() => expect(screen.getByTestId('dossier-check')).toBeTruthy());
    fireEvent.click(screen.getByTestId('dossier-assemble'));
    await waitFor(() =>
      expect(api.requestDossier).toHaveBeenCalledWith('pk', {
        scope_kind: 'project',
        scope_value: null,
        allow_incomplete: false,
        deliveries: [],
      }),
    );
  });

  it('needs a manager to send a dossier out', async () => {
    vi.mocked(api.checkDossier).mockResolvedValue({ ...baseCheck, check_status: 'passed', results: [] } as api.DossierCheck);
    wrap(<DossierPanel packageId="pk" projectId="p1" categoryLabel={(c) => c} canSignOff={false} />);
    await waitFor(() => expect(screen.getByTestId('dossier-check')).toBeTruthy());
    fireEvent.change(screen.getByTestId('dossier-channel'), { target: { value: 'email' } });
    expect(screen.getByText('closeout.dossier.manager_only')).toBeTruthy();
  });
});
