// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * TeamsPage - configure who is on a project and which records they can see.
 *
 * The backend module has existed for a while with no screen in front of it, so
 * the access-control model it implements was unreachable on every real
 * deployment. This page is that way in.
 *
 * Four tabs, answering the questions an operations lead actually asks:
 *
 *   People         Who is on this job at all - staff, subcontractor gangs and
 *                  the client side, most of whom will never hold a login. This
 *                  leads, because "who is here" comes before "who may see
 *                  what", and until it existed the module could only describe
 *                  the small minority of a site that signs in.
 *   Teams          Who is grouped how, and what does each group cover.
 *   Restricted     Which records are not open to the whole project, and can
 *                  anyone still read them.
 *   Who sees what  Per person, how much of the restricted material they still
 *                  reach - the check before a client walkthrough or a
 *                  subcontractor handover.
 *
 * Two honesty rules the UI keeps, because an access screen that overstates is
 * worse than no access screen at all:
 *
 *   - A record kind whose owning module does not filter on read yet is
 *     labelled "recorded, not enforced". It is never drawn as a lock.
 *   - A restriction whose teams have nobody on them is called out in red. That
 *     is the "we locked ourselves out" state, and it is invisible from the
 *     record's own screen.
 *
 * Writes need project ownership; the API answers 403 for a plain member. The
 * page surfaces that answer rather than hiding the controls, so a member can
 * still see what exists and who to ask.
 */

import { Fragment, useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  HardHat,
  Info,
  Loader2,
  Lock,
  Pencil,
  Plus,
  ShieldCheck,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button, Card, CollapsibleSection, EmptyState, PageHeader } from '@/shared/ui';
import { UserSearchInput } from '@/shared/ui/UserSearchInput';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  ALL_TEAM_ROLES,
  TEAM_KINDS,
  addMember,
  createTeam,
  deleteTeam,
  getAccessMatrix,
  listEntityTypes,
  listMembers,
  listRestrictedEntities,
  listTeams,
  removeMember,
  setEntityVisibility,
  updateMemberRole,
  updateTeam,
  validateProjectTeams,
  type Team,
  type TeamKind,
  type TeamRole,
  type TeamsValidationFinding,
} from './api';
import { RosterTab } from './RosterTab';
import { fmtList } from '@/shared/lib/formatters';
import { useSingleFlight } from '@/shared/hooks/useSingleFlight';

type TabId = 'people' | 'teams' | 'restricted' | 'matrix';

/** Read a backend `detail` off a failed request, falling back to the message. */
function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { body?: { detail?: string } })?.body?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return err instanceof Error && err.message ? err.message : fallback;
}

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/* ── Explainer ─────────────────────────────────────────────────────────── */

/**
 * Says out loud what a restriction is and, more importantly, what it is not.
 *
 * The dangerous misreading of a feature like this is "ticking a team grants
 * that team access". It does the opposite: it takes the record away from
 * everyone else on the project. Somebody who reads it as a grant will
 * eventually try to use it to share something outward and be surprised, so
 * step three says the direction out loud.
 */
