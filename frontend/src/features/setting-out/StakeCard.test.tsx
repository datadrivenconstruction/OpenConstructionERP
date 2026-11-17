// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The phone card from the Riverside Yard lessons: typing the measured values
 * shows the verdict at once (C-04 Pass at 5 mm, C-03 Fail at 15 mm), Save sends
 * the typed numbers, and a saved fail offers Create NCR draft.
 */
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import type { Stake, StakeRecord } from './api';

const recordStake = vi.fn();
const createNcrDraft = vi.fn();
vi.mock('./api', async (orig) => ({
  ...(await orig<typeof import('./api')>()),
  recordStake: (...a: unknown[]) => recordStake(...a),
  createNcrDraft: (...a: unknown[]) => createNcrDraft(...a),
}));

const { StakeCard } = await import('./StakeCard');

const stake = (pid: string, e: number, latest: StakeRecord | null = null): Stake => ({
  id: `s-${pid}`,
  point_id: pid,
  design_e: e,
  design_n: 5819030,
  design_z: 34.3,
  chainage: null,
  offset_m: null,
  code: 'COL',
  verdict: latest ? latest.verdict : 'open',
  latest,
  record_count: latest ? 1 : 0,
});

const failed: StakeRecord = {
  id: 'r1',
  point_id: 's-C-03',
  measured_e: 389060.012,
  measured_n: 5819029.991,
  measured_z: 34.302,
  de_mm: 12,
  dn_mm: -9,
  d_mm: 15,
  dz_mm: 2,
  tol_h_mm: 10,
  tol_v_mm: 10,
  verdict: 'fail',
  instrument: 'Demo total station',
  control_ref: 'CP1, CP2',
  measured_by: 'Demo surveyor',
  measured_at: '2026-10-12T09:00:00Z',
  note: '',
  ncr_id: null,
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function type(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

const props = { tolH: 10, tolV: 10, instrument: 'Demo total station', controlRef: 'CP1, CP2' };

describe('StakeCard', () => {
  beforeEach(() => {
    recordStake.mockReset().mockResolvedValue(failed);
    createNcrDraft.mockReset().mockResolvedValue({ ncr_id: 'n1', ncr_number: 'NCR-001', record_id: 'r1' });
  });

  it('shows Pass for C-04 while typing (lesson 2)', () => {
    wrap(<StakeCard stake={stake('C-04', 389080)} {...props} />);
    expect(screen.getByTestId('stake-verdict').textContent).toContain('Open');
    type(/Measured E/, '389080.004');
    type(/Measured N/, '5819029,997');
    type(/Measured Z/, '34.298');
    expect(screen.getByTestId('stake-verdict').textContent).toContain('Pass');
    expect(screen.getByTestId('stake-d').textContent).toBe('5');
  });

  it('shows Fail for C-03 and saves the typed numbers (lesson 3)', async () => {
    wrap(<StakeCard stake={stake('C-03', 389060)} {...props} />);
    expect((screen.getByTestId('stake-save') as HTMLButtonElement).disabled).toBe(true);
    type(/Measured E/, '389060.012');
    type(/Measured N/, '5819029.991');
    expect(screen.getByTestId('stake-verdict').textContent).toContain('Fail');
    expect(screen.getByTestId('stake-d').textContent).toBe('15');
    fireEvent.click(screen.getByTestId('stake-save'));
    await waitFor(() => expect(recordStake).toHaveBeenCalledTimes(1));
    expect(recordStake.mock.calls[0]).toEqual([
      's-C-03',
      { measured_e: 389060.012, measured_n: 5819029.991, measured_z: null, instrument: 'Demo total station', control_ref: 'CP1, CP2' },
    ]);
  });

  it('offers Create NCR draft on a saved fail', async () => {
    wrap(<StakeCard stake={stake('C-03', 389060, failed)} {...props} />);
    expect(screen.getByTestId('stake-verdict').textContent).toContain('Fail');
    fireEvent.click(screen.getByTestId('stake-create-ncr'));
    await waitFor(() => expect(createNcrDraft).toHaveBeenCalledWith('r1', expect.any(String)));
  });

  it('has no NCR button once the draft exists, and no inputs for a viewer', () => {
    wrap(<StakeCard stake={stake('C-03', 389060, { ...failed, ncr_id: 'n1' })} {...props} canWrite={false} />);
    expect(screen.queryByTestId('stake-create-ncr')).toBeNull();
    expect(screen.queryByTestId('stake-save')).toBeNull();
  });
});
