// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <HakedisPanel>.
//
// What is worth pinning:
//
//   * a contract without a certificate layout shows nothing at all;
//   * each line state reads as itself: a value prints its amount, a held line
//     prints "Held" with its sentence and its control and never a zero or a
//     dash, a line that does not apply prints that with its reason;
//   * the strip at the top lists what a person has to do, leaves out a line
//     that only waits for another, and says "ready" only when the server does;
//   * a line entered by hand goes out as a decimal string, and what the server
//     refuses is shown at the field it refused;
//   * a draft says it is one and why;
//   * a certified certificate is frozen: no control is offered;
//   * the printed document is asked for in the language picked;
//   * a refused certification is shown on the certificate;
//   * the same panel serves a subcontractor payment application.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    getHakedis: vi.fn(),
    putHakedisLine: vi.fn(),
    putHakedisOptions: vi.fn(),
    putHakedisTaxes: vi.fn(),
    downloadHakedis: vi.fn(),
    previewStatutoryTaxes: vi.fn(),
    listStatutoryCategories: vi.fn(),
    getStatutoryTaxes: vi.fn(),
  };
});

let role: string | null = 'manager';
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel: (s: { userRole: string | null; userId: string | null }) => unknown) =>
    sel({ userRole: role, userId: 'user-1' }),
}));

import * as api from './api';
import type { HakedisSource } from './api';
import { HakedisPanel } from './HakedisPanel';
import { recordHakedisRefusal } from './hakedisQueries';
import { certificate, settledCertificate, taxes } from './__fixtures__/certificate';
import { ApiError } from '@/shared/lib/api';

const getMock = vi.mocked(api.getHakedis);
const lineMock = vi.mocked(api.putHakedisLine);
const downloadMock = vi.mocked(api.downloadHakedis);
const categoriesMock = vi.mocked(api.listStatutoryCategories);
const calcMock = vi.mocked(api.getStatutoryTaxes);

const CLAIM: HakedisSource = { kind: 'progress_claim', id: 'claim-1' };

function renderPanel(source: HakedisSource = CLAIM) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <HakedisPanel source={source} />
    </QueryClientProvider>,
  );
  return { qc, ...view };
}

beforeEach(() => {
  vi.clearAllMocks();
  role = 'manager';
  categoriesMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 500 });
  calcMock.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'not found' }));
});

