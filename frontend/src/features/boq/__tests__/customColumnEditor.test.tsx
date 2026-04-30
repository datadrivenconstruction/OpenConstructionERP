/**
 * Phase E v2.7.0/E — Custom column editor (calculated type) flow tests.
 *
 * Acceptance:
 *   • Switching the type radio to "Calculated" reveals the formula textarea.
 *   • Typing a formula + clicking "Test" runs it against the first
 *     position and previews the result inline.
 *   • Save POSTs the new shape (`column_type: 'calculated'`, `formula`,
 *     `decimals`) to the API.
 *   • Reopening the dialog with an existing calculated column shows the
 *     formula in the existing-columns list.
 *
 * We mock the entire `boqApi` surface and the toast store so the tests
 * stay focused on the editor's own state machine.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { CustomColumnsDialog } from '../CustomColumnsDialog';
import type { CustomColumnDef, Position, BOQVariable } from '../api';

/* ── Mocks ──────────────────────────────────────────────────────── */

const mockListCustomColumns =
  vi.fn<(boqId: string) => Promise<CustomColumnDef[]>>();
const mockAddCustomColumn =
  vi.fn<(boqId: string, data: CustomColumnDef) => Promise<CustomColumnDef>>();
const mockDeleteCustomColumn =
  vi.fn<(boqId: string, name: string) => Promise<void>>();

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    boqApi: {
      listCustomColumns: (boqId: string) => mockListCustomColumns(boqId),
      addCustomColumn: (boqId: string, data: CustomColumnDef) =>
        mockAddCustomColumn(boqId, data),
      deleteCustomColumn: (boqId: string, name: string) =>
        mockDeleteCustomColumn(boqId, name),
    },
  };
});

const addToastMock = vi.fn();
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: <T,>(selector: (s: { addToast: typeof addToastMock }) => T) =>
    selector({ addToast: addToastMock }),
}));

vi.mock('@/shared/hooks/useConfirm', () => ({
  useConfirm: () => ({
    confirm: vi.fn().mockResolvedValue(true),
    open: false,
    title: '',
    message: '',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  }),
}));

/* ── Helpers ────────────────────────────────────────────────────── */

function makePos(opts: Partial<Position> & { id: string; ordinal: string }): Position {
  return {
    id: opts.id,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: opts.ordinal,
    description: opts.description ?? '',
    unit: opts.unit ?? 'm',
    quantity: opts.quantity ?? 0,
    unit_rate: opts.unit_rate ?? 0,
    total: (opts.quantity ?? 0) * (opts.unit_rate ?? 0),
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 0,
    validation_status: 'pending',
    metadata: opts.metadata ?? {},
  };
}

function renderDialog({
  initialColumns = [],
  positions = [],
  variables = [],
}: {
  initialColumns?: CustomColumnDef[];
  positions?: Position[];
  variables?: BOQVariable[];
} = {}) {
  mockListCustomColumns.mockResolvedValue(initialColumns);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(
    <CustomColumnsDialog
      open={true}
      onClose={vi.fn()}
      boqId="boq-1"
      positions={positions}
      variables={variables}
    />,
    { wrapper: Wrapper },
  );
}

/* ── Tests ──────────────────────────────────────────────────────── */

