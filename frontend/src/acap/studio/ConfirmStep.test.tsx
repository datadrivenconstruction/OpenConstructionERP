import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConfirmStep } from './ConfirmStep';
import type { FloorPlan } from '@/acap/planTypes';
import { saveLayout } from '@/acap/floorPlanApi';

vi.mock('@/acap/floorPlanApi', () => ({
  saveLayout: vi.fn(),
  LayoutValidationApiError: class LayoutValidationApiError extends Error {
    reasons: string[];
    constructor(reasons: string[]) {
      super('invalid');
      this.name = 'LayoutValidationApiError';
      this.reasons = reasons;
    }
  },
}));

const SAMPLE_DRAFT: FloorPlan = {
  kavling: { width_m: 12.32, length_m: 12.47 },
  levels: [
    {
      level: 1,
      rooms: [
        {
          name: 'Ruang Tamu',
          type: 'ruang_tamu',
          polygon: [
            { x: 0, y: 0 },
            { x: 5.92, y: 0 },
            { x: 5.92, y: 4.2 },
            { x: 0, y: 4.2 },
          ],
          area_m2: 24.864,
        },
      ],
      walls: [],
      openings: [],
    },
  ],
  requirement_text: '',
  jumlah_lantai: 1,
  generated_by: 'vision:gemini-2.5-flash',
  notes: '',
};

describe('ConfirmStep', () => {
  it('renders editable row with room data', () => {
    const onDraftChange = vi.fn();
    const onSaved = vi.fn();

    render(
      <ConfirmStep
        draft={SAMPLE_DRAFT}
        onDraftChange={onDraftChange}
        projectId="p1"
        onSaved={onSaved}
      />,
    );

    const nameInput = screen.getByDisplayValue('Ruang Tamu');
    expect(nameInput).toBeInTheDocument();
    expect(screen.getByDisplayValue('5.92')).toBeInTheDocument();
    expect(screen.getByDisplayValue('4.2')).toBeInTheDocument();
  });

  it('calls onDraftChange when width is edited', () => {
    const onDraftChange = vi.fn();
    const onSaved = vi.fn();

    render(
      <ConfirmStep
        draft={SAMPLE_DRAFT}
        onDraftChange={onDraftChange}
        projectId="p1"
        onSaved={onSaved}
      />,
    );

    const widthInput = screen.getByDisplayValue('5.92');
    fireEvent.change(widthInput, { target: { value: '6' } });

    expect(onDraftChange).toHaveBeenCalled();
    const updated = onDraftChange.mock.calls[0][0] as FloorPlan;
    const room = updated.levels[0].rooms[0];
    const xs = room.polygon.map((p) => p.x);
    expect(Math.max(...xs) - Math.min(...xs)).toBe(6);
  });

  it('fires onSaved with the version after a successful save', async () => {
    vi.mocked(saveLayout).mockResolvedValue({ version: 7, plan: SAMPLE_DRAFT });
    const onDraftChange = vi.fn();
    const onSaved = vi.fn();

    render(
      <ConfirmStep
        draft={SAMPLE_DRAFT}
        onDraftChange={onDraftChange}
        projectId="p1"
        onSaved={onSaved}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Simpan Layout' }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(7));
    expect(saveLayout).toHaveBeenCalledWith('p1', SAMPLE_DRAFT);
  });
});
