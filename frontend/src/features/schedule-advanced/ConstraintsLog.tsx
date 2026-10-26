// Constraints log​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Every constraint of a master schedule, open first, with the record (RFI,
 * submittal, purchase order, goods receipt) whose closing clears it. A
 * constraint past its target date and not yet cleared is highlighted.
 */
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Badge, Card, Skeleton } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConstraintsLog, type LpsConstraintRow } from './api';
import { constraintStatusLabel, constraintTypeLabel } from './labels';

const LINK_TYPE_EN: Record<string, string> = {
  rfi: 'RFI',
  submittal: 'Submittal',
  purchase_order: 'Purchase order',
  goods_receipt: 'Goods receipt',
};

export function linkedTypeLabel(t: (k: string, o?: Record<string, unknown>) => string, type: string): string {
  return t(`schedule_advanced.linked_type.${type}`, { defaultValue: LINK_TYPE_EN[type] ?? type });
}

export function isOverdue(row: LpsConstraintRow, today: string): boolean {
  return (
    !!row.target_clear_date &&
    row.target_clear_date < today &&
    row.status !== 'cleared' &&
    row.status !== 'cannot_clear'
  );
}

export function ConstraintsLogTable({ rows, today }: { rows: LpsConstraintRow[]; today: string }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 text-left">{t('common.description', { defaultValue: 'Description' })}</th>
            <th className="px-3 py-2 text-left">{t('schedule_advanced.type', { defaultValue: 'Type' })}</th>
            <th className="px-3 py-2 text-left">{t('schedule_advanced.log_owner', { defaultValue: 'Owner' })}</th>
            <th className="px-3 py-2 text-left">{t('schedule_advanced.log_due', { defaultValue: 'Due date' })}</th>
            <th className="px-3 py-2 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
            <th className="px-3 py-2 text-left">{t('schedule_advanced.log_linked', { defaultValue: 'Linked record' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const overdue = isOverdue(r, today);
            return (
              <tr
                key={r.id}
                data-testid="constraints-log-row"
                data-overdue={overdue ? 'true' : 'false'}
                className={clsx('border-t border-border-light', overdue && 'bg-semantic-error-bg/40')}
              >
                <td className="px-3 py-2">
                  <p className="text-content-primary">{r.description || '-'}</p>
                  {r.task_name && <p className="text-2xs text-content-tertiary">{r.task_name}</p>}
                </td>
                <td className="px-3 py-2 text-xs">{constraintTypeLabel(t, r.constraint_type)}</td>
                <td className="px-3 py-2 text-xs text-content-secondary">
                  {r.owner_user_id ? r.owner_user_id.slice(0, 8) : '-'}
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.target_clear_date ? <DateDisplay value={r.target_clear_date} /> : '-'}
                  {overdue && (
                    <Badge variant="error" size="sm" className="ml-1">
                      {t('schedule_advanced.log_overdue', { defaultValue: 'Overdue' })}
                    </Badge>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Badge variant={r.status === 'cleared' ? 'success' : 'warning'} dot>
                    {constraintStatusLabel(t, r.status)}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.linked_type ? (
                    <span>
                      {linkedTypeLabel(t, r.linked_type)}
                      {r.linked_label ? `: ${r.linked_label}` : ''}
                      {r.linked_status ? ` (${r.linked_status})` : ''}
                    </span>
                  ) : (
                    '-'
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

export function ConstraintsLog({ masterId }: { masterId: string }) {
  const { t } = useTranslation();
  const q = useConstraintsLog(masterId);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <Card padding="none">
      <h3 className="px-4 pt-4 pb-2 text-sm font-semibold text-content-primary">
        {t('schedule_advanced.log_title', { defaultValue: 'Constraints log' })}
      </h3>
      {q.isLoading ? (
        <div className="p-4">
          <Skeleton height={64} />
        </div>
      ) : q.isError ? (
        <p className="px-4 pb-4 text-xs text-content-tertiary">
          {t('schedule_advanced.log_error', { defaultValue: 'The constraints log could not be loaded.' })}
        </p>
      ) : (q.data ?? []).length === 0 ? (
        <p className="px-4 pb-4 text-xs text-content-tertiary">
          {t('schedule_advanced.log_empty', { defaultValue: 'No constraints have been logged for this schedule.' })}
        </p>
      ) : (
        <ConstraintsLogTable rows={q.data ?? []} today={today} />
      )}
    </Card>
  );
}
