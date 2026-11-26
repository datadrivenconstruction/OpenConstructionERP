// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the Pillar 3 as-built section:
//   * list render (records + tolerance + status badges),
//   * create-record submit (createAsBuilt is called with the form payload),
//   * a verify FSM action success path (verifyAsBuilt is called and the list
//     is refetched).
//
// The construction-control API module is fully stubbed so no network is hit.
// The global test setup (src/test/setup.ts) already mocks react-i18next (with
// defaultValue + {{var}} interpolation) and react-router-dom.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';

import { AsBuiltSection } from './AsBuiltSection';
import * as api from '../api';
import type { AsBuiltRecord, AcceptanceCriterion } from '../api';

vi.mock('../api');

const mockedApi = vi.mocked(api);

const PROJECT_ID = '11111111-1111-1111-1111-111111111111';

function makeRecord(overrides: Partial<AsBuiltRecord> = {}): AsBuiltRecord {
  return {
    id: 'rec-1',
    project_id: PROJECT_ID,
    record_number: 'AB-0001',
    title: 'Slab level survey - Level 2',
    discipline: 'Structural',
    location_description: 'Building A, Level 2',
    capture_method: 'total_station',
    instrument: null,
    instrument_calibration_ref: null,
    accuracy_class: 'standard',
    accuracy_value: null,
    accuracy_unit: null,
    coordinate_system: null,
    survey_date: null,
    surveyed_by: null,
    criterion_id: null,
    measured_value: null,
    deviation_value: null,
    tolerance_result: null,
    valid_for_legal_record: false,
    validity_signed_by: null,
    validity_signed_at: null,
    validity_signature_ip: null,
    validity_signature_sha256: null,
    source_kind: 'manual',
    source_ref: null,
    deviation_map_uri: null,
    status: 'draft',
    raised_ncr_id: null,
    created_by: null,
    metadata: {},
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    elements: [],
    ...overrides,
  };
}

function makeCriterion(overrides: Partial<AcceptanceCriterion> = {}): AcceptanceCriterion {
  return {
    id: 'crit-1',
    project_id: PROJECT_ID,
    code: 'TOL-01',
    title: 'Slab level tolerance',
    description: null,
    standard_ref: null,
    discipline: null,
    category: null,
    characteristic: null,
    method: null,
    unit: 'mm',
    acceptance_rule: 'range',
    nominal_value: '0',
    tolerance_lower: '-5',
    tolerance_upper: '5',
    is_active: true,
    created_by: null,
    metadata: {},
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    ...overrides,
  };
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AsBuiltSection projectId={PROJECT_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ userRole: 'admin' } as never);
  mockedApi.listAsBuilt.mockResolvedValue([]);
  mockedApi.listCriteria.mockResolvedValue([]);
});

describe('AsBuiltSection', () => {
  it('renders the records list with tolerance and status', async () => {
    mockedApi.listAsBuilt.mockResolvedValue([
      makeRecord({
        status: 'surveyed',
        measured_value: '3',
        tolerance_result: 'within',
      }),
    ]);

    renderSection();

    expect(await screen.findByText('Slab level survey - Level 2')).toBeInTheDocument();
    expect(screen.getByText('AB-0001')).toBeInTheDocument();
    // tolerance_result -> badge text "within"
    expect(screen.getByText('within')).toBeInTheDocument();
    // status -> badge text "surveyed"
    expect(screen.getByText('surveyed')).toBeInTheDocument();
    // a surveyed record exposes the Verify action
    expect(screen.getByRole('button', { name: 'Verify' })).toBeInTheDocument();
  });

  it('submits a new record (createAsBuilt called with the payload)', async () => {
    mockedApi.listCriteria.mockResolvedValue([makeCriterion()]);
    mockedApi.createAsBuilt.mockResolvedValue(makeRecord({ id: 'rec-new' }));

    renderSection();

    // Open the create modal from the toolbar.
    fireEvent.click(await screen.findByRole('button', { name: /New record/i }));

    const dialog = await screen.findByRole('dialog', { name: 'New record' });
    expect(dialog).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'New as-built record' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Create record' }));

    await waitFor(() => expect(mockedApi.createAsBuilt).toHaveBeenCalledTimes(1));
    // React Query passes a second mutate-context arg to the mutationFn, so
    // assert on the first argument (the payload) only.
    const createPayload = mockedApi.createAsBuilt.mock.calls[0]?.[0];
    expect(createPayload).toEqual(
      expect.objectContaining({
        project_id: PROJECT_ID,
        title: 'New as-built record',
        capture_method: 'total_station',
        accuracy_class: 'standard',
        source_kind: 'manual',
      }),
    );
  });

  it('verifies a surveyed record (verifyAsBuilt called, list refetched)', async () => {
    mockedApi.listAsBuilt
      .mockResolvedValueOnce([makeRecord({ status: 'surveyed', tolerance_result: 'within' })])
      .mockResolvedValue([makeRecord({ status: 'verified', tolerance_result: 'within' })]);
    mockedApi.verifyAsBuilt.mockResolvedValue(
      makeRecord({ status: 'verified', tolerance_result: 'within' }),
    );

    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: 'Verify' }));

    // The verify modal opens scoped to the record.
    const dialog = await screen.findByRole('dialog', { name: /Verify AB-0001/ });
    expect(dialog).toBeInTheDocument();

    // Confirm via the modal's primary Verify button (last match is in the footer).
    const verifyButtons = screen.getAllByRole('button', { name: 'Verify' });
    const confirmVerify = verifyButtons[verifyButtons.length - 1];
    expect(confirmVerify).toBeDefined();
    fireEvent.click(confirmVerify as HTMLElement);

    await waitFor(() => expect(mockedApi.verifyAsBuilt).toHaveBeenCalledTimes(1));
    expect(mockedApi.verifyAsBuilt).toHaveBeenCalledWith(
      'rec-1',
      expect.objectContaining({ ncr_severity: null }),
    );
    // The list query is invalidated -> a refetch happens.
    await waitFor(() => expect(mockedApi.listAsBuilt.mock.calls.length).toBeGreaterThan(1));
  });
});
