// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <MaterialsLabsSection /> - Pillar 2 (material records + lab tests).
//
// Coverage:
//   1. Render: the material-records list and lab-test list both render their
//      rows from the mocked api.
//   2. Create material: opening the "New material" form, filling the required
//      name and submitting calls createMaterial with the project id + name.
//   3. Create test result: opening the "New test result" form, filling the
//      required title and submitting calls createTestResult.
//   4. Review action (success path): recording a "Reject" decision calls
//      reviewMaterial and a toast is shown.
//
// The feature-local `../api` module is mocked so the test is deterministic and
// never touches the network (mirrors the approval-routes test idiom).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';

import { MaterialsLabsSection } from './MaterialsLabsSection';
import * as api from '../api';
import type { MaterialRecord, TestResult } from '../api';

/* ── Toast store mock ─────────────────────────────────────────────── */

const toastMocks = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToast }) => unknown) =>
      selector({ addToast: toastMocks.addToast }),
    { getState: () => ({ addToast: toastMocks.addToast }) },
  ),
}));

/* ── Feature-local API mock ───────────────────────────────────────── */

vi.mock('../api');

const PROJECT_ID = '11111111-1111-1111-1111-111111111111';

function material(overrides: Partial<MaterialRecord> = {}): MaterialRecord {
  return {
    id: 'mat-1',
    project_id: PROJECT_ID,
    record_number: 'MR-0001',
    name: 'Reinforcing steel B500B',
    material_type: null,
    spec_grade: 'EN 10080',
    manufacturer: 'Acme Steel',
    supplier: 'Supplier Co',
    supplier_id: null,
    product_code: null,
    cert_type: '3.1',
    cert_number: 'C-9001',
    cert_issuer: null,
    cert_document_id: null,
    dop_number: null,
    ce_marking: true,
    ukca_marking: false,
    issued_at: null,
    valid_from: null,
    valid_until: null,
    batch_number: 'B-77',
    heat_number: 'H-42',
    lot_number: null,
    quantity: null,
    unit: null,
    criterion_id: null,
    po_id: null,
    gr_id: null,
    gr_item_id: null,
    status: 'submitted',
    review_notes: null,
    raised_ncr_id: null,
    received_at: null,
    received_by: null,
    reviewed_at: null,
    reviewed_by: null,
    created_by: null,
    metadata: {},
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    is_expired: false,
    elements: [],
    ...overrides,
  };
}

function testResult(overrides: Partial<TestResult> = {}): TestResult {
  return {
    id: 'test-1',
    project_id: PROJECT_ID,
    result_number: 'TR-0001',
    title: 'Concrete cube compressive strength',
    description: null,
    material_record_id: null,
    inspection_id: null,
    criterion_id: null,
    sample_id: null,
    test_method: 'EN 12390-3',
    lab_name: 'City Materials Lab',
    lab_accreditation: 'UKAS 1234',
    is_accredited: true,
    measured_value: '32',
    unit: 'MPa',
    specimen_age_days: 28,
    status: 'draft',
    result: null,
    result_notes: null,
    raised_ncr_id: null,
    sampled_at: null,
    tested_at: null,
    performed_by: null,
    created_by: null,
    metadata: {},
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    elements: [],
    ...overrides,
  };
}

function renderSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MaterialsLabsSection projectId={PROJECT_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const mockedApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ userRole: 'admin' } as never);
  mockedApi.listMaterials.mockResolvedValue([material()]);
  mockedApi.listTestResults.mockResolvedValue([testResult()]);
  mockedApi.createMaterial.mockResolvedValue(material({ id: 'mat-new' }));
  mockedApi.reviewMaterial.mockResolvedValue(
    material({ status: 'rejected', raised_ncr_id: 'ncr-1' }),
  );
  mockedApi.createTestResult.mockResolvedValue(testResult({ id: 'test-new' }));
  mockedApi.recordTestResult.mockResolvedValue(
    testResult({ status: 'recorded', result: 'pass' }),
  );
});

describe('MaterialsLabsSection', () => {
  it('renders the material records and lab test results from the api', async () => {
    renderSection();

    expect(await screen.findByText('MR-0001')).toBeInTheDocument();
    expect(screen.getByText('Reinforcing steel B500B')).toBeInTheDocument();
    expect(await screen.findByText('TR-0001')).toBeInTheDocument();
    expect(screen.getByText('Concrete cube compressive strength')).toBeInTheDocument();

    expect(mockedApi.listMaterials).toHaveBeenCalledWith(PROJECT_ID);
    expect(mockedApi.listTestResults).toHaveBeenCalled();
  });

  it('creates a material record from the create form', async () => {
    renderSection();
    await screen.findByText('MR-0001');

    fireEvent.click(screen.getByRole('button', { name: /New material/i }));

    const dialog = await screen.findByRole('dialog');
    const nameInput = within(dialog).getByLabelText('Material');
    fireEvent.change(nameInput, { target: { value: 'Structural bolts M20' } });

    fireEvent.click(within(dialog).getByRole('button', { name: /Create material/i }));

    await waitFor(() => expect(mockedApi.createMaterial).toHaveBeenCalledTimes(1));
    // react-query passes a context object as the 2nd mutationFn arg, so assert
    // only on the payload (the first argument).
    expect(mockedApi.createMaterial.mock.calls[0]?.[0]).toMatchObject({
      project_id: PROJECT_ID,
      name: 'Structural bolts M20',
    });
  });

  it('creates a lab test result from the create form', async () => {
    renderSection();
    await screen.findByText('TR-0001');

    fireEvent.click(screen.getByRole('button', { name: /New test result/i }));

    const dialog = await screen.findByRole('dialog');
    const titleInput = within(dialog).getByLabelText('Title');
    fireEvent.change(titleInput, { target: { value: 'Slump test' } });

    fireEvent.click(within(dialog).getByRole('button', { name: /Create test result/i }));

    await waitFor(() => expect(mockedApi.createTestResult).toHaveBeenCalledTimes(1));
    expect(mockedApi.createTestResult.mock.calls[0]?.[0]).toMatchObject({
      project_id: PROJECT_ID,
      title: 'Slump test',
    });
  });

  it('records a material conformity decision (review) and toasts', async () => {
    renderSection();
    await screen.findByText('MR-0001');

    fireEvent.click(screen.getByRole('button', { name: /Review/i }));

    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByTestId('cc-decision-fail'));
    fireEvent.click(within(dialog).getByRole('button', { name: /Save decision/i }));

    await waitFor(() => expect(mockedApi.reviewMaterial).toHaveBeenCalledTimes(1));
    expect(mockedApi.reviewMaterial.mock.calls[0]?.[0]).toBe('mat-1');
    expect(mockedApi.reviewMaterial.mock.calls[0]?.[1]).toMatchObject({ decision: 'fail' });
    await waitFor(() => expect(toastMocks.addToast).toHaveBeenCalled());
  });
});
