// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - pure progress helpers.
//
// Deliberately framework-free (no React, no store, no localStorage) so they
// are trivially unit-testable and reusable. The zustand store and the runner
// component are thin wrappers over these.

import type { Playbook, PlaybookProgress } from './types';

/** A fresh, empty progress record (new object each call - safe to mutate). */
export function emptyProgress(): PlaybookProgress {
  return { completedStepIds: [], currentStepIndex: 0 };
}

/**
 * Stable storage/run key for a playbook, optionally scoped to a project.
 * Scoping by project keeps progress independent when the same case is learned
 * on two different sample projects.
 */
export function runKey(playbookId: string, projectId?: string | null): string {
  return projectId ? `${playbookId}::${projectId}` : playbookId;
}

/** True when the given step id is marked complete. */
export function isStepDone(progress: PlaybookProgress, stepId: string): boolean {
  return progress.completedStepIds.includes(stepId);
}

/**
 * Number of the playbook's OWN steps that are complete. Stale ids (a step
 * removed from the data file after a user completed it) are ignored, so the
 * count can never exceed the real step total.
 */
export function completedCount(progress: PlaybookProgress, playbook: Playbook): number {
  const done = new Set(progress.completedStepIds);
  return playbook.steps.reduce((n, step) => (done.has(step.id) ? n + 1 : n), 0);
}

/** True when every step in the playbook is complete (and it has at least one). */
export function isPlaybookDone(progress: PlaybookProgress, playbook: Playbook): boolean {
  return (
    playbook.steps.length > 0 &&
    completedCount(progress, playbook) === playbook.steps.length
  );
}

/**
 * Index of the first incomplete step. When every step is done it clamps to the
 * last step so the runner always has a valid focus target. An empty playbook
 * resolves to 0.
 */
export function nextStepIndex(progress: PlaybookProgress, playbook: Playbook): number {
  const done = new Set(progress.completedStepIds);
  const idx = playbook.steps.findIndex((step) => !done.has(step.id));
  if (idx >= 0) return idx;
  return Math.max(0, playbook.steps.length - 1);
}

/** Whole-number completion percentage (0..100). Empty playbook -> 0. */
export function progressPct(progress: PlaybookProgress, playbook: Playbook): number {
  if (playbook.steps.length === 0) return 0;
  return Math.round((completedCount(progress, playbook) / playbook.steps.length) * 100);
}

/**
 * Pure toggle: returns a NEW progress with `stepId` added to (or removed from)
 * the completed set. Never mutates the input.
 */
export function toggleStep(progress: PlaybookProgress, stepId: string): PlaybookProgress {
  const has = progress.completedStepIds.includes(stepId);
  return {
    ...progress,
    completedStepIds: has
      ? progress.completedStepIds.filter((id) => id !== stepId)
      : [...progress.completedStepIds, stepId],
  };
}

/** Clamp an arbitrary index into `[0, total - 1]` (or 0 for an empty list). */
export function clampStepIndex(index: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(Math.max(0, index), total - 1);
}

/**
 * Resolve a step route for navigation.
 *
 *  - With a project: fill the `:projectId` slot.
 *  - Without a project: strip the leading `/projects/:projectId` segment so the
 *    module opens unscoped.
 *  - Without a project, for a case whose screens only exist inside a project
 *    (`requiresProject`): the project list, so the reader picks one instead of
 *    landing on a stripped path that names no screen or the wrong one.
 *  - No slot: returned unchanged (query strings are preserved).
 */
export function resolveStepRoute(
  to: string,
  projectId: string | null,
  requiresProject = false,
): string {
  if (!to.includes(':projectId')) return to;
  if (projectId) return to.replace(':projectId', projectId);
  if (requiresProject) return '/projects';
  const stripped = to.replace(/^\/projects\/:projectId/, '');
  if (stripped === '') return '/';
  return stripped.startsWith('/') ? stripped : `/${stripped}`;
}
