// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The structured workflow editor.
 *
 * What matters here is the contract with the server: rows come off the
 * item in order, a reorder is a reorder, an existing hold point can only
 * be RETIRED with a reason (and Save refuses until it has one), and a
 * new decision goes out with its paths attached.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { KindSpec, RegisterItemRow, StepRow } from './registers-api';

const api = vi.hoisted(() => ({ configureSteps: vi.fn() }));

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock('./registers-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./registers-api')>()),
  configureSteps: api.configureSteps,
}));
vi.mock('./qAsk', () => ({
  qAsk: vi.fn(),
  qConfirm: vi.fn().mockResolvedValue(true),
}));

import { WorkflowEditorDialog, openWorkflowEditor, payloadOf, rowsFromItem } from './WorkflowEditor';

// ── Fixtures ────────────────────────────────────────────────────────────

const ROUTE = 'Does the answer change scope, cost or program?';
const GATE = 'Reviewed before issue';

function step(over: Partial<StepRow> & { name: string; position: number }): StepRow {
  return {
    id: `s-${over.position}`,
    type: 'step',
    owner: '',
    state: 'open',
    branches: [],
    chosen_branch: null,
    completed_at: null,
    completed_by: null,
    override_reason: null,
    raises_kind: null,
    raised_reference: null,
    ...over,
  };
}

function item(): RegisterItemRow {
  return {
    id: 'item-1',
    project_id: 'p-1',
    kind: 'rfi',
    reference: 'REG-RFI-25406-0001',
    title: 'Acme Electrical - grid clash at level 2',
    status: 'open',
    due_date: null,
    days_until_due: null,
    is_overdue: false,
    fields: {},
    recipient_contact_ids: [],
    raised_from_id: null,
    linked_entity_type: null,
    linked_entity_id: null,
    steps_total: 6,
    steps_done: 2,
    current_step: GATE,
    ball_in_court: 'us',
    created_at: '2026-09-01T08:00:00',
    steps: [
      // Deliberately out of position order: the editor must sort.
      step({ name: 'Sent to the client / consultant', position: 3 }),
      step({ name: GATE, position: 2, type: 'gate', owner: 'PM' }),
      step({
        name: 'Question drafted and clear',
        position: 0,
        state: 'done',
        completed_by: 'u1',
        completed_by_name: 'Jo Bloggs',
        completed_at: '2026-09-01T09:00:00',
      }),
      step({
        name: 'Drawings / marked-up sketch attached',
        position: 1,
        state: 'done',
        completed_by: 'u1',
        completed_at: '2026-09-01T09:05:00',
      }),
      step({ name: 'Response received in writing', position: 4 }),
      step({ name: ROUTE, position: 5, type: 'route', branches: ['No change - action it', 'Change - raise a variation'] }),
    ],
  };
}

function spec(): KindSpec {
  return {
    kind: 'rfi',
    label: 'RFI',
    prefix: 'RFI',
    recipient: 'any',
    evidence_section: '',
    intro: '',
    fields: [],
    flow: [
      { t: 'step', name: 'Question drafted and clear' },
      { t: 'step', name: 'Drawings / marked-up sketch attached' },
      { t: 'gate', name: GATE, owner: 'PM' },
      { t: 'step', name: 'Sent to the client / consultant' },
      { t: 'step', name: 'Response received in writing' },
      { t: 'route', name: ROUTE, branches: { 'No change - action it': ['Answer actioned in the works', 'Closed out'] } },
    ],
    actions: [
      { t: 'step', name: 'Chased by phone' },
      { t: 'gate', name: GATE, owner: 'PM' },
      { t: 'route', name: 'Does the client accept the cost?', branches: { Accepted: ['Raise the order'], Rejected: ['Advise the client in writing'] } },
    ],
  };
}

function mount(over: Partial<{ item: RegisterItemRow; spec: KindSpec | undefined }> = {}) {
  const resolve = vi.fn();
  const onSaved = vi.fn();
  render(
    <WorkflowEditorDialog item={over.item ?? item()} spec={'spec' in over ? over.spec : spec()} onSaved={onSaved} resolve={resolve} />,
  );
  return { resolve, onSaved };
}

const rows = () => screen.getAllByTestId('wfe-row');
const nameOf = (row: HTMLElement) => within(row).getByLabelText('Step name') as HTMLInputElement;
const names = () => rows().map((r) => nameOf(r).value);
const save = () => fireEvent.click(screen.getByText('Save the workflow'));

beforeEach(() => {
  api.configureSteps.mockReset();
  api.configureSteps.mockResolvedValue({});
});
afterEach(cleanup);

// ── Tests ───────────────────────────────────────────────────────────────

