// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BOQFilterBar — search + quick QA filters that sit directly above the grid.
 *
 * This narrows the GRID VIEW only. Totals, the grand total and exports keep
 * working off the full estimate, so filtering never changes the headline
 * numbers - it just helps you find and fix things in a large BOQ.
 *
 * Quick filters map to the validation-first workflow: jump straight to the
 * rows that need attention (errors, missing prices, zero quantities) or to the
 * AI-added rows you may want to review before trusting them.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X, AlertTriangle, CircleDollarSign, Hash, Sparkles, FileClock } from 'lucide-react';

export type BoqFilterKind = 'all' | 'errors' | 'no_price' | 'zero_qty' | 'ai' | 'drawing_revised';

export interface BOQFilterBarProps {
  search: string;
  onSearch: (value: string) => void;
  filter: BoqFilterKind;
  onFilter: (filter: BoqFilterKind) => void;
  /** Leaf positions currently shown vs. the total leaf count. */
  shown: number;
  total: number;
  /** True when a search term or a non-default filter is active. */
  active: boolean;
  onClear: () => void;
  /** Positions measured from a drawing that has since been revised; the chip shows only when above zero. */
  outdatedDrawingCount?: number;
  /** Visibility of the grid's Drawing column and its toggle. */
  showDrawingColumn?: boolean;
  onToggleDrawingColumn?: () => void;
}

export function BOQFilterBar({
  search,
  onSearch,
  filter,
  onFilter,
  shown,
  total,
  active,
  onClear,
  outdatedDrawingCount = 0,
  showDrawingColumn,
  onToggleDrawingColumn,
}: BOQFilterBarProps) {
  const { t } = useTranslation();

  const chips: { key: BoqFilterKind; label: string; icon: ReactNode }[] = [
    {
      key: 'errors',
      label: t('boq.filter_errors', { defaultValue: 'Errors' }),
      icon: <AlertTriangle size={12} />,
    },
    {
      key: 'no_price',
      label: t('boq.filter_no_price', { defaultValue: 'No price' }),
      icon: <CircleDollarSign size={12} />,
    },
    {
      key: 'zero_qty',
      label: t('boq.filter_zero_qty', { defaultValue: 'Zero qty' }),
      icon: <Hash size={12} />,
    },
    {
      key: 'ai',
      label: t('boq.filter_ai', { defaultValue: 'AI added' }),
      icon: <Sparkles size={12} />,
    },
    ...(outdatedDrawingCount > 0 || filter === 'drawing_revised'
      ? [
          {
            key: 'drawing_revised' as const,
            label: t('boq.filter_drawing_revised', {
              defaultValue: 'On revised drawings ({{count}})',
              count: outdatedDrawingCount,
            }),
            icon: <FileClock size={12} />,
          },
        ]
      : []),
  ];

  return (
    <div
      data-testid="boq-filter-bar"
      className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-2.5 py-1.5"
    >
      {/* Text search */}
      <div className="relative">
        <Search
          size={13}
          className="pointer-events-none absolute start-2 top-1/2 -translate-y-1/2 text-content-tertiary"
        />
        <input
          type="text"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={t('boq.filter_search_ph', { defaultValue: 'Search positions...' })}
          aria-label={t('boq.filter_search_aria', { defaultValue: 'Search positions by text or number' })}
          className="h-7 w-44 rounded-md border border-border-light bg-surface-primary ps-7 pe-6 text-xs text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 sm:w-56"
        />
        {search && (
          <button
            type="button"
            onClick={() => onSearch('')}
            aria-label={t('common.clear', { defaultValue: 'Clear' })}
            className="absolute end-1.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-primary"
          >
            <X size={13} />
          </button>
        )}
      </div>

      {/* Quick QA filter chips */}
      <div className="flex flex-wrap items-center gap-1">
        {chips.map((c) => {
          const isActive = filter === c.key;
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => onFilter(isActive ? 'all' : c.key)}
              aria-pressed={isActive}
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-2xs font-medium transition-colors ${
                isActive
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-primary text-content-secondary border border-border-light hover:bg-surface-secondary hover:text-content-primary'
              }`}
            >
              {c.icon}
              {c.label}
            </button>
          );
        })}
      </div>

      {onToggleDrawingColumn && (
        <button
          type="button"
          onClick={onToggleDrawingColumn}
          aria-pressed={!!showDrawingColumn}
          data-testid="drawing-column-toggle"
          className="text-2xs font-medium text-content-tertiary hover:text-content-primary hover:underline"
        >
          {showDrawingColumn
            ? t('boq.drawing_ref.hide_column', { defaultValue: 'Hide drawing column' })
            : t('boq.drawing_ref.show_column', { defaultValue: 'Show drawing column' })}
        </button>
      )}

      {/* Result count + clear */}
      {active && (
        <span className="ml-auto inline-flex items-center gap-2 text-2xs text-content-tertiary tabular-nums">
          {t('boq.filter_count', {
            defaultValue: '{{shown}} of {{total}}',
            shown,
            total,
          })}
          <button
            type="button"
            onClick={onClear}
            className="font-medium text-oe-blue hover:underline"
          >
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
        </span>
      )}
    </div>
  );
}
