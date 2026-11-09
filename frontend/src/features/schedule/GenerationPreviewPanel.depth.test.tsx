// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { GenerationPreviewPanel } from './GenerationPreviewPanel';
import type { GenerationPreview } from './api';

function preview(extra: Partial<GenerationPreview> = {}): GenerationPreview {
  return {
    boq_id: 'b1',
    boq_name: 'Bill',
    boq_estimate_type: null,
    activity_count: 40,
    positions_scheduled: 30,
    lump_sum_positions: 0,
    summary_count: 8,
    estimated_count: 0,
    skipped_count: 0,
    note_counts: {},
    crews: 2,
    compressed_pct: null,
    fits: true,
    planned_start: '2026-05-04',
    planned_end: '2026-09-04',
    requested_end: null,
    warnings: [],
    existing_activity_count: 0,
    existing_started_count: 0,
    notes: [],
    max_depth: 3,
    rollup_depth: 0,
    rolled_up_count: 0,
    hours_per_day: 7.5,
    hours_source: 'calendar',
    ...extra,
  } as GenerationPreview;
}

describe('GenerationPreviewPanel depth', () => {
  it('offers one level fewer than the bill has, and the whole bill', () => {
    const onDepthChange = vi.fn();
    render(<GenerationPreviewPanel preview={preview()} depth={null} onDepthChange={onDepthChange} />);
    const select = screen.getByTestId('generate-depth') as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['', '1', '2']);
    fireEvent.change(select, { target: { value: '1' } });
    expect(onDepthChange).toHaveBeenCalledWith(1);
    fireEvent.change(select, { target: { value: '' } });
    expect(onDepthChange).toHaveBeenLastCalledWith(null);
  });

  it('has no depth choice for a bill with a single level of sections', () => {
    render(<GenerationPreviewPanel preview={preview({ max_depth: 1 })} depth={null} onDepthChange={vi.fn()} />);
    expect(screen.queryByTestId('generate-depth')).toBeNull();
  });

  it('says which hours a day turn labour into days', () => {
    render(<GenerationPreviewPanel preview={preview()} />);
    expect(screen.getByTestId('preview-hours-per-day').textContent).toContain('7');
  });
});
