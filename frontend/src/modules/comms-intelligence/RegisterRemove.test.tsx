// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * "Remove — raised in error…", both tiers of it.
 *
 * What matters here is the handoff. A delete that the server refuses must
 * not surface as a red toast reading "409 Conflict": it has to become the
 * withdraw dialog, carrying the server's own reasons as the explanation of
 * why deleting was never on offer. And a reason the server rejects must
 * re-ask WITH THE TYPING STILL IN THE BOX — the same trap the quote-gate
 * override fell into, where firing once and toasting the refusal silently
 * did nothing.
 *
 * Run: npx vitest run src/modules/comms-intelligence/RegisterRemove.test.tsx
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { TFunction } from 'i18next';

import { ApiError } from '@/shared/lib/api';
import type { AskOptions } from './qAsk';
import type { Kind, KindSpec, RegisterItemRow, Summary } from './registers-api';

// ── Mocks ───────────────────────────────────────────────────────────────

const api = vi.hoisted(() => ({
  deleteItem: vi.fn(),
  withdrawItem: vi.fn(),
  fetchSpec: vi.fn(),
  fetchItems: vi.fn(),
  fetchSummary: vi.fn(),
  fetchStats: vi.fn(),
}));
const ask = vi.hoisted(() => ({ qAsk: vi.fn(), qConfirm: vi.fn() }));

vi.mock('./registers-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./registers-api')>()),
  ...api,
}));
vi.mock('./qAsk', () => ask);

import { removeItemFlow, withdrawFlow, type RemoveCtx } from './RegisterRemove';
import { RegisterWorkspace } from './RegisterWorkspace';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

// ── Fixtures ────────────────────────────────────────────────────────────

const PROJECT = 'cdf558ff-5ad6-4da0-9016-bfe0233d1bee';
const REF = 'REG-RFQ-25406-0009';

/** The i18n mock only exists inside components; these flows take `t`. */
const t = ((key: string, opts?: Record<string, unknown>) => {
  let out = String(opts?.defaultValue ?? key);
  for (const [k, v] of Object.entries(opts ?? {})) {
    if (k === 'defaultValue') continue;
    out = out.split(`{{${k}}}`).join(String(v));
  }
  return out;
}) as unknown as TFunction;

function item(over: Partial<RegisterItemRow> = {}): RegisterItemRow {
  return {
    id: 'item-1',
    project_id: PROJECT,
    kind: 'rfq',
    reference: REF,
    title: 'Switchboard package',
    status: 'open',
    due_date: null,
    days_until_due: null,
    is_overdue: false,
    fields: {},
    recipient_contact_ids: [],
    raised_from_id: null,
    linked_entity_type: null,
    linked_entity_id: null,
    steps_total: 3,
    steps_done: 0,
    current_step: null,
    ball_in_court: 'us',
    steps: [],
    created_at: '2026-09-01T00:00:00Z',
    ...over,
  };
}

const conflict = (error: string, reasons: string[]) =>
  new ApiError(409, 'Conflict', { detail: { error, reasons } });

function ctxFor(client: QueryClient) {
  const toasts: { type: string; title: string }[] = [];
  const ctx: RemoveCtx = {
    t,
    addToast: (x) => void toasts.push(x),
    queryClient: client,
    projectId: PROJECT,
  };
  return { ctx, toasts };
}

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  for (const fn of Object.values(ask)) fn.mockReset();
});
afterEach(cleanup);

// ── The delete tier ─────────────────────────────────────────────────────

