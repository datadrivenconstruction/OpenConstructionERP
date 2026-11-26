// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for the Pillar 4 handover / acceptance package section.
//
// The API layer is stubbed via vi.mock('../api') so we can verify:
//   - the packages list renders (master row + the selected-package detail),
//   - the completion gate report loads for the selected package,
//   - creating a package calls createHandoverPackage with the chosen regime,
//   - the assemble action calls assembleHandoverPackage,
//   - the issue action is gated by the gate report (disabled when blocked,
//     enabled and callable when the gate is clear).
//
// React Query runs with retry disabled so any error surfaces immediately.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';

// Automock the whole feature-local API so every export is a vi.fn(). A partial
// factory mock here would bleed across the construction_control suite (the
// module path is shared) and strip exports the sibling sections need, so the
// section tests all automock '../api' consistently.
vi.mock('../api');

import {
  listHandoverPackages,
  createHandoverPackage,
  getHandoverGates,
  assembleHandoverPackage,
  issueHandoverCertificate,
} from '../api';
import { HandoverSection } from './HandoverSection';

const PROJECT_ID = 'proj-1';

type AnyFn = ReturnType<typeof vi.fn>;

function makePackage(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ho-1',
    project_id: PROJECT_ID,
    package_number: 'HOP-001',
    title: 'Taking-over - Building A',
    completion_regime: 'taking_over',
    completion_type: 'whole',
    section_ref: null,
    status: 'draft',
    gating_state: 'blocked',
    open_ncr_count: 2,
    unreleased_hold_count: 1,
    completeness_pct: 50,
    gating_override_by: null,
    gating_override_reason: null,
    certificate_no: null,
    issued_at: null,
    issued_by: null,
    issue_signature_ip: null,
    issue_signature_sha256: null,
    closeout_package_id: null,
    dossier_key: null,
    dossier_built_at: null,
    assembled_at: null,
    approval_instance_id: null,
    created_by: null,
    metadata: {},
    created_at: '2026-06-23T00:00:00Z',
    updated_at: '2026-06-23T00:00:00Z',
    elements: [],
    ...overrides,
  };
}

function makeGate(overrides: Record<string, unknown> = {}) {
  return {
    package_id: 'ho-1',
    project_id: PROJECT_ID,
    gating_state: 'blocked',
    can_issue: false,
    open_ncr_count: 2,
    unreleased_hold_count: 1,
    completeness_pct: 50,
    blocking_gate_numbers: ['HLD-003'],
    ...overrides,
  };
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HandoverSection projectId={PROJECT_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('HandoverSection', () => {
  beforeEach(() => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    vi.clearAllMocks();
    (listHandoverPackages as AnyFn).mockResolvedValue([makePackage()]);
    (getHandoverGates as AnyFn).mockResolvedValue(makeGate());
  });

  it('shows the empty state when there are no packages', async () => {
    (listHandoverPackages as AnyFn).mockResolvedValue([]);
    renderSection();
    expect(await screen.findByText(/No handover packages yet/i)).toBeInTheDocument();
  });

  it('renders a package row and loads its completion gate', async () => {
    renderSection();
    await waitFor(() => expect(listHandoverPackages).toHaveBeenCalledWith(PROJECT_ID));

    // The master row renders (the package number also repeats in the detail panel).
    const row = await screen.findByTestId('cc-handover-row-ho-1');
    expect(row).toBeInTheDocument();
    expect(row.textContent).toMatch(/HOP-001/);
    expect(row.textContent).toMatch(/Taking-over - Building A/);

    // The selected-package detail loads the gate report.
    await waitFor(() => expect(getHandoverGates).toHaveBeenCalledWith('ho-1'));
    expect(await screen.findByText(/Blocked - clear or override the gate to issue/i)).toBeInTheDocument();
  });

  it('creates a package with the chosen completion regime', async () => {
    (createHandoverPackage as AnyFn).mockResolvedValue(makePackage({ id: 'ho-2', package_number: 'HOP-002' }));
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /New package/i }));

    const titleInput = await screen.findByLabelText(/Title/i);
    fireEvent.change(titleInput, { target: { value: 'Substantial completion - East wing' } });

    const regimeSelect = screen.getByLabelText(/Completion regime/i);
    fireEvent.change(regimeSelect, { target: { value: 'substantial' } });

    fireEvent.click(screen.getByRole('button', { name: /Create package/i }));

    await waitFor(() => expect(createHandoverPackage).toHaveBeenCalledTimes(1));
    // react-query's mutate appends a context arg, so assert on the payload (arg 0).
    const firstCall = (createHandoverPackage as AnyFn).mock.calls[0];
    expect(firstCall).toBeDefined();
    expect(firstCall?.[0]).toMatchObject({
      project_id: PROJECT_ID,
      title: 'Substantial completion - East wing',
      completion_regime: 'substantial',
      completion_type: 'whole',
    });
  });

  it('assembles the evidence manifest for the selected package', async () => {
    (assembleHandoverPackage as AnyFn).mockResolvedValue(makePackage({ status: 'assembling', completeness_pct: 75 }));
    renderSection();

    const assembleBtn = await screen.findByTestId('cc-handover-assemble');
    fireEvent.click(assembleBtn);

    await waitFor(() => expect(assembleHandoverPackage).toHaveBeenCalledWith('ho-1'));
  });

  it('disables issue while the gate is blocked', async () => {
    renderSection();
    const issueBtn = await screen.findByTestId('cc-handover-issue');
    expect(issueBtn).toBeDisabled();
  });

  it('issues the certificate when the gate is clear', async () => {
    (getHandoverGates as AnyFn).mockResolvedValue(
      makeGate({ gating_state: 'clear', can_issue: true, open_ncr_count: 0, unreleased_hold_count: 0, blocking_gate_numbers: [] }),
    );
    (issueHandoverCertificate as AnyFn).mockResolvedValue(
      makePackage({ status: 'issued', certificate_no: 'CERT-HOP-001' }),
    );
    renderSection();

    const issueBtn = await screen.findByTestId('cc-handover-issue');
    await waitFor(() => expect(issueBtn).not.toBeDisabled());
    fireEvent.click(issueBtn);

    // The issue modal opens; confirm signs and issues.
    fireEvent.click(await screen.findByRole('button', { name: /Sign and issue/i }));

    await waitFor(() => expect(issueHandoverCertificate).toHaveBeenCalledTimes(1));
    expect(issueHandoverCertificate).toHaveBeenCalledWith('ho-1', expect.any(Object));
  });
});
