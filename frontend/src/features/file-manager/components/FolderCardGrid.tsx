// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Folder-card grid — default landing view for the unified files hub.
 *
 * One card per category from the file tree. Click → drill into the
 * category's grid/list view. An empty card renders an "Add your first…"
 * CTA that opens the upload dialog.
 */

import { useTranslation } from 'react-i18next';
import {
  ArrowRight,
  FileText,
  Image as ImageIcon,
  Layout,
  Box,
  Pencil,
  Tag,
  FileBarChart,
  PenTool,
  Folder,
  Lock,
  Settings,
  UploadCloud,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';
import type { FileTreeNode, FileKind } from '../types';
import { KIND_TONE } from '../kindModule';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

const KIND_ICON: Record<FileKind, LucideIcon> = {
  document: FileText,
  photo: ImageIcon,
  sheet: Layout,
  bim_model: Box,
  dwg_drawing: Pencil,
  takeoff: Tag,
  report: FileBarChart,
  markup: PenTool,
};

/* Per-kind empty-state copy. Reads more useful than the generic
   "No documents yet" — each line names the format and the action so
   the user knows what to drop into this folder. */
const KIND_EMPTY_HINT: Record<FileKind, string> = {
  document: 'Upload specs, contracts, RFIs or reports (PDF, DOCX)',
  photo: 'Capture or upload site photos (JPG, PNG, HEIC)',
  sheet: 'Upload drawing sheets (PDF, DWF) with revision tracking',
  bim_model: 'Upload IFC, RVT or NWD models for 3D coordination',
  dwg_drawing: 'Upload DWG drawings for 2D takeoff',
  takeoff: 'Generate quantity takeoffs from sheets and models',
  report: 'Generate analysis, validation or cost reports',
  markup: 'Create PDF markups and review sessions',
};

// Per-kind accent tones (icon chip + share bar) live in `kindModule.ts`
// so the folder grid and the storage stats strip stay colour-consistent.

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

/** Count nested subfolders/types so the card can surface how the
 *  category is organised without a second API call. */
function countSubfolders(node: FileTreeNode): number {
  return node.children?.length ?? 0;
}

interface FolderCardGridProps {
  nodes: FileTreeNode[];
  isLoading?: boolean;
  onOpenCategory: (kind: FileKind) => void;
  onUpload: (kind: FileKind | null) => void;
  /** Owner-only: clicking the gear on a card opens the permissions modal. */
  onManageAccess?: (kind: FileKind) => void;
  /** ``{kind: count}`` of non-revoked grants per folder. Empty for non-owners. */
  permissionCounts?: Record<string, number>;
  /** True when the current user can manage permissions (project owner / admin). */
  canManageAccess?: boolean;
}

export function FolderCardGrid({
  nodes,
  isLoading,
  onOpenCategory,
  onUpload,
  onManageAccess,
  permissionCounts,
  canManageAccess,
}: FolderCardGridProps) {
  const { t } = useTranslation();

  if (isLoading && nodes.length === 0) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5 gap-3 p-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-[124px] rounded-xl border border-border-light bg-surface-secondary/40 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center text-content-tertiary">
        <Folder size={36} className="mb-3 opacity-60" />
        <p className="text-sm font-medium text-content-secondary">
          {t('files.tree.empty', { defaultValue: 'No files yet.' })}
        </p>
        <button
          type="button"
          onClick={() => onUpload(null)}
          className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold bg-oe-blue text-white hover:bg-oe-blue-hover transition-colors"
        >
          <UploadCloud size={14} />
          {t('files.upload', { defaultValue: 'Upload files' })}
        </button>
      </div>
    );
  }

  const totalBytes = nodes.reduce((acc, n) => acc + n.total_bytes, 0);

  return (
    <div className="p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5 gap-3">
      {nodes.map((node) => {
        const kind = bareKind(node.id);
        const count = permissionCounts?.[kind] ?? 0;
        return (
          <FolderCard
            key={node.id}
            node={node}
            totalBytes={totalBytes}
            onOpen={() => onOpenCategory(kind)}
            onUpload={() => onUpload(kind)}
            onManageAccess={
              canManageAccess && onManageAccess
                ? () => onManageAccess(kind)
                : undefined
            }
            permissionCount={count}
          />
        );
      })}
    </div>
  );
}

// Older backends shipped node ids prefixed with "category:" (e.g.
// "category:bim_model"). Strip the prefix defensively so cached URLs and
// older API responses still resolve to a valid FileKind.
function bareKind(id: string): FileKind {
  return id.replace(/^category:/, '') as FileKind;
}

interface FolderCardProps {
  node: FileTreeNode;
  /** Sum of bytes across every category — drives the share-of-storage bar. */
  totalBytes: number;
  onOpen: () => void;
  onUpload: () => void;
  onManageAccess?: () => void;
  permissionCount?: number;
}

