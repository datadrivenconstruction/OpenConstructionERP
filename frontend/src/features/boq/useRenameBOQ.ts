// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Rename an estimate. One mutation for the editor header and the list rows,
 * so both toast the same way and both refresh every query that shows the name.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { useToastStore } from '@/stores/useToastStore';
import { boqApi } from './api';
import { editorErrorText } from './editorErrorText';

export function useRenameBOQ(onDone?: () => void) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  return useMutation({
    mutationFn: ({ boqId, name }: { boqId: string; name: string }) => boqApi.update(boqId, { name }),
    onSuccess: (_data, { boqId }) => {
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      addToast({ type: 'success', title: t('boq.rename_saved', { defaultValue: 'Estimate renamed' }) });
      onDone?.();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.rename_failed', { defaultValue: 'Could not rename the estimate' }),
        message: editorErrorText(err, t),
      });
    },
  });
}
