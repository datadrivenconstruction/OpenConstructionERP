/**
 * Cascade Filter Panel (T04).
 *
 * A vertical stack of multi-select filter cards, one per active column.
 * Picking a chip on one card narrows the value pickers on every other
 * card — the "Tableau cascade filter" / "Power BI relative filter"
 * pattern.
 *
 * Each card:
 *   - shows the column's currently-selected values as removable chips
 *   - exposes a debounced text input that fetches cascade-aware
 *     candidates (the *other* columns' selections are sent as the
 *     `selected` map; that column itself is excluded so the picker
 *     keeps showing all its own potential values)
 *   - has a "Clear" button that drops every chip on that column
 *
 * A live "X of Y rows match" counter sits above the stack; a
 * "Reset all" button at the very top wipes every selection at once.
 *
 * The fetch flow is debounced per-card (default 250 ms). React Query
 * keys mix the snapshot id, the column, the debounced query AND a
 * stringified version of "selections OTHER than this column" so the
 * cascade re-fetches when *any* sibling card changes, even when the
 * card's own input is idle.
 */
import { useCallback, useEffect, useId, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Filter, RotateCcw, Search, X } from 'lucide-react';

import {
  getCascadeRowCount,
  getCascadeValues,
  type CascadeValue,
} from './api';
import { useDebouncedValue } from './SmartValueAutocomplete';

/* ── Types ───────────────────────────────────────────────────────────── */

export type CascadeSelection = Record<string, string[]>;

export interface CascadeFilterPanelProps {
  snapshotId: string;
  /** The columns that the user is filtering on. Order is preserved. */
  columns: string[];
  /** Optional human-readable column labels (column → label). */
  labels?: Record<string, string>;
  /** Current selection map. Empty arrays mean "no filter on that column". */
  value: CascadeSelection;
  /** Called whenever the selection changes (chip add / remove / reset). */
  onChange: (next: CascadeSelection) => void;
  /** Per-card debounce on the cascade fetch (default 250 ms). */
  debounceMs?: number;
  /** Maximum candidates fetched per card (default 25, max 200). */
  limitPerColumn?: number;
  className?: string;
  disabled?: boolean;
}

/* ── Helpers ─────────────────────────────────────────────────────────── */

/**
 * Return a copy of `selection` with `column` removed. Used to build the
 * "other columns" map each card sends to the cascade endpoint — a
 * column never gates its own picker.
 */
function selectionExcept(
  selection: CascadeSelection,
  column: string,
): CascadeSelection {
  const out: CascadeSelection = {};
  for (const [k, v] of Object.entries(selection)) {
    if (k === column) continue;
    if (v && v.length > 0) out[k] = v;
  }
  return out;
}

/** Stable JSON for use as a React Query key (sorted keys). */
function stableKey(obj: CascadeSelection): string {
  const sorted = Object.keys(obj).sort();
  const payload: Record<string, string[]> = {};
  for (const k of sorted) {
    const values = obj[k] ?? [];
    payload[k] = [...values].sort();
  }
  return JSON.stringify(payload);
}

/* ── Component ───────────────────────────────────────────────────────── */

export function CascadeFilterPanel({
  snapshotId,
  columns,
  labels,
  value,
  onChange,
  debounceMs = 250,
  limitPerColumn = 25,
  className,
  disabled,
}: CascadeFilterPanelProps) {
  const { t } = useTranslation();

  const handleResetAll = useCallback(() => {
    onChange({});
  }, [onChange]);

  const handleClearColumn = useCallback(
    (column: string) => {
      const next = { ...value };
      delete next[column];
      onChange(next);
    },
    [value, onChange],
  );

  const handleRemoveChip = useCallback(
    (column: string, chip: string) => {
      const current = value[column] ?? [];
      const remaining = current.filter((c) => c !== chip);
      const next = { ...value };
      if (remaining.length === 0) delete next[column];
      else next[column] = remaining;
      onChange(next);
    },
    [value, onChange],
  );

  const handleAddChip = useCallback(
    (column: string, chip: string) => {
      const current = value[column] ?? [];
      if (current.includes(chip)) return; // already there
      onChange({ ...value, [column]: [...current, chip] });
    },
    [value, onChange],
  );

  /* Live row counter — re-runs whenever the selection changes. */
  const selectionStable = stableKey(value);
  const rowCountQuery = useQuery({
    queryKey: ['dashboards-cascade-rowcount', snapshotId, selectionStable],
    queryFn: () => getCascadeRowCount(snapshotId, value),
    enabled: !!snapshotId,
    staleTime: 30 * 1000,
  });

  const totalChips = useMemo(
    () => Object.values(value).reduce((acc, arr) => acc + arr.length, 0),
    [value],
  );

  return (
    <div
      className={`flex flex-col gap-3 ${className ?? ''}`}
      data-testid="cascade-filter-panel"
    >
      <div className="flex items-center justify-between gap-2 text-sm">
        <div className="flex items-center gap-2 text-content-secondary">
          <Filter className="h-4 w-4" />
          <span data-testid="cascade-row-count">
            {rowCountQuery.data
              ? t('dashboards.cascade.rows_match', {
                  defaultValue: '{{matched}} of {{total}} rows match',
                  matched: rowCountQuery.data.matched.toLocaleString(),
                  total: rowCountQuery.data.total.toLocaleString(),
                })
              : t('dashboards.cascade.rows_loading', {
                  defaultValue: 'Counting rows…',
                })}
          </span>
        </div>
        <button
          type="button"
          onClick={handleResetAll}
          disabled={disabled || totalChips === 0}
          className="flex items-center gap-1 rounded border border-border-light px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          data-testid="cascade-reset-all"
        >
          <RotateCcw className="h-3 w-3" />
          {t('dashboards.cascade.reset_all', {
            defaultValue: 'Reset all filters',
          })}
        </button>
      </div>

      {columns.map((column) => (
        <CascadeFilterCard
          key={column}
          snapshotId={snapshotId}
          column={column}
          label={labels?.[column] ?? column}
          chips={value[column] ?? []}
          others={selectionExcept(value, column)}
          onAddChip={(chip) => handleAddChip(column, chip)}
          onRemoveChip={(chip) => handleRemoveChip(column, chip)}
          onClearColumn={() => handleClearColumn(column)}
          debounceMs={debounceMs}
          limit={limitPerColumn}
          disabled={disabled}
        />
      ))}
    </div>
  );
}

