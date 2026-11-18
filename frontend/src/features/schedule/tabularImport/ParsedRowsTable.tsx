// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The activities as the importer read them, one row per sheet or PDF table
 * row: the parsed dates and duration, a confidence and the worst problem on
 * the row. Read before confirming; nothing here is written.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';

import { DateDisplay } from '@/shared/ui';
import { fieldLabel, issueText } from './labels';
import { rowChecks, type TabularPreview } from './tabularImport';

/** Rows drawn; a longer table is summarised with a count. */
const MAX_SHOWN = 300;

const STATUS_ICON = {
  ok: <CheckCircle2 size={14} className="text-semantic-success" />,
  warning: <AlertTriangle size={14} className="text-semantic-warning" />,
  error: <XCircle size={14} className="text-semantic-error" />,
} as const;

export function ParsedRowsTable({ preview }: { preview: TabularPreview }) {
  const { t } = useTranslation();
  const activities = preview.document?.activities ?? [];
  const check = useMemo(() => rowChecks(preview), [preview]);
  if (activities.length === 0) return null;
  const shown = activities.slice(0, MAX_SHOWN);

  return (
    <div className="max-h-80 overflow-auto rounded-lg border border-border-light" data-testid="tabular-parsed-rows">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface-secondary text-left text-content-secondary">
          <tr>
            <th className="px-2 py-1.5 font-medium">#</th>
            <th className="px-2 py-1.5 font-medium">{fieldLabel(t, 'id')}</th>
            <th className="px-2 py-1.5 font-medium">{fieldLabel(t, 'name')}</th>
            <th className="px-2 py-1.5 font-medium">{fieldLabel(t, 'start')}</th>
            <th className="px-2 py-1.5 font-medium">{fieldLabel(t, 'finish')}</th>
            <th className="px-2 py-1.5 text-right font-medium">{fieldLabel(t, 'duration')}</th>
            <th className="px-2 py-1.5 text-right font-medium">
              {t('schedule.tabular_import.rows_confidence', { defaultValue: 'Confidence' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((activity) => {
            const row = activity.metadata?.import_row;
            const result = check(row);
            const first = result.issues[0];
            return (
              <tr key={activity.ref} className="border-t border-border-light align-top" data-status={result.status}>
                <td className="px-2 py-1 tabular-nums text-content-tertiary">{row ?? ''}</td>
                <td className="px-2 py-1 tabular-nums">{activity.activity_code ?? ''}</td>
                <td className="px-2 py-1">
                  <div className="text-content-primary">{activity.name}</div>
                  {first && <div className="text-2xs text-content-tertiary">{issueText(t, first)}</div>}
                </td>
                <td className="px-2 py-1 whitespace-nowrap">{activity.start_date ? <DateDisplay value={activity.start_date} /> : '-'}</td>
                <td className="px-2 py-1 whitespace-nowrap">{activity.end_date ? <DateDisplay value={activity.end_date} /> : '-'}</td>
                <td className="px-2 py-1 text-right tabular-nums">{activity.duration_days}</td>
                <td className="px-2 py-1">
                  <span className="flex items-center justify-end gap-1 tabular-nums">
                    {STATUS_ICON[result.status]}
                    {Math.round(result.confidence * 100)}%
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {activities.length > shown.length && (
        <p className="px-2 py-1.5 text-2xs text-content-tertiary">
          {t('schedule.tabular_import.rows_more', {
            defaultValue: 'More rows not shown: {{n}}',
            n: activities.length - shown.length,
          })}
        </p>
      )}
    </div>
  );
}
