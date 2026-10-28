// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure roll-up of a BCF topic list into review-dashboard statistics.
 *
 * A coordination reviewer wants the shape of the issue backlog at a glance:
 * how many are open, how they split by status / priority / assignee, how many
 * are overdue, and how stale the open ones are getting. This is computed
 * entirely from the already-loaded topic list - no extra endpoint - and kept
 * pure so it is trivially unit-testable and reused by both the on-screen
 * dashboard and the printable report.
 */

import type { Topic } from './api';
import { isDone, isOverdue } from './issueStatus';

export interface AssigneeCount {
  /** Assignee user id, or null for unassigned. */
  id: string | null;
  count: number;
}

/** Age buckets for open (not-done) issues, measured from creation date. */
export interface AgeingBuckets {
  d0_7: number;
  d8_30: number;
  d31_90: number;
  d90plus: number;
}

export interface IssueStats {
  total: number;
  /** Issues whose status is not closed. */
  open: number;
  /** Issues whose status reads closed. */
  closed: number;
  /** Open issues past their due date. */
  overdue: number;
  /** Open issues with no assignee. */
  unassignedOpen: number;
  /** Count keyed by the raw status string. */
  byStatus: Record<string, number>;
  /** Count keyed by the raw priority string ('' = no priority). */
  byPriority: Record<string, number>;
  /** Per-assignee counts (including null = unassigned), busiest first. */
  byAssignee: AssigneeCount[];
  /** Ageing of the open backlog by creation date. */
  ageing: AgeingBuckets;
}

const DAY_MS = 86_400_000;

/**
 * Roll a topic list up into {@link IssueStats}. `now` is injectable so callers
 * (and tests) get deterministic overdue / ageing maths.
 */
export function computeIssueStats(topics: Topic[], now: number = Date.now()): IssueStats {
  const byStatus: Record<string, number> = {};
  const byPriority: Record<string, number> = {};
  const assignee = new Map<string | null, number>();
  const ageing: AgeingBuckets = { d0_7: 0, d8_30: 0, d31_90: 0, d90plus: 0 };

  let open = 0;
  let overdue = 0;
  let unassignedOpen = 0;

  for (const topic of topics) {
    const status = topic.topic_status || 'Open';
    byStatus[status] = (byStatus[status] ?? 0) + 1;

    const priority = topic.priority ?? '';
    byPriority[priority] = (byPriority[priority] ?? 0) + 1;

    const done = isDone(topic.topic_status);
    if (!done) {
      open += 1;
      assignee.set(topic.assigned_to, (assignee.get(topic.assigned_to) ?? 0) + 1);
      if (!topic.assigned_to) unassignedOpen += 1;
      if (isOverdue(topic, now)) overdue += 1;

      if (topic.creation_date) {
        const created = new Date(topic.creation_date).getTime();
        if (Number.isFinite(created)) {
          const ageDays = Math.max(0, (now - created) / DAY_MS);
          if (ageDays <= 7) ageing.d0_7 += 1;
          else if (ageDays <= 30) ageing.d8_30 += 1;
          else if (ageDays <= 90) ageing.d31_90 += 1;
          else ageing.d90plus += 1;
        }
      }
    }
  }

  const byAssignee: AssigneeCount[] = [...assignee.entries()]
    .map(([id, count]) => ({ id, count }))
    .sort((a, b) => b.count - a.count);

  return {
    total: topics.length,
    open,
    closed: topics.length - open,
    overdue,
    unassignedOpen,
    byStatus,
    byPriority,
    byAssignee,
    ageing,
  };
}
