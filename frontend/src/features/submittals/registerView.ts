// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the submittal register is showing: the cut (filters), the order, and
 * the vocabulary the pickers and the badges read their codes from.
 *
 * Every filter but one is a query parameter of the list route, so the rows on
 * screen are the rows the server chose and the export can be asked for the
 * same cut. The exception is `awaiting`: "with the reviewer" is two statuses
 * (submitted and under review) and the route takes one, so that cut is made
 * over the rows already loaded. The list is read whole, which keeps it exact.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import {
  fetchSubmittalVocabulary,
  type Submittal,
  type SubmittalExportFilters,
  type SubmittalFilters,
  type SubmittalStatus,
  type SubmittalVocabulary,
  type SubmittalVocabularyEntry,
} from './api';

export interface RegisterFilters {
  status: SubmittalStatus | '';
  /** A submittal type; `shop_drawing` is the shop drawing register. */
  type: string;
  discipline: string;
  /** A review outcome code, the reviewer's decision on the current revision. */
  outcome: string;
  longLead: boolean;
  reviewOverdue: boolean;
  approvalLate: boolean;
  /** With the reviewer now. Applied on the client, see the file header. */
  awaiting: boolean;
}

export const NO_FILTERS: RegisterFilters = {
  status: '',
  type: '',
  discipline: '',
  outcome: '',
  longLead: false,
  reviewOverdue: false,
  approvalLate: false,
  awaiting: false,
};

export interface RegisterSort {
  field: string;
  order: 'asc' | 'desc';
}

/** The statuses in which a submittal is with the reviewer. */
const AWAITING_REVIEW: ReadonlySet<string> = new Set(['submitted', 'under_review']);

/** True when any filter narrows the list, the client-side one included. */
export function hasActiveFilter(filters: RegisterFilters): boolean {
  return hasServerFilter(filters) || filters.awaiting;
}

/** True when a filter the list and export routes understand is set. */
export function hasServerFilter(filters: RegisterFilters): boolean {
  return (
    filters.status !== '' ||
    filters.type !== '' ||
    filters.discipline !== '' ||
    filters.outcome !== '' ||
    filters.longLead ||
    filters.reviewOverdue ||
    filters.approvalLate
  );
}

/** Whether two cuts are the same, so a shortcut can tell that it is the active one. */
export function sameFilters(a: RegisterFilters, b: RegisterFilters): boolean {
  return (
    a.status === b.status &&
    a.type === b.type &&
    a.discipline === b.discipline &&
    a.outcome === b.outcome &&
    a.longLead === b.longLead &&
    a.reviewOverdue === b.reviewOverdue &&
    a.approvalLate === b.approvalLate &&
    a.awaiting === b.awaiting
  );
}

/** The filters as the export route takes them. */
export function toExportFilters(filters: RegisterFilters): SubmittalExportFilters {
  return {
    status: filters.status,
    type: filters.type || undefined,
    discipline: filters.discipline || undefined,
    outcome: filters.outcome || undefined,
    long_lead: filters.longLead || undefined,
    review_overdue: filters.reviewOverdue || undefined,
    approval_late: filters.approvalLate || undefined,
  };
}

/** The filters and the order as the list route takes them. */
export function toListFilters(
  projectId: string,
  filters: RegisterFilters,
  sort: RegisterSort | null,
): SubmittalFilters {
  return {
    project_id: projectId,
    ...toExportFilters(filters),
    sort: sort?.field,
    order: sort?.order,
  };
}

/**
 * The rows left after the one client-side cut.
 *
 * With `awaiting` on and no order chosen by the reader, the longest wait comes
 * first: that is the question the cut is opened to answer. The number sorted
 * by is the server's `days_in_review`, never a date difference worked out
 * here, and a row without one goes last.
 */
export function applyClientCut(
  rows: Submittal[],
  filters: RegisterFilters,
  sort: RegisterSort | null,
): Submittal[] {
  if (!filters.awaiting) return rows;
  const waiting = rows.filter((row) => AWAITING_REVIEW.has(row.status));
  if (sort) return waiting;
  return [...waiting].sort((a, b) => (b.days_in_review ?? -1) - (a.days_in_review ?? -1));
}

/**
 * The codes the pickers offer, in the interface language.
 *
 * `null` while loading and when the route is not there to answer; the page
 * then shows codes as stored and offers no list it would have had to invent.
 * The key is outside `['submittals']` on purpose: a vocabulary does not change
 * when a submittal does, so saving one should not refetch it.
 */
export function useSubmittalVocabulary(): SubmittalVocabulary | null {
  const { i18n } = useTranslation();
  const locale = (i18n.language || 'en').split('-')[0] || 'en';
  const { data } = useQuery({
    queryKey: ['submittal-vocabulary', locale],
    queryFn: () => fetchSubmittalVocabulary(locale),
    staleTime: 60 * 60_000,
  });
  return data ?? null;
}

/** Find one code in a vocabulary list. */
export function vocabularyEntry(
  entries: SubmittalVocabularyEntry[] | undefined,
  code: string | null | undefined,
): SubmittalVocabularyEntry | undefined {
  if (!entries || !code) return undefined;
  return entries.find((entry) => entry.code === code);
}

/** A code nobody has a label for, made readable: `fire_protection` -> `Fire Protection`. */
export function humaniseCode(code: string): string {
  return code.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** A discipline as a word: the vocabulary's label, or the code made readable. */
export function disciplineLabel(vocabulary: SubmittalVocabulary | null, code: string): string {
  return vocabularyEntry(vocabulary?.disciplines, code)?.label ?? humaniseCode(code);
}

/**
 * A discipline as the mark that fits a table cell: the two-letter short code
 * of the vocabulary, or the first letters of a code a project added itself.
 */
export function disciplineMark(vocabulary: SubmittalVocabulary | null, code: string): string {
  return vocabularyEntry(vocabulary?.disciplines, code)?.short_code ?? code.slice(0, 3).toUpperCase();
}

/** Whether the server can order the list by `field`. Nothing is sortable until it says so. */
export function isServerSortable(vocabulary: SubmittalVocabulary | null, field: string): boolean {
  return vocabulary?.sort_fields.includes(field) ?? false;
}