describe('remove — raised in error', () => {
  it('confirms by reference, deletes, toasts and invalidates the register', async () => {
    ask.qConfirm.mockResolvedValue(true);
    api.deleteItem.mockResolvedValue(undefined);
    const client = newClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { ctx, toasts } = ctxFor(client);

    const out = await removeItemFlow(item(), ctx);

    expect(out).toBe('deleted');
    // The guard names the row, because rows are one line apart.
    expect(String(ask.qConfirm.mock.calls[0]![0])).toContain(REF);
    expect(api.deleteItem).toHaveBeenCalledWith('item-1');
    expect(toasts).toEqual([{ type: 'success', title: `${REF} deleted` }]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['registers', PROJECT] });
    // Nothing was asked beyond the confirmation - a clean item never sees
    // the withdraw dialog.
    expect(ask.qAsk).not.toHaveBeenCalled();
  });

  it('deletes nothing when the confirmation is declined', async () => {
    ask.qConfirm.mockResolvedValue(false);
    const { ctx } = ctxFor(newClient());

    expect(await removeItemFlow(item(), ctx)).toBeNull();
    expect(api.deleteItem).not.toHaveBeenCalled();
  });

  // ── The handoff ───────────────────────────────────────────────────────

  it('turns a 409 into the withdraw dialog, carrying the server’s reasons', async () => {
    ask.qConfirm.mockResolvedValue(true);
    api.deleteItem.mockRejectedValue(
      conflict(`${REF} has already gone out.`, ['emailed to 2 suppliers on 2 Sep', '1 quote recorded']),
    );
    ask.qAsk.mockResolvedValue(null); // the user backs out of the withdraw
    const { ctx, toasts } = ctxFor(newClient());

    const out = await removeItemFlow(item(), ctx);

    expect(out).toBeNull();
    expect(ask.qAsk).toHaveBeenCalledTimes(1);
    const opts = ask.qAsk.mock.calls[0]![0] as AskOptions;
    expect(opts.title).toBe(`Withdraw ${REF}?`);
    // The refusal is EXPLAINED, not dumped: the lead sentence, then each
    // reason the server gave, then what withdrawing actually does.
    expect(opts.note).toContain('has already gone out');
    expect(opts.note).toContain('emailed to 2 suppliers on 2 Sep');
    expect(opts.note).toContain('1 quote recorded');
    expect(opts.note).toContain('keeps it on the record');
    // One field, required, multiline - a reason is a sentence.
    expect(opts.fields).toHaveLength(1);
    expect(opts.fields?.[0]?.multiline).toBe(true);
    expect(opts.fields?.[0]?.label).toContain('Why is it being withdrawn?');
    // And NOT a red toast full of transport noise.
    expect(toasts).toEqual([]);
  });

  it('reports a real failure as an error rather than offering to withdraw', async () => {
    ask.qConfirm.mockResolvedValue(true);
    api.deleteItem.mockRejectedValue(new ApiError(500, 'Server Error', { detail: 'boom' }));
    const { ctx, toasts } = ctxFor(newClient());

    expect(await removeItemFlow(item(), ctx)).toBeNull();
    expect(ask.qAsk).not.toHaveBeenCalled();
    expect(toasts[0]?.type).toBe('error');
  });
});

// ── The withdraw tier ───────────────────────────────────────────────────

describe('withdraw', () => {
  it('posts the trimmed reason, toasts and invalidates', async () => {
    ask.qAsk.mockResolvedValue(['  raised against the wrong job — reissued as REG-RFQ-25406-0010  ']);
    api.withdrawItem.mockResolvedValue(item({ status: 'withdrawn' }));
    const client = newClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { ctx, toasts } = ctxFor(client);

    expect(await withdrawFlow(item(), ctx)).toBe('withdrawn');
    expect(api.withdrawItem).toHaveBeenCalledWith(
      'item-1',
      'raised against the wrong job — reissued as REG-RFQ-25406-0010',
    );
    expect(toasts).toEqual([{ type: 'success', title: `${REF} withdrawn` }]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['registers', PROJECT] });
  });

  it('re-asks with the server’s message when the reason is refused, keeping the typing', async () => {
    ask.qAsk.mockResolvedValueOnce(['x']).mockResolvedValueOnce(['raised against the wrong job']);
    api.withdrawItem
      .mockRejectedValueOnce(
        new ApiError(422, 'Unprocessable', {
          detail: { error: '“x” is not a reason — say what went wrong.' },
        }),
      )
      .mockResolvedValueOnce(item({ status: 'withdrawn' }));
    const { ctx, toasts } = ctxFor(newClient());

    expect(await withdrawFlow(item(), ctx)).toBe('withdrawn');
    expect(ask.qAsk).toHaveBeenCalledTimes(2);
    const second = ask.qAsk.mock.calls[1]![0] as AskOptions;
    expect(second.note).toBe('“x” is not a reason — say what went wrong.');
    // THE TYPING SURVIVES the refusal - retyping a paragraph is how a rail
    // gets worked around instead of used.
    expect(second.fields?.[0]?.value).toBe('x');
    expect(api.withdrawItem).toHaveBeenCalledTimes(2);
    expect(toasts.filter((x) => x.type === 'error')).toEqual([]);
  });

  it('stops on a failure that is not about the words', async () => {
    ask.qAsk.mockResolvedValue(['raised against the wrong job']);
    api.withdrawItem.mockRejectedValue(new ApiError(403, 'Forbidden', { detail: 'not yours' }));
    const { ctx, toasts } = ctxFor(newClient());

    expect(await withdrawFlow(item(), ctx)).toBeNull();
    expect(ask.qAsk).toHaveBeenCalledTimes(1);
    expect(toasts[0]?.type).toBe('error');
  });

  it('does nothing when cancelled', async () => {
    ask.qAsk.mockResolvedValue(null);
    const { ctx } = ctxFor(newClient());
    expect(await withdrawFlow(item(), ctx)).toBeNull();
    expect(api.withdrawItem).not.toHaveBeenCalled();
  });
});

