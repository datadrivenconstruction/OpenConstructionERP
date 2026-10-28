// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Writing the decision paper of a plant item: the question, the options side
// by side, what they are judged on and how much each point weighs, then the
// recommendation and its reason. The server works out the weighted score; the
// paper is approved only through the project's approval route.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';

import { createPaper, updatePaper, type Paper, type PlantItem } from './api';
import { DialogFooter, Field, Refusal, fieldClass } from './PlantBits';
import { paperProblems, toPaperInput, type CriterionDraft, type OptionDraft, type PaperDraft } from './rules';

let rowSeq = 0;
function rowId(prefix: string): string {
  rowSeq += 1;
  return `${prefix}${rowSeq}`;
}

function newOption(code: string): OptionDraft {
  return { rowId: rowId('o'), code, title: '', lead_weeks: '', cost: '', currency: '', scores: {} };
}

function newCriterion(): CriterionDraft {
  return { rowId: rowId('c'), code: '', title: '', weight: '1' };
}

function draftOf(paper: Paper | null): PaperDraft {
  if (!paper) {
    return { question: '', options: [newOption('a'), newOption('b')], criteria: [newCriterion()], recommendation: '', rationale: '' };
  }
  const criteria = paper.criteria.map((c) => ({ rowId: rowId('c'), code: c.code, title: c.title, weight: String(c.weight) }));
  const options = paper.options.map((o) => {
    const scores: Record<string, string> = {};
    for (const c of criteria) {
      const value = o.scores?.[c.code];
      if (value !== undefined && value !== null) scores[c.rowId] = String(value);
    }
    return {
      rowId: rowId('o'),
      code: o.code,
      title: o.title,
      lead_weeks: o.lead_weeks === null || o.lead_weeks === undefined ? '' : String(o.lead_weeks),
      cost: o.cost === null || o.cost === undefined ? '' : String(o.cost),
      currency: o.currency ?? '',
      scores,
      keep: {
        ...(o.vendor_id ? { vendor_id: o.vendor_id } : {}),
        ...(o.quote_id ? { quote_id: o.quote_id } : {}),
        ...(o.risk_ref ? { risk_ref: o.risk_ref } : {}),
      },
    };
  });
  return {
    question: paper.question,
    options,
    criteria,
    recommendation: options.find((o) => o.code === paper.recommendation)?.rowId ?? '',
    rationale: paper.rationale,
  };
}

export interface PaperDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  item: PlantItem;
  /** The draft paper to edit, or null to write a new one. */
  paper: Paper | null;
  onSaved: () => void;
}

