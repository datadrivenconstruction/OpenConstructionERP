// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared BCF issue status helpers - the single source of truth for how a
 * topic's status / priority map to a badge colour, whether it is done or
 * overdue, and which viewpoint represents it. Used by the issues panel, the
 * coordination-meeting mode, the review dashboard and the printable report so
 * they never drift on what "closed" or "overdue" means.
 */

import type { Topic, Viewpoint } from './api';
import { parseDateUTC } from '@/shared/lib/dates';

export type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/** Common editable statuses; the current value is merged in so imported
 *  topics with custom statuses never lose their value on edit. */
export const COMMON_STATUSES = ['Open', 'In Progress', 'Resolved', 'Closed', 'Reopened'];
export const PRIORITY_CHOICES = ['', 'Low', 'Normal', 'High', 'Critical'];

export function statusVariant(status: string): BadgeVariant {
  const s = status.toLowerCase();
  if (s.includes('closed')) return 'neutral';
  if (s.includes('resolved') || s.includes('done') || s.includes('approved')) return 'success';
  if (s.includes('progress') || s.includes('review')) return 'warning';
  if (s.includes('open') || s.includes('new') || s.includes('active') || s.includes('reopen'))
    return 'blue';
  return 'neutral';
}

export function priorityVariant(priority: string | null): BadgeVariant {
  const p = (priority ?? '').toLowerCase();
  if (p.includes('critical') || p.includes('high') || p.includes('major')) return 'error';
  if (p.includes('normal') || p.includes('medium') || p.includes('minor')) return 'warning';
  return 'neutral';
}

/** A topic is "done" once its status reads closed. */
export function isDone(status: string): boolean {
  return status.toLowerCase().includes('closed');
}

export function isOverdue(topic: Topic, now: number = Date.now()): boolean {
  if (!topic.due_date || isDone(topic.topic_status)) return false;
  // Pin date-only due dates to UTC midnight so the overdue check is not
  // shifted by the browser's local timezone offset.
  const due = parseDateUTC(topic.due_date).getTime();
  return Number.isFinite(due) && due < now;
}

/** First viewpoint carrying a snapshot, else the first viewpoint, else null. */
export function primaryViewpoint(topic: Topic): Viewpoint | null {
  return topic.viewpoints.find((v) => v.has_snapshot) ?? topic.viewpoints[0] ?? null;
}
