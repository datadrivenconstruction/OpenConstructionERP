// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import type { Markup, UpdateMarkupData } from './api';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { parseDecimalInput, parseMoneyInput, stripCurrencySigns, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { resolveMarkupBase } from './markupBase';

/**
 * One row of a banded rate card as the editor holds it: the text the estimator
 * typed, not a parsed number, so a half-typed "1.000," is not rewritten under
 * their cursor. An empty `upTo` is the open-ended band, allowed last only.
 */
export interface BandDraft {
  upTo: string;
  rate: string;
}

export type BandIssue = 'rate' | 'limit' | 'order';

type MarkupType = Markup['markup_type'];
type ApplyTo = Markup['apply_to'];

// The three an estimator chooses from. ``subtotal`` computes exactly like
// ``cumulative``; offering both would be two options that mean one thing, so
// it is shown only on a row that already carries it (a GAEB import, an
// older bill) and labelled as the running total it is.
const BASES: ApplyTo[] = ['direct_cost', 'cumulative', 'same_as_previous'];

/**
 * Read the card stored on a row into editable text, or start one.
 *
 * A row switched to banded for the first time gets a single open-ended band at
 * its current percentage, which charges exactly what the percentage did. The
 * estimator then splits it, rather than the amount jumping the moment the type
 * changes.
 */
export function readBandDraft(metadata: unknown, fallbackRate: number): BandDraft[] {
  const raw = metadata && typeof metadata === 'object' ? (metadata as Record<string, unknown>).bands : undefined;
  if (Array.isArray(raw)) {
    const rows: { ceiling: number | null; draft: BandDraft }[] = [];
    for (const entry of raw) {
      if (!entry || typeof entry !== 'object') continue;
      const row = entry as Record<string, unknown>;
      const upToRaw = row.up_to;
      const open = upToRaw === null || upToRaw === undefined || String(upToRaw).trim() === '';
      const ceiling = open ? null : Number(String(upToRaw));
      rows.push({
        ceiling: ceiling !== null && Number.isFinite(ceiling) ? ceiling : null,
        draft: { upTo: open ? '' : String(upToRaw), rate: String(row.percentage ?? '0') },
      });
    }
    if (rows.length > 0) {
      // Show the card in the order the cascade reads it: ceilings ascending,
      // the open-ended band last.
      rows.sort((a, b) => {
        if (a.ceiling === null) return b.ceiling === null ? 0 : 1;
        if (b.ceiling === null) return -1;
        return a.ceiling - b.ceiling;
      });
      return rows.map((r) => r.draft);
    }
  }
  return [{ upTo: '', rate: String(Number.isFinite(fallbackRate) ? fallbackRate : 0) }];
}

/**
 * Find what is wrong with a card, per band.
 *
 * Each band starts where the previous one ends, so the card is contiguous by
 * construction; what can still go wrong is a missing or non-positive limit on
 * a band that is not last, limits that do not climb, and a rate outside 0-100.
 * The backend refuses the same cards (`_band_card_problem`), this only says so
 * before the round-trip.
 */
export function validateBandDraft(bands: BandDraft[]): { index: number; issue: BandIssue }[] {
  const issues: { index: number; issue: BandIssue }[] = [];
  let previous = 0;
  bands.forEach((band, index) => {
    const rate = parseDecimalInput(band.rate);
    if (rate === null || rate < 0 || rate > 100) issues.push({ index, issue: 'rate' });
    const isLast = index === bands.length - 1;
    if (band.upTo.trim() === '') {
      if (!isLast) issues.push({ index, issue: 'limit' });
      return;
    }
    const limit = parseMoneyInput(band.upTo);
    if (limit === null || limit <= 0) {
      issues.push({ index, issue: 'limit' });
      return;
    }
    if (limit <= previous) issues.push({ index, issue: 'order' });
    previous = limit;
  });
  return issues;
}

/** The card as the API stores it: Decimal strings, `null` for the open band. */
export function bandsToWire(bands: BandDraft[]): { up_to: string | null; percentage: string }[] {
  return bands.map((band) => ({
    up_to: band.upTo.trim() === '' ? null : toDecimalPayloadString(stripCurrencySigns(band.upTo)),
    percentage: toDecimalPayloadString(band.rate),
  }));
}

