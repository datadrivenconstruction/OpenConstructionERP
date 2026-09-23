// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  Leaf,
  ListFilter,
  Minus,
  Pencil,
  Plus,
  Printer,
  ShieldCheck,
  Target,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, DismissibleInfo, EmptyState, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  createEsgEntry,
  deleteEsgEntry,
  fetchEsgEntries,
  fetchEsgMetrics,
  fetchEsgSummary,
  updateEsgEntry,
  type EsgCategory,
  type EsgDirection,
  type EsgEntry,
  type EsgMetricDefinition,
  type EsgMetricSummary,
  type UpdateEsgEntryPayload,
} from './api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* ── Constants & helpers ───────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const CATEGORY_ORDER: EsgCategory[] = ['environmental', 'social', 'governance'];

const CATEGORY_META: Record<
  EsgCategory,
  { label: string; icon: typeof Leaf; accent: string }
> = {
  environmental: {
    label: 'Environmental',
    icon: Leaf,
    accent: 'text-emerald-600 dark:text-emerald-400',
  },
  social: { label: 'Social', icon: Users, accent: 'text-sky-600 dark:text-sky-400' },
  governance: {
    label: 'Governance',
    icon: ShieldCheck,
    accent: 'text-violet-600 dark:text-violet-400',
  },
};

const CHIP_GOOD = 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400';
const CHIP_BAD = 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
const CHIP_NEUTRAL = 'bg-surface-tertiary text-content-tertiary';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** Two decimals, written the way the reader's language writes them. Built per
 *  call rather than once at module scope, because the language switcher does
 *  not reload the app and a formatter made at chunk load never hears about it. */
