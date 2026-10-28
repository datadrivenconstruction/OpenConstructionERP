// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What stopping this commitment would cost: the basis the charge is worked
// out on (a contract clause, a supplier's cancellation schedule, an amount
// entered by hand), what can be recovered by transfer or resale, and where
// the figures come from. Without these the abort exposure of the item reads
// "unknown", never zero.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';

import { putAbortTerms, type AbortBasis, type AbortTerms, type CommitmentItem, type Transferable } from './api';
import { FIELD_CLASS, Field, RefusalBox, refusalText } from './CommitmentBits';
import { TRANSFERABLE, catalogueName, humanizeCode, vocab, type LabelContext } from './labels';
import {
  ABORT_TERMS_PROBLEM,
  abortTermsProblems,
  fractionToPercent,
  parametersFor,
  toAbortTermsInput,
  type AbortTermsDraft,
  type StepDraft,
} from './rules';

const TRANSFER_OPTIONS: Transferable[] = ['no', 'to_project', 'resale'];

let rowSeq = 0;
function newStep(): StepDraft {
  rowSeq += 1;
  return { rowId: `s${rowSeq}`, milestone: '', fromDate: '', progressPercent: '', chargePercent: '', chargeAmount: '' };
}

function draftOfTerms(terms: AbortTerms | null): AbortTermsDraft {
  return {
    basisCode: terms?.basis_code ?? '',
    basisSource: terms?.basis_source ?? 'shipped',
    progressPercent: fractionToPercent(terms?.progress_pct),
    // Stored as fractions, typed as percentages like every other share in this form.
    parameters: Object.fromEntries(
      Object.entries(terms?.parameters ?? {}).map(([name, value]) => [name, fractionToPercent(value)]),
    ),
    steps: (terms?.cancellation_schedule ?? []).map((s) => ({
      ...newStep(),
      milestone: s.milestone,
      fromDate: s.from_date ?? '',
      progressPercent: fractionToPercent(s.progress_pct),
      chargePercent: fractionToPercent(s.charge_pct),
      chargeAmount: s.charge_amount ?? '',
    })),
    transferable: terms?.transferable ?? 'no',
    transferValue: terms?.transfer_value_estimate ?? '',
    salvageValue: terms?.salvage_value_estimate ?? '',
    savedCost: terms?.saved_cost_estimate ?? '',
    otherCharge: terms?.other_charge_estimate ?? '',
    noticeDays: terms?.notice_days == null ? '' : String(terms.notice_days),
    sourceNote: terms?.source_note ?? '',
  };
}

export interface AbortTermsDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  item: CommitmentItem;
  /** The terms recorded for the whole item, or null when there are none yet. */
  terms: AbortTerms | null;
  bases: AbortBasis[];
  labels: LabelContext;
  onSaved: () => void;
}