/** Same progressive sum as `bandedAmount` in MarkupPanel, over parsed drafts. */
function bandedPreview(base: number, bands: BandDraft[]): number {
  let total = 0;
  let lower = 0;
  for (const band of bands) {
    const rate = parseDecimalInput(band.rate) ?? 0;
    const ceiling = band.upTo.trim() === '' ? null : parseMoneyInput(band.upTo);
    const top = ceiling === null ? base : Math.min(base, ceiling);
    if (top <= lower) continue;
    total += ((top - lower) * rate) / 100;
    lower = top;
    if (lower >= base) break;
  }
  return total;
}

export interface MarkupRowEditorProps {
  markup: Markup;
  /** Sum of the positions, the base of a `direct_cost` line. */
  directCost: number;
  /** Direct cost plus every active line above this one, the base of a running-total line. */
  runningBefore: number;
  /**
   * The base the nearest active line above was charged on, which a
   * `same_as_previous` line borrows. Null when there is no line above or
   * it is a fixed amount; the line then falls back to the sum of positions.
   */
  previousBase?: number | null;
  currencyCode: string;
  locale: string;
  saving?: boolean;
  onSave: (data: UpdateMarkupData) => void;
  onCancel: () => void;
}

/**
 * The per-row settings an estimator needs to build a real markup stack in the
 * panel rather than through the API: what the line is calculated on, what kind
 * of line it is, its amount or rate card, and a live preview of what those
 * choices add. Nothing is saved until Apply, so trying a base out is free.
 */
