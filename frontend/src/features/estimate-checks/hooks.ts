// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useModuleStore } from '@/stores/useModuleStore';
import { estimateChecksApi, type CheckResponse, type CheckSettings, type DisplayMode } from './api';

export const MODULE_KEY = 'estimate-checks';

const keys = {
  check: (boqId: string) => ['estimate-checks', 'check', boqId] as const,
  settings: ['estimate-checks', 'settings'] as const,
  preference: ['estimate-checks', 'preference'] as const,
};

/** True when the estimate-check module is switched on in System Modules. */
export function useEstimateChecksEnabled(): boolean {
  return useModuleStore((s) => s.isModuleEnabled(MODULE_KEY));
}

/** The caller's display preference. A missing backend module reads as "off". */
export function useDisplayMode(enabled: boolean) {
  return useQuery({
    queryKey: keys.preference,
    queryFn: async (): Promise<DisplayMode> => {
      try {
        return (await estimateChecksApi.preference()).display_mode;
      } catch {
        return 'off';
      }
    },
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useSaveDisplayMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: DisplayMode) => estimateChecksApi.savePreference(mode),
    onSuccess: (res) => qc.setQueryData(keys.preference, res.display_mode),
  });
}

export function useEstimateCheck(boqId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: keys.check(boqId ?? ''),
    queryFn: () => estimateChecksApi.check(boqId as string),
    enabled: enabled && Boolean(boqId),
    staleTime: 30_000,
    retry: false,
  });
}

export function useAcceptFinding(boqId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kpiId, reason }: { kpiId: string; reason: string }) =>
      estimateChecksApi.accept(boqId, kpiId, reason),
    onSuccess: (res: CheckResponse) => qc.setQueryData(keys.check(boqId), res),
  });
}

export function useWithdrawAcceptance(boqId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (kpiId: string) => estimateChecksApi.withdraw(boqId, kpiId),
    onSuccess: (res: CheckResponse) => qc.setQueryData(keys.check(boqId), res),
  });
}

export function useCheckSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: estimateChecksApi.settings });
}

export function useSaveCheckSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CheckSettings) => estimateChecksApi.saveSettings(body),
    onSuccess: (res) => {
      qc.setQueryData(keys.settings, res);
      qc.invalidateQueries({ queryKey: ['estimate-checks', 'check'] });
    },
  });
}
