// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The owner of a chapter and the way to change it. The control shows only when
// the server says the actor may edit the chapter. Handing a chapter to another
// person, or leaving it without an owner, takes away an accountability, so it
// asks first.

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { UserCog } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';

import { listProjectMembers, patchChapter, type ChapterDetail } from './api';
import { useHandbookAction } from './hooks';

export function OwnerControl({
  projectId,
  chapter,
  canChange,
  onChanged,
}: {
  projectId: string;
  chapter: Pick<ChapterDetail, 'code' | 'owner_id' | 'owner_name'>;
  canChange: boolean;
  onChanged: (next?: ChapterDetail) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState<string>(chapter.owner_id ?? '');
  const [confirming, setConfirming] = useState(false);

  const members = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => listProjectMembers(projectId),
    enabled: editing && !!projectId,
    staleTime: 30_000,
  });
  const change = useHandbookAction(
    () => patchChapter(projectId, chapter.code, { owner_id: choice || null }),
    (next) => {
      setConfirming(false);
      setEditing(false);
      onChanged(next);
    },
  );

  const name = chapter.owner_name || t('projectHandbook.no_owner', { defaultValue: 'No owner yet' });
  if (!canChange) return <span data-testid="handbook-owner">{name}</span>;

  const unchanged = choice === (chapter.owner_id ?? '');
  const apply = () => {
    // A chapter with no owner yet is simply assigned; replacing or clearing an owner is confirmed.
    if (chapter.owner_id) setConfirming(true);
    else change.mutate();
  };
  const nextName = members.data?.find((m) => m.user_id === choice)?.full_name;

  return (
    <div className="space-y-2" data-testid="handbook-owner">
      <div className="flex items-center gap-2">
        <span>{name}</span>
        {!editing ? (
          <Button
            variant="ghost"
            size="sm"
            icon={<UserCog size={14} />}
            onClick={() => {
              setChoice(chapter.owner_id ?? '');
              setEditing(true);
            }}
            data-testid="handbook-owner-change"
          >
            {t('projectHandbook.owner_change', { defaultValue: 'Change owner' })}
          </Button>
        ) : null}
      </div>
      {editing ? (
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
            aria-label={t('projectHandbook.owner', { defaultValue: 'Owner' })}
            value={choice}
            disabled={members.isLoading}
            onChange={(e) => setChoice(e.target.value)}
            data-testid="handbook-owner-select"
          >
            <option value="">{t('projectHandbook.no_owner', { defaultValue: 'No owner yet' })}</option>
            {(members.data ?? []).map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name || m.email}
              </option>
            ))}
          </select>
          <Button
            variant="primary"
            size="sm"
            loading={change.isPending}
            disabled={unchanged}
            onClick={apply}
            data-testid="handbook-owner-apply"
          >
            {t('projectHandbook.owner_apply', { defaultValue: 'Apply' })}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
            {t('projectHandbook.owner_cancel', { defaultValue: 'Cancel' })}
          </Button>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirming}
        variant="warning"
        loading={change.isPending}
        title={t('projectHandbook.owner_confirm_title', { defaultValue: 'Change the owner of this chapter?' })}
        message={
          choice
            ? t('projectHandbook.owner_confirm_message', {
                defaultValue: '{{from}} is no longer responsible for this chapter. {{to}} takes over.',
                from: name,
                to: nextName ?? '',
              })
            : t('projectHandbook.owner_confirm_clear', {
                defaultValue: '{{from}} is no longer responsible for this chapter, and nobody takes over. A chapter without an owner cannot be submitted.',
                from: name,
              })
        }
        confirmLabel={t('projectHandbook.owner_apply', { defaultValue: 'Apply' })}
        onConfirm={() => change.mutate()}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
