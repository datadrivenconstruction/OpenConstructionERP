// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A schedule of values line is linked to the bill from the screen.
//
// "Populate from progress" bills a line at the progress reading of the BOQ
// position it is linked to, and nothing on screen could make that link. The
// editor writes the link and the line's code in the project's own
// classification standard, which is NRM here rather than MasterFormat, and the
// code follows the picked position until the person types one.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

import { SovLineLinkEditor, SovLineLinkSummary } from './SovLineLink';
import type { ContractLine } from './api';

function line(metadata: Record<string, unknown> = {}): ContractLine {
  return {
    id: 'line-1',
    contract_id: 'ctr-1',
    parent_line_id: null,
    code: '01',
    description: 'Frame',
    scope_section: null,
    line_type: 'work',
    unit: 'm3',
    quantity: 10,
    unit_rate: 100,
    total_value: 1000,
    order_index: 0,
    metadata,
    created_at: '',
    updated_at: '',
  };
}

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPatch.mockReset();
  api.apiGet.mockImplementation((path: string) => {
    if (path === '/v1/projects/p-1') return Promise.resolve({ id: 'p-1', classification_standard: 'nrm' });
    if (path.startsWith('/v1/boq/boqs/?')) return Promise.resolve([{ id: 'boq-1', name: 'Main' }]);
    if (path === '/v1/boq/boqs/boq-1')
      return Promise.resolve({
        positions: [
          { id: 'sec-1', parent_id: null, ordinal: '2', description: 'Frame', unit: '' },
          {
            id: 'pos-1',
            parent_id: 'sec-1',
            ordinal: '2.1',
            description: 'Concrete frame',
            unit: 'm3',
            classification: { nrm: '2.1.1' },
          },
        ],
      });
    if (path === '/v1/boq/positions/pos-1')
      return Promise.resolve({ id: 'pos-1', ordinal: '2.1', description: 'Concrete frame' });
    return Promise.reject(new Error(`not mocked: ${path}`));
  });
  api.apiPatch.mockResolvedValue(line());
});

afterEach(() => cleanup());

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe('the link from a schedule line to the bill', () => {
  it('saves the position and its code in the project standard', async () => {
    const onDone = vi.fn();
    renderWith(
      <SovLineLinkEditor
        line={line({ boq_position_id: 'pos-1' })}
        contractId="ctr-1"
        projectId="p-1"
        onDone={onDone}
      />,
    );

    const code = (await screen.findByTestId('sov-link-code')) as HTMLInputElement;
    await waitFor(() => expect(code.value).toBe('2.1.1'));
    fireEvent.click(screen.getByTestId('sov-link-save'));

    await waitFor(() => expect(api.apiPatch).toHaveBeenCalledTimes(1));
    expect(api.apiPatch).toHaveBeenCalledWith('/v1/contracts/contracts/lines/line-1', {
      metadata: { boq_position_id: 'pos-1', classification: { nrm: '2.1.1' } },
    });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it('keeps a code the person typed over the position’s own', async () => {
    renderWith(
      <SovLineLinkEditor
        line={line({ boq_position_id: 'pos-1' })}
        contractId="ctr-1"
        projectId="p-1"
        onDone={vi.fn()}
      />,
    );

    const code = (await screen.findByTestId('sov-link-code')) as HTMLInputElement;
    fireEvent.change(code, { target: { value: '2.1.9' } });
    fireEvent.click(screen.getByTestId('sov-link-save'));

    await waitFor(() => expect(api.apiPatch).toHaveBeenCalledTimes(1));
    expect(api.apiPatch.mock.calls[0]![1]).toEqual({
      metadata: { boq_position_id: 'pos-1', classification: { nrm: '2.1.9' } },
    });
  });

  it('offers the link on a row that has none, and names the position once linked', async () => {
    const onOpen = vi.fn();
    renderWith(<SovLineLinkSummary line={line()} canLink onOpen={onOpen} />);
    fireEvent.click(screen.getByTestId('sov-link-open-line-1'));
    expect(onOpen).toHaveBeenCalled();

    cleanup();
    renderWith(
      <SovLineLinkSummary
        line={line({ boq_position_id: 'pos-1', classification: { nrm: '2.1.1' } })}
        canLink={false}
        onOpen={vi.fn()}
      />,
    );
    expect(await screen.findByText(/2\.1 · 2\.1\.1/)).toBeTruthy();
  });
});
