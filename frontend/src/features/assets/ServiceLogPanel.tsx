// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Service-log panel for a single asset.
 *
 * Shows the computed maintenance status (ok / due / overdue, derived from
 * the asset's interval + last service) and the service history, and lets
 * the user append a maintenance event. The append rides
 * ``POST /v1/assets/{id}/service-log``, which persists into the existing
 * ``asset_info.service_log`` JSON and returns the recomputed health, so
 * the status badge updates without a manual refresh.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, Wrench } from 'lucide-react';

import { Button, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { appendServiceLog, type AssetHealth, type MaintenanceStatus } from './api';

// English fallbacks for the computed `assets.maint.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const ASSETS_MAINT_LABELS: Record<string, string> = {
  ok: 'OK', due: 'Due', overdue: 'Overdue', unknown: 'Unknown'
};


interface ServiceLogPanelProps {
  assetId: string;
  /** Initial history from the parent (asset_info.service_log). */
  initialLog?: Array<Record<string, unknown>>;
  initialHealth?: AssetHealth | null;
}

const MAINT_TONE: Record<MaintenanceStatus, string> = {
  ok: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  due: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  overdue: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  unknown: 'bg-neutral-700/40 text-neutral-300 border-neutral-600/50',
};

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function ServiceLogPanel({ assetId, initialLog = [], initialHealth }: ServiceLogPanelProps) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [log, setLog] = useState<Array<Record<string, unknown>>>(initialLog);
  const [health, setHealth] = useState<AssetHealth | null>(initialHealth ?? null);
  const [date, setDate] = useState(todayIso());
  const [note, setNote] = useState('');
  const [kind, setKind] = useState('service');

  const mutation = useMutation({
    mutationFn: () => appendServiceLog(assetId, { date, note: note.trim(), kind }),
    onSuccess: (res) => {
      setLog(res.service_log);
      setHealth(res.health);
      setNote('');
      queryClient.invalidateQueries({ queryKey: ['bim-assets'] });
      queryClient.invalidateQueries({ queryKey: ['asset-portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['asset-ops-list'] });
      toast({
        type: 'success',
        title: t('assets.service.logged', { defaultValue: 'Service event logged' }),
      });
    },
    onError: (err: unknown) => {
      toast({
        type: 'error',
        title: t('assets.service.failed', { defaultValue: 'Could not log service event' }),
        message: err instanceof Error ? err.message : undefined,
      });
    },
  });

  const maint = health?.maintenance_status ?? 'unknown';

  return (
    <section data-testid="service-log-panel">
      <header className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
          <Wrench size={13} className="text-amber-400" />
          <span>{t('assets.service.title', { defaultValue: 'Maintenance & service log' })}</span>
        </div>
        <span className={`rounded-md border px-2 py-0.5 text-[11px] ${MAINT_TONE[maint]}`}>
          {t(`assets.maint.${maint}`, { defaultValue: ASSETS_MAINT_LABELS[maint] ?? maint })}
          {health?.next_maintenance_due
            ? ` · ${t('assets.service.next_due', {
                defaultValue: 'next {{date}}',
                date: health.next_maintenance_due,
              })}`
            : ''}
        </span>
      </header>

      {/* Add entry */}
      <div className="mb-3 flex flex-wrap items-end gap-2 rounded-md border border-border-light bg-surface-secondary/40 p-2">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-content-tertiary">
            {t('assets.service.date', { defaultValue: 'Date' })}
          </label>
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="service-date" />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-content-tertiary">
            {t('assets.service.kind', { defaultValue: 'Type' })}
          </label>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
            data-testid="service-kind"
          >
            <option value="service">{t('assets.service.kind_service', { defaultValue: 'Service' })}</option>
            <option value="repair">{t('assets.service.kind_repair', { defaultValue: 'Repair' })}</option>
            <option value="inspection">{t('assets.service.kind_inspection', { defaultValue: 'Inspection' })}</option>
            <option value="replacement">{t('assets.service.kind_replacement', { defaultValue: 'Replacement' })}</option>
          </select>
        </div>
        <div className="flex flex-1 flex-col gap-1" style={{ minWidth: 180 }}>
          <label className="text-[10px] text-content-tertiary">
            {t('assets.service.note', { defaultValue: 'What was done' })}
          </label>
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('assets.service.note_ph', { defaultValue: 'e.g. Replaced filter, checked belts' })}
            data-testid="service-note"
          />
        </div>
        <Button
          onClick={() => mutation.mutate()}
          disabled={!note.trim() || mutation.isPending}
          data-testid="service-add"
        >
          {mutation.isPending ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Plus size={14} className="mr-1" />}
          {t('assets.service.add', { defaultValue: 'Log' })}
        </Button>
      </div>

      {/* History */}
      {log.length === 0 ? (
        <p className="py-2 text-xs italic text-content-tertiary">
          {t('assets.service.empty', { defaultValue: 'No service history yet.' })}
        </p>
      ) : (
        <ul className="space-y-1">
          {[...log]
            .reverse()
            .map((entry, i) => (
              <li
                key={`${String(entry.date)}-${i}`}
                className="flex items-start justify-between gap-3 rounded border border-border-light bg-surface-secondary/50 px-2 py-1 text-[12px]"
              >
                <div className="min-w-0">
                  <span className="font-medium text-content-primary">{String(entry.note ?? '')}</span>
                  {entry.performed_by ? (
                    <span className="ml-1 text-content-tertiary">— {String(entry.performed_by)}</span>
                  ) : null}
                </div>
                <div className="shrink-0 text-right text-content-tertiary">
                  <span className="mr-1 rounded bg-surface-tertiary px-1 py-0.5 text-[10px] uppercase">
                    {String(entry.kind ?? 'service')}
                  </span>
                  {String(entry.date ?? '')}
                </div>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}

export default ServiceLogPanel;
