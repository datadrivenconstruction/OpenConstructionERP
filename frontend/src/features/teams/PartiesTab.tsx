// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PartiesTab - the companies on a project, and which member belongs to which.
 *
 * Binding a member to a party is what makes them external: in the shared
 * registers they then see only what their company originated or received.
 * The party the project owner belongs to is the host and sees everything, as
 * do members bound to no party. Writes are owner or admin only; everyone else
 * gets the same screen read-only, so they can see who to ask.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Building2, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, EmptyState } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { listTeams } from './api';
import {
  PARTY_ROLES,
  bindPartyMember,
  createParty,
  deleteParty,
  getMyPartyScope,
  listParties,
  listPartyMembers,
  unbindPartyMember,
  updateParty,
  type PartyRole,
  type ProjectParty,
} from './partiesApi';

const INPUT_CLASS =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { body?: { detail?: string } })?.body?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return err instanceof Error && err.message ? err.message : fallback;
}

interface PartyFormValues {
  name: string;
  role: PartyRole;
  notes: string;
}

export function PartiesTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const myUserId = useAuthStore((s) => s.userId);
  const myEmail = useAuthStore((s) => s.userEmail);
  const { confirm, ...confirmProps } = useConfirm();
  const [editing, setEditing] = useState<ProjectParty | 'new' | null>(null);
  const [form, setForm] = useState<PartyFormValues>({ name: '', role: 'subcontractor', notes: '' });

  const scopeQuery = useQuery({
    queryKey: ['party-scope', projectId],
    queryFn: () => getMyPartyScope(projectId),
    enabled: !!projectId,
  });
  const partiesQuery = useQuery({
    queryKey: ['parties', projectId],
    queryFn: () => listParties(projectId),
    enabled: !!projectId,
  });
  const membersQuery = useQuery({
    queryKey: ['party-members', projectId],
    queryFn: () => listPartyMembers(projectId),
    enabled: !!projectId,
  });
  const teamsQuery = useQuery({
    queryKey: ['teams', projectId],
    queryFn: () => listTeams(projectId),
    enabled: !!projectId,
  });

  const canManage = scopeQuery.data?.can_manage === true;
  const parties = partiesQuery.data ?? [];

  // Everyone who can reach the project through a team, plus the caller (the
  // owner is often on no team, and binding the owner is what names the host).
  const people = useMemo(() => {
    const byId = new Map<string, { user_id: string; label: string }>();
    for (const team of teamsQuery.data ?? []) {
      for (const m of team.memberships ?? []) {
        byId.set(m.user_id, { user_id: m.user_id, label: m.full_name || m.email || m.user_id });
      }
    }
    if (canManage && myUserId && !byId.has(myUserId)) {
      byId.set(myUserId, { user_id: myUserId, label: myEmail || myUserId });
    }
    return [...byId.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [teamsQuery.data, canManage, myUserId, myEmail]);

  const bindingByUser = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of membersQuery.data ?? []) map.set(m.user_id, m.party_id);
    return map;
  }, [membersQuery.data]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['parties', projectId] });
    qc.invalidateQueries({ queryKey: ['party-members', projectId] });
    qc.invalidateQueries({ queryKey: ['party-scope', projectId] });
    qc.invalidateQueries({ queryKey: ['teams-validation', projectId] });
  };
  const fail = (err: unknown) =>
    addToast({
      type: 'error',
      title: t('parties.toast_error', 'Party change refused'),
      message: errorDetail(err, t('parties.toast_error', 'Party change refused')),
    });

  const saveMutation = useMutation({
    mutationFn: () =>
      editing === 'new' || editing === null
        ? createParty(projectId, form)
        : updateParty(projectId, editing.id, form),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
    onError: fail,
  });
  const toggleActiveMutation = useMutation({
    mutationFn: (p: ProjectParty) => updateParty(projectId, p.id, { is_active: !p.is_active }),
    onSuccess: refresh,
    onError: fail,
  });
  const deleteMutation = useMutation({
    mutationFn: (p: ProjectParty) => deleteParty(projectId, p.id),
    onSuccess: refresh,
    onError: fail,
  });
  const bindMutation = useMutation({
    mutationFn: async ({ userId, partyId }: { userId: string; partyId: string }) => {
      if (bindingByUser.has(userId)) await unbindPartyMember(projectId, userId);
      if (partyId) await bindPartyMember(projectId, userId, partyId);
    },
    onSuccess: refresh,
    onError: (err) => {
      fail(err);
      refresh();
    },
  });

  const roleLabels: Record<PartyRole, string> = {
    owner: t('parties.role_owner', 'Client / owner'),
    contractor: t('parties.role_contractor', 'Contractor'),
    subcontractor: t('parties.role_subcontractor', 'Subcontractor'),
    consultant: t('parties.role_consultant', 'Consultant'),
    supplier: t('parties.role_supplier', 'Supplier'),
  };
  const roleLabel = (role: PartyRole) => roleLabels[role] ?? role;

  const startEdit = (p: ProjectParty | 'new') => {
    setEditing(p);
    setForm(
      p === 'new'
        ? { name: '', role: 'subcontractor', notes: '' }
        : { name: p.name, role: p.role, notes: p.notes ?? '' },
    );
  };

  const onDelete = async (p: ProjectParty) => {
    const ok = await confirm({
      title: t('parties.delete_title', 'Remove this party?'),
      message: t(
        'parties.delete_message',
        '{{name}} and its shares are removed. Its members become internal again and will see every record in the shared registers.',
        { name: p.name },
      ),
      confirmLabel: t('parties.delete_confirm', 'Remove'),
    });
    if (ok) deleteMutation.mutate(p);
  };

  if (partiesQuery.isLoading || scopeQuery.isLoading) {
    return <Loader2 size={16} className="animate-spin text-content-tertiary" />;
  }

  return (
    <div className="space-y-4">
      <Card className="p-4 text-sm text-content-secondary">
        <p>
          {t(
            'parties.explainer_1',
            'A party is a company taking part in this project: the client, the contractor, a subcontractor, a consultant or a supplier.',
          )}
        </p>
        <p className="mt-1.5">
          {t(
            'parties.explainer_2',
            'Binding a member to a party makes them see only their own company’s records, plus the records shared with it, in RFIs, interfaces, correspondence, transmittals, submittals and file transmittals. Other modules are not affected.',
          )}
        </p>
        <p className="mt-1.5">
          {t(
            'parties.explainer_3',
            'The project owner’s company is the host and sees everything, as do members bound to no party. A project without parties works exactly as before.',
          )}
        </p>
      </Card>

      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-content-primary">{t('parties.list_title', 'Parties')}</h3>
          {canManage ? (
            <Button size="sm" icon={<Plus size={14} />} onClick={() => startEdit('new')}>
              {t('parties.add', 'Add party')}
            </Button>
          ) : null}
        </div>

        {editing !== null ? (
          <div className="mb-3 grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-3">
            <input
              className={INPUT_CLASS}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={t('parties.field_name', 'Company name')}
              aria-label={t('parties.field_name', 'Company name')}
            />
            <select
              className={INPUT_CLASS}
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value as PartyRole })}
              aria-label={t('parties.field_role', 'Role on the project')}
            >
              {PARTY_ROLES.map((r) => (
                <option key={r} value={r}>
                  {roleLabel(r)}
                </option>
              ))}
            </select>
            <input
              className={INPUT_CLASS}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder={t('parties.field_notes', 'Notes')}
              aria-label={t('parties.field_notes', 'Notes')}
            />
            <div className="flex gap-2 sm:col-span-3">
              <Button
                size="sm"
                disabled={!form.name.trim()}
                loading={saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
              >
                {t('parties.save', 'Save')}
              </Button>
              <Button size="sm" variant="ghost" icon={<X size={14} />} onClick={() => setEditing(null)}>
                {t('parties.cancel', 'Cancel')}
              </Button>
            </div>
          </div>
        ) : null}

        {parties.length === 0 ? (
          <EmptyState
            icon={<Building2 size={20} />}
            title={t('parties.empty_title', 'No parties on this project')}
            description={t(
              'parties.empty_desc',
              'Every member sees every record. Add parties when companies outside your own work inside this project.',
            )}
          />
        ) : (
          <ul className="divide-y divide-border">
            {parties.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="font-medium text-content-primary">{p.name}</span>
                <Badge variant="neutral" size="sm">
                  {roleLabel(p.role)}
                </Badge>
                {p.is_host ? (
                  <Badge variant="blue" size="sm">
                    {t('parties.host_badge', 'Host, sees everything')}
                  </Badge>
                ) : null}
                {!p.is_active ? (
                  <Badge variant="warning" size="sm">
                    {t('parties.inactive_badge', 'Inactive')}
                  </Badge>
                ) : null}
                <span className="text-content-tertiary">
                  {t('parties.member_count', '{{count}} members', { count: p.member_count })}
                </span>
                {canManage ? (
                  <span className="ml-auto flex gap-1">
                    <Button size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => startEdit(p)}>
                      {t('parties.edit', 'Edit')}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => toggleActiveMutation.mutate(p)}>
                      {p.is_active
                        ? t('parties.deactivate', 'Deactivate')
                        : t('parties.activate', 'Activate')}
                    </Button>
                    <Button size="sm" variant="ghost" icon={<Trash2 size={14} />} onClick={() => void onDelete(p)}>
                      {t('parties.delete', 'Delete')}
                    </Button>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {parties.length > 0 ? (
        <Card className="p-4">
          <h3 className="mb-1 text-sm font-semibold text-content-primary">
            {t('parties.members_title', 'Who belongs to which party')}
          </h3>
          <p className="mb-3 text-xs text-content-tertiary">
            {t(
              'parties.members_hint',
              'A member belongs to at most one party on this project. Members with no party are internal.',
            )}
          </p>
          {people.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('parties.members_empty', 'Nobody is on a team of this project yet.')}
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {people.map((person) => (
                <li key={person.user_id} className="flex items-center gap-3 py-2 text-sm">
                  <span className="flex-1 text-content-primary">{person.label}</span>
                  <select
                    className="h-8 w-56 rounded-lg border border-border bg-surface-primary px-2 text-sm"
                    value={bindingByUser.get(person.user_id) ?? ''}
                    disabled={!canManage || bindMutation.isPending}
                    onChange={(e) => bindMutation.mutate({ userId: person.user_id, partyId: e.target.value })}
                    aria-label={t('parties.member_party', 'Party of {{name}}', { name: person.label })}
                  >
                    <option value="">{t('parties.no_party', 'No party (internal)')}</option>
                    {parties
                      .filter((p) => p.is_active || p.id === bindingByUser.get(person.user_id))
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                  </select>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
