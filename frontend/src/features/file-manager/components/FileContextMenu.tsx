// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/* Right-click context menu for a file row/tile. Backed by floating div
   positioned at the cursor; closes on outside click, scroll, Escape, or
   another contextmenu event. All actions reuse existing endpoints:
     - Open in module — primaryModule(kind, ext).route(project_id, id)
     - Download    — row.download_url
     - Copy link   — copies download_url to clipboard
     - Rename      — fires onRename(row) — caller opens inline editor
     - Delete      — fires onDelete(row); the caller soft-deletes into the
                     recycle bin and offers Undo, so there is no confirm step.
                     A document row carries the reference block above Delete
                     instead, because the links break the moment the row
                     leaves `documents` and Restore is what puts them back.
*/

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Download,
  ExternalLink,
  Eye,
  Image as ImageIcon,
  Link as LinkIcon,
  Pencil,
  PlayCircle,
  Ruler,
  Trash2,
} from 'lucide-react';
import clsx from 'clsx';
import { useNavigate } from 'react-router-dom';
import { DocumentDeleteWarning } from '@/features/documents/DocumentDeleteWarning';
import { useToastStore } from '@/stores/useToastStore';
import { copyToClipboard } from '../lib/tauri';
import { downloadProtectedFile } from '../api';
import {
  isInlinePreviewRow,
  isLightboxRow,
  isVideoRow,
  pdfTakeoffTargetFor,
  primaryModule,
} from '../kindModule';
import type { FileRow } from '../types';

interface FileContextMenuProps {
  row: FileRow;
  x: number;
  y: number;
  onClose: () => void;
  onRename: (row: FileRow) => void;
  onDelete: (row: FileRow) => void;
  /**
   * Open a PDF document in the focused inline reader (#284). When omitted,
   * the "Open" item degrades to the primary target's route fallback so the
   * menu still works if a consumer hasn't wired the inline reader yet.
   */
  onInlinePreview?: (row: FileRow) => void;
  /**
   * Open an image / video in the MediaLightbox (#284 follow-up, ITEM 10).
   * When omitted, the "Open" item degrades to the primary target's route
   * fallback (which keeps the file selected in /files) rather than a dead
   * click - it never routes a media file to PDF Takeoff.
   */
  onMediaPreview?: (row: FileRow) => void;
}

export function FileContextMenu({
  row,
  x,
  y,
  onClose,
  onRename,
  onDelete,
  onInlinePreview,
  onMediaPreview,
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
     `w-48` fixes the width, so 200 covers X for good. The height is not
     fixed: the items are conditional on kind, and the reference block below
     arrives after its own query resolves. A constant that guesses short puts
     the bottom of the menu past the fold, and since the menu clips its own
     overflow the item that disappears is Delete. Measure instead.

     ResizeObserver rather than a layout effect: the block that changes the
     height is a child holding its own query, so the parent never re-renders
     when it appears. jsdom has no ResizeObserver and no layout either, which
     makes the clamp inert under test rather than broken - hence the guard. */
  const [menuHeight, setMenuHeight] = useState(0);
  useLayoutEffect(() => {
    const node = menuRef.current;
    if (!node) return;
    const measure = () => setMenuHeight(node.offsetHeight);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const adjustedX = Math.min(x, window.innerWidth - 200);
  // Until the first measurement lands this is plain `y`, which is where the
  // menu was going to open anyway; the layout effect corrects it before paint.
  const adjustedY = Math.max(8, Math.min(y, window.innerHeight - menuHeight - 8));

  const target = primaryModule(row.kind, row.extension);
  const moduleLabel = t(target.i18nKey, { defaultValue: target.label });
  // #284 - a PDF document reads inline by default; PDF Takeoff is a separate,
  // explicit choice surfaced below.
  const inlinePreview = isInlinePreviewRow(row);
  // ITEM 10 - an image / video opens in the MediaLightbox, never PDF Takeoff.
  const lightbox = isLightboxRow(row);
  const isVideo = lightbox && isVideoRow(row);
  const takeoffTarget = pdfTakeoffTargetFor(row);

  function handleOpenPrimary() {
    if (inlinePreview && onInlinePreview) {
      onInlinePreview(row);
      onClose();
      return;
    }
    if (lightbox && onMediaPreview) {
      onMediaPreview(row);
      onClose();
      return;
    }
    navigate(target.route(row.project_id, row.id, row.extra));
    onClose();
  }

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
        icon={
          inlinePreview ? (
            <Eye size={13} />
          ) : lightbox ? (
            isVideo ? (
              <PlayCircle size={13} />
            ) : (
              <ImageIcon size={13} />
            )
          ) : (
            <ExternalLink size={13} />
          )
        }
        label={
          inlinePreview
            ? t('files.context.view_pdf', { defaultValue: 'View PDF' })
            : lightbox
              ? isVideo
                ? t('files.context.play_video', { defaultValue: 'Play video' })
                : t('files.context.view_image', { defaultValue: 'View image' })
              : t('files.context.open_in', {
                  defaultValue: 'Open in {{module}}',
                  module: moduleLabel,
                })
        }
        onClick={handleOpenPrimary}
      />
      {/* #284 - explicit, separate route into PDF Takeoff for a PDF document,
          now that the default open just reads the file inline. */}
      {takeoffTarget && (
        <MenuItem
          icon={<Ruler size={13} />}
          label={t('files.context.open_in_pdf_takeoff', {
            defaultValue: 'Open in PDF Takeoff',
          })}
          onClick={() => {
            navigate(takeoffTarget.route(row.project_id, row.id, row.extra));
            onClose();
          }}
        />
      )}
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
      {/* What the delete severs, above Delete so it is read before the eye
          lands on the item. Documents only - the endpoint answers for one of
          the eight kinds, and letting the other seven ask would draw the
          failure state on most rows in the manager. Renders nothing when
          nothing points at the file, which is the usual case, so the menu
          keeps its present shape. */}
      {row.kind === 'document' && <DocumentDeleteWarning documentId={row.id} />}
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
