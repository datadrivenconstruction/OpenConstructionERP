// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The roles a person can hold on a project, and how to print them.
 *
 * One list, used by every surface that shows or sets a role: the Team Strip's
 * add / change-role dialogs, the Project-team tile, the availability popup and
 * the right-click menu. It mirrors ``PROJECT_MEMBER_ROLES`` in
 * ``backend/app/modules/projects/member_schemas.py`` — that regex is the real
 * gate, this file is the presentation of it. Adding a role means adding it in
 * both places (the backend test pins the whitelist; the vitest suite pins that
 * every key here is a known one).
 *
 * The keys are deliberately unchanged from the values already stored in
 * ``oe_teams_membership.role``, so nothing needs migrating.
 *
 * ``roleLabel()`` exists because the raw key leaks into the UI in several
 * places (``m.email · m.role`` printed "automation_engineer"). Anywhere a role
 * reaches a human it should go through this function.
 */

/** The optgroup a role sits in, in display order. */
export type ProjectRoleGroup =
  | 'project'
  | 'engineering'
  | 'workshop_site'
  | 'commercial'
  | 'external';

export interface ProjectRoleOption {
  /** Wire value — must be in the backend whitelist. */
  key: string;
  /** Human label, English default (i18n key is `projects.team.role.<key>`). */
  label: string;
  group: ProjectRoleGroup;
}

export const PROJECT_ROLE_GROUPS: readonly {
  key: ProjectRoleGroup;
  label: string;
}[] = [
  { key: 'project', label: 'Project' },
  { key: 'engineering', label: 'Engineering' },
  { key: 'workshop_site', label: 'Workshop & site' },
  { key: 'commercial', label: 'Commercial' },
  { key: 'external', label: 'External' },
] as const;

export const PROJECT_ROLES: readonly ProjectRoleOption[] = [
  /* ── Project ─────────────────────────────────────────────────────────── */
  { key: 'owner', label: 'Owner', group: 'project' },
  { key: 'lead', label: 'Project lead', group: 'project' },
  { key: 'project_manager', label: 'Project manager', group: 'project' },
  { key: 'member', label: 'Team member', group: 'project' },

  /* ── Engineering ─────────────────────────────────────────────────────── */
  { key: 'engineer', label: 'Engineer', group: 'engineering' },
  { key: 'drafter', label: 'Drafter', group: 'engineering' },
  { key: 'automation_engineer', label: 'Automation engineer', group: 'engineering' },
  { key: 'estimator', label: 'Estimator', group: 'engineering' },

  /* ── Workshop & site ─────────────────────────────────────────────────── */
  { key: 'workshop_lead', label: 'Workshop lead', group: 'workshop_site' },
  { key: 'site_supervisor', label: 'Site supervisor', group: 'workshop_site' },
  { key: 'electrician', label: 'Electrician', group: 'workshop_site' },
  { key: 'apprentice', label: 'Apprentice', group: 'workshop_site' },

  /* ── Commercial (incl. assurance) ────────────────────────────────────── */
  { key: 'contracts_admin', label: 'Contracts administrator', group: 'commercial' },
  { key: 'procurement', label: 'Procurement', group: 'commercial' },
  { key: 'hse', label: 'HSE', group: 'commercial' },
  { key: 'quality', label: 'Quality', group: 'commercial' },

  /* ── External ────────────────────────────────────────────────────────── */
  { key: 'client_contact', label: 'Client contact', group: 'external' },
  { key: 'subcontractor', label: 'Subcontractor', group: 'external' },
  { key: 'viewer', label: 'Viewer', group: 'external' },
] as const;

/**
 * Roles that can be *assigned*. ``owner`` is derived from the project's
 * ``owner_id``, and the backend refuses to hand it out (400), so offering it
 * in a picker would only produce an error the user cannot act on.
 */
export const ASSIGNABLE_PROJECT_ROLES: readonly ProjectRoleOption[] =
  PROJECT_ROLES.filter((r) => r.key !== 'owner');

const ROLE_BY_KEY: Readonly<Record<string, ProjectRoleOption>> =
  Object.fromEntries(PROJECT_ROLES.map((r) => [r.key, r]));

/** Group index, used to sort team cards by role group. */
const GROUP_ORDER: Readonly<Record<string, number>> = Object.fromEntries(
  PROJECT_ROLE_GROUPS.map((g, i) => [g.key, i]),
);

/**
 * Print a role for a human.
 *
 * Unknown keys (a legacy row, or a role added on the backend before this file
 * caught up) are de-snake-cased rather than dropped — showing
 * "Site engineer" for an unlisted `site_engineer` is honest; showing nothing
 * would hide that the row exists.
 */
export function roleLabel(role: string | null | undefined): string {
  if (!role) return '';
  const known = ROLE_BY_KEY[role];
  if (known) return known.label;
  const spaced = role.replace(/[_-]+/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** i18n key for a role label, so translators can override the English above. */
export function roleLabelKey(role: string): string {
  return `projects.team.role.${role}`;
}

/** Sort weight for a role: its group first, then its position in the list. */
export function roleSortWeight(role: string | null | undefined): number {
  const known = role ? ROLE_BY_KEY[role] : undefined;
  if (!known) return 999; // unknown roles sort last, never silently first
  const groupIdx = GROUP_ORDER[known.group] ?? 99;
  return groupIdx * 100 + PROJECT_ROLES.indexOf(known);
}

/** Roles grouped for an optgroup picker, empty groups omitted. */
export function groupedRoles(
  roles: readonly ProjectRoleOption[] = ASSIGNABLE_PROJECT_ROLES,
): { key: ProjectRoleGroup; label: string; roles: ProjectRoleOption[] }[] {
  return PROJECT_ROLE_GROUPS.map((g) => ({
    key: g.key,
    label: g.label,
    roles: roles.filter((r) => r.group === g.key),
  })).filter((g) => g.roles.length > 0);
}
