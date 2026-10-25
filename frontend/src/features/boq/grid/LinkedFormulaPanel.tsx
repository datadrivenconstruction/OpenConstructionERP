// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { boqApi, type QuantityAggregation } from '../api';
import {
  buildFormulaLinkPayload,
  collectFormulaVars,
  previewFormula,
  type FormulaElementInput,
} from './formula/linkedFormula';

const AGGREGATIONS: QuantityAggregation[] = ['sum', 'max', 'min', 'count'];

interface Props {
  elements: FormulaElementInput[];
  modelId: string;
  /** Stable ids of the linked elements, as the backend expects them. */
  elementStableIds: string[];
  boqId?: string;
  positionId: string;
  currentQuantity: number;
  /** Writes the quantity once and records the formula on the position metadata. */
  onSetQuantity: (value: number, formula: string, aggregation: QuantityAggregation) => void;
  onLinked?: () => void;
}

const fmt = (n: number) =>
  Number.isInteger(n) ? String(n) : n.toLocaleString(undefined, { maximumFractionDigits: 4 });

export function LinkedFormulaPanel({
  elements,
  modelId,
  elementStableIds,
  boqId,
  positionId,
  currentQuantity,
  onSetQuantity,
  onLinked,
}: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [formula, setFormula] = useState('');
  const [agg, setAgg] = useState<QuantityAggregation>('sum');
  const [pending, setPending] = useState<'set' | 'link' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chips = useMemo(() => collectFormulaVars(elements), [elements]);
  const preview = useMemo(() => previewFormula(formula, agg, elements), [formula, agg, elements]);
  const canWrite = preview.total !== null && !preview.error && formula.trim() !== '';

  const insertChip = (name: string) => {
    const el = inputRef.current;
    const start = el?.selectionStart ?? formula.length;
    const end = el?.selectionEnd ?? formula.length;
    setFormula(formula.slice(0, start) + name + formula.slice(end));
    setPending(null);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + name.length, start + name.length);
    });
  };

  const confirm = async () => {
    if (!canWrite || preview.total === null) return;
    setError(null);
    if (pending === 'set') {
      onSetQuantity(preview.total, formula.trim(), agg);
      setPending(null);
      return;
    }
    if (!boqId) return;
    setBusy(true);
    try {
      const link = await boqApi.createQuantityLink(
        positionId,
        buildFormulaLinkPayload(modelId, elementStableIds, formula, agg),
      );
      await boqApi.applyQuantityLinks(boqId, [link.id]);
      await qc.invalidateQueries({ queryKey: ['boq'] });
      setPending(null);
      onLinked?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 p-3 text-[11px]" data-testid="linked-formula-panel">
      <label className="text-content-secondary">
        {t('boq.formula_per_element', { defaultValue: 'Formula per element' })}
        <input
          ref={inputRef}
          value={formula}
          onChange={(e) => {
            setFormula(e.target.value);
            setPending(null);
          }}
          placeholder="volume + type_bp_volume"
          spellCheck={false}
          className="mt-0.5 w-full rounded border border-border-light bg-surface-primary px-2 py-1 font-mono text-xs"
          data-testid="formula-input"
        />
      </label>
      <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto" data-testid="formula-chips">
        {chips.length === 0 && (
          <span className="text-content-tertiary">
            {t('boq.formula_no_vars', { defaultValue: 'No numeric properties on the linked elements' })}
          </span>
        )}
        {chips.map((c) => (
          <button
            key={c.name}
            type="button"
            onClick={() => insertChip(c.name)}
            title={`${c.label} (${c.count}/${elements.length})`}
            className="rounded border border-border-light px-1.5 py-0.5 font-mono text-[10px] hover:bg-emerald-500 hover:text-white"
          >
            {c.name}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-content-secondary">
        {t('boq.formula_aggregation', { defaultValue: 'Combine elements' })}
        <select
          value={agg}
          onChange={(e) => {
            setAgg(e.target.value as QuantityAggregation);
            setPending(null);
          }}
          className="rounded border border-border-light bg-surface-primary px-1 py-0.5"
          data-testid="formula-agg"
        >
          {AGGREGATIONS.map((a) => (
            <option key={a} value={a}>
              {t(`boq.formula_agg_${a}`, { defaultValue: a })}
            </option>
          ))}
        </select>
      </label>

      <div className="rounded border border-border-light/60 p-2" data-testid="formula-preview">
        {preview.error ? (
          <div className="text-red-600">{preview.error}</div>
        ) : formula.trim() === '' ? (
          <div className="text-content-tertiary">
            {t('boq.formula_enter_hint', { defaultValue: 'Enter a formula to see the result' })}
          </div>
        ) : (
          <>
            <div className="font-semibold">
              {t('boq.formula_total', { defaultValue: 'Total' })}:{' '}
              <span data-testid="formula-total">{preview.total === null ? '-' : fmt(preview.total)}</span>
            </div>
            <ul className="max-h-24 overflow-y-auto font-mono text-[10px]">
              {preview.rows.map((r) => (
                <li key={r.id} className="flex justify-between gap-2">
                  <span className="truncate">{r.label}</span>
                  <span>{fmt(r.value)}</span>
                </li>
              ))}
            </ul>
            {preview.skipped.length > 0 && (
              <div className="mt-1 text-amber-700" data-testid="formula-skipped">
                {t('boq.formula_skipped', {
                  defaultValue: '{{n}} element(s) skipped, not counted as 0:',
                  n: preview.skipped.length,
                })}
                <ul className="font-mono text-[10px]">
                  {preview.skipped.map((s) => (
                    <li key={s.id} className="truncate">
                      {s.label}
                      {s.missing.length > 0 ? ` - ${s.missing.join(', ')}` : s.error ? ` - ${s.error}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>

      {pending && canWrite && preview.total !== null && (
        <div className="rounded border border-amber-300 bg-amber-50 p-2 dark:bg-amber-950/20" data-testid="formula-confirm">
          {pending === 'set'
            ? t('boq.formula_confirm_set', {
                defaultValue: 'Quantity changes from {{from}} to {{to}}; the formula is saved on the position.',
                from: fmt(currentQuantity),
                to: fmt(preview.total),
              })
            : t('boq.formula_confirm_link', {
                defaultValue:
                  'A live link to the model is created and applied: quantity becomes {{to}} and updates when the model changes.',
                to: fmt(preview.total),
              })}
          <div className="mt-1 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={confirm}
              className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-white"
              data-testid="formula-confirm-btn"
            >
              {busy && <Loader2 size={10} className="animate-spin" />}
              {t('boq.formula_confirm', { defaultValue: 'Confirm' })}
            </button>
            <button type="button" onClick={() => setPending(null)} className="px-2 py-1">
              {t('boq.formula_cancel', { defaultValue: 'Cancel' })}
            </button>
          </div>
        </div>
      )}
      {error && <div className="text-red-600">{error}</div>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={!canWrite}
          onClick={() => setPending('set')}
          className="flex-1 rounded bg-emerald-600 px-2 py-1 text-white disabled:opacity-40"
          data-testid="formula-set"
        >
          {t('boq.bim_qty_use_as_quantity', { defaultValue: 'Set as quantity' })}
        </button>
        <button
          type="button"
          disabled={!canWrite || !boqId}
          onClick={() => setPending('link')}
          className="flex-1 rounded border border-emerald-600 px-2 py-1 text-emerald-700 disabled:opacity-40"
          data-testid="formula-link"
        >
          {t('boq.formula_link_to_model', { defaultValue: 'Link to model' })}
        </button>
      </div>
    </div>
  );
}
