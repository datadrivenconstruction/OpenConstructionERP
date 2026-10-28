// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure filtering + ordering of BCF topics for the Model Review dock.
 *
 * A coordinator walking a model asks four questions in a row: what is still
 * open, what is late, what is mine, and what belongs to the model currently on
 * screen. Each of those is a predicate over the already-loaded topic list, so
 * they live here as pure functions - trivially unit-testable, and shared by the
 * dock, the agenda that feeds the guided walk, and the session hand-over.
 *
 * Scoping to the active model is deliberately OPT-IN. A topic carries
 * `bim_model_id` only when it was raised against a model, so "this model" is a
 * genuinely smaller set that would silently hide imported issues if it were the
 * default. The dock always shows the count next to the chip so the reader can
 * see what the narrowing costs before they click it.
 */

import type { Topic } from '@/features/bcf/api';
import { isDone, isOverdue } from '@/features/bcf/issueStatus';

/** Assignee filter sentinel meaning "nobody is on it". */
export const UNASSIGNED = '__unassigned__';

/** Which models the list is drawn from. */
export type ReviewScope = 'all' | 'model';

/** Ordering of the visible list. */
export type ReviewSort = 'newest' | 'due' | 'priority';

export interface ReviewFilter {
  /** Free text over title, description, labels and assignee id. */
  search: string;
  /** Exact `topic_status` match; '' means any. */
  status: string;
  /** Exact `priority` match; '' means any. */
  priority: string;
  /** User id, {@link UNASSIGNED}, or '' for any. */
  assignee: string;
  /**
   * Exact match against one of the topic's `labels`; '' means any.
   *
   * Discipline lives in `labels` throughout the product: the model seeder
   * stamps the model's discipline there, the element-derived topics stamp the
   * element's, and the clash bridge writes the clash type. So the discipline
   * control is a label control - no new field, and it also serves the other
   * things teams put in labels (zone, package, floor).
   */
  label: string;
  /** Hide everything whose status reads closed. */
  onlyOpen: boolean;
  /** Keep only open issues past their due date. */
  onlyOverdue: boolean;
  /** 'model' keeps only topics raised against `modelId`. */
  scope: ReviewScope;
}

/** The neutral filter: everything, newest first. */
export const EMPTY_REVIEW_FILTER: ReviewFilter = {
  search: '',
  status: '',
  priority: '',
  assignee: '',
  label: '',
  onlyOpen: false,
  onlyOverdue: false,
  scope: 'all',
};

/** True when the filter would narrow the list at all. */
export function isFilterActive(filter: ReviewFilter): boolean {
  return (
    filter.search.trim() !== '' ||
    filter.status !== '' ||
    filter.priority !== '' ||
    filter.assignee !== '' ||
    filter.label !== '' ||
    filter.onlyOpen ||
    filter.onlyOverdue ||
    filter.scope !== 'all'
  );
}

/**
 * Rank a BCF priority for sorting - lower sorts first (most urgent on top).
 *
 * BCF `Priority` is free-form text, and the values that reach us come from
 * three places with different vocabularies: our own picker (Low / Normal /
 * High / Critical), the clash engine (Minor / Normal / Major / Critical) and
 * whatever an imported archive carried. Matching on substrings covers all
 * three; anything unrecognised sorts after everything named.
 */
export function priorityRank(priority: string | null): number {
  const p = (priority ?? '').toLowerCase();
  if (!p) return 5;
  if (p.includes('critical') || p.includes('blocker')) return 0;
  if (p.includes('high') || p.includes('major')) return 1;
  if (p.includes('normal') || p.includes('medium')) return 2;
  if (p.includes('low') || p.includes('minor')) return 3;
  return 4;
}

/** Milliseconds of a topic's due date, or +Infinity when it has none. */
function dueTime(topic: Topic): number {
  if (!topic.due_date) return Number.POSITIVE_INFINITY;
  const t = new Date(topic.due_date).getTime();
  return Number.isFinite(t) ? t : Number.POSITIVE_INFINITY;
}

/** Milliseconds of a topic's creation date, or 0 when it has none. */
function createdTime(topic: Topic): number {
  if (!topic.creation_date) return 0;
  const t = new Date(topic.creation_date).getTime();
  return Number.isFinite(t) ? t : 0;
}

/** True when the topic mentions `query` anywhere a reader would look. */
function matchesSearch(topic: Topic, query: string): boolean {
  if (!query) return true;
  return (
    topic.title.toLowerCase().includes(query) ||
    (topic.description ?? '').toLowerCase().includes(query) ||
    (topic.assigned_to ?? '').toLowerCase().includes(query) ||
    (topic.topic_type ?? '').toLowerCase().includes(query) ||
    topic.labels.some((l) => l.toLowerCase().includes(query))
  );
}

