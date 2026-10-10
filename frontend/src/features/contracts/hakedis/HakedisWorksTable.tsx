// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// HakedisWorksTable - the list of works done of one payment certificate.
//
// The columns are the server's, in the server's order: a unit price
// certificate lists quantities and a unit price, a lump sum one lists weights
// and percents, and a contract may choose its own set. Nothing is recomputed
// here. A money cell is printed from the decimal string behind it, every other
// numeric cell from its own string in the reader's number format, and a text
// cell as the server wrote it.
//
// A row that lacks data is counted in no total. It says so in words: its
// empty cells would otherwise read as zeros.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import { Badge } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { currencyFractionDigits } from '@/shared/lib/money';
import type { HakedisColumnKind, HakedisWorks, HakedisWorksColumn, HakedisWorksRow } from './api';
import { formatDecimalText } from './hakedisText';

const NUMERIC_KINDS: readonly HakedisColumnKind[] = ['quantity', 'unit_price', 'money', 'percent'];

function isNumeric(column: HakedisWorksColumn): boolean {
  return NUMERIC_KINDS.includes(column.kind);
}

interface HakedisWorksTableProps {
  works: HakedisWorks;
  currency: string;
  numberLocale: string;
  /** Names the table for assistive technology. */
  caption: string;
}

export function HakedisWorksTable({ works, currency, numberLocale, caption }: HakedisWorksTableProps) {
  const { t } = useTranslation();
  const { columns, rows } = works;
  // Where a section title and a total's title are written: the widest text column.
  const titleIndex = Math.max(
    0,
    columns.findIndex((column) => column.key === 'description'),
  );

  const cell = (row: HakedisWorksRow, column: HakedisWorksColumn, index: number) => {
    const value = row.values[index] ?? null;
    const text = row.cells[index] ?? '';
    if (!isNumeric(column) || value === null) return text;
    if (column.kind === 'money') return <MoneyDisplay amount={value} currency={currency || undefined} />;
    if (column.kind === 'unit_price') {
      return formatDecimalText(value, numberLocale, currencyFractionDigits(currency));
    }
    // Quantities and percents: two decimals at least, and every one the figure carries.
    return formatDecimalText(value, numberLocale, 2);
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-border-light" data-testid="hakedis-works">
      <table className="w-full min-w-[56rem] text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-secondary text-[10px] uppercase tracking-wide text-content-tertiary">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={clsx(
                  'px-2 py-2 align-bottom font-medium',
                  isNumeric(column) ? 'text-right' : 'text-left',
                  column.key === 'description' && 'min-w-[12rem]',
                )}
              >
                <span className="block whitespace-normal break-words">{column.labels.join(' / ')}</span>
                {column.letter && (
                  <span className="mt-0.5 block normal-case text-content-tertiary">{column.letter}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {/* Rows have no id of their own; their position is their identity. */}
          {rows.map((row, rowIndex) => {
            if (row.kind === 'section') {
              return (
                <tr key={`section-${rowIndex}`} className="bg-surface-secondary/60">
                  <th
                    scope="colgroup"
                    colSpan={columns.length}
                    className="break-words px-2 py-1.5 text-left font-semibold text-content-primary"
                  >
                    {row.title}
                  </th>
                </tr>
              );
            }
            const total = row.kind === 'subtotal' || row.kind === 'total';
            return (
              <tr
                key={`${row.kind}-${rowIndex}`}
                className={clsx(
                  total && 'bg-surface-secondary/40 font-semibold',
                  row.held && 'bg-amber-50/60 dark:bg-amber-950/20',
                )}
                data-testid={`hakedis-works-${row.kind}`}
                data-held={row.held ? 'true' : undefined}
              >
                {columns.map((column, index) => (
                  <td
                    key={column.key}
                    className={clsx(
                      'px-2 py-1.5 align-top',
                      isNumeric(column)
                        ? 'whitespace-nowrap text-right tabular-nums text-content-primary'
                        : 'break-words text-left text-content-secondary',
                    )}
                  >
                    {total && index === titleIndex ? (
                      <span className="text-content-primary">{row.title}</span>
                    ) : (
                      cell(row, column, index)
                    )}
                    {index === titleIndex && row.held && (
                      <span className="mt-1 block">
                        <Badge variant="warning" size="sm">
                          {t('hakedis.works.row_held', {
                            defaultValue: 'Data missing: this row is counted in no total',
                          })}
                        </Badge>
                      </span>
                    )}
                    {index === titleIndex && row.flagged && (
                      <span className="mt-1 block">
                        <Badge variant="warning" size="sm">
                          {t('hakedis.works.row_over', {
                            defaultValue: 'Over the contract: the total done exceeds what the contract states',
                          })}
                        </Badge>
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
