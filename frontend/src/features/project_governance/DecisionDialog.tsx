// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Recording a gate decision. The outcome comes first, because it decides what
// else the record must carry: a reason for anything but a plain go, at least
// one condition with an owner and a date for a go with conditions, a resume
// date for a hold. The submit button stays disabled and lists what is missing
// until the draft is complete; the server repeats every check.
//
// Which outcomes the caller may record is the server's answer, one flag per
// outcome: a final approver who already approved on the route may still record
// a go, but no longer a stop. A refused outcome stays visible and says why.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileWarning, Plus, Trash2 } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';

import type { ConditionInput, DecisionInput, GateDetail, Outcome, Violation } from './api';
import { outcomeVerdict } from './access';
import { ConditionFields } from './ConditionFields';
import {
  DECISION_PROBLEM,
  atRiskCandidates,
  conditionForDocument,
  coversDocument,
  decisionProblems,
  documentBlockers,
  emptyCondition,
  evidenceKey,
  evidenceToAcknowledge,
  letsGatePass,
  needsRationale,
  notApplicableAreas,
  dayAfter,
  toDecisionInput,
  type ConditionDraft,
  type DecisionDraft,
} from './decisionRules';
import { VerdictReason } from './GovernanceBits';
import {
  OUTCOME,
  OUTCOME_HINT,
  catalogueName,
  errorText,
  evidenceDetail,
  evidenceMark,
  evidenceText,
  vocab,
  type LabelContext,
} from './labels';

const OUTCOMES: Outcome[] = ['go', 'go_with_conditions', 'hold', 'recycle', 'stop'];

let rowSeq = 0;
function newCondition(seed: ConditionInput = emptyCondition()): ConditionDraft {
  rowSeq += 1;
  return { ...seed, rowId: `c${rowSeq}` };
}

export interface DecisionDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  detail: GateDetail;
  catalogueId: string;
  labels: LabelContext;
  today: string;
  busy: boolean;
  /** Blockers the server answered with on the last attempt, shown at the top. */
  serverViolations: Violation[];
  serverError: string | null;
  onSubmit: (input: DecisionInput) => void;
  /** Opens the approval this gate runs on; offered where an outcome waits for more approvers. */
  onOpenApproval?: () => void;
}

