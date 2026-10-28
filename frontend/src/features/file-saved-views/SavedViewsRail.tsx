// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SavedViewsRail — vertical list of saved views shown under the
// /files left-pane category tree. Each row is icon + name + use-count
// badge; right-click opens a context menu (rename / pin / delete /
// share-toggle / duplicate). Clicking a row applies the filter and
// bumps its ``use_count``.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Bookmark,
  ChevronDown,
  ChevronRight,
  Copy,
  Edit3,
  Pin,
  PinOff,
  Share2,
  Trash2,
  Users,
} from 'lucide-react';

import { useConfirm } from '@/shared/hooks/useConfirm';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';

import {
  useApplyView,
  useDeleteView,
  useDuplicateView,
  useSavedViews,
  useUpdateView,
} from './hooks';
import type { SavedViewResponse } from './types';

interface SavedViewsRailProps {
  projectId: string | null | undefined;
  /** Optional callback invoked when a view is applied — handy for
   *  the parent to close a mobile sidebar drawer, log analytics, etc.
   */
  onApply?: (view: SavedViewResponse) => void;
  /** Compact density (no use-count badge, smaller padding). */
  compact?: boolean;
}

interface ContextMenuState {
  viewId: string;
  x: number;
  y: number;
}

export function SavedViewsRail({ projectId, onApply, compact = false }: SavedViewsRailProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useSavedViews(projectId);
  const applyView = useApplyView('/files');
  const updateMut = useUpdateView(projectId);
  const deleteMut = useDeleteView(projectId);
  const duplicateMut = useDuplicateView(projectId);

  const [expanded, setExpanded] = useState(true);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  const views = useMemo<SavedViewResponse[]>(() => data?.items ?? [], [data]);
  const targetView = useMemo<SavedViewResponse | null>(
    () => (contextMenu ? views.find((v) => v.id === contextMenu.viewId) ?? null : null),
    [contextMenu, views],
  );

  const handleClick = async (view: SavedViewResponse) => {
    await applyView(view);
    onApply?.(view);
  };

  const handleContext = (e: React.MouseEvent<HTMLButtonElement>, view: SavedViewResponse) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ viewId: view.id, x: e.clientX, y: e.clientY });
  };

  const closeMenu = () => setContextMenu(null);

  const handleRename = async (view: SavedViewResponse) => {
    const next = window.prompt(t('files.views.rename_prompt', { defaultValue: 'New name' }), view.name);
    if (next === null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === view.name) return;
    await updateMut.mutateAsync({ id: view.id, payload: { name: trimmed } });
    closeMenu();
  };

  const handleTogglePin = async (view: SavedViewResponse) => {
    await updateMut.mutateAsync({
      id: view.id,
      payload: { is_pinned: !view.is_pinned },
    });
    closeMenu();
  };

  const handleToggleShare = async (view: SavedViewResponse) => {
    await updateMut.mutateAsync({
      id: view.id,
      payload: { is_shared: !view.is_shared },
    });
    closeMenu();
  };

  const handleDuplicate = async (view: SavedViewResponse) => {
    await duplicateMut.mutateAsync(view.id);
    closeMenu();
  };

  const handleDelete = async (view: SavedViewResponse) => {
    const confirmed = await confirm({
      title: t('files.views.delete_title', {
        defaultValue: 'Delete saved view?',
      }),
      message: t('files.views.delete_confirm', {
        defaultValue: 'Delete saved view "{{name}}"?',
        name: view.name,
      }),
      confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (!confirmed) return;
    await deleteMut.mutateAsync(view.id);
    closeMenu();
  };

  return (
    <div className="flex flex-col" onClick={closeMenu}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
        className={clsx(
          'flex items-center gap-1.5 px-2 py-1.5 text-xs font-semibold uppercase tracking-wide',
          'text-content-secondary hover:text-content-primary',
        )}
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <Bookmark className="h-3.5 w-3.5" />
        <span>{t('files.views.title', { defaultValue: 'Saved views' })}</span>
        {views.length > 0 && (
          <span className="ml-auto text-[10px] text-content-tertiary">{views.length}</span>
        )}
      </button>
      {expanded && (
        <ul className="flex flex-col gap-0.5" data-testid="saved-views-rail-list">
          {isLoading && (
            <li className="px-2 py-1 text-xs text-content-tertiary">
              {t('files.views.loading', { defaultValue: 'Loading…' })}
            </li>
          )}
          {!isLoading && views.length === 0 && (
            <li className="px-2 py-1 text-xs text-content-tertiary">
              {t('files.views.empty', { defaultValue: 'No saved views yet' })}
            </li>
          )}
          {views.map((view) => (
            <li key={view.id}>
              <button
                type="button"
                data-testid={`saved-view-row-${view.id}`}
                onClick={() => handleClick(view)}
                onContextMenu={(e) => handleContext(e, view)}
                className={clsx(
                  'group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm',
                  'hover:bg-surface-secondary active:bg-surface-tertiary',
                  'border border-transparent hover:border-border-light',
                  view.is_pinned && 'bg-surface-secondary/60',
                )}
              >
                {view.is_pinned ? (
                  <Pin className="h-3.5 w-3.5 shrink-0 text-oe-blue" />
                ) : (
                  <Bookmark className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
                )}
                <span className="flex-1 truncate text-content-primary">{view.name}</span>
                {view.is_shared && (
                  <Users
                    className="h-3 w-3 shrink-0 text-content-tertiary"
                    aria-label={t('files.views.shared_label', { defaultValue: 'Shared' })}
                  />
                )}
                {!compact && view.use_count > 0 && (
                  <span
                    data-testid={`saved-view-usecount-${view.id}`}
                    className="ml-auto rounded-full bg-surface-tertiary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary"
                  >
                    {view.use_count}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {contextMenu && targetView && (
        <div
          role="menu"
          data-testid="saved-views-context-menu"
          className="fixed z-50 min-w-[10rem] rounded-lg border border-border bg-surface-elevated shadow-2xl"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <MenuButton
            disabled={!targetView.is_own}
            icon={<Edit3 className="h-3.5 w-3.5" />}
            label={t('files.views.action_rename', { defaultValue: 'Rename' })}
            onClick={() => handleRename(targetView)}
            testid="saved-view-action-rename"
          />
          <MenuButton
            disabled={!targetView.is_own}
            icon={
              targetView.is_pinned ? (
                <PinOff className="h-3.5 w-3.5" />
              ) : (
                <Pin className="h-3.5 w-3.5" />
              )
            }
            label={
              targetView.is_pinned
                ? t('files.views.action_unpin', { defaultValue: 'Unpin' })
                : t('files.views.action_pin', { defaultValue: 'Pin' })
            }
            onClick={() => handleTogglePin(targetView)}
            testid="saved-view-action-pin"
          />
          <MenuButton
            disabled={!targetView.is_own}
            icon={<Share2 className="h-3.5 w-3.5" />}
            label={
              targetView.is_shared
                ? t('files.views.action_unshare', { defaultValue: 'Stop sharing' })
                : t('files.views.action_share', { defaultValue: 'Share with project' })
            }
            onClick={() => handleToggleShare(targetView)}
            testid="saved-view-action-share"
          />
          <MenuButton
            icon={<Copy className="h-3.5 w-3.5" />}
            label={t('files.views.action_duplicate', { defaultValue: 'Duplicate' })}
            onClick={() => handleDuplicate(targetView)}
            testid="saved-view-action-duplicate"
          />
          <div className="my-1 h-px bg-border-light" />
          <MenuButton
            disabled={!targetView.is_own}
            danger
            icon={<Trash2 className="h-3.5 w-3.5" />}
            label={t('files.views.action_delete', { defaultValue: 'Delete' })}
            onClick={() => handleDelete(targetView)}
            testid="saved-view-action-delete"
          />
        </div>
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

interface MenuButtonProps {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  testid?: string;
}

function MenuButton({ icon, label, onClick, disabled = false, danger = false, testid }: MenuButtonProps) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testid}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm',
        'hover:bg-surface-secondary active:bg-surface-tertiary',
        'disabled:cursor-not-allowed disabled:opacity-50',
        danger && 'text-semantic-error',
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
