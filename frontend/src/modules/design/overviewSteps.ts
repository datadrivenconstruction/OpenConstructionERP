// Design module (ERP side of the design editor link).
/** The project's steps (overview page and the editor's side panel): icon, state and one status line each. */
import type { useTranslation } from 'react-i18next';
import {
  Boxes, Calculator, CalendarRange, ClipboardList, DraftingCompass, FileStack, GitPullRequestArrow, Link2, Package,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { tr } from './BriefFields';
import type { OverviewStep, StepId } from './linksApi';

export const ICON: Record<StepId, LucideIcon> = {
  brief: DraftingCompass, model: Boxes, estimate: Calculator, schedule: CalendarRange, procurement: Package,
  documents: FileStack, bim: Link2, change_orders: GitPullRequestArrow, tasks: ClipboardList,
};
/** The path a project takes; documents, change orders and tasks follow on their own. */
export const CORE_STEPS: StepId[] = ['brief', 'model', 'estimate', 'schedule', 'procurement'];

export function stepState(s: OverviewStep): 'done' | 'waiting' | 'todo' {
  if (s.id === 'model' && (s.waiting ?? 0) > 0) return 'waiting';
  if (s.id === 'tasks') return (s.count ?? 0) > 0 ? 'waiting' : 'done';
  // An accepted model with no element linked to a position is not a finished link.
  if (s.id === 'bim') return s.done && (s.count ?? 0) > 0 ? 'done' : 'todo';
  return s.done ? 'done' : 'todo';
}

/** One line: what is there, or why it is not there yet. `all` lets a step say its prerequisite is ready. */
export function stepText(t: ReturnType<typeof useTranslation>['t'], s: OverviewStep, all: OverviewStep[] = []): string {
  const state = stepState(s);
  if (s.id === 'model' && (s.done || s.waiting)) {
    const parts = s.done ? [tr(t, 'design.overview.state.model', { current: s.current, count: s.count ?? 0 })] : [];
    if (s.waiting) parts.push(tr(t, 'design.overview.state.waiting', { count: s.waiting }));
    if (s.drafts) parts.push(tr(t, 'design.overview.state.drafts', { count: s.drafts }));
    return parts.join(' · ');
  }
  if (state === 'todo' && s.id === 'schedule' && all.find((x) => x.id === 'estimate')?.done) {
    return tr(t, 'design.overview.todo.schedule_ready');
  }
  if (state === 'todo' && !(s.id === 'bim' && s.done)) return tr(t, `design.overview.todo.${s.id}`);
  if (s.id === 'tasks' && !s.count) return tr(t, 'design.overview.state.tasks_none');
  return tr(t, `design.overview.state.${s.id}`, { count: s.count ?? 0 });
}
