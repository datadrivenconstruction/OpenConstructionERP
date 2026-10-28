// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The three dialogs of the comparison screen: adding a form to compare,
// describing the owner's own situation, and proposing the decision. A
// proposal lists what is still missing before it can be sent, and when the
// server answers that packages already in procurement are affected, it asks
// what happens to each of them.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtNumber } from '@/shared/lib/formatters';

import {
  addOption,
  deliveryViolations,
  patchModel,
  proposeDecision,
  type Comparison,
  type DeliveryCatalogue,
  type DeliveryForm,
  type DeliveryModel,
  type DeliveryPackage,
  type Disposition,
  type Finding,
  type OwnerCapability,
} from './api';
import { Field, FindingList, INPUT_CLASS, ProblemList, ReviewMark, ServerRefusal } from './DeliveryBits';
import { useRefusalText } from './hooks';
import {
  CONTRACTS_HELD,
  DESIGN_RESPONSIBILITY,
  DISPOSITION,
  PACKAGE_STATUS,
  PRICE_BASIS,
  catalogueSentence,
  formName,
  vocab,
  type KeyText,
  type LabelContext,
} from './labels';
import { leadingOptionId, proposeProblems } from './rules';

/** The facts of a form a reader compares on: who designs, who holds the contracts, how the price is set. */
export function FormFacts({ form, labels }: { form: DeliveryForm; labels: LabelContext }) {
  const { t } = useTranslation();
  const description = catalogueSentence(labels, form.description_key);
  return (
    <div className="space-y-1.5 text-xs text-content-secondary" data-testid="form-facts">
      {description && <p>{description}</p>}
      <ul className="space-y-0.5">
        <li>{vocab(labels.t, DESIGN_RESPONSIBILITY, form.design_responsibility)}</li>
        <li>{vocab(labels.t, CONTRACTS_HELD, form.owner_construction_contracts)}</li>
        {form.price_basis_at_award && (
          <li>
            {t('delivery_model.ui.form.price_at_award', {
              defaultValue: 'Price at award: {{basis}}',
              basis: vocab(labels.t, PRICE_BASIS, form.price_basis_at_award),
            })}
          </li>
        )}
      </ul>
      {form.aliases.length > 0 && (
        <div>
          <p className="font-medium text-content-primary">
            {t('delivery_model.ui.form.also_known', { defaultValue: 'Also known as' })}
          </p>
          <ul className="space-y-0.5">
            {form.aliases.map((a) => (
              <li key={`${a.country}-${a.term}`} className="flex flex-wrap items-center gap-1.5">
                {a.country && <span className="font-mono text-2xs text-content-tertiary">{a.country}</span>}
                <span>{a.term}</span>
                <ReviewMark status={a.review_status} sourceUrl={a.source_url} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export interface AddFormDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  catalogue: DeliveryCatalogue | null;
  /** Codes already in the comparison; they are not offered again. */
  compared: ReadonlyArray<string>;
  labels: LabelContext;
  onDone: () => void;
}

export function AddFormDialog({ open, onClose, projectId, catalogue, compared, labels, onDone }: AddFormDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const [code, setCode] = useState('');
  const [notes, setNotes] = useState('');
  const available = useMemo(
    () => (catalogue?.forms ?? []).filter((f) => !compared.includes(f.code)),
    [catalogue, compared],
  );
  const add = useMutation({
    mutationFn: () => addOption(projectId, { form_code: code, notes: notes.trim() }),
    onSuccess: () => {
      setCode('');
      setNotes('');
      onDone();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={add.isPending}
      testId="add-form-dialog"
      title={t('delivery_model.ui.add_form.title', { defaultValue: 'Add a form to compare' })}
      subtitle={t('delivery_model.ui.add_form.subtitle', {
        defaultValue: 'Pick a way the project could be contracted. You score it against the others afterwards.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={add.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={add.isPending} disabled={!code} onClick={() => add.mutate()} data-testid="add-form-send">
            {t('delivery_model.ui.add_form.send', { defaultValue: 'Add to comparison' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={add.isError ? refusal(add.error) : null} />
        {available.length === 0 ? (
          <p className="text-sm text-content-secondary" data-testid="no-forms-left">
            {t('delivery_model.ui.add_form.none_left', { defaultValue: 'Every form of the catalogue is already in the comparison.' })}
          </p>
        ) : (
          <div className="space-y-2" role="radiogroup">
            {available.map((f) => (
              <label
                key={f.code}
                data-testid="form-choice"
                className="flex cursor-pointer items-start gap-3 rounded-lg border border-border-light p-3 has-[:checked]:border-oe-blue has-[:checked]:bg-oe-blue-subtle"
              >
                <input type="radio" name="delivery-form" className="mt-1" checked={code === f.code} onChange={() => setCode(f.code)} />
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-content-primary">
                    {formName(labels, f, f.code)}
                    <ReviewMark status={f.review_status} sourceUrl={f.source_url} />
                  </span>
                  <FormFacts form={f} labels={labels} />
                </span>
              </label>
            ))}
          </div>
        )}
        <Field label={t('delivery_model.ui.add_form.notes', { defaultValue: 'Note (optional)' })}>
          <textarea rows={2} className={INPUT_CLASS} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </WideModal>
  );
}

type TriState = 'yes' | 'no' | 'unknown';

const TRI_STATE: Record<TriState, KeyText> = {
  yes: ['delivery_model.ui.tri.yes', 'Yes'],
  no: ['delivery_model.ui.tri.no', 'No'],
  unknown: ['delivery_model.ui.tri.unknown', 'Not known yet'],
};

const CAPABILITY_FIELDS: Record<'owner_has_design_team' | 'owner_has_cm_capacity' | 'public_client', KeyText> = {
  owner_has_design_team: ['delivery_model.ui.owner.design_team', 'The owner has its own design team'],
  owner_has_cm_capacity: ['delivery_model.ui.owner.cm_capacity', 'The owner can manage many contracts itself'],
  public_client: ['delivery_model.ui.owner.public_client', 'The owner is a public client'],
};

export const DIALOG_KEY_MAPS: Record<string, Record<string, KeyText>> = { TRI_STATE, CAPABILITY_FIELDS };

const toTri = (value: boolean | null | undefined): TriState => (value === true ? 'yes' : value === false ? 'no' : 'unknown');
const fromTri = (value: TriState): boolean | null => (value === 'yes' ? true : value === 'no' ? false : null);

export interface OwnerSituationDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  model: DeliveryModel;
  onDone: () => void;
}

/** What the owner brings to the project. It explains the choice and is kept on the decision record. */
export function OwnerSituationDialog({ open, onClose, projectId, model, onDone }: OwnerSituationDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const [draft, setDraft] = useState<OwnerCapability>(model.owner_capability ?? {});
  const [underground, setUnderground] = useState(model.underground_risk_sharing);
  const save = useMutation({
    mutationFn: () =>
      patchModel(projectId, {
        underground_risk_sharing: underground,
        owner_capability: { ...draft, funding_source: (draft.funding_source ?? '').trim() },
      }),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });
  const fields = Object.keys(CAPABILITY_FIELDS) as Array<keyof typeof CAPABILITY_FIELDS>;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="md"
      testId="owner-situation-dialog"
      title={t('delivery_model.ui.owner.title', { defaultValue: 'Owner situation' })}
      subtitle={t('delivery_model.ui.owner.subtitle', {
        defaultValue: 'What the owner can do itself. It explains the choice of form and is kept with the decision.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()} data-testid="owner-situation-send">
            {t('delivery_model.ui.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <ServerRefusal message={save.isError ? refusal(save.error) : null} />
        {fields.map((field) => (
          <Field key={field} label={t(CAPABILITY_FIELDS[field][0], { defaultValue: CAPABILITY_FIELDS[field][1] })}>
            <select
              className={INPUT_CLASS}
              value={toTri(draft[field])}
              onChange={(e) => setDraft((d) => ({ ...d, [field]: fromTri(e.target.value as TriState) }))}
            >
              {(Object.keys(TRI_STATE) as TriState[]).map((v) => (
                <option key={v} value={v}>
                  {t(TRI_STATE[v][0], { defaultValue: TRI_STATE[v][1] })}
                </option>
              ))}
            </select>
          </Field>
        ))}
        <Field label={t('delivery_model.ui.owner.funding', { defaultValue: 'How the project is funded' })}>
          <input
            className={INPUT_CLASS}
            maxLength={120}
            value={draft.funding_source ?? ''}
            onChange={(e) => setDraft((d) => ({ ...d, funding_source: e.target.value }))}
          />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={underground} onChange={(e) => setUnderground(e.target.checked)} />
          <span>
            <span className="font-medium text-content-primary">
              {t('delivery_model.ui.owner.underground', { defaultValue: 'Ground risk is shared on a baseline report' })}
            </span>
            <span className="block text-xs text-content-tertiary">
              {t('delivery_model.ui.owner.underground_hint', {
                defaultValue: 'For tunnels and deep works: the owner carries ground worse than the agreed baseline.',
              })}
            </span>
          </span>
        </label>
      </div>
    </WideModal>
  );
}

const DISPOSITIONS: Disposition[] = ['keep', 're_scope', 'cancel'];

export interface ProposeDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  comparison: Comparison;
  /** The package plan, to name the packages a change of form affects. */
  packages: ReadonlyArray<DeliveryPackage>;
  labels: LabelContext;
  onDone: () => void;
}

export function ProposeDialog({ open, onClose, projectId, comparison, packages, labels, onDone }: ProposeDialogProps) {
  const { t } = useTranslation();
  const refusal = useRefusalText();
  const leading = useMemo(() => leadingOptionId(comparison.options), [comparison.options]);
  const [optionId, setOptionId] = useState<string | null>(leading);
  const [rationale, setRationale] = useState('');
  const [tried, setTried] = useState(false);
  const [dispositions, setDispositions] = useState<Record<string, Disposition>>({});
  const [violations, setViolations] = useState<Finding[]>([]);

  const problems = proposeProblems(comparison, { optionId, rationale });
  const impacted = useMemo(() => {
    const codes = new Set(violations.filter((v) => v.code === 'disposition_missing').map((v) => v.ref));
    return packages.filter((p) => codes.has(p.code));
  }, [violations, packages]);
  const otherViolations = violations.filter((v) => v.code !== 'disposition_missing');

  const propose = useMutation({
    mutationFn: () => proposeDecision(projectId, { option_id: optionId as string, rationale: rationale.trim(), dispositions }),
    onSuccess: () => {
      setViolations([]);
      onDone();
      onClose();
    },
    onError: (err) => setViolations(deliveryViolations(err)),
  });

  const send = () => {
    setTried(true);
    if (problems.length > 0) return;
    propose.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={propose.isPending}
      testId="propose-dialog"
      title={t('delivery_model.ui.propose.title', { defaultValue: 'Propose the delivery form' })}
      subtitle={t('delivery_model.ui.propose.subtitle', {
        defaultValue: 'The proposal goes to the governance gate. It becomes binding when the gate approves it.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={propose.isPending}>
            {t('delivery_model.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={propose.isPending} onClick={send} data-testid="propose-send">
            {t('delivery_model.ui.propose.send', { defaultValue: 'Propose decision' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <ServerRefusal message={propose.isError ? refusal(propose.error) : null} />
        <FindingList findings={otherViolations} testId="propose-violations" />

        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-semibold text-content-primary">
            {t('delivery_model.ui.propose.choose', { defaultValue: 'Form to propose' })}
          </legend>
          {comparison.options.map((o) => (
            <label
              key={o.id}
              data-testid="propose-option"
              className="flex cursor-pointer items-center gap-3 rounded-lg border border-border-light p-3 text-sm has-[:checked]:border-oe-blue has-[:checked]:bg-oe-blue-subtle"
            >
              <input type="radio" name="propose-option" checked={optionId === o.id} onChange={() => setOptionId(o.id)} />
              <span className="flex-1 font-medium text-content-primary">{formName(labels, o.form, o.form_code)}</span>
              {o.id === leading && (
                <span className="text-xs text-semantic-success">
                  {t('delivery_model.ui.comparison.leading', { defaultValue: 'Highest score' })}
                </span>
              )}
              <span className="tabular-nums text-content-secondary">
                {o.weighted_total === null ? t('delivery_model.ui.comparison.no_total', { defaultValue: 'Not fully scored' }) : fmtNumber(o.weighted_total, 2)}
              </span>
            </label>
          ))}
        </fieldset>

        <Field
          label={t('delivery_model.ui.propose.rationale', { defaultValue: 'Why this form' })}
          hint={t('delivery_model.ui.propose.rationale_hint', {
            defaultValue: 'A few sentences the gate can read: what decided it and what the owner gives up.',
          })}
        >
          <textarea
            rows={4}
            className={INPUT_CLASS}
            data-testid="propose-rationale"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
        </Field>

        {impacted.length > 0 && (
          <div className="space-y-2" data-testid="propose-dispositions">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('delivery_model.ui.propose.impacted_heading', { defaultValue: 'Packages this change affects' })}
            </h3>
            <p className="text-xs text-content-secondary">
              {t('delivery_model.ui.propose.impacted_body', {
                defaultValue: 'These packages are already in procurement or awarded. Say what happens to each one.',
              })}
            </p>
            {impacted.map((p) => (
              <label key={p.id} className="flex flex-wrap items-center gap-3 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="font-mono text-xs text-content-tertiary">{p.code}</span> {p.title}
                  <span className="ml-2 text-xs text-content-tertiary">{vocab(labels.t, PACKAGE_STATUS, p.effective_status)}</span>
                </span>
                <select
                  className={`${INPUT_CLASS} w-48`}
                  value={dispositions[p.id] ?? ''}
                  aria-label={t('delivery_model.ui.propose.disposition_for', {
                    defaultValue: 'What happens to {{name}}',
                    name: p.title,
                  })}
                  onChange={(e) =>
                    setDispositions((d) => {
                      const next = { ...d };
                      if (e.target.value) next[p.id] = e.target.value as Disposition;
                      else delete next[p.id];
                      return next;
                    })
                  }
                >
                  <option value="">{t('delivery_model.ui.choose', { defaultValue: 'Choose' })}</option>
                  {DISPOSITIONS.map((d) => (
                    <option key={d} value={d}>
                      {vocab(labels.t, DISPOSITION, d)}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        )}

        {tried && <ProblemList problems={problems} testId="propose-problems" />}
      </div>
    </WideModal>
  );
}
