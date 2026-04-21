/**
 * Measurement Ledger — sortable, filterable table of ALL measurements.
 *
 * Rendered in the right sidebar when the "Ledger" tab is active.  Uses
 * the pure helpers in `lib/takeoff-ledger.ts` for sort/filter/subtotal
 * math so the component itself stays purely presentational.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  FileSpreadsheet,
  Filter,
  X,
} from 'lucide-react';
import type { Measurement } from '../lib/takeoff-types';
import {
  emptyFilter,
  filterMeasurements,
  groupSubtotals,
  ledgerToCsv,
  sortMeasurements,
  typeGrandTotals,
  uniqueFilterOptions,
  withOrdinals,
  type LedgerFilter,
  type LedgerSortColumn,
  type SortDirection,
} from '../lib/takeoff-ledger';

export interface MeasurementLedgerProps {
  measurements: Measurement[];
  /** Map of group name → hex color, for the row chip. */
  groupColorMap: Readonly<Record<string, string>>;
  /** Called when a row is clicked — parent navigates to the measurement. */
  onRowClick?: (measurement: Measurement) => void;
  /** Current selection, to highlight the matching row. */
  selectedMeasurementId?: string | null;
}

/** Column definitions — label, sort key, right-alignment. */
const COLUMNS: {
  key: LedgerSortColumn;
  label: string;
  align: 'left' | 'right';
}[] = [
  { key: 'ordinal', label: '#', align: 'right' },
  { key: 'type', label: 'Type', align: 'left' },
  { key: 'annotation', label: 'Annotation', align: 'left' },
  { key: 'group', label: 'Group', align: 'left' },
  { key: 'value', label: 'Value', align: 'right' },
  { key: 'unit', label: 'Unit', align: 'left' },
  { key: 'page', label: 'Page', align: 'right' },
];

