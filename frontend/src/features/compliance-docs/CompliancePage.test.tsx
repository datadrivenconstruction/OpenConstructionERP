// @ts-nocheck
/**
 * Compliance page smoke tests.
 *
 * Mocks the API layer so we can verify:
 *   - empty state when the project has no docs
 *   - table renders 3 rows when API returns 3
 *   - clicking "New document" opens the modal
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', () => ({
  listComplianceDocs: vi.fn(),
  listExpiringSoon: vi.fn(),
  createComplianceDoc: vi.fn(),
  deleteComplianceDoc: vi.fn(),
  getComplianceDoc: vi.fn(),
  updateComplianceDoc: vi.fn(),
}));

vi.mock('@/features/file-manager/hooks', () => ({
  useFileList: () => ({ data: { items: [] } }),
}));

import { listComplianceDocs } from './api';
import { CompliancePage } from './CompliancePage';

function makeDoc(overrides: Record<string, unknown> = {}) {
  return {
    id: 'doc-' + Math.random().toString(36).slice(2, 9),
    project_id: 'proj-1',
    doc_type: 'insurance_general_liability',
    name: 'GL Policy',
    issuer: 'Acme',
    policy_number: 'GL-001',
    coverage_amount: '1000000',
    currency: 'EUR',
    effective_date: '2026-01-01',
    expires_at: '2027-01-01',
    notify_days_before: 30,
    status: 'active',
    attachment_document_id: null,
    notes: '',
    metadata: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    days_until_expiry: 200,
    ...overrides,
  };
}

function renderWithProviders(projectId: string | null = 'proj-1') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // RecoveryCard (rendered on the error branch) calls useLocation, so the
  // tree must sit inside a router.
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <CompliancePage projectId={projectId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CompliancePage', () => {
  beforeEach(() => {
    vi.mocked(listComplianceDocs).mockReset();
  });

  it('renders an empty state when no docs', async () => {
    vi.mocked(listComplianceDocs).mockResolvedValue([]);
    renderWithProviders();
    await waitFor(() =>
      expect(
        screen.getByText(/no compliance documents/i),
      ).toBeInTheDocument(),
    );
  });

  it('renders the recovery UI (not the empty state) when the fetch fails', async () => {
    // A failed load must be visibly distinct from a genuinely empty register:
    // surfacing "No compliance documents yet" on a network/500/permission
    // error is a dangerous false negative for a compliance register.
    vi.mocked(listComplianceDocs).mockRejectedValue(new Error('boom'));
    renderWithProviders();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /retry/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/couldn’t load this/i)).toBeInTheDocument();
    // The misleading empty state must NOT render on error.
    expect(
      screen.queryByText(/no compliance documents/i),
    ).not.toBeInTheDocument();
  });

  it('renders 3 rows when the API returns 3 docs', async () => {
    vi.mocked(listComplianceDocs).mockResolvedValue([
      makeDoc({ name: 'Row A', expires_at: '2026-06-01', status: 'active' }),
      makeDoc({
        name: 'Row B',
        expires_at: '2026-05-20',
        status: 'expiring_soon',
        doc_type: 'permit_building',
      }),
      makeDoc({
        name: 'Row C',
        expires_at: '2026-04-01',
        status: 'expired',
        doc_type: 'certification_safety',
      }),
    ]);
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText('Row A')).toBeInTheDocument();
      expect(screen.getByText('Row B')).toBeInTheDocument();
      expect(screen.getByText('Row C')).toBeInTheDocument();
    });
    const table = screen.getByTestId('compliance-table');
    // 3 data rows.
    expect(table.querySelectorAll('tbody tr')).toHaveLength(3);
  });

  it('opens the create modal when "New document" is clicked', async () => {
    vi.mocked(listComplianceDocs).mockResolvedValue([]);
    renderWithProviders();
    await waitFor(() =>
      expect(screen.getByTestId('compliance-empty-cta')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('compliance-empty-cta'));
    // The create flow mounts CreateComplianceDocModal, which renders through
    // the shared WideModal as a role="dialog" labelled by its title and
    // exposes the form fields (e.g. the name input). Assert on the real
    // a11y contract rather than a testid the modal never set.
    await waitFor(() =>
      expect(
        screen.getByRole('dialog', { name: /new compliance document/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTestId('compliance-field-name')).toBeInTheDocument();
  });
});
