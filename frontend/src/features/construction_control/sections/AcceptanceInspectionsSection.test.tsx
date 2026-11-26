// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for the Pillar 1 acceptance-criteria + inspections section (the
// reference-quality pillar that was missing a test).
//
// The API layer is stubbed via vi.mock('../api') so we can verify:
//   - the empty state renders when there are no inspections,
//   - an inspection row renders for the active project (with the resolved
//     criterion code) and the acceptance-criteria table lists its criteria,
//   - the load-error surface renders when the inspections query rejects,
//   - creating an inspection calls createInspection with the chosen payload,
//   - recording a PASS result calls recordInspectionResult with the outcome,
//   - recording a FAIL result that auto-raises an NCR surfaces the
//     NCR-raised warning toast (the failed-result -> NCR linkage).
//
// React Query runs with retry disabled so any error surfaces immediately.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

// Automock the whole feature-local API so every export is a vi.fn(). A partial
// factory mock here would bleed across the construction_control suite (the
// module path is shared with the sibling section tests) and strip exports those
// sections need, so every section test automocks '../api' consistently.
vi.mock('../api');

import {
  listCriteria,
  listInspections,
  createInspection,
  recordInspectionResult,
} from '../api';
import { AcceptanceInspectionsSection } from './AcceptanceInspectionsSection';

const PROJECT_ID = 'proj-1';

type AnyFn = ReturnType<typeof vi.fn>;

function makeCriterion(overrides: Record<string, unknown> = {}) {
  return {
    id: 'crit-1',
    project_id: PROJECT_ID,
    code: 'AC-001',
    title: 'Slab flatness',
    description: null,
    standard_ref: 'EN 13670',
    discipline: null,
    category: null,
    characteristic: null,
    method: null,
    unit: 'mm',
    acceptance_rule: 'range',
    nominal_value: null,
    tolerance_lower: '-5',
    tolerance_upper: '5',
    is_active: true,
    created_by: null,
    metadata: {},
    created_at: '2026-06-23T00:00:00Z',
    updated_at: '2026-06-23T00:00:00Z',
    ...overrides,
  };
}

