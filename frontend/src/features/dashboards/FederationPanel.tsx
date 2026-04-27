/**
 * FederationPanel (T10 / task #193).
 *
 * Lets the user pick N snapshots from one or more projects, choose a
 * schema-alignment mode (intersect / union / strict), name a measure
 * column + an optional group-by, and see the federated rollup as a
 * table with per-row provenance chips.
 *
 * The panel is intentionally self-contained — it keeps every selection
 * in local state and only calls the parent through `onResults` when the
 * server returns a successful aggregate. That way the host page can
 * re-render its own headline numbers without wiring a controlled state
 * graph through every prop.
 */
import { useCallback, useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, Layers, Loader2, Play, X } from 'lucide-react';

import { Button } from '@/shared/ui';

import {
  buildFederation,
  federatedAggregate,
  type FederationAggKind,
  type FederationAggregateResponse,
  type FederationSchemaAlign,
  type FederationView,
} from './api';
import { FederatedResultsTable } from './FederatedResultsTable';

export interface FederationPanelSnapshotOption {
  id: string;
  label: string;
  /** Human-readable project label (rendered next to the snapshot label). */
  projectLabel?: string;
  /** Project id — used to populate the `projectLabels` map for chips. */
  projectId?: string;
}

export interface FederationPanelProps {
  /** Snapshots the user can pick from. Caller is responsible for
   * narrowing to "snapshots the caller can read" — the panel does
   * not filter for tenant scope itself. */
  available: FederationPanelSnapshotOption[];
  /** Default selection — typically the page's currently active snapshot. */
  initialSelection?: string[];
  /** Optional callback invoked with the latest successful aggregate
   * response. */
  onResults?: (result: FederationAggregateResponse) => void;
  className?: string;
}

const SCHEMA_ALIGN_MODES: FederationSchemaAlign[] = ['intersect', 'union', 'strict'];
const AGG_OPTIONS: FederationAggKind[] = ['count', 'sum', 'avg', 'min', 'max'];

