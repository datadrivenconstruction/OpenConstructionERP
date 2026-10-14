// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The plant register screens as a reader meets them: the register says where
// each lead time comes from, a blocked step lists every rule that blocks it,
// a refusal is shown in the server's words, a handover is sent only as the
// reader confirmed it, and the matrix and the gate check name their gaps.

import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('react-i18next', async () => (await import('./i18nMock')).i18nMockModule);
vi.mock('@/shared/ui/ProjectPeopleSelect', () => ({
  ProjectPeopleSelect: ({ placeholder }: { placeholder?: string }) => <input aria-label={placeholder} readOnly />,
}));
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    listQuotes: vi.fn(),
    listSlots: vi.fn(),
    listPapers: vi.fn(),
    listLimits: vi.fn(),
    listSpares: vi.fn(),
    transitionItem: vi.fn(),
    transitionSpare: vi.fn(),
    deleteSpare: vi.fn(),
    transitionSlot: vi.fn(),
    submitPaper: vi.fn(),
    withdrawPaper: vi.fn(),
    escalate: vi.fn(),
    handoverItem: vi.fn(),
    addQuote: vi.fn(),
    createItem: vi.fn(),
    updateItem: vi.fn(),
  };
});

import { useToastStore } from '@/stores/useToastStore';

import * as api from '../api';
import { DeliveryLimitsMatrix } from '../DeliveryLimitsMatrix';
import { FrameSummary } from '../FrameSummary';
import { ItemDialog } from '../ItemDialog';
import { QuoteDialog } from '../ItemDialogs';
import { ItemPanel } from '../ItemPanel';
import type { LabelContext } from '../labels';
import { LongLeadTimeline } from '../LongLeadTimeline';
import { PlantCanContext, Refusal, type PlantCan } from '../PlantBits';
import { RegisterTable } from '../RegisterTable';
import { TODAY, catalogue, frame, item, matrix, page, paper, quote, readiness, refusal, slot, spare } from './fixtures';
import { enT } from './i18nMock';

const mocked = vi.mocked(api);
const labels: LabelContext = { t: enT, language: 'en', exists: () => true };
const cat = catalogue();
const nobody = () => null;

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const ALLOWED = { allowed: true };

function panel(over: Parameters<typeof item>[0] = {}, onChanged = vi.fn(), can: PlantCan = { edit: ALLOWED, manage: ALLOWED }) {
  wrap(
    <PlantCanContext.Provider value={can}>
      <ItemPanel
        projectId="p1"
        item={item(over)}
        catalogue={cat}
        labels={labels}
        personName={nobody}
        onBack={() => undefined}
        onChanged={onChanged}
      />
    </PlantCanContext.Provider>,
  );
  return onChanged;
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.listQuotes.mockResolvedValue(page([]));
  mocked.listSlots.mockResolvedValue(page([]));
  mocked.listPapers.mockResolvedValue(page([]));
  mocked.listLimits.mockResolvedValue(page([]));
  mocked.listSpares.mockResolvedValue(page([]));
});
afterEach(cleanup);