/* ── Per-column card ─────────────────────────────────────────────────── */

interface CascadeFilterCardProps {
  snapshotId: string;
  column: string;
  label: string;
  chips: string[];
  others: CascadeSelection;
  onAddChip: (chip: string) => void;
  onRemoveChip: (chip: string) => void;
  onClearColumn: () => void;
  debounceMs: number;
  limit: number;
  disabled?: boolean;
}

function CascadeFilterCard({
  snapshotId,
  column,
  label,
  chips,
  others,
  onAddChip,
  onRemoveChip,
  onClearColumn,
  debounceMs,
  limit,
  disabled,
}: CascadeFilterCardProps) {
  const { t } = useTranslation();
  const inputId = useId();
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebouncedValue(query, debounceMs);
  const othersStable = stableKey(others);

  const cascadeQuery = useQuery({
    queryKey: [
      'dashboards-cascade-values',
      snapshotId,
      column,
      debouncedQuery,
      othersStable,
      limit,
    ],
    queryFn: () =>
      getCascadeValues(snapshotId, {
        selected: others,
        target_column: column,
        q: debouncedQuery,
        limit,
      }),
    enabled: !!snapshotId && !!column,
    staleTime: 5 * 1000,
  });

  // When the user picks an option that's already a chip, the input
  // should still clear so they can pick the next value without manually
  // emptying it.
  useEffect(() => {
    if (chips.length === 0) setQuery('');
  }, [chips.length]);

  const candidates: CascadeValue[] = cascadeQuery.data?.values ?? [];
  const selectableCandidates = candidates.filter(
    (c) => !chips.includes(c.value),
  );

  return (
    <div
      className="flex flex-col gap-2 rounded border border-border-light bg-surface-primary p-3"
      data-testid={`cascade-card-${column}`}
    >
      <div className="flex items-center justify-between gap-2">
        <label
          htmlFor={inputId}
          className="text-xs font-medium uppercase tracking-wide text-content-tertiary"
        >
          {label}
        </label>
        {chips.length > 0 && (
          <button
            type="button"
            onClick={onClearColumn}
            disabled={disabled}
            className="text-xs text-content-tertiary hover:text-content-primary"
            data-testid={`cascade-clear-${column}`}
          >
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
        )}
      </div>

      {chips.length > 0 && (
        <div
          className="flex flex-wrap gap-1"
          data-testid={`cascade-chips-${column}`}
        >
          {chips.map((chip) => (
            <span
              key={chip}
              className="inline-flex items-center gap-1 rounded-full bg-oe-blue/15 px-2 py-0.5 text-xs text-content-primary"
              data-testid={`cascade-chip-${column}-${chip}`}
            >
              <span className="max-w-[12rem] truncate">{chip}</span>
              <button
                type="button"
                onClick={() => onRemoveChip(chip)}
                disabled={disabled}
                aria-label={t('common.remove', { defaultValue: 'Remove' })}
                className="rounded p-0.5 hover:bg-oe-blue/25 disabled:opacity-40"
                data-testid={`cascade-chip-x-${column}-${chip}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
        <input
          id={inputId}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('dashboards.cascade.search_ph', {
            defaultValue: 'Search values…',
          })}
          disabled={disabled}
          className="w-full rounded border border-border-light bg-surface-primary px-7 py-1.5 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
          data-testid={`cascade-input-${column}`}
        />
      </div>

      <ul
        className="max-h-48 overflow-auto rounded border border-border-light bg-surface-secondary text-sm"
        role="listbox"
        data-testid={`cascade-list-${column}`}
      >
        {cascadeQuery.isError && (
          <li className="px-3 py-2 text-xs text-rose-300">
            {t('dashboards.cascade.error', {
              defaultValue: 'Could not load values',
            })}
          </li>
        )}
        {!cascadeQuery.isError && selectableCandidates.length === 0 && (
          <li className="px-3 py-2 text-xs text-content-tertiary">
            {cascadeQuery.isLoading
              ? t('common.loading', { defaultValue: 'Loading…' })
              : t('dashboards.cascade.empty', {
                  defaultValue: 'No matching values',
                })}
          </li>
        )}
        {selectableCandidates.map((c) => (
          <li
            key={c.value}
            role="option"
            aria-selected={false}
            className="flex items-center justify-between gap-2 px-3 py-1 hover:bg-surface-tertiary"
          >
            <button
              type="button"
              onClick={() => onAddChip(c.value)}
              disabled={disabled}
              className="flex flex-1 items-center justify-between gap-2 text-left text-content-secondary disabled:opacity-40"
              data-testid={`cascade-option-${column}-${c.value}`}
            >
              <span className="truncate">{c.value}</span>
              <span className="shrink-0 text-xs tabular-nums text-content-tertiary">
                {c.count.toLocaleString()}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default CascadeFilterPanel;
