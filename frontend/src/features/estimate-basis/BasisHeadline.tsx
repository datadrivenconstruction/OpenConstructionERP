// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The headline of the basis of estimate: the number the document qualifies, how
// firm it is, and the range that follows from that.
//
// This block is the answer to the question the page exists for. A qualification
// list on its own tells a reviewer what is in and out of scope but not how much
// to trust the figure, and a figure on its own tells them nothing about what it
// covers. The accuracy class is the hinge between the two, and it is the one
// judgement here the platform will not make: it proposes a class from the
// evidence and shows its reasoning, and an estimator confirms or overrides it.
//
// Money arrives as Decimal strings and is only ever formatted, never added.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CalendarClock, Check, Gauge, Info } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { fmtPercent } from '@/shared/lib/formatters';
import type { ClassReason, EstimateBasisDocument, EstimateClassOption } from './api';

export interface BasisHeadlineProps {
  doc: EstimateBasisDocument;
  /** The AACE class table as the platform publishes it (may still be loading). */
  classes: EstimateClassOption[];
  /** Called when the estimator states, changes or clears the class (0 clears). */
  onClassChange: (estimateClass: number) => void;
  /** Called when the estimator edits one of the two accuracy bounds. */
  onBandChange: (bound: 'low' | 'high', value: string) => void;
  /** The class the draft currently states, which may be ahead of `doc`. */
  estimateClass: number | null;
  accuracyLowPct: string;
  accuracyHighPct: string;
}

/** A percentage that arrived as a Decimal string, rendered for the reader. */
function Pct({ value }: { value: string }) {
  return <span className="tabular-nums">{fmtPercent(value, 1)}</span>;
}

