// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Header setting: what a sensor exceedance becomes in the HSE register. Hidden when the safety module is not reachable. */
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { HSE_EXCEEDANCE_MODES, fetchHseExceedanceMode, saveHseExceedanceMode, type HseExceedanceMode } from '../api';

export function HseModeSelect({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const key = ['site-sensors', 'hse-mode', projectId];
  const q = useQuery({ queryKey: key, queryFn: () => fetchHseExceedanceMode(projectId), enabled: !!projectId, retry: false });
  const save = useMutation({
    mutationFn: (mode: HseExceedanceMode) => saveHseExceedanceMode(projectId, mode),
    onSuccess: (data) => qc.setQueryData(key, data),
    onError: (e) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });
  if (!projectId || !q.data) return null;
  return (
    <label className="flex items-center gap-2 text-xs text-content-secondary">
      {t('site_sensors.hse_mode.label', { defaultValue: 'Exceedance to HSE' })}
      <select
        value={q.data.mode}
        disabled={save.isPending}
        onChange={(e) => save.mutate(e.target.value as HseExceedanceMode)}
        title={t('site_sensors.hse_mode.hint', { defaultValue: 'What a limit exceedance records in the HSE register' })}
        className="h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-sm text-content-primary"
      >
        {HSE_EXCEEDANCE_MODES.map((m) => (
          <option key={m} value={m}>
            {t(`site_sensors.hse_mode.${m}`, { defaultValue: m })}
          </option>
        ))}
      </select>
    </label>
  );
}
