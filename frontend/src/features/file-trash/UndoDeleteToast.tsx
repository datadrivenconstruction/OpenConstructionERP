// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Helper to fire an "Undo" toast after a successful soft-delete.
 *
 * This module exports a single function rather than a component
 * because the global toast surface is rendered by ``useToastStore``
 * — we just push a toast with an ``action`` payload that calls the
 * restore mutation.
 */

import type { TFunction } from 'i18next';
import { useToastStore } from '@/stores/useToastStore';

interface ShowUndoDeleteToastArgs {
  /** Name shown in the toast title. */
  fileName: string;
  /** ID of the trash row to restore when the user clicks Undo. */
  trashId: string;
  /** Bound to the restore mutation — invoked with ``trashId`` on click. */
  onUndo: (trashId: string) => void;
  t: TFunction;
  /** Auto-dismiss the toast after this many ms (default: 8s — gives the user time to react). */
  durationMs?: number;
}

export function showUndoDeleteToast({
  fileName,
  trashId,
  onUndo,
  t,
  durationMs = 8_000,
}: ShowUndoDeleteToastArgs): string {
  const addToast = useToastStore.getState().addToast;
  return addToast(
    {
      type: 'info',
      title: t('files.trash.toast.deleted_title', {
        defaultValue: 'Moved to Recycle Bin',
      }),
      message: t('files.trash.toast.deleted_message', {
        defaultValue: '{{name}} can be restored within 30 days.',
        name: fileName,
      }),
      action: {
        label: t('files.trash.toast.undo', { defaultValue: 'Undo' }),
        onClick: () => onUndo(trashId),
      },
    },
    { duration: durationMs },
  );
}
