// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Excel round-trip review: the dialog lists the changed, new, removed and
// conflicting rows, preselects nothing that deletes or overwrites, and the
// Apply button sends the skip / accept / delete lists the server expects.

import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  fetchWithAuth: vi.fn(),
}));

import { applyFields, hasReviewableChanges, type ExcelReviewPreview } from './excelReviewApi';
import { applyCount, buildChoices, EMPTY_REVIEW_STATE, firstTab } from './excelReviewText';
import { ExcelReviewDialog } from './ExcelReviewDialog';

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';
const C = '33333333-3333-4333-8333-333333333333';
const D = '44444444-4444-4444-8444-444444444444';

function preview(over: Partial<ExcelReviewPreview> = {}): ExcelReviewPreview {
  return {
    round_trip: true,
    created: [{ row: 9, ordinal: '09.001', description: 'Brand new line' }],
    updated: [{ row: 2, position_id: A, ordinal: '01.001', changes: [{ field: 'quantity', old: '10', new: '12.5' }] }],
    unchanged: 3,
    would_delete: [{ position_id: C, ordinal: '01.003', description: 'Dropped beam' }],
    conflicts: [
      {
        row: 4,
        position_id: B,
        ordinal: '01.002',
        stored_version: 4,
        file_version: 2,
        changes: [{ field: 'description', old: 'Wall', new: 'Wall, reinforced' }],
      },
    ],
    problems: [],
    errors: [],
    counts: { created: 1, updated: 1, unchanged: 3, would_delete: 1, conflicts: 1 },
    truncated: { created: false, updated: false, would_delete: false, conflicts: false },
    boq_version_token: 'abc',
    ...over,
  };
}

describe('excel review state', () => {
  it('preselects nothing that deletes or overwrites', () => {
    const p = preview();
    // One plain edit and one new row; the conflict stays on the app value and nothing is deleted.
    expect(applyCount(p, EMPTY_REVIEW_STATE)).toBe(2);
    expect(buildChoices(p, EMPTY_REVIEW_STATE)).toEqual({ skipIds: [B], acceptIds: [], deleteIds: [] });
  });

  it('opens on the conflicts when there are any', () => {
    expect(firstTab(preview())).toBe('conflicts');
    expect(firstTab(preview({ counts: { created: 0, updated: 2, unchanged: 0, would_delete: 0, conflicts: 0 } }))).toBe('changed');
  });

  it('is only worth showing for a round trip with something to decide', () => {
    expect(hasReviewableChanges(preview())).toBe(true);
    expect(hasReviewableChanges(preview({ round_trip: false }))).toBe(false);
    expect(
      hasReviewableChanges(preview({ counts: { created: 0, updated: 0, unchanged: 5, would_delete: 0, conflicts: 0 } })),
    ).toBe(false);
  });

  it('writes the choices as the form fields the apply call reads', () => {
    expect(applyFields({ skipIds: [A], acceptIds: [B], deleteIds: [C, D] })).toEqual({
      skip_position_ids: JSON.stringify([A]),
      accept_position_ids: JSON.stringify([B]),
      delete_position_ids: JSON.stringify([C, D]),
    });
  });
});

describe('ExcelReviewDialog', () => {
  it('renders the four groups with their counts and the apply total', () => {
    render(<ExcelReviewDialog open preview={preview()} onApply={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Changed: 1' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'New: 1' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Removed in Excel: 1' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Conflicts: 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Apply changes (2)' })).toBeTruthy();
  });

  it('shows the conflict with "Keep app value" selected by default', () => {
    render(<ExcelReviewDialog open preview={preview()} onApply={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText(/Changed in the app since export/)).toBeTruthy();
    const keep = screen.getByLabelText('Keep app value') as HTMLInputElement;
    const use = screen.getByLabelText('Use Excel value') as HTMLInputElement;
    expect(keep.checked).toBe(true);
    expect(use.checked).toBe(false);
  });

  it('lists removed rows unticked under "Delete from BOQ"', () => {
    render(<ExcelReviewDialog open preview={preview()} onApply={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Removed in Excel: 1' }));
    expect(screen.getByText('Dropped beam')).toBeTruthy();
    expect(screen.getByText('Delete from BOQ')).toBeTruthy();
    const box = screen.getByRole('checkbox') as HTMLInputElement;
    expect(box.checked).toBe(false);
  });

  it('sends the skip, accept and delete lists the person chose', () => {
    const onApply = vi.fn();
    render(<ExcelReviewDialog open preview={preview()} onApply={onApply} onCancel={vi.fn()} />);

    // Default: the conflict is skipped, nothing is accepted or deleted.
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes (2)' }));
    expect(onApply).toHaveBeenLastCalledWith({ skipIds: [B], acceptIds: [], deleteIds: [] });

    // Use the Excel value for the conflict and tick the removed row.
    fireEvent.click(screen.getByLabelText('Use Excel value'));
    fireEvent.click(screen.getByRole('tab', { name: 'Removed in Excel: 1' }));
    fireEvent.click(screen.getByRole('checkbox'));
    // Untick the plain edit.
    fireEvent.click(screen.getByRole('tab', { name: 'Changed: 1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Apply this change 01\.001/ }));

    // New row (1) + accepted conflict (1) + deletion (1); the plain edit is unticked.
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes (3)' }));
    expect(onApply).toHaveBeenLastCalledWith({ skipIds: [A], acceptIds: [B], deleteIds: [C] });
  });

  it('disables Apply when nothing would change', () => {
    const only = preview({
      created: [],
      updated: [],
      would_delete: [],
      conflicts: [],
      counts: { created: 0, updated: 0, unchanged: 5, would_delete: 0, conflicts: 0 },
    });
    render(<ExcelReviewDialog open preview={only} onApply={vi.fn()} onCancel={vi.fn()} />);
    expect((screen.getByRole('button', { name: 'Apply changes (0)' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
