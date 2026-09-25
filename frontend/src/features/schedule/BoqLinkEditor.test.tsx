// @ts-nocheck
/**
 * The BOQ link picker in the activity panel. Network is stubbed on the
 * schedule ``./api`` module. Linking sends the chosen position, unlinking
 * sends the linked one, and section headers and already linked positions are
 * not offered.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    scheduleApi: {
      listProjectBoqs: vi.fn(),
      getBoqPositions: vi.fn(),
      getBoqPosition: vi.fn(),
      linkPosition: vi.fn(),
      unlinkPosition: vi.fn(),
    },
  };
});

import { scheduleApi } from './api';
import { BoqLinkEditor } from './BoqLinkEditor';

const SECTION = { id: 'sec', boq_id: 'b1', parent_id: null, ordinal: '01', description: 'Earthworks', unit: '', quantity: '0' };
const DIG = { id: 'p1', boq_id: 'b1', parent_id: 'sec', ordinal: '01.001', description: 'Excavation', unit: 'm3', quantity: '120' };
const FILL = { id: 'p2', boq_id: 'b1', parent_id: 'sec', ordinal: '01.002', description: 'Backfill', unit: 'm3', quantity: '40' };

function renderEditor(linked: string[] = []) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const activity = { id: 'act1', name: 'Groundworks', boq_position_ids: linked };
  return render(
    <QueryClientProvider client={qc}>
      <BoqLinkEditor scheduleId="s1" projectId="proj1" activity={activity} />
    </QueryClientProvider>,
  );
}

describe('BoqLinkEditor', () => {
  beforeEach(() => {
    vi.mocked(scheduleApi.listProjectBoqs).mockResolvedValue([{ id: 'b1', name: 'Main bill' }]);
    vi.mocked(scheduleApi.getBoqPositions).mockResolvedValue([SECTION, DIG, FILL]);
    vi.mocked(scheduleApi.linkPosition).mockResolvedValue({});
    vi.mocked(scheduleApi.unlinkPosition).mockResolvedValue({});
    vi.mocked(scheduleApi.getBoqPosition).mockReset();
  });

  it('links the chosen position and offers neither sections nor linked positions', async () => {
    renderEditor(['p2']);
    const select = await screen.findByTestId('boq-link-position');
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(2));
    const values = within(select)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(values).toEqual(['', 'p1']);

    fireEvent.change(select, { target: { value: 'p1' } });
    fireEvent.click(screen.getByTestId('boq-link-submit'));
    await waitFor(() => expect(scheduleApi.linkPosition).toHaveBeenCalledWith('act1', 'p1'));
  });

  it('shows a linked position by its ordinal and removes it', async () => {
    renderEditor(['p1']);
    const row = await screen.findByTestId('boq-link-row-p1');
    await waitFor(() => expect(row.textContent).toContain('Excavation'));
    fireEvent.click(screen.getByTestId('boq-link-remove-p1'));
    await waitFor(() => expect(scheduleApi.unlinkPosition).toHaveBeenCalledWith('act1', 'p1'));
  });

  it('fetches a linked position that is not in the open BOQ', async () => {
    vi.mocked(scheduleApi.getBoqPosition).mockResolvedValue({
      id: 'x9', boq_id: 'b2', parent_id: null, ordinal: '09.001', description: 'Roof membrane', unit: 'm2', quantity: '300',
    });
    renderEditor(['x9']);
    const row = await screen.findByTestId('boq-link-row-x9');
    await waitFor(() => expect(row.textContent).toContain('Roof membrane'));
    expect(scheduleApi.getBoqPosition).toHaveBeenCalledWith('x9');
  });

  it('narrows the choice by the search text', async () => {
    renderEditor();
    const select = await screen.findByTestId('boq-link-position');
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(3));
    fireEvent.change(screen.getByTestId('boq-link-search'), { target: { value: 'back' } });
    const values = within(select)
      .getAllByRole('option')
      .map((o) => o.getAttribute('value'));
    expect(values).toEqual(['', 'p2']);
  });
});
