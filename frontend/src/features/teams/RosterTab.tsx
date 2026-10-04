// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RosterTab - who is actually on this job.
 *
 * The rest of this module answers "who may see what". That is an access
 * question, and it can only ever describe people who hold a login. A building
 * site is not made of logins: the concrete gang, the client's surveyor and the
 * safety officer are all on the project, and most of them will never sign in.
 * Until this tab existed there was nowhere to write them down, which is why
 * "how a team is assembled" had no answer on screen.
 *
 * A roster line is a record of a person, not a permission. Adding somebody
 * here grants nothing - that is what lets the list hold subcontractors and
 * client staff safely, and it is said out loud in the access column rather
 * than left for someone to discover.
 *
 * The screen leads with the summary because the questions a site manager
 * arrives with are counts: how many people, from how many firms, how many
 * tickets have run out. The table under it answers "which ones".
 */

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Building2,
  CalendarClock,
  HardHat,
  Pencil,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import clsx from 'clsx';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  StatCard,
  WideModal,
  WideModalField,
  WideModalSection,
} from '@/shared/ui';
import { useIntlLocale } from '@/shared/lib/intlLocale';
import { useNumberLocale } from '@/stores/usePreferencesStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  addRosterMembers,
  getRosterSummary,
  getRosterVocabulary,
  listRoster,
  listRosterCandidates,
  listTeams,
  removeRosterMember,
  updateRosterMember,
  type RosterCandidate,
  type RosterMember,
  type RosterMemberInput,
  type RosterVocabularyEntry,
} from './api';
import { fmtList } from '@/shared/lib/formatters';

/** Days left on a ticket below which it is worth warning about. */
const TICKET_WARN_DAYS = 30;

const INPUT_CLASS =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** Read a backend `detail` off a failed request, falling back to the message. */
function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { body?: { detail?: string } })?.body?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * The two closed vocabularies a roster line is written in.
 *
 * Fetched once and cached for the session: trades and site roles are a
 * deployment constant, not project data.
 */
function useRosterVocabulary() {
  return useQuery({
    queryKey: ['roster-vocabulary'],
    queryFn: getRosterVocabulary,
    staleTime: 60 * 60_000,
  });
}

/* ── Small pieces ──────────────────────────────────────────────────────── */

/**
 * One ticket, coloured by how much life is left in it.
 *
 * Each ticket is its own chip rather than a count, so the reader sees which
 * card has run out. "Two expired" sends somebody hunting; "First aid at work"
 * tells them who to call.
 */
function TicketChip({ cert }: { cert: RosterMember['certifications'][number] }) {
  const { t } = useTranslation();
  const locale = useIntlLocale();
  const soon =
    !cert.expired && cert.days_remaining !== null && cert.days_remaining <= TICKET_WARN_DAYS;
  const until = cert.valid_until
    ? new Date(`${cert.valid_until}T00:00:00`).toLocaleDateString(locale)
    : '';
  const state = cert.expired
    ? t('teams.roster_ticket_expired', 'Expired')
    : soon
      ? t('teams.roster_ticket_soon', 'Expires soon')
      : t('teams.roster_ticket_valid', 'Valid');

  return (
    <span
      title={until ? `${cert.kind} · ${state} · ${until}` : `${cert.kind} · ${state}`}
      className={clsx(
        'inline-flex max-w-[13rem] items-center gap-1 truncate rounded px-1.5 py-0.5 text-2xs',
        cert.expired
          ? 'bg-semantic-error-bg text-semantic-error'
          : soon
            ? 'bg-semantic-warning-bg text-semantic-warning'
            : 'bg-surface-tertiary text-content-tertiary',
      )}
    >
      {cert.expired || soon ? <AlertTriangle size={10} className="shrink-0" /> : null}
      <span className="truncate">{cert.kind}</span>
    </span>
  );
}

