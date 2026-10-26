// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Proportional scaling proposes and a person confirms. Pinned here: the scope
// is measured on open and the target starts at the current total, nothing is
// written before the preview, apply sends the factor the person saw, and a
// refusal is worded from its code.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('./resourceScalingApi', async (orig) => ({
  ...(await orig<typeof import('./resourceScalingApi')>()),
  previewScaling: vi.fn(),
  applyScaling: vi.fn(),
  scalingErrorCode: (err: unknown) => (err as { code?: string }).code ?? null,
}));
vi.mock('./api', () => ({ boqApi: { restoreSnapshot: vi.fn() } }));

import * as api from './resourceScalingApi';
import { ResourceScalingDialog } from './ResourceScalingDialog';

const previewMock = vi.mocked(api.previewScaling);
const applyMock = vi.mocked(api.applyScaling);

function plan(over: Partial<api.ScalePlan> = {}): api.ScalePlan {
  return {
    metric: 'hours',
    target: '40',
    current: '40',
    fixed: '0',
    scalable: '40',
    factor: '1',
    achieved: '40',
    drift: '0',
    rounding: { decimals: 3, mode: 'half_up' },
    units: ['h'],
    warnings: [],
    counts: { scaled: 0, locked: 0, excluded: 0, no_match: 0 },
    lines: [],
    ...over,
  };
}

const SCALED = plan({
  target: '20',
  factor: '0.5',
  achieved: '20',
  counts: { scaled: 1, locked: 1, excluded: 0, no_match: 0 },
  lines: [
    {
      id: 'p1',
      ordinal: '01.0010',
      description: 'Walls',
      status: 'scaled',
      old_value: '20',
      new_value: '10',
      changes: [{ index: 0, name: 'Mason', type: 'labor', unit: 'h', old_quantity: '2', new_quantity: '1' }],
    },
    { id: 'p2', ordinal: '01.0020', description: 'Slabs', status: 'locked', old_value: '20', new_value: '20', changes: [] },
  ],
});

describe('ResourceScalingDialog', () => {
  beforeEach(() => {
    previewMock.mockReset();
    applyMock.mockReset();
  });

  it('measures, previews and applies with the factor that was shown', async () => {
    previewMock.mockResolvedValueOnce(plan()).mockResolvedValueOnce(SCALED);
    applyMock.mockResolvedValue({ plan: SCALED, snapshot_id: 's1', updated: 1 });
    const onApplied = vi.fn();
    render(
      <ResourceScalingDialog open boqId="b1" scope={{ sectionId: 'sec', label: '01 Shell' }} onClose={vi.fn()} onApplied={onApplied} />,
    );
    await waitFor(() => expect(screen.getByDisplayValue('40')).toBeInTheDocument());
    expect(previewMock).toHaveBeenCalledWith('b1', expect.objectContaining({ sectionId: 'sec', target: null, metric: 'hours' }));
    const apply = screen.getByRole('button', { name: 'Apply' });
    expect(apply).toBeDisabled();

    fireEvent.change(screen.getByDisplayValue('40'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByTestId('scaling-preview')).toBeInTheDocument());
    expect(screen.getByText('Mason:', { exact: false })).toBeInTheDocument();
    expect(screen.getByLabelText('Locked line')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(applyMock).toHaveBeenCalled());
    expect(applyMock.mock.calls[0]![1]).toEqual(expect.objectContaining({ target: '20', expectedFactor: '0.5' }));
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
  });

  it('unticking a line previews again with it excluded', async () => {
    previewMock.mockResolvedValueOnce(plan()).mockResolvedValue(SCALED);
    render(<ResourceScalingDialog open boqId="b1" scope={{ sectionId: 'sec', label: 'S' }} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByDisplayValue('40')).toBeInTheDocument());
    fireEvent.change(screen.getByDisplayValue('40'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByTestId('scaling-preview')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include this position' }));
    await waitFor(() =>
      expect(previewMock).toHaveBeenLastCalledWith('b1', expect.objectContaining({ excludedPositionIds: ['p1'] })),
    );
  });

  it('words a refusal from its code', async () => {
    previewMock.mockRejectedValue({ code: 'scaling_nothing_to_scale' });
    render(<ResourceScalingDialog open boqId="b1" scope={{ resourceType: 'material', label: 'Material' }} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/Nothing in this scope can be scaled/)).toBeInTheDocument());
  });
});
