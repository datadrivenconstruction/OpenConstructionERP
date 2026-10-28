// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Recording what the authority decided. The outcome comes first, because it
// decides what else the record must carry: the conditions of a conditional
// grant, the scope of a partial one. A decision is recorded once and cannot
// be changed afterwards, so the dialog lists what is missing before it sends
// anything; the server repeats every check.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';

import {
  localToday,
  recordDecision,
  type ApplicationDetail,
  type ConditionRow,
  type DecisionInput,
  type DecisionResult,
  type Outcome,
} from './api';
import { ConditionFields, DocumentRevisionSelect } from './ConditionDialogs';
import { usePermitAction } from './hooks';
import { OUTCOME, OUTCOME_HINT, vocab } from './labels';
import { Field, FormDialog, fieldClass } from './PermitBits';
import {
  CONDITION_PROBLEM,
  DECISION_PROBLEM,
  carriesConditions,
  decisionProblems,
  emptyDecision,
  grantsPermit,
  newConditionDraft,
  toDecisionInput,
  type ConditionDraft,
  type DecisionDraft,
  type DecisionProblem,
} from './rules';

const OUTCOMES: Outcome[] = ['granted', 'granted_with_conditions', 'partially_granted', 'refused'];
const PROBLEM_TEXT = { ...CONDITION_PROBLEM, ...DECISION_PROBLEM };

export interface DecisionDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  application: ApplicationDetail;
  /** The project's conditions, to name the ones a discharge application listed. */
  conditions: ConditionRow[];
  personName: (userId: string | null | undefined) => string | null;
  onRecorded?: (result: DecisionResult) => void;
}

