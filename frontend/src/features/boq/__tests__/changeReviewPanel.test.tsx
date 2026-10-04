// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The change review panel reports and asks; it never writes on its own.
 *
 * Opening it runs one check for revised drawings and new model versions and
 * lists the positions they touch. Marking a flag reviewed sends that flag and
 * nothing else. On the quantities tab only the lines the estimator leaves
 * ticked are sent to the apply endpoint, the running total follows the ticks,
 * a line that cannot be applied cannot be ticked, and a locked bill cannot be
 * changed from here at all.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';

import { ChangeReviewButton, ChangeReviewPanel } from '../ChangeReviewPanel';
import {
  changeReviewApi,
  type BIMQuantityProposal,
  type ChangeFlag,
  type ChangeFlagList,
} from '../changeReviewApi';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const FLAG_DOC: ChangeFlag = {
  id: 'flag-doc',
  boq_id: 'boq-1',
  position_id: 'pos-wall',
  ordinal: '01.010',
  description: 'Blockwork wall',
  source_type: 'document_revision',
  source_key: 'document:doc-1:v2',
  source_id: 'doc-1',
  source_label: 'A-101 Ground floor plan.pdf',
  source_version: 'B',
  reason: 'document_revised',
  details: { version_number: 2, measurement_count: 3 },
  detected_via: 'scan',
  status: 'open',
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  created_at: '2026-10-02T09:00:00Z',
};

const FLAG_BIM: ChangeFlag = {
  ...FLAG_DOC,
  id: 'flag-bim',
  position_id: 'pos-slab',
  ordinal: '02.020',
  description: 'Floor slab',
  source_type: 'bim_version',
  source_key: 'bim:model-2',
  source_id: 'model-2',
  source_label: 'Structure',
  source_version: '2',
  reason: 'elements_modified',
  details: { modified_count: 2, deleted_count: 0 },
};

function flagList(flags: ChangeFlag[]): ChangeFlagList {
  return {
    boq_id: 'boq-1',
    open_count: flags.filter((f) => f.status === 'open').length,
    reviewed_count: flags.filter((f) => f.status === 'reviewed').length,
    flags,
  };
}

function proposal(overrides: Partial<BIMQuantityProposal>): BIMQuantityProposal {
  return {
    position_id: 'pos-x',
    ordinal: '00.000',
    description: 'Line',
    unit: 'm3',
    unit_rate: '100.00',
    current_quantity: '15',
    previous_model_quantity: '15',
    new_model_quantity: '13',
    delta: '-2',
    current_total: '1500.00',
    new_total: '1300.00',
    total_delta: '-200.00',
    method: 'unit',
    status: 'changed',
    appliable: true,
    manual_override: false,
    model_id: 'model-1',
    new_model_id: 'model-2',
    model_name: 'Structure',
    model_version: '2',
    element_count: 2,
    modified_count: 1,
    missing_count: 0,
    ...overrides,
  };
}

const ROWS: BIMQuantityProposal[] = [
  proposal({ position_id: 'pos-a', ordinal: '01.001', description: 'Concrete walls' }),
  proposal({
    position_id: 'pos-m',
    ordinal: '01.002',
    description: 'Formwork',
    unit: 'm2',
    unit_rate: '10.00',
    current_quantity: '4',
    previous_model_quantity: '3',
    new_model_quantity: '6',
    delta: '2',
    current_total: '40.00',
    new_total: '60.00',
    total_delta: '20.00',
    manual_override: true,
  }),
  proposal({
    position_id: 'pos-gone',
    ordinal: '01.003',
    description: 'Removed columns',
    status: 'elements_missing',
    appliable: false,
    new_model_quantity: '0',
    delta: '-15',
    total_delta: '0',
  }),
];

function renderPanel(props: Partial<Parameters<typeof ChangeReviewPanel>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onApplied = vi.fn();
  const onJumpToPosition = vi.fn();
  render(
    createElement(
      QueryClientProvider,
      { client },
      createElement(ChangeReviewPanel, {
        boqId: 'boq-1',
        locale: 'en-US',
        currencyCode: 'EUR',
        isOpen: true,
        isLocked: false,
        onClose: () => {},
        onApplied,
        onJumpToPosition,
        ...props,
      }),
    ),
  );
  return { onApplied, onJumpToPosition };
}

function mockFlags(flags: ChangeFlag[] = [FLAG_DOC, FLAG_BIM]) {
  const scan = vi.spyOn(changeReviewApi, 'scan').mockResolvedValue({
    boq_id: 'boq-1',
    positions_checked: 5,
    bim_flags_found: 1,
    document_flags_found: 1,
    created: 0,
    open_count: flags.length,
  });
  const list = vi.spyOn(changeReviewApi, 'listFlags').mockResolvedValue(flagList(flags));
  const review = vi
    .spyOn(changeReviewApi, 'review')
    .mockResolvedValue({ boq_id: 'boq-1', updated: 1, open_count: flags.length - 1 });
  return { scan, list, review };
}

