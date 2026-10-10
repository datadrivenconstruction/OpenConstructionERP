// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// HakedisTaxes - where the three taxes of a payment certificate that a person
// decides are decided: the VAT withholding, the income tax withholding and the
// stamp duty.
//
// Nothing is chosen for the reader. A tax starts undecided and stays held
// until a person either picks its category or states that it does not apply,
// with the reason. Where the contract names a default it is shown as a
// suggestion that takes one explicit click, never as a selection.
//
// Before anything is saved the server is asked what the figures would be for
// the choices on screen, and that answer is shown beside each tax. No amount
// is worked out here.
//
// Two different "confirmed" appear on this block and are kept apart on
// purpose: a person CONFIRMS the stored taxes of this document, and each rate
// row is separately marked as checked against its primary source or not.

import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, CheckCircle2, RefreshCw, RotateCcw } from 'lucide-react';

import { Badge, Button } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { ROLE_RANK } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  FIGURE_OF_CHOICE,
  HAKEDIS_TAX_CHOICE_KINDS,
  clearStatutoryTaxOverride,
  confirmStatutoryTaxes,
  getStatutoryTaxes,
  listStatutoryCategories,
  overrideStatutoryTax,
  previewStatutoryTaxes,
  putHakedisTaxes,
  reopenStatutoryTaxes,
  type HakedisChoiceState,
  type HakedisTaxCategory,
  type HakedisTaxChoice,
  type HakedisTaxChoiceKind,
  type HakedisTaxesInput,
  type StatutoryCategory,
  type StatutoryFigure,
  type StatutoryInputs,
} from './api';
import { hakedisBaseKey, hakedisStatutoryKey, readRefusal, type HakedisRefusal } from './hakedisQueries';
import {
  BlockTitle,
  RefusalNote,
  inputCls,
  rankOf,
  taxAnchor,
  textareaCls,
  type HakedisBlockProps,
} from './hakedisParts';
import { RateReviewBadge } from './HakedisSummaryTable';
import { rateText, reasonSentence, type ReasonContext } from './hakedisText';

const UNSET: HakedisTaxChoice = { state: 'unset', code: '', reason: '' };

type Drafts = Record<HakedisTaxChoiceKind, HakedisTaxChoice>;

function choiceIsComplete(choice: HakedisTaxChoice): boolean {
  if (choice.state === 'selected') return choice.code !== '';
  if (choice.state === 'not_applicable') return choice.reason.trim() !== '';
  return true;
}

function sameChoice(a: HakedisTaxChoice, b: HakedisTaxChoice): boolean {
  return a.state === b.state && a.code === b.code && a.reason.trim() === b.reason.trim();
}

function trimmed(choice: HakedisTaxChoice): HakedisTaxChoice {
  return { state: choice.state, code: choice.code, reason: choice.reason.trim() };
}

