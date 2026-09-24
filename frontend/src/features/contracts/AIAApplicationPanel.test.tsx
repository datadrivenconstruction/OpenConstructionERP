// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <AIAApplicationPanel>'s G703 continuation sheet.
//
// The row carrying money that no schedule of values line carries has no
// scheduled value, so the server sends column C, the percent and column H as
// null. The decision is that those print as empty cells: an empty cell says
// there is no answer, a zero says the answer is zero. What is pinned here is
// that null reaches the screen as nothing at all, in the desktop table and in
// the mobile cards, and never as 0, a dash, NaN or the word null, while the
// row's other figures and every schedule row still print.
//
// The i18n mock in src/test/setup.ts returns the defaultValue, so the English
// labels below are what renders here.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  getAiaApplication: vi.fn(),
  downloadAiaApplicationPdf: vi.fn(),
}));

import * as api from './api';
import { AIAApplicationPanel } from './AIAApplicationPanel';

const CLAIM_ID = '00000000-0000-0000-0000-0000000000a1';
const OUTSIDE_LABEL = 'Billed work not carried by any schedule of values line';

const getAiaMock = vi.mocked(api.getAiaApplication);

const SCHEDULE_ROW: api.AIAG703Line = {
  line_number: 1,
  item_number: 'A',
  description: 'Foundations',
  scheduled_value: '60000.00',
  previous_value: '24000.00',
  this_period_value: '12000.00',
  materials_stored: '0.00',
  total_completed_stored: '36000.00',
  percent_complete: '60.00',
  balance_to_finish: '24000.00',
  retainage: '3600.00',
};

const OUTSIDE_ROW: api.AIAG703Line = {
  line_number: 2,
  item_number: '',
  description: OUTSIDE_LABEL,
  scheduled_value: null,
  previous_value: '10000.00',
  this_period_value: '0.00',
  materials_stored: '0.00',
  total_completed_stored: '10000.00',
  percent_complete: null,
  balance_to_finish: null,
  retainage: '1000.00',
};

function application(): api.AIAApplication {
  return {
    claim_id: CLAIM_ID,
    contract_id: 'ctr-1',
    project_id: 'prj-1',
    application_number: '3',
    currency: 'USD',
    claim_status: 'draft',
    retainage_percent: '10.00',
    summary: {
      original_contract_sum: '60000.00',
      change_orders_net: '0.00',
      contract_sum_to_date: '60000.00',
      total_completed_stored: '46000.00',
      retainage: '4600.00',
      total_earned_less_retainage: '41400.00',
      previous_certificates_total: '30600.00',
      current_payment_due: '10800.00',
      balance_to_finish: '18600.00',
    },
    lines: [SCHEDULE_ROW, OUTSIDE_ROW],
    certification: {},
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AIAApplicationPanel claimId={CLAIM_ID} currency="USD" />
    </QueryClientProvider>,
  );
}

/** The desktop table's body rows, in the order the server sent them. */
async function tableRows() {
  const table = await screen.findByRole('table');
  return within(table).getAllByRole('row').slice(1);
}

/** The mobile card for a row, found by the description it prints. */
function card(description: string): HTMLElement {
  const paragraph = screen
    .getAllByText(description)
    .find((node) => node.tagName === 'P');
  if (!paragraph?.parentElement) throw new Error(`no mobile card for ${description}`);
  return paragraph.parentElement;
}

/** The value printed under a mobile card label. */
function cardValue(cardElement: HTMLElement, label: string): HTMLElement {
  const term = within(cardElement).getByText(label);
  const value = term.nextElementSibling;
  if (!(value instanceof HTMLElement)) throw new Error(`no value under ${label}`);
  return value;
}

// Column order on the desktop table: A item, B description, C scheduled,
// D previous, E this period, F stored, G total, percent, H balance, I retainage.
const C = 2;
const D = 3;
const G = 6;
const PCT = 7;
const H = 8;
const I = 9;

describe('AIAApplicationPanel continuation sheet', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    getAiaMock.mockResolvedValue(application());
  });

  it('leaves scheduled value, percent and balance empty on the row no schedule line carries', async () => {
    renderPanel();
    const [, outside] = await tableRows();
    const cells = within(outside!).getAllByRole('cell');

    expect(cells[1]).toHaveTextContent(OUTSIDE_LABEL);
    expect(cells[C]!.textContent).toBe('');
    expect(cells[PCT]!.textContent).toBe('');
    expect(cells[H]!.textContent).toBe('');
  });

  it('still prints the money that row does carry', async () => {
    renderPanel();
    const [, outside] = await tableRows();
    const cells = within(outside!).getAllByRole('cell');

    expect(cells[D]).toHaveTextContent('10,000.00');
    expect(cells[G]).toHaveTextContent('10,000.00');
    expect(cells[I]).toHaveTextContent('1,000.00');
    expect(outside!.textContent).not.toMatch(/NaN|null|undefined/);
  });

  it('prints every figure on a schedule row, as before', async () => {
    renderPanel();
    const [schedule] = await tableRows();
    const cells = within(schedule!).getAllByRole('cell');

    expect(cells[C]).toHaveTextContent('60,000.00');
    expect(cells[PCT]).toHaveTextContent('60.0%');
    expect(cells[H]).toHaveTextContent('24,000.00');
  });

  it('leaves the same three empty on the mobile card', async () => {
    renderPanel();
    await screen.findByRole('table');
    const outside = card(OUTSIDE_LABEL);

    const [, percent] = Array.from(outside.querySelectorAll('span'));
    expect(percent!.textContent).toBe('');
    expect(cardValue(outside, 'Scheduled').textContent).toBe('');
    expect(cardValue(outside, 'Balance').textContent).toBe('');
    expect(cardValue(outside, 'Total')).toHaveTextContent('10,000.00');
    expect(outside.textContent).not.toMatch(/NaN|null|undefined/);

    const schedule = card('Foundations');
    expect(cardValue(schedule, 'Scheduled')).toHaveTextContent('60,000.00');
    expect(cardValue(schedule, 'Balance')).toHaveTextContent('24,000.00');
  });
});