function FolderCard({
  node,
  totalBytes,
  onOpen,
  onUpload,
  onManageAccess,
  permissionCount = 0,
}: FolderCardProps) {
  const { t } = useTranslation();
  const kind = bareKind(node.id);
  const Icon = KIND_ICON[kind] ?? Folder;
  const tone = KIND_TONE[kind] ?? KIND_TONE.document;
  const isEmpty = node.file_count === 0;
  const label = t(`files.category.${kind}`, { defaultValue: node.label });
  const isRestricted = permissionCount > 0;
  const lockTooltip = t('files.permissions.restricted_members', {
    count: permissionCount,
    defaultValue_one: 'Restricted: {{count}} member can access',
    defaultValue_other: 'Restricted: {{count}} members can access',
  });

  if (isEmpty) {
    return (
      <button
        type="button"
        onClick={onUpload}
        className={clsx(
          'group relative flex flex-col items-start text-left rounded-xl p-3.5 min-h-[124px]',
          'border border-dashed border-border-light bg-surface-primary/40',
          'hover:border-oe-blue/40 hover:bg-surface-primary transition-colors',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        )}
      >
        <div className="flex items-center gap-2 w-full">
          <span
            className={clsx(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
              tone.tile,
            )}
          >
            <Icon size={15} strokeWidth={2} className={tone.icon} />
          </span>
          <h3
            className="text-[13px] font-semibold text-content-primary truncate"
            title={label}
          >
            {label}
          </h3>
        </div>
        <p className="mt-2 text-xs text-content-tertiary line-clamp-2">
          {t(`files.empty_hint.${kind}`, {
            defaultValue: KIND_EMPTY_HINT[kind] ?? `No ${label.toLowerCase()} yet`,
          })}
        </p>
        <span className="mt-auto pt-2.5 inline-flex items-center gap-1.5 text-xs font-medium text-oe-blue opacity-80 group-hover:opacity-100">
          <UploadCloud size={12} />
          {t('files.cta.add_first_short', { defaultValue: 'Add files' })}
        </span>
      </button>
    );
  }

  const subfolders = countSubfolders(node);
  const sharePct =
    totalBytes > 0 ? Math.round((node.total_bytes / totalBytes) * 100) : 0;

  return (
    <div
      data-testid={`folder-card-${kind}`}
      className={clsx(
        'group relative flex flex-col rounded-xl min-h-[124px]',
        'border border-border-light bg-surface-elevated',
        'transition-all duration-150',
        'hover:-translate-y-0.5 hover:shadow-md hover:border-border-medium',
      )}
    >
      {/* Owner-only secondary actions overlay (gear + lock badge). */}
      <div className="absolute top-2.5 right-2.5 z-10 flex items-center gap-1">
        {isRestricted && (
          <span
            data-testid={`folder-lock-${kind}`}
            title={lockTooltip}
            aria-label={lockTooltip}
            className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-300"
          >
            <Lock size={10} />
          </span>
        )}
        {onManageAccess && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onManageAccess();
            }}
            data-testid={`folder-manage-access-${kind}`}
            aria-label={t('files.permissions.manage', { defaultValue: 'Manage access' })}
            title={t('files.permissions.manage', { defaultValue: 'Manage access' })}
            className="inline-flex h-5 w-5 items-center justify-center rounded-md text-content-tertiary opacity-0 group-hover:opacity-100 hover:bg-surface-secondary hover:text-content-primary transition-all"
          >
            <Settings size={11} />
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={onOpen}
        className={clsx(
          'flex flex-col text-left p-3.5 w-full h-full min-h-[124px]',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 rounded-xl',
        )}
      >
        {/* Header: icon chip + title inline (compact, app design-system style) */}
        <div className="flex items-center gap-2 w-full pr-12">
          <span
            className={clsx(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
              'transition-shadow group-hover:ring-2',
              tone.tile,
              tone.ring,
            )}
          >
            <Icon size={15} strokeWidth={2} className={tone.icon} />
          </span>
          <h3
            className="text-[13px] font-semibold text-content-primary truncate"
            title={label}
          >
            {label}
          </h3>
        </div>

        {/* Inline stat row — files · size · subfolders (denser than the old 2-col dl) */}
        <div className="mt-3 flex items-baseline gap-1.5">
          <span className="text-xl font-semibold text-content-primary tabular-nums leading-none">
            {node.file_count.toLocaleString(getNumberLocale())}
          </span>
          <span className="text-xs text-content-tertiary">
            {t('files.folder.files_count', { defaultValue: 'files' })}
          </span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-content-tertiary tabular-nums">
          <span className="font-medium text-content-secondary">
            {fmtBytes(node.total_bytes)}
          </span>
          {subfolders > 0 && (
            <>
              <span className="text-content-quaternary">·</span>
              <span>
                {t('files.folder.subfolders', {
                  defaultValue: '{{count}} folders',
                  count: subfolders,
                })}
              </span>
            </>
          )}
        </div>

        {/* Footer: share-of-storage micro bar + hover Open affordance */}
        <div className="mt-auto pt-3 flex items-center gap-2">
          <div
            className="flex-1 h-1 rounded-full bg-surface-tertiary overflow-hidden"
            role="img"
            aria-label={t('files.folder.share', {
              defaultValue: '{{pct}}% of total storage',
              pct: sharePct,
            })}
          >
            <div
              className={clsx('h-full rounded-full transition-[width] duration-500', tone.bar)}
              style={{ width: `${Math.max(sharePct, node.total_bytes > 0 ? 2 : 0)}%` }}
            />
          </div>
          <span className="text-2xs text-content-quaternary tabular-nums shrink-0 group-hover:hidden">
            {sharePct}%
          </span>
          <span className="hidden group-hover:inline-flex items-center gap-0.5 text-2xs font-medium text-oe-blue shrink-0">
            {t('files.folder.open', { defaultValue: 'Open' })}
            <ArrowRight size={11} />
          </span>
        </div>
      </button>
    </div>
  );
}