export function HakedisTaxes({ source, doc, locale, numberLocale, canEdit, onUpdated }: HakedisBlockProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const formId = useId();
  const taxes = doc.taxes;
  const role = useAuthStore((s) => s.userRole);
  const userId = useAuthStore((s) => s.userId);
  const mayConfirm = rankOf(role) >= ROLE_RANK.manager;
  const confirmed = taxes.status === 'confirmed';
  // A confirmed set is frozen: the server refuses a new choice until it is reopened.
  const mayChoose = canEdit && taxes.available && !confirmed;

  const storedChoice = (kind: HakedisTaxChoiceKind): HakedisTaxChoice =>
    taxes.stored ? (taxes.choices[kind] ?? UNSET) : UNSET;
  const [drafts, setDrafts] = useState<Drafts>(() => ({
    vat_withholding: storedChoice('vat_withholding'),
    income_withholding: storedChoice('income_withholding'),
    stamp_duty: storedChoice('stamp_duty'),
  }));
  const [buyerDesignated, setBuyerDesignated] = useState<boolean | null>(taxes.buyer_is_designated);
  const [workValue, setWorkValue] = useState(taxes.work_value_incl_vat ?? '');
  const [workValueNote, setWorkValueNote] = useState(taxes.work_value_note);
  const [refusal, setRefusal] = useState<HakedisRefusal | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [reopenReason, setReopenReason] = useState('');

  const context = useMemo<ReasonContext>(
    () => ({ currency: doc.currency, locale: numberLocale }),
    [doc.currency, numberLocale],
  );

  const setDraft = (kind: HakedisTaxChoiceKind, choice: HakedisTaxChoice) =>
    setDrafts((current) => ({ ...current, [kind]: choice }));

  const workValuePayload = workValue.trim() === '' ? null : toDecimalPayloadString(workValue, '');
  const factsChanged =
    buyerDesignated !== taxes.buyer_is_designated ||
    workValuePayload !== (taxes.work_value_incl_vat ?? null) ||
    workValueNote.trim() !== taxes.work_value_note;
  const choicesChanged = HAKEDIS_TAX_CHOICE_KINDS.some((kind) => !sameChoice(drafts[kind], storedChoice(kind)));
  const complete = HAKEDIS_TAX_CHOICE_KINDS.every((kind) => choiceIsComplete(drafts[kind]));
  const dirty = choicesChanged || factsChanged;

  // The inputs of a preview are the certificate's own amounts, as the server
  // states them, with the choices on screen. Both stamp duty spellings are
  // never sent together.
  const previewInputs: StatutoryInputs | null =
    mayChoose && dirty && complete && taxes.document_date && taxes.expected_net_amount && doc.country_code
      ? {
          country_code: doc.country_code,
          currency_code: doc.currency,
          document_date: taxes.document_date,
          net_amount: taxes.expected_net_amount,
          vat_rate_pct: taxes.vat_rate_pct,
          buyer_is_designated: buyerDesignated,
          work_value_incl_vat: workValuePayload,
          work_value_note: workValueNote.trim(),
          stamp_duty_base: taxes.expected_stamp_duty_base,
          stamp_duty_base_same_as_net: false,
          vat_withholding: trimmed(drafts.vat_withholding),
          income_withholding: trimmed(drafts.income_withholding),
          stamp_duty: trimmed(drafts.stamp_duty),
        }
      : null;
  const previewQ = useQuery({
    queryKey: ['hakedis', 'tax-preview', source.kind, source.id, previewInputs],
    queryFn: () => {
      if (!previewInputs) throw new Error('preview without inputs');
      return previewStatutoryTaxes(previewInputs);
    },
    enabled: previewInputs !== null,
    retry: false,
    staleTime: 60_000,
  });
  const preview = previewInputs !== null ? previewQ.data : undefined;

  // The stored set, read from the tax module for what the certificate does not
  // carry: who entered an amount by hand, when and why.
  const calcQ = useQuery({
    queryKey: [...hakedisStatutoryKey(source), doc.project_id],
    queryFn: () => getStatutoryTaxes(source, doc.project_id),
    enabled: taxes.available && taxes.stored,
    retry: false,
  });
  const calc = calcQ.data;

  // The dates the categories are in force from live in the tax module's list.
  const categoriesQ = useQuery({
    queryKey: ['hakedis', 'tax-categories', doc.country_code, taxes.document_date],
    queryFn: () => listStatutoryCategories(doc.country_code, taxes.document_date ?? ''),
    enabled: mayChoose && doc.country_code !== '' && !!taxes.document_date,
    retry: false,
    staleTime: 10 * 60_000,
  });
  const categoryFacts = useMemo(() => {
    const map = new Map<string, StatutoryCategory>();
    for (const item of categoriesQ.data?.items ?? []) map.set(`${item.kind}|${item.code}`, item);
    return map;
  }, [categoriesQ.data]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: hakedisBaseKey(source) });
    void qc.invalidateQueries({ queryKey: hakedisStatutoryKey(source) });
  };

  const saveMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: (body: HakedisTaxesInput) => putHakedisTaxes(source, body, locale),
    onSuccess: (next) => {
      setRefusal(null);
      onUpdated(next);
      void qc.invalidateQueries({ queryKey: hakedisStatutoryKey(source) });
    },
    onError: (err) => setRefusal(readRefusal(err)),
  });
  const confirmMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () =>
      confirmStatutoryTaxes(source, { project_id: doc.project_id, acknowledge_unconfirmed_rates: acknowledged }),
    onSuccess: () => {
      setRefusal(null);
      setAcknowledged(false);
      refresh();
    },
    onError: (err) => setRefusal(readRefusal(err)),
  });
  const reopenMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => reopenStatutoryTaxes(source, { project_id: doc.project_id, reason: reopenReason.trim() }),
    onSuccess: () => {
      setRefusal(null);
      setReopenReason('');
      refresh();
    },
    onError: (err) => setRefusal(readRefusal(err)),
  });

  const save = () => {
    saveMut.mutate({
      vat_withholding: trimmed(drafts.vat_withholding),
      income_withholding: trimmed(drafts.income_withholding),
      stamp_duty: trimmed(drafts.stamp_duty),
      buyer_is_designated: buyerDesignated,
      work_value_incl_vat: workValuePayload,
      work_value_note: workValueNote.trim(),
    });
  };

  if (!taxes.available) {
    return (
      <section aria-labelledby={`${formId}-title`} data-testid="hakedis-taxes">
        <div id={`${formId}-title`}>
          <BlockTitle>{t('hakedis.taxes.title', { defaultValue: 'Withholdings and stamp duty' })}</BlockTitle>
        </div>
        <p className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-content-primary dark:border-amber-900 dark:bg-amber-950/30">
          {t('hakedis.taxes.module_absent', {
            defaultValue:
              'The tax module is not installed, so the tax lines of this certificate stay held. Install it to decide them.',
          })}
        </p>
      </section>
    );
  }

  const usesUnconfirmedRates = calc?.uses_unconfirmed_rates === true;
  const draftStored = taxes.stored && taxes.status === 'draft';

  return (
    <section aria-labelledby={`${formId}-title`} className="space-y-3" data-testid="hakedis-taxes">
      <div className="flex flex-wrap items-center gap-2">
        <div id={`${formId}-title`}>
          <BlockTitle>{t('hakedis.taxes.title', { defaultValue: 'Withholdings and stamp duty' })}</BlockTitle>
        </div>
        <span className="mb-2" data-testid="hakedis-taxes-status">
          {confirmed ? (
            <Badge variant="success" size="sm" dot>
              {t('hakedis.taxes.status.confirmed', { defaultValue: 'Taxes confirmed' })}
            </Badge>
          ) : taxes.stored && taxes.status === 'draft' ? (
            <Badge variant="blue" size="sm" dot>
              {t('hakedis.taxes.status.draft', { defaultValue: 'Taxes saved, not confirmed' })}
            </Badge>
          ) : (
            <Badge variant="warning" size="sm" dot>
              {t('hakedis.taxes.status.none', { defaultValue: 'Taxes not decided' })}
            </Badge>
          )}
        </span>
      </div>

      {taxes.stale && (
        <div
          role="alert"
          className="flex flex-wrap items-start gap-3 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 dark:border-amber-900 dark:bg-amber-950/30"
          data-testid="hakedis-taxes-stale"
        >
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden="true" />
          <p className="min-w-0 flex-1 break-words text-sm text-content-primary">
            {confirmed
              ? t('hakedis.taxes.stale_confirmed', {
                  defaultValue:
                    'The certificate changed after its taxes were confirmed. Reopen the taxes, then recalculate them.',
                })
              : t('hakedis.taxes.stale', {
                  defaultValue:
                    'The certificate changed after its taxes were calculated. Recalculate them on the current amounts.',
                })}
          </p>
          {canEdit && !confirmed && (
            <Button
              size="sm"
              icon={<RefreshCw size={13} />}
              loading={saveMut.isPending}
              onClick={() => saveMut.mutate({})}
              data-testid="hakedis-taxes-recalculate"
            >
              {t('hakedis.taxes.recalculate', { defaultValue: 'Recalculate' })}
            </Button>
          )}
        </div>
      )}

      {refusal && <RefusalNote t={t} refusal={refusal} testId="hakedis-taxes-refusal" />}

      {mayChoose && (
        <fieldset className="rounded-lg border border-border-light px-3 py-3">
          <legend className="px-1 text-xs font-medium text-content-secondary">
            {t('hakedis.taxes.buyer_facts', { defaultValue: 'Facts the VAT withholding depends on' })}
          </legend>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="block">
              <span className="block text-xs text-content-tertiary">
                {t('hakedis.taxes.buyer_designated', { defaultValue: 'Is the buyer a designated withholding agent?' })}
              </span>
              <select
                value={buyerDesignated === null ? '' : buyerDesignated ? 'yes' : 'no'}
                onChange={(e) => setBuyerDesignated(e.target.value === '' ? null : e.target.value === 'yes')}
                className={clsx(inputCls, 'mt-0.5')}
                data-testid="hakedis-taxes-buyer"
              >
                <option value="">{t('hakedis.taxes.buyer_unknown', { defaultValue: 'Not stated' })}</option>
                <option value="yes">{t('hakedis.taxes.buyer_yes', { defaultValue: 'Yes' })}</option>
                <option value="no">{t('hakedis.taxes.buyer_no', { defaultValue: 'No' })}</option>
              </select>
            </label>
            <label className="block">
              <span className="block text-xs text-content-tertiary">
                {t('hakedis.taxes.work_value', { defaultValue: 'Value of the whole work including VAT' })}
              </span>
              <input
                type="text"
                inputMode="decimal"
                autoComplete="off"
                value={workValue}
                onChange={(e) => setWorkValue(e.target.value)}
                className={clsx(inputCls, 'mt-0.5 text-right tabular-nums')}
                data-testid="hakedis-taxes-work-value"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-content-tertiary">
                {t('hakedis.taxes.work_value_note', { defaultValue: 'Where that value comes from' })}
              </span>
              <input
                type="text"
                value={workValueNote}
                maxLength={500}
                onChange={(e) => setWorkValueNote(e.target.value)}
                className={clsx(inputCls, 'mt-0.5')}
              />
            </label>
          </div>
        </fieldset>
      )}

      <div className="grid gap-3 xl:grid-cols-3">
        {HAKEDIS_TAX_CHOICE_KINDS.map((kind) => {
          const figureKind = FIGURE_OF_CHOICE[kind];
          return (
            <TaxCard
              key={kind}
              anchor={taxAnchor(source, kind)}
              kind={kind}
              categories={taxes.categories[kind] ?? []}
              categoryFacts={categoryFacts}
              draft={drafts[kind]}
              stored={taxes.stored}
              suggestion={taxes.stored ? undefined : taxes.choices[kind]}
              storedChoice={storedChoice(kind)}
              mayChoose={mayChoose}
              onChange={(choice) => setDraft(kind, choice)}
              previewFigure={preview?.figures.find((figure) => figure.kind === figureKind)}
              previewPending={previewInputs !== null && previewQ.isFetching}
              storedFigure={calc?.figures.find((figure) => figure.kind === figureKind)}
              mayOverride={canEdit && draftStored && !taxes.stale && !dirty}
              currency={doc.currency}
              numberLocale={numberLocale}
              context={context}
              userId={userId}
              onOverride={(amount, reason) =>
                overrideStatutoryTax(source, { project_id: doc.project_id, kind: figureKind, amount, reason })
              }
              onClearOverride={() => clearStatutoryTaxOverride(source, figureKind, doc.project_id)}
              onChanged={refresh}
            />
          );
        })}
      </div>

      {previewInputs !== null && previewQ.isError && (
        <RefusalNote t={t} refusal={readRefusal(previewQ.error)} testId="hakedis-taxes-preview-error" />
      )}

      {mayChoose && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {!complete && (
            <p className="mr-auto text-xs text-amber-800 dark:text-amber-300">
              {t('hakedis.taxes.incomplete', {
                defaultValue: 'A tax marked as not applicable needs its reason before the choices can be saved.',
              })}
            </p>
          )}
          <Button
            size="sm"
            loading={saveMut.isPending}
            disabled={!dirty || !complete}
            onClick={save}
            data-testid="hakedis-taxes-save"
          >
            {t('hakedis.taxes.save', { defaultValue: 'Save the tax choices' })}
          </Button>
        </div>
      )}

      {draftStored && !taxes.stale && !dirty && (
        <div className="rounded-lg border border-border-light px-3 py-3" data-testid="hakedis-taxes-confirm">
          {mayConfirm ? (
            <div className="space-y-2">
              {usesUnconfirmedRates && (
                <label className="flex items-start gap-2 text-sm text-content-primary">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={acknowledged}
                    onChange={(e) => setAcknowledged(e.target.checked)}
                    data-testid="hakedis-taxes-acknowledge"
                  />
                  <span className="min-w-0 break-words">
                    {t('hakedis.taxes.acknowledge_unconfirmed', {
                      defaultValue:
                        'I know that at least one rate used here has not been checked against its primary source, and I confirm the figures anyway.',
                    })}
                  </span>
                </label>
              )}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="min-w-0 flex-1 break-words text-xs text-content-secondary">
                  {t('hakedis.taxes.confirm_hint', {
                    defaultValue:
                      'Confirming freezes the tax figures of this certificate. They can be reopened with a reason.',
                  })}
                </p>
                <Button
                  size="sm"
                  icon={<CheckCircle2 size={13} />}
                  loading={confirmMut.isPending}
                  disabled={usesUnconfirmedRates && !acknowledged}
                  onClick={() => confirmMut.mutate()}
                  data-testid="hakedis-taxes-confirm-button"
                >
                  {t('hakedis.taxes.confirm', { defaultValue: 'Confirm the taxes' })}
                </Button>
              </div>
            </div>
          ) : (
            <p className="break-words text-sm text-content-secondary">
              {t('hakedis.taxes.confirm_needs_manager', {
                defaultValue: 'The taxes are saved. A manager has to confirm them before the certificate can be certified.',
              })}
            </p>
          )}
        </div>
      )}

      {confirmed && doc.editable && mayConfirm && (
        <form
          className="rounded-lg border border-border-light px-3 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (reopenReason.trim() !== '') reopenMut.mutate();
          }}
          data-testid="hakedis-taxes-reopen"
        >
          <label className="block">
            <span className="block text-xs text-content-tertiary">
              {t('hakedis.taxes.reopen_reason', { defaultValue: 'Why the confirmed taxes are reopened' })}
            </span>
            <textarea
              rows={2}
              maxLength={2000}
              value={reopenReason}
              onChange={(e) => setReopenReason(e.target.value)}
              className={clsx(textareaCls, 'mt-0.5')}
              data-testid="hakedis-taxes-reopen-reason"
            />
          </label>
          <div className="mt-2 flex justify-end">
            <Button
              type="submit"
              variant="secondary"
              size="sm"
              icon={<RotateCcw size={13} />}
              loading={reopenMut.isPending}
              disabled={reopenReason.trim() === ''}
              data-testid="hakedis-taxes-reopen-button"
            >
              {t('hakedis.taxes.reopen', { defaultValue: 'Reopen the taxes' })}
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}

