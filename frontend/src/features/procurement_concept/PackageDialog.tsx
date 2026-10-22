// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Planning the award of one package: what it is worth, which threshold that
// value meets, which procedures the threshold leaves open, and when the
// contract is needed. The threshold check is the server's; this dialog shows
// its rows with their sources and never compares an amount itself.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import clsx from 'clsx';
import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate } from '@/shared/lib/formatters';

import {
  putPackage,
  type EvaluationMethod,
  type Framework,
  type PackageView,
  type PinnedCatalogue,
  type PrequalProfile,
  type ProcedureOption,
  type SplitBasis,
  type TenderBasis,
} from './api';
import { useMilestones } from '@/features/engineering_brief/hooks';
import { RuleSnapshotPanel } from './RuleSnapshotPanel';
import { refusalText, useAdvanceReleases, useCostSections, useThreshold } from './hooks';
import {
  EVALUATION_METHOD,
  PICKER_REASON,
  SPLIT_BASIS,
  TENDER_BASIS,
  THRESHOLD_STATUS,
  catalogueName,
  errorText,
  vocab,
  type LabelContext,
} from './labels';
import { FIELD_CLASS, Field, FindingList, Money, ProblemList, RefusalBox, THRESHOLD_TONE, ToneBadge } from './ProcurementBits';
import {
  MAX_AWARD_CRITERIA,
  PACKAGE_PROBLEM,
  awardWeightsTotal,
  dropsCriteria,
  notApplicable,
  packageDraft,
  packageProblems,
  toPackageInput,
  type PackageDraft,
  type WeightRow,
} from './rules';

const METHODS: EvaluationMethod[] = ['lowest_price', 'best_value'];
const SPLITS: SplitBasis[] = ['whole', 'trade', 'section', 'system'];
const BASES: TenderBasis[] = ['detailed', 'functional', 'mixed'];

export interface PackageDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  view: PackageView;
  catalogue: PinnedCatalogue | null;
  frameworks: Framework[];
  profiles: PrequalProfile[];
  labels: LabelContext;
  /** Called after a save. `first` is true when the package had no procurement attributes before. */
  onSaved: (first: boolean) => void;
}