export function FederationPanel({
  available,
  initialSelection,
  onResults,
  className,
}: FederationPanelProps) {
  const { t } = useTranslation();

  const [selected, setSelected] = useState<string[]>(initialSelection ?? []);
  const [schemaAlign, setSchemaAlign] = useState<FederationSchemaAlign>('intersect');
  const [view, setView] = useState<FederationView | null>(null);
  const [groupBy, setGroupBy] = useState<string>('');
  const [measure, setMeasure] = useState<string>('*');
  const [agg, setAgg] = useState<FederationAggKind>('count');
  const [results, setResults] = useState<FederationAggregateResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const snapshotLabels = useMemo<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const o of available) out[o.id] = o.label;
    return out;
  }, [available]);

  const projectLabels = useMemo<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const o of available) {
      if (o.projectId && o.projectLabel) out[o.projectId] = o.projectLabel;
    }
    return out;
  }, [available]);

  const buildMutation = useMutation({
    mutationFn: () =>
      buildFederation({ snapshotIds: selected, schemaAlign }),
    onSuccess: (v) => {
      setView(v);
      setErrorMsg(null);
      // Reset measure when schema changes (column may not exist).
      if (measure !== '*' && !v.columns.includes(measure)) {
        setMeasure('*');
        setAgg('count');
      }
      if (groupBy && !v.columns.includes(groupBy)) {
        setGroupBy('');
      }
    },
    onError: (err: unknown) => {
      setErrorMsg(extractError(err, t));
    },
  });

  const aggregateMutation = useMutation({
    mutationFn: () =>
      federatedAggregate({
        snapshotIds: selected,
        schemaAlign,
        groupBy: groupBy ? [groupBy] : [],
        measure,
        agg,
      }),
    onSuccess: (data) => {
      setResults(data);
      setErrorMsg(null);
      onResults?.(data);
    },
    onError: (err: unknown) => {
      setErrorMsg(extractError(err, t));
    },
  });

  const toggleSnapshot = useCallback((id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
    setView(null);
    setResults(null);
  }, []);

  const removeChip = useCallback((id: string) => {
    setSelected((prev) => prev.filter((x) => x !== id));
    setView(null);
    setResults(null);
  }, []);

  const userColumns = useMemo<string[]>(() => {
    if (!view) return [];
    return view.columns.filter(
      (c) => c !== '__project_id' && c !== '__snapshot_id',
    );
  }, [view]);

  const canBuild = selected.length > 0 && !buildMutation.isPending;
  const canAggregate =
    !!view && !aggregateMutation.isPending && (measure === '*' || !!measure);

  return (
    <section
      className={`space-y-4 rounded border border-border-light bg-surface-primary p-4 ${className ?? ''}`}
      data-testid="federation-panel"
    >
      <header className="flex items-center gap-2">
        <Layers className="h-4 w-4 text-emerald-400" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('dashboards.federation.title', {
            defaultValue: 'Multi-Source Federation',
          })}
        </h3>
      </header>

      {/* ── Snapshot picker ─────────────────────────────────────────── */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-content-secondary">
          {t('dashboards.federation.pick_snapshots', {
            defaultValue: 'Pick snapshots to federate',
          })}
        </label>
        <div className="flex flex-wrap gap-1.5" data-testid="federation-selected-chips">
          {selected.length === 0 && (
            <span className="text-xs italic text-content-tertiary">
              {t('dashboards.federation.no_snapshots_selected', {
                defaultValue: 'No snapshots selected',
              })}
            </span>
          )}
          {selected.map((id) => (
            <span
              key={id}
              className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300"
              data-testid={`federation-chip-${id}`}
            >
              <span className="max-w-[140px] truncate">
                {snapshotLabels[id] ?? id}
              </span>
              <button
                type="button"
                onClick={() => removeChip(id)}
                aria-label={t('dashboards.federation.remove_snapshot', {
                  defaultValue: 'Remove snapshot',
                })}
                className="rounded hover:bg-emerald-500/20"
                data-testid={`federation-chip-remove-${id}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>

        <div
          className="max-h-40 overflow-y-auto rounded border border-border-light"
          role="listbox"
          aria-multiselectable="true"
          data-testid="federation-snapshot-listbox"
        >
          {available.length === 0 ? (
            <div className="px-3 py-2 text-xs text-content-tertiary">
              {t('dashboards.federation.no_snapshots_available', {
                defaultValue: 'No snapshots available.',
              })}
            </div>
          ) : (
            available.map((opt) => {
              const isSelected = selected.includes(opt.id);
              return (
                <button
                  key={opt.id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => toggleSnapshot(opt.id)}
                  data-testid={`federation-snapshot-option-${opt.id}`}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface-secondary ${
                    isSelected ? 'bg-emerald-500/5 text-emerald-200' : 'text-content-primary'
                  }`}
                >
                  <span className="flex h-3 w-3 flex-shrink-0 items-center justify-center">
                    {isSelected && <Check className="h-3 w-3 text-emerald-400" />}
                  </span>
                  <span className="flex-1 truncate">{opt.label}</span>
                  {opt.projectLabel && (
                    <span className="flex-shrink-0 text-[10px] text-content-tertiary">
                      {opt.projectLabel}
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* ── Schema-align mode ───────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs font-medium text-content-secondary">
          {t('dashboards.federation.schema_align', {
            defaultValue: 'Schema alignment',
          })}
        </label>
        <select
          className="rounded border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary"
          value={schemaAlign}
          onChange={(e) => {
            setSchemaAlign(e.target.value as FederationSchemaAlign);
            setView(null);
            setResults(null);
          }}
          data-testid="federation-schema-align"
        >
          {SCHEMA_ALIGN_MODES.map((m) => (
            <option key={m} value={m}>
              {t(`dashboards.federation.schema_align_${m}`, { defaultValue: m })}
            </option>
          ))}
        </select>

        <Button
          size="sm"
          variant="primary"
          onClick={() => buildMutation.mutate()}
          disabled={!canBuild}
          data-testid="federation-build-btn"
          className="ml-auto"
        >
          {buildMutation.isPending ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <Play className="mr-1 h-3 w-3" />
          )}
          {t('dashboards.federation.build', { defaultValue: 'Build view' })}
        </Button>
      </div>

      {/* ── View summary + aggregate controls ───────────────────────── */}
      {view && (
        <div
          className="space-y-2 rounded border border-border-light bg-surface-secondary/40 p-3"
          data-testid="federation-view-summary"
        >
          <p className="text-xs text-content-secondary">
            {t('dashboards.federation.view_summary', {
              defaultValue:
                '{{snapshots}} snapshots • {{projects}} projects • {{rows}} rows',
              snapshots: view.snapshot_count,
              projects: view.project_count,
              rows: view.row_count,
            })}
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-content-secondary">
              {t('dashboards.federation.group_by', { defaultValue: 'Group by' })}
            </label>
            <select
              className="rounded border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary"
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value)}
              data-testid="federation-group-by"
            >
              <option value="">
                {t('dashboards.federation.no_group_by', {
                  defaultValue: '(none — group by source only)',
                })}
              </option>
              {userColumns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>

            <label className="text-xs text-content-secondary">
              {t('dashboards.federation.measure', { defaultValue: 'Measure' })}
            </label>
            <select
              className="rounded border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary"
              value={measure}
              onChange={(e) => {
                const next = e.target.value;
                setMeasure(next);
                if (next === '*') setAgg('count');
              }}
              data-testid="federation-measure"
            >
              <option value="*">
                {t('dashboards.federation.measure_count_rows', {
                  defaultValue: 'Count rows',
                })}
              </option>
              {userColumns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>

            <select
              className="rounded border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary"
              value={agg}
              onChange={(e) => setAgg(e.target.value as FederationAggKind)}
              data-testid="federation-agg"
              disabled={measure === '*'}
            >
              {AGG_OPTIONS.map((a) => (
                <option key={a} value={a}>
                  {t(`dashboards.federation.agg_${a}`, { defaultValue: a })}
                </option>
              ))}
            </select>

            <Button
              size="sm"
              variant="primary"
              onClick={() => aggregateMutation.mutate()}
              disabled={!canAggregate}
              data-testid="federation-aggregate-btn"
              className="ml-auto"
            >
              {aggregateMutation.isPending ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Play className="mr-1 h-3 w-3" />
              )}
              {t('dashboards.federation.run', { defaultValue: 'Run aggregate' })}
            </Button>
          </div>
        </div>
      )}

      {errorMsg && (
        <div
          className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300"
          role="alert"
          data-testid="federation-error"
        >
          {errorMsg}
        </div>
      )}

      <FederatedResultsTable
        data={results}
        snapshotLabels={snapshotLabels}
        projectLabels={projectLabels}
      />
    </section>
  );
}

function extractError(err: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  if (err && typeof err === 'object' && 'message' in err) {
    const m = (err as { message?: string }).message;
    if (typeof m === 'string' && m.trim().length > 0) return m;
  }
  return t('dashboards.federation.error_generic', {
    defaultValue: 'Federation request failed.',
  });
}
