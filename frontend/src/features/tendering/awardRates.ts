// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { TFunction } from 'i18next';
import { fmtList } from '@/shared/lib/formatters';
import { isEmptyPosition, isSection } from '@/features/boq/api';

/** What `POST /packages/{id}/apply-winner/` answers. */
export interface AwardResult {
  package_id: string;
  bid_id: string;
  positions_updated: number;
  /** Why no rate went into the bill, or null when rates were written. */
  rates_skipped_reason?: 'boq_locked' | 'no_line_rates' | null;
  /** The package's lines that kept the bill's rate because the bid did not price them. */
  positions_unpriced?: number;
  boq_id: string;
}

/** "N positions keep their current rate", or "" when none did. */
function unpricedSentence(count: number, t: TFunction): string {
  if (count <= 0) return '';
  return t('tendering.award_unpriced_keep', {
    defaultValue: '{{count}} positions keep their current rate because the bid did not price them.',
    count,
  });
}

const joinSentences = (...parts: string[]): string => parts.filter(Boolean).join(' ');

/**
 * The sentence the award toast uses for what happened to the bill.
 *
 * An award writes the winning line rates into the BOQ only where it honestly
 * can: never into a locked bill, and not at all for a bid priced as a lump sum.
 * The toast says which, so nobody opens the estimate expecting rates that were
 * never written.
 */
export function awardRatesMessage(result: AwardResult | undefined, t: TFunction): string {
  switch (result?.rates_skipped_reason) {
    case 'boq_locked':
      return t('tendering.award_rates_locked', {
        defaultValue: 'The BOQ is locked, so its rates were left as approved.',
      });
    case 'no_line_rates':
      // The count is the one the confirm dialog showed, so the two agree.
      return joinSentences(
        t('tendering.award_rates_lump_sum', {
          defaultValue: 'The winning bid has no line rates (lump sum), so the BOQ rates were not changed.',
        }),
        unpricedSentence(result?.positions_unpriced ?? 0, t),
      );
    default:
      return joinSentences(
        t('tendering.award_rates_written', {
          defaultValue: 'BOQ positions updated with the winning rates: {{n}}.',
          n: result?.positions_updated ?? 0,
        }),
        unpricedSentence(result?.positions_unpriced ?? 0, t),
      );
  }
}

/** A bid line as the award reads it: the position it prices and its rate. */
export interface AwardLineLike {
  position_id?: string | null;
  unit_rate?: number | string | null;
}

/** A comparison row as the award preview reads it: the bill's current rate. */
export interface AwardRowLike {
  position_id: string | null;
  ordinal?: string;
  /** Section headers (no unit) are not lines and are never priced. */
  unit?: string;
  /** With the quantity, tells a blank placeholder row, which no bidder was sent. */
  description?: string;
  budget_quantity?: number | string;
  budget_rate: number | string;
}

/** What an award of this bid would do to the bill, worked out before it is confirmed. */
export interface AwardPreview {
  /** Lines that carry a rate for a position: what the award writes. */
  written: number;
  /** Of those, the ones whose rate differs from the bill's rate today. */
  changed: number;
  /** Position numbers of the changed lines, in bill order. */
  changedOrdinals: string[];
  /** Lines of the package the bid did not price: they keep the bill's rate. */
  unpriced: number;
}

const cents = (v: number | string | null | undefined): number => Math.round(Number(v ?? 0) * 100);

/**
 * A row the bidders were sent: not a section header and not a blank
 * placeholder, the rule the bill's exports and the server's count apply.
 */
const isLine = (r: AwardRowLike): boolean =>
  !isSection({ unit: r.unit ?? '' }) &&
  !isEmptyPosition({ unit: r.unit ?? '', description: r.description ?? '', quantity: Number(r.budget_quantity ?? 0) });

/**
 * Count what awarding a bid writes into the BOQ, with the filter the server's
 * `apply_winner` uses: every line that names a position and carries a rate
 * (a rate of 0 counts, a missing, null or empty one does not). That is the
 * number the success toast reports afterwards. Which of them actually change,
 * and which lines keep the bill's rate because the bid did not price them, is
 * read against the comparison rows, which hold the package's lines and the
 * bill's current rate per position.
 */
export function awardPreview(lines: readonly AwardLineLike[], rows: readonly AwardRowLike[]): AwardPreview {
  const written = lines.filter(
    (l) => !!l.position_id && l.unit_rate !== undefined && l.unit_rate !== null && l.unit_rate !== '',
  );
  const rate = new Map(written.map((l) => [String(l.position_id), cents(l.unit_rate)]));
  const changedRows = rows.filter(
    (r) => r.position_id && rate.has(r.position_id) && rate.get(r.position_id) !== cents(r.budget_rate),
  );
  return {
    written: written.length,
    changed: changedRows.length,
    changedOrdinals: changedRows.map((r) => r.ordinal || '').filter(Boolean),
    unpriced: rows.filter((r) => r.position_id && isLine(r) &&!rate.has(r.position_id)).length,
  };
}

const PREVIEW_ORDINALS = 5;

/** The sentence the award confirmation adds about the bill, from {@link awardPreview}. */
export function awardPreviewMessage(preview: AwardPreview, t: TFunction): string {
  if (preview.written === 0) {
    return t('tendering.award_preview_no_rates', {
      defaultValue: 'This bid has no line rates, so no BOQ rate changes.',
    });
  }
  const written = t('tendering.award_preview_written', {
    defaultValue: 'BOQ positions that receive this bid\'s unit rate: {{n}}.',
    n: preview.written,
  });
  const unpriced = unpricedSentence(preview.unpriced, t);
  if (preview.changed === 0) {
    return joinSentences(
      written,
      t('tendering.award_preview_none_changed', {
        defaultValue: 'None of them differs from the rate in the BOQ today.',
      }),
      unpriced,
    );
  }
  const shown = preview.changedOrdinals.slice(0, PREVIEW_ORDINALS);
  const rest = preview.changedOrdinals.length - shown.length;
  const list = rest > 0
    ? fmtList([...shown, t('tendering.award_preview_more', { defaultValue: '{{n}} more', n: rest })])
    : fmtList(shown);
  const changed = list
    ? t('tendering.award_preview_changed_list', {
        defaultValue: 'Rates that change: {{n}} ({{list}}).',
        n: preview.changed,
        list,
      })
    : t('tendering.award_preview_changed', { defaultValue: 'Rates that change: {{n}}.', n: preview.changed });
  return joinSentences(written, changed, unpriced);
}
