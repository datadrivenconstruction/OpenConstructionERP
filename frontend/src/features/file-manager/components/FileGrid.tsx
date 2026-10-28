// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Grid view of files — default right-pane layout. */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ExternalLink, FileText, Image as ImageIcon, Layout, Box, Pencil, File, PenTool, FileBarChart, Tag, Star } from 'lucide-react';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { AuthImage } from '@/shared/ui';
import { primaryModule } from '../kindModule';
import { SnippetHighlight } from '@/features/file-search/SnippetHighlight';
import { CDEBadge } from './CDEBadge';
import { favoriteKey, type FileRow, type FileKind } from '../types';
import { fmtFixed } from '@/shared/lib/formatters';
import { TagPill } from '@/features/file-tags/TagPill';
import { useTagsByFile } from '@/features/file-tags/hooks';

const KIND_ICON: Record<FileKind, typeof FileText> = {
  document: FileText,
  photo: ImageIcon,
  sheet: Layout,
  bim_model: Box,
  dwg_drawing: Pencil,
  takeoff: Tag,
  report: FileBarChart,
  markup: PenTool,
};

const KIND_TINT: Record<FileKind, string> = {
  document: 'bg-blue-50 dark:bg-blue-950/20 text-blue-600 dark:text-blue-400',
  photo: 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400',
  sheet: 'bg-amber-50 dark:bg-amber-950/20 text-amber-600 dark:text-amber-400',
  bim_model: 'bg-violet-50 dark:bg-violet-950/20 text-violet-600 dark:text-violet-400',
  dwg_drawing: 'bg-orange-50 dark:bg-orange-950/20 text-orange-600 dark:text-orange-400',
  takeoff: 'bg-cyan-50 dark:bg-cyan-950/20 text-cyan-600 dark:text-cyan-400',
  report: 'bg-pink-50 dark:bg-pink-950/20 text-pink-600 dark:text-pink-400',
  markup: 'bg-rose-50 dark:bg-rose-950/20 text-rose-600 dark:text-rose-400',
};

interface FileGridProps {
  items: FileRow[];
  selectedIds: Set<string>;
  onSelect: (id: string, additive: boolean, shift?: boolean) => void;
  onOpen: (row: FileRow) => void;
  isLoading?: boolean;
  /** ``favoriteKey(kind, id)`` membership set for the current user. */
  favoriteKeys?: Set<string>;
  /** Toggle a tile's favourite state. Omit to hide the star control. */
  onToggleFavorite?: (row: FileRow, isFavorite: boolean) => void;
  /** Right-click a tile — opens the shared FileContextMenu at the cursor. */
  onContextMenu?: (row: FileRow, x: number, y: number) => void;
  /** The live content-search term, so matched text can be highlighted.
      Only set while the page is in content mode; filename mode leaves the
      tiles untouched. */
  searchQuery?: string;
}

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

/**
 * The tags assigned to one file, shown under its tile.
 *
 * Three at most, because a tile is narrower than a tag list can get and the
 * fourth would push the card taller than its neighbours. The remainder is
 * counted rather than hidden, so a file with eight tags does not read as a
 * file with three.
 *
 * One request per visible tile. The bulk lookup exists on the server
 * (`tags_by_files`) and has no client yet, so this is the shape the feature
 * ships in: fine at a page of tiles, and the first thing to change if the page
 * size grows. Stated rather than left for someone to discover in a network tab.
 */
function FileGridTagsRow({
  projectId,
  kind,
  fileId,
}: {
  projectId: string;
  kind: FileKind;
  fileId: string;
}) {
  const { data: tags } = useTagsByFile(projectId, kind, fileId);
  if (!tags || tags.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-0.5">
      {tags.slice(0, 3).map((tag) => (
        <TagPill key={tag.id} tag={tag} size="sm" />
      ))}
      {tags.length > 3 && (
        <span className="text-[9px] text-content-tertiary tabular-nums self-center">
          +{tags.length - 3}
        </span>
      )}
    </div>
  );
}

