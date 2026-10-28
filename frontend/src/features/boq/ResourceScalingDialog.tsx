// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Proportional scaling: type the total hours (or cost, or quantity) a
 * section or a resource group should come to, and every norm beneath it is
 * scaled by one factor.
 *
 * Nothing is written until the person has seen the preview: the factor, the
 * total the rounded norms really add up to, and every line and norm that
 * changes. Locked lines (and lines unticked here) keep their norms and count
 * as the fixed part. Applying takes a version snapshot first, so the toast's
 * undo (or the version history) restores the norms as they were.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Lock, Scale, X } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { fmtList, fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi } from './api';
import {
  applyScaling,
  previewScaling,
  scalingErrorCode,
  type RoundingMode,
  type ScaleMetric,
  type ScalePlan,
  type ScaleScopeInput,
} from './resourceScalingApi';
import { scalingErrorText, scalingWarningText } from './resourceScalingText';

export interface ResourceScalingScope extends ScaleScopeInput {
  /** What the scope is called on screen: a section ordinal and title, or a resource name. */
  label: string;
}

export interface ResourceScalingDialogProps {
  open: boolean;
  boqId: string;
  scope: ResourceScalingScope | null;
  /** Hours by default; a resource group opens on quantity. */
  initialMetric?: ScaleMetric;
  readOnly?: boolean;
  onClose: () => void;
  /** Called after norms were written, so the editor refetches. */
  onApplied?: () => void;
}

const num = (value: string | number, decimals = 2) => fmtNumber(Number(value), decimals);