describe('RegisterTable', () => {
  const items = [
    item(),
    item({
      id: 'i2',
      code: 'PL-007',
      title: 'Commercial kitchen equipment',
      component_class_code: 'kitchen_equipment',
      critical: false,
      long_lead: false,
      lead_source: 'catalogue_default',
      basis_enquiry_date: null,
      effective_lead_weeks: 16,
      float_days: 240,
      order_status: 'ok',
    }),
    item({ id: 'i3', code: 'PL-009', title: 'Unpriced item', lead_source: 'none', effective_lead_weeks: null, float_days: null, order_status: 'ok', critical: false, long_lead: false }),
  ];

  it('says where each lead time comes from: a dated quote, a catalogue default, or nothing', () => {
    wrap(<RegisterTable items={items} total={3} catalogue={cat} labels={labels} onOpen={() => undefined} />);
    const rows = screen.getAllByTestId('register-row');
    expect(rows).toHaveLength(3);
    const quoted = within(rows[0]!).getByTestId('lead-chip');
    expect(quoted).toHaveAttribute('data-lead', 'quote');
    expect(quoted).toHaveTextContent(/quoted 110 wk on .+ by Supplier quote/);
    const byDefault = within(rows[1]!).getByTestId('lead-chip');
    expect(byDefault).toHaveTextContent('16 wk');
    expect(byDefault).toHaveTextContent('catalogue default, not market evidence');
    expect(within(rows[2]!).getByTestId('lead-chip')).toHaveTextContent('No lead time');
  });

  it('marks an overdue order and a negative float, and names the kind of plant', () => {
    wrap(<RegisterTable items={items} total={3} catalogue={cat} labels={labels} onOpen={() => undefined} />);
    const first = screen.getAllByTestId('register-row')[0]!;
    expect(within(first).getByText('Order overdue')).toBeInTheDocument();
    expect(within(first).getByText('-59')).toBeInTheDocument();
    expect(within(first).getByText('Power transformer')).toBeInTheDocument();
    expect(within(first).getByText('Enquired')).toBeInTheDocument();
  });

  it('narrows to the overdue items and opens the one that is clicked', () => {
    const onOpen = vi.fn();
    wrap(<RegisterTable items={items} total={3} catalogue={cat} labels={labels} onOpen={onOpen} />);
    expect(screen.getByTestId('register-filter-overdue')).toHaveTextContent('Order overdue 1');
    fireEvent.click(screen.getByTestId('register-filter-overdue'));
    const rows = screen.getAllByTestId('register-row');
    expect(rows).toHaveLength(1);
    fireEvent.click(within(rows[0]!).getByText('PL-001'));
    expect(onOpen).toHaveBeenCalledWith('i1');
  });

  it('says so when the list was cut, and when a filter matches nothing', () => {
    wrap(<RegisterTable items={[items[1]!]} total={640} catalogue={cat} labels={labels} onOpen={() => undefined} />);
    expect(screen.getByRole('status')).toHaveTextContent('Showing the first 1 of 640 items.');
    fireEvent.click(screen.getByTestId('register-filter-critical'));
    expect(screen.getByTestId('register-none')).toHaveTextContent('No item matches this filter.');
  });

  it('flags a basis quote that is older than the class allows', () => {
    wrap(
      <RegisterTable
        items={[item({ quote_stale: true, quote_age_days: 140, quote_max_age_days: 90 })]}
        total={1}
        catalogue={cat}
        labels={labels}
        onOpen={() => undefined}
      />,
    );
    expect(screen.getByTestId('lead-chip')).toHaveTextContent('quote is 140 days old, 90 allowed');
  });
});

describe('Refusal', () => {
  it('shows the coded reason as a sentence and every blocking rule with the server detail', () => {
    render(
      <Refusal
        error={refusal(422, 'transition_blocked', 'The state change is blocked by several rules.', [
          { code: 'critical_without_decision', reason: 'paper is draft' },
          { code: 'delivery_limit_gap', reason: 'commission' },
        ])}
      />,
    );
    const box = screen.getByTestId('plant-refusal');
    expect(box).toHaveAttribute('data-code', 'transition_blocked');
    expect(box).toHaveTextContent('The state change is blocked by several rules.');
    const rules = within(box).getAllByRole('listitem');
    expect(rules).toHaveLength(2);
    expect(rules[0]).toHaveTextContent('A critical item needs an approved decision paper before its route is set.');
    expect(rules[0]).toHaveTextContent('paper is draft');
    expect(rules[1]).toHaveTextContent('Not every delivery step has a responsible party.');
  });

  it('tells a reader without the right who may change the register', () => {
    render(<Refusal error={refusal(403, 'not_equipment_owner', 'server text')} />);
    expect(screen.getByTestId('plant-refusal')).toHaveTextContent(
      'Only a manager or the owner of the equipment area may change the plant register.',
    );
  });

  it('shows the plain message of a failure that carries no code, and nothing when there is no failure', () => {
    const { rerender } = render(<Refusal error={new Error('Download failed (HTTP 502)')} />);
    expect(screen.getByTestId('plant-refusal')).toHaveTextContent('Download failed (HTTP 502)');
    rerender(<Refusal error={null} />);
    expect(screen.queryByTestId('plant-refusal')).toBeNull();
  });
});

