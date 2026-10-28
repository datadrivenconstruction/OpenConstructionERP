// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the COPQ card has to say underneath its rework figure.
 *
 * The server only ever folds punch money already denominated in the report's
 * currency, and it reports what it left out: how many open items are priced,
 * how many are not, what sits in other currencies, and which of those cases
 * produced the number. The card used to print the amount alone, so a euro
 * project whose snags are all priced in dollars read "Rework est. 0 EUR" -
 * the same as a project nobody has priced at all, and the same as a project
 * with no open snags. Three facts, one figure, and a person acts on it.
 *
 * These are descriptors rather than finished strings so the rule can be
 * tested without an i18n runtime; the card resolves them through `t`.
 */

import { fmtList } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';
import type { COPQReport } from './api';

export interface ReworkNote {
  key: string;
  defaultValue: string;
  params?: Record<string, string | number>;
}

function count(value: number | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0;
}

/**
 * The lines to print under the rework figure, in reading order. Empty when
 * the figure needs no explanation: everything open is priced, in the report's
 * own currency.
 */
export function reworkNotes(report: COPQReport): ReworkNote[] {
  const priced = count(report.rework_priced_count);
  const unpriced = count(report.rework_unpriced_count);
  const unreadable = count(report.rework_unreadable_count);
  const total = priced + unpriced + unreadable;
  const currency = (report.currency || '').trim().toUpperCase();
  const notes: ReworkNote[] = [];

  switch (report.rework_cost_basis) {
    case 'override':
      notes.push({
        key: 'qms.rework_note_override',
        defaultValue: 'From an assumed cost per item, not from what was recorded.',
      });
      break;
    case 'source_unavailable':
      notes.push({
        key: 'qms.rework_note_unavailable',
        defaultValue: 'The punch list is not available, so no rework money is counted.',
      });
      break;
    case 'currency_unknown':
      notes.push({
        key: 'qms.rework_note_currency_unknown',
        defaultValue: 'The project has no currency set, so no rework money is counted.',
      });
      break;
    case 'no_open_punch_items':
      notes.push({
        key: 'qms.rework_note_no_items',
        defaultValue: 'No open punch items.',
      });
      break;
    case 'none_priced':
      notes.push({
        key: 'qms.rework_note_none_priced',
        defaultValue: 'Priced: none of {{total}} open items.',
        params: { total },
      });
      break;
    case 'currency_mismatch':
      notes.push({
        key: 'qms.rework_note_currency_mismatch',
        defaultValue: 'Priced: {{priced}} of {{total}} open items, none of them in {{currency}}.',
        params: { priced, total, currency },
      });
      break;
    case 'recorded':
      // Silence is only honest when every open item is priced in this currency.
      if (unpriced > 0 || unreadable > 0) {
        notes.push({
          key: 'qms.rework_note_recorded',
          defaultValue: 'Priced: {{priced}} of {{total}} open items.',
          params: { priced, total },
        });
      }
      break;
    default:
      break;
  }

  const others = Object.entries(report.rework_by_currency ?? {})
    .filter(([code]) => code.trim().toUpperCase() !== currency)
    .map(([code, amount]) => formatCurrency(amount, code));
  if (others.length > 0) {
    notes.push({
      key: 'qms.rework_other_currencies',
      defaultValue: 'Also recorded and not added: {{amounts}}.',
      // A list a person reads, so it is joined the way their language joins
      // one, not with a Latin comma.
      params: { amounts: fmtList(others) },
    });
  }

  if (unreadable > 0) {
    notes.push({
      key: 'qms.rework_unreadable',
      defaultValue: 'Amounts that could not be read: {{items}}.',
      params: { items: unreadable },
    });
  }

  return notes;
}
