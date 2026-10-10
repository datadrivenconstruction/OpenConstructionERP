// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// HakedisSummaryTable - the lettered summary of one payment certificate, with
// its deductions block.
//
// The lines come in the order and under the letters the server gives, and are
// printed that way: nothing is reordered, re-lettered or recomputed here. Each
// line is in one of three states and each state reads differently on purpose:
//
//   value           the amount, with where it comes from
//   held            no amount. An amber "Held", the sentence that says what is
//                   missing, and the control that resolves it on the line
//   not applicable  no amount. A muted "Not applicable" and the reason
//
// A held line never prints a zero or a dash: either would read as "nothing is
// deducted", which is the one thing a held line does not say.
//
// The lines a person enters (price adjustment, advance recovery, the other
// deductions of the layout) are edited in place, and what the server refuses
// is shown beside the field it refused.

import { Fragment, useId, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation } from '@tanstack/react-query';
import clsx from 'clsx';
import { AlertTriangle, ArrowDownRight, PenLine, ShieldX } from 'lucide-react';

import { Badge, Button } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import {
  putHakedisLine,
  type HakedisFinding,
  type HakedisLineInput,
  type HakedisSummaryLine,
  type HakedisTaxChoiceKind,
} from './api';
import { readRefusal, type HakedisRefusal } from './hakedisQueries';
import {
  RefusalNote,
  anchorId,
  inputCls,
  jumpTo,
  lineAnchor,
  lineNamer,
  taxAnchor,
  textareaCls,
  type HakedisBlockProps,
} from './hakedisParts';
import { DERIVED_REASONS, formatMoneyText, rateText, reasonSentence, type ReasonContext } from './hakedisText';

/** The choice a tax figure is decided by. The VAT itself has none: its rate comes from the tax rules. */
export const CHOICE_OF_FIGURE: Readonly<Record<string, HakedisTaxChoiceKind>> = {
  vat_withheld: 'vat_withholding',
  income_withheld: 'income_withholding',
  stamp_duty: 'stamp_duty',
};

/** Where a line's figure comes from, in a few words. */
function originText(t: TFunction, line: HakedisSummaryLine): string {
  if (line.entered) return t('hakedis.origin.entered', { defaultValue: 'Entered by hand' });
  switch (line.op) {
    case 'tax':
      return t('hakedis.origin.tax', { defaultValue: 'From the tax calculation' });
    case 'retention':
      return t('hakedis.origin.retention', { defaultValue: 'Calculated from the retention rate' });
    case 'manual':
      // A manual line with a figure nobody typed on this certificate was
      // settled by the contract: a recovery percent, or a line ruled out.
      return line.status === 'held'
        ? t('hakedis.origin.to_enter', { defaultValue: 'To be entered by hand' })
        : t('hakedis.origin.contract', { defaultValue: 'From the contract settings' });
    case 'input':
      return line.basis.source === 'work_cumulative'
        ? t('hakedis.origin.works', { defaultValue: 'From the list of works done' })
        : t('hakedis.origin.previous', { defaultValue: 'From the previous certificate' });
    default:
      return t('hakedis.origin.calculated', { defaultValue: 'Calculated from the lines above' });
  }
}

/** Why a line that does not apply does not, in the reader's language where the server gave a key. */
function notApplicableReason(t: TFunction, line: HakedisSummaryLine, context: ReasonContext): string {
  const key = line.basis.remark || line.basis.reason || '';
  if (key) {
    const prefix = 'remark.';
    const params: Record<string, string> = {};
    for (const [name, value] of Object.entries(line.basis)) {
      if (name.startsWith(prefix)) params[name.slice(prefix.length)] = value;
    }
    return reasonSentence(t, key, params, context, line.details[0]);
  }
  return line.basis.note || line.details[0] || '';
}

interface HakedisSummaryTableProps extends HakedisBlockProps {
  /** Findings of the certificate's rules that point at a summary line, by line key. */
  lineFindings: ReadonlyMap<string, HakedisFinding[]>;
}