describe('ItemPanel', () => {
  it('answers the first question at the top: need date, latest order date, float and where the lead time comes from', async () => {
    mocked.listQuotes.mockResolvedValue(page([quote({ id: 'q1', is_basis: false, source_name: 'Market sounding, three manufacturers' }), quote()]));
    panel();
    const dates = screen.getByTestId('item-dates');
    expect(within(dates).getByTestId('item-order-status')).toHaveTextContent('Order overdue');
    expect(within(dates).getByText('-59')).toBeInTheDocument();
    expect(within(dates).getByText('Fixed date')).toBeInTheDocument();
    expect(within(dates).getByTestId('lead-chip')).toHaveTextContent('quoted 110 wk');
    const rows = await screen.findAllByTestId('quote-row');
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent('96 to 110 wk');
    expect(rows[1]).toHaveTextContent('Dates planned on this');
    expect(within(rows[0]!).getByText('Plan on this')).toBeInTheDocument();
  });

  it('a blocked step stays where it is and lists every rule that blocks it', async () => {
    mocked.transitionItem.mockRejectedValue(
      refusal(422, 'transition_blocked', 'The state change is blocked by several rules.', [
        { code: 'route_missing' },
        { code: 'critical_without_decision' },
      ]),
    );
    const onChanged = panel();
    fireEvent.click(screen.getByTestId('item-next-step'));
    const box = await screen.findByTestId('plant-refusal');
    expect(mocked.transitionItem).toHaveBeenCalledWith('p1', 'i1', 'route_set');
    expect(within(box).getAllByRole('listitem')).toHaveLength(2);
    expect(box).toHaveTextContent('No procurement route is set.');
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('a step that goes through reloads the register', async () => {
    mocked.transitionItem.mockResolvedValue(item({ status: 'specified' }));
    const onChanged = panel({ status: 'identified' });
    expect(screen.getByTestId('item-next-step')).toHaveTextContent('Mark as specified');
    fireEvent.click(screen.getByTestId('item-next-step'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(mocked.transitionItem).toHaveBeenCalledWith('p1', 'i1', 'specified');
  });

  it('cancelling an item asks first', async () => {
    mocked.transitionItem.mockResolvedValue(item({ status: 'cancelled' }));
    panel();
    fireEvent.click(screen.getByTestId('item-cancel'));
    expect(mocked.transitionItem).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog')).toHaveTextContent('This cannot be undone.');
    fireEvent.click(screen.getByTestId('item-cancel-confirm'));
    await waitFor(() => expect(mocked.transitionItem).toHaveBeenCalledWith('p1', 'i1', 'cancelled'));
  });

  it('every section of a new item says what is missing and what to do first', async () => {
    panel({ needs_slot: true });
    expect(await screen.findByTestId('quotes-empty')).toHaveTextContent('No lead time asked yet.');
    expect(await screen.findByTestId('paper-empty')).toHaveTextContent('No decision paper.');
    expect(await screen.findByTestId('slot-empty')).toHaveTextContent('No production slot reserved.');
    expect(await screen.findByTestId('spares-empty')).toHaveTextContent('No spares listed for this item.');
    expect(screen.getByTestId('item-slot')).toHaveTextContent('reserve factory capacity before the order can be placed');
    expect(screen.getAllByTestId('limit-cell').every((cell) => cell.textContent?.includes('Nobody yet'))).toBe(true);
  });

  it('a section that is still loading shows that, not an empty state, and offers no write yet', () => {
    mocked.listSlots.mockReturnValue(new Promise(() => undefined));
    mocked.listPapers.mockReturnValue(new Promise(() => undefined));
    panel({ needs_slot: true });
    expect(screen.getByTestId('slot-loading')).toBeInTheDocument();
    expect(screen.getByTestId('paper-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('slot-empty')).toBeNull();
    expect(screen.queryByTestId('paper-empty')).toBeNull();
    expect(screen.queryByText('Reserve slot')).toBeNull();
    expect(screen.queryByText('Write decision paper')).toBeNull();
  });

  it('a section that failed to load shows the reason, not an empty state', async () => {
    mocked.listQuotes.mockRejectedValue(refusal(404, 'item_not_found', 'Plant item not found.'));
    panel();
    const box = await within(screen.getByTestId('item-quotes')).findByTestId('plant-refusal');
    expect(box).toHaveTextContent('Plant item not found.');
    expect(screen.queryByTestId('quotes-empty')).toBeNull();
  });

  it('a closed item offers no step, no edit and no new lead time', () => {
    panel({ status: 'handed_over' });
    expect(screen.queryByTestId('item-next-step')).toBeNull();
    expect(screen.queryByTestId('item-cancel')).toBeNull();
    expect(screen.queryByText('Add lead time')).toBeNull();
    expect(screen.queryByTestId('item-set-route')).toBeNull();
  });

  it('says plainly that no route is set, and names the steps nobody carries', () => {
    panel();
    expect(screen.getByTestId('item-route-value')).toHaveTextContent('No route yet. Nobody is named to buy this item.');
    const limits = screen.getByTestId('item-limits');
    expect(limits).toHaveTextContent('Nobody is named for: Commission');
    const cells = within(limits).getAllByTestId('limit-cell');
    expect(cells).toHaveLength(3);
    expect(cells[2]).toHaveAttribute('data-gap', 'true');
    expect(cells[0]).not.toHaveAttribute('data-gap');
  });

  it('shows the reservation fee with its cents and the terms it was agreed on', async () => {
    mocked.listSlots.mockResolvedValue(page([slot()]));
    panel();
    const fee = await screen.findByTestId('slot-fee');
    expect(fee.textContent).toMatch(/12[.,\s\u00a0\u202f]?500[.,]50/);
    const section = screen.getByTestId('item-slot');
    expect(within(section).getByTestId('slot-state')).toHaveTextContent('Requested');
    expect(section).toHaveTextContent('Partly refundable');
    expect(section).toHaveTextContent('Credited to the order');
  });

  it('holding a slot with incomplete terms shows why beside the slot', async () => {
    mocked.listSlots.mockResolvedValue(page([slot({ reservation_fee: null, convert_by_date: null })]));
    mocked.transitionSlot.mockRejectedValue(
      refusal(422, 'slot_terms_incomplete', 'A held reservation needs fee, refund terms and the conversion deadline.'),
    );
    panel();
    fireEvent.click(await screen.findByTestId('slot-hold'));
    const box = await within(screen.getByTestId('item-slot')).findByTestId('plant-refusal');
    expect(box).toHaveTextContent('A held reservation needs fee, refund terms and the conversion deadline.');
    expect(mocked.transitionSlot).toHaveBeenCalledWith('p1', 'i1', 's1', 'held');
  });

  it('shows the decision paper with its recommended option and submits the draft', async () => {
    mocked.listPapers.mockResolvedValue(page([paper()]));
    mocked.submitPaper.mockRejectedValue(refusal(422, 'no_decision_route', 'The project has no approval route for decision papers.'));
    panel();
    const options = await screen.findAllByTestId('paper-option');
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent('Recommended');
    expect(options[0]).toHaveTextContent('40 wk');
    expect(options[1]).not.toHaveTextContent('Recommended');
    expect(screen.getByTestId('paper-state')).toHaveTextContent('Draft');
    fireEvent.click(screen.getByTestId('paper-submit'));
    const box = await within(screen.getByTestId('item-paper')).findByTestId('plant-refusal');
    expect(box).toHaveTextContent('The project has no approval route for decision papers.');
  });

  it('a submitted paper can be taken back to draft', async () => {
    mocked.listPapers.mockResolvedValue(page([paper({ status: 'submitted' })]));
    mocked.withdrawPaper.mockResolvedValue(paper({ status: 'draft' }));
    const onChanged = panel();
    fireEvent.click(await screen.findByTestId('paper-withdraw'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(mocked.withdrawPaper).toHaveBeenCalledWith('p1', 'i1', 'pp1');
    expect(screen.queryByTestId('paper-submit')).toBeNull();
  });

  it('a reader the server does not let edit sees every write switched off with the reason', async () => {
    mocked.listPapers.mockResolvedValue(page([paper()]));
    panel({}, vi.fn(), {
      edit: { allowed: false, reason: 'not_equipment_owner' },
      manage: { allowed: false, reason: 'manage_required' },
    });
    const why = 'Only a manager or the owner of the equipment area may change the plant register.';
    for (const button of [await screen.findByTestId('paper-submit'), screen.getByTestId('item-cancel'), screen.getByTestId('item-set-route')]) {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute('title', why);
    }
    // Reading stays open: the way back and the paper as a document.
    expect(screen.getByText('Back to the register').closest('button')).toBeEnabled();
    expect(screen.getByText('PDF').closest('button')).toBeEnabled();
  });

  it('an approved paper can no longer be edited or submitted', async () => {
    mocked.listPapers.mockResolvedValue(page([paper({ status: 'approved' })]));
    panel();
    expect(await screen.findByTestId('paper-state')).toHaveTextContent('Approved');
    expect(screen.queryByTestId('paper-submit')).toBeNull();
    expect(screen.queryByText('Write decision paper')).toBeNull();
  });

  it('deleting a spare asks first and sends nothing until the reader confirms', async () => {
    mocked.listSpares.mockResolvedValue(page([spare()]));
    mocked.deleteSpare.mockResolvedValue(undefined);
    const onChanged = panel();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete the spare' }));
    expect(await screen.findByText('Delete this spare?')).toBeInTheDocument();
    expect(mocked.deleteSpare).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(mocked.deleteSpare).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete the spare' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(mocked.deleteSpare).toHaveBeenCalledWith('p1', 'i1', 'sp1'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('waiving a spare sends the reason the reader wrote', async () => {
    mocked.listSpares.mockResolvedValue(page([spare()]));
    mocked.transitionSpare.mockResolvedValue(spare({ status: 'waived' }));
    const onChanged = panel();
    fireEvent.click(await screen.findByTestId('spare-waive'));
    fireEvent.change(screen.getByTestId('spare-waiver-reason'), { target: { value: '  Held centrally for the estate  ' } });
    fireEvent.click(screen.getByTestId('spare-waive-send'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(mocked.transitionSpare).toHaveBeenCalledWith('p1', 'i1', 'sp1', 'waived', 'Held centrally for the estate');
  });

  it('a waiver without a reason is refused by the server and the box stays open', async () => {
    mocked.listSpares.mockResolvedValue(page([spare()]));
    mocked.transitionSpare.mockRejectedValue(refusal(422, 'waiver_needs_reason', 'Waiving a spare part needs a reason.'));
    panel();
    fireEvent.click(await screen.findByTestId('spare-waive'));
    fireEvent.click(screen.getByTestId('spare-waive-send'));
    const box = await within(screen.getByTestId('item-spares')).findByTestId('plant-refusal');
    expect(box).toHaveTextContent('Waiving a spare part needs a reason.');
    expect(screen.getByTestId('spare-waiver-reason')).toBeInTheDocument();
  });

  it('handover is sent exactly as confirmed, with the reason the item has no service contract', async () => {
    mocked.handoverItem.mockRejectedValueOnce(refusal(422, 'handover_needs_confirmation', 'Handover must be confirmed.'));
    mocked.handoverItem.mockResolvedValueOnce(item({ status: 'handed_over' }));
    const onChanged = panel({ status: 'commissioned' });
    fireEvent.click(screen.getByTestId('item-handover'));
    const dialog = await screen.findByTestId('plant-handover-dialog');
    fireEvent.click(within(dialog).getByTestId('dialog-submit'));
    expect(within(dialog).getByTestId('dialog-problems')).toHaveTextContent(
      'Write down why the item is handed over without a service contract.',
    );
    expect(mocked.handoverItem).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByTestId('handover-reason'), { target: { value: ' Serviced by the estate team ' } });
    fireEvent.click(within(dialog).getByTestId('dialog-submit'));
    expect(await within(dialog).findByTestId('plant-refusal')).toHaveTextContent('Handover must be confirmed.');
    expect(mocked.handoverItem).toHaveBeenLastCalledWith('p1', 'i1', false, 'Serviced by the estate team');
    fireEvent.click(within(dialog).getByTestId('handover-confirm'));
    fireEvent.click(within(dialog).getByTestId('dialog-submit'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(mocked.handoverItem).toHaveBeenLastCalledWith('p1', 'i1', true, 'Serviced by the estate team');
  });

  it('a handover blocked by several rules lists each of them', async () => {
    mocked.handoverItem.mockRejectedValue(
      refusal(422, 'transition_blocked', 'The state change is blocked by several rules.', [
        { code: 'spares_not_handed_over' },
        { code: 'critical_without_strategic_spares' },
      ]),
    );
    panel({ status: 'commissioned' });
    fireEvent.click(screen.getByTestId('item-handover'));
    const dialog = await screen.findByTestId('plant-handover-dialog');
    fireEvent.change(within(dialog).getByTestId('handover-reason'), { target: { value: 'No contract yet' } });
    fireEvent.click(within(dialog).getByTestId('dialog-submit'));
    const box = await within(dialog).findByTestId('plant-refusal');
    expect(box).toHaveTextContent('Every spare part must be handed over or waived first.');
    expect(box).toHaveTextContent('A critical item needs a strategic spare or a stated reason why not.');
  });

  it('handover is not offered before commissioning', () => {
    panel({ status: 'installed' });
    expect(screen.queryByTestId('item-handover')).toBeNull();
  });
});

describe('dialogs', () => {
  it('a new item is not sent until it has a code, a title and a kind of plant', () => {
    wrap(
      <ItemDialog open onClose={() => undefined} projectId="p1" item={null} catalogue={cat} labels={labels} personName={nobody} onSaved={() => undefined} />,
    );
    expect(screen.queryByTestId('dialog-problems')).toBeNull();
    fireEvent.click(screen.getByTestId('dialog-submit'));
    const problems = within(screen.getByTestId('dialog-problems')).getAllByRole('listitem');
    expect(problems.map((p) => p.getAttribute('data-problem'))).toEqual(['code_required', 'title_required', 'class_required']);
    expect(mocked.createItem).not.toHaveBeenCalled();
  });

  it('a new item is sent with decimals as strings, and a taken code is explained in place', async () => {
    mocked.createItem.mockRejectedValue(refusal(409, 'item_code_taken', 'An item with this code already exists in the project.'));
    wrap(
      <ItemDialog open onClose={() => undefined} projectId="p1" item={null} catalogue={cat} labels={labels} personName={nobody} onSaved={() => undefined} />,
    );
    fireEvent.change(screen.getByLabelText(/^Code/), { target: { value: 'PL-001' } });
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: 'Second transformer' } });
    fireEvent.change(screen.getByLabelText(/^Kind of plant/), { target: { value: 'power_transformer' } });
    fireEvent.change(screen.getByLabelText(/^Quantity/), { target: { value: '2' } });
    fireEvent.click(screen.getByTestId('dialog-submit'));
    expect(await screen.findByTestId('plant-refusal')).toHaveTextContent('An item with this code already exists in the project.');
    expect(mocked.createItem).toHaveBeenCalledWith('p1', {
      code: 'PL-001',
      title: 'Second transformer',
      component_class_code: 'power_transformer',
      quantity: '2',
      vendor_policy: 'neutral',
    });
  });

  it('the critical and long-lead overrides are closed to a reader without the manage capability', () => {
    wrap(
      <PlantCanContext.Provider value={{ edit: ALLOWED, manage: { allowed: false, reason: 'manage_required' } }}>
        <ItemDialog open onClose={() => undefined} projectId="p1" item={null} catalogue={cat} labels={labels} personName={nobody} onSaved={() => undefined} />
      </PlantCanContext.Provider>,
    );
    expect(screen.getByTestId('item-critical-override')).toBeDisabled();
    expect(screen.getByTestId('item-long-lead-override')).toBeDisabled();
    expect(screen.getAllByText('Only a holder of the plant management permission may change this.')).toHaveLength(2);
  });

  it('the overrides are frozen once the route is set, and open before', () => {
    const frozen = wrap(
      <ItemDialog open onClose={() => undefined} projectId="p1" item={item({ status: 'route_set' })} catalogue={cat} labels={labels} personName={nobody} onSaved={() => undefined} />,
    );
    expect(screen.getByTestId('item-critical-override')).toBeDisabled();
    expect(screen.getAllByText('Critical and long-lead overrides are frozen once the procurement route is set.')).toHaveLength(2);
    frozen.unmount();
    wrap(
      <ItemDialog open onClose={() => undefined} projectId="p1" item={item({ status: 'enquired' })} catalogue={cat} labels={labels} personName={nobody} onSaved={() => undefined} />,
    );
    expect(screen.getByTestId('item-critical-override')).toBeEnabled();
  });

  it('an edit sends only the field that changed', async () => {
    const original = item();
    mocked.updateItem.mockResolvedValue(original);
    const onSaved = vi.fn();
    wrap(
      <ItemDialog open onClose={() => undefined} projectId="p1" item={original} catalogue={cat} labels={labels} personName={nobody} onSaved={onSaved} />,
    );
    expect(screen.getByLabelText(/^Code/)).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Location/), { target: { value: 'Substation, level -1' } });
    fireEvent.click(screen.getByTestId('dialog-submit'));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(mocked.updateItem).toHaveBeenCalledWith('p1', 'i1', { space_ref: 'Substation, level -1' });
  });

  it('a lead time is not sent without the date it was asked', async () => {
    mocked.addQuote.mockResolvedValue(quote());
    const onSaved = vi.fn();
    wrap(<QuoteDialog open onClose={() => undefined} projectId="p1" item={item()} catalogue={cat} labels={labels} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/^Source/), { target: { value: 'supplier_quote' } });
    fireEvent.change(screen.getByLabelText(/^Shortest lead time/), { target: { value: '96' } });
    fireEvent.click(screen.getByTestId('dialog-submit'));
    expect(within(screen.getByTestId('dialog-problems')).getByRole('listitem')).toHaveTextContent(
      'A lead time needs the date it was enquired.',
    );
    expect(mocked.addQuote).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/^Enquiry date/), { target: { value: '2026-01-15' } });
    fireEvent.click(screen.getByTestId('dialog-submit'));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(mocked.addQuote).toHaveBeenCalledWith(
      'p1',
      'i1',
      expect.objectContaining({ source: 'supplier_quote', enquiry_date: '2026-01-15', lead_weeks_min: 96, lead_weeks_max: 96, set_basis: true }),
    );
  });
});

describe('DeliveryLimitsMatrix', () => {
  it('shows who carries each step and marks the step nobody carries', () => {
    render(<DeliveryLimitsMatrix matrix={matrix()} catalogue={cat} labels={labels} onOpen={() => undefined} />);
    const cells = within(screen.getByTestId('limit-matrix-row')).getAllByTestId('limit-matrix-cell');
    expect(cells.map((c) => c.textContent)).toEqual(['Supplier', 'Contractor', 'Open']);
    expect(cells[2]).toHaveAttribute('data-gap', 'true');
    expect(screen.getByText('Commission')).toBeInTheDocument();
  });

  it('explains what the matrix is for when there is nothing to show', () => {
    render(<DeliveryLimitsMatrix matrix={matrix({ rows: [] })} catalogue={cat} labels={labels} onOpen={() => undefined} />);
    expect(screen.getByText('No delivery limits yet')).toBeInTheDocument();
  });
});

describe('LongLeadTimeline', () => {
  it('draws a bar per long-lead item and says when one cannot be dated', () => {
    render(
      <LongLeadTimeline
        items={[
          item({ float_days: 12, order_status: 'due_soon', latest_order_date: '2026-10-24', need_date: '2028-11-10' }),
          item({ id: 'i2', code: 'PL-002', float_days: null, latest_order_date: null, need_date: null, date_basis: 'none' }),
          item({ id: 'i3', code: 'PL-007', long_lead: false }),
        ]}
        catalogue={cat}
        labels={labels}
        today={TODAY}
        onOpen={() => undefined}
      />,
    );
    const rows = screen.getAllByTestId('timeline-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByTestId('timeline-bar')).toBeInTheDocument();
    expect(rows[0]).toHaveTextContent('Order soon');
    expect(rows[0]).toHaveTextContent('Float 12 days');
    expect(within(rows[1]!).queryByTestId('timeline-bar')).toBeNull();
    expect(rows[1]).toHaveTextContent('No need date yet, so no order date can be worked out.');
  });

  it('says what makes an item long-lead when none is', () => {
    render(<LongLeadTimeline items={[item({ long_lead: false })]} catalogue={cat} labels={labels} today={TODAY} onOpen={() => undefined} />);
    expect(screen.getByText('No long-lead items')).toBeInTheDocument();
    expect(screen.getByText(/once its lead time reaches 12 weeks/)).toBeInTheDocument();
  });
});

describe('FrameSummary', () => {
  it('lists exactly what the gate still misses', () => {
    wrap(
      <FrameSummary
        projectId="p1"
        summary={frame()}
        readiness={readiness()}
        findings={[
          { rule_id: 'plant.basis', passed: false, severity: 'error', message: 'PL-003 has no basis lead time.', element_ref: 'PL-003', suggestion: null },
          { rule_id: 'plant.ok', passed: true, severity: 'error', message: 'fine', element_ref: null, suggestion: null },
        ]}
        catalogue={cat}
        labels={labels}
      />,
    );
    const open = within(screen.getByTestId('readiness-open')).getAllByRole('listitem');
    expect(open.map((li) => li.getAttribute('data-open'))).toEqual(['critical', 'long_lead', 'frame']);
    expect(open[0]).toHaveTextContent('PL-001');
    expect(open[0]).toHaveTextContent('PL-002');
    const findings = screen.getAllByTestId('finding-row');
    expect(findings).toHaveLength(1);
    expect(findings[0]).toHaveTextContent('Must fix');
    expect(findings[0]).toHaveTextContent('PL-003 has no basis lead time.');
    expect(screen.getAllByTestId('frame-tile').map((tile) => tile.textContent)).toEqual([
      'Items8',
      'Critical3',
      'Long-lead5',
      'Order overdue1',
    ]);
    expect(screen.getByText('No route yet')).toBeInTheDocument();
    expect(screen.getAllByTestId('export-row')).toHaveLength(4);
  });

  it('sending reminders reports the orders due soon as well as the overdue ones', async () => {
    mocked.escalate.mockResolvedValue({ overdue: ['PL-001'], due_soon: ['PL-002', 'PL-003'], expired_slots: [] });
    wrap(<FrameSummary projectId="p1" summary={frame()} readiness={readiness()} findings={[]} catalogue={cat} labels={labels} />);
    fireEvent.click(screen.getByTestId('frame-remind'));
    await waitFor(() => expect(mocked.escalate).toHaveBeenCalledWith('p1'));
    await waitFor(() =>
      expect(useToastStore.getState().toasts.map((toast) => toast.title)).toContain(
        'Reminders sent. Overdue orders: 1. Orders due soon: 2. Expired slots: 0.',
      ),
    );
  });

  it('on a project without gates it names no gate and does not list the frame document as missing', () => {
    wrap(
      <FrameSummary
        projectId="p1"
        summary={frame()}
        readiness={readiness({ gates_in_use: false, frame_document_attached: false })}
        findings={[]}
        catalogue={cat}
        labels={labels}
      />,
    );
    const panel = screen.getByTestId('frame-readiness');
    expect(panel).toHaveTextContent('This project does not use gates.');
    expect(panel).not.toHaveTextContent('gate to execution');
    const open = within(screen.getByTestId('readiness-open')).getAllByRole('listitem');
    expect(open.map((li) => li.getAttribute('data-open'))).toEqual(['critical', 'long_lead']);
  });

  it('on a project without gates a complete register says so without naming a gate', () => {
    wrap(
      <FrameSummary
        projectId="p1"
        summary={frame()}
        readiness={readiness({ gates_in_use: false, ready: true, critical_open: [], long_lead_open: [] })}
        findings={[]}
        catalogue={cat}
        labels={labels}
      />,
    );
    expect(screen.getByTestId('readiness-ready')).toHaveTextContent('Nothing is open in the plant register.');
  });

  it('says the register is ready when it is, and that every check passes', () => {
    wrap(
      <FrameSummary
        projectId="p1"
        summary={frame({ overdue_count: 0 })}
        readiness={readiness({ ready: true, critical_open: [], long_lead_open: [], frame_document_attached: true })}
        findings={[]}
        catalogue={cat}
        labels={labels}
      />,
    );
    expect(screen.getByTestId('readiness-ready')).toBeInTheDocument();
    expect(screen.getByTestId('findings-clean')).toHaveTextContent('No finding. Every check passes.');
  });
});
