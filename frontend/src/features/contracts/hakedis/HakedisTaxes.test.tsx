// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <HakedisTaxes>.
//
// What is worth pinning:
//
//   * nothing is chosen for the reader, and a contract default is a suggestion
//     that takes a click;
//   * each category shows what an accountant checks it by;
//   * the server is asked what the figures would be before anything is saved,
//     with the certificate's own amounts, and saving is a separate act;
//   * "does not apply" cannot be saved without its reason;
//   * a stale set says so and recalculates on an empty body;
//   * an amount entered by hand needs its reason, and shows who entered it;
//   * confirming is offered to a manager only, and rates that were never
//     checked against their source have to be acknowledged first;
//   * a confirmed set offers no choice, only reopening with a reason.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    putHakedisTaxes: vi.fn(),
    previewStatutoryTaxes: vi.fn(),
    listStatutoryCategories: vi.fn(),
    getStatutoryTaxes: vi.fn(),
    overrideStatutoryTax: vi.fn(),
    clearStatutoryTaxOverride: vi.fn(),
    confirmStatutoryTaxes: vi.fn(),
    reopenStatutoryTaxes: vi.fn(),
  };
});

let role: string | null = 'manager';
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel: (s: { userRole: string | null; userId: string | null }) => unknown) =>
    sel({ userRole: role, userId: 'user-1' }),
}));

import * as api from './api';
import type { HakedisDocument, HakedisSource, StatutoryCalc, StatutoryFigure, StatutoryInputs } from './api';
import { HakedisTaxes } from './HakedisTaxes';
import { certificate, taxes } from './__fixtures__/certificate';
import { ApiError } from '@/shared/lib/api';

const saveMock = vi.mocked(api.putHakedisTaxes);
const previewMock = vi.mocked(api.previewStatutoryTaxes);
const categoriesMock = vi.mocked(api.listStatutoryCategories);
const calcMock = vi.mocked(api.getStatutoryTaxes);
const overrideMock = vi.mocked(api.overrideStatutoryTax);
const confirmMock = vi.mocked(api.confirmStatutoryTaxes);
const reopenMock = vi.mocked(api.reopenStatutoryTaxes);

const CLAIM: HakedisSource = { kind: 'progress_claim', id: 'claim-1' };
const UNSET = { state: 'unset', code: '', reason: '' } as const;

function figure(over: Partial<StatutoryFigure> & { kind: string }): StatutoryFigure {
  return {
    status: 'value',
    amount: '80.00',
    base: '200.00',
    rate_pct: null,
    numerator: 4,
    denominator: 10,
    code: '601',
    currency_code: 'TRY',
    legal_reference: '',
    source_url: '',
    effective_from: '2024-01-01',
    effective_to: null,
    review_status: 'confirmed',
    overridden: false,
    reason_key: '',
    reason_params: {},
    choice_state: 'selected',
    choice_code: '601',
    choice_reason: '',
    override_amount: null,
    override_reason: '',
    overridden_by: null,
    overridden_at: null,
    ...over,
  };
}

function inputs(): StatutoryInputs {
  return {
    country_code: 'TR',
    currency_code: 'TRY',
    document_date: '2026-09-30',
    net_amount: '1000.00',
    vat_rate_pct: '20',
    buyer_is_designated: null,
    work_value_incl_vat: null,
    work_value_note: '',
    stamp_duty_base: '1000.00',
    stamp_duty_base_same_as_net: false,
    vat_withholding: { state: 'selected', code: '601', reason: '' },
    income_withholding: { ...UNSET },
    stamp_duty: { ...UNSET },
  };
}

function calc(over: Partial<StatutoryCalc> = {}): StatutoryCalc {
  return {
    id: 'calc-1',
    project_id: 'project-1',
    source_kind: 'progress_claim',
    source_id: 'claim-1',
    source_reference: 'PC-3',
    direction: 'issued',
    status: 'draft',
    inputs: inputs(),
    figures: [figure({ kind: 'vat_withheld' })],
    complete: true,
    uses_unconfirmed_rates: false,
    confirmed_by: null,
    confirmed_at: null,
    unconfirmed_rates_acknowledged_by: null,
    unconfirmed_rates_acknowledged_at: null,
    reopened_by: null,
    reopened_at: null,
    reopen_reason: '',
    voided_by: null,
    voided_at: null,
    void_reason: '',
    created_at: '2026-09-30T10:00:00Z',
    updated_at: '2026-09-30T10:00:00Z',
    findings: [],
    ...over,
  };
}