// ── How a withdrawn row reads ───────────────────────────────────────────

const SPEC: KindSpec = {
  kind: 'rfq',
  label: 'RFQ',
  prefix: 'RFQ',
  recipient: 'multi',
  evidence_section: '',
  intro: '',
  fields: [],
  flow: [],
  actions: [],
};

const EMPTY_SUMMARY = Object.fromEntries(
  (['rfi', 'rfq', 'order', 'variation', 'delay', 'toolbox'] as Kind[]).map((k) => [
    k,
    { total: 1, open: 0, overdue: 0, with_them: 0 },
  ]),
) as Summary;

function renderWorkspace() {
  return render(
    <QueryClientProvider client={newClient()}>
      <MemoryRouter>
        <RegisterWorkspace onEmailItem={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('a withdrawn row', () => {
  const withdrawn = item({
    status: 'withdrawn',
    withdrawn_at: '2026-09-03T04:00:00Z',
    withdrawn_by: 'Test Admin',
    withdrawn_reason: 'raised against the wrong job',
  });

  beforeEach(() => {
    useProjectContextStore.setState({ activeProjectId: PROJECT, activeProjectName: 'Sample Project' });
    api.fetchSpec.mockResolvedValue({ kinds: ['rfq'], specs: { rfq: SPEC } });
    api.fetchSummary.mockResolvedValue(EMPTY_SUMMARY);
    api.fetchStats.mockResolvedValue({
      open: 0,
      closed: 1,
      avg_days_to_close: null,
      closed_on_time_pct: null,
      oldest_open_days: null,
      oldest_open_reference: null,
      lost_hours: '0',
    });
    api.fetchItems.mockResolvedValue([withdrawn]);
  });

  it('is out of the list until "show closed" is ticked, then reads as withdrawn', async () => {
    renderWorkspace();

    // Out of the open register: the whole point of withdrawing is that it
    // stops sitting beside the real work.
    await waitFor(() => expect(api.fetchItems).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(REF)).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(screen.getByText(REF)).toBeInTheDocument());

    const row = document.getElementById('rw-item-item-1') as HTMLElement;
    expect(row).toBeTruthy();
    expect(row.style.textDecoration).toContain('line-through');
    expect(Number(row.style.opacity)).toBeLessThan(1);
    // The badge, and the reason where anybody would look for it.
    expect(row.textContent).toContain('withdrawn');
    expect(row.getAttribute('title')).toContain('raised against the wrong job');
    expect(row.getAttribute('title')).toContain('Test Admin');
    // And nothing further can be sent on it.
    const email = screen.getByRole('button', { name: /preview email/i });
    expect(email).toBeDisabled();
    expect(email.getAttribute('title')).toContain('was withdrawn');
  });
});
