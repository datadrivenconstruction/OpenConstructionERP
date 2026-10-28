// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One application, opened in place: where it stands with the authority, the
// decision clock with every stop and extension, and the decision once there
// is one. The next step is the one primary button.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Clock3, Gavel, Pencil, TimerReset } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';

import { completeRegister, type ApplicationTarget, type CanFlag, type ConditionRow, type Decision, type Permit } from './api';
import { CorrectDecisionDialog } from './CorrectDecisionDialog';
import { ApplicationDialog, ClockEventDialog, TransitionDialog } from './ApplicationDialogs';
import { DecisionDialog } from './DecisionDialog';
import { refusalText, useApplicationDetail, usePermitAction } from './hooks';
import {
  APPLICATION_KIND,
  APPLICATION_STATE,
  APPLICATION_STEP,
  CLOCK_EVENT,
  CLOCK_REASON,
  OUTCOME,
  errorText,
  periodText,
  vocab,
  type LabelContext,
  type TFn,
} from './labels';
import { APPLICATION_TONE, Fact, GatedButton, MoreActions, OUTCOME_TONE, PanelHeader, Refusal, RefusedActions, ToneBadge, dateText } from './PermitBits';
import { applicationSteps, clockEventKinds, gate, isDecidable, isOpenApplication } from './rules';

export interface ApplicationPanelProps {
  projectId: string;
  applicationId: string;
  /** What the application is for, shown above its own heading. */
  requirementName: string;
  permits: Permit[];
  conditions: ConditionRow[];
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  /** The roadmap asks for an internal release before an application is filed. */
  internalReview: boolean;
  onBack: () => void;
}

