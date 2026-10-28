// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The three writes on a bidder candidate: who the company is and which list
// it is on, how it scores against the prequalification profile, and the
// reference projects it names. The server repeats every check made here.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';

import {
  addCandidate,
  addReference,
  patchCandidate,
  putScores,
  type Candidate,
  type CandidateList,
  type CandidateSource,
  type ProfileCriterion,
} from './api';
import { CompanyPicker, useCompanyRegister } from './CompanyPicker';
import { CANDIDATE_LIST, CANDIDATE_SOURCE, catalogueName, errorText, vocab, type LabelContext } from './labels';
import { FIELD_CLASS, Field, ProblemList, RefusalBox } from './ProcurementBits';
import {
  CANDIDATE_PROBLEM,
  candidateProblems,
  companyLinks,
  companyValue,
  parseAmount,
  scoresValid,
  toCandidateInput,
  toScoreInputs,
  type CandidateDraft,
  type ScoreDraft,
  type Verdict,
} from './rules';

const LISTS: CandidateList[] = ['long', 'short', 'excluded'];
const SOURCES: CandidateSource[] = ['own_list', 'market_sounding', 'framework', 'public_notice'];

interface DialogBase {
  open: boolean;
  onClose: () => void;
  projectId: string;
  labels: LabelContext;
  onSaved: () => void;
}

/* ── Candidate ────────────────────────────────────────────────────────── */

