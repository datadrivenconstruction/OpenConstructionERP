// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every condition the project's permits carry, in the views a site team asks
// for: what must be done before start, before occupation, what runs for the
// whole build, what is overdue and what is mine.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BellRing, ClipboardCheck, UserPlus } from 'lucide-react';
import clsx from 'clsx';

import { fmtList } from '@/shared/lib/formatters';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { useToastStore } from '@/stores/useToastStore';

import { escalateConditions, type ConditionRow, type ConditionView, type RoadmapCan } from './api';
import { AssignDialog } from './ConditionDialogs';
import { usePermitAction } from './hooks';
import { CONDITION_KIND, CONDITION_STATE, CONDITION_VIEW, TOPIC, TRIGGER, vocab } from './labels';
import { CONDITION_TONE, GatedButton, PersonChip, Refusal, RefusedActions, ToneBadge, dateText } from './PermitBits';
import { gate, inConditionView } from './rules';

type View = ConditionView | 'all' | 'proposals';
const VIEWS: View[] = ['all', 'before_start', 'before_occupation', 'ongoing_hse', 'overdue', 'mine', 'proposals'];

export interface ConditionsRegisterProps {
  projectId: string;
  /** What the reader may do across the roadmap, as the server says. */
  can?: RoadmapCan;
  conditions: ConditionRow[];
  viewerId: string | null;
  personName: (userId: string | null | undefined) => string | null;
  onOpen: (conditionId: string) => void;
  onShowPermits: () => void;
}