const STORED_DRAFT = taxes({
  stored: true,
  status: 'draft',
  choices: {
    vat_withholding: { state: 'selected', code: '601', reason: '' },
    income_withholding: { state: 'not_applicable', code: '', reason: 'Single year job' },
    stamp_duty: { state: 'selected', code: 'DV-HAKEDIS', reason: '' },
  },
});

const onUpdated = vi.fn<(doc: HakedisDocument) => void>();

function renderTaxes(doc: HakedisDocument, canEdit = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <HakedisTaxes
        source={CLAIM}
        doc={doc}
        locale="en"
        numberLocale="en-US"
        canEdit={canEdit}
        onUpdated={onUpdated}
      />
    </QueryClientProvider>,
  );
}

function radio(testId: string): HTMLInputElement {
  return screen.getByTestId(testId) as HTMLInputElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  role = 'manager';
  categoriesMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 500 });
  calcMock.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'not found' }));
  previewMock.mockResolvedValue({
    inputs: inputs(),
    figures: [
      figure({ kind: 'vat_withheld' }),
      figure({ kind: 'income_withheld', status: 'held', amount: null, base: null, reason_key: 'not_chosen' }),
    ],
    complete: false,
    uses_unconfirmed_rates: false,
    findings: [],
  });
});

describe('HakedisTaxes', () => {
  it('chooses nothing for the reader', () => {
    renderTaxes(certificate());
    for (const kind of ['vat_withholding', 'income_withholding', 'stamp_duty']) {
      expect(radio(`hakedis-tax-option-${kind}-unset`).checked).toBe(true);
      expect(radio(`hakedis-tax-option-${kind}-not_applicable`).checked).toBe(false);
    }
    expect(radio('hakedis-tax-option-vat_withholding-601').checked).toBe(false);
    expect(screen.getByTestId('hakedis-taxes-save')).toBeDisabled();
    expect(screen.getByTestId('hakedis-taxes-status')).toHaveTextContent('Taxes not decided');
    expect(previewMock).not.toHaveBeenCalled();
  });

  it('shows what each category is checked by', async () => {
    categoriesMock.mockResolvedValue({
      items: [
        {
          country_code: 'TR',
          kind: 'vat_withholding',
          code: '601',
          labels: { en: 'Construction works' },
          base: 'vat',
          rate_pct: null,
          numerator: 4,
          denominator: 10,
          threshold_amount: null,
          threshold_currency: '',
          threshold_scope: '',
          threshold_measure: '',
          cap_amount: null,
          buyer_scope: 'designated_only',
          work_value_threshold: null,
          conditions: {},
          effective_from: '2024-01-01',
          effective_to: null,
          legal_reference: 'VAT General Communique I/C-2.1.3.2.1',
          source_url: '',
          read_date: '2026-01-01',
          review_status: 'confirmed',
        },
      ],
      total: 1,
      offset: 0,
      limit: 500,
    });
    renderTaxes(certificate());
    const card = screen.getByTestId('hakedis-tax-vat_withholding');
    expect(card).toHaveTextContent('601');
    expect(card).toHaveTextContent('Construction works');
    expect(card).toHaveTextContent('4/10');
    expect(card).toHaveTextContent('Only a designated buyer withholds');
    expect(card).toHaveTextContent('Applies to designated buyers');
    expect(card).toHaveTextContent('VAT General Communique I/C-2.1.3.2.1');
    expect(card).toHaveTextContent('Rate checked against its source');
    await waitFor(() => expect(card).toHaveTextContent('In force from'));
    expect(categoriesMock).toHaveBeenCalledWith('TR', '2026-09-30');
    // A percent rate, and a rate nobody has checked yet.
    const income = screen.getByTestId('hakedis-tax-income_withholding');
    expect(income).toHaveTextContent('5%');
    expect(income).toHaveTextContent('Rate awaiting confirmation against its source');
  });

  it("offers the contract's default as a suggestion, not as a selection", () => {
    renderTaxes(
      certificate({
        taxes: taxes({ choices: { vat_withholding: { state: 'selected', code: '601', reason: '' } } }),
      }),
    );
    expect(screen.getByTestId('hakedis-tax-suggestion-vat_withholding')).toHaveTextContent(
      'The contract suggests category 601 Construction works. It is not saved for this certificate.',
    );
    expect(radio('hakedis-tax-option-vat_withholding-601').checked).toBe(false);
    fireEvent.click(screen.getByTestId('hakedis-tax-use-suggestion-vat_withholding'));
    expect(radio('hakedis-tax-option-vat_withholding-601').checked).toBe(true);
  });

  it('previews the figures from the server before anything is saved', async () => {
    renderTaxes(certificate());
    fireEvent.click(screen.getByTestId('hakedis-tax-option-vat_withholding-601'));
    await waitFor(() => expect(previewMock).toHaveBeenCalledTimes(1));
    expect(previewMock).toHaveBeenCalledWith(inputs());
    const preview = await screen.findByTestId('hakedis-tax-preview-vat_withholding');
    expect(preview).toHaveTextContent('If saved');
    expect(preview).toHaveTextContent(/80[.,]00/);
    expect(preview).toHaveTextContent('4/10');
    // A tax still undecided previews as held, with the reason.
    expect(await screen.findByTestId('hakedis-tax-preview-income_withholding')).toHaveTextContent('Held');
    expect(saveMock).not.toHaveBeenCalled();

    saveMock.mockResolvedValue(certificate({ taxes: STORED_DRAFT }));
    fireEvent.click(screen.getByTestId('hakedis-taxes-save'));
    await waitFor(() =>
      expect(saveMock).toHaveBeenCalledWith(
        CLAIM,
        {
          vat_withholding: { state: 'selected', code: '601', reason: '' },
          income_withholding: { ...UNSET },
          stamp_duty: { ...UNSET },
          buyer_is_designated: null,
          work_value_incl_vat: null,
          work_value_note: '',
        },
        'en',
      ),
    );
    await waitFor(() => expect(onUpdated).toHaveBeenCalledTimes(1));
  });

  it('sends the buyer facts with the preview', async () => {
    renderTaxes(certificate());
    fireEvent.change(screen.getByTestId('hakedis-taxes-buyer'), { target: { value: 'yes' } });
    fireEvent.change(screen.getByTestId('hakedis-taxes-work-value'), { target: { value: '6000000,00' } });
    await waitFor(() =>
      expect(previewMock).toHaveBeenLastCalledWith({
        ...inputs(),
        vat_withholding: { ...UNSET },
        buyer_is_designated: true,
        work_value_incl_vat: '6000000.00',
      }),
    );
  });

  it('does not save "does not apply" without its reason', async () => {
    renderTaxes(certificate());
    fireEvent.click(screen.getByTestId('hakedis-tax-option-stamp_duty-not_applicable'));
    expect(screen.getByTestId('hakedis-taxes-save')).toBeDisabled();
    expect(previewMock).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId('hakedis-tax-reason-stamp_duty'), {
      target: { value: 'Exempt under the contract' },
    });
    expect(screen.getByTestId('hakedis-taxes-save')).not.toBeDisabled();
    await waitFor(() =>
      expect(previewMock).toHaveBeenLastCalledWith({
        ...inputs(),
        vat_withholding: { ...UNSET },
        stamp_duty: { state: 'not_applicable', code: '', reason: 'Exempt under the contract' },
      }),
    );
  });

  it('says a stored set is stale and recalculates it on an empty body', async () => {
    saveMock.mockResolvedValue(certificate({ taxes: STORED_DRAFT }));
    renderTaxes(certificate({ taxes: { ...STORED_DRAFT, stale: true } }));
    const banner = screen.getByTestId('hakedis-taxes-stale');
    expect(banner).toHaveTextContent('Recalculate them on the current amounts');
    fireEvent.click(within(banner).getByTestId('hakedis-taxes-recalculate'));
    await waitFor(() => expect(saveMock).toHaveBeenCalledWith(CLAIM, {}, 'en'));
    // Nothing is confirmed or entered by hand on figures that are out of date.
    expect(screen.queryByTestId('hakedis-taxes-confirm')).toBeNull();
  });

  it('needs a reason for an amount entered by hand', async () => {
    calcMock.mockResolvedValue(calc());
    overrideMock.mockResolvedValue(calc());
    renderTaxes(certificate({ taxes: STORED_DRAFT }));
    fireEvent.click(await screen.findByTestId('hakedis-tax-override-vat_withholding'));
    fireEvent.change(screen.getByTestId('hakedis-tax-override-amount-vat_withholding'), {
      target: { value: '150,00' },
    });
    expect(screen.getByTestId('hakedis-tax-override-save-vat_withholding')).toBeDisabled();
    fireEvent.change(screen.getByTestId('hakedis-tax-override-reason-vat_withholding'), {
      target: { value: 'Agreed with the tax office' },
    });
    fireEvent.click(screen.getByTestId('hakedis-tax-override-save-vat_withholding'));
    await waitFor(() =>
      expect(overrideMock).toHaveBeenCalledWith(CLAIM, {
        project_id: 'project-1',
        kind: 'vat_withheld',
        amount: '150.00',
        reason: 'Agreed with the tax office',
      }),
    );
  });

  it('shows an amount entered by hand as such, with who entered it and why', async () => {
    calcMock.mockResolvedValue(
      calc({
        figures: [
          figure({
            kind: 'vat_withheld',
            amount: '150.00',
            overridden: true,
            override_amount: '150.00',
            override_reason: 'Agreed with the tax office',
            overridden_by: 'user-1',
            overridden_at: '2026-09-30T12:00:00Z',
          }),
          figure({
            kind: 'stamp_duty',
            amount: '9.00',
            overridden: true,
            override_reason: 'Rounded by the employer',
            overridden_by: 'user-2',
            overridden_at: '2026-09-30T12:00:00Z',
          }),
        ],
      }),
    );
    renderTaxes(certificate({ taxes: STORED_DRAFT }));
    const mine = await screen.findByTestId('hakedis-tax-overridden-vat_withholding');
    expect(mine).toHaveTextContent('Amount entered by hand by you');
    expect(mine).toHaveTextContent('Reason: Agreed with the tax office');
    expect(within(mine).getByTestId('hakedis-tax-clear-override-vat_withholding')).toBeInTheDocument();
    expect(screen.getByTestId('hakedis-tax-overridden-stamp_duty')).toHaveTextContent(
      'Amount entered by hand by a colleague',
    );
  });

  it('asks a manager to acknowledge unchecked rates before confirming', async () => {
    calcMock.mockResolvedValue(calc({ uses_unconfirmed_rates: true }));
    confirmMock.mockResolvedValue(calc({ status: 'confirmed' }));
    renderTaxes(certificate({ taxes: STORED_DRAFT }));
    const box = (await screen.findByTestId('hakedis-taxes-acknowledge')) as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(screen.getByTestId('hakedis-taxes-confirm-button')).toBeDisabled();
    fireEvent.click(box);
    fireEvent.click(screen.getByTestId('hakedis-taxes-confirm-button'));
    await waitFor(() =>
      expect(confirmMock).toHaveBeenCalledWith(CLAIM, {
        project_id: 'project-1',
        acknowledge_unconfirmed_rates: true,
      }),
    );
  });

  it('does not offer confirming below a manager', () => {
    role = 'editor';
    renderTaxes(certificate({ taxes: STORED_DRAFT }));
    expect(screen.getByTestId('hakedis-taxes-confirm')).toHaveTextContent('A manager has to confirm them');
    expect(screen.queryByTestId('hakedis-taxes-confirm-button')).toBeNull();
  });

  it('offers no choice on a confirmed set, only reopening with a reason', async () => {
    reopenMock.mockResolvedValue(calc());
    renderTaxes(certificate({ taxes: { ...STORED_DRAFT, status: 'confirmed' } }));
    expect(screen.getByTestId('hakedis-taxes-status')).toHaveTextContent('Taxes confirmed');
    expect(screen.queryByTestId('hakedis-taxes-save')).toBeNull();
    expect(screen.queryByTestId('hakedis-tax-option-vat_withholding-601')).toBeNull();
    expect(screen.getByTestId('hakedis-tax-stored-vat_withholding')).toHaveTextContent('Category 601');
    expect(screen.getByTestId('hakedis-tax-stored-income_withholding')).toHaveTextContent(
      'Does not apply: Single year job',
    );
    expect(screen.getByTestId('hakedis-taxes-reopen-button')).toBeDisabled();
    fireEvent.change(screen.getByTestId('hakedis-taxes-reopen-reason'), { target: { value: 'Wrong category' } });
    fireEvent.click(screen.getByTestId('hakedis-taxes-reopen-button'));
    await waitFor(() =>
      expect(reopenMock).toHaveBeenCalledWith(CLAIM, { project_id: 'project-1', reason: 'Wrong category' }),
    );
  });

  it("shows the server's refusal in the reader's words with its own beneath", async () => {
    saveMock.mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: {
          key: 'taxWithholding.statutory.error.statutory_changed',
          code: 'statutory_changed',
          message: 'Somebody else changed these tax lines.',
        },
      }),
    );
    renderTaxes(certificate({ taxes: { ...STORED_DRAFT, stale: true } }));
    fireEvent.click(screen.getByTestId('hakedis-taxes-recalculate'));
    expect(await screen.findByTestId('hakedis-taxes-refusal')).toHaveTextContent(
      'Somebody else changed these tax lines.',
    );
  });

  it('says the tax lines stay held when no tax module is installed', () => {
    renderTaxes(certificate({ taxes: taxes({ available: false, categories: {} }) }));
    expect(screen.getByTestId('hakedis-taxes')).toHaveTextContent('The tax module is not installed');
    expect(screen.queryByTestId('hakedis-taxes-save')).toBeNull();
  });
});
