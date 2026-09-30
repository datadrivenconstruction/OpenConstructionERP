/**
 * What to do with a stored active project once the project list has loaded.
 *
 * A persisted id whose project is gone (hard-deleted, or no longer visible to
 * this user) made every project-scoped page answer 404. Clearing it left the
 * user on an empty "pick a project" state even when they had other projects,
 * so switch to the first project they can see and clear only when there is
 * none.
 *
 * @returns ``keep`` when the id is still listed, ``switch`` with the project
 *   to activate, or ``clear`` when the list is empty.
 */
export type StaleProjectAction =
  | { kind: 'keep' }
  | { kind: 'switch'; id: string; name: string }
  | { kind: 'clear' };

export function resolveStaleProject(
  projects: ReadonlyArray<{ id: string; name: string }>,
  activeProjectId: string,
): StaleProjectAction {
  if (projects.some((p) => p.id === activeProjectId)) return { kind: 'keep' };
  const first = projects.find((p) => typeof p?.id === 'string' && p.id);
  if (!first) return { kind: 'clear' };
  return { kind: 'switch', id: first.id, name: String(first.name ?? '') };
}