export function BasisHeadline({
  doc,
  classes,
  onClassChange,
  onBandChange,
  estimateClass,
  accuracyLowPct,
  accuracyHighPct,
}: BasisHeadlineProps) {
  const { t } = useTranslation();
  const currency = doc.currency || doc.financials?.currency || '';
  const financials = doc.financials;
  const suggestion = doc.provenance?.suggestion;

  const byClass = useMemo(() => {
    const map = new Map<number, EstimateClassOption>();
    for (const option of classes) map.set(option.estimate_class, option);
    return map;
  }, [classes]);

  // The served English label is the fallback, so a locale that has not
  // translated a class still reads the standard's own wording rather than a key.
  const classLabel = (n: number) =>
    t(`estimateBasis.class.label.${n}`, { defaultValue: byClass.get(n)?.label || String(n) });

  const stated = estimateClass !== null && estimateClass > 0;
  // The band on the draft is authoritative while editing; the amounts are
  // recomputed by the server on save, so an unsaved band shows its percentages
  // without pretending to know the money yet.
  const bandSaved =
    accuracyLowPct === doc.accuracy_low_pct && accuracyHighPct === doc.accuracy_high_pct;
  const showAmounts = stated && bandSaved && !!doc.accuracy_low_amount && !!doc.accuracy_high_amount;

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Gauge className="h-4 w-4 text-oe-blue" aria-hidden />
            {t('estimateBasis.headline.title', { defaultValue: 'The number this document qualifies' })}
          </span>
        }
      />
      <CardContent className="space-y-4">
        {/* ── The figure ─────────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('estimateBasis.headline.total', { defaultValue: 'Estimate total' })}
            </div>
            <div className="text-2xl font-semibold tabular-nums text-content-primary">
              {!financials || financials.boq_count === 0
                ? <span className="text-content-tertiary italic">{t('estimateBasis.headline.notEstimated', { defaultValue: 'Not yet estimated' })}</span>
                : formatCurrency(financials.grand_total ?? '0', currency)}
            </div>
          </div>
          <div className="text-xs text-content-tertiary">
            <div>
              {t('estimateBasis.headline.directCost', { defaultValue: 'Direct cost' })}{' '}
              <span className="tabular-nums text-content-secondary">
                {!financials || financials.boq_count === 0
                  ? '—'
                  : formatCurrency(financials.direct_cost ?? '0', currency)}
              </span>
            </div>
            <div>
              {t('estimateBasis.headline.markups', { defaultValue: 'Markups' })}{' '}
              <span className="tabular-nums text-content-secondary">
                {!financials || financials.boq_count === 0
                  ? '—'
                  : formatCurrency(financials.markups_total ?? '0', currency)}
              </span>
              {financials?.markup_count ? (
                <span className="text-content-quaternary">
                  {' '}
                  ·{' '}
                  {t('estimateBasis.headline.markupCount', {
                    defaultValue: '{{count}} lines',
                    count: financials.markup_count,
                  })}
                </span>
              ) : null}
            </div>
          </div>
          {doc.pricing_date && (
            <div className="flex items-center gap-1.5 text-xs text-content-tertiary">
              <CalendarClock className="h-3.5 w-3.5" aria-hidden />
              {t('estimateBasis.headline.pricedAt', {
                defaultValue: 'Prices current as of {{date}}',
                date: doc.pricing_date,
              })}
            </div>
          )}
        </div>

        {/* ── How firm it is ─────────────────────────────────────────────── */}
        <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <label
              htmlFor="estimate-basis-class"
              className="text-xs font-medium uppercase tracking-wide text-content-tertiary"
            >
              {t('estimateBasis.headline.classLabel', { defaultValue: 'Accuracy class' })}
            </label>
            <select
              id="estimate-basis-class"
              value={estimateClass ?? 0}
              onChange={(e) => onClassChange(Number(e.target.value))}
              className="rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary"
            >
              <option value={0}>
                {t('estimateBasis.headline.classNotStated', { defaultValue: 'Not stated' })}
              </option>
              {classes.map((option) => (
                <option key={option.estimate_class} value={option.estimate_class}>
                  {t('estimateBasis.headline.classOption', {
                    defaultValue: 'Class {{n}} - {{label}} ({{low}} / {{high}})',
                    n: option.estimate_class,
                    label: classLabel(option.estimate_class),
                    low: option.accuracy_low,
                    high: option.accuracy_high,
                  })}
                </option>
              ))}
            </select>

            {stated && (
              <div className="flex items-center gap-1.5 text-xs text-content-tertiary">
                <span>{t('estimateBasis.headline.band', { defaultValue: 'Band' })}</span>
                <input
                  aria-label={t('estimateBasis.headline.bandLow', { defaultValue: 'Lower bound, percent' })}
                  value={accuracyLowPct}
                  onChange={(e) => onBandChange('low', e.target.value)}
                  inputMode="decimal"
                  className="w-16 rounded border border-border-light bg-surface-primary px-1.5 py-1 text-right tabular-nums text-content-primary"
                />
                <span aria-hidden>%</span>
                <span aria-hidden>/</span>
                <input
                  aria-label={t('estimateBasis.headline.bandHigh', { defaultValue: 'Upper bound, percent' })}
                  value={accuracyHighPct}
                  onChange={(e) => onBandChange('high', e.target.value)}
                  inputMode="decimal"
                  className="w-16 rounded border border-border-light bg-surface-primary px-1.5 py-1 text-right tabular-nums text-content-primary"
                />
                <span aria-hidden>%</span>
              </div>
            )}
          </div>

          {showAmounts ? (
            <p className="mt-2 text-sm text-content-secondary">
              {t('estimateBasis.headline.expectedRange', { defaultValue: 'Expected range' })}{' '}
              <span className="font-medium tabular-nums text-content-primary">
                {formatCurrency(doc.accuracy_low_amount, currency)}
              </span>{' '}
              {t('estimateBasis.headline.rangeTo', { defaultValue: 'to' })}{' '}
              <span className="font-medium tabular-nums text-content-primary">
                {formatCurrency(doc.accuracy_high_amount, currency)}
              </span>
              <span className="text-content-tertiary">
                {' '}
                (<Pct value={accuracyLowPct} /> / <Pct value={accuracyHighPct} />)
              </span>
            </p>
          ) : (
            <p className="mt-2 text-xs text-content-tertiary">
              {stated
                ? t('estimateBasis.headline.rangePending', {
                    defaultValue: 'Save to recalculate the expected range against the estimate total.',
                  })
                : t('estimateBasis.headline.noClassYet', {
                    defaultValue:
                      'Until a class is stated this estimate carries no accuracy range, and a reviewer cannot tell a concept figure from a tendered one.',
                  })}
            </p>
          )}
        </div>

        {/* ── The suggestion, and why ────────────────────────────────────── */}
        {suggestion && suggestion.suggested_class > 0 && !stated && (
          <SuggestionRow
            suggestion={suggestion}
            label={classLabel(suggestion.suggested_class)}
            onAccept={() => onClassChange(suggestion.suggested_class)}
          />
        )}

        {/* ── The two "this total is not final" flags ────────────────────── */}
        {(financials?.is_mixed_currency || financials?.has_unresolved_escalation) && (
          <div className="space-y-1">
            {financials.is_mixed_currency && (
              <Warning
                text={t('estimateBasis.headline.mixedCurrency', {
                  defaultValue:
                    'The bill blends more than one currency. The total above is converted at the project rate and is not safe to read as final.',
                })}
              />
            )}
            {financials.has_unresolved_escalation && (
              <Warning
                text={t('estimateBasis.headline.unresolvedEscalation', {
                  defaultValue:
                    'An escalation line names a price index that could not be resolved, so it was left out of the total rather than priced at zero.',
                })}
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Warning({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-1.5 text-xs text-content-secondary">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-warning" aria-hidden />
      {text}
    </p>
  );
}

/**
 * The class the platform proposes, its evidence, and one button to accept it.
 *
 * Deliberately a proposal and not a default: nothing writes a class onto the
 * document until somebody presses this. The evidence is listed underneath so
 * the estimator is agreeing with a reason rather than with a machine.
 */
function SuggestionRow({
  suggestion,
  label,
  onAccept,
}: {
  suggestion: { suggested_class: number; base_class: number; reasons: ClassReason[] };
  label: string;
  onAccept: () => void;
}) {
  const { t } = useTranslation();

  const reasonText = (reason: ClassReason): string => {
    const v = reason.value;
    switch (reason.code) {
      case 'completeness_class':
        return t('estimateBasis.classReason.completeness_class', {
          defaultValue: 'Bill completeness alone reads as class {{value}}',
          value: v,
        });
      case 'measured_share':
        return t('estimateBasis.classReason.measured_share', {
          defaultValue: '{{value}}% of the value was measured from a drawing or model',
          value: v,
        });
      case 'manual_share':
        return t('estimateBasis.classReason.manual_share', {
          defaultValue: '{{value}}% of the value was entered by hand',
          value: v,
        });
      case 'capped_by_measurement':
        return t('estimateBasis.classReason.capped_by_measurement', {
          defaultValue: 'Held back from class {{value}} because too little of it was measured',
          value: v,
        });
      case 'low_confidence_lines':
        return t('estimateBasis.classReason.low_confidence_lines', {
          defaultValue: '{{value}} machine-proposed lines are still awaiting review',
          value: v,
        });
      case 'stale_model_links':
        return t('estimateBasis.classReason.stale_model_links', {
          defaultValue: '{{value}} model-driven quantities are out of step with the model',
          value: v,
        });
      case 'share_by_count':
        return t('estimateBasis.classReason.share_by_count', {
          defaultValue: 'The bill carries no priced value, so shares are counted by line',
          value: v,
        });
      case 'unpriced_lines':
        return t('estimateBasis.classReason.unpriced_lines', {
          defaultValue: '{{value}} line items carry no unit rate',
          value: v,
        });
      default:
        return reason.code;
    }
  };

  return (
    <div className="rounded-lg border border-oe-blue/30 bg-oe-blue-subtle/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm text-content-primary">
          <Info className="h-4 w-4 shrink-0 text-oe-blue" aria-hidden />
          {t('estimateBasis.headline.suggested', {
            defaultValue: 'The estimate contents suggest class {{n}}, {{label}}.',
            n: suggestion.suggested_class,
            label,
          })}
          <Badge variant="neutral">
            {t('estimateBasis.headline.suggestionBadge', { defaultValue: 'Suggestion' })}
          </Badge>
        </span>
        <Button size="sm" onClick={onAccept} icon={<Check className="h-4 w-4" aria-hidden />}>
          {t('estimateBasis.headline.useSuggestion', {
            defaultValue: 'Use class {{n}}',
            n: suggestion.suggested_class,
          })}
        </Button>
      </div>
      {suggestion.reasons.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs text-content-secondary">
          {suggestion.reasons.map((reason) => (
            <li key={`${reason.code}-${reason.value}`}>{reasonText(reason)}</li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-2xs text-content-tertiary">
        {t('estimateBasis.headline.suggestionNote', {
          defaultValue:
            'A suggestion, not a decision. Nothing is written onto the document until you state a class.',
        })}
      </p>
    </div>
  );
}