export function ApplicationPanel({
  projectId,
  applicationId,
  requirementName,
  permits,
  conditions,
  labels,
  personName,
  internalReview,
  onBack,
}: ApplicationPanelProps) {
  const { t } = useTranslation();
  const detailQ = useApplicationDetail(projectId, applicationId);
  const [target, setTarget] = useState<ApplicationTarget | null>(null);
  const [dialog, setDialog] = useState<'edit' | 'clock' | 'decision' | null>(null);
  const complete = usePermitAction(projectId, (decisionId: string) => completeRegister(projectId, decisionId));
  const [correcting, setCorrecting] = useState<Decision | null>(null);
  const back = t('permits.ui.back_to_permit', { defaultValue: 'Back to the permit' });

  if (detailQ.isLoading) return <SkeletonTable rows={4} columns={4} />;
  if (detailQ.isError || !detailQ.data) {
    return (
      <div className="space-y-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          {back}
        </Button>
        <ErrorState
          title={t('permits.ui.application.load_failed', { defaultValue: 'The application could not be loaded' })}
          hint={refusalText(t as TFn, detailQ.error)}
          onRetry={() => detailQ.refetch()}
        />
      </div>
    );
  }

  const a = detailQ.data;
  const clock = a.clock;
  const open = isOpenApplication(a);
  const decidable = isDecidable(a);
  // One primary action: the decision once the application is with the authority, the next step before that.
  const { steps, primary: primaryStep } = applicationSteps(a, internalReview);
  const canWithdraw = a.allowed_targets.includes('withdrawn');
  // A menu entry the server refuses for now stays visible, greyed, with the reason under it.
  const refusedItem = (flag: CanFlag | undefined) =>
    flag?.allowed === false ? { disabled: true, reason: flag.reason ? errorText(t as TFn, flag.reason, null) : undefined } : {};
  const clockKinds = open ? clockEventKinds(clock) : [];
  const stepLabel = (step: ApplicationTarget) =>
    step === 'preparing' && a.state === 'internal_review'
      ? t('permits.ui.app_step.back_to_preparing', { defaultValue: 'Return to preparation' })
      : vocab(t, APPLICATION_STEP, step);

  return (
    <div className="space-y-5" data-testid="application-panel">
      <PanelHeader
        title={t('permits.ui.application.heading', {
          defaultValue: '{{kind}}, attempt {{attempt}}',
          kind: vocab(t, APPLICATION_KIND, a.kind),
          attempt: a.attempt,
        })}
        subtitle={requirementName}
        badge={
          <ToneBadge tone={APPLICATION_TONE[a.state]} testId="application-state">
            {vocab(t, APPLICATION_STATE, a.state)}
          </ToneBadge>
        }
        onBack={onBack}
        backLabel={back}
        actions={
          <>
            {decidable && (
              <GatedButton gate={gate(a.can?.decide, true)} size="sm" icon={<Gavel size={14} />} onClick={() => setDialog('decision')} data-testid="application-decide">
                {t('permits.ui.decision.submit', { defaultValue: 'Record decision' })}
              </GatedButton>
            )}
            {primaryStep && (
              <GatedButton
                gate={gate(a.can?.transition?.[primaryStep], true)}
                size="sm"
                onClick={() => setTarget(primaryStep)}
                data-testid={`application-step-${primaryStep}`}
              >
                {stepLabel(primaryStep)}
              </GatedButton>
            )}
            <MoreActions
              testId="application-more"
              items={[
                ...steps
                  .filter((step) => step !== primaryStep)
                  .map((step) => ({
                    id: step,
                    label: stepLabel(step),
                    onClick: () => setTarget(step),
                    testId: `application-step-${step}`,
                    ...refusedItem(a.can?.transition?.[step]),
                  })),
                {
                  id: 'edit',
                  label: t('permits.ui.application.edit', { defaultValue: 'Edit the application details' }),
                  onClick: () => setDialog('edit'),
                  testId: 'application-edit',
                  ...refusedItem(a.can?.edit),
                },
                ...(canWithdraw
                  ? [
                      {
                        id: 'withdrawn',
                        label: vocab(t, APPLICATION_STEP, 'withdrawn'),
                        onClick: () => setTarget('withdrawn'),
                        testId: 'application-step-withdrawn',
                        ...refusedItem(a.can?.transition?.withdrawn),
                      },
                    ]
                  : []),
              ]}
            />
          </>
        }
      />

      <RefusedActions
        items={[
          decidable && [t('permits.ui.decision.submit', { defaultValue: 'Record decision' }), gate(a.can?.decide, true)],
          !!primaryStep && [stepLabel(primaryStep), gate(a.can?.transition?.[primaryStep], true)],
          clockKinds.length > 0 && [t('permits.ui.clock.title', { defaultValue: 'Decision period' }), gate(a.can?.clock, true)],
        ]}
      />
      {clock.deemed_proposal && (
        <p
          role="status"
          data-testid="deemed-proposal"
          className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm text-content-primary"
        >
          {t('permits.ui.clock.deemed_proposal', {
            defaultValue:
              'The decision period ran out without an answer. The law treats that as approval, but it only takes effect here once you record it as a decision.',
          })}
          {clock.deemed_requires_notice && (
            <>
              {' '}
              {t('permits.ui.clock.deemed_needs_notice', { defaultValue: 'For this permit type you need the confirming notice of the authority.' })}
            </>
          )}
        </p>
      )}

      <dl className="grid gap-4 rounded-lg border border-border bg-surface-elevated shadow-sm p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label={t('permits.ui.application.authority', { defaultValue: 'Authority' })}>{a.authority_name || '-'}</Fact>
        <Fact label={t('permits.ui.application.reference', { defaultValue: 'Authority reference' })}>{a.authority_reference || '-'}</Fact>
        <Fact label={t('permits.ui.application.submitted', { defaultValue: 'Submitted' })}>{dateText(a.submitted_at)}</Fact>
        <Fact label={t('permits.ui.application.received', { defaultValue: 'Received by the authority' })}>{dateText(a.received_at)}</Fact>
        <Fact label={t('permits.ui.application.validated', { defaultValue: 'Accepted as complete' })}>{dateText(a.validated_at)}</Fact>
        {a.appeal_note && <Fact label={t('permits.ui.application.appeal_note', { defaultValue: 'Appeal note' })}>{a.appeal_note}</Fact>}
      </dl>

      <section className="space-y-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-4" data-testid="clock-card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Clock3 size={16} aria-hidden />
            {t('permits.ui.clock.title', { defaultValue: 'Decision period' })}
          </h3>
          {clockKinds.length > 0 && (
            <GatedButton gate={gate(a.can?.clock, true)} size="sm" variant="secondary" icon={<TimerReset size={14} />} onClick={() => setDialog('clock')} data-testid="clock-record">
              {clock.stopped_now
                ? t('permits.ui.clock.record_resume', { defaultValue: 'Record that the period runs again' })
                : t('permits.ui.clock.record', { defaultValue: 'Record a stop or extension' })}
            </GatedButton>
          )}
        </div>
        {clock.stopped_now && (
          <p role="status" className="text-sm font-medium text-semantic-warning" data-testid="clock-stopped">
            {t('permits.ui.clock.stopped_now', { defaultValue: 'The period is stopped. It runs again once the authority has what it asked for.' })}
          </p>
        )}
        {!clock.forecast && clock.reason && (
          <p className="text-sm text-content-secondary" data-testid="clock-reason">
            {vocab(t, CLOCK_REASON, clock.reason)}
          </p>
        )}
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label={t('permits.ui.clock.statutory', { defaultValue: 'Period set by law' })}>{periodText(t as TFn, clock.period, clock.unit) || '-'}</Fact>
          <Fact label={t('permits.ui.clock.start', { defaultValue: 'Counted from' })}>{dateText(clock.start)}</Fact>
          <Fact label={t('permits.ui.clock.base_due', { defaultValue: 'Due without stops' })}>{dateText(clock.base_due)}</Fact>
          <Fact label={t('permits.ui.clock.forecast', { defaultValue: 'Decision expected' })} testId="clock-forecast">
            {dateText(clock.forecast)}
            {clock.estimate && clock.forecast && (
              <span className="block text-xs text-content-tertiary">{t('permits.ui.roadmap.estimate', { defaultValue: 'estimate' })}</span>
            )}
          </Fact>
          {clock.stopped_days > 0 && (
            <Fact label={t('permits.ui.clock.stopped_days', { defaultValue: 'Days stopped so far' })}>{clock.stopped_days}</Fact>
          )}
        </dl>
        {a.clock_events.length > 0 && (
          <ul className="space-y-1 border-t border-border-light pt-3 text-sm" data-testid="clock-events">
            {a.clock_events.map((e) => (
              <li key={e.id} className="flex flex-wrap gap-x-3 text-content-secondary">
                <span className="w-24 shrink-0 text-content-tertiary">{dateText(e.at)}</span>
                <span className="font-medium text-content-primary">{vocab(t, CLOCK_EVENT, e.kind)}</span>
                {e.period && e.unit && <span>{periodText(t as TFn, e.period, e.unit)}</span>}
                {e.reason && <span>{e.reason}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-content-primary">{t('permits.ui.decision.heading', { defaultValue: 'Decision' })}</h3>
        {complete.error && <Refusal>{complete.error}</Refusal>}
        {a.decisions.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-tertiary" data-testid="decision-empty">
            {decidable
              ? t('permits.ui.decision.none_decidable', {
                  defaultValue: 'No decision yet. Record it here as soon as the notice of the authority arrives.',
                })
              : t('permits.ui.decision.none', { defaultValue: 'No decision yet. A decision is recorded once the application is submitted.' })}
          </p>
        ) : (
          <ul className="space-y-1.5" data-testid="decision-list">
            {a.decisions.map((d) => {
              // A corrected revision stays for the record; only the newest one can be corrected again.
              const replaced = a.decisions.some((x) => x.supersedes_id === d.id);
              return (
              <li key={d.id} className={`space-y-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-3 text-sm ${replaced ? 'opacity-60' : ''}`} data-testid="decision-entry">
                <div className="flex flex-wrap items-center gap-3">
                  <ToneBadge tone={OUTCOME_TONE[d.outcome]}>{vocab(t, OUTCOME, d.outcome)}</ToneBadge>
                  <span className="text-content-secondary">{dateText(d.decision_date)}</span>
                  {d.reference && <span className="text-content-secondary">{d.reference}</span>}
                  {replaced && (
                    <span className="text-xs text-content-tertiary" data-testid="decision-replaced">
                      {t('permits.ui.decision.replaced', { defaultValue: 'Replaced by a correction' })}
                    </span>
                  )}
                  {d.revision > 1 && !replaced && (
                    <span className="text-xs text-content-tertiary">
                      {t('permits.ui.decision.revision', { defaultValue: 'Corrected, revision {{n}}', n: d.revision })}
                    </span>
                  )}
                  {d.decided_by && (
                    <span className="text-xs text-content-tertiary">
                      {t('permits.ui.decision.recorded_by', {
                        defaultValue: 'Recorded by {{name}}',
                        name: personName(d.decided_by) ?? t('permits.ui.unknown_person', { defaultValue: 'Project member' }),
                      })}
                    </span>
                  )}
                  {d.appeal_deadline && (
                    <span className="ml-auto text-xs text-content-tertiary">
                      {t('permits.ui.decision.appeal_until', { defaultValue: 'Appeal possible until {{date}}', date: dateText(d.appeal_deadline) })}
                    </span>
                  )}
                </div>
                {d.scope_note && <p className="text-content-secondary">{d.scope_note}</p>}
                {!replaced && (
                  <GatedButton gate={gate(d.can?.correct, true)} size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setCorrecting(d)} data-testid="decision-correct">
                    {t('permits.ui.correct.open', { defaultValue: 'Correct a date or reference' })}
                  </GatedButton>
                )}
                <RefusedActions
                  testId="decision-refused"
                  items={[
                    !replaced && [t('permits.ui.correct.open', { defaultValue: 'Correct a date or reference' }), gate(d.can?.correct, true)],
                    d.conditions_pending && [
                      t('permits.ui.decision.complete_register', { defaultValue: 'All conditions are entered' }),
                      gate(d.can?.complete_register, true),
                    ],
                  ]}
                />
                {d.conditions_pending && (
                  <div className="flex flex-wrap items-center gap-3 rounded-md bg-semantic-warning-bg px-3 py-2" data-testid="conditions-pending">
                    <span className="text-content-primary">
                      {t('permits.ui.decision.pending_banner', {
                        defaultValue: 'The conditions of this decision are not all entered yet. Readiness stays blocked until they are.',
                      })}
                    </span>
                    <GatedButton gate={gate(d.can?.complete_register, true)} size="sm" variant="secondary" loading={complete.busy} onClick={() => complete.run(d.id)} data-testid="complete-register">
                      {t('permits.ui.decision.complete_register', { defaultValue: 'All conditions are entered' })}
                    </GatedButton>
                  </div>
                )}
              </li>
              );
            })}
          </ul>
        )}
      </section>

      <TransitionDialog open={target !== null} onClose={() => setTarget(null)} projectId={projectId} application={a} target={target} />
      <ApplicationDialog
        open={dialog === 'edit'}
        onClose={() => setDialog(null)}
        projectId={projectId}
        requirementId={a.requirement_id}
        application={a}
        canOpenNew={false}
        permits={permits}
        conditions={conditions}
        labels={labels}
      />
      <CorrectDecisionDialog open={correcting !== null} onClose={() => setCorrecting(null)} projectId={projectId} decision={correcting} />
      <ClockEventDialog open={dialog === 'clock'} onClose={() => setDialog(null)} projectId={projectId} applicationId={a.id} clock={clock} />
      <DecisionDialog
        open={dialog === 'decision'}
        onClose={() => setDialog(null)}
        projectId={projectId}
        application={a}
        conditions={conditions}
        personName={personName}
      />
    </div>
  );
}