export function MarkupRowEditor({
  markup,
  directCost,
  runningBefore,
  previousBase = null,
  currencyCode,
  locale,
  saving,
  onSave,
  onCancel,
}: MarkupRowEditorProps) {
  const { t } = useTranslation();
  const idBase = `markup-${markup.id}`;

  const initialBands = useMemo(
    () => readBandDraft(markup.metadata, typeof markup.percentage === 'number' ? markup.percentage : 0),
    [markup.metadata, markup.percentage],
  );
  const [markupType, setMarkupType] = useState<MarkupType>(markup.markup_type ?? 'percentage');
  const [applyTo, setApplyTo] = useState<ApplyTo>(markup.apply_to ?? 'direct_cost');
  const [percentage, setPercentage] = useState(String(markup.percentage ?? 0));
  const [fixedAmount, setFixedAmount] = useState(String(toNum(markup.fixed_amount)));
  const [bands, setBands] = useState<BandDraft[]>(initialBands);

  const types: MarkupType[] =
    markup.markup_type === 'escalation' ? ['percentage', 'fixed', 'banded', 'escalation'] : ['percentage', 'fixed', 'banded'];

  const pctValue = parseDecimalInput(percentage);
  const pctInvalid = markupType === 'percentage' && (pctValue === null || pctValue < 0 || pctValue > 100);
  const fixedValue = parseMoneyInput(fixedAmount);
  const fixedInvalid = markupType === 'fixed' && (fixedValue === null || fixedValue < 0);
  const bandIssues = markupType === 'banded' ? validateBandDraft(bands) : [];
  const hasErrors = pctInvalid || fixedInvalid || bandIssues.length > 0;

  const base = resolveMarkupBase(applyTo, directCost, runningBefore, previousBase);
  const baseFellBack = applyTo === 'same_as_previous' && previousBase === null;
  const baseOptions: ApplyTo[] = markup.apply_to === 'subtotal' ? [...BASES, 'subtotal'] : BASES;
  const previewAmount: number | null = (() => {
    if (hasErrors) return null;
    switch (markupType) {
      case 'fixed':
        return fixedValue ?? 0;
      case 'banded':
        return bandedPreview(base, bands);
      case 'escalation': {
        const factor = toNum(markup.escalation_factor ?? 0);
        return factor > 0 ? base * (factor - 1) : 0;
      }
      default:
        return (base * (pctValue ?? 0)) / 100;
    }
  })();

  const issueText: Record<BandIssue, string> = {
    rate: t('boq.markup_band_err_rate', { defaultValue: 'Each band needs a rate from 0 to 100.' }),
    limit: t('boq.markup_band_err_limit', {
      defaultValue: 'Enter an upper limit above zero for every band except the last.',
    }),
    order: t('boq.markup_band_err_order', { defaultValue: 'Each upper limit must be higher than the one before it.' }),
  };
  const firstBandIssue = bandIssues[0]?.issue;
  const lastBandCapped = bands.length > 0 && bands[bands.length - 1]!.upTo.trim() !== '';

  const money = (v: number) => formatCurrency(v, currencyCode, locale || undefined);

  const changeType = (next: MarkupType) => {
    setMarkupType(next);
    if (next === 'banded' && markup.markup_type !== 'banded') {
      // Seed from the percentage as it stands now, so the amount does not jump.
      setBands(readBandDraft(markup.metadata, pctValue ?? 0));
    }
  };

  const updateBand = (index: number, patch: Partial<BandDraft>) =>
    setBands((prev) => prev.map((band, i) => (i === index ? { ...band, ...patch } : band)));

  const addBand = () =>
    setBands((prev) => {
      const last = prev[prev.length - 1];
      // The open-ended band stays last: a new band goes in front of it and the
      // estimator gives it a limit.
      if (last && last.upTo.trim() === '') {
        return [...prev.slice(0, -1), { upTo: '', rate: last.rate }, last];
      }
      return [...prev, { upTo: '', rate: last?.rate ?? '0' }];
    });

  const removeBand = (index: number) => setBands((prev) => prev.filter((_, i) => i !== index));

  const handleApply = () => {
    if (hasErrors) return;
    const data: UpdateMarkupData = {};
    if (markupType !== markup.markup_type) data.markup_type = markupType;
    if (applyTo !== markup.apply_to) data.apply_to = applyTo;
    if (markupType === 'percentage' && pctValue !== null && pctValue !== markup.percentage) {
      data.percentage = pctValue;
    }
    if (markupType === 'fixed' && fixedValue !== null && fixedValue !== toNum(markup.fixed_amount)) {
      data.fixed_amount = toDecimalPayloadString(stripCurrencySigns(fixedAmount));
    }
    if (
      markupType === 'banded' &&
      (markup.markup_type !== 'banded' || JSON.stringify(bands) !== JSON.stringify(initialBands))
    ) {
      data.metadata = { bands: bandsToWire(bands) };
    }
    onSave(data);
  };

  const inputClass =
    'rounded border border-border bg-surface-primary px-1.5 py-1 text-sm tabular-nums outline-none focus:ring-1 focus:ring-oe-blue';

  return (
    <div
      data-testid="markup-row-editor"
      className="whitespace-normal space-y-3 px-4 py-3 text-xs text-content-secondary"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel();
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        {/* Type */}
        <fieldset>
          <legend className="mb-1.5 font-semibold text-content-primary">
            {t('boq.markup_type_legend', { defaultValue: 'Type' })}
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {types.map((type) => (
              <label
                key={type}
                className={clsx(
                  'cursor-pointer rounded-md border px-2 py-1',
                  markupType === type
                    ? 'border-oe-blue bg-oe-blue/10 text-content-primary'
                    : 'border-border-light hover:bg-surface-secondary',
                )}
              >
                <input
                  type="radio"
                  name={`${idBase}-type`}
                  value={type}
                  checked={markupType === type}
                  onChange={() => changeType(type)}
                  className="sr-only"
                />
                {type === 'percentage' && t('boq.markup_type_percentage', { defaultValue: 'Percentage' })}
                {type === 'fixed' && t('boq.markup_type_fixed', { defaultValue: 'Fixed amount' })}
                {type === 'banded' && t('boq.markup_type_banded', { defaultValue: 'Banded rates' })}
                {type === 'escalation' && t('boq.markup_type_escalation', { defaultValue: 'Index escalation' })}
              </label>
            ))}
          </div>
          <p className="mt-1.5 text-content-tertiary">
            {markupType === 'percentage' && t('boq.markup_type_percentage_hint', { defaultValue: 'A percentage of the base.' })}
            {markupType === 'fixed' &&
              t('boq.markup_type_fixed_hint', { defaultValue: 'A lump sum that stays the same whatever the estimate.' })}
            {markupType === 'banded' &&
              t('boq.markup_type_banded_hint', {
                defaultValue: 'Each slice of the base is charged at its own rate, the way a surety prices a bond.',
              })}
          </p>

          {markupType === 'percentage' && (
            <label className="mt-2 flex items-center gap-2">
              <span>{t('boq.markup_rate_pct', { defaultValue: 'Rate (%)' })}</span>
              <input
                type="text"
                inputMode="decimal"
                value={percentage}
                onChange={(e) => setPercentage(e.target.value)}
                aria-invalid={pctInvalid}
                className={clsx(inputClass, 'w-20 text-right', pctInvalid && 'border-red-500')}
              />
            </label>
          )}
          {pctInvalid && (
            <p role="alert" className="mt-1 text-red-600 dark:text-red-400">
              {t('boq.markup_pct_invalid_title', { defaultValue: 'Enter a percentage from 0 to 100' })}
            </p>
          )}

          {markupType === 'fixed' && (
            <label className="mt-2 flex items-center gap-2">
              <span>{t('boq.markup_fixed_amount_label', { defaultValue: 'Amount' })}</span>
              <input
                type="text"
                inputMode="decimal"
                value={fixedAmount}
                onChange={(e) => setFixedAmount(e.target.value)}
                aria-invalid={fixedInvalid}
                className={clsx(inputClass, 'w-32 text-right', fixedInvalid && 'border-red-500')}
              />
            </label>
          )}
          {fixedInvalid && (
            <p role="alert" className="mt-1 text-red-600 dark:text-red-400">
              {t('boq.markup_fixed_invalid', { defaultValue: 'Enter an amount of zero or more.' })}
            </p>
          )}
        </fieldset>

        {/* Base */}
        <fieldset>
          <legend className="mb-1.5 font-semibold text-content-primary">
            {t('boq.markup_base_legend', { defaultValue: 'Calculated on' })}
          </legend>
          {markupType === 'fixed' ? (
            <p className="text-content-tertiary">
              {t('boq.markup_base_none_fixed', { defaultValue: 'A fixed amount does not depend on a base.' })}
            </p>
          ) : (
            <div className="space-y-1.5">
              {baseOptions.map((option) => (
                <label key={option} className="flex cursor-pointer items-start gap-2">
                  <input
                    type="radio"
                    name={`${idBase}-base`}
                    value={option}
                    checked={applyTo === option}
                    onChange={() => setApplyTo(option)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium text-content-primary">
                      {option === 'direct_cost' && t('boq.markup_base_direct_cost', { defaultValue: 'Sum of positions' })}
                      {option === 'cumulative' && t('boq.markup_base_cumulative', { defaultValue: 'Running total incl. rows above' })}
                      {option === 'same_as_previous' &&
                        t('boq.markup_base_same_as_previous', { defaultValue: 'Same base as the row above' })}
                      {option === 'subtotal' &&
                        t('boq.markup_base_subtotal', {
                          defaultValue: 'Running total incl. rows above (stored as subtotal)',
                        })}
                    </span>
                    <span className="block text-content-tertiary">
                      {option === 'direct_cost' &&
                        t('boq.markup_base_direct_cost_hint', {
                          defaultValue: 'Only the sum of the positions. Other markups are left out.',
                        })}
                      {option === 'cumulative' &&
                        t('boq.markup_base_cumulative_hint', {
                          defaultValue:
                            'Sum of positions plus every active markup above this line. Move the line up or down to change what it includes.',
                        })}
                      {option === 'same_as_previous' &&
                        t('boq.markup_base_same_as_previous_hint', {
                          defaultValue:
                            'Uses exactly the base of the nearest active line above, so two lines such as risk and profit sit on the same amount instead of one compounding on the other.',
                        })}
                      {option === 'subtotal' &&
                        t('boq.markup_base_subtotal_hint', {
                          defaultValue:
                            'Works exactly like the running total. This line was stored as a subtotal, for example by a GAEB import.',
                        })}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </fieldset>
      </div>

      {markupType === 'banded' && (
        <div>
          <table className="text-xs">
            <thead>
              <tr className="text-content-tertiary">
                <th className="px-1 py-1 text-left font-medium">{t('boq.markup_band_from', { defaultValue: 'From' })}</th>
                <th className="px-1 py-1 text-left font-medium">{t('boq.markup_band_to', { defaultValue: 'Up to' })}</th>
                <th className="px-1 py-1 text-left font-medium">{t('boq.markup_rate_pct', { defaultValue: 'Rate (%)' })}</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {bands.map((band, index) => {
                const prevLimit = index === 0 ? 0 : parseMoneyInput(bands[index - 1]!.upTo);
                const rowIssues = bandIssues.filter((i) => i.index === index).map((i) => i.issue);
                return (
                  <tr key={index} data-testid="markup-band-row">
                    <td className="px-1 py-1 tabular-nums text-content-tertiary">
                      {prevLimit === null ? '' : money(prevLimit)}
                    </td>
                    <td className="px-1 py-1">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={band.upTo}
                        placeholder={
                          index === bands.length - 1 ? t('boq.markup_band_open', { defaultValue: 'and above' }) : ''
                        }
                        onChange={(e) => updateBand(index, { upTo: e.target.value })}
                        aria-label={t('boq.markup_band_to', { defaultValue: 'Up to' })}
                        aria-invalid={rowIssues.includes('limit') || rowIssues.includes('order')}
                        className={clsx(
                          inputClass,
                          'w-32 text-right',
                          (rowIssues.includes('limit') || rowIssues.includes('order')) && 'border-red-500',
                        )}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={band.rate}
                        onChange={(e) => updateBand(index, { rate: e.target.value })}
                        aria-label={t('boq.markup_rate_pct', { defaultValue: 'Rate (%)' })}
                        aria-invalid={rowIssues.includes('rate')}
                        className={clsx(inputClass, 'w-20 text-right', rowIssues.includes('rate') && 'border-red-500')}
                      />
                    </td>
                    <td className="px-1 py-1">
                      <button
                        type="button"
                        onClick={() => removeBand(index)}
                        disabled={bands.length <= 1}
                        aria-label={t('boq.markup_band_remove', { defaultValue: 'Remove band' })}
                        className="text-content-tertiary hover:text-red-500 disabled:opacity-40 disabled:hover:text-content-tertiary"
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <button
            type="button"
            onClick={addBand}
            className="mt-1 flex items-center gap-1 rounded-md px-1.5 py-1 font-medium text-oe-blue-text hover:bg-oe-blue-subtle"
          >
            <Plus size={13} />
            {t('boq.markup_band_add', { defaultValue: 'Add band' })}
          </button>
          {firstBandIssue && (
            <p role="alert" className="mt-1 text-red-600 dark:text-red-400">
              {issueText[firstBandIssue]}
            </p>
          )}
          {!firstBandIssue && lastBandCapped && (
            <p className="mt-1 text-amber-700 dark:text-amber-400">
              {t('boq.markup_band_uncapped_hint', {
                defaultValue:
                  'Amounts above the last limit are not charged. Leave the last limit empty to charge everything above it.',
              })}
            </p>
          )}
          <p className="mt-1 text-content-tertiary">
            {t('boq.markup_band_per_thousand_hint', {
              defaultValue: 'A rate quoted per 1,000 divides by 10: 25 per 1,000 is 2.5 %.',
            })}
          </p>
        </div>
      )}

      {/* Live preview */}
      <div
        data-testid="markup-row-preview"
        aria-live="polite"
        className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-md bg-surface-secondary/50 px-3 py-2"
      >
        {markupType !== 'fixed' && baseFellBack && (
          <span data-testid="markup-base-fallback" className="basis-full text-amber-700 dark:text-amber-400">
            {t('boq.markup_base_fallback_note', {
              defaultValue: 'No line above has a base, so this line uses the sum of positions.',
            })}
          </span>
        )}
        {markupType !== 'fixed' && (
          <span className="flex items-baseline gap-1.5">
            <span>{t('boq.markup_preview_base', { defaultValue: 'Base amount' })}</span>
            <span data-testid="markup-preview-base" className="tabular-nums font-medium text-content-primary">
              {money(base)}
            </span>
          </span>
        )}
        <span className="flex items-baseline gap-1.5">
          <span>{t('boq.markup_preview_amount', { defaultValue: 'This line adds' })}</span>
          <span data-testid="markup-preview-amount" className="tabular-nums font-semibold text-content-primary">
            {previewAmount === null ? '—' : money(previewAmount)}
          </span>
        </span>
        <span className="ms-auto flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-2.5 py-1 hover:bg-surface-secondary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            onClick={handleApply}
            disabled={hasErrors || saving}
            className="rounded-md bg-oe-blue px-2.5 py-1 font-medium text-white disabled:opacity-50"
          >
            {t('boq.markup_apply', { defaultValue: 'Apply' })}
          </button>
        </span>
      </div>
    </div>
  );
}