export function FileGrid({
  items,
  selectedIds,
  onSelect,
  onOpen,
  isLoading,
  favoriteKeys,
  onToggleFavorite,
  onContextMenu,
  searchQuery,
}: FileGridProps) {
  const { t } = useTranslation();

  // ── Keyboard roving navigation ──────────────────────────────────────
  // Exactly one tile carries ``tabIndex={0}`` (the roving item); the rest
  // are ``-1`` so Tab lands on the grid once and arrow keys move focus
  // inside it. Enter opens, Space toggles selection, Shift+Arrow extends.
  const [focusIndex, setFocusIndex] = useState(0);
  const tileRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Keep the roving index in range as the list grows / shrinks / filters.
  useEffect(() => {
    if (focusIndex > items.length - 1) {
      setFocusIndex(Math.max(0, items.length - 1));
    }
  }, [items.length, focusIndex]);

  // How many tiles sit on the first visual row — derived from the DOM so it
  // tracks the responsive column count (2 → 5) without hard-coding it.
  const columnCount = (): number => {
    const els = tileRefs.current;
    const first = els[0]?.getBoundingClientRect().top;
    if (first == null) return 1;
    let cols = 1;
    for (let i = 1; i < els.length; i += 1) {
      const top = els[i]?.getBoundingClientRect().top;
      if (top == null || Math.abs(top - first) > 1) break;
      cols += 1;
    }
    return cols;
  };

  const step = (nextIndex: number, shift: boolean) => {
    const clamped = Math.max(0, Math.min(items.length - 1, nextIndex));
    const targetRow = items[clamped];
    if (shift && targetRow) onSelect(targetRow.id, true, true);
    setFocusIndex(clamped);
    tileRefs.current[clamped]?.focus();
  };

  const handleTileKeyDown = (e: React.KeyboardEvent, idx: number, row: FileRow) => {
    // Only act on keys targeting the tile button itself, not anything that
    // bubbles up from nested controls.
    if (e.target !== e.currentTarget) return;
    // ``dir`` on the document root flips the horizontal arrows so RTL users
    // navigate in the reading direction they expect.
    const rtl = typeof document !== 'undefined' && document.documentElement.dir === 'rtl';
    switch (e.key) {
      case 'ArrowRight':
        e.preventDefault();
        step(idx + (rtl ? -1 : 1), e.shiftKey);
        break;
      case 'ArrowLeft':
        e.preventDefault();
        step(idx + (rtl ? 1 : -1), e.shiftKey);
        break;
      case 'ArrowDown':
        e.preventDefault();
        step(idx + columnCount(), e.shiftKey);
        break;
      case 'ArrowUp':
        e.preventDefault();
        step(idx - columnCount(), e.shiftKey);
        break;
      case 'Home':
        e.preventDefault();
        step(0, e.shiftKey);
        break;
      case 'End':
        e.preventDefault();
        step(items.length - 1, e.shiftKey);
        break;
      case 'Enter':
        e.preventDefault();
        onOpen(row);
        break;
      case ' ':
      case 'Spacebar':
        e.preventDefault();
        onSelect(row.id, true);
        break;
      default:
        break;
    }
  };

  if (isLoading && items.length === 0) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-3 p-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="aspect-[4/5] rounded-xl border border-border-light bg-surface-secondary/40 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center text-content-tertiary">
        <File size={28} className="mb-3 opacity-60" />
        <p className="text-sm">{t('files.empty', { defaultValue: 'No files match your filters.' })}</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-3 p-4">
      {items.map((row, idx) => {
        const Icon = KIND_ICON[row.kind] ?? File;
        const tint = KIND_TINT[row.kind] ?? 'bg-surface-secondary text-content-secondary';
        const isSelected = selectedIds.has(row.id);
        const target = primaryModule(row.kind, row.extension);
        const moduleLabel = t(target.i18nKey, { defaultValue: target.label });
        // #284 - a PDF document's primary action reads it inline rather than
        // routing to a module, so the tile shows a plain "View" affordance
        // instead of "Open in <module>". ITEM 10 - an image / video shows
        // "View" / "Play" (the target label) for the same in-place reason.
        const openLabel = target.inlinePreview
          ? t('files.actions.view_file', { defaultValue: 'View' })
          : target.mediaPreview
            ? t(target.i18nKey, { defaultValue: target.label })
            : t('files.actions.open_in_short', {
                defaultValue: 'Open in {{module}}',
                module: moduleLabel,
              });
        // A plain in-place viewer (PDF reader / media lightbox) is not a
        // navigation, so the tile tooltip says "view" rather than "open in".
        const opensInPlace = Boolean(target.inlinePreview || target.mediaPreview);
        const isFavorite = favoriteKeys?.has(favoriteKey(row.kind, row.id)) ?? false;
        return (
          <div
            key={row.id}
            onContextMenu={
              onContextMenu
                ? (e) => {
                    e.preventDefault();
                    onContextMenu(row, e.clientX, e.clientY);
                  }
                : undefined
            }
            className={clsx(
              'group relative flex flex-col rounded-xl border bg-surface-elevated text-left transition-all',
              'overflow-hidden',
              isSelected
                ? 'border-oe-blue ring-2 ring-oe-blue/30 shadow-md'
                : 'border-border-light hover:border-border hover:shadow-sm',
            )}
            title={
              opensInPlace
                ? t('files.tile.tooltip_view', {
                    defaultValue: '{{name}} - double-click to view',
                    name: row.name,
                  })
                : t('files.tile.tooltip', {
                    defaultValue: '{{name}} - double-click to open in {{module}}',
                    name: row.name,
                    module: moduleLabel,
                  })
            }
          >
            <button
              type="button"
              ref={(el) => {
                tileRefs.current[idx] = el;
              }}
              tabIndex={idx === focusIndex ? 0 : -1}
              onClick={(e) => {
                setFocusIndex(idx);
                onSelect(row.id, e.metaKey || e.ctrlKey, e.shiftKey);
              }}
              onDoubleClick={() => onOpen(row)}
              onKeyDown={(e) => handleTileKeyDown(e, idx, row)}
              className="flex flex-col text-left w-full focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <div className={clsx('relative aspect-[4/3] flex items-center justify-center', tint)}>
                {row.thumbnail_url ? (
                  <AuthImage
                    src={row.thumbnail_url}
                    alt=""
                    loading="lazy"
                    className="w-full h-full object-cover"
                    placeholder={<Icon size={32} strokeWidth={1.5} />}
                    fallback={<Icon size={32} strokeWidth={1.5} />}
                  />
                ) : (
                  <Icon size={32} strokeWidth={1.5} />
                )}
                {row.extension && (
                  <span className="absolute bottom-1.5 left-1.5 px-1.5 py-px rounded bg-black/60 text-white text-[9px] font-mono uppercase tracking-wide">
                    {row.extension.replace(/^\./, '')}
                  </span>
                )}
              </div>
              <div className="px-2.5 py-2 min-w-0">
                {typeof row.extra?.drawing_number === 'string' && row.extra.drawing_number && (
                  <p className="font-mono text-[10px] text-content-tertiary truncate" title={t('files.drawing_number', { defaultValue: 'Drawing number' })}>
                    {row.extra.drawing_number}
                  </p>
                )}
                <p className="text-xs font-medium text-content-primary truncate" title={row.name}>
                  {row.name}
                </p>
                <div className="mt-1 flex items-center gap-1 flex-wrap">
                  {typeof row.extra?.revision_code === 'string' && row.extra.revision_code && (
                    <span className="inline-flex items-center rounded-md border border-border-light px-1 py-px text-[9px] font-medium text-content-secondary">
                      Rev {row.extra.revision_code}
                    </span>
                  )}
                  <CDEBadge state={row.extra?.cde_state as string | undefined} size="xs" />
                  {row.discipline && (
                    <span className="inline-flex items-center rounded-md bg-surface-secondary px-1 py-px text-[9px] font-medium text-content-secondary truncate max-w-[80px]">
                      {row.discipline}
                    </span>
                  )}
                </div>
                {typeof row.extra?.snippet === 'string' && row.extra.snippet && (
                  <p className="mt-1 text-[10px] leading-snug text-content-secondary line-clamp-2">
                    <SnippetHighlight text={row.extra.snippet} query={searchQuery ?? ''} />
                  </p>
                )}
                {/* A content-search hit is built from the index, not from a
                    directory listing: it carries no size and no modified date.
                    Printing the placeholder zero would claim the file is empty,
                    so the hit shows how much text was searched instead. */}
                {typeof row.extra?.snippet === 'string' && row.extra.snippet ? (
                  typeof row.extra?.page_count === 'number' && (
                    <div className="mt-1 text-[10px] text-content-tertiary tabular-nums">
                      {t('files.search.pages', { count: row.extra.page_count })}
                    </div>
                  )
                ) : (
                  <div className="mt-1 flex items-center justify-between text-[10px] text-content-tertiary tabular-nums">
                    <span>{fmtBytes(row.size_bytes)}</span>
                    {row.modified_at && (
                      <DateDisplay value={row.modified_at} format="relative" className="ms-2 shrink-0" />
                    )}
                  </div>
                )}
                <FileGridTagsRow projectId={row.project_id} kind={row.kind} fileId={row.id} />
              </div>
            </button>

            {/* Hover overlay — opens the file in its native module.
                Sits over the thumbnail so it's discoverable; nested
                button (with stopPropagation) keeps the surrounding card
                selectable on a single click. */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onOpen(row);
              }}
              className={clsx(
                'absolute top-1.5 right-1.5 inline-flex items-center gap-1 h-6 px-2 rounded-md',
                'bg-surface-elevated/95 backdrop-blur-sm shadow-sm border border-border-light',
                'text-[10px] font-medium text-content-secondary',
                'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity',
                'hover:text-oe-blue hover:border-oe-blue/40',
              )}
              title={t(target.descriptionI18nKey, { defaultValue: target.description })}
            >
              <span className="truncate max-w-[120px]">{openLabel}</span>
              <ExternalLink size={9} className="shrink-0 opacity-70" />
            </button>

            {/* Favourite star — top-left. Always visible once favourited
                (so the user can find their starred files at a glance);
                fades in on hover otherwise. */}
            {onToggleFavorite && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleFavorite(row, isFavorite);
                }}
                aria-pressed={isFavorite}
                className={clsx(
                  'absolute top-1.5 left-1.5 inline-flex items-center justify-center h-6 w-6 rounded-md',
                  'bg-surface-elevated/95 backdrop-blur-sm shadow-sm border border-border-light',
                  'transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
                  isFavorite
                    ? 'opacity-100 text-amber-500 hover:text-amber-600'
                    : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-content-tertiary hover:text-amber-500',
                )}
                title={
                  isFavorite
                    ? t('files.favorites.remove', { defaultValue: 'Remove from favourites' })
                    : t('files.favorites.add', { defaultValue: 'Add to favourites' })
                }
              >
                <Star size={13} strokeWidth={2} fill={isFavorite ? 'currentColor' : 'none'} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