export function ResourceScalingDialog({
  open,
  boqId,
  scope,
  initialMetric = 'hours',
  readOnly = false,
  onClose,
  onApplied,
}: ResourceScalingDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [metric, setMetric] = useState<ScaleMetric>(initialMetric);
  const [target, setTarget] = useState('');
  const [decimals, setDecimals] = useState(3);
  const [mode, setMode] = useState<RoundingMode>('half_up');
  const [excluded, setExcluded] = useState<string[]>([]);
  const [measure, setMeasure] = useState<ScalePlan | null>(null);
  const [plan, setPlan] = useState<ScalePlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const request = useCallback(
    (targetValue: string | null) => ({
      sectionId: scope?.sectionId ?? null,
      positionIds: scope?.positionIds ?? null,
      resourceType: scope?.resourceType ?? null,
      resourceKey: scope?.resourceKey ?? null,
      metric,
      target: targetValue,
      decimals,
      roundingMode: mode,
      excludedPositionIds: excluded,
    }),
    [scope, metric, decimals, mode, excluded],
  );

  const fail = useCallback(
    (err: unknown) => {
      const code = scalingErrorCode(err);
      setError(code ? scalingErrorText(t, code) : err instanceof Error ? err.message : String(err));
    },
    [t],
  );

  // Measure the scope whenever it or the metric changes: the current total is the starting point.
  useEffect(() => {
    if (!open || !scope) return;
    let cancelled = false;
    setPlan(null);
    setError(null);
    setMeasure(null);
    previewScaling(boqId, request(null))
      .then((result) => {
        if (cancelled) return;
        setMeasure(result);
        setTarget(String(Number(result.current)));
      })
      .catch((err) => !cancelled && fail(err));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, boqId, scope, metric]);

  useEffect(() => {
    if (open) {
      setMetric(initialMetric);
      setExcluded([]);
    }
  }, [open, initialMetric, scope]);

  const targetValue = target.trim().replace(',', '.');
  const targetValid = targetValue !== '' && Number.isFinite(Number(targetValue)) && Number(targetValue) >= 0;

  const runPreview = async () => {
    if (!targetValid) return;
    setBusy(true);
    setError(null);
    try {
      setPlan(await previewScaling(boqId, request(targetValue)));
    } catch (err) {
      setPlan(null);
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      const result = await applyScaling(boqId, { ...request(targetValue), expectedFactor: plan.factor });
      const snapshotId = result.snapshot_id;
      addToast(
        {
          type: 'success',
          title: t('boq.scaling.applied', { defaultValue: 'Positions scaled: {{n}}', n: result.updated }),
          action: snapshotId
            ? {
                label: t('boq.scaling.undo', { defaultValue: 'Undo' }),
                onClick: () => {
                  void boqApi
                    .restoreSnapshot(boqId, snapshotId)
                    .then(() => {
                      onApplied?.();
                      addToast({ type: 'info', title: t('boq.scaling.undone', { defaultValue: 'Scaling undone' }) });
                    })
                    .catch((err: unknown) =>
                      addToast({ type: 'error', title: err instanceof Error ? err.message : String(err) }),
                    );
                },
              }
            : undefined,
        },
        { duration: 15000 },
      );
      onApplied?.();
      onClose();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const toggleLine = (id: string) => {
    setExcluded((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  // A line ticked or unticked in the preview changes the factor: preview again at once.
  useEffect(() => {
    if (plan) void runPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [excluded]);

  const unitLabel = useMemo(() => {
    if (metric === 'cost') return '';
    if (metric === 'hours') return t('boq.scaling.unit_hours', { defaultValue: 'h' });
    return fmtList(measure?.units ?? []);
  }, [metric, measure, t]);

  if (!open || !scope) return null;

  const factorPct = plan ? (Number(plan.factor) - 1) * 100 : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="boq-scaling-title"
        className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-full max-w-4xl max-h-[90vh] flex flex-col animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h3 id="boq-scaling-title" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Scale size={16} />
            {t('boq.scaling.title', { defaultValue: 'Scale to a target total' })}
            <span className="font-normal text-content-secondary">· {scope.label}</span>
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-content-tertiary hover:bg-surface-secondary transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-4">
          <p className="text-xs text-content-secondary">
            {t('boq.scaling.intro', {
              defaultValue:
                'Enter the total this scope should come to. Every resource norm beneath it is multiplied by the same factor; locked lines keep theirs.',
            })}
          </p>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('boq.scaling.metric', { defaultValue: 'Scale by' })}
              <select
                value={metric}
                onChange={(e) => setMetric(e.target.value as ScaleMetric)}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary"
              >
                <option value="hours">{t('boq.scaling.metric_hours', { defaultValue: 'Labour hours' })}</option>
                <option value="cost">{t('boq.scaling.metric_cost', { defaultValue: 'Total cost' })}</option>
                <option value="quantity">{t('boq.scaling.metric_quantity', { defaultValue: 'Resource quantity' })}</option>
              </select>
            </label>
            <div className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('boq.scaling.current', { defaultValue: 'Current total' })}
              <span className="py-1.5 text-sm font-medium text-content-primary">
                {measure ? `${num(measure.current)} ${unitLabel}` : '–'}
              </span>
            </div>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('boq.scaling.target', { defaultValue: 'New total' })}
              <input
                inputMode="decimal"
                value={target}
                onChange={(e) => {
                  setTarget(e.target.value);
                  setPlan(null);
                }}
                aria-invalid={!targetValid}
                className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary"
              />
            </label>
            <div className="flex gap-2">
              <label className="flex flex-1 flex-col gap-1 text-xs text-content-secondary">
                {t('boq.scaling.decimals', { defaultValue: 'Decimals' })}
                <select
                  value={decimals}
                  onChange={(e) => {
                    setDecimals(Number(e.target.value));
                    setPlan(null);
                  }}
                  className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary"
                >
                  {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-1 flex-col gap-1 text-xs text-content-secondary">
                {t('boq.scaling.rounding', { defaultValue: 'Rounding' })}
                <select
                  value={mode}
                  onChange={(e) => {
                    setMode(e.target.value as RoundingMode);
                    setPlan(null);
                  }}
                  className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary"
                >
                  <option value="half_up">{t('boq.scaling.rounding_half_up', { defaultValue: 'Nearest' })}</option>
                  <option value="up">{t('boq.scaling.rounding_up', { defaultValue: 'Up' })}</option>
                  <option value="down">{t('boq.scaling.rounding_down', { defaultValue: 'Down' })}</option>
                </select>
              </label>
            </div>
          </div>

          {measure && Number(measure.fixed) > 0 && (
            <p className="flex items-center gap-1.5 text-xs text-content-secondary">
              <Lock size={12} />
              {t('boq.scaling.fixed_part', {
                defaultValue: '{{fixed}} of it is fixed (locked or excluded lines) and does not move.',
                fixed: `${num(measure.fixed)} ${unitLabel}`.trim(),
              })}
            </p>
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg p-3 text-xs text-semantic-error">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {plan && (
            <div className="space-y-3" data-testid="scaling-preview">
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="blue">
                  {t('boq.scaling.factor', { defaultValue: 'Factor' })}: {num(plan.factor, 4)} (
                  {factorPct >= 0 ? '+' : ''}
                  {num(factorPct, 1)} %)
                </Badge>
                <Badge variant="neutral">
                  {t('boq.scaling.achieved', { defaultValue: 'After rounding' })}: {num(plan.achieved)} {unitLabel}
                </Badge>
                {Number(plan.drift) !== 0 && (
                  <Badge variant="warning">
                    {t('boq.scaling.drift', { defaultValue: 'Rounding difference' })}: {num(plan.drift, 4)}
                  </Badge>
                )}
                <Badge variant="neutral">
                  {t('boq.scaling.lines_changed', { defaultValue: 'Positions that change: {{n}}', n: plan.counts.scaled })}
                </Badge>
              </div>
              {plan.warnings.map((w) => (
                <div key={w.code} className="flex items-start gap-2 rounded-lg bg-semantic-warning-bg p-2 text-xs">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                  <span>{scalingWarningText(t, w)}</span>
                </div>
              ))}
              <div className="max-h-[40vh] overflow-auto rounded-lg border border-border-light">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-surface-secondary text-left text-content-secondary">
                    <tr>
                      <th className="w-8 px-2 py-1.5" />
                      <th className="px-2 py-1.5 font-medium">{t('boq.fidelity.col_position', { defaultValue: 'Position' })}</th>
                      <th className="px-2 py-1.5 font-medium">{t('boq.scaling.col_norms', { defaultValue: 'Norms' })}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t('boq.scaling.col_before', { defaultValue: 'Before' })}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t('boq.scaling.col_after', { defaultValue: 'After' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.lines.map((line) => (
                      <tr key={line.id} className="border-t border-border-light align-top">
                        <td className="px-2 py-1.5">
                          {line.status === 'locked' ? (
                            <Lock size={12} className="text-content-tertiary" aria-label={t('boq.scaling.locked_line', { defaultValue: 'Locked line' })} />
                          ) : (
                            <input
                              type="checkbox"
                              checked={line.status !== 'excluded'}
                              onChange={() => toggleLine(line.id)}
                              aria-label={t('boq.scaling.include_line', { defaultValue: 'Include this position' })}
                            />
                          )}
                        </td>
                        <td className="px-2 py-1.5">
                          <span className="font-mono">{line.ordinal}</span> {line.description}
                        </td>
                        <td className="px-2 py-1.5">
                          {line.changes.map((c) => (
                            <div key={c.index}>
                              {c.name}: {num(c.old_quantity, 4)} → <strong>{num(c.new_quantity, 4)}</strong> {c.unit}
                            </div>
                          ))}
                        </td>
                        <td className="px-2 py-1.5 text-right">{num(line.old_value)}</td>
                        <td className="px-2 py-1.5 text-right">{num(line.new_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {excluded.length > 0 && (
                <p className="text-xs text-content-tertiary">
                  {t('boq.scaling.excluded_hint', { defaultValue: 'Unticked positions keep their norms and count as fixed.' })}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border-light px-5 py-3">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="secondary" size="sm" onClick={runPreview} loading={busy && !plan} disabled={!targetValid || !measure}>
            {t('boq.scaling.preview', { defaultValue: 'Preview' })}
          </Button>
          <Button
            size="sm"
            onClick={apply}
            loading={busy && !!plan}
            disabled={!plan || readOnly || plan.counts.scaled === 0}
          >
            {t('boq.scaling.apply', { defaultValue: 'Apply' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
