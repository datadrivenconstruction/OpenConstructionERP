/* Right-click context menu for a file row/tile. Backed by floating div
   positioned at the cursor; closes on outside click, scroll, Escape, or
   another contextmenu event. All actions reuse existing endpoints:
     - Open in module — primaryModule(kind, ext).route(project_id, id)
     - Download    — row.download_url
     - Copy link   — copies download_url to clipboard
     - Rename      — fires onRename(row) — caller opens inline editor
     - Delete      — fires onDelete(row) — caller shows confirm + DELETE
*/

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Download,
  ExternalLink,
  Link as LinkIcon,
  Pencil,
  Trash2,
} from 'lucide-react';
import clsx from 'clsx';
import { useNavigate } from 'react-router-dom';
import { useToastStore } from '@/stores/useToastStore';
import { copyToClipboard } from '../lib/tauri';
import { downloadProtectedFile } from '../api';
import { primaryModule } from '../kindModule';
import type { FileRow } from '../types';

interface FileContextMenuProps {
  row: FileRow;
  x: number;
  y: number;
  onClose: () => void;
  onRename: (row: FileRow) => void;
  onDelete: (row: FileRow) => void;
}

export function FileContextMenu({
  row,
  x,
  y,
  onClose,
  onRename,
  onDelete,
}: FileContextMenuProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const menuRef = useRef<HTMLDivElement>(null);

  /* Close on any of: outside click, escape, scroll, blur. We attach with
     capture so we beat the click that just spawned us — without capture,
     React's synthetic event finishes before our listener mounts and the
     menu opens then closes on the same gesture. */
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleClick, true);
    document.addEventListener('keydown', handleKey);
    window.addEventListener('scroll', onClose, true);
    window.addEventListener('blur', onClose);
    return () => {
      document.removeEventListener('mousedown', handleClick, true);
      document.removeEventListener('keydown', handleKey);
      window.removeEventListener('scroll', onClose, true);
      window.removeEventListener('blur', onClose);
    };
  }, [onClose]);

  /* Clamp the menu inside the viewport so it never opens off-screen.
     200x180 covers the largest the menu can grow to (5 items, comfortable
     padding); plenty of headroom for label growth. */
  const adjustedX = Math.min(x, window.innerWidth - 200);
  const adjustedY = Math.min(y, window.innerHeight - 200);

  const target = primaryModule(row.kind, row.extension);
  const moduleLabel = t(target.i18nKey, { defaultValue: target.label });

  async function handleDownload() {
    if (!row.download_url) return;
    onClose();
    try {
      await downloadProtectedFile(row.download_url, row.name);
    } catch (e) {
      addToast({
        type: 'error',
        title: t('files.actions.download_failed', { defaultValue: 'Could not download the file' }),
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }

  async function handleCopyLink() {
    if (!row.download_url) return;
    const absolute = row.download_url.startsWith('http')
      ? row.download_url
      : `${window.location.origin}${row.download_url}`;
    const ok = await copyToClipboard(absolute);
    addToast({
      type: ok ? 'success' : 'error',
      title: ok
        ? t('files.context.link_copied', { defaultValue: 'Link copied' })
        : t('files.context.copy_failed', { defaultValue: 'Could not copy link' }),
    });
    onClose();
  }

  return (
    <div
      ref={menuRef}
      role="menu"
      className={clsx(
        'fixed z-50 w-48 rounded-lg border border-border-light bg-surface-elevated shadow-xl overflow-hidden',
        'animate-fade-in',
      )}
      style={{ left: adjustedX, top: adjustedY }}
      onClick={(e) => e.stopPropagation()}
    >
      <MenuItem
        icon={<ExternalLink size={13} />}
        label={t('files.context.open_in', {
          defaultValue: 'Open in {{module}}',
          module: moduleLabel,
        })}
        onClick={() => {
          navigate(target.route(row.project_id, row.id));
          onClose();
        }}
      />
      {row.download_url && (
        <MenuItem
          icon={<Download size={13} />}
          label={t('files.context.download', { defaultValue: 'Download' })}
          onClick={handleDownload}
        />
      )}
      {row.download_url && (
        <MenuItem
          icon={<LinkIcon size={13} />}
          label={t('files.context.copy_link', { defaultValue: 'Copy link' })}
          onClick={handleCopyLink}
        />
      )}
      <div className="h-px bg-border-light" />
      <MenuItem
        icon={<Pencil size={13} />}
        label={t('files.context.rename', { defaultValue: 'Rename' })}
        onClick={() => {
          onRename(row);
          onClose();
        }}
        disabled={row.kind !== 'document'}
        disabledTitle={t('files.context.rename_unsupported', {
          defaultValue: 'Rename is only available for documents',
        })}
      />
      <div className="h-px bg-border-light" />
      <MenuItem
        icon={<Trash2 size={13} />}
        label={t('files.context.delete', { defaultValue: 'Delete' })}
        onClick={() => {
          onDelete(row);
          onClose();
        }}
        danger
      />
    </div>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  danger = false,
  disabled = false,
  disabledTitle,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  disabledTitle?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? disabledTitle : undefined}
      className={clsx(
        'flex w-full items-center gap-2 px-3 py-2 text-xs transition-colors',
        disabled
          ? 'text-content-quaternary cursor-not-allowed'
          : danger
            ? 'text-semantic-error hover:bg-semantic-error-bg'
            : 'text-content-primary hover:bg-surface-secondary',
      )}
    >
      <span className="shrink-0">{icon}</span>
      <span className="truncate text-left flex-1">{label}</span>
    </button>
  );
}