function HowTeamVisibilityWorks() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <HardHat size={14} className="text-oe-blue" />,
      title: t('teams.flow_0_title', 'Write down who is on the job'),
      desc: t(
        'teams.flow_0_desc',
        'The roster is everyone on this project: your own staff, the subcontractor gangs, the client side. Pick them from the people the platform already knows, or type in somebody who has no account. A roster line records a person and grants nothing.',
      ),
    },
    {
      icon: <Users size={14} className="text-oe-blue" />,
      title: t('teams.flow_1_title', 'Group the people already on the project'),
      desc: t(
        'teams.flow_1_desc',
        'A team is a label over people who can reach this project. Adding somebody to a team is itself what grants them project access, which is why only the project owner may do it.',
      ),
    },
    {
      icon: <Lock size={14} className="text-oe-blue" />,
      title: t('teams.flow_2_title', 'Narrow the records that are not for everyone'),
      desc: t(
        'teams.flow_2_desc',
        'A record with no restriction is open to the whole project. Naming teams on it takes it away from everyone else, so this is a way to hide, never a way to share outward.',
      ),
    },
    {
      icon: <ShieldCheck size={14} className="text-oe-blue" />,
      title: t('teams.flow_3_title', 'Nobody gains anything from a team'),
      desc: t(
        'teams.flow_3_desc',
        'No arrangement of teams can show a person a project or a record they could not already reach. The project owner and system admins never lose their own project.',
      ),
    },
    {
      icon: <Eye size={14} className="text-oe-blue" />,
      title: t('teams.flow_4_title', 'Check it before you rely on it'),
      desc: t(
        'teams.flow_4_desc',
        'Who sees what lists every person against the restricted records they still reach. Read it before a client walkthrough, not after.',
      ),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="teams.how"
      icon={<ShieldCheck size={15} className="text-oe-blue" />}
      title={t('teams.flow_title', 'How teams and record visibility fit together')}
    >
      <p className="text-xs text-content-tertiary">
        {t(
          'teams.flow_intro',
          'Teams group the people on a project so individual records can be narrowed to the ones who should see them. Visibility here only ever subtracts: a team can take a record away from the rest of the project, and no team arrangement can hand anyone something they could not already open.',
        )}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('teams.flow_connects', 'Connects with:')}
          </span>{' '}
          <ModLink to="/projects">{t('teams.mod_projects', 'Projects')}</ModLink> ·{' '}
          <ModLink to="/users">{t('teams.mod_users', 'User management')}</ModLink> ·{' '}
          <ModLink to="/files">{t('teams.mod_files', 'Files')}</ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

/* ── Validation banner ─────────────────────────────────────────────────── */