/** Headline counts. The answer before the list. */
function RosterSummaryBand({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['roster-summary', projectId],
    queryFn: () => getRosterSummary(projectId),
    enabled: !!projectId,
    staleTime: 15_000,
  });

  if (!data || data.headcount === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
      <StatCard
        label={t('teams.roster_stat_headcount', 'On the roster')}
        value={data.headcount}
        sub={t('teams.roster_stat_headcount_sub', 'people recorded on this project')}
        icon={Users}
        tone="blue"
      />
      <StatCard
        label={t('teams.roster_stat_companies', 'Firms')}
        value={data.company_count}
        sub={t('teams.roster_stat_companies_sub', 'distinct companies on site')}
        icon={Building2}
      />
      <StatCard
        label={t('teams.roster_stat_no_access', 'Without a login')}
        value={data.without_access_count}
        sub={t('teams.roster_stat_no_access_sub', 'normal for site staff, they need no account')}
        icon={HardHat}
      />
      <StatCard
        label={t('teams.roster_stat_expired', 'Expired tickets')}
        value={data.expired_certification_count}
        sub={t('teams.roster_stat_expired_sub', 'check before the next induction')}
        icon={AlertTriangle}
        tone={data.expired_certification_count > 0 ? 'danger' : 'default'}
        tintValue={data.expired_certification_count > 0}
      />
      <StatCard
        label={t('teams.roster_stat_unrostered', 'Members not on the roster')}
        value={data.unrostered_member_count}
        sub={t('teams.roster_stat_unrostered_sub', 'they hold access but nobody wrote them down')}
        icon={ShieldCheck}
        tone={data.unrostered_member_count > 0 ? 'warning' : 'default'}
      />
    </div>
  );
}

/* ── Add people ────────────────────────────────────────────────────────── */

/** One person picked in the drawer, before they become a roster line. */
interface PickedPerson {
  /** Stable key for React and for de-duplication within the selection. */
  key: string;
  name: string;
  source: 'user' | 'contact' | 'manual';
  user_id?: string;
  contact_id?: string;
  company_name: string;
}

function candidateKey(c: RosterCandidate): string {
  return `${c.source}:${c.id}`;
}

/**
 * The drawer that answers "how do I assemble a team".
 *
 * Tick people the platform already knows - platform users and address-book
 * contacts in one list - or type in somebody it does not. Then set the trade,
 * the site role and the team once for the whole selection, because that is how
 * people are actually added: a gang at a time, not one form per person.
 */
