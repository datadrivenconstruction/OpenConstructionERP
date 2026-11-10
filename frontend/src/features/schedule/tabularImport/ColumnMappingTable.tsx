// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
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
      <table className="oe-table-compact text-left">
        <thead>
          <tr>
            <th>
              {t('schedule.tabular_import.col_header', { defaultValue: 'Column in the file' })}
            </th>
            <th>
              {t('schedule.tabular_import.col_sample', { defaultValue: 'First value' })}
            </th>
            <th>
              {t('schedule.tabular_import.col_field', { defaultValue: 'Import as' })}
            </th>
            <th>
              {t('schedule.tabular_import.col_confidence', { defaultValue: 'Match' })}
            </th>
          </tr>
        </thead>
        <tbody>
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
                <td>{header}</td>
                <td className="max-w-[12rem] truncate text-content-secondary" title={sample[column.index] ?? ''}>
                  {sample[column.index] ?? ''}
                </td>
                <td>
                  <select
                    value={value}
                    disabled={disabled}
                    onChange={(e) => onChoose(key, e.target.value)}
                    aria-label={t('schedule.tabular_import.col_field_for', {
                      defaultValue: 'Import column "{{column}}" as',
                      column: header,
                    })}
                    className="oe-select oe-input-sm"
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
                <td>
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