const numberFmt = (n: number): string =>
  n.toLocaleString(getNumberLocale(), { maximumFractionDigits: 2 });
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Parse a Decimal-as-string into a finite number, or null. */
function toNum(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fmtNum(n: number | null): string {
  return n === null ? '-' : numberFmt(n);
}

function formatPeriod(period: string | null): string {
  if (!period) return '';
  const [year, month] = period.split('-');
  const idx = Number(month) - 1;
  return MONTHS[idx] ? `${MONTHS[idx]} ${year}` : period;
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function statusChip(onTrack: boolean | null): string {
  if (onTrack === true) return CHIP_GOOD;
  if (onTrack === false) return CHIP_BAD;
  return CHIP_NEUTRAL;
}

/* ── CSV + print-report helpers ────────────────────────────────────────── */

/**
 * Whether a reading met its own target given the metric direction. Compares a
 * single metric's value against that metric's target (same unit) - never
 * blends units. Returns null when either figure is missing/unparseable.
 */
function meetsTarget(
  value: string | null | undefined,
  target: string | null | undefined,
  direction: EsgDirection,
): boolean | null {
  const v = toNum(value);
  const tg = toNum(target);
  if (v === null || tg === null) return null;
  return direction === 'lower_better' ? v <= tg : v >= tg;
}

/** Quote a CSV text cell and escape embedded quotes, so commas, quotes and
 *  line breaks inside labels or notes never break the row shape. */
function csvCell(value: string): string {
  return `"${String(value).replace(/"/g, '""')}"`;
}

/** Escape text for safe interpolation into the print-report HTML. */
function esc(value: string): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const PILLAR_PRINT_ACCENT: Record<EsgCategory, string> = {
  environmental: '#059669',
  social: '#0284c7',
  governance: '#7c3aed',
};

interface ReportMetricRow {
  label: string;
  unit: string;
  latest: string;
  target: string;
  deltaLabel: string;
  status: 'ok' | 'bad' | 'muted';
  statusLabel: string;
}
interface ReportPillar {
  label: string;
  accent: string;
  metrics: ReportMetricRow[];
}
interface EsgReportModel {
  projectName: string;
  periodLabel: string;
  generatedLabel: string;
  offTrackCount: number;
  pillars: ReportPillar[];
  labels: {
    title: string;
    project: string;
    period: string;
    generated: string;
    offTrack: string;
    colMetric: string;
    colLatest: string;
    colTarget: string;
    colChange: string;
    colStatus: string;
    footer: string;
    empty: string;
  };
}

/**
 * Build a self-contained, print-friendly HTML document for one period's ESG
 * report card (opened in a new window and printed client-side). Pure over
 * strings; every dynamic value is pre-escaped by the caller/`esc`.
 */
function buildEsgReportHtml(model: EsgReportModel): string {
  const L = model.labels;
  const statusColor: Record<ReportMetricRow['status'], string> = {
    ok: '#047857',
    bad: '#b91c1c',
    muted: '#9ca3af',
  };
  const pillarsHtml = model.pillars
    .map((p) => {
      const rows = p.metrics
        .map(
          (m) => `
          <tr>
            <td>${esc(m.label)}</td>
            <td class="num">${esc(m.latest)} <span class="unit">${esc(m.unit)}</span></td>
            <td class="num">${esc(m.target)}</td>
            <td class="num">${esc(m.deltaLabel)}</td>
            <td style="color:${statusColor[m.status]};font-weight:600">${esc(m.statusLabel)}</td>
          </tr>`,
        )
        .join('');
      return `
        <section class="pillar" style="border-left-color:${p.accent}">
          <h2>${esc(p.label)}</h2>
          <table>
            <thead>
              <tr>
                <th>${esc(L.colMetric)}</th>
                <th class="num">${esc(L.colLatest)}</th>
                <th class="num">${esc(L.colTarget)}</th>
                <th class="num">${esc(L.colChange)}</th>
                <th>${esc(L.colStatus)}</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </section>`;
    })
    .join('');

  const body = model.pillars.length > 0 ? pillarsHtml : `<p class="empty">${esc(L.empty)}</p>`;
  const offTrackHtml =
    model.offTrackCount > 0 ? `<p class="alert">${esc(L.offTrack)}</p>` : '';

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>${esc(L.title)} - ${esc(model.projectName)}</title>
<style>
  @page { margin: 16mm; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #111827; margin: 0; padding: 24px; font-size: 12px; }
  h1 { font-size: 19px; margin: 0 0 6px; }
  .meta { color: #6b7280; font-size: 11px; line-height: 1.7; margin-bottom: 14px; }
  .meta strong { color: #374151; font-weight: 600; }
  .alert { display: inline-block; background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; border-radius: 6px; padding: 6px 10px; font-size: 11px; font-weight: 600; margin: 0 0 16px; }
  .pillar { margin: 0 0 18px; border-left: 3px solid #cccccc; padding-left: 10px; page-break-inside: avoid; }
  .pillar h2 { font-size: 13px; margin: 0 0 6px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }
  th { background: #f9fafb; text-transform: uppercase; letter-spacing: .04em; font-size: 9.5px; color: #6b7280; font-weight: 600; }
  td { font-size: 11.5px; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .unit { color: #9ca3af; font-size: 10px; }
  .empty { color: #9ca3af; font-size: 12px; }
  footer { margin-top: 22px; padding-top: 10px; border-top: 1px solid #e5e7eb; color: #9ca3af; font-size: 10px; }
</style>
</head>
<body>
  <h1>${esc(L.title)}</h1>
  <div class="meta">
    <div><strong>${esc(L.project)}:</strong> ${esc(model.projectName)}</div>
    <div><strong>${esc(L.period)}:</strong> ${esc(model.periodLabel)}</div>
    <div><strong>${esc(L.generated)}:</strong> ${esc(model.generatedLabel)}</div>
  </div>
  ${offTrackHtml}
  ${body}
  <footer>${esc(L.footer)}</footer>
  <script>window.addEventListener('load',function(){setTimeout(function(){try{window.focus();window.print();}catch(e){}},250);});</script>
</body>
</html>`;
}

/* ── Sparkline (pure SVG, no deps) ─────────────────────────────────────── */

function Sparkline({ values, onTrack }: { values: number[]; onTrack: boolean | null }) {
  const { t } = useTranslation();
  if (values.length < 2) {
    return (
      <div className="h-8 flex items-center text-2xs text-content-quaternary">
        {t('esg.trend_needs_two', { defaultValue: 'Trend appears after 2+ periods' })}
      </div>
    );
  }
  const w = 140;
  const h = 32;
  const pad = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = (w - 2 * pad) / (values.length - 1);
  const coords = values.map((v, i) => ({
    x: pad + i * stepX,
    y: h - pad - ((v - min) / span) * (h - 2 * pad),
  }));
  const points = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');
  const lastPoint = coords[coords.length - 1];
  const tone =
    onTrack === true
      ? 'text-emerald-500'
      : onTrack === false
        ? 'text-red-500'
        : 'text-content-tertiary';
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className={clsx('w-full h-8', tone)}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {lastPoint && <circle cx={lastPoint.x} cy={lastPoint.y} r={2} fill="currentColor" />}
    </svg>
  );
}

/* ── Metric KPI card ───────────────────────────────────────────────────── */

function MetricCard({
  summary,
  onAdd,
}: {
  summary: EsgMetricSummary;
  onAdd: (metricKey: string) => void;
}) {
  const { t } = useTranslation();
  const label = t(`esg.metric_${summary.metric_key}`, { defaultValue: summary.label });
  const latest = toNum(summary.latest_value);
  const target = toNum(summary.target);
  const unit = summary.unit;
  const hasReading = latest !== null;
  const values = summary.trend
    .map((p) => toNum(p.value))
    .filter((v): v is number => v !== null);

  const directionHint =
    summary.direction === 'lower_better'
      ? t('esg.lower_better', { defaultValue: 'Lower is better' })
      : t('esg.higher_better', { defaultValue: 'Higher is better' });

  return (
    <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-content-primary truncate" title={label}>
            {label}
          </p>
          <p className="text-2xs text-content-tertiary">{directionHint}</p>
        </div>
        <Badge variant="neutral" size="sm" className="shrink-0 font-mono">
          {unit}
        </Badge>
      </div>

      {!hasReading ? (
        <div className="mt-4 flex flex-1 flex-col items-start justify-between gap-3">
          <p className="text-sm text-content-quaternary">
            {t('esg.no_readings_yet', { defaultValue: 'No readings yet' })}
          </p>
          <Button variant="ghost" size="sm" onClick={() => onAdd(summary.metric_key)}>
            <Plus size={14} className="mr-1" />
            {t('esg.add_reading', { defaultValue: 'Add reading' })}
          </Button>
        </div>
      ) : (
        <>
          {/* Value + delta */}
          <div className="mt-3 flex items-end justify-between gap-2">
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold tabular-nums text-content-primary">
                {fmtNum(latest)}
              </span>
              <span className="text-xs text-content-tertiary">{unit}</span>
            </div>
            {summary.delta_pct !== null && (
              <span
                className={clsx(
                  'inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-2xs font-semibold tabular-nums',
                  statusChip(summary.on_track),
                )}
                title={
                  summary.on_track === true
                    ? t('esg.on_track', { defaultValue: 'On track vs target' })
                    : summary.on_track === false
                      ? t('esg.off_track', { defaultValue: 'Off track vs target' })
                      : undefined
                }
              >
                {summary.delta_pct > 0 ? (
                  <ArrowUpRight size={11} />
                ) : summary.delta_pct < 0 ? (
                  <ArrowDownRight size={11} />
                ) : (
                  <Minus size={11} />
                )}
                {summary.delta_pct > 0 ? '+' : ''}
                {numberFmt(summary.delta_pct)}%
              </span>
            )}
          </div>

          {/* Target line */}
          <div className="mt-1 flex items-center gap-1 text-xs text-content-secondary">
            <Target size={12} className="text-content-tertiary shrink-0" />
            {target !== null ? (
              <span>
                {t('esg.target', { defaultValue: 'Target' })} {fmtNum(target)} {unit}
              </span>
            ) : (
              <span className="text-content-quaternary">
                {t('esg.no_target', { defaultValue: 'No target set' })}
              </span>
            )}
          </div>

          {/* Trend */}
          <div className="mt-3">
            <Sparkline values={values} onTrack={summary.on_track} />
          </div>

          {/* Footer */}
          <div className="mt-2 flex items-center justify-between text-2xs text-content-tertiary">
            <span>{formatPeriod(summary.latest_period)}</span>
            <span className="tabular-nums">
              {t('esg.n_periods', {
                defaultValue: '{{count}} periods',
                count: summary.entry_count,
              })}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

/* ── Add / edit reading modal ──────────────────────────────────────────── */

function ReadingModal({
  metrics,
  projectId,
  editEntry,
  presetMetric,
  onClose,
  onSaved,
}: {
  metrics: EsgMetricDefinition[];
  projectId: string;
  editEntry: EsgEntry | null;
  presetMetric: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = editEntry !== null;

  const [metricKey, setMetricKey] = useState(
    editEntry?.metric_key ?? presetMetric ?? metrics[0]?.key ?? '',
  );
  const [period, setPeriod] = useState(editEntry?.period ?? currentMonth());
  const [value, setValue] = useState(editEntry?.value ?? '');
  const [target, setTarget] = useState(editEntry?.target ?? '');
  const [note, setNote] = useState(editEntry?.note ?? '');
  const [touched, setTouched] = useState(false);

  const selectedMetric = metrics.find((m) => m.key === metricKey);

  const grouped = useMemo(() => {
    const map: Record<EsgCategory, EsgMetricDefinition[]> = {
      environmental: [],
      social: [],
      governance: [],
    };
    for (const m of metrics) map[m.category]?.push(m);
    return map;
  }, [metrics]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const valueError = touched && (value.trim() === '' || Number(value) < 0 || !Number.isFinite(Number(value)));
  const canSubmit = metricKey !== '' && period !== '' && value.trim() !== '' && Number(value) >= 0;

  const saveMut = useMutation({
    mutationFn: async () => {
      if (isEdit && editEntry) {
        // Only what the user actually edited goes back. Correcting a value used
        // to rewrite the target and the note as they stood when this list was
        // read, undoing anyone else's edit to them without a word. The update
        // route dumps with `exclude_unset=True`, so an omitted field is left
        // alone; `null` is what clears one, since `JSON.stringify` would drop
        // an `undefined` key and the old value would simply survive.
        const patch: UpdateEsgEntryPayload = {};
        if (value !== (editEntry.value ?? '')) patch.value = value.trim();
        if (target !== (editEntry.target ?? '')) {
          patch.target = target.trim() === '' ? null : target.trim();
        }
        if (note !== (editEntry.note ?? '')) {
          patch.note = note.trim() === '' ? null : note.trim();
        }
        return updateEsgEntry(editEntry.id, patch);
      }
      return createEsgEntry({
        project_id: projectId,
        metric_key: metricKey,
        period,
        value: value.trim(),
        target: target.trim() === '' ? undefined : target.trim(),
        note: note.trim() === '' ? undefined : note.trim(),
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: isEdit
          ? t('esg.reading_updated', { defaultValue: 'Reading updated' })
          : t('esg.reading_saved', { defaultValue: 'Reading saved' }),
      });
      onSaved();
      onClose();
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('esg.save_failed', { defaultValue: 'Could not save reading' }),
        message: getErrorMessage(e),
      });
    },
  });

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) saveMut.mutate();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in"
      role="dialog"
      aria-label={
        isEdit
          ? t('esg.edit_reading', { defaultValue: 'Edit reading' })
          : t('esg.new_reading', { defaultValue: 'New reading' })
      }
    >
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {isEdit
              ? t('esg.edit_reading', { defaultValue: 'Edit reading' })
              : t('esg.new_reading', { defaultValue: 'New reading' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-4">
          {/* Metric + period */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="esg-metric" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('esg.field_metric', { defaultValue: 'Metric' })}
              </label>
              <select
                id="esg-metric"
                value={metricKey}
                onChange={(e) => setMetricKey(e.target.value)}
                disabled={isEdit}
                className={clsx(inputCls, isEdit && 'opacity-60 cursor-not-allowed')}
              >
                {CATEGORY_ORDER.map((cat) => (
                  <optgroup
                    key={cat}
                    label={t(`esg.category_${cat}`, { defaultValue: CATEGORY_META[cat].label })}
                  >
                    {grouped[cat].map((m) => (
                      <option key={m.key} value={m.key}>
                        {t(`esg.metric_${m.key}`, { defaultValue: m.label })} ({m.unit})
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="esg-period" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('esg.field_period', { defaultValue: 'Period' })}
              </label>
              <input
                id="esg-period"
                type="month"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                disabled={isEdit}
                className={clsx(inputCls, isEdit && 'opacity-60 cursor-not-allowed')}
              />
            </div>
          </div>

          {/* Value + target */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="esg-value" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('esg.field_value', { defaultValue: 'Value' })}{' '}
                {selectedMetric && (
                  <span className="text-content-tertiary font-normal">({selectedMetric.unit})</span>
                )}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                id="esg-value"
                type="number"
                step="any"
                min="0"
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  setTouched(true);
                }}
                className={clsx(
                  inputCls,
                  valueError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
                )}
                autoFocus
              />
              {valueError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('esg.value_invalid', { defaultValue: 'Enter a value of zero or more' })}
                </p>
              )}
            </div>
            <div>
              <label htmlFor="esg-target" className="block text-sm font-medium text-content-primary mb-1.5">
                {t('esg.field_target', { defaultValue: 'Target' })}{' '}
                <span className="text-content-tertiary font-normal">
                  ({t('common.optional', { defaultValue: 'optional' })})
                </span>
              </label>
              <input
                id="esg-target"
                type="number"
                step="any"
                min="0"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          {/* Note */}
          <div>
            <label htmlFor="esg-note" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('esg.field_note', { defaultValue: 'Note' })}
            </label>
            <textarea
              id="esg-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('esg.note_placeholder', {
                defaultValue: 'Optional context for this reading...',
              })}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={saveMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={saveMut.isPending || !canSubmit}>
            {saveMut.isPending && (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            )}
            {isEdit
              ? t('common.save', { defaultValue: 'Save' })
              : t('esg.add_reading', { defaultValue: 'Add reading' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Recent readings table ─────────────────────────────────────────────── */

function RecentReadings({
  entries,
  metrics,
  onEdit,
  onDelete,
}: {
  entries: EsgEntry[];
  metrics: EsgMetricDefinition[];
  onEdit: (entry: EsgEntry) => void;
  onDelete: (entry: EsgEntry) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const byKey = useMemo(() => {
    const map = new Map<string, EsgMetricDefinition>();
    for (const m of metrics) map.set(m.key, m);
    return map;
  }, [metrics]);

  // Newest first: period is 'YYYY-MM' (sorts lexicographically = chronological),
  // then break ties by recency. Sorting explicitly makes "recent" honest and
  // keeps the full history ordered when expanded.
  const sorted = useMemo(
    () =>
      [...entries].sort(
        (a, b) =>
          b.period.localeCompare(a.period) ||
          (b.created_at ?? '').localeCompare(a.created_at ?? ''),
      ),
    [entries],
  );

  if (sorted.length === 0) return null;

  const COLLAPSED = 12;
  const visible = expanded ? sorted : sorted.slice(0, COLLAPSED);
  const hasMore = sorted.length > COLLAPSED;

  return (
    <Card padding="none" className="overflow-x-auto">
      {/* When expanded the full history scrolls inside a capped area with a
          sticky header, so long histories never push the page down endlessly. */}
      <div
        className={clsx(
          'min-w-[560px]',
          expanded && hasMore && 'max-h-[32rem] overflow-y-auto',
        )}
      >
        <div className="sticky top-0 z-10 flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-elevated text-2xs font-medium text-content-tertiary uppercase tracking-wider">
          <span className="flex-1">{t('esg.col_metric', { defaultValue: 'Metric' })}</span>
          <span className="w-24">{t('esg.col_period', { defaultValue: 'Period' })}</span>
          <span className="w-24 text-right">{t('esg.col_value', { defaultValue: 'Value' })}</span>
          <span className="w-24 text-right">{t('esg.col_target', { defaultValue: 'Target' })}</span>
          <span className="w-16 text-right">{t('esg.col_actions', { defaultValue: 'Actions' })}</span>
        </div>
        {visible.map((entry) => {
          const def = byKey.get(entry.metric_key);
          const unit = def?.unit ?? '';
          const label = def
            ? t(`esg.metric_${entry.metric_key}`, { defaultValue: def.label })
            : entry.metric_key;
          return (
            <div
              key={entry.id}
              className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light last:border-b-0 hover:bg-surface-secondary/40 transition-colors"
            >
              <span className="flex-1 min-w-0">
                <span className="block text-sm text-content-primary truncate">{label}</span>
                {entry.note && (
                  <span className="block text-2xs text-content-tertiary truncate">{entry.note}</span>
                )}
              </span>
              <span className="w-24 text-xs text-content-secondary tabular-nums">
                {formatPeriod(entry.period)}
              </span>
              <span className="w-24 text-right text-sm text-content-primary tabular-nums">
                {fmtNum(toNum(entry.value))}
                <span className="text-2xs text-content-tertiary ml-1">{unit}</span>
              </span>
              <span className="w-24 text-right text-xs text-content-tertiary tabular-nums">
                {entry.target !== null ? fmtNum(toNum(entry.target)) : '-'}
              </span>
              <span className="w-16 flex items-center justify-end gap-1">
                <button
                  onClick={() => onEdit(entry)}
                  aria-label={t('common.edit', { defaultValue: 'Edit' })}
                  className="p-1.5 rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
                >
                  <Pencil size={14} />
                </button>
                <button
                  onClick={() => onDelete(entry)}
                  aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  className="p-1.5 rounded-lg text-content-tertiary hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </span>
            </div>
          );
        })}
      </div>
      {hasMore && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-t border-border-light bg-surface-secondary/20 min-w-[560px]">
          <span className="text-2xs text-content-tertiary tabular-nums">
            {t('esg.showing_readings', {
              defaultValue: 'Showing {{shown}} of {{total}}',
              shown: visible.length,
              total: sorted.length,
            })}
          </span>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-oe-blue-text hover:bg-oe-blue/10 transition-colors"
          >
            {expanded ? (
              <>
                {t('esg.show_fewer', { defaultValue: 'Show fewer' })}
                <ChevronUp size={13} />
              </>
            ) : (
              <>
                {t('esg.show_all_readings', {
                  defaultValue: 'Show all {{count}} readings',
                  count: sorted.length,
                })}
                <ChevronDown size={13} />
              </>
            )}
          </button>
        </div>
      )}
    </Card>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────── */

export function EsgPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [modalOpen, setModalOpen] = useState(false);
  const [presetMetric, setPresetMetric] = useState<string | null>(null);
  const [editEntry, setEditEntry] = useState<EsgEntry | null>(null);
  const [onlyOffTrack, setOnlyOffTrack] = useState(false);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });
  const projectId = activeProjectId || projects[0]?.id || '';

  const { data: metrics = [] } = useQuery({
    queryKey: ['esg-metrics'],
    queryFn: fetchEsgMetrics,
    staleTime: Infinity,
  });

  const {
    data: summary,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['esg-summary', projectId],
    queryFn: () => fetchEsgSummary(projectId),
    enabled: !!projectId,
  });

  const { data: entries = [] } = useQuery({
    queryKey: ['esg-entries', projectId],
    queryFn: () => fetchEsgEntries(projectId),
    enabled: !!projectId,
  });

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['esg-summary', projectId] });
    qc.invalidateQueries({ queryKey: ['esg-entries', projectId] });
  }, [qc, projectId]);

  const { confirm, ...confirmProps } = useConfirm();

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteEsgEntry(id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('esg.reading_deleted', { defaultValue: 'Reading deleted' }) });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('esg.delete_failed', { defaultValue: 'Could not delete reading' }),
        message: getErrorMessage(e),
      });
    },
  });

  const openAdd = useCallback((metricKey: string | null) => {
    setEditEntry(null);
    setPresetMetric(metricKey);
    setModalOpen(true);
  }, []);

  const openEdit = useCallback((entry: EsgEntry) => {
    setPresetMetric(null);
    setEditEntry(entry);
    setModalOpen(true);
  }, []);

  const handleDelete = useCallback(
    async (entry: EsgEntry) => {
      const def = metrics.find((m) => m.key === entry.metric_key);
      const label = def
        ? t(`esg.metric_${entry.metric_key}`, { defaultValue: def.label })
        : entry.metric_key;
      const ok = await confirm({
        title: t('esg.confirm_delete_title', { defaultValue: 'Delete reading?' }),
        message: t('esg.confirm_delete_msg', {
          defaultValue: 'Delete the {{label}} reading for {{period}}? This cannot be undone.',
          label,
          period: formatPeriod(entry.period),
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(entry.id);
    },
    [confirm, deleteMut, metrics, t],
  );

  const hasAnyReading = useMemo(
    () =>
      summary
        ? CATEGORY_ORDER.some((cat) =>
            (summary.by_category[cat] ?? []).some((m) => m.latest_value !== null),
          )
        : false,
    [summary],
  );

  // Flatten the already-loaded summary to surface exceptions. `on_track` is a
  // tri-state: false = missed target, true = met, null = no target/no reading.
  const allMetrics = useMemo(
    () => (summary ? CATEGORY_ORDER.flatMap((c) => summary.by_category[c] ?? []) : []),
    [summary],
  );
  const offTrackMetrics = useMemo(
    () => allMetrics.filter((m) => m.on_track === false),
    [allMetrics],
  );
  const trackedCount = useMemo(
    () => allMetrics.filter((m) => m.on_track !== null).length,
    [allMetrics],
  );

  // Drop the off-target filter when the project changes or once nothing is off
  // target, so the user is never stranded on an empty filtered view.
  useEffect(() => {
    setOnlyOffTrack(false);
  }, [projectId]);
  useEffect(() => {
    if (onlyOffTrack && offTrackMetrics.length === 0) setOnlyOffTrack(false);
  }, [onlyOffTrack, offTrackMetrics.length]);

  const projectSlug = useMemo(() => {
    const name = projects.find((p) => p.id === projectId)?.name ?? 'project';
    return (
      name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) ||
      'project'
    );
  }, [projects, projectId]);

  // Export every reading as CSV for a client/regulator handoff. Reuses the
  // client-side Blob pattern (no dependency). Decimal-as-string value/target
  // are emitted verbatim (exact, dot-decimal is CSV-safe) - no float math.
  const handleExportCsv = useCallback(() => {
    if (entries.length === 0) return;
    const byKey = new Map(metrics.map((m) => [m.key, m]));
    const rows = [...entries].sort(
      (a, b) => a.period.localeCompare(b.period) || a.metric_key.localeCompare(b.metric_key),
    );
    const headers = [
      t('esg.col_category', { defaultValue: 'Category' }),
      t('esg.col_metric', { defaultValue: 'Metric' }),
      t('esg.col_unit', { defaultValue: 'Unit' }),
      t('esg.col_period', { defaultValue: 'Period' }),
      t('esg.col_value', { defaultValue: 'Value' }),
      t('esg.col_target', { defaultValue: 'Target' }),
      t('esg.col_met_target', { defaultValue: 'Met target' }),
      t('esg.col_note', { defaultValue: 'Note' }),
    ].map(csvCell);
    const body = rows.map((e) => {
      const def = byKey.get(e.metric_key);
      const catLabel = def
        ? t(`esg.category_${def.category}`, { defaultValue: CATEGORY_META[def.category].label })
        : '';
      const metricLabel = def
        ? t(`esg.metric_${e.metric_key}`, { defaultValue: def.label })
        : e.metric_key;
      const met = def ? meetsTarget(e.value, e.target, def.direction) : null;
      const metStr =
        met === null
          ? ''
          : met
            ? t('common.yes', { defaultValue: 'Yes' })
            : t('common.no', { defaultValue: 'No' });
      return [
        csvCell(catLabel),
        csvCell(metricLabel),
        csvCell(def?.unit ?? ''),
        e.period,
        e.value,
        e.target ?? '',
        csvCell(metStr),
        csvCell(e.note ?? ''),
      ].join(',');
    });
    // Prepend a UTF-8 BOM so Excel opens accented notes/units correctly.
    const csv = '' + [headers.join(','), ...body].join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `esg-${projectSlug}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [entries, metrics, projectSlug, t]);

  // Print a compact per-period report card of all three pillars. Builds a
  // self-contained HTML doc and prints it from a new window (fully client-side).
  const handlePrintReport = useCallback(() => {
    if (!summary) return;
    const projectName =
      projects.find((p) => p.id === projectId)?.name ??
      t('esg.report_untitled_project', { defaultValue: 'Project' });
    const pillars = CATEGORY_ORDER.map((cat) => ({
      label: t(`esg.category_${cat}`, { defaultValue: CATEGORY_META[cat].label }),
      accent: PILLAR_PRINT_ACCENT[cat],
      metrics: (summary.by_category[cat] ?? [])
        .filter((m) => m.latest_value !== null)
        .map((m) => {
          const dp = m.delta_pct;
          return {
            label: t(`esg.metric_${m.metric_key}`, { defaultValue: m.label }),
            unit: m.unit,
            latest: fmtNum(toNum(m.latest_value)),
            target: m.target !== null ? fmtNum(toNum(m.target)) : '-',
            deltaLabel: dp === null ? '-' : `${dp > 0 ? '+' : ''}${numberFmt(dp)}%`,
            status: (m.on_track === true ? 'ok' : m.on_track === false ? 'bad' : 'muted') as
              | 'ok'
              | 'bad'
              | 'muted',
            statusLabel:
              m.on_track === true
                ? t('esg.status_on_track', { defaultValue: 'On track' })
                : m.on_track === false
                  ? t('esg.status_off_track', { defaultValue: 'Off target' })
                  : t('esg.status_no_target', { defaultValue: 'No target' }),
          };
        }),
    })).filter((p) => p.metrics.length > 0);

    const html = buildEsgReportHtml({
      projectName,
      periodLabel: summary.latest_period
        ? formatPeriod(summary.latest_period)
        : t('esg.report_no_period', { defaultValue: 'No readings yet' }),
      generatedLabel: new Date().toLocaleDateString(getIntlLocale(), {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }),
      offTrackCount: offTrackMetrics.length,
      pillars,
      labels: {
        title: t('esg.report_title', { defaultValue: 'ESG Site Performance Report' }),
        project: t('esg.report_project', { defaultValue: 'Project' }),
        period: t('esg.report_period', { defaultValue: 'Reporting period' }),
        generated: t('esg.report_generated', { defaultValue: 'Generated' }),
        offTrack: t('esg.off_track_banner', {
          defaultValue: '{{count}} metrics off target this period',
          count: offTrackMetrics.length,
        }),
        colMetric: t('esg.col_metric', { defaultValue: 'Metric' }),
        colLatest: t('esg.col_value', { defaultValue: 'Value' }),
        colTarget: t('esg.col_target', { defaultValue: 'Target' }),
        colChange: t('esg.report_col_change', { defaultValue: 'Change' }),
        colStatus: t('esg.report_col_status', { defaultValue: 'Status' }),
        footer: t('esg.report_footer', {
          defaultValue: 'This report was generated from recorded site ESG readings.',
        }),
        empty: t('esg.report_empty', { defaultValue: 'No readings recorded for this project yet.' }),
      },
    });

    const win = window.open('', '_blank', 'width=920,height=1000');
    if (!win) {
      addToast({
        type: 'error',
        title: t('esg.print_blocked_title', { defaultValue: 'Could not open print view' }),
        message: t('esg.print_blocked_msg', {
          defaultValue: 'Allow pop-ups for this site, then try again.',
        }),
      });
      return;
    }
    win.document.write(html);
    win.document.close();
  }, [summary, projects, projectId, offTrackMetrics.length, t, addToast]);

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        srTitle={t('esg.title', { defaultValue: 'ESG Site Performance' })}
        subtitle={t('esg.subtitle', {
          defaultValue:
            'Track operational site ESG each period - energy, water, waste, site CO2e, local labour, training and safety - against your targets.',
        })}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleExportCsv}
              disabled={entries.length === 0}
              title={t('esg.export_csv_hint', {
                defaultValue: 'Download every recorded reading as a CSV file',
              })}
              className="shrink-0 whitespace-nowrap"
            >
              <Download size={14} className="mr-1 shrink-0" />
              <span>{t('esg.export_csv', { defaultValue: 'Export CSV' })}</span>
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={handlePrintReport}
              disabled={!hasAnyReading}
              title={t('esg.print_report_hint', {
                defaultValue: 'Open a printable report card for the latest period',
              })}
              className="shrink-0 whitespace-nowrap"
            >
              <Printer size={14} className="mr-1 shrink-0" />
              <span>{t('esg.print_report', { defaultValue: 'Print report' })}</span>
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                if (!projectId) {
                  addToast({
                    type: 'info',
                    title: t('esg.select_project_first_title', { defaultValue: 'Select a project first' }),
                    message: t('esg.select_project_first', {
                      defaultValue: 'Pick a project from the top bar, then add a reading.',
                    }),
                  });
                  return;
                }
                openAdd(null);
              }}
              className="shrink-0 whitespace-nowrap"
            >
              <Plus size={14} className="mr-1 shrink-0" />
              <span>{t('esg.add_reading', { defaultValue: 'Add reading' })}</span>
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="esg"
        title={t('esg.intro_title', {
          defaultValue: 'How ESG site performance works',
        })}
        more={
          <IntroRichText
            text={t('esg.intro_more', {
              defaultValue:
                'ESG site performance turns everyday site facts into a simple per-period scorecard.\n\n**What you put in:** one reading per metric each period, for example energy used, water drawn, waste sent to landfill versus recycled, site CO2e, the share of local labour, training hours and safety incidents. Set a target next to each metric so the card knows what good looks like.\n\n**What you get back:**\n\n- The latest value with the change versus the previous period.\n- An on-track or off-target flag for every metric that has a target.\n- A trend line that appears once you have two or more periods.\n\n**Sharing:** export every reading as CSV for a client or regulator, or print a one-page report card covering the environmental, social and governance pillars.',
            })}
          />
        }
      >
        {t('esg.intro_body', {
          defaultValue:
            'Record one reading per metric each period and set a target for each. The cards roll up your latest value, the change versus the previous period and whether you are on or off track against that target.',
        })}
      </DismissibleInfo>

      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-40 animate-pulse rounded-xl bg-surface-secondary" />
          ))}
        </div>
      ) : isError ? (
        <Card className="p-6">
          <p className="text-sm text-semantic-error">{getErrorMessage(error)}</p>
          <Button variant="ghost" size="sm" onClick={() => refetch()} className="mt-3">
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </Card>
      ) : (
        <>
          {/* Status strip: latest period, how many metrics are tracked against
              a target, and how many missed it - with a one-click filter to
              focus on the exceptions. */}
          {hasAnyReading && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-content-secondary">
                {summary?.latest_period && (
                  <span className="inline-flex items-center gap-2">
                    <Activity size={15} className="text-oe-blue shrink-0" />
                    <span>
                      {t('esg.latest_period', { defaultValue: 'Latest reporting period' })}:{' '}
                      <span className="font-semibold text-content-primary">
                        {formatPeriod(summary.latest_period)}
                      </span>
                    </span>
                  </span>
                )}
                {trackedCount > 0 && (
                  <span className="inline-flex items-center gap-1.5 text-content-tertiary">
                    <Target size={14} className="shrink-0" />
                    {t('esg.tracked_against_target', {
                      defaultValue: '{{count}} tracked against target',
                      count: trackedCount,
                    })}
                  </span>
                )}
                {trackedCount > 0 &&
                  (offTrackMetrics.length > 0 ? (
                    <span className="inline-flex items-center gap-1.5 font-medium text-red-600 dark:text-red-400">
                      <AlertTriangle size={14} className="shrink-0" />
                      {t('esg.n_off_target', {
                        defaultValue: '{{count}} off target',
                        count: offTrackMetrics.length,
                      })}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 font-medium text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 size={14} className="shrink-0" />
                      {t('esg.all_on_track', { defaultValue: 'All metrics on track' })}
                    </span>
                  ))}
              </div>
              {offTrackMetrics.length > 0 && (
                <button
                  type="button"
                  onClick={() => setOnlyOffTrack((v) => !v)}
                  aria-pressed={onlyOffTrack}
                  className={clsx(
                    'inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
                    onlyOffTrack
                      ? 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                      : 'border-border-light text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                  )}
                >
                  <ListFilter size={14} className="shrink-0" />
                  {onlyOffTrack
                    ? t('esg.show_all_metrics', { defaultValue: 'Show all metrics' })
                    : t('esg.show_off_target_only', { defaultValue: 'Show off target only' })}
                </button>
              )}
            </div>
          )}

          {/* Pillars */}
          {CATEGORY_ORDER.map((cat) => {
            const allCards = summary?.by_category[cat] ?? [];
            // When the off-target filter is on, keep only metrics that missed
            // their target so the exceptions are easy to act on.
            const cards = onlyOffTrack
              ? allCards.filter((m) => m.on_track === false)
              : allCards;
            if (cards.length === 0) return null;
            const meta = CATEGORY_META[cat];
            const Icon = meta.icon;
            return (
              <section key={cat} className="space-y-3">
                <div className="flex items-center gap-2">
                  <Icon size={18} className={meta.accent} />
                  <h2 className="text-base font-semibold text-content-primary">
                    {t(`esg.category_${cat}`, { defaultValue: meta.label })}
                  </h2>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {cards.map((m) => (
                    <MetricCard key={m.metric_key} summary={m} onAdd={openAdd} />
                  ))}
                </div>
              </section>
            );
          })}

          {/* Recent readings */}
          {hasAnyReading ? (
            <section className="space-y-3">
              <h2 className="text-base font-semibold text-content-primary">
                {t('esg.recent_readings', { defaultValue: 'Recent readings' })}
              </h2>
              <RecentReadings
                entries={entries}
                metrics={metrics}
                onEdit={openEdit}
                onDelete={handleDelete}
              />
            </section>
          ) : (
            <EmptyState
              icon={<Leaf size={28} strokeWidth={1.5} />}
              title={t('esg.no_data_title', { defaultValue: 'No ESG readings yet' })}
              description={t('esg.no_data_desc', {
                defaultValue:
                  'Record your first period reading to start tracking site energy, water, waste, labour and safety against targets.',
              })}
              action={{
                label: t('esg.add_reading', { defaultValue: 'Add reading' }),
                onClick: () => openAdd(null),
              }}
            />
          )}
        </>
      )}

      {modalOpen && projectId && (
        <ReadingModal
          metrics={metrics}
          projectId={projectId}
          editEntry={editEntry}
          presetMetric={presetMetric}
          onClose={() => setModalOpen(false)}
          onSaved={invalidate}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
