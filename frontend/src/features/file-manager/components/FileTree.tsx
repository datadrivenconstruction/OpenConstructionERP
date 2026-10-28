// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Left-pane category list for the file manager. */

import { useTranslation } from 'react-i18next';
import { FileText, Image as ImageIcon, Layout, Box, Pencil, Folder, Tag, FileBarChart, PenTool, HardDrive } from 'lucide-react';
import clsx from 'clsx';
import type { FileTreeNode, FileKind } from '../types';
import { TrashNode } from '@/features/file-trash/TrashNode';
import { SavedViewsRail } from '@/features/file-saved-views';
import { fmtFixed } from '@/shared/lib/formatters';

const KIND_ICONS: Record<FileKind, typeof FileText> = {
  document: FileText,
  photo: ImageIcon,
  sheet: Layout,
  bim_model: Box,
  dwg_drawing: Pencil,
  takeoff: Tag,
  report: FileBarChart,
  markup: PenTool,
};

interface FileTreeProps {
  nodes: FileTreeNode[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  isLoading?: boolean;
  /** Active project — when set, mounts saved-views rail and routes the
   *  per-project Recycle Bin link to `/files/trash`. */
  projectId?: string | null;
}

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

export function FileTree({ nodes, selectedId, onSelect, isLoading, projectId }: FileTreeProps) {
  const { t } = useTranslation();

  const totalCount = nodes.reduce((acc, n) => acc + n.file_count, 0);
  const totalBytes = nodes.reduce((acc, n) => acc + n.total_bytes, 0);

  /* Per-category breakdown drives the proportional storage bar. We cap at the
     5 largest categories so the bar stays readable; everything else collapses
     into a neutral "Other" wedge. */
  const STORAGE_TINTS: Record<FileKind, string> = {
    document: 'bg-blue-400',
    photo: 'bg-emerald-400',
    sheet: 'bg-amber-400',
    bim_model: 'bg-violet-400',
    dwg_drawing: 'bg-orange-400',
    takeoff: 'bg-cyan-400',
    report: 'bg-pink-400',
    markup: 'bg-rose-400',
  };
  const storageBreakdown = totalBytes > 0
    ? [...nodes]
        .filter((n) => n.total_bytes > 0)
        .sort((a, b) => b.total_bytes - a.total_bytes)
        .slice(0, 6)
    : [];

  return (
    <aside className="w-60 shrink-0 border-r border-border-light bg-surface-secondary/40 overflow-y-auto">
      {totalBytes > 0 && (
        <div className="px-3 pt-3 pb-3 border-b border-border-light">
          <div className="flex items-center gap-1.5 mb-2 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
            <HardDrive size={11} strokeWidth={2} />
            <span>{t('files.tree.storage_used', { defaultValue: 'Storage used' })}</span>
          </div>
          <div className="text-base font-semibold text-content-primary tabular-nums">
            {fmtBytes(totalBytes)}
          </div>
          <div className="text-[10px] text-content-tertiary mb-2">
            {t('files.tree.file_count', {
              defaultValue: '{{count}} files',
              count: totalCount,
            })}
          </div>
          <div
            className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary"
            role="img"
            aria-label={t('files.tree.storage_breakdown', { defaultValue: 'Storage by category' })}
          >
            {storageBreakdown.map((node) => {
              const kind = node.id.replace(/^category:/, '') as FileKind;
              const pct = (node.total_bytes / totalBytes) * 100;
              return (
                <span
                  key={node.id}
                  className={clsx('block h-full', STORAGE_TINTS[kind] ?? 'bg-gray-300')}
                  style={{ width: `${pct}%` }}
                  title={`${t(`files.category.${kind}`, { defaultValue: node.label })}: ${fmtBytes(node.total_bytes)}`}
                />
              );
            })}
          </div>
        </div>
      )}

      <div className="px-3 pt-3 pb-2">
        <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary px-2 mb-1">
          {t('files.tree.title', { defaultValue: 'Categories' })}
        </div>

        <button
          type="button"
          onClick={() => onSelect(null)}
          className={clsx(
            'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-sm transition-colors',
            selectedId === null
              ? 'bg-oe-blue/10 text-oe-blue font-medium'
              : 'text-content-secondary hover:bg-surface-secondary',
          )}
        >
          <Folder size={14} className="shrink-0" />
          <span className="flex-1 truncate">
            {t('files.tree.all', { defaultValue: 'All files' })}
          </span>
          <span className="text-2xs text-content-tertiary tabular-nums">{totalCount}</span>
        </button>
      </div>

      <ul className="px-3 pb-4 space-y-0.5">
        {nodes.map((node) => {
          // Strip any legacy "category:" prefix from older backends.
          const kind = node.id.replace(/^category:/, '') as FileKind;
          const Icon = KIND_ICONS[kind] ?? Folder;
          const isActive = selectedId === kind;
          return (
            <li key={node.id}>
              <button
                type="button"
                onClick={() => onSelect(kind)}
                className={clsx(
                  'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-sm transition-colors',
                  isActive
                    ? 'bg-oe-blue/10 text-oe-blue font-medium'
                    : 'text-content-secondary hover:bg-surface-secondary',
                )}
              >
                <Icon size={14} className="shrink-0" />
                <span className="flex-1 truncate">
                  {t(`files.category.${kind}`, { defaultValue: node.label })}
                </span>
                <span className="text-2xs text-content-tertiary tabular-nums shrink-0">
                  {node.file_count}
                </span>
              </button>
              {node.total_bytes > 0 && (
                <div className="ps-8 pe-2 text-[10px] text-content-quaternary tabular-nums">
                  {fmtBytes(node.total_bytes)}
                </div>
              )}
            </li>
          );
        })}
        {!isLoading && nodes.length === 0 && (
          <li className="px-2 py-3 text-xs text-content-tertiary">
            {t('files.tree.empty', { defaultValue: 'No files yet.' })}
          </li>
        )}
      </ul>

      {projectId && (
        <div className="border-t border-border-light pt-2 mt-2">
          <SavedViewsRail projectId={projectId} />
        </div>
      )}

      <div className="mt-2 px-3 pb-3 border-t border-border-light pt-2">
        <TrashNode projectId={projectId ?? null} active={selectedId === 'trash'} />
      </div>
    </aside>
  );
}