describe('WorkflowEditor - rows', () => {
  it('lays out history locked and the open steps in position order', () => {
    mount();
    const done = screen.getAllByTestId('wfe-done-row');
    expect(done.map((d) => d.textContent)).toEqual([
      expect.stringContaining('Question drafted and clear'),
      expect.stringContaining('Drawings / marked-up sketch attached'),
    ]);
    // Who signed it, and when.
    expect(done[0]!.textContent).toContain('Jo Bloggs');
    // Rendered through the ERP's own date formatter, not an ISO slice.
    expect(done[0]!.textContent).toMatch(/Sep 0?1, 2026|01 Sep 2026/);
    // No controls on history.
    expect(within(done[0]!).queryByRole('button')).toBeNull();

    expect(names()).toEqual([GATE, 'Sent to the client / consultant', 'Response received in writing', ROUTE]);
    // An existing row's type is a fixed chip, not a picker.
    const gateRow = rows()[0]!;
    expect(gateRow.dataset.rowType).toBe('gate');
    expect(within(gateRow).queryByRole('group')).toBeNull();
    expect(within(gateRow).getByText(/Gate/)).toBeInTheDocument();
    expect((within(gateRow).getByLabelText('Owner') as HTMLInputElement).value).toBe('PM');
    expect(rows()[3]!.dataset.rowType).toBe('route');
  });

  it('shows the item it is configuring', () => {
    mount();
    expect(screen.getByText('Configure the workflow')).toBeInTheDocument();
    expect(screen.getByText('REG-RFI-25406-0001')).toBeInTheDocument();
  });

  it('a retired hold point in history shows its reason', () => {
    const it2 = item();
    it2.steps.push(
      step({
        name: 'Package checked before it goes out',
        position: 6,
        type: 'gate',
        state: 'not_required',
        override_reason: 'Taken off this workflow: the client checks this package themselves',
        completed_by: 'u2',
        completed_at: '2026-09-02T10:00:00',
      }),
    );
    mount({ item: it2 });
    expect(screen.getByText(/the client checks this package themselves/)).toBeInTheDocument();
  });

  it('▼ moves a row down (and ▲ back up)', () => {
    mount();
    fireEvent.click(within(rows()[0]!).getByLabelText('Move down'));
    expect(names()).toEqual(['Sent to the client / consultant', GATE, 'Response received in writing', ROUTE]);
    fireEvent.click(within(rows()[1]!).getByLabelText('Move up'));
    expect(names()).toEqual([GATE, 'Sent to the client / consultant', 'Response received in writing', ROUTE]);
    // The ends cannot move past themselves.
    expect(within(rows()[0]!).getByLabelText('Move up')).toBeDisabled();
    expect(within(rows()[3]!).getByLabelText('Move down')).toBeDisabled();
  });

  it('removing an existing plain step just removes it', () => {
    mount();
    fireEvent.click(within(rows()[1]!).getByLabelText(/^Remove/));
    expect(names()).toEqual([GATE, 'Response received in writing', ROUTE]);
    expect(screen.queryByTestId('wfe-reason')).toBeNull();
  });
});