export function HakedisSummaryTable({
  source,
  doc,
  locale,
  numberLocale,
  canEdit,
  onUpdated,
  lineFindings,
}: HakedisSummaryTableProps) {
  const { t } = useTranslation();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const context = useMemo<ReasonContext>(
    () => ({ currency: doc.currency, locale: numberLocale, lineName: lineNamer(doc) }),
    [doc, numberLocale],
  );

  return (
    <div className="overflow-x-auto rounded-lg border border-border-light" data-testid="hakedis-summary">
      <table className="w-full text-sm">
        <caption className="sr-only">{t('hakedis.section.summary', { defaultValue: 'Summary' })}</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">{t('hakedis.summary.col_letter', { defaultValue: 'Line' })}</th>
            <th scope="col">{t('hakedis.summary.col_description', { defaultValue: 'Description' })}</th>
            <th scope="col">{t('hakedis.line.amount', { defaultValue: 'Amount' })}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {doc.summary.map((line, index) => {
            const previous = doc.summary[index - 1];
            const opensDeductions = line.section === 'deductions' && previous?.section !== 'deductions';
            const mayEnter = canEdit && line.enterable;
            const editing = mayEnter && editingKey === line.key;
            return (
              <Fragment key={line.key}>
                {opensDeductions && (
                  <tr className="bg-surface-secondary/60" data-testid="hakedis-deductions-heading">
                    <th
                      scope="colgroup"
                      colSpan={3}
                      className="px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-content-secondary"
                    >
                      {t('hakedis.section.deductions', { defaultValue: 'Deductions and set-offs' })}
                    </th>
                  </tr>
                )}
                <SummaryRow
                  source={source}
                  line={line}
                  currency={doc.currency}
                  numberLocale={numberLocale}
                  context={context}
                  findings={lineFindings.get(line.key) ?? []}
                  mayEnter={mayEnter}
                  editing={editing}
                  onEdit={() => setEditingKey(line.key)}
                />
                {editing && (
                  <tr className="bg-surface-secondary/40">
                    <td colSpan={3} className="px-3 py-3">
                      <ManualLineEditor
                        key={line.key}
                        line={line}
                        submit={(body) => putHakedisLine(source, line.key, body, locale)}
                        onSaved={(next) => {
                          setEditingKey(null);
                          onUpdated(next);
                        }}
                        onCancel={() => setEditingKey(null)}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SummaryRow({
  source,
  line,
  currency,
  numberLocale,
  context,
  findings,
  mayEnter,
  editing,
  onEdit,
}: {
  source: HakedisBlockProps['source'];
  line: HakedisSummaryLine;
  currency: string;
  numberLocale: string;
  context: ReasonContext;
  findings: HakedisFinding[];
  mayEnter: boolean;
  editing: boolean;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const choiceKind = line.op === 'tax' ? CHOICE_OF_FIGURE[line.tax_kind] : undefined;
  const held = line.status === 'held';
  const notApplicable = line.status === 'not_applicable';
  const label = line.labels.join(' / ');
  const formula = line.formulas[0] ?? '';
  const derived = held && DERIVED_REASONS.includes(line.reason_key);
  const heldOperands = derived
    ? (line.reason_params.operands ?? '')
        .split(',')
        .map((part) => part.trim())
        .filter((part) => part !== '')
    : [];

  return (
    <tr
      id={lineAnchor(source, line.key)}
      tabIndex={-1}
      className={clsx(
        'align-top focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-oe-blue',
        held && 'bg-amber-50/60 dark:bg-amber-950/20',
        line.emphasis && !held && 'bg-surface-secondary/40',
      )}
      data-testid={`hakedis-line-${line.key}`}
      data-status={line.status}
    >
      <th
        scope="row"
        className="w-10 whitespace-nowrap px-3 py-2 text-left font-mono text-xs font-semibold text-content-tertiary"
      >
        {line.letter}
      </th>
      <td className="min-w-0 px-2 py-2">
        <p className={clsx('break-words', line.emphasis ? 'font-semibold text-content-primary' : 'text-content-primary')}>
          {label}
          {formula && <span className="ml-1.5 font-normal text-content-tertiary">{formula}</span>}
        </p>
        <p className="mt-0.5 text-xs text-content-tertiary">{originText(t, line)}</p>

        {line.status === 'value' && line.op !== 'tax' && line.basis.base && (
          <p className="mt-0.5 break-words text-xs text-content-secondary" data-testid={`hakedis-line-basis-${line.key}`}>
            {t('hakedis.line.percent_of_base', {
              defaultValue: 'Base {{base}}, rate {{rate}}',
              base: formatMoneyText(line.basis.base, currency, numberLocale),
              rate: rateText(t, { rate_pct: line.basis.rate_pct }, numberLocale),
            })}
          </p>
        )}
        {line.status === 'value' && line.op !== 'tax' && line.basis.note && (
          <p className="mt-0.5 break-words text-xs text-content-secondary">{line.basis.note}</p>
        )}
        {line.op === 'tax' && !held && <TaxBasisFacts line={line} currency={currency} numberLocale={numberLocale} />}

        {held && (
          <p
            className="mt-1 flex items-start gap-1.5 break-words text-xs text-amber-800 dark:text-amber-300"
            data-testid={`hakedis-line-reason-${line.key}`}
          >
            <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{reasonSentence(t, line.reason_key, line.reason_params, context, line.reason_text[0])}</span>
          </p>
        )}
        {notApplicable && (
          <p className="mt-1 break-words text-xs text-content-tertiary" data-testid={`hakedis-line-reason-${line.key}`}>
            {notApplicableReason(t, line, context) ||
              t('hakedis.line.not_applicable_no_reason', { defaultValue: 'No reason was recorded.' })}
          </p>
        )}

        {findings.map((finding) => (
          <p
            key={`${finding.rule_id}|${finding.message}`}
            className={clsx(
              'mt-1 flex items-start gap-1.5 break-words text-xs',
              finding.severity === 'error' || finding.engine_error
                ? 'text-red-700 dark:text-red-400'
                : 'text-amber-800 dark:text-amber-300',
            )}
            data-testid={`hakedis-line-finding-${line.key}`}
          >
            <ShieldX size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{finding.message}</span>
          </p>
        ))}

        <div className="mt-1.5 flex flex-wrap gap-1.5 empty:hidden">
          {mayEnter && !editing && (
            <Button
              variant={held ? 'primary' : 'ghost'}
              size="sm"
              icon={<PenLine size={12} />}
              onClick={onEdit}
              data-testid={`hakedis-line-edit-${line.key}`}
            >
              {held
                ? t('hakedis.line.enter', { defaultValue: 'Enter' })
                : t('hakedis.line.edit', { defaultValue: 'Change' })}
            </Button>
          )}
          {choiceKind && (
            <Button
              variant={held ? 'primary' : 'ghost'}
              size="sm"
              icon={<ArrowDownRight size={12} />}
              onClick={() => jumpTo(taxAnchor(source, choiceKind))}
              data-testid={`hakedis-line-tax-${line.key}`}
            >
              {held
                ? t('hakedis.line.decide_tax', { defaultValue: 'Decide this tax' })
                : t('hakedis.line.review_tax', { defaultValue: 'Show the tax decision' })}
            </Button>
          )}
          {held && line.reason_key === 'work_line_incomplete' && (
            <Button
              variant="secondary"
              size="sm"
              icon={<ArrowDownRight size={12} />}
              onClick={() => jumpTo(anchorId(source, 'works'))}
            >
              {t('hakedis.line.show_works', { defaultValue: 'Show the list of works done' })}
            </Button>
          )}
          {heldOperands.map((key) => (
            <Button
              key={key}
              variant="secondary"
              size="sm"
              icon={<ArrowDownRight size={12} />}
              onClick={() => jumpTo(lineAnchor(source, key))}
            >
              {t('hakedis.line.go_to_line', {
                defaultValue: 'Go to {{line}}',
                line: context.lineName ? context.lineName(key) : key,
              })}
            </Button>
          ))}
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums" data-testid={`hakedis-line-amount-${line.key}`}>
        {line.status === 'value' && (
          <MoneyDisplay
            amount={line.amount}
            currency={currency || undefined}
            className={line.emphasis ? 'font-semibold text-content-primary' : 'text-content-primary'}
          />
        )}
        {held && (
          <Badge variant="warning" size="sm">
            {t('hakedis.line.held', { defaultValue: 'Held' })}
          </Badge>
        )}
        {notApplicable && (
          <span className="text-xs text-content-tertiary">
            {t('hakedis.line.status.not_applicable', { defaultValue: 'Not applicable' })}
          </span>
        )}
      </td>
    </tr>
  );
}

/**
 * What a computed tax figure rests on: its base, its rate or fraction, the
 * category, the legal reference, the date the rate is in force from, and
 * whether the rate row has been checked against its primary source. Shown on
 * every tax line so an accountant can check the figure without opening
 * anything.
 */
export function TaxBasisFacts({
  line,
  currency,
  numberLocale,
}: {
  line: HakedisSummaryLine;
  currency: string;
  numberLocale: string;
}) {
  const { t } = useTranslation();
  const basis = line.basis;
  const rate = rateText(t, basis, numberLocale);
  const facts: { key: string; label: string; value: ReactNode }[] = [];
  if (basis.base) {
    facts.push({
      key: 'base',
      label: t('hakedis.basis.base', { defaultValue: 'Base' }),
      value: <MoneyDisplay amount={basis.base} currency={currency || undefined} />,
    });
  }
  if (rate) {
    facts.push({ key: 'rate', label: t('hakedis.basis.rate', { defaultValue: 'Rate' }), value: rate });
  }
  if (basis.code) {
    facts.push({ key: 'code', label: t('hakedis.basis.code', { defaultValue: 'Code' }), value: basis.code });
  }
  if (basis.legal_reference) {
    facts.push({
      key: 'legal',
      label: t('hakedis.basis.legal_reference', { defaultValue: 'Legal basis' }),
      value: basis.legal_reference,
    });
  }
  if (basis.effective_from) {
    facts.push({
      key: 'effective',
      label: t('hakedis.basis.effective_from', { defaultValue: 'In force from' }),
      value: <DateDisplay value={basis.effective_from} format="numeric" />,
    });
  }
  if (basis.conditions) {
    facts.push({
      key: 'conditions',
      label: t('hakedis.basis.conditions', { defaultValue: 'Condition' }),
      value: basis.conditions,
    });
  }
  if (facts.length === 0 && !basis.review_status) return null;
  return (
    <div className="mt-1 space-y-1" data-testid={`hakedis-tax-facts-${line.key}`}>
      <dl className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
        {facts.map((fact) => (
          <div key={fact.key} className="flex min-w-0 gap-1">
            <dt className="shrink-0 text-content-tertiary">{fact.label}:</dt>
            <dd className="min-w-0 break-words text-content-secondary">{fact.value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap gap-1.5">
        {line.status === 'value' && <RateReviewBadge status={basis.review_status} />}
        {basis.overridden === 'true' && (
          <Badge variant="warning" size="sm">
            {t('hakedis.taxes.overridden', { defaultValue: 'Amount entered by hand' })}
          </Badge>
        )}
      </div>
    </div>
  );
}

/** Whether the rate behind a figure has been checked against its primary source. Not the same as a person confirming the taxes. */
export function RateReviewBadge({ status }: { status: string | undefined }) {
  const { t } = useTranslation();
  if (!status) return null;
  return status === 'confirmed' ? (
    <Badge variant="success" size="sm">
      {t('hakedis.rate_review.confirmed', { defaultValue: 'Rate checked against its source' })}
    </Badge>
  ) : (
    <Badge variant="warning" size="sm">
      {t('hakedis.rate_review.unconfirmed', { defaultValue: 'Rate awaiting confirmation against its source' })}
    </Badge>
  );
}

type EntryMode = 'amount' | 'percent' | 'not_applicable';

function ManualLineEditor({
  line,
  submit,
  onSaved,
  onCancel,
}: {
  line: HakedisSummaryLine;
  submit: (body: HakedisLineInput) => ReturnType<typeof putHakedisLine>;
  onSaved: (doc: Awaited<ReturnType<typeof putHakedisLine>>) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const formId = useId();
  const entered = line.entered;
  // The previous certificates' total is an amount and nothing else: the server
  // refuses a percent or "not applicable" for it, so neither is offered.
  const amountOnly = line.op !== 'manual';
  const [mode, setMode] = useState<EntryMode>(() => {
    if (!amountOnly && entered?.state === 'not_applicable') return 'not_applicable';
    if (!amountOnly && line.accepts_percent && entered?.pct) return 'percent';
    return 'amount';
  });
  const [amount, setAmount] = useState(entered?.amount ?? '');
  const [pct, setPct] = useState(entered?.pct ?? '');
  const [note, setNote] = useState(entered?.note ?? '');
  const [refusal, setRefusal] = useState<HakedisRefusal | null>(null);

  const saveMut = useMutation({
    // The refusal is shown where the person acted, in its own words.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: (body: HakedisLineInput) => submit(body),
    onSuccess: (doc) => onSaved(doc),
    onError: (err) => setRefusal(readRefusal(err)),
  });

  const ready =
    mode === 'not_applicable' ? note.trim() !== '' : mode === 'percent' ? pct.trim() !== '' : amount.trim() !== '';
  const body = (): HakedisLineInput => {
    if (mode === 'not_applicable') return { state: 'not_applicable', note: note.trim() };
    // The typed figure is handed over as a decimal string, never through a float.
    if (mode === 'percent') return { state: 'value', pct: toDecimalPayloadString(pct, ''), note: note.trim() };
    return { state: 'value', amount: toDecimalPayloadString(amount, ''), note: note.trim() };
  };
  const fieldError = (name: string) => refusal?.fields[name];
  const modes: { id: EntryMode; label: string }[] = amountOnly
    ? []
    : [
        { id: 'amount', label: t('hakedis.line.by_amount', { defaultValue: 'As an amount' }) },
        ...(line.accepts_percent
          ? [{ id: 'percent' as const, label: t('hakedis.line.by_percent', { defaultValue: 'As a percent' }) }]
          : []),
        { id: 'not_applicable', label: t('hakedis.line.not_applicable', { defaultValue: 'Does not apply' }) },
      ];
  const noteLabel =
    mode === 'not_applicable'
      ? t('hakedis.line.not_applicable_reason', { defaultValue: 'Why it does not apply' })
      : t('hakedis.line.note', { defaultValue: 'Note (optional, printed with the line)' });

  return (
    <form
      className="space-y-3"
      aria-label={line.labels.join(' / ')}
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) saveMut.mutate(body());
      }}
      data-testid={`hakedis-line-editor-${line.key}`}
    >
      {amountOnly && (
        <p className="text-xs text-content-secondary">
          {t('hakedis.previous.enter_hint', {
            defaultValue: 'No certified certificate carries this total. Enter the total of the previous certificate.',
          })}
        </p>
      )}
      {modes.length > 0 && (
        <fieldset>
          <legend className="sr-only">{t('hakedis.line.entry_kind', { defaultValue: 'How to state this line' })}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {modes.map((option) => (
              <label key={option.id} className="inline-flex items-center gap-1.5 text-sm text-content-primary">
                <input
                  type="radio"
                  name={`${formId}-mode`}
                  checked={mode === option.id}
                  onChange={() => setMode(option.id)}
                  data-testid={`hakedis-line-mode-${option.id}`}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {mode === 'amount' && (
          <label className="block">
            <span className="block text-xs uppercase tracking-wide text-content-tertiary">
              {t('hakedis.line.amount', { defaultValue: 'Amount' })}
            </span>
            <input
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-invalid={fieldError('amount') ? true : undefined}
              aria-describedby={fieldError('amount') ? `${formId}-amount-error` : undefined}
              className={clsx(inputCls, 'mt-0.5 text-right tabular-nums')}
              data-testid="hakedis-line-amount-input"
            />
            {fieldError('amount') && (
              <span id={`${formId}-amount-error`} className="mt-0.5 block text-xs text-semantic-error" role="alert">
                {fieldError('amount')}
              </span>
            )}
          </label>
        )}
        {mode === 'percent' && (
          <label className="block">
            <span className="block text-xs uppercase tracking-wide text-content-tertiary">
              {t('hakedis.line.percent', { defaultValue: 'Percent of base' })}
            </span>
            <input
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={pct}
              onChange={(e) => setPct(e.target.value)}
              aria-invalid={fieldError('pct') ? true : undefined}
              aria-describedby={fieldError('pct') ? `${formId}-pct-error` : undefined}
              className={clsx(inputCls, 'mt-0.5 text-right tabular-nums')}
              data-testid="hakedis-line-pct-input"
            />
            {fieldError('pct') && (
              <span id={`${formId}-pct-error`} className="mt-0.5 block text-xs text-semantic-error" role="alert">
                {fieldError('pct')}
              </span>
            )}
          </label>
        )}
        <label className={clsx('block', mode === 'not_applicable' && 'sm:col-span-2')}>
          <span className="block text-xs uppercase tracking-wide text-content-tertiary">{noteLabel}</span>
          <textarea
            rows={2}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-invalid={fieldError('note') ? true : undefined}
            aria-describedby={fieldError('note') ? `${formId}-note-error` : undefined}
            className={clsx(textareaCls, 'mt-0.5')}
            data-testid="hakedis-line-note-input"
          />
          {fieldError('note') && (
            <span id={`${formId}-note-error`} className="mt-0.5 block text-xs text-semantic-error" role="alert">
              {fieldError('note')}
            </span>
          )}
        </label>
      </div>

      {refusal && (refusal.code !== '' || Object.keys(refusal.fields).length === 0) && (
        <RefusalNote t={t} refusal={refusal} testId="hakedis-line-refusal" />
      )}

      <div className="flex flex-wrap justify-end gap-2">
        {entered && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => saveMut.mutate({ state: 'unset' })}
            disabled={saveMut.isPending}
            data-testid="hakedis-line-clear"
          >
            {t('hakedis.line.clear', { defaultValue: 'Clear entry' })}
          </Button>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={saveMut.isPending}>
          {t('hakedis.line.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          type="submit"
          size="sm"
          loading={saveMut.isPending}
          disabled={!ready}
          data-testid="hakedis-line-save"
        >
          {t('hakedis.line.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </form>
  );
}