function makeInspection(overrides: Record<string, unknown> = {}) {
  return {
    id: 'insp-1',
    project_id: PROJECT_ID,
    inspection_number: 'INS-001',
    inspection_type: 'wir',
    party_role: 'qc',
    intervention_point: null,
    title: 'Rebar inspection - Level 2 slab',
    description: null,
    location_description: 'Grid C4',
    activity_id: null,
    criterion_id: 'crit-1',
    status: 'draft',
    result: null,
    measured_value: null,
    result_notes: null,
    raised_ncr_id: null,
    scheduled_at: null,
    performed_at: null,
    performed_by: null,
    created_by: null,
    metadata: {},
    created_at: '2026-06-23T00:00:00Z',
    updated_at: '2026-06-23T00:00:00Z',
    elements: [],
    ...overrides,
  };
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AcceptanceInspectionsSection projectId={PROJECT_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AcceptanceInspectionsSection', () => {
  beforeEach(() => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    vi.clearAllMocks();
    // Toasts are stored in a zustand store (rendered elsewhere by a Toaster),
    // so reset the store between tests and assert on its state, not the DOM.
    useToastStore.setState({ toasts: [], history: [] });
    (listCriteria as AnyFn).mockResolvedValue([]);
    (listInspections as AnyFn).mockResolvedValue([]);
  });

  it('shows the empty state when there are no inspections', async () => {
    renderSection();
    await waitFor(() => expect(listInspections).toHaveBeenCalledWith(PROJECT_ID));
    expect(await screen.findByText(/No inspections yet/i)).toBeInTheDocument();
  });

  it('renders an inspection row and the resolved criterion code', async () => {
    (listCriteria as AnyFn).mockResolvedValue([makeCriterion()]);
    (listInspections as AnyFn).mockResolvedValue([makeInspection()]);
    renderSection();

    const row = await screen.findByTestId('cc-inspection-row-insp-1');
    expect(row).toBeInTheDocument();
    expect(row.textContent).toMatch(/INS-001/);
    expect(row.textContent).toMatch(/Rebar inspection - Level 2 slab/);

    // The inspection's criterion_id resolves to the criterion code in the row,
    // and the criterion also lists in the acceptance-criteria table below.
    expect(screen.getAllByText('AC-001').length).toBeGreaterThan(0);
    expect(screen.getByText('Slab flatness')).toBeInTheDocument();
  });

  it('renders the load-error surface when inspections fail to load', async () => {
    (listInspections as AnyFn).mockRejectedValue(new Error('boom'));
    renderSection();
    expect(await screen.findByText(/Could not load inspections/i)).toBeInTheDocument();
  });

  it('creates an inspection with the chosen payload', async () => {
    // Return one existing inspection so only the toolbar "New inspection"
    // button renders (the empty state would add a second one with that label).
    (listInspections as AnyFn).mockResolvedValue([makeInspection()]);
    (createInspection as AnyFn).mockResolvedValue(makeInspection({ id: 'insp-2' }));
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /New inspection/i }));

    const titleInput = await screen.findByLabelText(/Title/i);
    fireEvent.change(titleInput, { target: { value: 'Formwork check - East wing' } });

    fireEvent.click(screen.getByRole('button', { name: /Create inspection/i }));

    await waitFor(() => expect(createInspection).toHaveBeenCalledTimes(1));
    // react-query's mutate appends a context arg, so assert on the payload (arg 0).
    const firstCall = (createInspection as AnyFn).mock.calls[0];
    expect(firstCall).toBeDefined();
    expect(firstCall?.[0]).toMatchObject({
      project_id: PROJECT_ID,
      inspection_type: 'wir',
      party_role: 'qc',
      title: 'Formwork check - East wing',
    });
  });

  it('records a PASS result for an open inspection', async () => {
    (listInspections as AnyFn).mockResolvedValue([makeInspection()]);
    (recordInspectionResult as AnyFn).mockResolvedValue(
      makeInspection({ status: 'passed', result: 'pass' }),
    );
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /Record result/i }));

    // The record-result modal opens defaulting to a pass; save it.
    fireEvent.click(await screen.findByRole('button', { name: /Save result/i }));

    await waitFor(() => expect(recordInspectionResult).toHaveBeenCalledTimes(1));
    const [id, payload] = (recordInspectionResult as AnyFn).mock.calls[0]!;
    expect(id).toBe('insp-1');
    expect(payload).toMatchObject({ result: 'pass' });
  });

  it('records a FAIL result and surfaces the NCR-raised warning toast', async () => {
    (listInspections as AnyFn).mockResolvedValue([makeInspection()]);
    // A failed result returns the inspection with a raised NCR linked.
    (recordInspectionResult as AnyFn).mockResolvedValue(
      makeInspection({ status: 'failed', result: 'fail', raised_ncr_id: 'ncr-9' }),
    );
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /Record result/i }));

    // Pick the FAIL outcome, then save.
    fireEvent.click(await screen.findByTestId('cc-result-fail'));
    fireEvent.click(screen.getByRole('button', { name: /Save result/i }));

    await waitFor(() => expect(recordInspectionResult).toHaveBeenCalledTimes(1));
    const [, payload] = (recordInspectionResult as AnyFn).mock.calls[0]!;
    expect(payload).toMatchObject({ result: 'fail' });

    // The auto-raised NCR is surfaced to the user via a warning toast whose
    // title names the raised NCR (toasts live in the store, not the DOM here).
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      const ncrToast = toasts.find((toast) => /NCR raised/i.test(toast.title));
      expect(ncrToast).toBeDefined();
      expect(ncrToast?.type).toBe('warning');
    });
  });
});