export function MeasurementLedger({
  measurements,
  groupColorMap,
  onRowClick,
  selectedMeasurementId,
}: MeasurementLedgerProps) {
  const { t } = useTranslation();
  const [sortCol, setSortCol] = useState<LedgerSortColumn>('ordinal');
  const [sortDir, setSortDir] = useState<SortDirection>('asc');
  const [filter, setFilter] = useState<LedgerFilter>(emptyFilter());
  const [showFilters, setShowFilters] = useState(false);

  const options = useMemo(() => uniqueFilterOptions(measurements), [measurements]);

  const filtered = useMemo(
    () => filterMeasurements(measurements, filter),
    [measurements, filter],
  );

  const sorted = useMemo(
    () => sortMeasurements(filtered, sortCol, sortDir),
    [filtered, sortCol, sortDir],
  );

  const rows = useMemo(() => withOrdinals(sorted), [sorted]);
  const footers = useMemo(() => typeGrandTotals(sorted), [sorted]);

  // Build a grouped structure so we can slot subtotal rows between groups.
  const rowsByGroup = useMemo(() => {
    const map = new Map<string, typeof rows>();
    for (const row of rows) {
      const g = row.measurement.group || 'General';
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(row);
    }
    return Array.from(map.entries());
  }, [rows]);

  const subtotals = useMemo(() => groupSubtotals(sorted), [sorted]);
  const subtotalByGroup = useMemo(() => {
    const map = new Map<string, typeof subtotals[number]>();
    for (const s of subtotals) map.set(s.group, s);
    return map;
  }, [subtotals]);

  const toggleSort = (col: LedgerSortColumn) => {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  const toggleInSet = <T,>(set: Set<T>, value: T): Set<T> => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  };

  const clearFilters = () =>
    setFilter({ groups: new Set(), types: new Set(), pages: new Set() });

  const hasFilters =
    filter.groups.size > 0 || filter.types.size > 0 || filter.pages.size > 0;

  const handleExport = () => {
    const csv = ledgerToCsv(sorted);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `takeoff-ledger-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      className="rounded-md border border-border/80 bg-surface-primary/80 backdrop-blur-sm p-3 shadow-sm"
      data-testid="measurement-ledger"
    >
      <div className="flex items-center justify-between mb-2 gap-2">
        <p className="text-xs font-semibold text-content-primary">
          {t('takeoff_viewer.ledger', { defaultValue: 'Ledger' })}{' '}
          <span className="text-content-tertiary tabular-nums">
            ({rows.length}/{measurements.length})
          </span>
        </p>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setShowFilters((v) => !v)}
            className={clsx(
              'flex items-center gap-1 px-1.5 py-1 rounded text-[10px] transition-colors',
              showFilters || hasFilters
                ? 'bg-oe-blue/10 text-oe-blue border border-oe-blue/30'
                : 'hover:bg-surface-secondary text-content-tertiary border border-transparent',
            )}
            aria-pressed={showFilters}
            data-testid="ledger-filter-toggle"
          >
            <Filter size={10} />
            {t('takeoff_viewer.filters', { defaultValue: 'Filters' })}
            {hasFilters && (
              <span className="ml-0.5 h-1.5 w-1.5 rounded-full bg-oe-blue" />
            )}
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={rows.length === 0}
            className="flex items-center gap-1 px-1.5 py-1 rounded text-[10px] hover:bg-surface-secondary text-content-tertiary disabled:opacity-40 disabled:pointer-events-none transition-colors"
            title={t('takeoff_viewer.export_filtered_csv', {
              defaultValue: 'Export filtered view as CSV',
            })}
            data-testid="ledger-export-csv"
          >
            <FileSpreadsheet size={10} />
            CSV
          </button>
        </div>
      </div>

      {showFilters && (
        <div
          className="mb-2 rounded border border-border-light bg-surface-secondary/50 p-2 space-y-1.5"
          data-testid="ledger-filters"
        >
          <FilterChipGroup
            label={t('takeoff_viewer.filter_groups', { defaultValue: 'Groups' })}
            options={options.groups}
            active={filter.groups}
            onToggle={(v) =>
              setFilter((f) => ({ ...f, groups: toggleInSet(f.groups, v) }))
            }
            renderLabel={(g) => g}
            dataTestId="filter-group"
          />
          <FilterChipGroup
            label={t('takeoff_viewer.filter_types', { defaultValue: 'Types' })}
            options={options.types}
            active={filter.types}
            onToggle={(v) =>
              setFilter((f) => ({ ...f, types: toggleInSet(f.types, v) }))
            }
            renderLabel={(tp) => tp}
            dataTestId="filter-type"
          />
          <FilterChipGroup
            label={t('takeoff_viewer.filter_pages', { defaultValue: 'Pages' })}
            options={options.pages}
            active={filter.pages}
            onToggle={(v) =>
              setFilter((f) => ({ ...f, pages: toggleInSet(f.pages, v) }))
            }
            renderLabel={(p) => `p${p}`}
            dataTestId="filter-page"
          />
          {hasFilters && (
            <button
              type="button"
              onClick={clearFilters}
              className="flex items-center gap-1 text-[10px] text-content-tertiary hover:text-content-primary transition-colors"
            >
              <X size={9} />
              {t('takeoff_viewer.clear_filters', { defaultValue: 'Clear filters' })}
            </button>
          )}
        </div>
      )}

      {measurements.length === 0 ? (
        <p
          className="text-xs text-content-tertiary py-6 text-center"
          data-testid="ledger-empty"
        >
          {t('takeoff_viewer.ledger_empty', {
            defaultValue: 'No measurements yet — pick a tool to start.',
          })}
        </p>
      ) : (
        <div className="max-h-[500px] overflow-auto">
          <table
            className="w-full text-[11px] tabular-nums"
            data-testid="ledger-table"
          >
            <thead className="sticky top-0 bg-surface-primary/95 backdrop-blur-sm z-10">
              <tr className="border-b border-border">
                {COLUMNS.map((col) => {
                  const isActive = sortCol === col.key;
                  const Arrow =
                    isActive && sortDir === 'asc'
                      ? ArrowUp
                      : isActive && sortDir === 'desc'
                        ? ArrowDown
                        : ArrowUpDown;
                  return (
                    <th
                      key={col.key}
                      onClick={() => toggleSort(col.key)}
                      className={clsx(
                        'px-1.5 py-1 font-semibold text-content-secondary cursor-pointer select-none hover:bg-surface-secondary transition-colors',
                        col.align === 'right' ? 'text-right' : 'text-left',
                      )}
                      data-testid={`ledger-header-${col.key}`}
                      data-sort={isActive ? sortDir : undefined}
                    >
                      <span className="inline-flex items-center gap-0.5">
                        {col.label}
                        <Arrow
                          size={9}
                          className={clsx(
                            'shrink-0',
                            isActive ? 'text-oe-blue' : 'text-content-quaternary',
                          )}
                        />
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={COLUMNS.length}
                    className="text-center text-content-tertiary py-4"
                    data-testid="ledger-no-matches"
                  >
                    {t('takeoff_viewer.ledger_no_matches', {
                      defaultValue: 'No measurements match the current filters.',
                    })}
                  </td>
                </tr>
              )}
              {rowsByGroup.map(([group, groupRows]) => {
                const color = groupColorMap[group] ?? '#3B82F6';
                const sub = subtotalByGroup.get(group);
                return (
                  <GroupRows
                    key={group}
                    group={group}
                    groupRows={groupRows}
                    color={color}
                    subtotal={sub}
                    selectedId={selectedMeasurementId ?? null}
                    onRowClick={onRowClick}
                  />
                );
              })}
            </tbody>
            {footers.length > 0 && (
              <tfoot className="border-t-2 border-border bg-surface-secondary/40">
                {footers.map((gt) => (
                  <tr
                    key={gt.type}
                    data-testid="ledger-grand-total"
                    data-type={gt.type}
                  >
                    <td className="px-1.5 py-1 text-right text-content-tertiary" />
                    <td className="px-1.5 py-1 font-semibold text-content-primary capitalize">
                      Total {gt.type}
                    </td>
                    <td className="px-1.5 py-1 text-content-tertiary">
                      {gt.count} {t('takeoff_viewer.items', { defaultValue: 'items' })}
                    </td>
                    <td className="px-1.5 py-1" />
                    <td className="px-1.5 py-1 text-right font-semibold text-content-primary">
                      {formatNum(gt.total)}
                    </td>
                    <td className="px-1.5 py-1 text-content-secondary">{gt.unit}</td>
                    <td className="px-1.5 py-1" />
                  </tr>
                ))}
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  );
}

/** Rows for a single group, followed by subtotal rows (one per unit). */
function GroupRows({
  group,
  groupRows,
  color,
  subtotal,
  selectedId,
  onRowClick,
}: {
  group: string;
  groupRows: { ordinal: number; measurement: Measurement }[];
  color: string;
  subtotal?: { totals: Record<string, number>; count: number };
  selectedId: string | null;
  onRowClick?: (m: Measurement) => void;
}) {
  return (
    <>
      {groupRows.map(({ ordinal, measurement }) => {
        const selected = selectedId === measurement.id;
        return (
          <tr
            key={measurement.id}
            onClick={() => onRowClick?.(measurement)}
            className={clsx(
              'border-b border-border-light cursor-pointer transition-colors',
              selected ? 'bg-oe-blue/10' : 'hover:bg-surface-secondary/60',
            )}
            data-testid="ledger-row"
            data-measurement-id={measurement.id}
            data-selected={selected}
          >
            <td className="px-1.5 py-1 text-right text-content-tertiary font-mono">
              {ordinal}
            </td>
            <td className="px-1.5 py-1 capitalize">{measurement.type}</td>
            <td
              className="px-1.5 py-1 text-content-primary truncate max-w-[140px]"
              title={measurement.annotation}
            >
              {measurement.annotation || '—'}
            </td>
            <td className="px-1.5 py-1">
              <span className="inline-flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                {group}
              </span>
            </td>
            <td className="px-1.5 py-1 text-right font-mono">
              {formatNum(measurement.value)}
            </td>
            <td className="px-1.5 py-1 text-content-secondary">{measurement.unit || ''}</td>
            <td className="px-1.5 py-1 text-right text-content-tertiary">{measurement.page}</td>
          </tr>
        );
      })}
      {subtotal && Object.keys(subtotal.totals).length > 0 && (
        <>
          {Object.entries(subtotal.totals).map(([unit, total]) => (
            <tr
              key={`${group}-subtotal-${unit}`}
              className="bg-surface-secondary/40 border-b border-border-light italic"
              data-testid="ledger-subtotal"
              data-group={group}
              data-unit={unit}
            >
              <td />
              <td className="px-1.5 py-1 text-content-tertiary">subtotal</td>
              <td className="px-1.5 py-1 text-content-secondary">
                {group} · {subtotal.count}
              </td>
              <td />
              <td className="px-1.5 py-1 text-right font-semibold text-content-primary">
                {formatNum(total)}
              </td>
              <td className="px-1.5 py-1 text-content-secondary">{unit}</td>
              <td />
            </tr>
          ))}
        </>
      )}
    </>
  );
}

function FilterChipGroup<T extends string | number>({
  label,
  options,
  active,
  onToggle,
  renderLabel,
  dataTestId,
}: {
  label: string;
  options: T[];
  active: Set<T>;
  onToggle: (value: T) => void;
  renderLabel: (value: T) => string;
  dataTestId: string;
}) {
  if (options.length === 0) return null;
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-wider text-content-tertiary mb-0.5">
        {label}
      </p>
      <div className="flex flex-wrap gap-1">
        {options.map((opt) => {
          const on = active.has(opt);
          return (
            <button
              key={String(opt)}
              type="button"
              onClick={() => onToggle(opt)}
              className={clsx(
                'px-1.5 py-0.5 rounded-full text-[10px] border transition-colors',
                on
                  ? 'bg-oe-blue/15 text-oe-blue border-oe-blue/30'
                  : 'bg-surface-primary text-content-secondary border-border hover:border-oe-blue/40',
              )}
              data-testid={dataTestId}
              data-value={String(opt)}
              data-active={on}
            >
              {renderLabel(opt)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function formatNum(value: number): string {
  if (value === 0) return '0';
  const abs = Math.abs(value);
  if (abs < 1) return value.toFixed(3);
  if (abs < 100) return value.toFixed(2);
  return value.toFixed(1);
}

export default MeasurementLedger;
