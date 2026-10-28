// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * <LineComposer> - add a new labour or plant line to a draft timesheet.
 *
 * The foreman picks whether the line is labour (a worker / crew) or plant
 * (a machine), chooses it, enters hours and a cost code (optionally via the
 * AI assist), flags daywork if applicable, then adds the line. Fields reset
 * after a successful add so several lines can be entered in a row.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Plus, HardHat, Wrench } from 'lucide-react';
import { Button } from '@/shared/ui';
import { Toggle } from '@/shared/ui/Toggle';
import { CostCodeAssist } from './CostCodeAssist';
import type { PickOption } from './TimesheetLineRow';
import type { LineCreatePayload, LineKind } from './api';

const fieldCls =
  'h-8 w-full rounded-lg border border-border-light bg-surface-primary px-2.5 text-sm text-content-primary';

export interface LineComposerProps {
  projectId: string;
  labour: PickOption[];
  plant: PickOption[];
  variations: PickOption[];
  onAdd: (payload: LineCreatePayload) => Promise<unknown>;
  busy?: boolean;
}

export function LineComposer({ projectId, labour, plant, variations, onAdd, busy }: LineComposerProps) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<LineKind>('labour');
  const [pickId, setPickId] = useState('');
  const [hours, setHours] = useState('');
  const [costCode, setCostCode] = useState('');
  const [wbs, setWbs] = useState('');
  const [isDaywork, setIsDaywork] = useState(false);
  const [variationId, setVariationId] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const options = kind === 'labour' ? labour : plant;

  const reset = () => {
    setPickId('');
    setHours('');
    setCostCode('');
    setWbs('');
    setIsDaywork(false);
    setVariationId('');
    setNote('');
  };

  const switchKind = (next: LineKind) => {
    if (next === kind) return;
    setKind(next);
    setPickId('');
  };

  const canAdd = pickId !== '' && !submitting && !busy;

  const handleAdd = async () => {
    if (!canAdd) return;
    const payload: LineCreatePayload = {
      hours: hours.trim() === '' ? '0' : hours.trim(),
      cost_code: costCode.trim(),
      wbs: wbs.trim() || null,
      is_daywork: isDaywork,
      variation_id: isDaywork ? variationId || null : null,
      note: note.trim() || null,
      ...(kind === 'labour' ? { resource_id: pickId } : { equipment_id: pickId }),
    };
    setSubmitting(true);
    try {
      await onAdd(payload);
      reset();
    } catch {
      // The parent mutation surfaces the error toast; keep the input intact.
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-lg border border-dashed border-border bg-surface-secondary/40 p-3">
      <div className="mb-2.5 flex items-center gap-2">
        <span className="text-xs font-semibold text-content-primary">
          {t('field_time.add_line', { defaultValue: 'Add a line' })}
        </span>
        <div className="ml-1 inline-flex overflow-hidden rounded-lg border border-border-light">
          <button
            type="button"
            onClick={() => switchKind('labour')}
            className={clsx(
              'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium transition-colors',
              kind === 'labour'
                ? 'bg-oe-blue text-content-inverse'
                : 'bg-surface-primary text-content-secondary hover:bg-surface-secondary',
            )}
          >
            <HardHat size={13} />
            {t('field_time.kind_labour', { defaultValue: 'Labour' })}
          </button>
          <button
            type="button"
            onClick={() => switchKind('plant')}
            className={clsx(
              'inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium transition-colors',
              kind === 'plant'
                ? 'bg-oe-blue text-content-inverse'
                : 'bg-surface-primary text-content-secondary hover:bg-surface-secondary',
            )}
          >
            <Wrench size={13} />
            {t('field_time.kind_plant', { defaultValue: 'Plant' })}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-12 lg:items-end">
        <label className="col-span-2 lg:col-span-3">
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {kind === 'labour'
              ? t('field_time.worker', { defaultValue: 'Worker / crew' })
              : t('field_time.machine', { defaultValue: 'Machine' })}
          </span>
          <select value={pickId} className={fieldCls} onChange={(e) => setPickId(e.target.value)}>
            <option value="">
              {kind === 'labour'
                ? t('field_time.select_worker', { defaultValue: 'Select worker / crew' })
                : t('field_time.select_machine', { defaultValue: 'Select machine' })}
            </option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <label className="lg:col-span-1">
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {t('field_time.hours', { defaultValue: 'Hours' })}
          </span>
          <input
            type="number"
            min="0"
            step="0.25"
            value={hours}
            className={clsx(fieldCls, 'tabular-nums')}
            onChange={(e) => setHours(e.target.value)}
          />
        </label>

        <div className="col-span-2 lg:col-span-3">
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {t('field_time.cost_code', { defaultValue: 'Cost code' })}
          </span>
          <div className="flex items-center gap-1.5">
            <input
              value={costCode}
              className={fieldCls}
              placeholder={t('field_time.cost_code_placeholder', { defaultValue: 'e.g. 03.30' })}
              onChange={(e) => setCostCode(e.target.value)}
            />
            <CostCodeAssist
              projectId={projectId}
              defaultText={note || undefined}
              onApply={(code) => setCostCode(code)}
            />
          </div>
        </div>

        <label className="lg:col-span-1">
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {t('field_time.wbs', { defaultValue: 'WBS' })}
          </span>
          <input value={wbs} className={fieldCls} onChange={(e) => setWbs(e.target.value)} />
        </label>

        <label className="col-span-2 lg:col-span-2">
          <span className="mb-1 block text-2xs font-medium text-content-tertiary">
            {t('field_time.note', { defaultValue: 'Note' })}
          </span>
          <input value={note} className={fieldCls} onChange={(e) => setNote(e.target.value)} />
        </label>

        <div className="flex justify-end lg:col-span-2">
          <Button
            type="button"
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            loading={submitting}
            disabled={!canAdd}
            onClick={handleAdd}
          >
            {t('field_time.add_line_action', { defaultValue: 'Add line' })}
          </Button>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Toggle
          checked={isDaywork}
          size="sm"
          onChange={setIsDaywork}
          label={t('field_time.daywork_flag', { defaultValue: 'Daywork' })}
        />
        {isDaywork && (
          <select
            value={variationId}
            className={clsx(fieldCls, 'max-w-xs')}
            onChange={(e) => setVariationId(e.target.value)}
          >
            <option value="">
              {t('field_time.variation_none', { defaultValue: 'No variation' })}
            </option>
            {variations.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
