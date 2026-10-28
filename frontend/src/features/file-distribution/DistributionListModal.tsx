// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DistributionListModal — manage the members of a single distribution
// list (or create one from scratch). The modal toggles between two
// modes: "list overview" (lists collection, click to open one) and
// "edit one list" (rename + members CRUD).

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, UserPlus, X } from 'lucide-react';

import { WideModal } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui/Button';
import { Input } from '@/shared/ui/Input';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { useConfirm } from '@/shared/hooks/useConfirm';
import {
  useAddDistributionMember,
  useCreateDistributionList,
  useDeleteDistributionList,
  useDistributionLists,
  useRemoveDistributionMember,
  useUpdateDistributionList,
} from './hooks';
import type { DistributionList, DistributionMemberRole } from './types';

interface DistributionListModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string | null | undefined;
  /** Pre-open one specific list by id; falls back to the overview
   *  when undefined / unknown. */
  initialListId?: string | null;
}

const ROLE_OPTIONS: DistributionMemberRole[] = ['for_review', 'fyi', 'for_construction'];

export function DistributionListModal({
  open,
  onClose,
  projectId,
  initialListId,
}: DistributionListModalProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useDistributionLists(projectId);
  const createMut = useCreateDistributionList(projectId);
  const updateMut = useUpdateDistributionList(projectId);
  const deleteMut = useDeleteDistributionList(projectId);
  const addMemberMut = useAddDistributionMember(projectId);
  const removeMemberMut = useRemoveDistributionMember(projectId);

  const [activeId, setActiveId] = useState<string | null>(initialListId ?? null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newRole, setNewRole] = useState<string>('for_review');
  const [error, setError] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  useEffect(() => {
    if (open) {
      setActiveId(initialListId ?? null);
      setCreating(false);
      setNewName('');
      setNewEmail('');
      setNewRole('for_review');
      setError(null);
    }
  }, [open, initialListId]);

  const lists = useMemo<DistributionList[]>(() => data?.items ?? [], [data]);
  const active = useMemo<DistributionList | null>(
    () => lists.find((l) => l.id === activeId) ?? null,
    [lists, activeId],
  );

  const submitCreate = async () => {
    const trimmed = newName.trim();
    if (!trimmed) {
      setError(t('files.distribution.error_name_required', { defaultValue: 'Name is required' }));
      return;
    }
    setError(null);
    try {
      const row = await createMut.mutateAsync({
        name: trimmed,
        project_id: projectId ?? null,
      });
      setActiveId(row.id);
      setCreating(false);
      setNewName('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submitDelete = async (list: DistributionList) => {
    const confirmed = await confirm({
      title: t('files.distribution.delete_list_title', {
        defaultValue: 'Delete distribution list?',
      }),
      message: t('files.distribution.delete_list_confirm', {
        defaultValue: 'Delete list "{{name}}"?',
        name: list.name,
      }),
      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (!confirmed) return;
    await deleteMut.mutateAsync(list.id);
    if (activeId === list.id) setActiveId(null);
  };

  const submitRename = async (list: DistributionList) => {
    const next = window.prompt(
      t('files.distribution.rename_list_prompt', { defaultValue: 'New name' }),
      list.name,
    );
    if (next === null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === list.name) return;
    await updateMut.mutateAsync({ id: list.id, payload: { name: trimmed } });
  };

  const submitAddMember = async () => {
    if (!active) return;
    const trimmed = newEmail.trim();
    if (!trimmed) {
      setError(t('files.distribution.error_email_required', { defaultValue: 'Email is required' }));
      return;
    }
    setError(null);
    try {
      await addMemberMut.mutateAsync({
        listId: active.id,
        payload: { email: trimmed, role: newRole || null },
      });
      setNewEmail('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submitRemoveMember = async (memberId: string) => {
    if (!active) return;
    await removeMemberMut.mutateAsync({ listId: active.id, memberId });
  };

  return (
    <>
    <WideModal
      open={open}
      onClose={onClose}
      title={
        active
          ? t('files.distribution.modal_edit_title', {
              defaultValue: '{{name}}',
              name: active.name,
            })
          : t('files.distribution.modal_overview_title', {
              defaultValue: 'Distribution lists',
            })
      }
      size="lg"
      busy={createMut.isPending || deleteMut.isPending}
      footer={
        active ? (
          <div className="flex justify-between gap-2">
            <Button
              variant="ghost"
              onClick={() => setActiveId(null)}
              data-testid="distribution-back-to-overview"
            >
              {t('files.distribution.back', { defaultValue: 'Back to lists' })}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
          </div>
        )
      }
    >
      {!active && (
        <div className="flex flex-col gap-3" data-testid="distribution-list-overview">
          <div className="flex items-center justify-between">
            <span className="text-sm text-content-secondary">
              {lists.length === 0
                ? t('files.distribution.empty', { defaultValue: 'No lists yet - create one.' })
                : t('files.distribution.count', {
                    defaultValue: '{{count}} list(s)',
                    count: lists.length,
                  })}
            </span>
            {!creating && (
              <Button
                size="sm"
                icon={<Plus className="h-3.5 w-3.5" />}
                onClick={() => setCreating(true)}
                data-testid="distribution-new-list-button"
              >
                {t('files.distribution.new_list', { defaultValue: 'New list' })}
              </Button>
            )}
          </div>
          {creating && (
            <div className="flex items-center gap-2">
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={t('files.distribution.name_placeholder', {
                  defaultValue: 'List name',
                })}
                data-testid="distribution-new-list-name"
                maxLength={128}
              />
              <Button onClick={submitCreate} loading={createMut.isPending} size="sm">
                {t('common.create', { defaultValue: 'Create' })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setCreating(false);
                  setNewName('');
                  setError(null);
                }}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          )}
          {error && (
            <div
              role="alert"
              className="rounded-md border border-semantic-error/40 bg-semantic-error/10 px-3 py-2 text-sm text-semantic-error"
            >
              {error}
            </div>
          )}
          {isLoading && <div className="text-sm text-content-tertiary">…</div>}
          <ul className="flex flex-col gap-1.5">
            {lists.map((list) => (
              <li
                key={list.id}
                className="flex items-center gap-2 rounded-md border border-border-light bg-surface-primary px-3 py-2"
              >
                <button
                  type="button"
                  onClick={() => setActiveId(list.id)}
                  data-testid={`distribution-open-${list.id}`}
                  className="flex flex-1 flex-col text-left"
                >
                  <span className="font-medium text-content-primary">{list.name}</span>
                  <span className="text-xs text-content-tertiary">
                    {t('files.distribution.members_count', {
                      defaultValue: '{{count}} member(s)',
                      count: list.members.length,
                    })}
                    {list.is_shared
                      ? ` · ${t('files.distribution.shared_label', { defaultValue: 'shared' })}`
                      : ''}
                  </span>
                </button>
                {list.is_own && (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => submitRename(list)}
                      data-testid={`distribution-rename-${list.id}`}
                    >
                      {t('common.rename', { defaultValue: 'Rename' })}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Trash2 className="h-3.5 w-3.5" />}
                      onClick={() => submitDelete(list)}
                      data-testid={`distribution-delete-${list.id}`}
                    >
                      {t('common.delete', { defaultValue: 'Delete' })}
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {active && (
        <div className="flex flex-col gap-4" data-testid="distribution-list-detail">
          {active.description && (
            <p className="text-sm text-content-secondary">{active.description}</p>
          )}
          <div className="flex items-end gap-2">
            <label className="flex flex-1 flex-col gap-1 text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('files.distribution.member_email', { defaultValue: 'Email' })}
              </span>
              <Input
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder="someone@example.com"
                data-testid="distribution-new-member-email"
                type="email"
                maxLength={255}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('files.distribution.member_role', { defaultValue: 'Role' })}
              </span>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                data-testid="distribution-new-member-role"
                className="h-8 rounded-md border border-border bg-surface-primary px-2 text-sm"
              >
                {ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <Button
              icon={<UserPlus className="h-3.5 w-3.5" />}
              onClick={submitAddMember}
              loading={addMemberMut.isPending}
              disabled={!active.is_own}
              data-testid="distribution-add-member"
            >
              {t('files.distribution.add_member', { defaultValue: 'Add' })}
            </Button>
          </div>
          {error && (
            <div
              role="alert"
              className="rounded-md border border-semantic-error/40 bg-semantic-error/10 px-3 py-2 text-sm text-semantic-error"
            >
              {error}
            </div>
          )}
          <ul className="flex flex-col gap-1">
            {active.members.map((m) => (
              <li
                key={m.id}
                className="flex items-center gap-2 rounded-md border border-border-light bg-surface-primary px-3 py-2"
                data-testid={`distribution-member-${m.id}`}
              >
                <div className="flex flex-1 flex-col">
                  <span className="font-medium text-content-primary">
                    {m.display_name || m.email}
                  </span>
                  {m.display_name && (
                    <span className="text-xs text-content-tertiary">{m.email}</span>
                  )}
                </div>
                {m.role && (
                  <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-[10px] uppercase tracking-wide text-content-tertiary">
                    {m.role}
                  </span>
                )}
                {active.is_own && (
                  <button
                    type="button"
                    onClick={() => submitRemoveMember(m.id)}
                    className="text-content-tertiary hover:text-semantic-error"
                    data-testid={`distribution-remove-member-${m.id}`}
                    aria-label={t('files.distribution.remove_member', {
                      defaultValue: 'Remove member',
                    })}
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
            {active.members.length === 0 && (
              <li className="rounded-md border border-dashed border-border-light px-3 py-3 text-center text-xs text-content-tertiary">
                {t('files.distribution.no_members', {
                  defaultValue: 'No members yet - add one above.',
                })}
              </li>
            )}
          </ul>
        </div>
      )}
    </WideModal>
    <ConfirmDialog {...confirmProps} />
    </>
  );
}
