// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, Hammer, X } from 'lucide-react';
import { apiPost } from '@/shared/lib/api';

export interface StrikeSuggestion {
  status: 'pending' | 'accepted' | 'dismissed';
  strength_mpa?: number | null;
  target_mpa?: number | null;
  proposed_start?: string;
  confidence?: number;
}

/** The pending strike suggestion a concrete sensor left on an activity, if any. */
export function pendingStrike(metadata: Record<string, unknown> | null | undefined): StrikeSuggestion | null {
  const raw = metadata?.strike_suggestion;
  if (!raw || typeof raw !== 'object') return null;
  const sug = raw as StrikeSuggestion;
  return sug.status === 'pending' ? sug : null;
}

/** "Strike ready" on a Gantt row: the pour reached strike strength; a person accepts or dismisses. */
export function StrikeReadyChip({
  activityId,
  metadata,
}: {
  activityId: string;
  metadata: Record<string, unknown> | null | undefined;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const sug = pendingStrike(metadata);
  const resolve = useMutation({
    mutationFn: (action: 'accept' | 'dismiss') =>
      apiPost(`/v1/schedule/activities/${activityId}/strike-suggestion/${action}`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gantt'] }),
  });
  if (!sug) return null;
  const pct = Math.round((sug.confidence ?? 0) * 100);
  return (
    <span
      className="inline-flex shrink-0 items-center gap-0.5 rounded border border-emerald-300 bg-emerald-50 px-1 py-0.5 text-[9px] font-semibold text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
      title={t('schedule.strike_ready_tooltip', {
        defaultValue: 'Sensor estimate {{strength}} of {{target}} MPa ({{pct}}% confidence). Start the strike today?',
        strength: sug.strength_mpa ?? '-',
        target: sug.target_mpa ?? '-',
        pct,
      })}
    >
      <Hammer size={9} className="shrink-0" />
      {t('schedule.strike_ready', { defaultValue: 'Strike ready' })}
      <button
        type="button"
        disabled={resolve.isPending}
        onClick={(e) => {
          e.stopPropagation();
          resolve.mutate('accept');
        }}
        aria-label={t('schedule.strike_accept', { defaultValue: 'Start strike today' })}
        className="ml-0.5 rounded hover:bg-emerald-200/60 disabled:opacity-50"
      >
        <Check size={9} />
      </button>
      <button
        type="button"
        disabled={resolve.isPending}
        onClick={(e) => {
          e.stopPropagation();
          resolve.mutate('dismiss');
        }}
        aria-label={t('schedule.strike_dismiss', { defaultValue: 'Keep planned dates' })}
        className="rounded hover:bg-emerald-200/60 disabled:opacity-50"
      >
        <X size={9} />
      </button>
    </span>
  );
}
