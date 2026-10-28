// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The comparison of delivery forms: the forms as columns, the criteria as
// rows, a weight per criterion and a score from 1 to 5 in every cell. The
// server computes the weighted totals; the screen shows which form leads and
// what is still missing before a decision can be proposed.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Plus, Scale, Sparkles, Trash2, UserCog } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtNumber } from '@/shared/lib/formatters';

import { actionApplies, canEditComparison, canPropose } from './access';
import {
  deleteOption,
  patchWeights,
  prefillScores,
  putScores,
  type Comparison,
  type DeliveryCatalogue,
  type DeliveryModel,
  type DeliveryOption,
  type DeliveryPackage,
} from './api';
import { AddFormDialog, FormFacts, OwnerSituationDialog, ProposeDialog } from './ComparisonDialogs';
import { INPUT_CLASS, ProblemList, ReasonedButton, ReviewMark } from './DeliveryBits';
import { useRefusalToast } from './hooks';
import { catalogueSentence, catalogueText, formName, type LabelContext } from './labels';
import { fromHundredths, leadingOptionId, missingScores, scoreMap, scoreOf, sumHundredths, toHundredths, weightsProblem } from './rules';

const SCORES = [1, 2, 3, 4, 5];

export interface ComparisonPanelProps {
  projectId: string;
  model: DeliveryModel;
  comparison: Comparison;
  catalogue: DeliveryCatalogue | null;
  packages: ReadonlyArray<DeliveryPackage>;
  labels: LabelContext;
  onChanged: () => void;
}

type Dialog = 'add' | 'owner' | 'propose' | null;