/**
 * Apply the review filter to a topic list.
 *
 * `modelId` is only consulted when `filter.scope === 'model'`; a null model id
 * with model scope yields an empty list, which is the honest answer (nothing is
 * raised against a model that is not selected).
 */
export function filterReviewTopics(
  topics: Topic[],
  filter: ReviewFilter,
  modelId: string | null,
  now: number = Date.now(),
): Topic[] {
  const query = filter.search.trim().toLowerCase();
  return topics.filter((topic) => {
    // With no model selected, model scope must yield nothing. Comparing the
    // two nulls instead would keep every topic that belongs to no model - the
    // opposite of what the chip says it does.
    if (filter.scope === 'model' && (modelId === null || topic.bim_model_id !== modelId)) {
      return false;
    }
    if (filter.status && topic.topic_status !== filter.status) return false;
    if (filter.priority && (topic.priority ?? '') !== filter.priority) return false;
    if (filter.assignee === UNASSIGNED && topic.assigned_to) return false;
    if (filter.assignee && filter.assignee !== UNASSIGNED && topic.assigned_to !== filter.assignee) {
      return false;
    }
    if (filter.label && !topic.labels.includes(filter.label)) return false;
    if (filter.onlyOpen && isDone(topic.topic_status)) return false;
    if (filter.onlyOverdue && !isOverdue(topic, now)) return false;
    return matchesSearch(topic, query);
  });
}

/**
 * The distinct labels present in `topics`, sorted for a picker.
 *
 * Drawn from the loaded list rather than from a fixed vocabulary: BCF labels
 * are free text, so the only honest option list is the one the project has
 * actually used. Comparison is case-sensitive because that is how the filter
 * matches; two spellings of the same word are two labels, and the reader can
 * see that they are.
 */
export function collectReviewLabels(topics: Topic[]): string[] {
  const seen = new Set<string>();
  for (const topic of topics) {
    for (const label of topic.labels) {
      const trimmed = label.trim();
      if (trimmed) seen.add(trimmed);
    }
  }
  // Case-folded first so 'imported' does not land after 'Structure' just for
  // being lower case; the exact spelling still breaks ties.
  return [...seen].sort(
    (a, b) => a.toLowerCase().localeCompare(b.toLowerCase()) || a.localeCompare(b),
  );
}

/**
 * Order a topic list for review. Returns a new array; the input is untouched.
 *
 * - `due`: earliest deadline first, undated issues last.
 * - `priority`: most urgent first, then by earliest deadline within a rank.
 * - `newest`: most recently raised first (the register's own default).
 */
export function sortReviewTopics(topics: Topic[], sort: ReviewSort): Topic[] {
  const out = [...topics];
  if (sort === 'due') {
    out.sort((a, b) => dueTime(a) - dueTime(b) || createdTime(b) - createdTime(a));
  } else if (sort === 'priority') {
    out.sort(
      (a, b) =>
        priorityRank(a.priority) - priorityRank(b.priority) ||
        dueTime(a) - dueTime(b) ||
        createdTime(b) - createdTime(a),
    );
  } else {
    out.sort((a, b) => createdTime(b) - createdTime(a));
  }
  return out;
}

/** Headline counts a coordinator scans before deciding where to start. */
export interface ReviewCounts {
  total: number;
  open: number;
  overdue: number;
  unassignedOpen: number;
  /** Open issues raised against the active model (0 when none is selected). */
  openOnModel: number;
}

/** Roll a topic list up into the counts the review header shows. */
export function countReviewTopics(
  topics: Topic[],
  modelId: string | null,
  now: number = Date.now(),
): ReviewCounts {
  let open = 0;
  let overdue = 0;
  let unassignedOpen = 0;
  let openOnModel = 0;
  for (const topic of topics) {
    if (isDone(topic.topic_status)) continue;
    open += 1;
    if (!topic.assigned_to) unassignedOpen += 1;
    if (isOverdue(topic, now)) overdue += 1;
    if (modelId && topic.bim_model_id === modelId) openOnModel += 1;
  }
  return { total: topics.length, open, overdue, unassignedOpen, openOnModel };
}

/**
 * The agenda a guided walk runs through: the visible list minus what is
 * already closed, in the order the reader put it in.
 *
 * Keeping this next to the filter is deliberate - the walk must review exactly
 * what the dock is showing, never a second, invisible selection.
 */
export function buildReviewAgenda(visible: Topic[]): Topic[] {
  return visible.filter((topic) => !isDone(topic.topic_status));
}