export function CandidateDialog({
  open,
  onClose,
  projectId,
  packageId,
  candidate,
  listVerdict,
  labels,
  onSaved,
}: DialogBase & {
  packageId: string;
  candidate: Candidate | null;
  /** Why the reader may not move a company between the lists, or null when they may. */
  listVerdict: Verdict;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<CandidateDraft>({
    subcontractor_id: candidate?.subcontractor_id ?? '',
    vendor_id: candidate?.subcontractor_id ? '' : (candidate?.vendor_id ?? ''),
    free_name: candidate && !candidate.registered ? candidate.name : '',
    source: candidate?.source ?? 'own_list',
    list: candidate?.list ?? 'long',
    decision_rationale: candidate?.decision_rationale ?? '',
    conflict_of_interest_declared: candidate?.conflict_of_interest_declared ?? false,
    conflict_note: candidate?.conflict_note ?? '',
  });
  const set = <K extends keyof CandidateDraft>(key: K, value: CandidateDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const problems = candidateProblems(draft);

  // A registered company is a subcontractor or a vendor: both registers feed one picker.
  const register = useCompanyRegister(open);
  const company = companyValue(draft);

  const save = useMutation({
    mutationFn: () =>
      candidate
        ? patchCandidate(projectId, candidate.id, toCandidateInput(draft))
        : addCandidate(projectId, packageId, toCandidateInput(draft)),
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="candidate-dialog"
      title={
        candidate
          ? t('procurement_concept.ui.candidate.edit_title', { defaultValue: 'Candidate {{name}}', name: candidate.name })
          : t('procurement_concept.ui.candidate.add_title', { defaultValue: 'Add a candidate' })
      }
      subtitle={t('procurement_concept.ui.candidate.subtitle', {
        defaultValue: 'A company you consider for this package. Only a registered company can be short-listed.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          <ProblemList problems={problems.map((p) => CANDIDATE_PROBLEM[p])} />
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={problems.length > 0} onClick={() => save.mutate()} data-testid="candidate-save">
            {t('procurement_concept.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox error={save.error} />
        <div className="grid gap-4 sm:grid-cols-2">
          <CompanyPicker
            id="cd-company"
            label={t('procurement_concept.ui.candidate.company', { defaultValue: 'Registered company' })}
            value={company}
            keptName={candidate?.name}
            register={register}
            onChange={(value) => setDraft((d) => ({ ...d, ...companyLinks(value) }))}
          />
          {!company && (
            <Field label={t('procurement_concept.ui.candidate.free_name', { defaultValue: 'Company name' })} htmlFor="cd-name">
              <input id="cd-name" className={FIELD_CLASS} value={draft.free_name} onChange={(e) => set('free_name', e.target.value)} />
            </Field>
          )}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t('procurement_concept.ui.candidate.list', { defaultValue: 'List' })}
            htmlFor="cd-list"
            hint={listVerdict ? errorText(labels.t, listVerdict) : undefined}
          >
            <select id="cd-list" className={FIELD_CLASS} disabled={!!listVerdict} value={draft.list} onChange={(e) => set('list', e.target.value as CandidateList)}>
              {LISTS.map((l) => (
                <option key={l} value={l}>
                  {vocab(labels.t, CANDIDATE_LIST, l)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('procurement_concept.ui.candidate.source', { defaultValue: 'Where the company came from' })} htmlFor="cd-source">
            <select
              id="cd-source"
              className={FIELD_CLASS}
              value={draft.source}
              onChange={(e) => set('source', e.target.value as CandidateSource)}
            >
              {SOURCES.map((s) => (
                <option key={s} value={s}>
                  {vocab(labels.t, CANDIDATE_SOURCE, s)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field
          label={
            draft.list === 'excluded'
              ? t('procurement_concept.ui.candidate.rationale_required', { defaultValue: 'Why the company is excluded (required)' })
              : t('procurement_concept.ui.candidate.rationale', { defaultValue: 'Reason for this list' })
          }
          htmlFor="cd-rationale"
        >
          <textarea
            id="cd-rationale"
            rows={2}
            className={FIELD_CLASS}
            value={draft.decision_rationale}
            onChange={(e) => set('decision_rationale', e.target.value)}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            checked={draft.conflict_of_interest_declared}
            onChange={(e) => set('conflict_of_interest_declared', e.target.checked)}
          />
          {t('procurement_concept.ui.candidate.conflict', { defaultValue: 'A conflict of interest was declared' })}
        </label>
        {draft.conflict_of_interest_declared && (
          <Field label={t('procurement_concept.ui.candidate.conflict_note', { defaultValue: 'What the conflict is and how it is handled' })} htmlFor="cd-conflict">
            <textarea
              id="cd-conflict"
              rows={2}
              className={FIELD_CLASS}
              value={draft.conflict_note}
              onChange={(e) => set('conflict_note', e.target.value)}
            />
          </Field>
        )}
      </div>
    </WideModal>
  );
}

/* ── Scores ───────────────────────────────────────────────────────────── */

export function ScoresDialog({
  open,
  onClose,
  projectId,
  candidate,
  criteria,
  labels,
  onSaved,
}: DialogBase & { candidate: Candidate; criteria: ProfileCriterion[] }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ScoreDraft[]>(() =>
    criteria.map((c) => {
      const s = candidate.scores.find((x) => x.criterion_code === c.code);
      return {
        criterion_code: c.code,
        kind: c.kind === 'pass_fail' ? 'pass_fail' : 'scored',
        passed: s?.passed === true ? 'yes' : s?.passed === false ? 'no' : '',
        score: s?.score ?? '',
      };
    }),
  );
  const patch = (code: string, change: Partial<ScoreDraft>) =>
    setRows((list) => list.map((r) => (r.criterion_code === code ? { ...r, ...change } : r)));
  const valid = scoresValid(rows);

  const save = useMutation({
    mutationFn: () => putScores(projectId, candidate.id, toScoreInputs(rows)),
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="scores-dialog"
      title={t('procurement_concept.ui.scores.title', { defaultValue: 'Score {{name}}', name: candidate.name })}
      subtitle={t('procurement_concept.ui.scores.subtitle', {
        defaultValue: 'Pass or fail criteria take a verdict. Scored criteria take 0 to 100 points and count by their weight.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          <ProblemList
            problems={valid ? [] : [['procurement_concept.ui.problem.score_invalid', 'A score is a number from 0 to 100.']]}
          />
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={!valid} onClick={() => save.mutate()} data-testid="scores-save">
            {t('procurement_concept.ui.scores.save', { defaultValue: 'Save scores' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <RefusalBox error={save.error} />
        {rows.map((r) => {
          const criterion = criteria.find((c) => c.code === r.criterion_code);
          const name = catalogueName(labels, 'criterion', r.criterion_code);
          const id = `sc-${r.criterion_code}`;
          return (
            <div key={r.criterion_code} className="grid items-center gap-3 sm:grid-cols-[1fr_12rem]" data-testid="score-row">
              <label htmlFor={id} className="text-sm text-content-primary">
                {name}
                {r.kind === 'scored' && criterion && (
                  <span className="ml-2 text-xs text-content-tertiary">
                    {t('procurement_concept.ui.scores.weight', { defaultValue: 'weight {{weight}}', weight: criterion.weight })}
                  </span>
                )}
              </label>
              {r.kind === 'pass_fail' ? (
                <select
                  id={id}
                  className={FIELD_CLASS}
                  value={r.passed}
                  onChange={(e) => patch(r.criterion_code, { passed: e.target.value as ScoreDraft['passed'] })}
                >
                  <option value="">{t('procurement_concept.ui.scores.not_assessed', { defaultValue: 'Not assessed' })}</option>
                  <option value="yes">{t('procurement_concept.ui.scores.pass', { defaultValue: 'Pass' })}</option>
                  <option value="no">{t('procurement_concept.ui.scores.fail', { defaultValue: 'Fail' })}</option>
                </select>
              ) : (
                <input
                  id={id}
                  inputMode="decimal"
                  className={FIELD_CLASS}
                  placeholder={t('procurement_concept.ui.scores.points', { defaultValue: 'Points, 0 to 100' })}
                  value={r.score}
                  onChange={(e) => patch(r.criterion_code, { score: e.target.value })}
                />
              )}
            </div>
          );
        })}
      </div>
    </WideModal>
  );
}

/* ── Reference project ────────────────────────────────────────────────── */

export function ReferenceDialog({ open, onClose, projectId, candidate, onSaved }: DialogBase & { candidate: Candidate }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState({ project_name: '', client: '', value: '', currency: '', year: '', role: '', verified: false });
  const set = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const valueBad = draft.value.trim() !== '' && parseAmount(draft.value) === null;
  const yearBad = draft.year.trim() !== '' && !/^(19|20)\d{2}$/.test(draft.year.trim());
  const blocked = !draft.project_name.trim() || valueBad || yearBad;

  const save = useMutation({
    mutationFn: () =>
      addReference(projectId, candidate.id, {
        project_name: draft.project_name.trim(),
        client: draft.client.trim(),
        value: draft.value.trim() ? parseAmount(draft.value) : null,
        currency: draft.currency.trim().toUpperCase(),
        year: draft.year.trim() ? Number(draft.year.trim()) : null,
        role: draft.role.trim(),
        verified: draft.verified,
      }),
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="reference-dialog"
      title={t('procurement_concept.ui.reference.title', { defaultValue: 'Reference project of {{name}}', name: candidate.name })}
      subtitle={t('procurement_concept.ui.reference.subtitle', {
        defaultValue: 'A comparable project the company completed. Tick it as verified once you have checked it with the client.',
      })}
      footer={
        <div className="flex w-full items-center justify-end gap-3">
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={blocked} onClick={() => save.mutate()} data-testid="reference-save">
            {t('procurement_concept.ui.reference.save', { defaultValue: 'Add reference' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox error={save.error} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('procurement_concept.ui.reference.project_name', { defaultValue: 'Project (required)' })} htmlFor="rf-name">
            <input id="rf-name" className={FIELD_CLASS} value={draft.project_name} onChange={(e) => set('project_name', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.reference.client', { defaultValue: 'Client' })} htmlFor="rf-client">
            <input id="rf-client" className={FIELD_CLASS} value={draft.client} onChange={(e) => set('client', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.reference.value', { defaultValue: 'Contract value' })} htmlFor="rf-value">
            <input id="rf-value" inputMode="decimal" className={FIELD_CLASS} value={draft.value} onChange={(e) => set('value', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.package.currency', { defaultValue: 'Currency' })} htmlFor="rf-currency">
            <input id="rf-currency" maxLength={3} className={`${FIELD_CLASS} uppercase`} value={draft.currency} onChange={(e) => set('currency', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.reference.year', { defaultValue: 'Year completed' })} htmlFor="rf-year">
            <input id="rf-year" inputMode="numeric" maxLength={4} className={FIELD_CLASS} value={draft.year} onChange={(e) => set('year', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.reference.role', { defaultValue: 'Role on the project' })} htmlFor="rf-role">
            <input id="rf-role" className={FIELD_CLASS} value={draft.role} onChange={(e) => set('role', e.target.value)} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-content-primary">
          <input type="checkbox" checked={draft.verified} onChange={(e) => set('verified', e.target.checked)} />
          {t('procurement_concept.ui.reference.verified', { defaultValue: 'Checked with the client' })}
        </label>
      </div>
    </WideModal>
  );
}