export function ConditionsRegister({ projectId, can, conditions, viewerId, personName, onOpen, onShowPermits }: ConditionsRegisterProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [view, setView] = useState<View>('all');
  const [assigning, setAssigning] = useState(false);

  const counts = useMemo(() => {
    const out = {} as Record<View, number>;
    for (const v of VIEWS) out[v] = conditions.filter((c) => inConditionView(c, v, viewerId)).length;
    return out;
  }, [conditions, viewerId]);
  const shown = conditions.filter((c) => inConditionView(c, view, viewerId));
  // A note carries no duty, so it needs no owner; everything else does.
  const ownerless = conditions.filter(
    // The owner of a condition is fixed once it left `open`, so only open ones can still be assigned.
    (c) => c.confirmed && !c.owner_user_id && c.kind !== 'information' && c.state === 'open',
  );

  const escalate = usePermitAction(
    projectId,
    () => escalateConditions(projectId),
    (result) => {
      const waiting = result.unescalated?.length ?? 0;
      if (waiting > 0) {
        addToast({
          type: 'warning',
          title: t('permits.ui.conditions.escalate_unowned', {
            defaultValue: 'Not escalated, because the management area has no owner yet: {{n}}. Name an owner in project governance.',
            n: waiting,
          }),
        });
      }
      addToast({
        type: 'success',
        title: t('permits.ui.conditions.escalate_done', {
          defaultValue: 'Owners reminded: {{notified}}. Escalated to the area owner: {{escalated}}. Permits lapsed: {{lapsed}}.',
          notified: result.notified.length,
          escalated: result.escalated.length,
          lapsed: result.lapsed.length,
        }),
      });
    },
  );

  if (conditions.length === 0) {
    return (
      <EmptyState
        icon={<ClipboardCheck size={28} />}
        title={t('permits.ui.conditions.empty_title', { defaultValue: 'No permit condition yet' })}
        description={t('permits.ui.conditions.empty_body', {
          defaultValue:
            'Conditions come with a granted permit. Enter them when you record the decision, or add them to a permit in the permit register. Each one gets an owner and a due point.',
        })}
        action={{ label: t('permits.ui.conditions.go_permits', { defaultValue: 'Open the permit register' }), onClick: onShowPermits }}
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label={t('permits.ui.conditions.filter', { defaultValue: 'Show conditions' })}
        >
          {VIEWS.filter((v) => v !== 'proposals' || counts.proposals > 0).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => setView(v)}
              data-testid={`view-${v}`}
              className={clsx(
                'rounded-full border px-3 py-1 text-xs',
                view === v ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary',
                v === 'overdue' && counts.overdue > 0 && view !== v && 'border-semantic-error/50 text-semantic-error',
              )}
            >
              {t('permits.ui.conditions.view_count', { defaultValue: '{{view}} ({{n}})', view: vocab(t, CONDITION_VIEW, v), n: counts[v] })}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {ownerless.length > 0 && (
            <Button size="sm" icon={<UserPlus size={14} />} onClick={() => setAssigning(true)} data-testid="conditions-assign">
              {t('permits.ui.conditions.assign', { defaultValue: 'Assign owner to conditions without one' })}
            </Button>
          )}
          <GatedButton gate={gate(can?.escalate, true)}
            size="sm"
            variant="secondary"
            icon={<BellRing size={14} />}
            loading={escalate.busy}
            onClick={() => escalate.run(undefined)}
            title={t('permits.ui.conditions.escalate_hint', {
              defaultValue: 'Reminds the owners of overdue conditions, tells the area owner after the escalation period and marks unused permits as lapsed.',
            })}
            data-testid="conditions-escalate"
          >
            {t('permits.ui.conditions.escalate', { defaultValue: 'Send overdue reminders' })}
          </GatedButton>
        </div>
      </div>
      <RefusedActions items={[[t('permits.ui.conditions.escalate', { defaultValue: 'Send overdue reminders' }), gate(can?.escalate, true)]]} />
      {escalate.error && <Refusal>{escalate.error}</Refusal>}

      {shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-content-tertiary" data-testid="conditions-none">
          {t('permits.ui.conditions.none_in_view', { defaultValue: 'No condition in this view.' })}
        </p>
      ) : (
        <ul className="space-y-2" data-testid="conditions-list">
          {shown.map((c) => (
            <li key={c.id} data-testid="condition-entry">
              <button
                type="button"
                onClick={() => onOpen(c.id)}
                className="w-full rounded-lg border border-border-light p-3 text-left hover:border-border"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-content-primary">
                    {t('permits.ui.conditions.number', { defaultValue: 'No. {{number}}', number: c.number })}
                  </span>
                  {c.confirmed ? (
                    <ToneBadge tone={CONDITION_TONE[c.state]}>{vocab(t, CONDITION_STATE, c.state)}</ToneBadge>
                  ) : (
                    <ToneBadge tone="warning" testId="condition-proposal">
                      {t('permits.ui.conditions.proposal', { defaultValue: 'Proposal, to confirm' })}
                    </ToneBadge>
                  )}
                  {c.overdue && (
                    <ToneBadge tone="error" testId="condition-overdue">
                      {t('permits.ui.conditions.overdue', { defaultValue: 'Overdue' })}
                    </ToneBadge>
                  )}
                  <span className="text-xs text-content-tertiary">
                    {fmtList([vocab(t, CONDITION_KIND, c.kind), vocab(t, TRIGGER, c.trigger), vocab(t, TOPIC, c.topic)])}
                  </span>
                  <span className="ml-auto flex items-center gap-3">
                    {c.kind !== 'information' && (
                      <PersonChip
                        name={
                          c.owner_user_id
                            ? personName(c.owner_user_id) ?? t('permits.ui.unknown_person', { defaultValue: 'Project member' })
                            : null
                        }
                      />
                    )}
                    {c.due_date && (
                      <span className={clsx('text-xs', c.overdue ? 'font-medium text-semantic-error' : 'text-content-secondary')}>
                        {t('permits.ui.conditions.due', { defaultValue: 'Due {{date}}', date: dateText(c.due_date) })}
                      </span>
                    )}
                  </span>
                </span>
                <span className="mt-1 block text-sm text-content-primary">{c.text}</span>
                {c.permit_reference && (
                  <span className="mt-1 block text-xs text-content-tertiary">
                    {t('permits.ui.conditions.of_permit', { defaultValue: 'Permit {{reference}}', reference: c.permit_reference })}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      <AssignDialog open={assigning} onClose={() => setAssigning(false)} projectId={projectId} conditions={ownerless} />
    </div>
  );
}
