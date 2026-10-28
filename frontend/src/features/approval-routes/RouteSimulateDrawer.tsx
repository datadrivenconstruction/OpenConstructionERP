// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RouteSimulateDrawer — dry-run panel for an approval route template.
//
// Surfaces the read-only simulator (POST /routes/{id}/simulate): before
// anyone routes real work through a template, an author can see how many
// approvals each step needs, whether a step can ever clear, the happy-path
// outcome (completed / rejected / stuck) and any design warnings. Especially
// useful for confirming an ISO 19650 preset behaves as expected. Read-only,
// no database is touched.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  PauseCircle,
  ShieldCheck,
} from 'lucide-react';

import { Badge, RecoveryCard, SideDrawer, Skeleton } from '@/shared/ui';
import { approvalRoutesKeys, simulateRoute } from './api';
import type {
  ApprovalRoute,
  RouteSimulation,
  SimulatedStep,
  SimulationOutcome,
  SimulationOutcomeKind,
} from './types';

export interface RouteSimulateDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Route to dry-run; pass ``null`` when the drawer is closed. */
  route: ApprovalRoute | null;
}

function outcomeVariant(
  kind: SimulationOutcomeKind,
): 'success' | 'error' | 'warning' {
  if (kind === 'completed') return 'success';
  if (kind === 'rejected') return 'error';
  return 'warning';
}

function OutcomeIcon({ kind }: { kind: SimulationOutcomeKind }) {
  if (kind === 'completed')
    return <CheckCircle2 size={16} className="text-semantic-success" />;
  if (kind === 'rejected')
    return <CircleSlash size={16} className="text-semantic-error" />;
  return <PauseCircle size={16} className="text-semantic-warning" />;
}

function OutcomeBlock({
  title,
  outcome,
}: {
  title: string;
  outcome: SimulationOutcome;
}) {
  const { t } = useTranslation();
  const label = t(`approvalRoutes.sim_outcome_${outcome.outcome}`, {
    defaultValue:
      outcome.outcome === 'completed'
        ? 'Reaches approved'
        : outcome.outcome === 'rejected'
          ? 'Rejected'
          : 'Stuck',
  });
  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {title}
        </h4>
        <Badge variant={outcomeVariant(outcome.outcome)} size="sm">
          <OutcomeIcon kind={outcome.outcome} />
          {label}
        </Badge>
      </div>
      {outcome.stopped_at_ordinal != null && (
        <p className="mt-1.5 text-xs text-content-secondary">
          {t('approvalRoutes.sim_stopped_at', {
            defaultValue: 'Stops at step {{n}}.',
            n: outcome.stopped_at_ordinal,
          })}
        </p>
      )}
      <ol className="mt-2 space-y-1">
        {outcome.trace.map((line, i) => (
          <li
            key={i}
            className="text-xs text-content-secondary leading-relaxed flex gap-1.5"
          >
            <span className="text-content-tertiary tabular-nums">{i + 1}.</span>
            <span>{line}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function StepRow({ step }: { step: SimulatedStep }) {
  const { t } = useTranslation();
  const who = step.approver_user_id
    ? t('approvalRoutes.sim_pinned_user', { defaultValue: 'Pinned user' })
    : (step.approver_role ??
      t('approvalRoutes.sim_an_approver', { defaultValue: 'An approver' }));
  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-content-primary">
          <ShieldCheck size={13} className="text-content-tertiary" />
          {t('approvalRoutes.sim_step_n', {
            defaultValue: 'Step {{n}}',
            n: step.ordinal,
          })}
          <span className="text-xs font-normal text-content-tertiary">
            · {who}
          </span>
        </span>
        <div className="flex items-center gap-1">
          <Badge variant="neutral" size="sm">
            {step.mode}
          </Badge>
          {step.needs_multiple_approvers && (
            <Badge variant="warning" size="sm">
              {t('approvalRoutes.sim_multi_approver', {
                defaultValue: 'Needs 2+',
              })}
            </Badge>
          )}
        </div>
      </div>
      <p className="mt-1.5 text-xs text-content-secondary">{step.note}</p>
      <p className="mt-1 text-2xs text-content-tertiary tabular-nums">
        {t('approvalRoutes.sim_min_approvals', {
          defaultValue: 'Minimum approvals to clear: {{n}}',
          n: step.min_approvals_to_clear,
        })}
      </p>
    </div>
  );
}

function SimulationBody({ sim }: { sim: RouteSimulation }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      {sim.warnings.length > 0 && (
        <div className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg/40 p-3">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold text-[#b45309]">
            <AlertTriangle size={13} />
            {t('approvalRoutes.sim_warnings_title', {
              defaultValue: 'Design warnings',
            })}
          </h4>
          <ul className="mt-1.5 space-y-1 list-disc pl-4">
            {sim.warnings.map((w, i) => (
              <li key={i} className="text-xs text-content-secondary">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      <OutcomeBlock
        title={t('approvalRoutes.sim_happy_path', {
          defaultValue: 'Happy path',
        })}
        outcome={sim.happy_path}
      />

      {sim.scenario && (
        <OutcomeBlock
          title={t('approvalRoutes.sim_scenario', {
            defaultValue: 'What-if scenario',
          })}
          outcome={sim.scenario}
        />
      )}

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('approvalRoutes.sim_per_step', {
            defaultValue: 'Per-step analysis ({{n}})',
            n: sim.step_count,
          })}
        </h4>
        <div className="space-y-2">
          {sim.steps.map((s) => (
            <StepRow key={s.ordinal} step={s} />
          ))}
        </div>
      </div>
    </div>
  );
}

export function RouteSimulateDrawer({
  open,
  onClose,
  route,
}: RouteSimulateDrawerProps) {
  const { t } = useTranslation();

  const simQuery = useQuery({
    queryKey: route ? approvalRoutesKeys.simulation(route.id) : ['sim', 'none'],
    // Happy-path-only dry run (empty decisions) — enough to confirm a
    // template reaches approved and to surface design warnings.
    queryFn: () => simulateRoute(route!.id),
    enabled: open && route !== null,
    staleTime: 30_000,
  });

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={t('approvalRoutes.sim_title', { defaultValue: 'Dry run' })}
      subtitle={route?.name}
    >
      <div className="p-4">
        <p className="mb-3 text-xs text-content-tertiary max-w-prose">
          {t('approvalRoutes.sim_intro', {
            defaultValue:
              'A read-only walk of this template before any real work is routed through it. It shows how many approvals each step needs, whether the route reaches approved, and any design warnings. Nothing is saved.',
          })}
        </p>
        {simQuery.isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : simQuery.isError ? (
          <RecoveryCard
            error={simQuery.error as Error}
            onRetry={() => simQuery.refetch()}
          />
        ) : simQuery.data ? (
          <SimulationBody sim={simQuery.data} />
        ) : null}
      </div>
    </SideDrawer>
  );
}
