// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Correct the facts of a recorded decision: a date, the reference, the scope
// note, the notice. The server keeps the old revision and writes a new one.
// What the authority decided cannot be changed this way.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { correctDecision, localToday, type Decision, type DecisionCorrection } from './api';
import { DocumentRevisionSelect } from './ConditionDialogs';
import { usePermitAction } from './hooks';
import { Field, FormDialog, fieldClass } from './PermitBits';
import { changedOnly } from './rules';

interface Draft {
  decision_date: string;
  served_date: string;
  reference: string;
  scope_note: string;
  appeal_deadline: string;
  document_revision_id: string;
}

function draftOf(d: Decision | null): Draft {
  return {
    decision_date: d?.decision_date ?? '',
    served_date: d?.served_date ?? '',
    reference: d?.reference ?? '',
    scope_note: d?.scope_note ?? '',
    appeal_deadline: d?.appeal_deadline ?? '',
    document_revision_id: d?.document_revision_id ?? '',
  };
}

/** The corrected fields only, with an emptied optional date sent as null. */
export function toCorrection(decision: Decision, draft: Draft, reason: string): DecisionCorrection {
  const next = {
    decision_date: draft.decision_date,
    served_date: draft.served_date || null,
    reference: draft.reference.trim(),
    scope_note: draft.scope_note.trim(),
    appeal_deadline: draft.appeal_deadline || null,
    document_revision_id: draft.document_revision_id || null,
  };
  return { ...changedOnly(decision, next), reason: reason.trim() };
}

export interface CorrectDecisionDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  decision: Decision | null;
}

export function CorrectDecisionDialog({ open, onClose, projectId, decision }: CorrectDecisionDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Draft>(() => draftOf(decision));
  const [reason, setReason] = useState('');
  useEffect(() => {
    if (!open) return;
    setDraft(draftOf(decision));
    setReason('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, decision?.id]);

  const body = decision ? toCorrection(decision, draft, reason) : null;
  const action = usePermitAction(projectId, () => correctDecision(projectId, decision!.id, body!), onClose);
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const today = localToday();
  const problems: string[] = [];
  if (body && Object.keys(body).length === 1) {
    problems.push(t('permits.ui.correct.problem_nothing', { defaultValue: 'Nothing is changed yet.' }));
  }
  if (!draft.decision_date) {
    problems.push(t('permits.ui.problem.date_required', { defaultValue: 'Enter the date of the decision.' }));
  } else if (draft.decision_date > today) {
    problems.push(t('permits.ui.problem.date_in_future', { defaultValue: 'The decision date cannot be in the future.' }));
  }
  if (!reason.trim()) {
    problems.push(t('permits.ui.correct.problem_reason', { defaultValue: 'Say why the decision is corrected.' }));
  }
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="correct-decision-dialog"
      title={t('permits.ui.correct.title', { defaultValue: 'Correct the recorded decision' })}
      subtitle={t('permits.ui.correct.subtitle', {
        defaultValue:
          'For a mistyped date, reference or note. The earlier entry stays visible. What the authority decided cannot be changed here.',
      })}
      submitLabel={t('permits.ui.correct.submit', { defaultValue: 'Save correction' })}
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={() => action.run(undefined)}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label={t('permits.ui.decision.date', { defaultValue: 'Decision date' })} required>
          {(id) => (
            <input id={id} type="date" max={today} className={fieldClass} value={draft.decision_date} onChange={(e) => set({ decision_date: e.target.value })} />
          )}
        </Field>
        <Field label={t('permits.ui.decision.served', { defaultValue: 'Served on' })}>
          {(id) => (
            <input id={id} type="date" max={today} className={fieldClass} value={draft.served_date} onChange={(e) => set({ served_date: e.target.value })} />
          )}
        </Field>
        <Field label={t('permits.ui.decision.appeal_deadline', { defaultValue: 'Appeal possible until' })}>
          {(id) => (
            <input id={id} type="date" className={fieldClass} value={draft.appeal_deadline} onChange={(e) => set({ appeal_deadline: e.target.value })} />
          )}
        </Field>
      </div>
      <Field label={t('permits.ui.decision.reference', { defaultValue: 'Notice reference' })}>
        {(id) => <input id={id} className={fieldClass} value={draft.reference} onChange={(e) => set({ reference: e.target.value })} />}
      </Field>
      <Field label={t('permits.ui.decision.scope', { defaultValue: 'What the permit covers' })}>
        {(id) => <textarea id={id} rows={2} className={fieldClass} value={draft.scope_note} onChange={(e) => set({ scope_note: e.target.value })} />}
      </Field>
      <Field label={t('permits.ui.decision.document', { defaultValue: 'The notice as a document' })}>
        {(id) => (
          <DocumentRevisionSelect
            id={id}
            projectId={projectId}
            value={draft.document_revision_id}
            onChange={(v) => set({ document_revision_id: v })}
            enabled={open}
          />
        )}
      </Field>
      <Field label={t('permits.ui.correct.reason', { defaultValue: 'Why it is corrected' })} required>
        {(id) => (
          <textarea id={id} rows={2} className={fieldClass} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="correct-reason" />
        )}
      </Field>
    </FormDialog>
  );
}