describe('ChangeReviewPanel flags', () => {
  it('checks once on open and names the drawing, its revision and the position', async () => {
    const { scan, list } = mockFlags();
    vi.spyOn(changeReviewApi, 'proposals').mockResolvedValue({
      boq_id: 'boq-1',
      positions_checked: 0,
      appliable_count: 0,
      total_delta: '0',
      rows: [],
    });
    renderPanel();

    const rows = await screen.findAllByTestId('change-flag-row');
    expect(rows).toHaveLength(2);
    expect(scan).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledWith('boq-1', 'open');

    const doc = within(rows[0]!);
    expect(doc.getByText(/Blockwork wall/)).toBeTruthy();
    expect(doc.getByText('A-101 Ground floor plan.pdf, revision B')).toBeTruthy();
    expect(doc.getByText(/revised after this quantity was measured/)).toBeTruthy();

    const bim = within(rows[1]!);
    expect(bim.getByText('Structure, version 2')).toBeTruthy();
    expect(bim.getByText('Changed: 2')).toBeTruthy();
  });

  it('marks one flag reviewed by id and changes nothing else', async () => {
    const { review } = mockFlags();
    const { onApplied } = renderPanel();
    const rows = await screen.findAllByTestId('change-flag-row');

    fireEvent.click(within(rows[1]!).getByText('Mark reviewed'));
    await waitFor(() => expect(review).toHaveBeenCalledTimes(1));
    expect(review).toHaveBeenCalledWith('boq-1', { flag_ids: ['flag-bim'], status: 'reviewed' });
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('marks every open flag reviewed in one request', async () => {
    const { review } = mockFlags();
    renderPanel();
    await screen.findAllByTestId('change-flag-row');

    fireEvent.click(screen.getByText('Mark all reviewed'));
    await waitFor(() => expect(review).toHaveBeenCalledWith('boq-1', { all_open: true }));
  });

  it('jumps the grid to the flagged position', async () => {
    mockFlags();
    const { onJumpToPosition } = renderPanel();
    const rows = await screen.findAllByTestId('change-flag-row');

    fireEvent.click(within(rows[0]!).getByText('Show position'));
    expect(onJumpToPosition).toHaveBeenCalledWith('pos-wall');
  });

  it('reopens a reviewed flag', async () => {
    const reviewed: ChangeFlag = { ...FLAG_DOC, status: 'reviewed', reviewed_at: '2026-10-03T10:00:00Z' };
    const { review, list } = mockFlags([reviewed]);
    renderPanel();
    await waitFor(() => expect(list).toHaveBeenCalled());

    fireEvent.click(screen.getByText('Reviewed'));
    const row = await screen.findByTestId('change-flag-row');
    fireEvent.click(within(row).getByText('Reopen'));
    await waitFor(() => expect(review).toHaveBeenCalledWith('boq-1', { flag_ids: ['flag-doc'], status: 'open' }));
  });
});

describe('ChangeReviewPanel model quantities', () => {
  function openQuantities(props: Partial<Parameters<typeof ChangeReviewPanel>[0]> = {}) {
    mockFlags([]);
    vi.spyOn(changeReviewApi, 'proposals').mockResolvedValue({
      boq_id: 'boq-1',
      positions_checked: 4,
      appliable_count: 2,
      total_delta: '-180.00',
      rows: ROWS,
    });
    const apply = vi.spyOn(changeReviewApi, 'applyProposals').mockResolvedValue({
      boq_id: 'boq-1',
      applied: 1,
      skipped: 0,
      total_delta: '-200.00',
      results: [],
    });
    const handles = renderPanel(props);
    fireEvent.click(screen.getByRole('tab', { name: /Model quantities/ }));
    return { apply, ...handles };
  }

  it('ticks only appliable lines and totals what is ticked', async () => {
    openQuantities();
    const rows = await screen.findAllByTestId('bim-proposal-row');
    expect(rows).toHaveLength(3);

    const boxes = rows.map((r) => within(r).getByRole('checkbox') as HTMLInputElement);
    expect(boxes.map((b) => b.checked)).toEqual([true, true, false]);
    expect(boxes[2]!.disabled).toBe(true);
    expect(within(rows[2]!).getByText(/All linked elements were removed/)).toBeTruthy();
    expect(within(rows[1]!).getByText(/edited by hand/)).toBeTruthy();

    // -200 + 20 with both ticked; the untickable line adds nothing.
    expect(screen.getByTestId('bim-proposal-total').textContent).toMatch(/180\.00/);
    fireEvent.click(boxes[1]!);
    expect(screen.getByTestId('bim-proposal-total').textContent).toMatch(/200\.00/);
  });

  it('sends only the lines left ticked and refreshes the bill', async () => {
    const { apply, onApplied } = openQuantities();
    const rows = await screen.findAllByTestId('bim-proposal-row');

    fireEvent.click(within(rows[1]!).getByRole('checkbox'));
    fireEvent.click(screen.getByText('Accept selected: 1'));

    await waitFor(() => expect(apply).toHaveBeenCalledTimes(1));
    expect(apply).toHaveBeenCalledWith('boq-1', ['pos-a']);
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1));
  });

  it('does not apply on a locked bill', async () => {
    const { apply } = openQuantities({ isLocked: true });
    await screen.findAllByTestId('bim-proposal-row');

    const accept = screen.getByText('Accept selected: 2').closest('button') as HTMLButtonElement;
    expect(accept.disabled).toBe(true);
    fireEvent.click(accept);
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByText(/This estimate is locked/)).toBeTruthy();
  });
});

describe('ChangeReviewButton', () => {
  function renderButton(open: number) {
    vi.spyOn(changeReviewApi, 'summary').mockResolvedValue({
      boq_id: 'boq-1',
      open_count: open,
      open_by_source: {},
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const onClick = vi.fn();
    render(createElement(QueryClientProvider, { client }, createElement(ChangeReviewButton, { boqId: 'boq-1', onClick })));
    return onClick;
  }

  it('shows the open count', async () => {
    const onClick = renderButton(3);
    expect((await screen.findByTestId('boq-changes-badge')).textContent).toBe('3');
    fireEvent.click(screen.getByTestId('boq-changes-btn'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('shows no badge when nothing is open', async () => {
    renderButton(0);
    await waitFor(() => expect(changeReviewApi.summary).toHaveBeenCalled());
    expect(screen.queryByTestId('boq-changes-badge')).toBeNull();
  });
});
