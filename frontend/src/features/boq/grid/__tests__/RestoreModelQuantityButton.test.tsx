// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/features/bim/api', () => ({ restoreModelQuantity: vi.fn() }));

import { restoreModelQuantity } from '@/features/bim/api';
import { useToastStore } from '@/stores/useToastStore';
import { RestoreModelQuantityButton } from '../RestoreModelQuantityButton';

const restore = vi.mocked(restoreModelQuantity);

afterEach(() => {
  cleanup();
  restore.mockReset();
  useToastStore.setState({ toasts: [] });
});

function mount() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <RestoreModelQuantityButton positionId="p1" boqId="b1" manualQuantity="12" modelQuantity="4.0000" unit="m3" />
    </QueryClientProvider>,
  );
}

describe('RestoreModelQuantityButton', () => {
  it('asks first and changes nothing when the person cancels', async () => {
    mount();
    fireEvent.click(screen.getByTestId('restore-model-qty-p1'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain('12');
    expect(dialog.textContent).toContain('4.0000 m3');
    const cancel = within(dialog).getAllByRole('button').find((b) => b.dataset.testid !== 'confirm-dialog-confirm')!;
    fireEvent.click(cancel);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(restore).not.toHaveBeenCalled();
  });

  it('restores after confirmation and shows where the figure came from', async () => {
    restore.mockResolvedValue({
      position_id: 'p1',
      quantity: '4.0000',
      unit: 'm3',
      provenance: { formula: 'sum(volume_m3) x 1 [m3 -> m3]', element_count: 2, manual_kept: false, applied_quantity: '4.0000' },
    });
    mount();
    fireEvent.click(screen.getByTestId('restore-model-qty-p1'));
    fireEvent.click(await screen.findByTestId('confirm-dialog-confirm'));
    await waitFor(() => expect(restore).toHaveBeenCalledWith('p1'));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0]!;
    expect(toast.type).toBe('success');
    expect(toast.title).toBe('Model quantity restored: 4.0000 m3');
    expect(toast.message).toBe('Linked elements: 2. Formula: sum(volume_m3) x 1 [m3 -> m3]');
  });
});
