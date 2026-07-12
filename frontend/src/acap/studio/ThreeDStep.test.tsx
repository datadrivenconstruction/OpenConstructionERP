import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ThreeDStep } from './ThreeDStep';

vi.mock('@/acap/floorPlanApi', () => ({
  getLatestLayout: vi.fn().mockResolvedValue({
    version: 1,
    status: 'edited',
    plan: {
      kavling: { width_m: 10, length_m: 10 },
      levels: [
        {
          level: 1,
          rooms: [
            { name: 'X', type: 'ruang_tamu' as const, polygon: [{ x: 0, y: 0 }, { x: 5, y: 0 }, { x: 5, y: 4 }, { x: 0, y: 4 }], area_m2: 20 },
          ],
          walls: [],
          openings: [],
        },
      ],
      requirement_text: '',
      jumlah_lantai: 1,
      generated_by: 'test',
      notes: '',
    },
  }),
}));

describe('ThreeDStep', () => {
  it('shows fallback when WebGL is not available', async () => {
    render(<ThreeDStep projectId="p1" />);
    await waitFor(() => {
      expect(screen.getByText('3D tidak tersedia di browser ini.')).toBeTruthy();
    });
  });
});
