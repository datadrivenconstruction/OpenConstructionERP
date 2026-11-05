// Subcontract changes: owner panel (margin strip, split payload) and the
// agreement's own list (link back to the owner VO / CO).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), getAuthToken: () => 'token' };
});

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

import { apiGet, apiPost } from '@/shared/lib/api';
import { SubcontractChangesPanel } from './SubcontractChangesPanel';
import { AgreementChangesSection } from './AgreementChangesSection';

const change = (over: Record<string, unknown> = {}) => ({
  id: 'c-1',
  agreement_id: 'ag-1',
  project_id: 'p-1',
  code: 'SC-001',
  title: 'Extra slab',
  amount: '4000.00',
  currency: 'EUR',
  status: 'draft',
  back_to_back: true,
  owner_change_type: 'variation_order',
  owner_change_id: 'vo-1',
  ...over,
});

const rollup = {
  owner_code: 'VO-1',
  owner_title: 'Extra slab',
  owner_status: 'agreed',
  currency: 'EUR',
  owner_value: '10000.00',
  sub_cost_approved: '3000.00',
  sub_cost_pending: '9000.00',
  sub_cost_total: '12000.00',
  margin: '-2000.00',
  margin_percent: '-20',
  owner_approved: true,
  approved_sub_total: '3000.00',
  markup_retained: '300.00',
  leakage: '-2300.00',
  days_owner: 10,
  days_sub_total: 13,
  changes: [change({ markup_pct: '10.000', time_impact_days: 4 })],
};

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
  vi.mocked(apiPost).mockReset().mockResolvedValue([]);
  vi.mocked(apiGet).mockImplementation(async (path: string) => {
    if (path.includes('/changes/by-owner-change/')) return rollup;
    if (path.includes('/validate/')) {
      return { status: 'warnings', results: [{ rule_id: 'r1', severity: 'warning', passed: false, message: 'Exceeds agreement value' }] };
    }
    if (path.includes('/agreements/ag-1/changes/')) return { items: [change()], total: 1, offset: 0, limit: 500 };
    if (path.includes('/agreements/')) return [{ id: 'ag-1', title: 'Concrete works', project_id: 'p-1' }];
    return [];
  });
});

describe('SubcontractChangesPanel', () => {
  it('renders the margin strip, the linked change and its validation warning', async () => {
    wrap(<SubcontractChangesPanel ownerType="variation_order" ownerId="vo-1" projectId="p-1" />);
    await waitFor(() => expect(screen.getByTestId('sc-owner-value').textContent).toMatch(/10[,.\s]?000/));
    expect(screen.getByTestId('sc-sub-cost').textContent).toMatch(/12[,.\s]?000/);
    expect(screen.getByTestId('sc-margin').textContent).toMatch(/2[,.\s]?000/);
    expect(screen.getByTestId('sc-margin').className).toContain('text-semantic-error');
    expect(screen.getByTestId('sc-margin-pct').textContent).toContain('20');
    expect(await screen.findByText('SC-001')).toBeTruthy();
    expect(await screen.findByText('Exceeds agreement value')).toBeTruthy();
    expect(screen.getByText('submit')).toBeTruthy();
  });

  it('posts the split lines to from-owner-change', async () => {
    wrap(<SubcontractChangesPanel ownerType="variation_order" ownerId="vo-1" projectId="p-1" ownerTitle="Extra slab" />);
    await screen.findByText('Concrete works', { selector: 'option' });
    fireEvent.change(screen.getByLabelText('Agreement'), { target: { value: 'ag-1' } });
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '2500' } });
    fireEvent.click(screen.getByText('Create subcontract changes'));
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    expect(vi.mocked(apiPost).mock.calls[0]![0]).toContain('/changes/from-owner-change/');
    expect(vi.mocked(apiPost).mock.calls[0]![1]).toEqual({
      owner_change_type: 'variation_order',
      owner_change_id: 'vo-1',
      lines: [
        { agreement_id: 'ag-1', amount: '2500', title: 'Extra slab', back_to_back: true, markup_pct: 0, time_impact_days: 0 },
      ],
    });
  });
});

describe('SubcontractChangesPanel pass-through', () => {
  it('shows markup and days columns and the leakage strip', async () => {
    wrap(<SubcontractChangesPanel ownerType="variation_order" ownerId="vo-1" projectId="p-1" />);
    expect((await screen.findByTestId('sc-markup-SC-001')).textContent).toBe('10.000');
    expect(screen.getByTestId('sc-days-SC-001').textContent).toBe('4');
    expect(screen.getByTestId('sc-leakage').textContent).toMatch(/2[,.\s]?300/);
    expect(screen.getByTestId('sc-leakage').className).toContain('text-semantic-error');
    expect(screen.getByTestId('sc-markup-retained').textContent).toMatch(/300/);
    expect(screen.getByTestId('sc-days').textContent).toContain('10');
    expect(screen.getByTestId('sc-days').textContent).toContain('13');
  });

  it('blocks approval with a chip while the owner change is not approved', async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path.includes('/changes/by-owner-change/')) {
        return { ...rollup, owner_status: 'draft', owner_approved: false, changes: [change({ status: 'submitted' })] };
      }
      if (path.includes('/validate/')) return { status: 'ok', results: [] };
      return [];
    });
    wrap(<SubcontractChangesPanel ownerType="variation_order" ownerId="vo-1" projectId="p-1" />);
    expect(await screen.findByTestId('sc-blocker-SC-001')).toBeTruthy();
    expect(screen.getByText('approve').closest('button')?.disabled).toBe(true);
  });

  it('shows no chip and an enabled approve once the owner approved', async () => {
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path.includes('/changes/by-owner-change/')) return { ...rollup, changes: [change({ status: 'submitted' })] };
      if (path.includes('/validate/')) return { status: 'ok', results: [] };
      return [];
    });
    wrap(<SubcontractChangesPanel ownerType="variation_order" ownerId="vo-1" projectId="p-1" />);
    await screen.findByText('SC-001');
    expect(screen.queryByTestId('sc-blocker-SC-001')).toBeNull();
    expect(screen.getByText('approve').closest('button')?.disabled).toBe(false);
  });
});

describe('AgreementChangesSection', () => {
  it('links each change back to its owner record', async () => {
    wrap(<AgreementChangesSection agreementId="ag-1" />);
    const link = await screen.findByText('Variation order');
    expect(link.closest('a')?.getAttribute('href')).toBe('/variations?tab=orders&highlight=vo-1');
  });
});