export function PaperDialog({ open, onClose, projectId, item, paper, onSaved }: PaperDialogProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<PaperDraft>(() => draftOf(paper));
  const [tried, setTried] = useState(false);
  const problems = paperProblems(draft);
  const save = useMutation({
    mutationFn: () =>
      paper
        ? updatePaper(projectId, item.id, paper.id, toPaperInput(draft))
        : createPaper(projectId, item.id, toPaperInput(draft)),
    onSuccess: onSaved,
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };
  const patchOption = (id: string, patch: Partial<OptionDraft>) =>
    setDraft((d) => ({ ...d, options: d.options.map((o) => (o.rowId === id ? { ...o, ...patch } : o)) }));
  const patchCriterion = (id: string, patch: Partial<CriterionDraft>) =>
    setDraft((d) => ({ ...d, criteria: d.criteria.map((c) => (c.rowId === id ? { ...c, ...patch } : c)) }));

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="2xl"
      testId="plant-paper-dialog"
      title={t('plant.paper.dialog_title', { defaultValue: 'Decision paper for {{code}}', code: item.code })}
      subtitle={t('plant.paper.dialog_subtitle', {
        defaultValue:
          'Compare at least two options, say which one you recommend and why. It stays a draft until you submit it for approval.',
      })}
      footer={
        <DialogFooter
          problems={problems}
          showProblems={tried}
          busy={save.isPending}
          submitLabel={t('plant.paper.save_draft', { defaultValue: 'Save draft' })}
          onCancel={onClose}
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-5">
        <Refusal error={save.error} />

        <Field label={t('plant.paper.question', { defaultValue: 'What has to be decided' })} required>
          {(id) => (
            <textarea
              id={id}
              rows={2}
              className={fieldClass}
              value={draft.question}
              onChange={(e) => setDraft((d) => ({ ...d, question: e.target.value }))}
            />
          )}
        </Field>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('plant.paper.criteria', { defaultValue: 'What the options are judged on' })}
            </h3>
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus size={14} />}
              onClick={() => setDraft((d) => ({ ...d, criteria: [...d.criteria, newCriterion()] }))}
            >
              {t('plant.paper.add_criterion', { defaultValue: 'Add criterion' })}
            </Button>
          </div>
          {draft.criteria.map((c, index) => (
            <div key={c.rowId} className="grid gap-2 sm:grid-cols-[minmax(0,3fr)_minmax(0,1fr)_auto]" data-testid="criterion-row">
              <input
                aria-label={t('plant.paper.criterion_n', { defaultValue: 'Criterion {{n}}', n: index + 1 })}
                placeholder={t('plant.paper.criterion_placeholder', { defaultValue: 'For example lead time, cost, local service' })}
                className={fieldClass}
                value={c.title}
                onChange={(e) => patchCriterion(c.rowId, { title: e.target.value })}
              />
              <input
                aria-label={t('plant.paper.weight_n', { defaultValue: 'Weight of criterion {{n}}', n: index + 1 })}
                placeholder={t('plant.paper.weight', { defaultValue: 'Weight' })}
                inputMode="decimal"
                className={fieldClass}
                value={c.weight}
                onChange={(e) => patchCriterion(c.rowId, { weight: e.target.value })}
              />
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 size={14} />}
                aria-label={t('plant.paper.remove_criterion', { defaultValue: 'Remove criterion {{n}}', n: index + 1 })}
                onClick={() => setDraft((d) => ({ ...d, criteria: d.criteria.filter((x) => x.rowId !== c.rowId) }))}
              />
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-content-primary">{t('plant.paper.options', { defaultValue: 'Options' })}</h3>
            <Button
              size="sm"
              variant="secondary"
              icon={<Plus size={14} />}
              onClick={() =>
                setDraft((d) => ({ ...d, options: [...d.options, newOption(String.fromCharCode(97 + (d.options.length % 26)))] }))
              }
            >
              {t('plant.paper.add_option', { defaultValue: 'Add option' })}
            </Button>
          </div>
          {draft.options.map((o, index) => (
            <div key={o.rowId} className="space-y-2 rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="option-row">
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,4fr)_minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)_auto]">
                <input
                  aria-label={t('plant.paper.option_code_n', { defaultValue: 'Code of option {{n}}', n: index + 1 })}
                  placeholder={t('plant.field.code', { defaultValue: 'Code' })}
                  className={fieldClass}
                  value={o.code}
                  onChange={(e) => patchOption(o.rowId, { code: e.target.value })}
                />
                <input
                  aria-label={t('plant.paper.option_title_n', { defaultValue: 'Title of option {{n}}', n: index + 1 })}
                  placeholder={t('plant.paper.option_title', { defaultValue: 'What this option is' })}
                  className={fieldClass}
                  value={o.title}
                  onChange={(e) => patchOption(o.rowId, { title: e.target.value })}
                />
                <input
                  aria-label={t('plant.paper.option_weeks_n', { defaultValue: 'Lead time of option {{n}} in weeks', n: index + 1 })}
                  placeholder={t('plant.field.lead_weeks', { defaultValue: 'Lead time (weeks)' })}
                  inputMode="numeric"
                  className={fieldClass}
                  value={o.lead_weeks}
                  onChange={(e) => patchOption(o.rowId, { lead_weeks: e.target.value })}
                />
                <input
                  aria-label={t('plant.paper.option_cost_n', { defaultValue: 'Cost of option {{n}}', n: index + 1 })}
                  placeholder={t('plant.paper.cost', { defaultValue: 'Cost' })}
                  inputMode="decimal"
                  className={fieldClass}
                  value={o.cost}
                  onChange={(e) => patchOption(o.rowId, { cost: e.target.value })}
                />
                <input
                  aria-label={t('plant.paper.option_currency_n', { defaultValue: 'Currency of option {{n}}', n: index + 1 })}
                  placeholder="EUR"
                  maxLength={3}
                  className={fieldClass}
                  value={o.currency}
                  onChange={(e) => patchOption(o.rowId, { currency: e.target.value.toUpperCase() })}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 size={14} />}
                  aria-label={t('plant.paper.remove_option', { defaultValue: 'Remove option {{n}}', n: index + 1 })}
                  onClick={() =>
                    setDraft((d) => ({
                      ...d,
                      options: d.options.filter((x) => x.rowId !== o.rowId),
                      recommendation: d.recommendation === o.rowId ? '' : d.recommendation,
                    }))
                  }
                />
              </div>
              {draft.criteria.some((c) => c.title.trim()) && (
                <div className="flex flex-wrap gap-2">
                  {draft.criteria
                    .filter((c) => c.title.trim())
                    .map((c) => (
                      <label key={c.rowId} className="flex items-center gap-1.5 text-xs text-content-secondary">
                        {c.title}
                        <input
                          inputMode="decimal"
                          className={`${fieldClass} w-20`}
                          value={o.scores[c.rowId] ?? ''}
                          onChange={(e) => patchOption(o.rowId, { scores: { ...o.scores, [c.rowId]: e.target.value } })}
                        />
                      </label>
                    ))}
                </div>
              )}
              <label className="flex items-center gap-2 text-sm text-content-primary">
                <input
                  type="radio"
                  name="plant-paper-recommendation"
                  checked={draft.recommendation === o.rowId}
                  onChange={() => setDraft((d) => ({ ...d, recommendation: o.rowId }))}
                />
                {t('plant.paper.recommend_this', { defaultValue: 'Recommend this option' })}
              </label>
            </div>
          ))}
        </div>

        <Field label={t('plant.paper.rationale', { defaultValue: 'Why this option' })}>
          {(id) => (
            <textarea
              id={id}
              rows={3}
              className={fieldClass}
              value={draft.rationale}
              onChange={(e) => setDraft((d) => ({ ...d, rationale: e.target.value }))}
            />
          )}
        </Field>
      </div>
    </WideModal>
  );
}
