// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The project's people, cached so the phone can offer them with no signal.
 *
 * A punch typed as a name carries no register id, and the desktop timesheet
 * reconciles on the id alone. The same person then lands on the project twice,
 * once from the phone and once from the office, and neither screen says so.
 * Picking off a list fixes that at the source, but only if the list is there
 * when the foreman is standing in a basement with no bars, which is where this
 * cache comes in.
 *
 * Held per project and refreshed whenever a fetch succeeds. A stale roster is
 * useful and a missing one is not: somebody who left last week showing on the
 * list costs a wrong pick that an approver can see, while an empty list costs
 * every punch its id.
 */

export interface CrewRosterMember {
  id: string;
  name: string;
  code: string;
  resource_type: string;
}

const ROSTER_STORAGE_PREFIX = 'oe_field_roster_v1:';

export function rosterStorageKey(projectId: string): string {
  return `${ROSTER_STORAGE_PREFIX}${projectId}`;
}

function isRosterMember(value: unknown): value is CrewRosterMember {
  if (!value || typeof value !== 'object') return false;
  const row = value as Partial<CrewRosterMember>;
  return (
    typeof row.id === 'string' &&
    row.id !== '' &&
    typeof row.name === 'string' &&
    row.name !== ''
  );
}

/** Normalise a server row, tolerating the optional fields being absent. */
function toRosterMember(value: unknown): CrewRosterMember {
  const row = value as Partial<CrewRosterMember>;
  return {
    id: String(row.id),
    name: String(row.name),
    code: typeof row.code === 'string' ? row.code : '',
    resource_type: typeof row.resource_type === 'string' ? row.resource_type : 'person',
  };
}

export function readCachedRoster(projectId: string): CrewRosterMember[] {
  if (!projectId) return [];
  try {
    const raw = window.localStorage.getItem(rosterStorageKey(projectId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isRosterMember).map(toRosterMember);
  } catch {
    return [];
  }
}

/**
 * Replace the cached roster.
 *
 * An empty list is not written. The server answering with nobody is
 * indistinguishable here from a project whose register is simply not filled in
 * yet, and overwriting a working cache with nothing would take the picker away
 * from a foreman who had it a minute ago. Clearing is a separate, deliberate
 * act.
 */
export function writeCachedRoster(projectId: string, roster: CrewRosterMember[]): void {
  if (!projectId || roster.length === 0) return;
  try {
    window.localStorage.setItem(rosterStorageKey(projectId), JSON.stringify(roster));
  } catch {
    /* Private mode, or the quota is full. The list stays in memory for this
       session, which is still better than typing names. */
  }
}

export function clearCachedRoster(projectId: string): void {
  if (!projectId) return;
  try {
    window.localStorage.removeItem(rosterStorageKey(projectId));
  } catch {
    /* nothing to do */
  }
}

/**
 * The roster minus whoever is already on today's list.
 *
 * Offering a person who is already added invites a second row for one worker,
 * and two rows punch in twice - which is the double count this whole change
 * exists to stop, arriving through the other door.
 */
export function availableRoster(
  roster: CrewRosterMember[],
  taken: readonly { resourceId: string }[],
): CrewRosterMember[] {
  const used = new Set(taken.map((m) => m.resourceId).filter(Boolean));
  return roster.filter((row) => !used.has(row.id));
}
