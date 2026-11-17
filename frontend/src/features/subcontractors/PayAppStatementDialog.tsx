// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The progress statement of one pay application: per line the scheduled value,
// what earlier approved applications billed, this period, the total to date,
// percent complete, retention and the balance to finish, with the summary
// (original sum, change orders, completed to date, retention held, previous
// certified, current due) and what the validation rules say about it.
//
// Everything is worked out on the server from the agreement's earlier approved
// applications; this component only shows it and offers the print view.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Printer } from 'lucide-react';

import { Button } from '@/shared/ui';
import { WideModal, WideModalSection } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { getPayAppStatement, type PayAppStatement, type PaymentApplication } from './api';
import { buildStatementHtml, formatAmount, formatPercent, printStatement, type StatementLabels } from './statementPrint';

export function useStatementLabels(): StatementLabels {
  const { t } = useTranslation();
  const k = (key: string, defaultValue: string) => t(`subcontractors.statement.${key}`, { defaultValue });
  return {
    title: k('title', 'Progress statement'),
    application: k('application', 'Application'),
    period: k('period', 'Period'),
    status: k('status', 'Status'),
    scheduled_value: k('scheduled_value', 'Scheduled value'),
    previous: k('previous', 'Previous applications'),
    this_period: k('this_period', 'This period'),
    total_completed: k('total_completed', 'Completed to date'),
    percent_complete: k('percent_complete', '% complete'),
    retention: k('retention', 'Retention'),
    balance_to_finish: k('balance_to_finish', 'Balance to finish'),
    original_contract_sum: k('original_contract_sum', 'Original contract sum'),
    change_orders: k('change_orders', 'Approved change orders'),
    contract_sum_to_date: k('contract_sum_to_date', 'Contract sum to date'),
    completed_to_date: k('completed_to_date', 'Total completed to date'),
    retention_held: k('retention_held', 'Retention held'),
    previous_certified: k('previous_certified', 'Previously certified'),
    current_due: k('current_due', 'Current payment due'),
    total: k('total', 'Total'),
  };
}

export function StatementBody({ statement, labels }: { statement: PayAppStatement; labels: StatementLabels }) {
  const cur = statement.currency || 'USD';
  const money = (v: string) => formatAmount(v, cur);
  const s = statement.summary;
  const summary: [string, string][] = [
    [labels.original_contract_sum, s.original_contract_sum],
    [labels.change_orders, s.change_orders],
    [labels.contract_sum_to_date, s.contract_sum_to_date],
    [labels.completed_to_date, s.completed_to_date],
    [labels.retention_held, s.retention_held],
    [labels.previous_certified, s.previous_certified],
    [labels.current_due, s.current_due],
  ];
  return (
    <div className="space-y-4" data-testid="statement-body">
      <div className="overflow-x-auto">
        <table className="w-full text-xs tabular-nums">
          <thead>
            <tr className="border-b border-border-light text-content-tertiary">
              <th className="py-1 pr-2 text-left font-medium" />
              {[
                labels.scheduled_value,
                labels.previous,
                labels.this_period,
                labels.total_completed,
                labels.percent_complete,
                labels.retention,
                labels.balance_to_finish,
              ].map((h) => (
                <th key={h} className="px-2 py-1 text-right font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {statement.lines.map((l) => (
              <tr key={l.work_package_id} className="border-b border-border-light" data-testid="statement-line">
                <td className="py-1 pr-2">{l.name}</td>
                <td className="px-2 text-right">{money(l.scheduled_value)}</td>
                <td className="px-2 text-right">{money(l.previous)}</td>
                <td className="px-2 text-right">{money(l.this_period)}</td>
                <td className="px-2 text-right">{money(l.total_completed)}</td>
                <td className="px-2 text-right">{formatPercent(l.percent_complete)}</td>
                <td className="px-2 text-right">{money(l.retention)}</td>
                <td className="px-2 text-right">{money(l.balance_to_finish)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="ml-auto max-w-sm space-y-1 text-sm" data-testid="statement-summary">
        {summary.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4">
            <dt className="text-content-secondary">{k}</dt>
            <dd className="tabular-nums">{money(v)}</dd>
          </div>
        ))}
      </dl>
      {statement.findings.some((f) => !f.passed) && (
        <ul className="space-y-1 text-xs" data-testid="statement-findings">
          {statement.findings
            .filter((f) => !f.passed)
            .map((f, i) => (
              <li key={`${f.rule_id}-${i}`} className={f.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning'}>
                {f.message}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

export function PayAppStatementDialog({ payment, onClose }: { payment: PaymentApplication; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const labels = useStatementLabels();
  const q = useQuery({
    queryKey: ['subcontractors', 'pay-app-statement', payment.id],
    queryFn: () => getPayAppStatement(payment.id),
  });

  const print = () => {
    if (!q.data) return;
    const html = buildStatementHtml(q.data, labels, payment.application_number, i18n.language);
    if (!printStatement(html)) {
      addToast({
        type: 'error',
        title: t('subcontractors.statement.print_blocked', {
          defaultValue: 'The browser blocked the print window. Allow pop-ups for this page and try again.',
        }),
      });
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      title={`${labels.title} ${payment.application_number}`}
      testId="statement-dialog"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          <Button variant="primary" icon={<Printer size={14} />} onClick={print} disabled={!q.data} data-testid="statement-print">
            {t('subcontractors.statement.print', { defaultValue: 'Print / PDF' })}
          </Button>
        </>
      }
    >
      <WideModalSection title={labels.title} columns={1}>
        {q.isLoading && <p className="text-sm text-content-tertiary">{t('common.loading', { defaultValue: 'Loading...' })}</p>}
        {q.isError && (
          <p className="text-sm text-semantic-error">
            {t('subcontractors.statement.load_failed', { defaultValue: 'The statement could not be loaded.' })}
          </p>
        )}
        {q.data && <StatementBody statement={q.data} labels={labels} />}
      </WideModalSection>
    </WideModal>
  );
}