export function PackageDialog({
  open,
  onClose,
  projectId,
  view,
  catalogue,
  frameworks,
  profiles,
  labels,
  onSaved,
}: PackageDialogProps) {
  const { t } = useTranslation();
  const [original] = useState<PackageDraft>(() => packageDraft(view));
  const [draft, setDraft] = useState<PackageDraft>(original);
  const set = <K extends keyof PackageDraft>(key: K, value: PackageDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  // Where a package cannot run in advance the reason field is not shown, and the server asks for no reason either.
  const problems = packageProblems(draft).filter((p) => p !== 'advance_without_reason' || !notApplicable(view.can.set_advance));
  // Going to lowest price removes the criteria the package holds, so the reader says yes to that first.
  const [dropConfirmed, setDropConfirmed] = useState(false);
  const mustConfirmDrop = dropsCriteria(draft, original);
  const cp = view.contract_package;

  // The check needs the package to exist on the server with its value.
  const thresholdQ = useThreshold(projectId, view.award ? cp.id : null);
  const check = thresholdQ.data ?? null;
  // The server says whether a package can run in advance at all in this project.
  const advanceOff = notApplicable(view.can.set_advance);
  // A package may still carry the mark from an earlier phase model: the switch stays, so the mark can be cleared.
  const advanceLeftover = advanceOff && original.is_advance;
  const advanceFields = draft.is_advance && !advanceOff;
  // The acts of the release gate, asked for only once the package is marked as an advance package.
  const releasesQ = useAdvanceReleases(projectId, advanceFields);
  const releases = releasesQ.data?.items ?? [];
  // Set when the commitment matrix is not connected, so released commitments are missing from the list for a reason.
  const commitmentsOff = releasesQ.data?.commitments?.available === false ? (releasesQ.data.commitments.reason ?? 'commitment_release_unavailable') : null;
  const sectionsQ = useCostSections(projectId);
  const sections = sectionsQ.data ?? [];
  const setWeight = (index: number, patch: Partial<WeightRow>) =>
    set(
      'weights',
      draft.weights.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );

  const options: ProcedureOption[] =
    check?.procedures ??
    (catalogue?.procedures ?? []).map((p) => ({ code: p.code, name_key: p.name_key ?? '', allowed: true, reason: null }));

  const save = useMutation({
    mutationFn: () => putPackage(projectId, cp.id, toPackageInput(draft, original)),
    onSuccess: () => onSaved(!view.award),
  });

  const milestones = (useMilestones(projectId, true).data ?? []).filter((m) => m.activity_id && m.published);
  const bound = milestones.find((m) => m.activity_id === draft.need_activity_id);
  const usableFrameworks = frameworks.filter((f) => f.state === 'active' || f.id === draft.framework_agreement_id);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="xl"
      testId="package-dialog"
      title={t('procurement_concept.ui.package.dialog_title', {
        defaultValue: 'Plan the award of {{code}}',
        code: cp.code,
      })}
      subtitle={cp.title}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          <ProblemList problems={problems.map((p) => PACKAGE_PROBLEM[p])} />
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={problems.length > 0 || (mustConfirmDrop && !dropConfirmed)} onClick={() => save.mutate()} data-testid="package-save">
            {t('procurement_concept.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        <RefusalBox error={save.error} />

        <section>
          <h3 className="mb-2 text-sm font-semibold text-content-primary">
            {t('procurement_concept.ui.package.value_title', { defaultValue: '1. What the package is worth' })}
          </h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={t('procurement_concept.ui.package.estimated_value', { defaultValue: 'Estimated value' })} htmlFor="pk-value">
              <input
                id="pk-value"
                inputMode="decimal"
                className={FIELD_CLASS}
                value={draft.estimated_value}
                onChange={(e) => set('estimated_value', e.target.value)}
              />
            </Field>
            <Field label={t('procurement_concept.ui.package.currency', { defaultValue: 'Currency' })} htmlFor="pk-currency">
              <input
                id="pk-currency"
                maxLength={3}
                className={clsx(FIELD_CLASS, 'uppercase')}
                value={draft.currency}
                onChange={(e) => set('currency', e.target.value)}
              />
            </Field>
            <Field label={t('procurement_concept.ui.package.split_basis', { defaultValue: 'How the work is split' })} htmlFor="pk-split">
              <select
                id="pk-split"
                className={FIELD_CLASS}
                value={draft.split_basis}
                onChange={(e) => set('split_basis', e.target.value as SplitBasis)}
              >
                {SPLITS.map((s) => (
                  <option key={s} value={s}>
                    {vocab(labels.t, SPLIT_BASIS, s)}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={t('procurement_concept.ui.package.lot_group', { defaultValue: 'Lot group' })}
              htmlFor="pk-lot"
              hint={t('procurement_concept.ui.package.lot_group_hint', {
                defaultValue: 'Lots with the same group are added up for the threshold test.',
              })}
            >
              <input id="pk-lot" className={FIELD_CLASS} value={draft.lot_group} onChange={(e) => set('lot_group', e.target.value)} />
            </Field>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              checked={draft.small_lot_exemption}
              onChange={(e) => set('small_lot_exemption', e.target.checked)}
            />
            {t('procurement_concept.ui.package.small_lot', {
              defaultValue: 'Claim the small lot exemption for this lot',
            })}
          </label>
        </section>

        <section data-testid="threshold-section">
          <h3 className="mb-2 text-sm font-semibold text-content-primary">
            {t('procurement_concept.ui.package.threshold_title', { defaultValue: '2. Which threshold it meets' })}
          </h3>
          {!view.award ? (
            <p className="rounded-md bg-surface-secondary px-3 py-2 text-sm text-content-secondary" data-testid="threshold-pending">
              {t('procurement_concept.ui.package.threshold_after_save', {
                defaultValue: 'Save the value first. The threshold check and the procedures it allows appear right after.',
              })}
            </p>
          ) : thresholdQ.isLoading ? (
            <p className="text-sm text-content-tertiary">
              {t('procurement_concept.ui.package.threshold_loading', { defaultValue: 'Checking the value against the thresholds' })}
            </p>
          ) : thresholdQ.isError || !check ? (
            <RefusalBox error={thresholdQ.error} />
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <ToneBadge tone={THRESHOLD_TONE[check.status]} testId="threshold-status">
                  {vocab(labels.t, THRESHOLD_STATUS, check.status)}
                </ToneBadge>
                {check.aggregated_value !== null && (
                  <span className="text-content-secondary">
                    {t('procurement_concept.ui.package.tested_value', { defaultValue: 'Value tested, lots added up:' })}{' '}
                    <Money value={check.aggregated_value} currency={draft.currency} />
                  </span>
                )}
                <span className="text-xs text-content-tertiary">
                  {t('procurement_concept.ui.package.checked_on', {
                    defaultValue: 'Rules as of {{date}}',
                    date: fmtDate(check.checked_on),
                  })}
                </span>
              </div>
              {check.small_lot_exempt && (
                <p className="text-xs text-content-secondary">
                  {t('procurement_concept.ui.package.small_lot_applies', {
                    defaultValue: 'The small lot exemption applies, so this lot is tested on its own value.',
                  })}
                </p>
              )}
              {check.status === 'unconfirmed' && (
                <p className="rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-xs text-content-primary" role="note">
                  {t('procurement_concept.badge.unconfirmed_banner', {
                    defaultValue: 'This threshold is not yet confirmed on its primary source. It warns, it does not block.',
                  })}
                </p>
              )}
              {check.thresholds.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm" data-testid="threshold-rows">
                    <thead className="text-xs text-content-tertiary">
                      <tr>
                        <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.package.th_threshold', { defaultValue: 'Threshold' })}</th>
                        <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.package.th_compared', { defaultValue: 'Package value compared' })}</th>
                        <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.package.th_result', { defaultValue: 'Result' })}</th>
                        <th className="py-1 font-medium">{t('procurement_concept.ui.package.th_source', { defaultValue: 'Source' })}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {check.thresholds.map((row, i) => (
                        <tr key={`${row.contract_kind}-${row.amount}-${i}`} className="border-t border-border-light">
                          <td className="py-1.5 pr-3">
                            <Money value={row.amount} currency={row.currency} />{' '}
                            <span className="text-xs text-content-tertiary">
                              {row.vat_basis === 'net'
                                ? t('procurement_concept.ui.package.vat_net', { defaultValue: 'without VAT' })
                                : t('procurement_concept.ui.package.vat_gross', { defaultValue: 'with VAT' })}
                            </span>
                          </td>
                          <td className="py-1.5 pr-3">
                            <Money value={row.compared_value} currency={row.currency} />
                          </td>
                          <td className="py-1.5 pr-3">
                            {row.position
                              ? vocab(labels.t, THRESHOLD_STATUS, row.position)
                              : vocab(labels.t, THRESHOLD_STATUS, 'unresolved')}
                          </td>
                          <td className="py-1.5">
                            {row.source_url ? (
                              <a href={row.source_url} target="_blank" rel="noreferrer noopener" className="text-oe-blue underline">
                                {row.review_status === 'verified'
                                  ? t('procurement_concept.ui.package.source_verified', { defaultValue: 'Primary source, confirmed' })
                                  : t('procurement_concept.ui.package.source_unconfirmed', { defaultValue: 'Primary source, not yet confirmed' })}
                              </a>
                            ) : (
                              <span className="text-content-tertiary">
                                {t('procurement_concept.ui.package.source_missing', { defaultValue: 'No source given' })}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <FindingList findings={check.findings} refLabel={() => ''} testId="threshold-findings" />
            </div>
          )}
        </section>

        {view.award?.procedure_code && <RuleSnapshotPanel projectId={projectId} packageId={cp.id} />}

        <section>
          <h3 className="mb-2 text-sm font-semibold text-content-primary">
            {t('procurement_concept.ui.package.procedure_title', { defaultValue: '3. How it is awarded' })}
          </h3>
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t('procurement_concept.ui.package.procedure', { defaultValue: 'Procedure' })}>
            {options.map((o) => (
              <label
                key={o.code}
                data-testid="procedure-option"
                data-allowed={o.allowed ? 'yes' : 'no'}
                className={clsx(
                  'flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-sm',
                  draft.procedure_code === o.code ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light',
                  !o.allowed && 'opacity-80',
                )}
              >
                <input
                  type="radio"
                  name="procedure"
                  className="mt-1"
                  value={o.code}
                  checked={draft.procedure_code === o.code}
                  onChange={() => set('procedure_code', o.code)}
                />
                <span>
                  <span className="font-medium text-content-primary">{catalogueName(labels, 'procedure', o)}</span>
                  {!o.allowed && o.reason && (
                    <span className="block text-xs text-semantic-error">{vocab(labels.t, PICKER_REASON, o.reason)}</span>
                  )}
                </span>
              </label>
            ))}
          </div>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <Field label={t('procurement_concept.ui.package.tender_basis', { defaultValue: 'What bidders price' })} htmlFor="pk-basis">
              <select
                id="pk-basis"
                className={FIELD_CLASS}
                value={draft.tender_basis}
                onChange={(e) => set('tender_basis', e.target.value as TenderBasis | '')}
              >
                <option value="">{t('procurement_concept.ui.not_set', { defaultValue: 'Not set' })}</option>
                {BASES.map((b) => (
                  <option key={b} value={b}>
                    {vocab(labels.t, TENDER_BASIS, b)}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={t('procurement_concept.ui.package.framework', { defaultValue: 'Call off from a framework agreement' })}
              htmlFor="pk-framework"
            >
              <select
                id="pk-framework"
                className={FIELD_CLASS}
                value={draft.framework_agreement_id}
                onChange={(e) => set('framework_agreement_id', e.target.value)}
              >
                <option value="">{t('procurement_concept.ui.package.no_framework', { defaultValue: 'No framework' })}</option>
                {usableFrameworks.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.title ? `${f.code} ${f.title}` : f.code}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={t('procurement_concept.ui.package.profile', { defaultValue: 'Prequalification profile' })}
              htmlFor="pk-profile"
            >
              <select
                id="pk-profile"
                className={FIELD_CLASS}
                value={draft.prequal_profile_id}
                onChange={(e) => set('prequal_profile_id', e.target.value)}
              >
                <option value="">{t('procurement_concept.ui.package.profile_default', { defaultValue: 'Project default' })}</option>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label={t('procurement_concept.ui.package.evaluation_method', { defaultValue: 'How the bids are compared' })}
              htmlFor="pk-evaluation"
            >
              <select
                id="pk-evaluation"
                className={FIELD_CLASS}
                value={draft.evaluation_method}
                onChange={(e) => set('evaluation_method', e.target.value as EvaluationMethod)}
              >
                {METHODS.map((m) => (
                  <option key={m} value={m}>
                    {vocab(labels.t, EVALUATION_METHOD, m)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {mustConfirmDrop && (
            <label
              className="mt-3 flex items-start gap-2 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm text-content-primary"
              data-testid="criteria-drop-confirm"
            >
              <input type="checkbox" className="mt-1" checked={dropConfirmed} onChange={(e) => setDropConfirmed(e.target.checked)} />
              {t('procurement_concept.ui.package.criteria_drop_confirm', {
                defaultValue: 'A lowest price award has no award criteria. Saving removes the criteria and weights this package holds.',
              })}
            </label>
          )}
          {draft.evaluation_method === 'best_value' && (
            <fieldset className="mt-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="award-criteria">
              <legend className="px-1 text-xs font-medium text-content-secondary">
                {t('procurement_concept.ui.package.criteria_title', { defaultValue: 'Award criteria and their weights' })}
              </legend>
              <p className="mb-2 text-xs text-content-tertiary">
                {t('procurement_concept.ui.package.criteria_hint', {
                  defaultValue: 'Name what the bids are judged on and give each a share in percent. The shares add up to 100.',
                })}
              </p>
              <ul className="space-y-2">
                {draft.weights.map((row, i) => (
                  <li key={i} className="flex items-center gap-2" data-testid="award-criterion">
                    <input
                      className={clsx(FIELD_CLASS, 'flex-1')}
                      maxLength={64}
                      aria-label={t('procurement_concept.ui.package.criterion_name', { defaultValue: 'Criterion' })}
                      placeholder={t('procurement_concept.ui.package.criterion_name', { defaultValue: 'Criterion' })}
                      value={row.name}
                      onChange={(e) => setWeight(i, { name: e.target.value })}
                    />
                    <input
                      className={clsx(FIELD_CLASS, 'w-24 text-right')}
                      inputMode="decimal"
                      aria-label={t('procurement_concept.ui.package.criterion_weight', { defaultValue: 'Weight in percent' })}
                      placeholder={t('procurement_concept.ui.package.criterion_weight', { defaultValue: 'Weight in percent' })}
                      value={row.weight}
                      onChange={(e) => setWeight(i, { weight: e.target.value })}
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      aria-label={t('procurement_concept.ui.package.criterion_remove', { defaultValue: 'Remove this criterion' })}
                      onClick={() => set('weights', draft.weights.filter((_, j) => j !== i))}
                      data-testid="award-criterion-remove"
                    >
                      {null}
                    </Button>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<Plus size={14} />}
                  disabled={draft.weights.length >= MAX_AWARD_CRITERIA}
                  onClick={() => set('weights', [...draft.weights, { name: '', weight: '' }])}
                  data-testid="award-criterion-add"
                >
                  {t('procurement_concept.ui.package.criterion_add', { defaultValue: 'Add a criterion' })}
                </Button>
                <span className="text-xs text-content-secondary" data-testid="award-criteria-total">
                  {t('procurement_concept.ui.package.criteria_total', {
                    defaultValue: 'Total: {{total}} of 100',
                    total: awardWeightsTotal(draft.weights),
                  })}
                </span>
              </div>
            </fieldset>
          )}
          <Field
            className="mt-3"
            label={t('procurement_concept.ui.package.cost_ref', { defaultValue: 'Bill of quantities section the tender is built from' })}
            htmlFor="pk-cost-ref"
            hint={
              sectionsQ.isError
                ? refusalText(labels.t, sectionsQ.error)
                : sectionsQ.isLoading
                  ? t('procurement_concept.ui.package.cost_ref_loading', { defaultValue: 'Reading the bill of quantities sections of this project' })
                  : sections.length === 0
                  ? t('procurement_concept.ui.package.cost_ref_none', {
                      defaultValue: 'This project has no bill of quantities section yet. Without one the tender starts with no scope lines.',
                    })
                  : t('procurement_concept.ui.package.cost_ref_hint', {
                      defaultValue: 'The positions under this section become the scope lines of the bid package or the request for quotation.',
                    })
            }
          >
            <select id="pk-cost-ref" className={FIELD_CLASS} aria-busy={sectionsQ.isLoading} value={draft.cost_ref_id} onChange={(e) => set('cost_ref_id', e.target.value)}>
              <option value="">{t('procurement_concept.ui.package.cost_ref_unset', { defaultValue: 'No section' })}</option>
              {draft.cost_ref_id && !sections.some((x) => x.id === draft.cost_ref_id) && (
                <option value={draft.cost_ref_id}>
                  {t('procurement_concept.ui.package.cost_ref_kept', { defaultValue: 'The section named before' })}
                </option>
              )}
              {sections.map((x) => (
                <option key={x.id} value={x.id}>
                  {t('procurement_concept.ui.package.cost_ref_option', {
                    defaultValue: '{{name}} (positions: {{n}})',
                    name: [x.boq_name, x.code, x.title].filter(Boolean).join(' / '),
                    n: x.positions,
                  })}
                </option>
              ))}
            </select>
          </Field>
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-content-primary">
            {t('procurement_concept.ui.package.timing_title', { defaultValue: '4. When the contract is needed' })}
          </h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label={t('procurement_concept.ui.package.need_date', { defaultValue: 'Needed on site by' })}
              htmlFor="pk-need"
              hint={t('procurement_concept.ui.package.need_date_hint', {
                defaultValue: 'The award schedule counts back from this date.',
              })}
            >
              <input
                id="pk-need"
                type="date"
                className={FIELD_CLASS}
                value={bound?.planned_date ?? draft.need_date}
                disabled={!!draft.need_activity_id}
                onChange={(e) => set('need_date', e.target.value)}
              />
            </Field>
            {milestones.length > 0 && (
              <Field
                label={t('procurement_concept.ui.package.need_activity', { defaultValue: 'Take the date from a schedule milestone' })}
                htmlFor="pk-need-activity"
                hint={t('procurement_concept.ui.package.need_activity_hint', {
                  defaultValue: 'The need date follows the milestone when the schedule moves.',
                })}
              >
                <select
                  id="pk-need-activity"
                  className={FIELD_CLASS}
                  value={draft.need_activity_id}
                  onChange={(e) => set('need_activity_id', e.target.value)}
                >
                  <option value="">{t('procurement_concept.ui.package.need_activity_none', { defaultValue: 'No, use the typed date' })}</option>
                  {milestones.map((m) => (
                    <option key={m.id} value={m.activity_id ?? ''}>
                      {m.name}{m.planned_date ? ` (${fmtDate(m.planned_date)})` : ''}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field
              label={t('procurement_concept.ui.package.lead_time', { defaultValue: 'Lead time after award, in days' })}
              htmlFor="pk-lead"
              hint={t('procurement_concept.ui.package.lead_time_hint', {
                defaultValue: 'Fabrication and delivery between the award and the need date.',
              })}
            >
              <input
                id="pk-lead"
                inputMode="numeric"
                className={FIELD_CLASS}
                value={draft.lead_time_days}
                onChange={(e) => set('lead_time_days', e.target.value)}
              />
            </Field>
          </div>
          {(!advanceOff || advanceLeftover) && (
          <label className="mt-3 flex items-start gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              className="mt-1"
              checked={draft.is_advance}
              onChange={(e) => set('is_advance', e.target.checked)}
              data-testid="package-advance"
            />
            <span>
              {t('procurement_concept.ui.package.advance', { defaultValue: 'Advance package' })}
              <span className="block text-xs text-content-tertiary">
                {t('procurement_concept.ui.package.advance_hint', {
                  defaultValue: 'Tendered before the main works are released, for example a long lead item.',
                })}
              </span>
            </span>
          </label>
          )}
          {advanceLeftover && draft.is_advance && (
            <p className="mt-1 text-xs text-semantic-warning" role="note" data-testid="advance-leftover">
              {errorText(labels.t, view.can.set_advance.reason ?? 'advance_not_applicable')}{' '}
              {t('procurement_concept.ui.package.advance_leftover', {
                defaultValue: 'This package still carries the mark from an earlier phase model. Clear the tick and save to remove it.',
              })}
            </p>
          )}
          {advanceFields && (
            <Field
              className="mt-2"
              label={t('procurement_concept.ui.package.advance_reason', { defaultValue: 'Why it goes ahead of the rest (required)' })}
              htmlFor="pk-advance-reason"
            >
              <textarea
                id="pk-advance-reason"
                rows={2}
                className={FIELD_CLASS}
                value={draft.advance_reason}
                onChange={(e) => set('advance_reason', e.target.value)}
              />
            </Field>
          )}
          {advanceFields && (
            <Field
              className="mt-2"
              label={t('procurement_concept.ui.package.advance_release', { defaultValue: 'What releases it' })}
              htmlFor="pk-advance-release"
              hint={
                releases.length === 0 && !releasesQ.isLoading
                  ? t('procurement_concept.ui.package.advance_release_none', {
                      defaultValue: 'Nothing can release this package yet: the release gate has no decision and no condition, and no commitment is listed. Until something releases it, it cannot go to tender early.',
                    })
                  : t('procurement_concept.ui.package.advance_release_hint', {
                      defaultValue: 'A decision of the release gate, a condition it set, or a released commitment. An open condition or a commitment not released yet can be named; the package is released once it is.',
                    })
              }
            >
              <select
                id="pk-advance-release"
                className={FIELD_CLASS}
                value={draft.advance_release}
                onChange={(e) => set('advance_release', e.target.value)}
              >
                <option value="">{t('procurement_concept.ui.package.advance_release_unset', { defaultValue: 'Not released yet' })}</option>
                {draft.advance_release && !releases.some((r) => `${r.kind}:${r.id}` === draft.advance_release) && (
                  <option value={draft.advance_release}>
                    {t('procurement_concept.ui.package.advance_release_kept', { defaultValue: 'The release named before' })}
                  </option>
                )}
                {releases.map((r) => (
                  <option key={`${r.kind}:${r.id}`} value={`${r.kind}:${r.id}`}>
                    {r.kind === 'commitment'
                      ? t('procurement_concept.ui.package.advance_release_commitment', {
                          defaultValue: 'Commitment {{label}} ({{status}})',
                          label: r.label,
                          status: r.status,
                        })
                      : r.releases
                      ? r.label
                      : t('procurement_concept.ui.package.advance_release_open', { defaultValue: '{{label}} (still open)', label: r.label })}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {advanceFields && commitmentsOff && (
            <p className="mt-1 text-xs text-content-tertiary" role="note" data-testid="commitments-unavailable">
              {errorText(labels.t, commitmentsOff)}
            </p>
          )}
          <Field className="mt-3" label={t('procurement_concept.ui.package.notes', { defaultValue: 'Notes' })} htmlFor="pk-notes">
            <textarea id="pk-notes" rows={2} className={FIELD_CLASS} value={draft.notes} onChange={(e) => set('notes', e.target.value)} />
          </Field>
        </section>
      </div>
    </WideModal>
  );
}