export function DecisionDialog({
  open,
  onClose,
  projectId,
  application,
  conditions,
  personName,
  onRecorded,
}: DecisionDialogProps) {
  const { t } = useTranslation();
  const today = localToday();
  const listed = application.kind === 'discharge_of_conditions' ? application.discharges_condition_ids : [];
  const varies = application.kind === 'variation' || application.kind === 'amendment_non_material';
  const [draft, setDraft] = useState<DecisionDraft>(() => emptyDecision(today));
  useEffect(() => {
    if (open) setDraft(emptyDecision(localToday(), application.authority_reference, listed));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, application.id]);

  const action = usePermitAction(
    projectId,
    (input: DecisionInput) => recordDecision(projectId, application.id, input),
    (result) => {
      onClose();
      onRecorded?.(result);
    },
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // The deemed outcome is offered only when the server proposes it: the period ran out undecided.
  const deemed = application.clock.deemed_proposal !== null;
  const outcomes: Outcome[] = deemed ? [...OUTCOMES, 'deemed_granted'] : OUTCOMES;
  const set = (patch: Partial<DecisionDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const patchCondition = (rowId: string, patch: Partial<ConditionDraft>) =>
    setDraft((d) => ({ ...d, conditions: d.conditions.map((c) => (c.rowId === rowId ? { ...c, ...patch } : c)) }));
  const problems = decisionProblems(draft, {
    today,
    deemedNeedsNotice: application.clock.deemed_requires_notice,
  }).map((p: DecisionProblem) => vocab(t, PROBLEM_TEXT, p));
  const granted = grantsPermit(draft.outcome);

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="decision-dialog"
      size="xl"
      title={t('permits.ui.decision.title', { defaultValue: 'Record the decision of the authority' })}
      subtitle={t('permits.ui.decision.subtitle', {
        defaultValue: 'Recorded once and kept as it is. A granted permit appears in the permit register with its conditions.',
      })}
      submitLabel={t('permits.ui.decision.submit', { defaultValue: 'Record decision' })}
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={() => action.run(toDecisionInput(draft, { listed, varies }))}
    >
      <fieldset>
        <legend className="mb-2 text-sm font-semibold text-content-primary">
          {t('permits.ui.decision.outcome', { defaultValue: 'What the authority decided' })}
        </legend>
        <div className="grid gap-2 sm:grid-cols-2" role="radiogroup">
          {outcomes.map((o) => (
            <label
              key={o}
              className={clsx(
                'flex cursor-pointer flex-col gap-1 rounded-lg border p-3 text-sm transition-colors',
                draft.outcome === o
                  ? o === 'refused'
                    ? 'border-semantic-error bg-semantic-error-bg'
                    : 'border-oe-blue bg-oe-blue-subtle'
                  : 'border-border-light hover:border-border',
              )}
            >
              <span className="flex items-center gap-2 font-medium text-content-primary">
                <input type="radio" name="decision-outcome" value={o} checked={draft.outcome === o} onChange={() => set({ outcome: o })} />
                {vocab(t, OUTCOME, o)}
              </span>
              <span className="text-xs text-content-secondary">{vocab(t, OUTCOME_HINT, o)}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-4">
        <Field label={t('permits.ui.decision.date', { defaultValue: 'Decision date' })} required>
          {(id) => (
            <input id={id} type="date" max={today} className={fieldClass} value={draft.decision_date} onChange={(e) => set({ decision_date: e.target.value })} />
          )}
        </Field>
        <Field
          label={t('permits.ui.decision.served', { defaultValue: 'Served on' })}
          hint={t('permits.ui.decision.served_hint', { defaultValue: 'The day the notice reached the applicant.' })}
        >
          {(id) => (
            <input id={id} type="date" max={localToday()} className={fieldClass} value={draft.served_date} onChange={(e) => set({ served_date: e.target.value })} />
          )}
        </Field>
        <Field label={t('permits.ui.decision.appeal_deadline', { defaultValue: 'Appeal possible until' })}>
          {(id) => (
            <input id={id} type="date" className={fieldClass} value={draft.appeal_deadline} onChange={(e) => set({ appeal_deadline: e.target.value })} />
          )}
        </Field>
        <Field label={t('permits.ui.decision.reference', { defaultValue: 'Notice reference' })}>
          {(id) => <input id={id} className={fieldClass} value={draft.reference} onChange={(e) => set({ reference: e.target.value })} />}
        </Field>
      </div>

      <Field
        label={t('permits.ui.decision.document', { defaultValue: 'The notice as a document' })}
        required={draft.outcome === 'deemed_granted' && application.clock.deemed_requires_notice}
      >
        {(id) => (
          <DocumentRevisionSelect
            id={id}
            projectId={projectId}
            value={draft.document_revision_id}
            onChange={(revisionId) => set({ document_revision_id: revisionId })}
            enabled={open}
          />
        )}
      </Field>

      {draft.outcome === 'partially_granted' && (
        <Field label={t('permits.ui.decision.scope', { defaultValue: 'What the permit covers' })} required>
          {(id) => <textarea id={id} rows={2} className={fieldClass} value={draft.scope_note} onChange={(e) => set({ scope_note: e.target.value })} />}
        </Field>
      )}

      {listed.length > 0 && granted && (
        <fieldset data-testid="decision-discharged">
          <legend className="mb-1 text-sm font-semibold text-content-primary">
            {t('permits.ui.decision.discharged', { defaultValue: 'Conditions the authority discharged' })}
          </legend>
          {listed.map((conditionId) => {
            const c = conditions.find((x) => x.id === conditionId);
            return (
              <label key={conditionId} className="flex items-start gap-2 py-0.5 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={draft.discharged.includes(conditionId)}
                  onChange={() =>
                    set({
                      discharged: draft.discharged.includes(conditionId)
                        ? draft.discharged.filter((x) => x !== conditionId)
                        : [...draft.discharged, conditionId],
                    })
                  }
                />
                <span>
                  <span className="font-medium">{c?.number}</span> {c?.text}
                </span>
              </label>
            );
          })}
        </fieldset>
      )}

      {varies && granted && (
        <Field
          label={t('permits.ui.decision.removed', { defaultValue: 'Conditions the new decision drops' })}
          hint={t('permits.ui.decision.removed_hint', {
            defaultValue: 'Their numbers, separated by commas. Every other condition of the old permit is carried over.',
          })}
        >
          {(id) => <input id={id} className={fieldClass} value={draft.removed_numbers} onChange={(e) => set({ removed_numbers: e.target.value })} />}
        </Field>
      )}

      {granted && listed.length === 0 && (
        <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
          <Field
            label={t('permits.ui.decision.security_amount', { defaultValue: 'Security required by the authority' })}
            hint={t('permits.ui.decision.security_hint', { defaultValue: 'Leave empty when the decision asks for none.' })}
          >
            {(id) => (
              <input
                id={id}
                inputMode="decimal"
                className={fieldClass}
                value={draft.security_amount}
                onChange={(e) => set({ security_amount: e.target.value })}
              />
            )}
          </Field>
          <Field label={t('permits.ui.decision.security_currency', { defaultValue: 'Currency' })}>
            {(id) => (
              <input
                id={id}
                maxLength={3}
                className={fieldClass}
                value={draft.security_currency}
                onChange={(e) => set({ security_currency: e.target.value })}
              />
            )}
          </Field>
        </div>
      )}

      {carriesConditions(draft.outcome) && listed.length === 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('permits.ui.decision.conditions', { defaultValue: 'Conditions of the decision' })}
            </h3>
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus size={14} />}
              data-testid="decision-add-condition"
              onClick={() => set({ conditions: [...draft.conditions, newConditionDraft(String(draft.conditions.length + 1))] })}
            >
              {t('permits.ui.decision.add_condition', { defaultValue: 'Add condition' })}
            </Button>
          </div>
          {draft.conditions.map((c, idx) => (
            <div key={c.rowId} data-testid="decision-condition" className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
              <div className="mb-2 flex justify-end">
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 size={14} />}
                  aria-label={t('permits.ui.decision.remove_condition', { defaultValue: 'Remove condition {{n}}', n: idx + 1 })}
                  onClick={() => set({ conditions: draft.conditions.filter((x) => x.rowId !== c.rowId) })}
                />
              </div>
              <ConditionFields
                projectId={projectId}
                draft={c}
                onChange={(patch) => patchCondition(c.rowId, patch)}
                personName={personName}
              />
            </div>
          ))}
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              className="mt-1"
              checked={draft.conditions_pending}
              onChange={(e) => set({ conditions_pending: e.target.checked })}
            />
            <span>
              {t('permits.ui.decision.conditions_pending', { defaultValue: 'More conditions follow, the register is not complete yet' })}
              <span className="block text-xs text-content-tertiary">
                {t('permits.ui.decision.conditions_pending_hint', {
                  defaultValue: 'Readiness stays blocked until the register is marked complete on the application.',
                })}
              </span>
            </span>
          </label>
        </div>
      )}
    </FormDialog>
  );
}