function ValidationBanner({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['teams-validation', projectId],
    queryFn: () => validateProjectTeams(projectId),
    enabled: !!projectId,
    staleTime: 15_000,
  });

  if (isLoading || !data) return null;

  // A `skipped` report means nothing was checked. Rendering "all good" there
  // would be a lie and rendering anything at all would be noise, so only a
  // genuine pass gets the green line.
  if (data.findings.length === 0) {
    if (data.status === 'passed') {
      return (
        <div className="flex items-center gap-2 rounded-lg border border-semantic-success/40 bg-semantic-success-bg px-3 py-2 text-sm text-semantic-success">
          <CheckCircle2 size={15} />
          {t('teams.validation_clean', 'This project’s access configuration checks out.')}
        </div>
      );
    }
    return null;
  }

  const hasErrors = data.error_count > 0;

  return (
    <div
      className={clsx(
        'rounded-lg border px-3 py-2.5 text-sm',
        hasErrors
          ? 'border-semantic-error/40 bg-semantic-error-bg text-semantic-error'
          : 'border-semantic-warning/40 bg-semantic-warning-bg text-[#b45309]',
      )}
    >
      <div className="flex items-center gap-2 font-medium">
        <AlertTriangle size={15} />
        {hasErrors
          ? t('teams.validation_errors', 'Problems with this project’s access setup: {{count}}', {
              count: data.error_count + data.warning_count,
            })
          : t('teams.validation_warnings', 'Worth checking: {{count}}', {
              count: data.warning_count,
            })}
      </div>
      <ul className="mt-1.5 space-y-1 pl-6">
        {data.findings.map((f: TeamsValidationFinding, i: number) => (
          <li
            key={`${f.rule_id}-${f.element_ref ?? i}`}
            className="list-disc text-xs leading-relaxed"
          >
            {/* The English `message` is composed by the backend rule and
                already names the team or record, so it stands alone as the
                fallback. A locale that supplies `f.key` gets the rule's
                structured details through `replace` - scoped rather than
                spread, so a details field called `count` or `context` cannot
                collide with an i18next reserved option. */}
            {t(f.key, { defaultValue: f.message, replace: f.context })}
            {f.suggestion ? <span className="opacity-80"> {f.suggestion}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── Team editor ───────────────────────────────────────────────────────── */

interface TeamFormValues {
  name: string;
  description: string;
  kind: TeamKind;
  is_default: boolean;
}

const INPUT_CLASS =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

function TeamForm({
  initial,
  submitting,
  onCancel,
  onSubmit,
}: {
  initial?: Partial<TeamFormValues>;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (values: TeamFormValues) => void;
}) {
  const { t } = useTranslation();
  const [values, setValues] = useState<TeamFormValues>({
    name: initial?.name ?? '',
    description: initial?.description ?? '',
    kind: initial?.kind ?? 'internal',
    is_default: initial?.is_default ?? false,
  });

  return (
    <form
      className="space-y-3 rounded-lg border border-border bg-surface-secondary/40 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!values.name.trim()) return;
        onSubmit({ ...values, name: values.name.trim() });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-content-secondary">
            {t('teams.field_name', 'Team name')}
          </span>
          <input
            value={values.name}
            onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
            maxLength={255}
            required
            autoComplete="off"
            className={INPUT_CLASS}
            placeholder={t('teams.field_name_placeholder', 'Client-side QS')}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-content-secondary">
            {t('teams.field_kind', 'Represents')}
          </span>
          <select
            value={values.kind}
            onChange={(e) => setValues((v) => ({ ...v, kind: e.target.value as TeamKind }))}
            className={INPUT_CLASS}
          >
            {TEAM_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`teams.kind.${k}`, { defaultValue: k.charAt(0).toUpperCase() + k.slice(1) })}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">
          {t('teams.field_description', 'What this team covers')}
        </span>
        <textarea
          value={values.description}
          onChange={(e) => setValues((v) => ({ ...v, description: e.target.value }))}
          maxLength={2000}
          rows={2}
          className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          placeholder={t(
            'teams.field_description_placeholder',
            'The client’s own cost consultants. Sees the priced bill, not our internal margins.',
          )}
        />
      </label>
      <label className="flex items-center gap-2 text-sm text-content-secondary">
        <input
          type="checkbox"
          checked={values.is_default}
          onChange={(e) => setValues((v) => ({ ...v, is_default: e.target.checked }))}
          className="h-4 w-4 rounded border-border"
        />
        {t('teams.field_is_default', 'New project members land on this team')}
      </label>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={submitting || !values.name.trim()}>
          {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
          {t('teams.save', 'Save')}
        </Button>
        <Button type="button" size="sm" variant="secondary" onClick={onCancel}>
          {t('teams.cancel', 'Cancel')}
        </Button>
      </div>
    </form>
  );
}

/* ── Member list ───────────────────────────────────────────────────────── */

function MemberPanel({ team, projectId }: { team: Team; projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [adding, setAdding] = useState(false);
  const [newUserId, setNewUserId] = useState('');
  const [newUserName, setNewUserName] = useState('');
  const [newRole, setNewRole] = useState<TeamRole>('member');

  // Keyed 'teams-members', not 'team-members': the punch list already caches
  // its own member list under ['team-members', projectId]. The second element
  // differs (a team id, not a project id) so the two never actually collide,
  // but sharing a family name with a different response shape is a trap for
  // whoever next writes a prefix invalidation. Stay inside the teams- family.
  const { data: members = [], isLoading } = useQuery({
    queryKey: ['teams-members', team.id],
    queryFn: () => listMembers(team.id),
    staleTime: 15_000,
  });

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['teams-members', team.id] });
    qc.invalidateQueries({ queryKey: ['teams', projectId] });
    qc.invalidateQueries({ queryKey: ['teams-validation', projectId] });
    qc.invalidateQueries({ queryKey: ['teams-matrix', projectId] });
    qc.invalidateQueries({ queryKey: ['teams-restricted', projectId] });
  }, [qc, team.id, projectId]);

  const fail = useCallback(
    (fallback: string) => (err: unknown) =>
      addToast({
        type: 'error',
        title: t('teams.toast_error', 'Access change refused'),
        message: errorDetail(err, fallback),
      }),
    [addToast, t],
  );

  const addMutation = useMutation({
    mutationFn: () => addMember(team.id, { user_id: newUserId, role: newRole }),
    onSuccess: () => {
      setAdding(false);
      setNewUserId('');
      setNewUserName('');
      invalidate();
    },
    onError: fail(t('teams.add_member_failed', 'Could not add that person')),
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: TeamRole }) =>
      updateMemberRole(team.id, userId, role),
    onSuccess: invalidate,
    onError: fail(t('teams.change_role_failed', 'Could not change that role')),
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => removeMember(team.id, userId),
    onSuccess: invalidate,
    onError: fail(t('teams.remove_member_failed', 'Could not remove that person')),
  });

  return (
    <div className="space-y-2">
      {isLoading ? (
        <p className="text-xs text-content-tertiary">{t('teams.loading', 'Loading…')}</p>
      ) : members.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t(
            'teams.no_members',
            'Nobody on this team yet. Until somebody is, it grants nothing, and any record narrowed to it is hidden from everyone but the project owner.',
          )}
        </p>
      ) : (
        <ul className="divide-y divide-border-light">
          {members.map((m) => (
            <li key={m.id} className="flex items-center gap-2 py-1.5">
              <span className="min-w-0 flex-1 truncate text-sm text-content-primary">
                {m.full_name || m.email || m.user_id}
                {!m.is_active ? (
                  <Badge variant="warning" size="sm" className="ml-2">
                    {t('teams.member_inactive', 'Inactive')}
                  </Badge>
                ) : null}
              </span>
              <select
                value={m.role}
                onChange={(e) =>
                  roleMutation.mutate({ userId: m.user_id, role: e.target.value as TeamRole })
                }
                aria-label={t('teams.role_label', 'Role')}
                className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-xs text-content-primary focus:border-oe-blue focus:outline-none"
              >
                {ALL_TEAM_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {t(`teams.role.${r}`, { defaultValue: r.replace(/_/g, ' ') })}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => removeMutation.mutate(m.user_id)}
                aria-label={t('teams.remove_member', 'Remove from team')}
                className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <div className="space-y-2 rounded-lg border border-border bg-surface-secondary/40 p-2.5">
          <UserSearchInput
            value={newUserId}
            displayValue={newUserName}
            onChange={(id, name) => {
              setNewUserId(id);
              setNewUserName(name);
            }}
            placeholder={t('teams.find_person', 'Find a person')}
          />
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as TeamRole)}
              aria-label={t('teams.role_label', 'Role')}
              className="h-8 rounded-lg border border-border bg-surface-primary px-2 text-xs text-content-primary"
            >
              {ALL_TEAM_ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`teams.role.${r}`, { defaultValue: r.replace(/_/g, ' ') })}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              disabled={!newUserId || addMutation.isPending}
              onClick={() => addMutation.mutate()}
            >
              {t('teams.add_member', 'Add to team')}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setAdding(false)}>
              {t('teams.cancel', 'Cancel')}
            </Button>
          </div>
          <p className="text-2xs text-content-tertiary">
            {t(
              'teams.add_member_note',
              'This also grants project access, so only the project owner can do it.',
            )}
          </p>
        </div>
      ) : (
        <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
          <Plus size={14} />
          {t('teams.add_member', 'Add to team')}
        </Button>
      )}
    </div>
  );
}

