// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Recurring lines: every line that appears more than once in the bill (same
 * description and unit), with its occurrences and a flag when they are priced
 * differently. One rate can be applied to all occurrences at once, the unit
 * price schedule view of the bill.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Repeat, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { parsePastedNumber } from '@/shared/lib/parseDecimal';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { boqApi, type Position } from './api';
import { recurringLines, type RecurringLine } from './boqStructure';

interface RecurringLinesPanelProps {
  open: boolean;
  boqId: string;
  positions: Position[];
  readOnly?: boolean;
  onClose: () => void;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}

export function RecurringLinesPanel({ open, boqId, positions, readOnly, onClose, onDone, onError }: RecurringLinesPanelProps) {
  const { t } = useTranslation();
  const lines = useMemo(() => recurringLines(positions), [positions]);
  const ordinals = useMemo(() => new Map(positions.map((p) => [p.id, p.ordinal])), [positions]);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [rate, setRate] = useState('');
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const apply = async (line: RecurringLine) => {
    const parsed = parsePastedNumber(rate, getNumberLocale()).value;
    if (parsed === null || !Number.isFinite(parsed) || parsed < 0) {
      onError(t('boq.recurring_bad_rate', { defaultValue: 'Enter a unit rate of 0 or more.' }));
      return;
    }
    setSaving(true);
    try {
      const res = await boqApi.bulkUpdatePositions(boqId, { ids: line.ids, set_rate: String(parsed) });
      onDone(
        t('boq.recurring_applied', {
          defaultValue: 'Rate applied: {{updated}}. Left as they were: {{unchanged}}',
          updated: res.updated,
          unchanged: res.unchanged,
        }),
      );
      setOpenKey(null);
      setRate('');
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside
      className="fixed right-0 top-0 z-40 h-full w-[420px] max-w-full bg-surface-primary border-l border-border-light shadow-2xl flex flex-col"
      aria-label={t('boq.recurring_title', { defaultValue: 'Recurring lines' })}
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-light">
        <div className="flex items-center gap-2">
          <Repeat size={16} className="text-oe-blue" />
          <h2 className="text-sm font-semibold">{t('boq.recurring_title', { defaultValue: 'Recurring lines' })}</h2>
        </div>
        <button onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })} className="p-1.5 rounded-lg hover:bg-surface-secondary">
          <X size={16} className="text-content-tertiary" />
        </button>
      </div>
      <p className="px-4 py-2 text-xs text-content-secondary">
        {t('boq.recurring_hint', {
          defaultValue:
            'Lines with the same description and unit that appear more than once. Price each one once and the rate is written to every occurrence. Lines priced from resources keep their own rate.',
        })}
      </p>
      <div className="flex-1 overflow-y-auto divide-y divide-border-light">
        {lines.length === 0 && (
          <p className="px-4 py-6 text-xs text-content-tertiary">
            {t('boq.recurring_none', { defaultValue: 'No line appears more than once in this bill.' })}
          </p>
        )}
        {lines.map((line) => (
          <div key={line.key} className="px-4 py-2">
            <button
              type="button"
              className="w-full text-left flex items-start justify-between gap-2"
              onClick={() => setOpenKey(openKey === line.key ? null : line.key)}
            >
              <span className="text-xs font-medium">
                {line.description} <span className="font-mono text-content-tertiary">{line.unit}</span>
              </span>
              <span className="flex items-center gap-1 text-xs text-content-secondary whitespace-nowrap">
                {line.drifting && (
                  <AlertTriangle
                    size={13}
                    className="text-amber-600"
                    aria-label={t('boq.recurring_drifting', { defaultValue: 'Priced differently' })}
                  />
                )}
                {t('boq.recurring_count', { defaultValue: 'Occurrences: {{count}}', count: line.ids.length })}
              </span>
            </button>
            {openKey === line.key && (
              <div className="mt-2 space-y-2">
                <div className="flex flex-wrap gap-1">
                  {line.ids.map((id, i) => (
                    <span key={id} className="rounded bg-surface-secondary px-1.5 py-0.5 font-mono text-xs">
                      {ordinals.get(id)} · {line.rates[i]!.toLocaleString(getNumberLocale(), { minimumFractionDigits: 2 })}
                    </span>
                  ))}
                </div>
                {!readOnly && (
                  <div className="flex items-center gap-2">
                    <input
                      value={rate}
                      onChange={(e) => setRate(e.target.value)}
                      inputMode="decimal"
                      placeholder={t('boq.unit_rate', { defaultValue: 'Rate' })}
                      aria-label={t('boq.unit_rate', { defaultValue: 'Rate' })}
                      className="w-32 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs tabular-nums"
                    />
                    <Button variant="primary" size="sm" onClick={() => apply(line)} disabled={!rate.trim() || saving} loading={saving}>
                      {t('boq.recurring_apply', { defaultValue: 'Apply to all' })}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
