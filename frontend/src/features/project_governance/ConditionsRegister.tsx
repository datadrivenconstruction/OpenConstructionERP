// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every condition the project's gate decisions carry, filterable by state.
// An owner clears a condition with evidence; a decider waives it, and a
// waiver is only accepted with a written reason. Who may do which is the
// server's answer on each condition. Overdue is the server's too: it reports
// a condition past its due date as overdue from the day after, whether or not
// anybody has escalated it yet.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { ClipboardCheck } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import { clearCondition, waiveCondition, type ConditionStatus, type GovernanceCondition } from './api';
import { canClearCondition, canWaiveCondition } from './access';
import { waiverProblem } from './decisionRules';
import { CONDITION_TONE, PersonChip, ReasonedButton, ToneBadge } from './GovernanceBits';
import { CONDITION_STATUS, SEVERITY, catalogueName, errorText, refusalText, vocab, type LabelContext } from './labels';

const FILTERS: Array<ConditionStatus | 'all'> = ['all', 'open', 'overdue', 'cleared', 'waived'];

export interface ConditionsRegisterProps {
  projectId: string;
  conditions: GovernanceCondition[];
  catalogueId: string;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onChanged: () => void;
}

type Action = { id: string; kind: 'clear' | 'waive' } | null;

export function ConditionsRegister({
  projectId,
  conditions,
  catalogueId,
  labels,
  personName,
  onChanged,
}: ConditionsRegisterProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [filter, setFilter] = useState<ConditionStatus | 'all'>('all');
  const [action, setAction] = useState<Action>(null);
  const [text, setText] = useState('');
  const [tried, setTried] = useState(false);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: conditions.length };
    for (const x of conditions) c[x.status] = (c[x.status] ?? 0) + 1;
    return c;
  }, [conditions]);
  const shown = filter === 'all' ? conditions : conditions.filter((c) => c.status === filter);

  const run = useMutation({
    mutationFn: (a: NonNullable<Action>) =>
      a.kind === 'clear' ? clearCondition(projectId, a.id, text.trim()) : waiveCondition(projectId, a.id, text.trim()),
    onSuccess: (_condition, done) => {
      // With a filter on, the row leaves the list; the toast says where it went.
      addToast({
        type: 'success',
        title:
          done.kind === 'clear'
            ? t('governance.project.conditions.cleared', { defaultValue: 'Condition cleared' })
            : t('governance.project.conditions.waived', { defaultValue: 'Condition waived' }),
      });
      setAction(null);
      setText('');
      setTried(false);
      onChanged();
    },
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });

  const start = (id: string, kind: 'clear' | 'waive') => {
    setAction({ id, kind });
    setText('');
    setTried(false);
  };
  const send = () => {
    if (!action) return;
    if (action.kind === 'waive' && waiverProblem(text)) {
      setTried(true);
      return;
    }
    run.mutate(action);
  };

  if (conditions.length === 0) {
    return (
      <EmptyState
        icon={<ClipboardCheck size={28} />}
        title={t('governance.project.conditions.empty_title', { defaultValue: 'No conditions yet' })}
        description={t('governance.project.conditions.empty_body', {
          defaultValue: 'Conditions appear here when a gate is decided as go with conditions. Each one gets an owner and a due date.',
        })}
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('governance.project.conditions.filter', { defaultValue: 'Filter conditions' })}>
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={filter === f}
            onClick={() => setFilter(f)}
            className={clsx(
              'rounded-full border px-3 py-1 text-xs',
              filter === f ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary',
            )}
          >
            {f === 'all' ? t('governance.project.conditions.all', { defaultValue: 'All' }) : vocab(t, CONDITION_STATUS, f)}{' '}
            <span className="text-content-tertiary">{counts[f] ?? 0}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-content-tertiary">
          {t('governance.project.conditions.none_in_filter', { defaultValue: 'No condition in this state.' })}
        </p>
      ) : (
        <ul className="space-y-2" data-testid="conditions-list">
          {shown.map((c) => {
            const clearV = canClearCondition(c);
            const waiveV = canWaiveCondition(c);
            const active = action?.id === c.id ? action : null;
            const showWaiverError = active?.kind === 'waive' && tried && !!waiverProblem(text);
            return (
              <li key={c.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="condition-entry">
                <div className="flex flex-wrap items-center gap-2">
                  <ToneBadge tone={CONDITION_TONE[c.status]}>{vocab(t, CONDITION_STATUS, c.status)}</ToneBadge>
                  <span className="text-xs text-content-tertiary">{vocab(t, SEVERITY, c.severity)}</span>
                  <span className="text-xs text-content-tertiary">
                    {catalogueName(labels, { kind: 'gate', code: c.gate_code, catalogueId })}
                    {c.area_code && <> / {catalogueName(labels, { kind: 'area', code: c.area_code, catalogueId })}</>}
                  </span>
                  <span className="ml-auto flex items-center gap-3">
                    <PersonChip
                      name={
                        c.owner_user_id
                          ? personName(c.owner_user_id) ?? t('governance.project.unknown_person', { defaultValue: 'Project member' })
                          : null
                      }
                    />
                    {c.due_date && (
                      <span className={clsx('text-xs', c.status === 'overdue' ? 'font-medium text-semantic-error' : 'text-content-secondary')}>
                        {t('governance.project.conditions.due', { defaultValue: 'Due {{date}}', date: fmtDate(c.due_date) })}
                      </span>
                    )}
                  </span>
                </div>
                <p className="mt-1 text-sm text-content-primary">{c.text}</p>
                {c.evidence && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {t('governance.project.conditions.evidence_label', { defaultValue: 'Evidence:' })} {c.evidence}
                  </p>
                )}
                {c.waiver_rationale && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {t('governance.project.conditions.waiver_label', { defaultValue: 'Waived because:' })} {c.waiver_rationale}
                  </p>
                )}

                {(c.status === 'open' || c.status === 'overdue') && !active && (
                  <div className="mt-2 flex flex-wrap items-start gap-3">
                    <ReasonedButton size="sm" variant="secondary" verdict={clearV} onClick={() => start(c.id, 'clear')}>
                      {t('governance.project.conditions.clear', { defaultValue: 'Clear with evidence' })}
                    </ReasonedButton>
                    <ReasonedButton size="sm" variant="ghost" verdict={waiveV} onClick={() => start(c.id, 'waive')}>
                      {t('governance.project.conditions.waive', { defaultValue: 'Waive' })}
                    </ReasonedButton>
                  </div>
                )}
                {active && (
                  <div className="mt-2 space-y-2 rounded-md bg-surface-secondary p-2">
                    <textarea
                      rows={2}
                      data-testid="condition-action-text"
                      className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
                      aria-label={
                        active.kind === 'clear'
                          ? t('governance.project.conditions.evidence_placeholder', { defaultValue: 'What shows the condition is met' })
                          : t('governance.project.conditions.waiver_placeholder', { defaultValue: 'Why the condition is waived (required)' })
                      }
                      placeholder={
                        active.kind === 'clear'
                          ? t('governance.project.conditions.evidence_placeholder', { defaultValue: 'What shows the condition is met' })
                          : t('governance.project.conditions.waiver_placeholder', { defaultValue: 'Why the condition is waived (required)' })
                      }
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                    />
                    {showWaiverError && (
                      <p className="text-xs text-semantic-error" role="alert" data-testid="waiver-error">
                        {errorText(t, 'waiver_needs_rationale')}
                      </p>
                    )}
                    <div className="flex gap-2">
                      <Button size="sm" loading={run.isPending} onClick={send} data-testid="condition-action-send">
                        {active.kind === 'clear'
                          ? t('governance.project.conditions.clear_send', { defaultValue: 'Clear condition' })
                          : t('governance.project.conditions.waive_send', { defaultValue: 'Waive condition' })}
                      </Button>
                      <Button size="sm" variant="ghost" disabled={run.isPending} onClick={() => setAction(null)}>
                        {t('governance.project.cancel', { defaultValue: 'Cancel' })}
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
