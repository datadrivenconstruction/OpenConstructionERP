// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The importer's findings, errors first, each one pointing at its sheet row
 * and column so the person can fix the file where the problem is.
 */
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info, XCircle } from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui';
import { issueText } from './labels';
import type { ImportColumn, ImportIssue, IssueSeverity } from './tabularImport';

const ORDER: IssueSeverity[] = ['error', 'warning', 'info'];

const ICONS = {
  error: <XCircle size={14} className="mt-0.5 shrink-0 text-semantic-error" />,
  warning: <AlertTriangle size={14} className="mt-0.5 shrink-0 text-semantic-warning" />,
  info: <Info size={14} className="mt-0.5 shrink-0 text-content-tertiary" />,
} as const;

export interface ImportIssuesListProps {
  issues: ImportIssue[];
  /** The file's columns, to name a column by its header rather than its number. */
  columns?: ImportColumn[];
  /** Hide the informational notes (the commit refusal lists errors only). */
  hideInfo?: boolean;
  testId?: string;
}

export function ImportIssuesList({ issues, columns = [], hideInfo = false, testId }: ImportIssuesListProps) {
  const { t } = useTranslation();
  const headers = new Map(columns.map((c) => [c.index, c.header]));
  const shown = issues.filter((issue) => !(hideInfo && issue.severity === 'info'));

  if (shown.length === 0) {
    return (
      <p className="text-xs text-content-tertiary" data-testid={testId}>
        {t('schedule.tabular_import.issues_none', { defaultValue: 'No problems found in the file.' })}
      </p>
    );
  }

  const sorted = [...shown].sort(
    (a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity) || (a.row ?? 0) - (b.row ?? 0),
  );
  const counts = ORDER.map((severity) => [severity, shown.filter((i) => i.severity === severity).length] as const);

  const where = (issue: ImportIssue): string | null => {
    const header = issue.column !== null && issue.column !== undefined ? headers.get(issue.column) : undefined;
    if (issue.row && header) {
      return t('schedule.tabular_import.issue_where_row_column', {
        defaultValue: 'Row {{row}}, column "{{column}}"',
        row: issue.row,
        column: header,
      });
    }
    if (issue.row) {
      return t('schedule.tabular_import.issue_where_row', { defaultValue: 'Row {{row}}', row: issue.row });
    }
    if (header) {
      return t('schedule.tabular_import.issue_where_column', {
        defaultValue: 'Column "{{column}}"',
        column: header,
      });
    }
    return null;
  };

  return (
    <div className="space-y-2" data-testid={testId}>
      <div className="flex flex-wrap gap-1.5">
        {counts.map(([severity, count]) =>
          count > 0 ? (
            <Badge
              key={severity}
              size="sm"
              variant={severity === 'error' ? 'error' : severity === 'warning' ? 'warning' : 'neutral'}
            >
              {severity === 'error'
                ? t('schedule.tabular_import.count_errors', {
                    count,
                    defaultValue_one: '{{count}} error',
                    defaultValue_other: '{{count}} errors',
                  })
                : severity === 'warning'
                  ? t('schedule.tabular_import.count_warnings', {
                      count,
                      defaultValue_one: '{{count}} warning',
                      defaultValue_other: '{{count}} warnings',
                    })
                  : t('schedule.tabular_import.count_notes', {
                      count,
                      defaultValue_one: '{{count}} note',
                      defaultValue_other: '{{count}} notes',
                    })}
            </Badge>
          ) : null,
        )}
      </div>
      <ul className="max-h-64 divide-y divide-border-light overflow-y-auto rounded-lg border border-border-light">
        {sorted.map((issue, index) => {
          const place = where(issue);
          return (
            <li
              key={`${issue.code}-${issue.row ?? 'x'}-${issue.column ?? 'x'}-${index}`}
              className={clsx('flex items-start gap-2 px-3 py-2 text-xs', issue.severity === 'error' && 'bg-semantic-error-bg/40')}
              data-severity={issue.severity}
              data-code={issue.code}
            >
              {ICONS[issue.severity]}
              <div className="min-w-0">
                {place && <span className="mr-1.5 font-medium text-content-primary">{place}:</span>}
                <span className="text-content-secondary">{issueText(t, issue)}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