describe('CustomColumnsDialog — calculated column flow', () => {
  beforeEach(() => {
    mockListCustomColumns.mockReset();
    mockAddCustomColumn.mockReset();
    mockDeleteCustomColumn.mockReset();
    addToastMock.mockReset();
  });

  it('reveals the formula textarea when "Calculated" is selected', async () => {
    renderDialog();
    // Wait for the empty-state message confirming list query resolved.
    await screen.findByText(/No custom columns yet/i);
    // Open the manual form.
    fireEvent.click(screen.getByText('Show form'));
    // Default type is "text" — formula textarea must be hidden.
    expect(screen.queryByPlaceholderText(/quantity \* unit_rate/i)).toBeNull();
    // Click the "Calculated" radio.
    fireEvent.click(screen.getByRole('radio', { name: /Calculated/i }));
    // Formula textarea now visible.
    const formula = await screen.findByPlaceholderText(/quantity \* unit_rate/i);
    expect(formula).toBeInTheDocument();
    // Decimals input is present with default 2.
    const decimals = screen.getByLabelText(/Decimals/i) as HTMLInputElement;
    expect(decimals.value).toBe('2');
  });

  it('Test button evaluates the formula against the first position', async () => {
    renderDialog({
      positions: [makePos({ id: 'a', ordinal: '1.1', quantity: 4, unit_rate: 25 })],
    });
    await screen.findByText(/No custom columns yet/i);
    fireEvent.click(screen.getByText('Show form'));
    fireEvent.click(screen.getByRole('radio', { name: /Calculated/i }));

    const textarea = screen.getByPlaceholderText(/quantity \* unit_rate/i);
    fireEvent.change(textarea, { target: { value: '=$QUANTITY * $UNIT_RATE' } });

    const testBtn = screen.getByRole('button', { name: /Test/i });
    fireEvent.click(testBtn);

    // 4 * 25 = 100 → "100.00" with 2 decimals.
    await screen.findByText('100.00');
    expect(screen.getByText(/Result:/i)).toBeInTheDocument();
  });

  it('Save persists the calculated column with formula + decimals', async () => {
    mockAddCustomColumn.mockResolvedValue({
      name: 'with_vat',
      display_name: 'With VAT',
      column_type: 'calculated',
      formula: '=$QUANTITY * $UNIT_RATE * 1.19',
      decimals: 2,
    });
    renderDialog({
      positions: [makePos({ id: 'a', ordinal: '1.1', quantity: 1, unit_rate: 1 })],
    });
    await screen.findByText(/No custom columns yet/i);
    fireEvent.click(screen.getByText('Show form'));
    fireEvent.click(screen.getByRole('radio', { name: /Calculated/i }));

    fireEvent.change(screen.getByLabelText(/Column name/i), {
      target: { value: 'With VAT' },
    });
    fireEvent.change(screen.getByPlaceholderText(/quantity \* unit_rate/i), {
      target: { value: '=$QUANTITY * $UNIT_RATE * 1.19' },
    });
    fireEvent.change(screen.getByLabelText(/Decimals/i), {
      target: { value: '3' },
    });

    fireEvent.click(screen.getByRole('button', { name: /Add column/i }));

    await waitFor(() => expect(mockAddCustomColumn).toHaveBeenCalledTimes(1));
    const [, payload] = mockAddCustomColumn.mock.calls[0]!;
    expect(payload.column_type).toBe('calculated');
    expect(payload.name).toBe('with_vat');
    expect(payload.formula).toBe('=$QUANTITY * $UNIT_RATE * 1.19');
    expect(payload.decimals).toBe(3);
  });

  it('refuses to save a calculated column without a formula', async () => {
    renderDialog();
    await screen.findByText(/No custom columns yet/i);
    fireEvent.click(screen.getByText('Show form'));
    fireEvent.click(screen.getByRole('radio', { name: /Calculated/i }));

    fireEvent.change(screen.getByLabelText(/Column name/i), {
      target: { value: 'Empty Calc' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Add column/i }));

    // Mutation must not have been called and the user must have seen an error toast.
    expect(mockAddCustomColumn).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(addToastMock).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'error',
          title: expect.stringMatching(/needs a formula/i),
        }),
      );
    });
  });

  it('flags syntax errors live below the textarea', async () => {
    renderDialog();
    await screen.findByText(/No custom columns yet/i);
    fireEvent.click(screen.getByText('Show form'));
    fireEvent.click(screen.getByRole('radio', { name: /Calculated/i }));

    const textarea = screen.getByPlaceholderText(/quantity \* unit_rate/i);
    // Unterminated string literal — `normaliseFormula` itself doesn't
    // tokenise, but the formula passes `isFormula` (has parens) and the
    // bad quote will be flagged at evaluation time. The "must contain
    // operator/function" check is what's exercised by "plain text".
    fireEvent.change(textarea, { target: { value: 'plain text' } });
    // Live error visible.
    expect(
      await screen.findByText(/Must start with `=`/i),
    ).toBeInTheDocument();
  });

  it('reopens with an existing calculated column visible in the list', async () => {
    renderDialog({
      initialColumns: [
        {
          name: 'tax',
          display_name: 'Tax',
          column_type: 'calculated',
          formula: '=$QUANTITY * 0.19',
          decimals: 2,
          sort_order: 0,
        },
      ],
    });
    // The column display name + the formula source appear.
    await screen.findByText('Tax');
    expect(screen.getByText('=$QUANTITY * 0.19')).toBeInTheDocument();
    // Type badge says "calculated".
    expect(screen.getByText('calculated')).toBeInTheDocument();
  });

  it('clicking a preset chip fills the textarea', async () => {
    renderDialog();
    await screen.findByText(/No custom columns yet/i);
    fireEvent.click(screen.getByText('Show form'));
    fireEvent.click(screen.getByRole('radio', { name: /Calculated/i }));

    fireEvent.click(screen.getByRole('button', { name: /× 1.19 \(VAT\)/i }));
    const textarea = screen.getByPlaceholderText(
      /quantity \* unit_rate/i,
    ) as HTMLTextAreaElement;
    expect(textarea.value).toContain('1.19');
  });
});