function kindTitle(t: ReturnType<typeof useTranslation>['t'], kind: HakedisTaxChoiceKind): string {
  switch (kind) {
    case 'vat_withholding':
      return t('hakedis.taxes.kind.vat_withholding', { defaultValue: 'VAT withholding' });
    case 'income_withholding':
      return t('hakedis.taxes.kind.income_withholding', { defaultValue: 'Income tax withholding' });
    default:
      return t('hakedis.taxes.kind.stamp_duty', { defaultValue: 'Stamp duty' });
  }
}

function buyerScopeText(t: ReturnType<typeof useTranslation>['t'], scope: string): string {
  switch (scope) {
    case 'any':
      return t('hakedis.taxes.scope.any', { defaultValue: 'Any buyer withholds' });
    case 'designated_only':
      return t('hakedis.taxes.scope.designated_only', { defaultValue: 'Only a designated buyer withholds' });
    case 'designated_or_work_value':
      return t('hakedis.taxes.scope.designated_or_work_value', {
        defaultValue: 'A designated buyer withholds, or any buyer once the work value passes the threshold',
      });
    default:
      return '';
  }
}

interface TaxCardProps {
  anchor: string;
  kind: HakedisTaxChoiceKind;
  categories: HakedisTaxCategory[];
  categoryFacts: ReadonlyMap<string, StatutoryCategory>;
  draft: HakedisTaxChoice;
  stored: boolean;
  /** The contract's default, offered while nothing is stored. */
  suggestion: HakedisTaxChoice | undefined;
  storedChoice: HakedisTaxChoice;
  mayChoose: boolean;
  onChange: (choice: HakedisTaxChoice) => void;
  previewFigure: StatutoryFigure | undefined;
  previewPending: boolean;
  storedFigure: StatutoryFigure | undefined;
  mayOverride: boolean;
  currency: string;
  numberLocale: string;
  context: ReasonContext;
  userId: string | null;
  onOverride: (amount: string, reason: string) => Promise<unknown>;
  onClearOverride: () => Promise<unknown>;
  onChanged: () => void;
}