describe('WorkflowEditor - taking a hold point off', () => {
  it('marks the gate as coming off, demands a reason, and refuses to save without one', async () => {
    const { onSaved, resolve } = mount();
    fireEvent.click(within(rows()[0]!).getByLabelText(/^Remove/));

    // Still on the list, struck through, with an undo - not deleted.
    expect(rows()).toHaveLength(4);
    expect(rows()[0]!.className).toContain('retiring');
    expect(screen.getByTestId('wfe-offnote')).toHaveTextContent('coming off this workflow');
    const reasonBox = screen.getByTestId('wfe-reason');
    expect(reasonBox).toHaveTextContent('Why are these coming off this job?');
    expect(reasonBox).toHaveTextContent(GATE);

    save();
    expect(api.configureSteps).not.toHaveBeenCalled();
    expect(screen.getByTestId('wfe-error')).toHaveTextContent(/why these hold points are coming off/);
    expect(onSaved).not.toHaveBeenCalled();

    const reason = 'The client issues this RFI direct - there is no internal review here';
    fireEvent.change(within(reasonBox).getByRole('textbox'), { target: { value: reason } });
    save();
    await waitFor(() => expect(api.configureSteps).toHaveBeenCalledTimes(1));
    expect(api.configureSteps).toHaveBeenCalledWith(
      'item-1',
      [
        { name: 'Sent to the client / consultant', type: 'step' },
        { name: 'Response received in writing', type: 'step' },
        { name: ROUTE, type: 'route' },
      ],
      reason,
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(resolve).toHaveBeenCalledWith(true);
  });

  it('undo puts the gate back and the reason field goes away', () => {
    mount();
    fireEvent.click(within(rows()[0]!).getByLabelText(/^Remove/));
    fireEvent.click(screen.getByText('undo'));
    expect(rows()[0]!.className).not.toContain('retiring');
    expect(screen.queryByTestId('wfe-reason')).toBeNull();
  });

  it('keeps the dialog open and shows the server refusal inline', async () => {
    api.configureSteps.mockRejectedValueOnce(new Error('"n/a" is not a reason - say what is actually happening.'));
    const { resolve } = mount();
    fireEvent.click(within(rows()[0]!).getByLabelText(/^Remove/));
    fireEvent.change(within(screen.getByTestId('wfe-reason')).getByRole('textbox'), { target: { value: 'n/a' } });
    save();
    await waitFor(() => expect(screen.getByTestId('wfe-error')).toHaveTextContent('not a reason'));
    expect(resolve).not.toHaveBeenCalled();
    expect(screen.getByTestId('wfe')).toBeInTheDocument();
  });
});

describe('WorkflowEditor - the payload', () => {
  it('sends a new decision with its paths, and kept rows with their owner', async () => {
    mount();
    fireEvent.click(screen.getByText(/Add decision/));
    const fresh = rows()[4]!;
    expect(fresh.dataset.existing).toBe('0');
    // A new row's type is a picker, pressed on "Decision".
    expect(within(fresh).getByRole('group')).toBeInTheDocument();
    expect(within(fresh).getByText(/Decision/, { selector: 'button' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.change(nameOf(fresh), { target: { value: 'Does Acme Electrical accept the revised price?' } });
    fireEvent.change(within(fresh).getByLabelText('Owner'), { target: { value: 'PM' } });

    // No path yet: refused before the server is troubled.
    save();
    expect(api.configureSteps).not.toHaveBeenCalled();
    expect(screen.getByTestId('wfe-error')).toHaveTextContent('needs at least one path');

    fireEvent.click(within(fresh).getByText(/Add a path/));
    fireEvent.click(within(fresh).getByText(/Add a path/));
    const labels = within(fresh).getAllByLabelText('Path');
    const stepsOf = within(fresh).getAllByLabelText('Steps this path adds');
    fireEvent.change(labels[0]!, { target: { value: 'Accepted' } });
    fireEvent.change(stepsOf[0]!, { target: { value: 'Raise the order\n\nClosed out ' } });
    fireEvent.change(labels[1]!, { target: { value: 'Rejected' } });
    fireEvent.change(stepsOf[1]!, { target: { value: 'Advise the client in writing' } });

    save();
    await waitFor(() => expect(api.configureSteps).toHaveBeenCalledTimes(1));
    expect(api.configureSteps).toHaveBeenCalledWith(
      'item-1',
      [
        { name: GATE, type: 'gate', owner: 'PM' },
        { name: 'Sent to the client / consultant', type: 'step' },
        { name: 'Response received in writing', type: 'step' },
        { name: ROUTE, type: 'route' },
        {
          name: 'Does Acme Electrical accept the revised price?',
          type: 'route',
          owner: 'PM',
          branches: { Accepted: ['Raise the order', 'Closed out'], Rejected: ['Advise the client in writing'] },
        },
      ],
      undefined,
    );
  });

  it('a library decision arrives with its paths prefilled', () => {
    mount();
    fireEvent.click(screen.getByText(/From the library/));
    fireEvent.click(within(screen.getByTestId('wfe-library')).getByText('Does the client accept the cost?'));
    const fresh = rows()[4]!;
    expect(fresh.dataset.rowType).toBe('route');
    const labels = within(fresh).getAllByLabelText('Path') as HTMLInputElement[];
    expect(labels.map((l) => l.value)).toEqual(['Accepted', 'Rejected']);
    const rowsOut = payloadOf(rowsFromItem(item()));
    expect(rowsOut.every((r) => !('branches' in r))).toBe(true);
  });

  it('refuses an empty name and a duplicate name before calling the server', () => {
    mount();
    fireEvent.click(screen.getByText(/Add step/));
    save();
    expect(screen.getByTestId('wfe-error')).toHaveTextContent('Every step needs a name');
    fireEvent.change(nameOf(rows()[4]!), { target: { value: GATE.toLowerCase() } });
    save();
    expect(screen.getByTestId('wfe-error')).toHaveTextContent(/share the name/);
    expect(api.configureSteps).not.toHaveBeenCalled();
  });

  it('Enter in a name moves to the next row', () => {
    mount();
    const first = nameOf(rows()[0]!);
    first.focus();
    fireEvent.keyDown(first, { key: 'Enter' });
    expect(document.activeElement).toBe(nameOf(rows()[1]!));
  });
});

describe('openWorkflowEditor', () => {
  it('mounts over the page and resolves false on cancel', async () => {
    let p: Promise<boolean> | undefined;
    await act(async () => {
      p = openWorkflowEditor({ item: item(), spec: spec(), onSaved: vi.fn() });
    });
    expect(screen.getByTestId('wfe')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByText('Cancel'));
    });
    await expect(p!).resolves.toBe(false);
    expect(screen.queryByTestId('wfe')).toBeNull();
  });

  it('Escape cancels', async () => {
    let p: Promise<boolean> | undefined;
    await act(async () => {
      p = openWorkflowEditor({ item: item(), spec: undefined, onSaved: vi.fn() });
    });
    await act(async () => {
      fireEvent.keyDown(window, { key: 'Escape' });
    });
    await expect(p!).resolves.toBe(false);
  });
});
