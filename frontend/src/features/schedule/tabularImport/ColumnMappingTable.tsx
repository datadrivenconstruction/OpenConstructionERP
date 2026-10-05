// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which schedule field each column of the file is read as.
 *
 * The importer proposes a field per header with a confidence (exact header,
 * synonym, close spelling); the person can change any of them. A field is fed
 * by one column, so choosing a field already taken moves it (`chooseColumn`),
 * and the dialog sends back only the columns that differ from the proposal.
 */
import { useTranslation } from 'react-i18next';

import { Badge, ConfidenceBadge } from '@/shared/ui';
import { fieldLabel } from './labels';
import { IMPORT_FIELDS, type ImportColumn } from './tabularImport';

export interface ColumnMappingTableProps {
  columns: ImportColumn[];
  /** Column index -> chosen field (`''` = not imported). */
  chosen: Record<string, string>;
  onChoose: (column: string, field: string) => void;
  /** First data row of the file, to show what each column holds. */
  sample?: string[];
  disabled?: boolean;
}

export function ColumnMappingTable({ columns, chosen, onChoose, sample = [], disabled = false }: ColumnMappingTableProps) {
  const { t } = useTranslation();

  return (
    <div className="overflow-x-auto rounded-lg border border-border-light">
      <table className="w-full text-left text-xs">
        <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-secondary">
          <tr>
            <th className="px-3 py-2 font-medium">
              {t('schedule.tabular_import.col_header', { defaultValue: 'Column in the file' })}
            </th>
            <th className="px-3 py-2 font-medium">
              {t('schedule.tabular_import.col_sample', { defaultValue: 'First value' })}
            </th>
            <th className="px-3 py-2 font-medium">
              {t('schedule.tabular_import.col_field', { defaultValue: 'Import as' })}
            </th>
            <th className="px-3 py-2 font-medium">
              {t('schedule.tabular_import.col_confidence', { defaultValue: 'Match' })}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {columns.map((column) => {
            const key = String(column.index);
            const value = chosen[key] ?? column.field ?? '';
            const header =
              column.header ||
              t('schedule.tabular_import.col_unnamed', {
                defaultValue: 'Column {{number}}',
                number: column.index + 1,
              });
            return (
              <tr key={key} data-column={column.index}>
                <td className="px-3 py-2 font-medium text-content-primary">{header}</td>
                <td className="max-w-[12rem] truncate px-3 py-2 text-content-secondary" title={sample[column.index] ?? ''}>
                  {sample[column.index] ?? ''}
                </td>
                <td className="px-3 py-2">
                  <select
                    value={value}
                    disabled={disabled}
                    onChange={(e) => onChoose(key, e.target.value)}
                    aria-label={t('schedule.tabular_import.col_field_for', {
                      defaultValue: 'Import column "{{column}}" as',
                      column: header,
                    })}
                    className="w-full rounded-md border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  >
                    <option value="">
                      {t('schedule.tabular_import.field_none', { defaultValue: 'Do not import' })}
                    </option>
                    {IMPORT_FIELDS.map((field) => (
                      <option key={field} value={field}>
                        {fieldLabel(t, field)}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-3 py-2">
                  {column.tier === 'override' ? (
                    <Badge size="sm" variant="blue">
                      {t('schedule.tabular_import.match_override', { defaultValue: 'Chosen by you' })}
                    </Badge>
                  ) : column.field ? (
                    <ConfidenceBadge score={column.confidence} />
                  ) : (
                    <Badge size="sm" variant="neutral">
                      {t('schedule.tabular_import.match_none', { defaultValue: 'Not recognised' })}
                    </Badge>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
