// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "What do I pay, and when": the instalments of each contract the builder
// chose to show the client, with what is paid and what is still to pay.
//
// An instalment that waits for a stage of the work falls due when that stage
// is done, so its date moves with the schedule. The card says so plainly when
// it has moved and shows the date the contract first named, because a client
// who budgeted for March and is now asked in May should see why.
//
// Everything that is a judgement comes from the server: the status (overdue
// included), how far the date moved and how many days are left. The card only
// formats. Money arrives as decimal strings and goes through MoneyDisplay, so
// a yen amount has no decimals and a dinar amount has three.
//
// Like UpcomingMilestones it hides itself when there is nothing to show.

import { useQueries, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertCircle, ArrowRight, Wallet } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { PaymentPlanStatusBadge } from '@/shared/ui/PaymentPlanStatusBadge';
import { fmtPercent } from '@/shared/lib/formatters';
import {
  listMyProjects,
  listProjectPaymentPlans,
  type PortalPaymentPlan,
  type PortalPaymentPlanLine,
} from './api';

export function PaymentPlanCard() {
  const { t } = useTranslation();

  const projectsQ = useQuery({
    queryKey: ['portal-home', 'projects'],
    queryFn: () => listMyProjects(),
    staleTime: 60_000,
  });
  const projects = projectsQ.data ?? [];

  const planQs = useQueries({
    queries: projects.map((p) => ({
      queryKey: ['portal-home', 'payment-plan', p.id],
      queryFn: () => listProjectPaymentPlans(p.id),
      staleTime: 60_000,
    })),
  });

  const failed = planQs.filter((q) => q.isError);
  const groups = projects
    .map((p, i) => ({ project: p, plans: planQs[i]?.data?.items ?? [] }))
    .filter((g) => g.plans.length > 0);

  if (groups.length === 0 && failed.length === 0) return null;
  const showProjectNames = projects.length > 1;

  return (
    <Card padding="none" className="w-full">
      <div className="border-b border-border-light px-4 py-3">
        <div className="flex items-center gap-2">
          <Wallet size={16} className="text-oe-blue" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('homeportal.plan_title', { defaultValue: 'Your payment plan' })}
          </h2>
        </div>
        <p className="mt-1 text-xs text-content-secondary">
          {t('homeportal.plan_subtitle', {
            defaultValue:
              'What you pay and when. Instalments tied to a stage of the work fall due when that stage is done, so their dates move with the work.',
          })}
        </p>
      </div>

      {failed.length > 0 && (
        <div role="alert" className="flex items-center justify-between gap-3 px-4 py-3">
          <p className="flex items-center gap-2 text-sm text-semantic-error">
            <AlertCircle size={14} />
            {t('homeportal.plan_error', {
              defaultValue: 'Your payment plan could not be loaded.',
            })}
          </p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              for (const q of failed) void q.refetch();
            }}
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      )}

      <div className="divide-y divide-border-light">
        {groups.map(({ project, plans }) => (
          <section key={project.id} className="px-4 py-3">
            {showProjectNames && (
              <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                {project.name}
              </p>
            )}
            <div className="space-y-4">
              {plans.map((plan) => (
                <PlanBlock key={plan.contract_id} plan={plan} showTitle={plans.length > 1} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </Card>
  );
}

function PlanBlock({ plan, showTitle }: { plan: PortalPaymentPlan; showTitle: boolean }) {
  const { t } = useTranslation();
  return (
    <div>
      {showTitle && (
        <p className="mb-2 text-sm font-medium text-content-primary">{plan.contract_title}</p>
      )}
      <dl className="grid grid-cols-3 gap-2 rounded-lg bg-surface-secondary px-3 py-2">
        <Total
          label={t('homeportal.plan_contract_total', { defaultValue: 'Contract total' })}
          amount={plan.contract_total}
          currency={plan.currency}
        />
        <Total
          label={t('homeportal.plan_paid', { defaultValue: 'Paid' })}
          amount={plan.paid_total}
          currency={plan.currency}
        />
        <Total
          label={t('homeportal.plan_outstanding', { defaultValue: 'Still to pay' })}
          amount={plan.outstanding_total}
          currency={plan.currency}
          strong
        />
      </dl>
      <ol className="mt-3 space-y-3">
        {plan.lines.map((line) => (
          <InstalmentRow key={line.id} line={line} currency={plan.currency} />
        ))}
      </ol>
    </div>
  );
}

function Total({
  label,
  amount,
  currency,
  strong = false,
}: {
  label: string;
  amount: string;
  currency: string;
  strong?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd
        className={
          strong
            ? 'text-sm font-semibold tabular-nums text-content-primary'
            : 'text-sm tabular-nums text-content-secondary'
        }
      >
        <MoneyDisplay amount={amount} currency={currency || undefined} />
      </dd>
    </div>
  );
}

function InstalmentRow({ line, currency }: { line: PortalPaymentPlanLine; currency: string }) {
  const { t } = useTranslation();
  const moved = line.days_moved ?? 0;

  return (
    <li className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-content-primary">{line.label}</p>
        {line.milestone_name && (
          <p className="flex items-center gap-1 text-xs text-content-secondary">
            <ArrowRight size={12} className="shrink-0 rtl:rotate-180" />
            <span className="truncate">
              {t('homeportal.plan_after_milestone', {
                milestone: line.milestone_name,
                defaultValue: 'When this is done: {{milestone}}',
              })}
            </span>
          </p>
        )}
        <p className="text-xs text-content-secondary">
          {line.forecast_due_date ? (
            <>
              <span>{t('homeportal.plan_due_label', { defaultValue: 'Due' })}</span>{' '}
              <DateDisplay value={line.forecast_due_date} />
            </>
          ) : (
            t('homeportal.plan_no_date', { defaultValue: 'Date not known yet' })
          )}
        </p>
        {moved !== 0 && (
          <p className="text-2xs text-content-tertiary">
            <span className="font-medium text-semantic-warning">
              {moved > 0
                ? t('homeportal.plan_moved_later', {
                    count: moved,
                    defaultValue_one: 'Moved {{count}} day later',
                    defaultValue_other: 'Moved {{count}} days later',
                  })
                : t('homeportal.plan_moved_earlier', {
                    count: -moved,
                    defaultValue_one: 'Moved {{count}} day earlier',
                    defaultValue_other: 'Moved {{count}} days earlier',
                  })}
            </span>
            {line.original_due_date && (
              <>
                {' · '}
                <span>
                  {t('homeportal.plan_originally_due', { defaultValue: 'Originally due' })}
                </span>{' '}
                <DateDisplay value={line.original_due_date} />
              </>
            )}
          </p>
        )}
        {line.status === 'overdue' && (line.days_overdue ?? 0) > 0 && (
          <p className="text-2xs font-medium text-semantic-error">
            {t('homeportal.plan_overdue_days', {
              count: line.days_overdue ?? 0,
              defaultValue_one: '{{count}} day overdue',
              defaultValue_other: '{{count}} days overdue',
            })}
          </p>
        )}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className="text-sm font-medium tabular-nums text-content-primary">
          <MoneyDisplay amount={line.amount} currency={currency || undefined} />
        </span>
        {line.percent_of_contract != null && (
          <span className="text-2xs tabular-nums text-content-tertiary">
            {t('homeportal.plan_percent_of_contract', {
              percent: fmtPercent(line.percent_of_contract),
              defaultValue: '{{percent}} of the contract',
            })}
          </span>
        )}
        <PaymentPlanStatusBadge status={line.status} size="sm" />
      </div>
    </li>
  );
}