/* ── Tabs ──────────────────────────────────────────────────────────────── */

function TeamsTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: teams = [], isLoading } = useQuery({
    queryKey: ['teams', projectId],
    queryFn: () => listTeams(projectId),
    enabled: !!projectId,
    staleTime: 15_000,
  });

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['teams', projectId] });
    qc.invalidateQueries({ queryKey: ['teams-validation', projectId] });
    qc.invalidateQueries({ queryKey: ['teams-matrix', projectId] });
    qc.invalidateQueries({ queryKey: ['teams-restricted', projectId] });
  }, [qc, projectId]);

  const fail = useCallback(
    (fallback: string) => (err: unknown) =>
      addToast({
        type: 'error',
        title: t('teams.toast_error', 'Access change refused'),
        message: errorDetail(err, fallback),
      }),
    [addToast, t],
  );

  const createMutationOnce = useSingleFlight();
  const createMutation = useMutation({
    mutationFn: (values: TeamFormValues) => createTeam({ project_id: projectId, ...values }),
    onSuccess: () => {
      setCreating(false);
      invalidate();
    },
    onError: fail(t('teams.create_failed', 'Could not create that team')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: TeamFormValues }) => updateTeam(id, values),
    onSuccess: () => {
      setEditingId(null);
      invalidate();
    },
    onError: fail(t('teams.update_failed', 'Could not save that team')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteTeam(id),
    onSuccess: invalidate,
    onError: fail(t('teams.delete_failed', 'Could not delete that team')),
  });

  if (isLoading) {
    return <p className="text-sm text-content-tertiary">{t('teams.loading', 'Loading…')}</p>;
  }

  return (
    <div className="space-y-3">
      {creating ? (
        <TeamForm
          submitting={createMutation.isPending}
          onCancel={() => setCreating(false)}
          onSubmit={(values) => createMutationOnce(() => createMutation.mutateAsync(values))}
        />
      ) : (
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus size={14} />
          {t('teams.new_team', 'New team')}
        </Button>
      )}

      {teams.length === 0 && !creating ? (
        <EmptyState
          icon={<Users size={28} />}
          title={t('teams.empty_title', 'No teams on this project yet')}
          description={t(
            'teams.empty_desc',
            'Group the people on this project so you can narrow individual records to the ones who should see them.',
          )}
        />
      ) : null}

      {teams.map((team) => {
        const restricted = team.restricted_record_count ?? 0;
        const stranded = team.member_count === 0 && restricted > 0;
        const isExpanded = expandedId === team.id;
        return (
          <Card key={team.id} padding="none" className="p-3">
            {editingId === team.id ? (
              <TeamForm
                initial={team}
                submitting={updateMutation.isPending}
                onCancel={() => setEditingId(null)}
                onSubmit={(values) => updateMutation.mutate({ id: team.id, values })}
              />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setExpandedId(isExpanded ? null : team.id)}
                    aria-expanded={isExpanded}
                    className="text-sm font-semibold text-content-primary hover:underline"
                  >
                    {team.name}
                  </button>
                  <Badge variant="neutral" size="sm">
                    {t(`teams.kind.${team.kind}`, { defaultValue: team.kind })}
                  </Badge>
                  {team.is_default ? (
                    <Badge variant="blue" size="sm">
                      {t('teams.badge_default', 'Default')}
                    </Badge>
                  ) : null}
                  <span className="text-xs text-content-tertiary">
                    {t('teams.member_count', 'Members: {{count}}', { count: team.member_count })}
                  </span>
                  {restricted > 0 ? (
                    <span
                      className={clsx(
                        'inline-flex items-center gap-1 text-xs',
                        stranded ? 'text-semantic-error' : 'text-content-tertiary',
                      )}
                    >
                      <Lock size={12} />
                      {t('teams.restriction_count', 'Restricted records: {{count}}', {
                        count: restricted,
                      })}
                    </span>
                  ) : null}
                  <span className="flex-1" />
                  <button
                    type="button"
                    onClick={() => setEditingId(team.id)}
                    aria-label={t('teams.edit_team', 'Edit team')}
                    className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteMutation.mutate(team.id)}
                    aria-label={t('teams.delete_team', 'Delete team')}
                    className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                {team.description ? (
                  <p className="mt-1 text-xs text-content-secondary">{team.description}</p>
                ) : null}
                {stranded ? (
                  <p className="mt-1.5 flex items-center gap-1.5 text-xs text-semantic-error">
                    <AlertTriangle size={13} />
                    {t(
                      'teams.stranded_warning',
                      'This team holds restrictions but has no members, so those records are readable by nobody except the project owner.',
                    )}
                  </p>
                ) : null}
                {isExpanded ? (
                  <div className="mt-3 border-t border-border-light pt-3">
                    <MemberPanel team={team} projectId={projectId} />
                  </div>
                ) : null}
              </>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function RestrictedTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState<{ type: string; id: string; teamIds: string[] } | null>(
    null,
  );

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['teams-restricted', projectId],
    queryFn: () => listRestrictedEntities(projectId),
    enabled: !!projectId,
    staleTime: 15_000,
  });
  const { data: teams = [] } = useQuery({
    queryKey: ['teams', projectId],
    queryFn: () => listTeams(projectId),
    enabled: !!projectId,
    staleTime: 15_000,
  });
  const { data: entityTypes = [] } = useQuery({
    queryKey: ['teams-entity-types'],
    queryFn: listEntityTypes,
    staleTime: 5 * 60_000,
  });

  const typeLabel = useMemo(() => {
    const byKey = new Map(entityTypes.map((e) => [e.key, e]));
    return (key: string) => t(`teams.entityType.${key}`, { defaultValue: byKey.get(key)?.label ?? key });
  }, [entityTypes, t]);

  const saveMutation = useMutation({
    mutationFn: ({ type, id, teamIds }: { type: string; id: string; teamIds: string[] }) =>
      setEntityVisibility(projectId, type, id, teamIds),
    onSuccess: () => {
      setEditing(null);
      qc.invalidateQueries({ queryKey: ['teams-restricted', projectId] });
      qc.invalidateQueries({ queryKey: ['teams', projectId] });
      qc.invalidateQueries({ queryKey: ['teams-validation', projectId] });
      qc.invalidateQueries({ queryKey: ['teams-matrix', projectId] });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('teams.toast_error', 'Access change refused'),
        message: errorDetail(err, t('teams.save_visibility_failed', 'Could not save that change')),
      }),
  });

  if (isLoading) {
    return <p className="text-sm text-content-tertiary">{t('teams.loading', 'Loading…')}</p>;
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Eye size={28} />}
        title={t('teams.no_restrictions_title', 'Every record on this project is open')}
        description={t(
          'teams.no_restrictions_desc',
          'Nothing here is narrowed to a team yet. Restrict a record from its own screen and it appears in this register.',
        )}
      />
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-content-secondary">
        {t(
          'teams.restricted_intro',
          'These records are not open to the whole project. Everything not listed here follows plain project access.',
        )}
      </p>
      {rows.map((row) => {
        const isEditing = editing?.type === row.entity_type && editing?.id === row.entity_id;
        return (
          <Card key={`${row.entity_type}/${row.entity_id}`} padding="none" className="p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Lock size={14} className="text-content-tertiary" />
              <span className="text-sm font-medium text-content-primary">
                {typeLabel(row.entity_type)}
              </span>
              <code className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-secondary">
                {row.entity_id}
              </code>
              {!row.enforced ? (
                <Badge variant="warning" size="sm">
                  <Info size={11} className="mr-1 inline" />
                  {t('teams.not_enforced', 'Recorded, not enforced')}
                </Badge>
              ) : null}
              <span className="flex-1" />
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  setEditing(
                    isEditing
                      ? null
                      : { type: row.entity_type, id: row.entity_id, teamIds: [...row.team_ids] },
                  )
                }
              >
                {t('teams.change_who_sees', 'Change who sees this')}
              </Button>
            </div>
            <p className="mt-1.5 text-xs text-content-secondary">
              {t('teams.visible_to', 'Visible to')}: {fmtList(row.team_names)}
            </p>
            <p
              className={clsx(
                'mt-0.5 flex items-center gap-1.5 text-xs',
                row.viewer_count === 0 ? 'text-semantic-error' : 'text-content-tertiary',
              )}
            >
              {row.viewer_count === 0 ? <EyeOff size={12} /> : <Eye size={12} />}
              {row.viewer_count === 0
                ? t(
                    'teams.no_viewers',
                    'Nobody except the project owner and system admins can open this.',
                  )
                : t('teams.viewer_count', 'People who can open this: {{count}}', {
                    count: row.viewer_count,
                  })}
            </p>
            {!row.enforced ? (
              <p className="mt-0.5 text-2xs text-content-tertiary">
                {t(
                  'teams.not_enforced_hint',
                  'This record kind does not filter on read yet, so the restriction is stored and reported but hides nothing. Do not rely on it as a lock.',
                )}
              </p>
            ) : null}

            {isEditing && editing ? (
              <div className="mt-3 space-y-2 border-t border-border-light pt-3">
                {teams.map((team) => (
                  <label key={team.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={editing.teamIds.includes(team.id)}
                      onChange={(e) =>
                        setEditing((cur) =>
                          cur
                            ? {
                                ...cur,
                                teamIds: e.target.checked
                                  ? [...cur.teamIds, team.id]
                                  : cur.teamIds.filter((id) => id !== team.id),
                              }
                            : cur,
                        )
                      }
                      className="h-4 w-4 rounded border-border"
                    />
                    <span className="text-content-primary">{team.name}</span>
                    <span className="text-xs text-content-tertiary">
                      {t('teams.member_count', 'Members: {{count}}', { count: team.member_count })}
                    </span>
                  </label>
                ))}
                <p className="text-2xs text-content-tertiary">
                  {t(
                    'teams.clear_to_open',
                    'Clear every box to lift the restriction and return this record to everyone on the project.',
                  )}
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    disabled={saveMutation.isPending}
                    onClick={() => saveMutation.mutate(editing)}
                  >
                    {saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
                    {t('teams.save', 'Save')}
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => setEditing(null)}>
                    {t('teams.cancel', 'Cancel')}
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
        );
      })}
    </div>
  );
}

function MatrixTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['teams-matrix', projectId],
    queryFn: () => getAccessMatrix(projectId),
    enabled: !!projectId,
    staleTime: 15_000,
  });

  if (isLoading) {
    return <p className="text-sm text-content-tertiary">{t('teams.loading', 'Loading…')}</p>;
  }
  if (!data || data.members.length === 0) {
    return (
      <EmptyState
        icon={<Users size={28} />}
        title={t('teams.matrix_empty_title', 'Nobody is on a team yet')}
        description={t(
          'teams.matrix_empty_desc',
          'Put people on teams and this becomes the one screen that answers who can still open what.',
        )}
      />
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-content-secondary">
        {t(
          'teams.matrix_intro',
          'Restricted records on this project: {{count}}. The table shows how many of them each person can still open.',
          { count: data.restricted_record_count },
        )}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="py-2 pr-3 font-medium">{t('teams.col_person', 'Person')}</th>
              <th className="py-2 pr-3 font-medium">{t('teams.col_teams', 'Teams')}</th>
              <th className="py-2 pr-3 font-medium">{t('teams.col_can_open', 'Can open')}</th>
              <th className="py-2 font-medium">{t('teams.col_hidden', 'Hidden from them')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {data.members.map((m) => (
              <tr key={m.user_id}>
                <td className="py-2 pr-3">
                  <span className="text-content-primary">
                    {m.full_name || m.email || m.user_id}
                  </span>
                  {m.is_project_owner ? (
                    <Badge variant="blue" size="sm" className="ml-2">
                      {t('teams.badge_owner', 'Owner')}
                    </Badge>
                  ) : null}
                  {m.is_system_admin ? (
                    <Badge variant="neutral" size="sm" className="ml-2">
                      {t('teams.badge_admin', 'Admin')}
                    </Badge>
                  ) : null}
                </td>
                <td className="py-2 pr-3 text-xs text-content-secondary">
                  {fmtList(m.team_names)}
                </td>
                <td className="py-2 pr-3 text-content-primary">{m.visible_restricted_count}</td>
                <td
                  className={clsx(
                    'py-2',
                    m.hidden_restricted_count > 0 ? 'text-[#b45309]' : 'text-content-tertiary',
                  )}
                >
                  {m.hidden_restricted_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export function TeamsPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  // People leads. "Who is on this job" is the question somebody opens this
  // screen with; "who may see what" is the one they get to afterwards.
  const [tab, setTab] = useState<TabId>('people');

  const tabs: { id: TabId; label: string }[] = [
    { id: 'people', label: t('teams.tab_people', 'People on the project') },
    { id: 'teams', label: t('teams.tab_teams', 'Teams') },
    { id: 'restricted', label: t('teams.tab_restricted', 'Restricted records') },
    { id: 'matrix', label: t('teams.tab_matrix', 'Who sees what') },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('teams.title', 'Teams and visibility')}
        subtitle={t(
          'teams.subtitle',
          'Group the people on this project, and narrow individual records to the teams that should see them',
        )}
      />
      <RequiresProject
        emptyHint={t(
          'teams.select_project_hint',
          'Teams and record visibility are configured per project. Pick one to continue.',
        )}
      >
        <div className="space-y-4">
          {/* The explainer sits above the tab strip. Inside a tab it would
              vanish on switch, and a user who cannot find the explanation
              again stops believing there is one. */}
          <HowTeamVisibilityWorks />
          <ValidationBanner projectId={projectId} />
          <div className="flex gap-1 border-b border-border">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                aria-current={tab === item.id ? 'page' : undefined}
                className={clsx(
                  '-mb-px border-b-2 px-3 py-2 text-sm',
                  tab === item.id
                    ? 'border-oe-blue font-medium text-content-primary'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          {tab === 'people' ? <RosterTab projectId={projectId} /> : null}
          {tab === 'teams' ? <TeamsTab projectId={projectId} /> : null}
          {tab === 'restricted' ? <RestrictedTab projectId={projectId} /> : null}
          {tab === 'matrix' ? <MatrixTab projectId={projectId} /> : null}
        </div>
      </RequiresProject>
    </div>
  );
}

export default TeamsPage;