export function DecisionDialog({
  open,
  onClose,
  projectId,
  detail,
  catalogueId,
  labels,
  today,
  busy,
  serverViolations,
  serverError,
  onSubmit,
  onOpenApproval,
}: DecisionDialogProps) {
  const { t } = useTranslation();
  const naAreas = useMemo(() => notApplicableAreas(detail), [detail]);
  const riskAreas = useMemo(() => atRiskCandidates(detail), [detail]);
  const missingDocuments = useMemo(() => documentBlockers(detail), [detail]);
  const unknownEvidence = useMemo(() => evidenceToAcknowledge(detail), [detail]);
  const [draft, setDraft] = useState<DecisionDraft>({
    outcome: null,
    rationale: '',
    conditions: [],
    proceedAtRisk: [],
    acceptedNotApplicable: [],
    holdResumeDate: '',
    acknowledged: [],
  });
  const problems = decisionProblems(draft, detail, today);
  const areaName = (code: string) => catalogueName(labels, { kind: 'area', code, catalogueId });
  const documentLabels = new Map(detail.areas.flatMap((a) => a.documents.map((d) => [d.doc_type, d.name] as const)));
  const documentName = (code: string) =>
    catalogueName(labels, { kind: 'doc', code, catalogueId, label: documentLabels.get(code) });
  // A missing document becomes a condition that already names the pair the
  // server matches on, with a sentence the decider can still rewrite.
  const coverDocument = (blocker: Violation) =>
    setDraft((d) => {
      const text = t('governance.project.decision.document_condition_text', {
        defaultValue: 'Hand in "{{document}}" and have it approved',
        document: documentName(blocker.document_type ?? ''),
      });
      const row = newCondition(conditionForDocument(blocker, text));
      // The row the dialog opened by itself is still empty: replace it rather than leave it behind.
      const kept = d.conditions.filter((c) => c.text.trim() || c.document_type);
      return { ...d, outcome: 'go_with_conditions', conditions: [...kept, row] };
    });

  const setOutcome = (outcome: Outcome) =>
    setDraft((d) => ({
      ...d,
      outcome,
      conditions: outcome === 'go_with_conditions' && d.conditions.length === 0 ? [newCondition()] : d.conditions,
    }));
  const patchCondition = (rowId: string, patch: Partial<ConditionDraft>) =>
    setDraft((d) => ({ ...d, conditions: d.conditions.map((c) => (c.rowId === rowId ? { ...c, ...patch } : c)) }));
  const toggle = (field: 'proceedAtRisk' | 'acceptedNotApplicable', code: string) =>
    setDraft((d) => ({
      ...d,
      [field]: d[field].includes(code) ? d[field].filter((c) => c !== code) : [...d[field], code],
    }));
  const acknowledged = draft.acknowledged ?? [];
  const toggleAcknowledged = (key: string) =>
    setDraft((d) => {
      const now = d.acknowledged ?? [];
      return { ...d, acknowledged: now.includes(key) ? now.filter((k) => k !== key) : [...now, key] };
    });

  const fieldClass =
    'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="xl"
      testId="decision-dialog"
      title={t('governance.project.decision.title', { defaultValue: 'Record gate decision' })}
      subtitle={t('governance.project.decision.subtitle', {
        defaultValue: 'The decision is final for this attempt. It freezes the approved document revisions and readiness checks.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {problems.length > 0 && (
            <ul className="mr-auto space-y-0.5 text-xs text-semantic-error" data-testid="decision-problems">
              {problems.map((p) => (
                <li key={p} data-problem={p}>
                  {t(DECISION_PROBLEM[p][0], { defaultValue: DECISION_PROBLEM[p][1] })}
                </li>
              ))}
            </ul>
          )}
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('governance.project.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant={draft.outcome === 'stop' ? 'danger' : 'primary'}
            loading={busy}
            disabled={problems.length > 0}
            onClick={() => onSubmit(toDecisionInput(draft, detail))}
            data-testid="decision-submit"
          >
            {t('governance.project.decision.submit', { defaultValue: 'Record decision' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        {(serverError || serverViolations.length > 0) && (
          <div role="alert" className="rounded-md border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm">
            {serverError && <p className="font-medium text-content-primary">{serverError}</p>}
            {serverViolations.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-content-secondary">
                {serverViolations.map((v, i) => (
                  <li key={`${v.code}-${v.area_code ?? ''}-${v.ref ?? ''}-${i}`}>
                    {errorText(t, v.code, v.message)}
                    {v.area_code && <span className="text-content-tertiary"> ({areaName(v.area_code)})</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {detail.blockers.length > 0 && (
          <div className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg p-3 text-sm">
            <p className="font-medium text-content-primary">
              {t('governance.project.decision.open_blockers', {
                defaultValue: 'This gate has {{count}} open blockers. A plain go is refused until they are resolved or turned into conditions.',
                count: detail.blockers.length,
              })}
            </p>
          </div>
        )}

        <fieldset>
          <legend className="mb-2 text-sm font-semibold text-content-primary">
            {t('governance.project.decision.outcome', { defaultValue: 'Outcome' })}
          </legend>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5" role="radiogroup">
            {OUTCOMES.map((o) => {
              const refused = outcomeVerdict(detail, o);
              return (
                <label
                  key={o}
                  data-testid={`outcome-${o}`}
                  className={clsx(
                    'flex flex-col gap-1 rounded-lg border p-3 text-sm transition-colors',
                    refused ? 'cursor-not-allowed opacity-70' : 'cursor-pointer',
                    draft.outcome === o
                      ? o === 'stop'
                        ? 'border-semantic-error bg-semantic-error-bg'
                        : 'border-oe-blue bg-oe-blue-subtle'
                      : 'border-border-light hover:border-border',
                  )}
                >
                  <span className="flex items-center gap-2 font-medium text-content-primary">
                    <input
                      type="radio"
                      name="outcome"
                      value={o}
                      checked={draft.outcome === o}
                      disabled={!!refused}
                      onChange={() => setOutcome(o)}
                    />
                    {vocab(t, OUTCOME, o)}
                  </span>{' '}
                  <span className="text-xs text-content-secondary">{vocab(t, OUTCOME_HINT, o)}</span>
                  <VerdictReason verdict={refused} />
                  {onOpenApproval && refused && typeof refused === 'object' && refused.server === 'route_needs_more_approvals' && (
                    <button
                      type="button"
                      className="self-start text-xs font-medium text-oe-blue hover:underline"
                      onClick={(e) => {
                        e.preventDefault();
                        onOpenApproval();
                      }}
                      data-testid={`outcome-${o}-open-approval`}
                    >
                      {t('governance.project.gate.open_approval', { defaultValue: 'Open the approval' })}
                    </button>
                  )}
                </label>
              );
            })}
          </div>
        </fieldset>

        <div>
          <label htmlFor="decision-rationale" className="mb-1 block text-sm font-semibold text-content-primary">
            {t('governance.project.decision.rationale', { defaultValue: 'Rationale' })}
            {needsRationale(draft.outcome) && (
              <span className="ml-1 text-xs font-normal text-semantic-error">
                {t('governance.project.required', { defaultValue: 'required' })}
              </span>
            )}
          </label>
          <textarea
            id="decision-rationale"
            rows={3}
            className={fieldClass}
            value={draft.rationale}
            onChange={(e) => setDraft((d) => ({ ...d, rationale: e.target.value }))}
            placeholder={t('governance.project.decision.rationale_placeholder', {
              defaultValue: 'Why this outcome, and what it rests on. It stays on the record.',
            })}
          />
        </div>

        {draft.outcome === 'hold' && (
          <div>
            <label htmlFor="decision-resume" className="mb-1 block text-sm font-semibold text-content-primary">
              {t('governance.project.decision.resume_date', { defaultValue: 'Resume on' })}
            </label>
            <input
              id="decision-resume"
              type="date"
              min={dayAfter(today)}
              className={clsx(fieldClass, 'max-w-xs')}
              value={draft.holdResumeDate}
              onChange={(e) => setDraft((d) => ({ ...d, holdResumeDate: e.target.value }))}
            />
          </div>
        )}

        {missingDocuments.length > 0 && (
          <div className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="missing-documents">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
              <FileWarning size={15} className="text-[#b45309]" aria-hidden />
              {t('governance.project.decision.missing_documents', { defaultValue: 'Required documents not ready' })}
            </h3>
            <p className="mt-1 text-xs text-content-secondary">
              {t('governance.project.decision.missing_documents_hint', {
                defaultValue:
                  'A go is refused while these are missing. Turn one into a condition to go ahead with an owner and a due date for it.',
              })}
            </p>
            <ul className="mt-2 space-y-1.5">
              {missingDocuments.map((b) => {
                const covered = coversDocument(draft.conditions, b);
                return (
                  <li
                    key={`${b.area_code}-${b.document_type}`}
                    className="flex flex-wrap items-center gap-2 text-sm"
                    data-testid="missing-document"
                  >
                    <span className="text-content-primary">{documentName(b.document_type ?? '')}</span>
                    <span className="text-xs text-content-tertiary">({areaName(b.area_code ?? '')})</span>
                    {covered ? (
                      <span className="ml-auto text-xs font-medium text-semantic-success">
                        {t('governance.project.decision.document_covered', { defaultValue: 'Covered by a condition' })}
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        className="ml-auto"
                        disabled={!!outcomeVerdict(detail, 'go_with_conditions')}
                        onClick={() => coverDocument(b)}
                      >
                        {t('governance.project.decision.document_to_condition', { defaultValue: 'Turn into a condition' })}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {draft.outcome === 'go_with_conditions' && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('governance.project.decision.conditions', { defaultValue: 'Conditions' })}
              </h3>
              <Button
                size="sm"
                variant="secondary"
                icon={<Plus size={14} />}
                onClick={() => setDraft((d) => ({ ...d, conditions: [...d.conditions, newCondition()] }))}
              >
                {t('governance.project.decision.add_condition', { defaultValue: 'Add condition' })}
              </Button>
            </div>
            {draft.conditions.map((c, idx) => (
              <div key={c.rowId} data-testid="condition-row" className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
                <ConditionFields
                  projectId={projectId}
                  value={c}
                  areas={detail.areas}
                  areaName={areaName}
                  documentName={documentName}
                  onChange={(patch) => patchCondition(c.rowId, patch)}
                  trailing={
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      aria-label={t('governance.project.decision.remove_condition', {
                        defaultValue: 'Remove condition {{n}}',
                        n: idx + 1,
                      })}
                      onClick={() =>
                        setDraft((d) => ({ ...d, conditions: d.conditions.filter((x) => x.rowId !== c.rowId) }))
                      }
                    />
                  }
                />
              </div>
            ))}
            {riskAreas.length > 0 && (
              <fieldset className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
                <legend className="px-1 text-xs font-semibold text-content-secondary">
                  {t('governance.project.decision.proceed_at_risk', {
                    defaultValue: 'Proceed at risk (only areas whose readiness blocks)',
                  })}
                </legend>
                {riskAreas.map((code) => (
                  <label key={code} className="mr-4 inline-flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={draft.proceedAtRisk.includes(code)}
                      onChange={() => toggle('proceedAtRisk', code)}
                    />
                    {areaName(code)}
                  </label>
                ))}
              </fieldset>
            )}
          </div>
        )}

        {unknownEvidence.length > 0 && letsGatePass(draft.outcome) && (
          <fieldset className="rounded-lg border border-semantic-warning/40 p-3" data-testid="acknowledge-evidence">
            <legend className="px-1 text-xs font-semibold text-content-secondary">
              {t('governance.project.decision.acknowledge', { defaultValue: 'Evidence to confirm before the gate passes' })}
            </legend>
            <p className="mb-1.5 text-xs text-content-secondary">
              {t('governance.project.decision.acknowledge_hint', {
                defaultValue:
                  'These items are unconfirmed or carry a warning. Tick each one to confirm that you have seen it before the gate passes.',
              })}
            </p>
            {unknownEvidence.map((ref) => {
              const key = evidenceKey(ref);
              const item = detail.areas.find((a) => a.code === ref.area_code)?.evidence.find((e) => e.code === ref.code);
              const state = ref.state ?? item?.state;
              return (
                <label key={key} className="flex items-start gap-1.5 py-0.5 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={acknowledged.includes(key)}
                    onChange={() => toggleAcknowledged(key)}
                    data-testid="acknowledge-item"
                  />
                  <span>
                    {areaName(ref.area_code)}
                    <span
                      className={clsx(
                        'ml-1.5 text-xs font-medium',
                        state === 'warning' ? 'text-[#b45309]' : 'text-content-tertiary',
                      )}
                      data-testid="acknowledge-mark"
                      data-state={state === 'warning' ? 'warning' : 'unknown'}
                    >
                      {evidenceMark(t, state)}
                    </span>
                    <span className="block text-xs text-content-tertiary">
                      {evidenceText(t, labels, item ?? ref)}
                      {item && evidenceDetail(t, labels, item) ? ` - ${evidenceDetail(t, labels, item)}` : ''}
                    </span>
                  </span>
                </label>
              );
            })}
          </fieldset>
        )}

        {naAreas.length > 0 && (
          <fieldset className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
            <legend className="px-1 text-xs font-semibold text-content-secondary">
              {t('governance.project.decision.accept_na', {
                defaultValue: 'Accept as not applicable',
              })}
            </legend>
            {naAreas.map((code) => {
              const area = detail.areas.find((a) => a.code === code);
              const why = area?.check?.na_rationale;
              return (
                <label key={code} className="flex items-start gap-1.5 py-0.5 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={draft.acceptedNotApplicable.includes(code)}
                    onChange={() => toggle('acceptedNotApplicable', code)}
                  />
                  <span>
                    {areaName(code)}
                    {why && <span className="block text-xs text-content-tertiary">{why}</span>}
                  </span>
                </label>
              );
            })}
          </fieldset>
        )}
      </div>
    </WideModal>
  );
}