function TaxCard({
  anchor,
  kind,
  categories,
  categoryFacts,
  draft,
  stored,
  suggestion,
  storedChoice,
  mayChoose,
  onChange,
  previewFigure,
  previewPending,
  storedFigure,
  mayOverride,
  currency,
  numberLocale,
  context,
  userId,
  onOverride,
  onClearOverride,
  onChanged,
}: TaxCardProps) {
  const { t } = useTranslation();
  const groupId = useId();
  const title = kindTitle(t, kind);
  const setState = (state: HakedisChoiceState, code = '') =>
    onChange({ state, code, reason: state === 'not_applicable' ? draft.reason : '' });
  const hasSuggestion = suggestion !== undefined && suggestion.state !== 'unset';
  const suggested = hasSuggestion && suggestion ? suggestion : null;
  const suggestedCategory = suggested ? categories.find((category) => category.code === suggested.code) : undefined;

  return (
    <section
      id={anchor}
      tabIndex={-1}
      aria-labelledby={`${groupId}-title`}
      className="flex min-w-0 flex-col gap-2 rounded-lg border border-border-light px-3 py-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
      data-testid={`hakedis-tax-${kind}`}
    >
      <h4 id={`${groupId}-title`} className="break-words text-sm font-semibold text-content-primary">
        {title}
      </h4>

      {!mayChoose && (
        <p className="break-words text-sm text-content-secondary" data-testid={`hakedis-tax-stored-${kind}`}>
          {storedChoice.state === 'selected'
            ? t('hakedis.taxes.stored_selected', { defaultValue: 'Category {{code}}', code: storedChoice.code })
            : storedChoice.state === 'not_applicable'
              ? t('hakedis.taxes.stored_not_applicable', {
                  defaultValue: 'Does not apply: {{reason}}',
                  reason: storedChoice.reason,
                })
              : t('hakedis.taxes.unset', { defaultValue: 'Not decided yet' })}
        </p>
      )}

      {mayChoose && suggested && (
        <div
          className="rounded-md border border-dashed border-border px-2 py-1.5 text-xs text-content-secondary"
          data-testid={`hakedis-tax-suggestion-${kind}`}
        >
          <p className="break-words">
            {suggested.state === 'selected'
              ? t('hakedis.taxes.suggestion_selected', {
                  defaultValue: 'The contract suggests category {{code}}. It is not saved for this certificate.',
                  code: suggestedCategory ? `${suggested.code} ${suggestedCategory.label}` : suggested.code,
                })
              : t('hakedis.taxes.suggestion_not_applicable', {
                  defaultValue:
                    'The contract states this tax does not apply: {{reason}}. It is not saved for this certificate.',
                  reason: suggested.reason,
                })}
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-1"
            onClick={() => onChange({ ...suggested })}
            data-testid={`hakedis-tax-use-suggestion-${kind}`}
          >
            {t('hakedis.taxes.use_suggestion', { defaultValue: "Use the contract's choice" })}
          </Button>
        </div>
      )}

      {mayChoose && (
        <fieldset className="space-y-1.5">
          <legend className="sr-only">
            {t('hakedis.taxes.choose', { defaultValue: 'Choose a category for {{tax}}', tax: title })}
          </legend>
          <label className="flex items-start gap-2 text-sm text-content-secondary">
            <input
              type="radio"
              className="mt-1"
              name={groupId}
              checked={draft.state === 'unset'}
              onChange={() => setState('unset')}
              data-testid={`hakedis-tax-option-${kind}-unset`}
            />
            <span>{t('hakedis.taxes.unset', { defaultValue: 'Not decided yet' })}</span>
          </label>
          {categories.map((category) => {
            const facts = categoryFacts.get(`${kind}|${category.code}`);
            const scope = buyerScopeText(t, category.buyer_scope);
            const rate = rateText(t, category, numberLocale);
            return (
              <label
                key={category.code}
                className={clsx(
                  'flex items-start gap-2 rounded-md border px-2 py-1.5 text-sm',
                  draft.state === 'selected' && draft.code === category.code
                    ? 'border-oe-blue bg-oe-blue/5'
                    : 'border-border-light',
                )}
              >
                <input
                  type="radio"
                  className="mt-1"
                  name={groupId}
                  checked={draft.state === 'selected' && draft.code === category.code}
                  onChange={() => setState('selected', category.code)}
                  data-testid={`hakedis-tax-option-${kind}-${category.code}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-content-primary">
                    <span className="font-mono text-xs text-content-tertiary">{category.code}</span>{' '}
                    {category.label}
                    {rate && <span className="ml-1.5 whitespace-nowrap font-semibold tabular-nums">{rate}</span>}
                  </span>
                  {scope && <span className="mt-0.5 block break-words text-xs text-content-secondary">{scope}</span>}
                  {category.conditions && (
                    <span className="mt-0.5 block break-words text-xs text-content-secondary">
                      {category.conditions}
                    </span>
                  )}
                  {category.legal_reference && (
                    <span className="mt-0.5 block break-words text-xs text-content-tertiary">
                      {t('hakedis.basis.legal_reference', { defaultValue: 'Legal basis' })}: {category.legal_reference}
                    </span>
                  )}
                  {facts?.effective_from && (
                    <span className="mt-0.5 block text-xs text-content-tertiary">
                      {t('hakedis.basis.effective_from', { defaultValue: 'In force from' })}:{' '}
                      <DateDisplay value={facts.effective_from} format="numeric" />
                    </span>
                  )}
                  <span className="mt-1 block">
                    <RateReviewBadge status={category.review_status} />
                  </span>
                </span>
              </label>
            );
          })}
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input
              type="radio"
              className="mt-1"
              name={groupId}
              checked={draft.state === 'not_applicable'}
              onChange={() => setState('not_applicable')}
              data-testid={`hakedis-tax-option-${kind}-not_applicable`}
            />
            <span>{t('hakedis.taxes.not_applicable', { defaultValue: 'Does not apply to this certificate' })}</span>
          </label>
          {draft.state === 'not_applicable' && (
            <label className="block pl-6">
              <span className="block text-xs text-content-tertiary">
                {t('hakedis.taxes.not_applicable_reason', { defaultValue: 'Why it does not apply (required)' })}
              </span>
              <textarea
                rows={2}
                maxLength={2000}
                required
                value={draft.reason}
                onChange={(e) => onChange({ state: 'not_applicable', code: '', reason: e.target.value })}
                className={clsx(textareaCls, 'mt-0.5')}
                data-testid={`hakedis-tax-reason-${kind}`}
              />
            </label>
          )}
        </fieldset>
      )}

      {mayChoose && !stored && categories.length === 0 && (
        <p className="break-words text-xs text-content-tertiary">
          {t('hakedis.taxes.no_categories', {
            defaultValue: 'No category is in force for this tax on the date of the certificate.',
          })}
        </p>
      )}

      {(previewFigure || previewPending) && (
        <div
          aria-live="polite"
          className="rounded-md bg-surface-secondary px-2 py-1.5 text-xs"
          data-testid={`hakedis-tax-preview-${kind}`}
        >
          <p className="font-medium text-content-secondary">
            {t('hakedis.taxes.preview', { defaultValue: 'If saved' })}
          </p>
          {previewFigure ? (
            <FigureLine
              figure={previewFigure}
              currency={currency}
              numberLocale={numberLocale}
              context={context}
            />
          ) : (
            <p className="text-content-tertiary">{t('hakedis.taxes.preview_pending', { defaultValue: 'Calculating' })}</p>
          )}
        </div>
      )}

      {storedFigure && (
        <StoredFigure
          kind={kind}
          figure={storedFigure}
          mayOverride={mayOverride}
          currency={currency}
          numberLocale={numberLocale}
          context={context}
          userId={userId}
          onOverride={onOverride}
          onClearOverride={onClearOverride}
          onChanged={onChanged}
        />
      )}
    </section>
  );
}

/** One figure in words: its amount with base and rate, why it is held, or that it does not apply. */
function FigureLine({
  figure,
  currency,
  numberLocale,
  context,
}: {
  figure: StatutoryFigure;
  currency: string;
  numberLocale: string;
  context: ReasonContext;
}) {
  const { t } = useTranslation();
  if (figure.status === 'value' && figure.amount !== null) {
    const rate = rateText(t, figure, numberLocale);
    return (
      <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-content-primary">
        <span className="min-w-0 break-words text-content-secondary">
          {figure.base !== null && (
            <>
              {t('hakedis.basis.base', { defaultValue: 'Base' })}:{' '}
              <MoneyDisplay amount={figure.base} currency={currency || undefined} />
            </>
          )}
          {rate && <span className="ml-2 whitespace-nowrap">{rate}</span>}
        </span>
        <MoneyDisplay amount={figure.amount} currency={currency || undefined} className="font-semibold" />
      </p>
    );
  }
  if (figure.status === 'not_applicable') {
    return (
      <p className="break-words text-content-tertiary">
        {t('hakedis.line.status.not_applicable', { defaultValue: 'Not applicable' })}
        {figure.reason_key && <>: {reasonSentence(t, figure.reason_key, figure.reason_params, context)}</>}
      </p>
    );
  }
  return (
    <p className="break-words text-amber-800 dark:text-amber-300">
      <span className="font-semibold">{t('hakedis.line.held', { defaultValue: 'Held' })}</span>:{' '}
      {reasonSentence(t, figure.reason_key, figure.reason_params, context)}
    </p>
  );
}

function StoredFigure({
  kind,
  figure,
  mayOverride,
  currency,
  numberLocale,
  context,
  userId,
  onOverride,
  onClearOverride,
  onChanged,
}: {
  kind: HakedisTaxChoiceKind;
  figure: StatutoryFigure;
  mayOverride: boolean;
  currency: string;
  numberLocale: string;
  context: ReasonContext;
  userId: string | null;
  onOverride: (amount: string, reason: string) => Promise<unknown>;
  onClearOverride: () => Promise<unknown>;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [refusal, setRefusal] = useState<HakedisRefusal | null>(null);
  const done = () => {
    setRefusal(null);
    setOpen(false);
    setAmount('');
    setReason('');
    onChanged();
  };
  const overrideMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => onOverride(toDecimalPayloadString(amount, ''), reason.trim()),
    onSuccess: done,
    onError: (err) => setRefusal(readRefusal(err)),
  });
  const clearMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => onClearOverride(),
    onSuccess: done,
    onError: (err) => setRefusal(readRefusal(err)),
  });
  const ready = amount.trim() !== '' && reason.trim() !== '';

  return (
    <div className="space-y-1.5 border-t border-border-light pt-2 text-xs" data-testid={`hakedis-tax-figure-${kind}`}>
      <p className="font-medium text-content-secondary">{t('hakedis.taxes.saved_figure', { defaultValue: 'Saved' })}</p>
      <FigureLine figure={figure} currency={currency} numberLocale={numberLocale} context={context} />

      {figure.overridden && (
        <div
          className="rounded-md border border-amber-200 bg-amber-50/60 px-2 py-1.5 dark:border-amber-900 dark:bg-amber-950/30"
          data-testid={`hakedis-tax-overridden-${kind}`}
        >
          <p className="break-words font-medium text-content-primary">
            {figure.overridden_by !== null && figure.overridden_by === userId
              ? t('hakedis.taxes.overridden_by_you', { defaultValue: 'Amount entered by hand by you' })
              : t('hakedis.taxes.overridden_by_other', { defaultValue: 'Amount entered by hand by a colleague' })}
            {figure.overridden_at && (
              <>
                {', '}
                <DateDisplay value={figure.overridden_at} format="datetime" />
              </>
            )}
          </p>
          <p className="mt-0.5 break-words text-content-secondary">
            {t('hakedis.taxes.override_reason_shown', {
              defaultValue: 'Reason: {{reason}}',
              reason: figure.override_reason,
            })}
          </p>
          {mayOverride && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-1"
              loading={clearMut.isPending}
              onClick={() => clearMut.mutate()}
              data-testid={`hakedis-tax-clear-override-${kind}`}
            >
              {t('hakedis.taxes.clear_override', { defaultValue: 'Go back to the calculated amount' })}
            </Button>
          )}
        </div>
      )}

      {mayOverride && !figure.overridden && figure.status !== 'not_applicable' && !open && (
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)} data-testid={`hakedis-tax-override-${kind}`}>
          {t('hakedis.taxes.override', { defaultValue: 'Enter another amount' })}
        </Button>
      )}

      {open && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (ready) overrideMut.mutate();
          }}
          data-testid={`hakedis-tax-override-form-${kind}`}
        >
          <label className="block">
            <span className="block text-content-tertiary">{t('hakedis.line.amount', { defaultValue: 'Amount' })}</span>
            <input
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-invalid={refusal?.fields.amount ? true : undefined}
              className={clsx(inputCls, 'mt-0.5 text-right tabular-nums')}
              data-testid={`hakedis-tax-override-amount-${kind}`}
            />
            {refusal?.fields.amount && (
              <span className="mt-0.5 block text-semantic-error" role="alert">
                {refusal.fields.amount}
              </span>
            )}
          </label>
          <label className="block">
            <span className="block text-content-tertiary">
              {t('hakedis.taxes.override_reason', { defaultValue: 'Why the calculated amount is replaced (required)' })}
            </span>
            <textarea
              rows={2}
              maxLength={2000}
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className={clsx(textareaCls, 'mt-0.5')}
              data-testid={`hakedis-tax-override-reason-${kind}`}
            />
            {refusal?.fields.reason && (
              <span className="mt-0.5 block text-semantic-error" role="alert">
                {refusal.fields.reason}
              </span>
            )}
          </label>
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
              {t('hakedis.line.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              type="submit"
              size="sm"
              loading={overrideMut.isPending}
              disabled={!ready}
              data-testid={`hakedis-tax-override-save-${kind}`}
            >
              {t('hakedis.taxes.override_save', { defaultValue: 'Save the entered amount' })}
            </Button>
          </div>
        </form>
      )}

      {refusal && (refusal.code !== '' || Object.keys(refusal.fields).length === 0) && (
        <RefusalNote t={t} refusal={refusal} testId={`hakedis-tax-override-refusal-${kind}`} />
      )}
    </div>
  );
}