export function AbortTermsDialog({ open, onClose, projectId, item, terms, bases, labels, onSaved }: AbortTermsDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<AbortTermsDraft>(() => draftOfTerms(terms));
  const [tried, setTried] = useState(false);
  const set = (patch: Partial<AbortTermsDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const patchStep = (rowId: string, patch: Partial<StepDraft>) =>
    set({ steps: draft.steps.map((s) => (s.rowId === rowId ? { ...s, ...patch } : s)) });
  // Two sources may carry a basis under one id, so a basis is told apart by both.
  const basisKey = (b: Pick<AbortBasis, 'source' | 'id'>) => `${b.source}:${b.id}`;
  const picked = draft.basisCode ? `${draft.basisSource}:${draft.basisCode}` : '';
  const basis = bases.find((b) => basisKey(b) === picked) ?? null;
  // The contract figures the chosen basis works with. Another basis has other figures or none.
  const fields = basis?.parameter_fields ?? [];
  const problems = abortTermsProblems(draft, fields);
  const currency = item.exposure?.currency ?? item.schedule_currency;

  const save = useMutation({
    mutationFn: () => putAbortTerms(projectId, item.id, toAbortTermsInput(draft, fields)),
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  const amountField = (id: string, label: string, key: 'transferValue' | 'salvageValue' | 'savedCost' | 'otherCharge') => (
    <Field id={id} label={label}>
      <input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        className={FIELD_CLASS}
        value={draft[key]}
        onChange={(e) => set({ [key]: e.target.value })}
      />
    </Field>
  );

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="xl"
      testId="abort-terms-dialog"
      title={t('commitment.drawer.abort_terms', { defaultValue: 'Abort terms' })}
      subtitle={t('commitment.abort_form.subtitle', {
        defaultValue: '{{code}} {{title}}. What stopping this commitment would cost, in {{currency}}.',
        code: item.code,
        title: item.title,
        currency,
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          {tried && problems.length > 0 && (
            <ul className="mr-auto space-y-0.5 text-xs text-semantic-error" data-testid="abort-terms-problems">
              {problems.map((p) => (
                <li key={p} data-problem={p}>
                  {t(ABORT_TERMS_PROBLEM[p][0], { defaultValue: ABORT_TERMS_PROBLEM[p][1] })}
                </li>
              ))}
            </ul>
          )}
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('commitment.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={submit} data-testid="abort-terms-save">
            {t('commitment.abort_form.save', { defaultValue: 'Save abort terms' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        {save.isError && <RefusalBox message={refusalText(t, save.error)} />}

        <Field
          id="abort-basis"
          label={t('commitment.abort_form.basis', { defaultValue: 'Basis of the charge' })}
          hint={t('commitment.abort_form.basis_hint', {
            defaultValue: 'The clause or agreement the cancellation charge follows from.',
          })}
        >
          <select
            id="abort-basis"
            className={FIELD_CLASS}
            value={picked}
            onChange={(e) => {
              const next = bases.find((b) => basisKey(b) === e.target.value);
              set({
                basisCode: next?.id ?? '',
                basisSource: next?.source ?? 'shipped',
                parameters: parametersFor(draft.parameters, next?.parameter_fields ?? []),
              });
            }}
          >
            <option value="">{t('commitment.abort_form.basis_none', { defaultValue: 'Not known yet' })}</option>
            {bases.map((b) => (
              <option key={basisKey(b)} value={basisKey(b)}>
                {catalogueName(labels, b.id, b.name)}
              </option>
            ))}
          </select>
        </Field>
        {basis && basis.review_status !== 'verified' && (
          <p className="flex items-start gap-2 text-xs text-content-secondary" data-testid="basis-unconfirmed">
            <Badge variant="warning" size="sm">
              {t('commitment.abort_form.unconfirmed', { defaultValue: 'Unconfirmed' })}
            </Badge>
            {t('commitment.exposure.basis_unconfirmed', {
              defaultValue: 'Statutory basis not yet confirmed by a domain expert',
            })}
          </p>
        )}

        {fields.length > 0 && (
          <fieldset className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="abort-parameters">
            <legend className="px-1 text-xs font-semibold text-content-secondary">
              {t('commitment.abort_form.parameters', { defaultValue: 'Figures this basis works with, in per cent' })}
            </legend>
            <div className="grid gap-3 sm:grid-cols-3">
              {fields.map((field) => {
                const id = `abort-parameter-${field.name}`;
                const standard = fractionToPercent(field.default);
                return (
                  <Field
                    key={field.name}
                    id={id}
                    label={labels.exists(field.label_key) ? labels.t(field.label_key) : humanizeCode(field.name)}
                    required={field.required}
                    hint={
                      field.default === null
                        ? t('commitment.abort_form.parameter_required', {
                            defaultValue: 'The basis has no standard value. Take it from the contract.',
                          })
                        : t('commitment.abort_form.parameter_default', {
                            defaultValue: 'Left empty, the standard value of the basis applies: {{value}}',
                            value: standard,
                          })
                    }
                  >
                    <input
                      id={id}
                      inputMode="decimal"
                      autoComplete="off"
                      className={FIELD_CLASS}
                      placeholder={standard}
                      value={draft.parameters[field.name] ?? ''}
                      onChange={(e) => set({ parameters: { ...draft.parameters, [field.name]: e.target.value } })}
                    />
                  </Field>
                );
              })}
            </div>
          </fieldset>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('commitment.abort_form.schedule', { defaultValue: 'Cancellation steps' })}
            </h3>
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus size={14} />}
              onClick={() => set({ steps: [...draft.steps, newStep()] })}
              data-testid="abort-step-add"
            >
              {t('commitment.abort_form.add_step', { defaultValue: 'Add step' })}
            </Button>
          </div>
          {draft.steps.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('commitment.abort_form.no_steps', {
                defaultValue: 'No steps. Add them when the charge grows with time, for example 10% from order and 50% once fabrication starts.',
              })}
            </p>
          ) : (
            draft.steps.map((s, idx) => (
              <div
                key={s.rowId}
                data-testid="abort-step-row"
                className="grid gap-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-3 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]"
              >
                <input
                  aria-label={t('commitment.abort_form.step_name', { defaultValue: 'Step, for example fabrication started' })}
                  placeholder={t('commitment.abort_form.step_name', {
                    defaultValue: 'Step, for example fabrication started',
                  })}
                  className={FIELD_CLASS}
                  value={s.milestone}
                  onChange={(e) => patchStep(s.rowId, { milestone: e.target.value })}
                />
                <input
                  type="date"
                  aria-label={t('commitment.abort_form.step_from', { defaultValue: 'Applies from' })}
                  className={FIELD_CLASS}
                  value={s.fromDate}
                  onChange={(e) => patchStep(s.rowId, { fromDate: e.target.value })}
                />
                <input
                  inputMode="decimal"
                  aria-label={t('commitment.abort_form.step_progress', { defaultValue: 'or from progress, %' })}
                  placeholder={t('commitment.abort_form.step_progress', { defaultValue: 'or from progress, %' })}
                  className={FIELD_CLASS}
                  value={s.progressPercent}
                  onChange={(e) => patchStep(s.rowId, { progressPercent: e.target.value })}
                />
                <input
                  inputMode="decimal"
                  aria-label={t('commitment.abort_form.step_percent', { defaultValue: 'Charge, % of the commitment' })}
                  placeholder={t('commitment.abort_form.step_percent', { defaultValue: 'Charge, % of the commitment' })}
                  className={FIELD_CLASS}
                  value={s.chargePercent}
                  onChange={(e) => patchStep(s.rowId, { chargePercent: e.target.value })}
                />
                <input
                  inputMode="decimal"
                  aria-label={t('commitment.abort_form.step_amount', { defaultValue: 'or a fixed amount' })}
                  placeholder={t('commitment.abort_form.step_amount', { defaultValue: 'or a fixed amount' })}
                  className={FIELD_CLASS}
                  value={s.chargeAmount}
                  onChange={(e) => patchStep(s.rowId, { chargeAmount: e.target.value })}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 size={14} />}
                  aria-label={t('commitment.abort_form.remove_step', { defaultValue: 'Remove step {{n}}', n: idx + 1 })}
                  onClick={() => set({ steps: draft.steps.filter((x) => x.rowId !== s.rowId) })}
                />
              </div>
            ))
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {amountField(
            'abort-other-charge',
            t('commitment.abort_form.other_charge', { defaultValue: 'Other charge on cancellation' }),
            'otherCharge',
          )}
          {amountField(
            'abort-saved-cost',
            t('commitment.abort_form.saved_cost', { defaultValue: 'Cost the contractor saves' }),
            'savedCost',
          )}
        </div>

        <fieldset className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3">
          <legend className="px-1 text-xs font-semibold text-content-secondary">
            {t('commitment.grid.cancellation_option', { defaultValue: 'Cancellation or transfer' })}
          </legend>
          <div className="flex flex-wrap gap-4" role="radiogroup">
            {TRANSFER_OPTIONS.map((opt) => (
              <label key={opt} className="inline-flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name="abort-transferable"
                  value={opt}
                  checked={draft.transferable === opt}
                  onChange={() => set({ transferable: opt })}
                />
                {vocab(t, TRANSFERABLE, opt)}
              </label>
            ))}
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {amountField(
              'abort-transfer-value',
              t('commitment.abort_form.transfer_value', { defaultValue: 'Value if transferred' }),
              'transferValue',
            )}
            {amountField(
              'abort-salvage-value',
              t('commitment.abort_form.salvage_value', { defaultValue: 'Value if resold' }),
              'salvageValue',
            )}
          </div>
        </fieldset>

        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,3fr)]">
          <Field id="abort-progress" label={t('commitment.abort_form.progress', { defaultValue: 'Work done so far, %' })}>
            <input
              id="abort-progress"
              inputMode="decimal"
              className={FIELD_CLASS}
              value={draft.progressPercent}
              onChange={(e) => set({ progressPercent: e.target.value })}
            />
          </Field>
          <Field id="abort-notice" label={t('commitment.abort_form.notice_days', { defaultValue: 'Notice, days' })}>
            <input
              id="abort-notice"
              inputMode="numeric"
              className={FIELD_CLASS}
              value={draft.noticeDays}
              onChange={(e) => set({ noticeDays: e.target.value })}
            />
          </Field>
          <Field
            id="abort-source"
            label={t('commitment.abort_form.source_note', { defaultValue: 'Where the figures come from' })}
            hint={t('commitment.abort_form.source_note_hint', {
              defaultValue: 'The contract clause, the quotation or the letter. Every change is kept in the audit log.',
            })}
          >
            <input
              id="abort-source"
              className={FIELD_CLASS}
              value={draft.sourceNote}
              onChange={(e) => set({ sourceNote: e.target.value })}
            />
          </Field>
        </div>
      </div>
    </WideModal>
  );
}