function AddPeopleModal({
  projectId,
  open,
  onClose,
  trades,
  siteRoles,
}: {
  projectId: string;
  open: boolean;
  onClose: () => void;
  trades: RosterVocabularyEntry[];
  siteRoles: RosterVocabularyEntry[];
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [search, setSearch] = useState('');
  const [picked, setPicked] = useState<PickedPerson[]>([]);
  const [manualName, setManualName] = useState('');
  const [teamId, setTeamId] = useState('');
  const [trade, setTrade] = useState('');
  const [siteRole, setSiteRole] = useState('');
  const [company, setCompany] = useState('');
  const [startsOn, setStartsOn] = useState('');
  const [allocation, setAllocation] = useState('');
  const [grantAccess, setGrantAccess] = useState(false);

  const { data: candidates = [], isLoading } = useQuery({
    queryKey: ['roster-candidates', projectId, search],
    queryFn: () => listRosterCandidates(projectId, { q: search, limit: 60 }).then((page) => page.items),
    enabled: open && !!projectId,
    staleTime: 30_000,
  });

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', projectId],
    queryFn: () => listTeams(projectId),
    enabled: open && !!projectId,
  });

  const pickedKeys = useMemo(() => new Set(picked.map((p) => p.key)), [picked]);
  const anyUserPicked = picked.some((p) => p.source === 'user');

  const reset = useCallback(() => {
    setSearch('');
    setPicked([]);
    setManualName('');
    setTeamId('');
    setTrade('');
    setSiteRole('');
    setCompany('');
    setStartsOn('');
    setAllocation('');
    setGrantAccess(false);
  }, []);

  const toggle = useCallback((c: RosterCandidate) => {
    const key = candidateKey(c);
    setPicked((prev) => {
      if (prev.some((p) => p.key === key)) return prev.filter((p) => p.key !== key);
      return [
        ...prev,
        {
          key,
          name: c.name,
          source: c.source,
          user_id: c.source === 'user' ? c.id : undefined,
          contact_id: c.source === 'contact' ? c.id : undefined,
          company_name: c.company_name,
        },
      ];
    });
  }, []);

  const addManual = useCallback(() => {
    const name = manualName.trim();
    if (!name) return;
    setPicked((prev) => [
      ...prev,
      { key: `manual:${name}:${prev.length}`, name, source: 'manual', company_name: '' },
    ]);
    setManualName('');
  }, [manualName]);

  const mutation = useMutation({
    mutationFn: () => {
      const allocationValue = allocation.trim() ? Number(allocation) : null;
      const members: RosterMemberInput[] = picked.map((p) => ({
        user_id: p.user_id ?? null,
        contact_id: p.contact_id ?? null,
        display_name: p.source === 'manual' ? p.name : '',
        team_id: teamId || null,
        trade,
        site_role: siteRole,
        // A firm typed once for the whole selection must not wipe the one a
        // contact already carries, so it is only sent when it was filled in.
        ...(company.trim() ? { company_name: company.trim() } : {}),
        starts_on: startsOn || null,
        allocation_percent: Number.isFinite(allocationValue) ? allocationValue : null,
        grant_project_access: grantAccess && p.source === 'user',
      }));
      return addRosterMembers(projectId, members);
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['roster', projectId] });
      qc.invalidateQueries({ queryKey: ['roster-summary', projectId] });
      qc.invalidateQueries({ queryKey: ['roster-candidates', projectId] });
      qc.invalidateQueries({ queryKey: ['teams', projectId] });
      qc.invalidateQueries({ queryKey: ['teams-validation', projectId] });
      addToast({
        type: 'success',
        title: t('teams.roster_added', 'Added to the roster'),
        message:
          created.length === picked.length
            ? undefined
            : t('teams.roster_added_some', 'Anybody already on the roster was left as they were.'),
      });
      reset();
      onClose();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('teams.roster_add_failed', 'Could not add these people'),
        message: errorDetail(err, t('teams.roster_add_failed', 'Could not add these people')),
      });
    },
  });

  return (
    <WideModal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title={t('teams.roster_add_title', 'Add people to the project')}
      subtitle={t(
        'teams.roster_add_subtitle',
        'Tick anybody the platform already knows - their name, firm and contact details come with them. Somebody who has no account can be typed in: being on the roster needs no login.',
      )}
      size="xl"
      busy={mutation.isPending}
      footer={
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-content-tertiary">
            {picked.length > 0
              ? fmtList(picked.map((p) => p.name))
              : t('teams.roster_pick_someone', 'Pick at least one person')}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                reset();
                onClose();
              }}
            >
              {t('teams.roster_cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => mutation.mutate()}
              disabled={picked.length === 0 || mutation.isPending}
            >
              {t('teams.roster_add_submit', 'Add to roster')}
            </Button>
          </div>
        </div>
      }
    >
      <WideModalSection
        title={t('teams.roster_add_who', 'Who is joining')}
        description={t(
          'teams.roster_add_who_desc',
          'Platform users and address-book contacts, in one list.',
        )}
        columns={1}
      >
        <WideModalField span={3}>
          <div className="relative">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('teams.roster_add_search', 'Search users and contacts')}
              className={`${INPUT_CLASS} pl-8`}
            />
          </div>

          <div className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-border-light">
            {isLoading ? (
              <p className="p-3 text-xs text-content-tertiary">
                {t('teams.roster_loading', 'Loading')}
              </p>
            ) : candidates.length === 0 ? (
              <p className="p-3 text-xs text-content-tertiary">
                {t('teams.roster_add_none', 'Nobody matches that search')}
              </p>
            ) : (
              candidates.map((c) => {
                const key = candidateKey(c);
                const checked = pickedKeys.has(key);
                return (
                  <label
                    key={key}
                    className={clsx(
                      'flex items-center gap-2.5 border-b border-border-light px-3 py-2 text-sm last:border-b-0',
                      c.on_roster
                        ? 'cursor-default opacity-60'
                        : 'cursor-pointer hover:bg-surface-secondary',
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked || c.on_roster}
                      disabled={c.on_roster}
                      onChange={() => toggle(c)}
                      className="h-4 w-4 shrink-0 rounded border-border"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-content-primary">{c.name}</span>
                      <span className="block truncate text-2xs text-content-tertiary">
                        {[c.company_name, c.email].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                    <Badge variant={c.source === 'user' ? 'blue' : 'neutral'} size="sm">
                      {c.source === 'user'
                        ? t('teams.roster_source_user', 'Has a login')
                        : t('teams.roster_source_contact', 'From contacts')}
                    </Badge>
                    {c.on_roster ? (
                      <span className="shrink-0 text-2xs text-content-tertiary">
                        {t('teams.roster_add_already', 'Already on the roster')}
                      </span>
                    ) : null}
                  </label>
                );
              })
            )}
          </div>

          <div className="mt-2 flex items-end gap-2">
            <div className="flex-1">
              <label
                htmlFor="roster-manual-name"
                className="mb-1 block text-2xs text-content-tertiary"
              >
                {t('teams.roster_add_manual', 'Not in the list? Type a name')}
              </label>
              <input
                id="roster-manual-name"
                type="text"
                value={manualName}
                onChange={(e) => setManualName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addManual();
                  }
                }}
                className={INPUT_CLASS}
              />
            </div>
            <Button variant="secondary" onClick={addManual} disabled={!manualName.trim()}>
              <UserPlus size={14} />
              {t('teams.roster_add_manual_action', 'Add by name')}
            </Button>
          </div>

          {picked.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {picked.map((p) => (
                <span
                  key={p.key}
                  className="inline-flex items-center gap-1 rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs text-oe-blue-text"
                >
                  {p.name}
                  <button
                    type="button"
                    onClick={() => setPicked((prev) => prev.filter((x) => x.key !== p.key))}
                    aria-label={t('teams.roster_remove_pick', 'Remove from the selection')}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          ) : null}
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('teams.roster_add_common', 'Apply to everyone you picked')}
        description={t(
          'teams.roster_add_common_desc',
          'Optional, and changeable per person afterwards. Set here because people arrive a gang at a time.',
        )}
        columns={3}
      >
        <WideModalField label={t('teams.roster_field_team', 'Team')} htmlFor="roster-add-team">
          <select
            id="roster-add-team"
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            className={INPUT_CLASS}
          >
            <option value="">{t('teams.roster_no_team', 'No team')}</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('teams.roster_field_trade', 'Trade')} htmlFor="roster-add-trade">
          <select
            id="roster-add-trade"
            value={trade}
            onChange={(e) => setTrade(e.target.value)}
            className={INPUT_CLASS}
          >
            <option value="">{t('teams.roster_no_trade', 'No trade')}</option>
            {trades.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {t(`teams.trade_${entry.key}`, { defaultValue: entry.label })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField label={t('teams.roster_field_role', 'Site role')} htmlFor="roster-add-role">
          <select
            id="roster-add-role"
            value={siteRole}
            onChange={(e) => setSiteRole(e.target.value)}
            className={INPUT_CLASS}
          >
            <option value="">{t('teams.roster_no_role', 'No site role')}</option>
            {siteRoles.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {t(`teams.site_role_${entry.key}`, { defaultValue: entry.label })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('teams.roster_field_company', 'Firm')}
          hint={t('teams.roster_company_hint', 'Left as it is when blank')}
          htmlFor="roster-add-company"
        >
          <input
            id="roster-add-company"
            type="text"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className={INPUT_CLASS}
          />
        </WideModalField>

        <WideModalField label={t('teams.roster_field_starts', 'First day')} htmlFor="roster-add-start">
          <input
            id="roster-add-start"
            type="date"
            value={startsOn}
            onChange={(e) => setStartsOn(e.target.value)}
            className={INPUT_CLASS}
          />
        </WideModalField>

        <WideModalField
          label={t('teams.roster_field_allocation', 'Allocation %')}
          hint={t('teams.roster_allocation_hint', 'Share of their time on this project')}
          htmlFor="roster-add-allocation"
        >
          <input
            id="roster-add-allocation"
            type="number"
            min={0}
            max={100}
            value={allocation}
            onChange={(e) => setAllocation(e.target.value)}
            className={INPUT_CLASS}
          />
        </WideModalField>

        {anyUserPicked ? (
          <WideModalField span={3}>
            <label className="flex items-start gap-2 text-xs text-content-secondary">
              <input
                type="checkbox"
                checked={grantAccess}
                onChange={(e) => setGrantAccess(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-border"
              />
              <span>
                {t(
                  'teams.roster_grant_access',
                  'Also give the people who have an account access to this project',
                )}
                <span className="mt-0.5 block text-2xs text-content-tertiary">
                  {t(
                    'teams.roster_grant_hint',
                    'Only the project owner may do this, and the whole request is refused if you may not. Leave it off and the roster grants nothing, which is the usual case.',
                  )}
                </span>
              </span>
            </label>
          </WideModalField>
        ) : null}
      </WideModalSection>
    </WideModal>
  );
}

/* ── Edit one line ─────────────────────────────────────────────────────── */

function EditMemberModal({
  projectId,
  member,
  onClose,
  trades,
  siteRoles,
}: {
  projectId: string;
  member: RosterMember | null;
  onClose: () => void;
  trades: RosterVocabularyEntry[];
  siteRoles: RosterVocabularyEntry[];
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', projectId],
    queryFn: () => listTeams(projectId),
    enabled: !!member && !!projectId,
  });

  const [form, setForm] = useState<RosterMemberInput>({});
  const [certs, setCerts] = useState<{ kind: string; valid_until: string }[]>([]);
  const [loadedFor, setLoadedFor] = useState<string>('');

  // Load the open line into the form once per member, without an effect: the
  // render that first sees a new member is the render that seeds the fields.
  if (member && loadedFor !== member.id) {
    setLoadedFor(member.id);
    setForm({
      display_name: member.display_name,
      company_name: member.company_name,
      trade: member.trade,
      site_role: member.site_role,
      email: member.email,
      phone: member.phone,
      team_id: member.team_id,
      starts_on: member.starts_on,
      ends_on: member.ends_on,
      allocation_percent: member.allocation_percent,
      notes: member.notes,
      is_active: member.is_active,
    });
    setCerts(
      member.certifications.map((c) => ({ kind: c.kind, valid_until: c.valid_until ?? '' })),
    );
  }

  const set = useCallback(<K extends keyof RosterMemberInput>(k: K, v: RosterMemberInput[K]) => {
    setForm((prev) => ({ ...prev, [k]: v }));
  }, []);

  // Reopening a line must show what is stored, not the edits somebody walked
  // away from with Cancel, so the seed marker is cleared on the way out.
  const close = useCallback(() => {
    setLoadedFor('');
    onClose();
  }, [onClose]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!member) throw new Error('no member');
      return updateRosterMember(projectId, member.id, {
        ...form,
        certifications: certs
          .filter((c) => c.kind.trim())
          .map((c) => ({ kind: c.kind.trim(), valid_until: c.valid_until || null })),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['roster', projectId] });
      qc.invalidateQueries({ queryKey: ['roster-summary', projectId] });
      qc.invalidateQueries({ queryKey: ['teams-validation', projectId] });
      addToast({ type: 'success', title: t('teams.roster_saved', 'Roster updated') });
      close();
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('teams.roster_save_failed', 'Could not save this line'),
        message: errorDetail(err, t('teams.roster_save_failed', 'Could not save this line')),
      });
    },
  });

  if (!member) return null;

  return (
    <WideModal
      open={!!member}
      onClose={close}
      title={member.display_name}
      subtitle={t('teams.roster_edit_subtitle', 'What this person does on the project')}
      size="lg"
      busy={mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={close}>
            {t('teams.roster_cancel', 'Cancel')}
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {t('teams.roster_save', 'Save')}
          </Button>
        </div>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('teams.roster_field_name', 'Name')} htmlFor="roster-edit-name">
          <input
            id="roster-edit-name"
            type="text"
            value={form.display_name ?? ''}
            onChange={(e) => set('display_name', e.target.value)}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('teams.roster_field_company', 'Firm')} htmlFor="roster-edit-company">
          <input
            id="roster-edit-company"
            type="text"
            value={form.company_name ?? ''}
            onChange={(e) => set('company_name', e.target.value)}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('teams.roster_field_trade', 'Trade')} htmlFor="roster-edit-trade">
          <select
            id="roster-edit-trade"
            value={form.trade ?? ''}
            onChange={(e) => set('trade', e.target.value)}
            className={INPUT_CLASS}
          >
            <option value="">{t('teams.roster_no_trade', 'No trade')}</option>
            {trades.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {t(`teams.trade_${entry.key}`, { defaultValue: entry.label })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('teams.roster_field_role', 'Site role')} htmlFor="roster-edit-role">
          <select
            id="roster-edit-role"
            value={form.site_role ?? ''}
            onChange={(e) => set('site_role', e.target.value)}
            className={INPUT_CLASS}
          >
            <option value="">{t('teams.roster_no_role', 'No site role')}</option>
            {siteRoles.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {t(`teams.site_role_${entry.key}`, { defaultValue: entry.label })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('teams.roster_field_team', 'Team')} htmlFor="roster-edit-team">
          <select
            id="roster-edit-team"
            value={form.team_id ?? ''}
            onChange={(e) => set('team_id', e.target.value || null)}
            className={INPUT_CLASS}
          >
            <option value="">{t('teams.roster_no_team', 'No team')}</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('teams.roster_field_allocation', 'Allocation %')}
          htmlFor="roster-edit-allocation"
        >
          <input
            id="roster-edit-allocation"
            type="number"
            min={0}
            max={100}
            value={form.allocation_percent ?? ''}
            onChange={(e) =>
              set('allocation_percent', e.target.value === '' ? null : Number(e.target.value))
            }
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('teams.roster_field_starts', 'First day')} htmlFor="roster-edit-start">
          <input
            id="roster-edit-start"
            type="date"
            value={form.starts_on ?? ''}
            onChange={(e) => set('starts_on', e.target.value || null)}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('teams.roster_field_ends', 'Last day')} htmlFor="roster-edit-end">
          <input
            id="roster-edit-end"
            type="date"
            value={form.ends_on ?? ''}
            onChange={(e) => set('ends_on', e.target.value || null)}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('teams.roster_field_email', 'Email')} htmlFor="roster-edit-email">
          <input
            id="roster-edit-email"
            type="email"
            value={form.email ?? ''}
            onChange={(e) => set('email', e.target.value)}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('teams.roster_field_phone', 'Phone')} htmlFor="roster-edit-phone">
          <input
            id="roster-edit-phone"
            type="text"
            value={form.phone ?? ''}
            onChange={(e) => set('phone', e.target.value)}
            className={INPUT_CLASS}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('teams.roster_tickets_title', 'Tickets and competencies')}
        description={t(
          'teams.roster_tickets_desc',
          'The cards that let this person onto site. Only the expiry date is checked, so the name of the card can be whatever your jurisdiction calls it.',
        )}
        columns={1}
      >
        <WideModalField span={3}>
          {certs.map((c, i) => (
            <div key={i} className="mb-2 flex items-center gap-2">
              <input
                type="text"
                value={c.kind}
                placeholder={t('teams.roster_ticket_kind', 'Card or competency')}
                onChange={(e) =>
                  setCerts((prev) =>
                    prev.map((x, j) => (i === j ? { ...x, kind: e.target.value } : x)),
                  )
                }
                className={`${INPUT_CLASS} flex-1`}
              />
              <input
                type="date"
                value={c.valid_until}
                aria-label={t('teams.roster_ticket_until', 'Valid until')}
                onChange={(e) =>
                  setCerts((prev) =>
                    prev.map((x, j) => (i === j ? { ...x, valid_until: e.target.value } : x)),
                  )
                }
                className={`${INPUT_CLASS} w-40`}
              />
              <button
                type="button"
                onClick={() => setCerts((prev) => prev.filter((_, j) => j !== i))}
                aria-label={t('teams.roster_ticket_remove', 'Remove this ticket')}
                className="p-1 text-content-tertiary hover:text-semantic-error"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <Button
            variant="secondary"
            onClick={() => setCerts((prev) => [...prev, { kind: '', valid_until: '' }])}
          >
            <Plus size={14} />
            {t('teams.roster_ticket_add', 'Add a ticket')}
          </Button>
        </WideModalField>
      </WideModalSection>

      <WideModalSection columns={1}>
        <WideModalField label={t('teams.roster_field_notes', 'Notes')} span={3} htmlFor="roster-edit-notes">
          <textarea
            id="roster-edit-notes"
            rows={2}
            value={form.notes ?? ''}
            onChange={(e) => set('notes', e.target.value)}
            className="w-full rounded-lg border border-border bg-surface-primary p-2.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </WideModalField>
        <WideModalField span={3}>
          <label className="flex items-center gap-2 text-xs text-content-secondary">
            <input
              type="checkbox"
              checked={form.is_active !== false}
              onChange={(e) => set('is_active', e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            {t('teams.roster_still_on', 'Still on the project')}
          </label>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── The tab ───────────────────────────────────────────────────────────── */

export function RosterTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const locale = useIntlLocale();
  // A date on this screen follows the interface language and a number follows
  // the reader's number preference, which are two different questions and only
  // look like one while the reader has never answered the second. The dates
  // below keep `locale`; the allocation percentage does not, because a reader
  // who asked for German number formatting asked for it everywhere.
  const numberLocale = useNumberLocale();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<RosterMember | null>(null);
  const [confirmId, setConfirmId] = useState('');
  const [query, setQuery] = useState('');
  const [tradeFilter, setTradeFilter] = useState('');
  const [teamFilter, setTeamFilter] = useState('');
  // Default to the people who are still here. "Who is on this job" answered
  // with people who left in March is the wrong answer to the question asked.
  const [showLeavers, setShowLeavers] = useState(false);

  const { data: vocabulary } = useRosterVocabulary();
  const trades = vocabulary?.trades ?? [];
  const siteRoles = vocabulary?.site_roles ?? [];

  const { data: roster = [], isLoading } = useQuery({
    queryKey: ['roster', projectId],
    // Same unwrap as ProjectPeopleSelect, which caches under this same key:
    // whatever sits under ['roster'] has to be one shape, because React Query
    // hands whichever query resolved first to both readers.
    queryFn: () => listRoster(projectId).then((page) => page.items),
    enabled: !!projectId,
    staleTime: 15_000,
  });

  const removal = useMutation({
    mutationFn: (memberId: string) => removeRosterMember(projectId, memberId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['roster', projectId] });
      qc.invalidateQueries({ queryKey: ['roster-summary', projectId] });
      qc.invalidateQueries({ queryKey: ['roster-candidates', projectId] });
      qc.invalidateQueries({ queryKey: ['teams-validation', projectId] });
      addToast({ type: 'success', title: t('teams.roster_removed', 'Taken off the roster') });
      setConfirmId('');
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('teams.roster_remove_failed', 'Could not remove this line'),
        message: errorDetail(err, t('teams.roster_remove_failed', 'Could not remove this line')),
      });
    },
  });

  const teamNames = useMemo(() => {
    const seen = new Map<string, string>();
    roster.forEach((m) => {
      if (m.team_id) seen.set(m.team_id, m.team_name);
    });
    return [...seen.entries()];
  }, [roster]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return roster.filter((m) => {
      if (!showLeavers && !m.is_active) return false;
      if (tradeFilter && m.trade !== tradeFilter) return false;
      if (teamFilter && (m.team_id ?? '') !== teamFilter) return false;
      if (!needle) return true;
      return [m.display_name, m.company_name, m.trade_label, m.site_role_label, m.email]
        .join(' ')
        .toLowerCase()
        .includes(needle);
    });
  }, [roster, query, tradeFilter, teamFilter, showLeavers]);

  const formatDate = useCallback(
    (value: string | null) =>
      value
        ? new Date(`${value}T00:00:00`).toLocaleDateString(locale, {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
          })
        : '',
    [locale],
  );

  const addButton = (
    <Button onClick={() => setAdding(true)}>
      <Plus size={14} />
      {t('teams.roster_add_people', 'Add people')}
    </Button>
  );

  return (
    <div className="space-y-4">
      <RosterSummaryBand projectId={projectId} />

      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('teams.roster_search', 'Search name, firm or trade')}
              aria-label={t('teams.roster_search', 'Search name, firm or trade')}
              className={`${INPUT_CLASS} pl-8`}
            />
          </div>

          <select
            value={tradeFilter}
            onChange={(e) => setTradeFilter(e.target.value)}
            aria-label={t('teams.roster_all_trades', 'All trades')}
            className={`${INPUT_CLASS} max-w-[11rem]`}
          >
            <option value="">{t('teams.roster_all_trades', 'All trades')}</option>
            {trades.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {t(`teams.trade_${entry.key}`, { defaultValue: entry.label })}
              </option>
            ))}
          </select>

          <select
            value={teamFilter}
            onChange={(e) => setTeamFilter(e.target.value)}
            aria-label={t('teams.roster_all_teams', 'All teams')}
            className={`${INPUT_CLASS} max-w-[11rem]`}
          >
            <option value="">{t('teams.roster_all_teams', 'All teams')}</option>
            {teamNames.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>

          <label className="flex items-center gap-1.5 text-xs text-content-secondary">
            <input
              type="checkbox"
              checked={showLeavers}
              onChange={(e) => setShowLeavers(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            {t('teams.roster_show_leavers', 'Include people who have left')}
          </label>

          <div className="ml-auto">{addButton}</div>
        </div>
      </Card>

      {isLoading ? (
        <Card className="p-6 text-sm text-content-tertiary">
          {t('teams.roster_loading', 'Loading')}
        </Card>
      ) : roster.length === 0 ? (
        <EmptyState
          icon={<HardHat size={28} />}
          title={t('teams.roster_empty_title', 'Nobody is written down on this project yet')}
          description={t(
            'teams.roster_empty_desc',
            'The roster is the list of everyone on the job: your staff, the subcontractor gangs, the client side. Most of them never sign in, and they do not need to - a roster line records a person, it does not hand out access.',
          )}
          action={addButton}
        />
      ) : visible.length === 0 ? (
        <Card className="p-6 text-sm text-content-tertiary">
          {t('teams.roster_no_match', 'Nobody on the roster matches these filters')}
        </Card>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[60rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="px-3 py-2 font-medium">
                  {t('teams.roster_col_person', 'Person')}
                </th>
                <th className="px-3 py-2 font-medium">{t('teams.roster_col_firm', 'Firm')}</th>
                <th className="px-3 py-2 font-medium">
                  {t('teams.roster_col_trade', 'Trade and site role')}
                </th>
                <th className="px-3 py-2 font-medium">{t('teams.roster_col_team', 'Team')}</th>
                <th className="px-3 py-2 font-medium">
                  {t('teams.roster_col_dates', 'On the project')}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t('teams.roster_col_tickets', 'Tickets')}
                </th>
                <th className="px-3 py-2 font-medium">{t('teams.roster_col_access', 'Access')}</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {visible.map((m) => (
                <tr
                  key={m.id}
                  className={clsx(
                    'border-b border-border-light last:border-b-0',
                    !m.is_active && 'opacity-60',
                  )}
                >
                  <td className="px-3 py-2">
                    <span className="block font-medium text-content-primary">
                      {m.display_name}
                    </span>
                    <span className="block text-2xs text-content-tertiary">
                      {[m.email, m.phone].filter(Boolean).join(' · ')}
                    </span>
                    {m.user_is_inactive ? (
                      <Badge variant="warning" size="sm">
                        {t('teams.roster_user_inactive', 'Account deactivated')}
                      </Badge>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">{m.company_name || '—'}</td>
                  <td className="px-3 py-2">
                    <span className="block text-content-secondary">
                      {m.trade
                        ? t(`teams.trade_${m.trade}`, { defaultValue: m.trade_label })
                        : '—'}
                    </span>
                    <span className="block text-2xs text-content-tertiary">
                      {m.site_role
                        ? t(`teams.site_role_${m.site_role}`, { defaultValue: m.site_role_label })
                        : ''}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-content-secondary">{m.team_name || '—'}</td>
                  <td className="px-3 py-2">
                    <span
                      className={clsx(
                        'block text-2xs',
                        m.off_window ? 'text-semantic-warning' : 'text-content-tertiary',
                      )}
                    >
                      {m.starts_on || m.ends_on
                        ? `${formatDate(m.starts_on) || '…'} – ${formatDate(m.ends_on) || '…'}`
                        : '—'}
                    </span>
                    {m.off_window ? (
                      <span className="inline-flex items-center gap-1 text-2xs text-semantic-warning">
                        <CalendarClock size={10} />
                        {t('teams.roster_off_window', 'Outside their dates')}
                      </span>
                    ) : null}
                    {m.allocation_percent !== null ? (
                      <span className="block text-2xs text-content-tertiary">
                        {new Intl.NumberFormat(numberLocale, { style: 'percent' }).format(
                          m.allocation_percent / 100,
                        )}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    {m.certifications.length === 0 ? (
                      <span className="text-2xs text-content-quaternary">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {m.certifications.map((c, i) => (
                          <TicketChip key={`${c.kind}-${i}`} cert={c} />
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {m.has_project_access ? (
                      <Badge variant="blue" size="sm">
                        {t('teams.roster_has_access', 'Project access')}
                      </Badge>
                    ) : (
                      <span
                        className="text-2xs text-content-tertiary"
                        title={t(
                          'teams.roster_no_access_hint',
                          'On the roster, but with no way into the platform. Normal for site staff.',
                        )}
                      >
                        {t('teams.roster_no_access', 'No login')}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {confirmId === m.id ? (
                      <span className="inline-flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => removal.mutate(m.id)}
                          className="text-2xs font-medium text-semantic-error hover:underline"
                        >
                          {t('teams.roster_confirm_remove', 'Remove')}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmId('')}
                          className="text-2xs text-content-tertiary hover:underline"
                        >
                          {t('teams.roster_cancel', 'Cancel')}
                        </button>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setEditing(m)}
                          aria-label={t('teams.roster_edit', 'Edit this line')}
                          className="p-1 text-content-tertiary hover:text-content-primary"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmId(m.id)}
                          aria-label={t('teams.roster_remove', 'Take off the roster')}
                          className="p-1 text-content-tertiary hover:text-semantic-error"
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <AddPeopleModal
        projectId={projectId}
        open={adding}
        onClose={() => setAdding(false)}
        trades={trades}
        siteRoles={siteRoles}
      />
      <EditMemberModal
        projectId={projectId}
        member={editing}
        onClose={() => setEditing(null)}
        trades={trades}
        siteRoles={siteRoles}
      />
    </div>
  );
}

export default RosterTab;
