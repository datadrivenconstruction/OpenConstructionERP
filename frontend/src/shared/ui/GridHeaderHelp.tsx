/**
 * <GridHeaderHelp> — an AG Grid `headerComponent` that puts the same
 * glossary (i) help into a column header, so field-level help reaches
 * the data grids (BOQ / estimating) where the densest jargon lives.
 *
 * It keeps the native behaviour a plain header has — click to sort, with
 * a sort arrow — and adds an InfoHint trigger reading `glossary.<term>`
 * (or an explicit `helpText`). Wire it per-column:
 *
 *   {
 *     headerName: 'Unit rate',
 *     headerComponent: GridHeaderHelp,
 *     headerComponentParams: { glossaryTerm: 'unit_rate' },
 *   }
 *
 * Plain everyday columns are left as plain headers — target jargon only,
 * not a wall of (i) icons.
 */

import { useEffect, useState, type MouseEvent } from 'react';
import type { IHeaderParams } from 'ag-grid-community';
import { ArrowDown, ArrowUp } from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { InfoHint } from './InfoHint';

export interface GridHeaderHelpParams extends IHeaderParams {
  /** Glossary key suffix; reads `glossary.<term>` for the (i) popover. */
  glossaryTerm?: string;
  /** Explicit pre-translated help string; wins over `glossaryTerm`. */
  helpText?: string;
}

export function GridHeaderHelp(params: GridHeaderHelpParams) {
  const { t } = useTranslation();
  const { displayName, enableSorting, column, progressSort, glossaryTerm, helpText } = params;

  const [sort, setSort] = useState<'asc' | 'desc' | null>(column.getSort() ?? null);

  useEffect(() => {
    const onSortChanged = () => setSort(column.getSort() ?? null);
    column.addEventListener('sortChanged', onSortChanged);
    return () => column.removeEventListener('sortChanged', onSortChanged);
  }, [column]);

  const help = helpText ?? (glossaryTerm ? t(`glossary.${glossaryTerm}`, { defaultValue: '' }) : '');

  const onLabelClick = (e: MouseEvent) => {
    if (enableSorting) progressSort(e.shiftKey);
  };

  return (
    <div className="flex w-full items-center gap-1">
      <span
        className={clsx('flex min-w-0 items-center gap-1', enableSorting && 'cursor-pointer select-none')}
        onClick={onLabelClick}
        role={enableSorting ? 'button' : undefined}
      >
        <span className="truncate">{displayName}</span>
        {sort === 'asc' && <ArrowUp size={12} className="shrink-0 text-content-tertiary" />}
        {sort === 'desc' && <ArrowDown size={12} className="shrink-0 text-content-tertiary" />}
      </span>
      {help && <InfoHint inline text={help} className="shrink-0" />}
    </div>
  );
}