export function ComparisonPanel({ projectId, model, comparison, catalogue, packages, labels, onChanged }: ComparisonPanelProps) {
  const { t } = useTranslation();
  const onError = useRefusalToast();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [removing, setRemoving] = useState<DeliveryOption | null>(null);
  const editV = canEditComparison(model);
  const proposeV = canPropose(model);
  const readOnly = !!editV;

  const serverWeights = useMemo(
    () => Object.fromEntries(comparison.criteria.map((c) => [c.code, c.weight])),
    [comparison.criteria],
  );
  const [weights, setWeights] = useState<Record<string, string>>(serverWeights);
  useEffect(() => setWeights(serverWeights), [serverWeights]);
  const weightsDirty = comparison.criteria.some((c) => (weights[c.code] ?? '') !== c.weight);
  const draftTotal = sumHundredths(Object.values(weights));
  const draftProblem = weightsProblem(weights);

  const scores = useMemo(() => scoreMap(comparison), [comparison]);
  const leading = useMemo(() => leadingOptionId(comparison.options), [comparison.options]);
  const missing = missingScores(comparison);

  const saveWeights = useMutation({ mutationFn: () => patchWeights(projectId, weights), onSuccess: onChanged, onError });
  const score = useMutation({
    mutationFn: (cell: { optionId: string; criterionCode: string; value: number }) =>
      putScores(projectId, [
        {
          option_id: cell.optionId,
          criterion_code: cell.criterionCode,
          score: cell.value,
          rationale:
            comparison.scores.find((s) => s.option_id === cell.optionId && s.criterion_code === cell.criterionCode)?.rationale ?? '',
        },
      ]),
    onSuccess: onChanged,
    onError,
  });
  const prefill = useMutation({ mutationFn: () => prefillScores(projectId), onSuccess: onChanged, onError });
  const remove = useMutation({
    mutationFn: (optionId: string) => deleteOption(projectId, optionId),
    onSuccess: () => {
      setRemoving(null);
      onChanged();
    },
    onError,
  });

  const dialogs = (
    <>
      {dialog === 'add' && (
        <AddFormDialog
          open
          onClose={() => setDialog(null)}
          projectId={projectId}
          catalogue={catalogue}
          compared={comparison.options.map((o) => o.form_code)}
          labels={labels}
          onDone={onChanged}
        />
      )}
      {dialog === 'owner' && (
        <OwnerSituationDialog open onClose={() => setDialog(null)} projectId={projectId} model={model} onDone={onChanged} />
      )}
      {dialog === 'propose' && (
        <ProposeDialog
          open
          onClose={() => setDialog(null)}
          projectId={projectId}
          comparison={comparison}
          packages={packages}
          labels={labels}
          onDone={onChanged}
        />
      )}
    </>
  );

  if (comparison.options.length === 0) {
    return (
      <div className="space-y-4" data-testid="comparison-empty">
        <EmptyState
          icon={<Scale size={28} />}
          title={t('delivery_model.ui.comparison.empty_title', { defaultValue: 'No forms to compare yet' })}
          description={t('delivery_model.ui.comparison.empty_body', {
            defaultValue:
              'Add at least two ways the project could be contracted, for example one main contractor and design and build. Then score them against each other.',
          })}
        />
        {actionApplies(model, 'edit') && (
          <div className="flex justify-center">
            <ReasonedButton verdict={editV} icon={<Plus size={14} />} onClick={() => setDialog('add')} data-testid="add-form-button">
              {t('delivery_model.ui.comparison.add_form', { defaultValue: 'Add a form' })}
            </ReasonedButton>
          </div>
        )}
        {dialogs}
      </div>
    );
  }

  const ready: string[] = [];
  if (comparison.options.length < 2) ready.push('single_option_decision');
  if (toHundredths(comparison.weights_total) !== 10000) ready.push('weights_not_100');
  if (missing > 0) ready.push('scores_incomplete');

  return (
    <div className="space-y-4" data-testid="comparison-panel">
      <div className="flex flex-wrap items-start gap-3">
        {actionApplies(model, 'propose') && (
          <ReasonedButton verdict={proposeV} icon={<Scale size={14} />} onClick={() => setDialog('propose')} data-testid="propose-button">
            {t('delivery_model.ui.comparison.propose', { defaultValue: 'Propose decision' })}
          </ReasonedButton>
        )}
        {!readOnly && (
          <>
            <Button variant="secondary" icon={<Plus size={14} />} onClick={() => setDialog('add')} data-testid="add-form-button">
              {t('delivery_model.ui.comparison.add_form', { defaultValue: 'Add a form' })}
            </Button>
            {missing > 0 && (
              <Button
                variant="secondary"
                icon={<Sparkles size={14} />}
                loading={prefill.isPending}
                onClick={() => prefill.mutate()}
                data-testid="prefill-button"
                title={t('delivery_model.ui.comparison.prefill_hint', {
                  defaultValue: 'Fills the empty cells with the usual score of each form. Change any of them afterwards.',
                })}
              >
                {t('delivery_model.ui.comparison.prefill', { defaultValue: 'Fill in usual scores' })}
              </Button>
            )}
            <Button variant="ghost" icon={<UserCog size={14} />} onClick={() => setDialog('owner')} data-testid="owner-situation-button">
              {t('delivery_model.ui.owner.title', { defaultValue: 'Owner situation' })}
            </Button>
          </>
        )}
      </div>

      {!readOnly && <ProblemList problems={ready} testId="comparison-open-points" />}

      <div className="overflow-x-auto rounded-xl border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[640px] text-sm" data-testid="comparison-table">
          <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('delivery_model.ui.comparison.criterion', { defaultValue: 'Criterion' })}
              </th>
              <th scope="col" className="w-24 px-3 py-2 font-medium">
                {t('delivery_model.ui.comparison.weight', { defaultValue: 'Weight' })}
              </th>
              {comparison.options.map((o) => (
                <th key={o.id} scope="col" className="px-3 py-2 font-medium" data-testid="option-column">
                  <span className="flex items-start justify-between gap-2">
                    <span>
                      <span className="block text-sm text-content-primary">{formName(labels, o.form, o.form_code)}</span>
                      {(o.customised ?? []).length > 0 && (
                        <span className="mr-2 text-content-tertiary" data-testid="customised-option">
                          {t('delivery_model.ui.comparison.customised', { defaultValue: 'Adjusted for this project' })}
                        </span>
                      )}
                      {o.id === leading && (
                        <span className="text-semantic-success" data-testid="leading-option">
                          {t('delivery_model.ui.comparison.leading', { defaultValue: 'Highest score' })}
                        </span>
                      )}
                      {model.selected_form_code === o.form_code && (
                        <span className="ml-2 text-oe-blue-text" data-testid="chosen-option">
                          {t('delivery_model.ui.comparison.chosen', { defaultValue: 'Chosen' })}
                        </span>
                      )}
                    </span>
                    {!readOnly && (
                      <button
                        type="button"
                        className="text-content-tertiary hover:text-semantic-error"
                        onClick={() => setRemoving(o)}
                        aria-label={t('delivery_model.ui.comparison.remove_form', {
                          defaultValue: 'Remove {{form}} from the comparison',
                          form: formName(labels, o.form, o.form_code),
                        })}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comparison.criteria.map((c) => {
              const scale = catalogueSentence(labels, c.rationale_key);
              const name = catalogueText(labels, { key: c.name_key, code: c.code });
              return (
                <tr key={c.id} className="border-t border-border-light align-top" data-testid="criterion-row">
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="block font-medium text-content-primary">{name}</span>
                    {scale && <span className="block text-xs text-content-tertiary">{scale}</span>}
                  </th>
                  <td className="px-3 py-2">
                    <input
                      className={clsx(INPUT_CLASS, 'tabular-nums')}
                      inputMode="decimal"
                      disabled={readOnly}
                      value={weights[c.code] ?? ''}
                      onChange={(e) => setWeights((w) => ({ ...w, [c.code]: e.target.value }))}
                      aria-label={t('delivery_model.ui.comparison.weight_of', { defaultValue: 'Weight of {{criterion}}', criterion: name })}
                    />
                  </td>
                  {comparison.options.map((o) => {
                    const value = scoreOf(scores, o.id, c.code);
                    return (
                      <td key={o.id} className="px-3 py-2">
                        <select
                          className={clsx(INPUT_CLASS, 'tabular-nums', value === null && 'border-semantic-warning')}
                          disabled={readOnly || score.isPending}
                          value={value ?? ''}
                          data-testid="score-cell"
                          aria-label={t('delivery_model.ui.comparison.score_of', {
                            defaultValue: 'Score of {{form}} on {{criterion}}',
                            form: formName(labels, o.form, o.form_code),
                            criterion: name,
                          })}
                          onChange={(e) => {
                            const next = Number(e.target.value);
                            if (next >= 1) score.mutate({ optionId: o.id, criterionCode: c.code, value: next });
                          }}
                        >
                          <option value="">{t('delivery_model.ui.comparison.no_score', { defaultValue: 'No score' })}</option>
                          {SCORES.map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
          <tfoot className="border-t border-border bg-surface-secondary text-sm font-semibold">
            <tr>
              <th scope="row" className="px-3 py-2 text-left">
                {t('delivery_model.ui.comparison.total', { defaultValue: 'Weighted total (1 to 5)' })}
              </th>
              <td
                className={clsx('px-3 py-2 tabular-nums', draftTotal !== 10000 && 'text-semantic-error')}
                data-testid="weights-total"
                title={t('delivery_model.ui.comparison.weights_hint', { defaultValue: 'The weights must add up to 100.' })}
              >
                {draftTotal === null ? t('delivery_model.ui.comparison.weights_invalid', { defaultValue: 'Not a number' }) : fromHundredths(draftTotal)}
              </td>
              {comparison.options.map((o) => (
                <td key={o.id} className="px-3 py-2 tabular-nums" data-testid="option-total">
                  {o.weighted_total === null ? (
                    <span className="font-normal text-content-tertiary">
                      {t('delivery_model.ui.comparison.no_total', { defaultValue: 'Not fully scored' })}
                    </span>
                  ) : (
                    fmtNumber(o.weighted_total, 2)
                  )}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>

      {weightsDirty && (
        <div className="flex flex-wrap items-center gap-3" data-testid="weights-save-bar">
          <Button size="sm" loading={saveWeights.isPending} disabled={draftProblem === 'weight_invalid'} onClick={() => saveWeights.mutate()} data-testid="weights-save">
            {t('delivery_model.ui.comparison.save_weights', { defaultValue: 'Save weights' })}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setWeights(serverWeights)}>
            {t('delivery_model.ui.comparison.reset_weights', { defaultValue: 'Undo changes' })}
          </Button>
          {draftProblem && <ProblemList problems={[draftProblem]} testId="weights-problem" />}
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('delivery_model.ui.comparison.forms_heading', { defaultValue: 'What each form means' })}
        </h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {comparison.options.map((o) => (
            <article key={o.id} className="space-y-1.5 rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="form-card">
              <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium text-content-primary">
                {formName(labels, o.form, o.form_code)}
                <ReviewMark status={o.form?.review_status} sourceUrl={o.form?.source_url} />
              </h3>
              {o.form && <FormFacts form={o.form} labels={labels} />}
              {o.notes && <p className="text-xs text-content-secondary">{o.notes}</p>}
            </article>
          ))}
        </div>
      </section>

      <ConfirmDialog
        open={!!removing}
        variant="warning"
        loading={remove.isPending}
        title={t('delivery_model.ui.comparison.remove_title', { defaultValue: 'Remove this form from the comparison?' })}
        message={t('delivery_model.ui.comparison.remove_body', {
          defaultValue: '{{form}} and its scores are removed. You can add the form again later.',
          form: removing ? formName(labels, removing.form, removing.form_code) : '',
        })}
        confirmLabel={t('delivery_model.ui.comparison.remove_confirm', { defaultValue: 'Remove form' })}
        cancelLabel={t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && remove.mutate(removing.id)}
      />
      {dialogs}
    </div>
  );
}