describe('HakedisPanel', () => {
  it('renders nothing for a contract without a certificate layout', async () => {
    getMock.mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: { error: 'hakedis_not_available', message: 'No layout' } }),
    );
    const { container } = renderPanel();
    await waitFor(() => expect(getMock).toHaveBeenCalledWith(CLAIM, 'en'));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(screen.queryByTestId('hakedis-panel')).toBeNull();
    expect(screen.queryByTestId('hakedis-panel-error')).toBeNull();
  });

  it('says so when the certificate cannot be read for another reason', async () => {
    getMock.mockRejectedValue(
      new ApiError(400, 'Bad Request', {
        detail: { error: 'hakedis_configuration_invalid', message: "hakedis 'retention' has unknown key 'x'" },
      }),
    );
    renderPanel();
    const card = await screen.findByTestId('hakedis-panel-error');
    expect(card).toHaveTextContent("hakedis 'retention' has unknown key 'x'");
  });

  it('prints a value line with its amount, in the order and under the letters given', async () => {
    getMock.mockResolvedValue(certificate());
    renderPanel();
    const row = await screen.findByTestId('hakedis-line-work_done');
    expect(row).toHaveAttribute('data-status', 'value');
    expect(within(row).getByText('A')).toBeInTheDocument();
    expect(screen.getByTestId('hakedis-line-amount-work_done')).toHaveTextContent(/1[.,]000[.,]00/);
    const keys = screen
      .getAllByTestId(/^hakedis-line-(work_done|price_adjustment|total|vat_withholding|delay_penalty|payable)$/)
      .map((element) => element.getAttribute('data-testid'));
    expect(keys).toEqual([
      'hakedis-line-work_done',
      'hakedis-line-price_adjustment',
      'hakedis-line-total',
      'hakedis-line-vat_withholding',
      'hakedis-line-delay_penalty',
      'hakedis-line-payable',
    ]);
    // The deductions heading opens the block once, before its first line.
    expect(screen.getAllByTestId('hakedis-deductions-heading')).toHaveLength(1);
  });

  it('prints a held line as held, with its sentence and its control, never as a zero or a dash', async () => {
    const base = certificate();
    getMock.mockResolvedValue(
      certificate({
        findings: [
          ...base.findings,
          {
            rule_id: 'hakedis.percent_regressed',
            rule_name: 'Percent regressed',
            severity: 'warning',
            message: 'The adjustment is lower than on the previous certificate.',
            suggestion: null,
            element_ref: 'price_adjustment',
            details: {},
            engine_error: false,
          },
        ],
      }),
    );
    renderPanel();
    const amount = await screen.findByTestId('hakedis-line-amount-price_adjustment');
    expect(amount).toHaveTextContent('Held');
    expect(amount.textContent).not.toMatch(/\d/);
    expect(amount.textContent).not.toMatch(/[-–—]/);
    expect(screen.getByTestId('hakedis-line-reason-price_adjustment')).toHaveTextContent(
      'No amount has been entered.',
    );
    expect(screen.getByTestId('hakedis-line-edit-price_adjustment')).toHaveTextContent('Enter');
    // A held tax line leads to where the tax is decided.
    expect(screen.getByTestId('hakedis-line-tax-vat_withholding')).toHaveTextContent('Decide this tax');
    // A finding that names the line is shown on the line. The one that only
    // repeats "this line has no figure" is not: the line already says why.
    const onLine = screen.getAllByTestId('hakedis-line-finding-price_adjustment');
    expect(onLine).toHaveLength(1);
    expect(onLine[0]).toHaveTextContent('The adjustment is lower than on the previous certificate.');
    expect(screen.queryByText('Line B has no figure.')).toBeNull();
  });

  it('prints a line that does not apply as such, with the reason', async () => {
    getMock.mockResolvedValue(certificate());
    renderPanel();
    const amount = await screen.findByTestId('hakedis-line-amount-delay_penalty');
    expect(amount).toHaveTextContent('Not applicable');
    expect(amount.textContent).not.toMatch(/[-–—]/);
    expect(screen.getByTestId('hakedis-line-reason-delay_penalty')).toHaveTextContent('No delay on this contract');
  });

  it('lists what needs a person at the top and leaves out lines that only wait for another', async () => {
    getMock.mockResolvedValue(certificate());
    renderPanel();
    const strip = await screen.findByTestId('hakedis-attention');
    expect(strip).toHaveTextContent('Needs your attention');
    expect(within(strip).getByTestId('hakedis-attention-line-price_adjustment')).toHaveTextContent(
      'B) Price Adjustment: No amount has been entered.',
    );
    expect(within(strip).getByTestId('hakedis-attention-line-vat_withholding')).toBeInTheDocument();
    expect(within(strip).queryByTestId('hakedis-attention-line-total')).toBeNull();
    expect(within(strip).queryByTestId('hakedis-attention-line-payable')).toBeNull();
    expect(screen.queryByTestId('hakedis-ready')).toBeNull();
    // A warning is shown apart from what blocks.
    expect(screen.getByTestId('hakedis-findings-warnings')).toHaveTextContent(
      'The work value differs from the contract.',
    );
    expect(screen.queryByTestId('hakedis-findings-errors')).toBeNull();
  });

  it('lists the tax lines that share one reason about the stored set as one item', async () => {
    const base = certificate();
    const stale = { reason_key: 'taxes_stale', reason_text: ['The taxes were computed on another base.'] };
    getMock.mockResolvedValue(
      certificate({
        summary: [
          ...base.summary.map((line) => (line.key === 'vat_withholding' ? { ...line, ...stale } : line)),
          {
            ...(base.summary[3] as (typeof base.summary)[number]),
            key: 'stamp_duty',
            letter: 'b',
            tax_kind: 'stamp_duty',
            labels: ['Stamp Duty'],
            ...stale,
          },
        ],
        taxes: taxes({ stored: true, status: 'draft', stale: true }),
      }),
    );
    renderPanel();
    const strip = await screen.findByTestId('hakedis-attention');
    expect(within(strip).getAllByTestId('hakedis-attention-taxes')).toHaveLength(1);
    expect(within(strip).queryByTestId('hakedis-attention-line-stamp_duty')).toBeNull();
    expect(screen.getByTestId('hakedis-taxes-stale')).toBeInTheDocument();
  });

  it('says the certificate is ready only when nothing is missing and the server agrees', async () => {
    getMock.mockResolvedValue(settledCertificate());
    renderPanel();
    expect(await screen.findByTestId('hakedis-ready')).toHaveTextContent('ready to certify');
    expect(screen.queryByTestId('hakedis-draft-badge')).toBeNull();
  });

  it('marks a draft and lists why it is one', async () => {
    getMock.mockResolvedValue(certificate());
    renderPanel();
    expect(await screen.findByTestId('hakedis-draft-badge')).toHaveTextContent('Draft');
    const notes = screen.getByTestId('hakedis-notes');
    expect(notes).toHaveTextContent('Why the document prints as a draft');
    expect(within(notes).getAllByRole('listitem')).toHaveLength(2);
  });

  it('sends an entered amount as a decimal string and shows the refreshed certificate', async () => {
    getMock.mockResolvedValue(certificate());
    lineMock.mockResolvedValue(settledCertificate());
    renderPanel();
    fireEvent.click(await screen.findByTestId('hakedis-line-edit-price_adjustment'));
    fireEvent.change(screen.getByTestId('hakedis-line-amount-input'), { target: { value: '1250,50' } });
    fireEvent.click(screen.getByTestId('hakedis-line-save'));
    await waitFor(() =>
      expect(lineMock).toHaveBeenCalledWith(
        CLAIM,
        'price_adjustment',
        { state: 'value', amount: '1250.50', note: '' },
        'en',
      ),
    );
    expect(await screen.findByTestId('hakedis-ready')).toBeInTheDocument();
    expect(screen.queryByTestId('hakedis-line-editor-price_adjustment')).toBeNull();
  });

  it("shows the server's message at the field it refused", async () => {
    getMock.mockResolvedValue(certificate());
    lineMock.mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity', {
        detail: [{ loc: ['body', 'amount'], msg: 'Input should be a valid decimal', type: 'decimal_parsing' }],
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByTestId('hakedis-line-edit-price_adjustment'));
    fireEvent.change(screen.getByTestId('hakedis-line-amount-input'), { target: { value: 'abc' } });
    fireEvent.click(screen.getByTestId('hakedis-line-save'));
    const input = screen.getByTestId('hakedis-line-amount-input');
    await waitFor(() => expect(input).toHaveAttribute('aria-invalid', 'true'));
    expect(screen.getByText('Input should be a valid decimal')).toBeInTheDocument();
    // The editor stays open with what was typed.
    expect(input).toHaveValue('abc');
  });

  it('requires a reason to mark a line as not applicable, and shows a refusal that names no field', async () => {
    getMock.mockResolvedValue(certificate());
    lineMock.mockRejectedValue(
      new ApiError(422, 'Unprocessable Entity', {
        detail: { error: 'hakedis_line_entry_invalid', message: 'A line cannot be both an amount and a percent' },
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByTestId('hakedis-line-edit-price_adjustment'));
    fireEvent.click(screen.getByTestId('hakedis-line-mode-not_applicable'));
    expect(screen.getByTestId('hakedis-line-save')).toBeDisabled();
    fireEvent.change(screen.getByTestId('hakedis-line-note-input'), { target: { value: 'Fixed price contract' } });
    fireEvent.click(screen.getByTestId('hakedis-line-save'));
    await waitFor(() =>
      expect(lineMock).toHaveBeenCalledWith(
        CLAIM,
        'price_adjustment',
        { state: 'not_applicable', note: 'Fixed price contract' },
        'en',
      ),
    );
    expect(await screen.findByTestId('hakedis-line-refusal')).toHaveTextContent(
      'A line cannot be both an amount and a percent',
    );
  });

  it('offers no entry to a viewer', async () => {
    role = 'viewer';
    getMock.mockResolvedValue(certificate());
    renderPanel();
    await screen.findByTestId('hakedis-line-price_adjustment');
    expect(screen.queryByTestId('hakedis-line-edit-price_adjustment')).toBeNull();
    expect(screen.queryByTestId('hakedis-final-toggle')).toBeNull();
  });

  it('is read-only and says it is frozen once certified', async () => {
    getMock.mockResolvedValue(
      settledCertificate({
        status: 'certified',
        editable: false,
        frozen: true,
        frozen_at: '2026-10-01T09:30:00Z',
        can_certify: false,
        taxes: taxes({ stored: true, status: 'confirmed', categories: {} }),
      }),
    );
    const { qc } = renderPanel();
    expect(await screen.findByTestId('hakedis-frozen-badge')).toHaveTextContent('Frozen');
    // A refusal recorded before it was completed is not carried onto the frozen certificate.
    recordHakedisRefusal(
      qc,
      CLAIM,
      new ApiError(422, 'Unprocessable Entity', {
        detail: { error: 'hakedis_not_ready', message: 'The certificate is not ready', findings: [] },
      }),
    );
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('hakedis-certify-refusal')).toBeNull();
    expect(screen.getByTestId('hakedis-frozen-note')).toHaveTextContent('stored snapshot');
    expect(screen.queryByTestId('hakedis-attention')).toBeNull();
    expect(screen.queryByTestId('hakedis-final-toggle')).toBeNull();
    expect(screen.queryByTestId(/^hakedis-line-edit-/)).toBeNull();
    expect(screen.queryByTestId('hakedis-taxes-save')).toBeNull();
    expect(screen.queryByTestId(/^hakedis-tax-option-/)).toBeNull();
  });

  it('downloads the printed certificate in the language picked', async () => {
    getMock.mockResolvedValue(certificate());
    downloadMock.mockResolvedValue(undefined);
    renderPanel();
    fireEvent.click(await screen.findByTestId('hakedis-export-more'));
    fireEvent.click(await screen.findByTestId('hakedis-export-lang-tr-en'));
    fireEvent.click(screen.getByTestId('hakedis-export-item-xlsx'));
    await waitFor(() => expect(downloadMock).toHaveBeenCalledWith(CLAIM, 'xlsx', 'tr-en', 'hakedis-3'));
  });

  it('builds the document address from the source and the language', async () => {
    const actual = await vi.importActual<typeof import('./api')>('./api');
    const pdf = actual.hakedisDocumentUrl(CLAIM, 'pdf', 'tr-en');
    expect(pdf).toContain('/v1/contracts/progress-claims/claim-1/hakedis/pdf');
    expect(pdf).toContain('locale=tr-en');
    const sheet = actual.hakedisDocumentUrl({ kind: 'sub_payment_application', id: 'pa-9' }, 'xlsx', 'tr');
    expect(sheet).toContain('/v1/subcontractors/payment-applications/pa-9/hakedis/xlsx');
    expect(sheet).toContain('locale=tr');
  });

  it('shows a refused certification on the certificate', async () => {
    getMock.mockResolvedValue(certificate());
    const { qc } = renderPanel();
    await screen.findByTestId('hakedis-panel');
    const own = recordHakedisRefusal(
      qc,
      CLAIM,
      new ApiError(422, 'Unprocessable Entity', {
        detail: { error: 'hakedis_not_ready', message: 'The certificate is not ready', findings: [] },
      }),
    );
    expect(own).toBe(true);
    expect(await screen.findByTestId('hakedis-certify-refusal')).toHaveTextContent('The certificate is not ready');
    // Any other refusal is not the certificate's to show.
    expect(recordHakedisRefusal(qc, CLAIM, new ApiError(409, 'Conflict', { detail: 'Wrong status' }))).toBe(false);
    await waitFor(() => expect(screen.queryByTestId('hakedis-certify-refusal')).toBeNull());
  });

  it('serves a subcontractor payment application with the same panel', async () => {
    const source: HakedisSource = { kind: 'sub_payment_application', id: 'pa-9' };
    getMock.mockResolvedValue(certificate({ source_kind: 'sub_payment_application', source_id: 'pa-9' }));
    lineMock.mockResolvedValue(settledCertificate());
    renderPanel(source);
    const panel = await screen.findByTestId('hakedis-panel');
    expect(panel).toHaveAttribute('data-source-kind', 'sub_payment_application');
    expect(getMock).toHaveBeenCalledWith(source, 'en');
    fireEvent.click(screen.getByTestId('hakedis-line-edit-price_adjustment'));
    fireEvent.change(screen.getByTestId('hakedis-line-amount-input'), { target: { value: '10' } });
    fireEvent.click(screen.getByTestId('hakedis-line-save'));
    await waitFor(() =>
      expect(lineMock).toHaveBeenCalledWith(source, 'price_adjustment', { state: 'value', amount: '10', note: '' }, 'en'),
    );
  });
});
