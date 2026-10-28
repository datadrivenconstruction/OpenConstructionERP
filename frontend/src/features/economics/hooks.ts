// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the economics screens. One mutation helper runs a
// write, says why it failed in the reader's words, and reads everything again,
// because a change to the frame moves the key figures and the financing too.

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import { economicsKeys, getBusinessCase, getCostFrame, getFinancing, getPlan, getRegisters } from './api';

export function useEconomicsPlan(projectId: string) {
  return useQuery({ queryKey: economicsKeys.plan(projectId), queryFn: () => getPlan(projectId), enabled: !!projectId });
}

export function useBusinessCase(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: economicsKeys.businessCase(projectId),
    queryFn: () => getBusinessCase(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useCostFrame(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: economicsKeys.costFrame(projectId),
    queryFn: () => getCostFrame(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useFinancing(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: economicsKeys.financing(projectId),
    queryFn: () => getFinancing(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useRegisters(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: economicsKeys.registers(projectId),
    queryFn: () => getRegisters(projectId),
    enabled: !!projectId && enabled,
  });
}

/** Run a write, toast a refusal, and read the plan and its three views again. */
export function useEconomicsAction<TArgs>(projectId: string, run: (args: TArgs) => Promise<unknown>) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const mutation = useMutation({
    mutationFn: run,
    onSuccess: () => qc.invalidateQueries({ queryKey: economicsKeys.all(projectId) }),
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('economics.ui.action_failed', { defaultValue: 'The change was refused' }),
        message: getErrorMessage(err),
      }),
  });
  return useCallback((args: TArgs) => mutation.mutateAsync(args).catch(() => undefined), [mutation]);
}
