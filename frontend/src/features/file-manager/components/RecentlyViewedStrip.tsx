// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Recently-viewed files strip — Phase-0 quick win.
 *
 * Tracks the last 8 opened files in localStorage and surfaces them as a
 * one-row chip rail above the folder-card grid on the /files landing.
 * Click → re-routes via the same primaryModule resolver used elsewhere.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Clock, X } from 'lucide-react';
import clsx from 'clsx';
import type { FileKind, FileRow } from '../types';

const STORAGE_KEY = 'file-manager:recently-viewed';
const MAX_ITEMS = 8;

export interface RecentItem {
  id: string;
  project_id: string;
  kind: FileKind;
  name: string;
  extension?: string | undefined;
  extra?: Record<string, unknown>;
  viewed_at: number;
}

function readRecents(): RecentItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (r): r is RecentItem =>
        r &&
        typeof r.id === 'string' &&
        typeof r.project_id === 'string' &&
        typeof r.kind === 'string' &&
        typeof r.name === 'string' &&
        typeof r.viewed_at === 'number',
    );
  } catch {
    return [];
  }
}

function writeRecents(items: RecentItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
  } catch {
    /* quota exhausted or unavailable */
  }
}

/** Record a file opening — call from FileManagerPage.handleOpen. */
export function recordRecentlyViewed(row: FileRow) {
  const items = readRecents();
  const next: RecentItem[] = [
    {
      id: row.id,
      project_id: row.project_id,
      kind: row.kind,
      name: row.name,
      extension: row.extension ?? undefined,
      extra: row.extra,
      viewed_at: Date.now(),
    },
    ...items.filter((r) => r.id !== row.id),
  ].slice(0, MAX_ITEMS);
  writeRecents(next);
  window.dispatchEvent(new Event('file-manager:recents-changed'));
}

export function useRecentlyViewed(projectId?: string | null): {
  items: RecentItem[];
  clear: () => void;
  remove: (id: string) => void;
} {
  const [items, setItems] = useState<RecentItem[]>(() => readRecents());

  useEffect(() => {
    const handler = () => setItems(readRecents());
    window.addEventListener('file-manager:recents-changed', handler);
    window.addEventListener('storage', handler);
    return () => {
      window.removeEventListener('file-manager:recents-changed', handler);
      window.removeEventListener('storage', handler);
    };
  }, []);

  const scoped = projectId ? items.filter((r) => r.project_id === projectId) : items;

  const clear = useCallback(() => {
    writeRecents([]);
    setItems([]);
    window.dispatchEvent(new Event('file-manager:recents-changed'));
  }, []);

  const remove = useCallback((id: string) => {
    const next = readRecents().filter((r) => r.id !== id);
    writeRecents(next);
    setItems(next);
    window.dispatchEvent(new Event('file-manager:recents-changed'));
  }, []);

  return { items: scoped, clear, remove };
}

interface RecentlyViewedStripProps {
  projectId?: string | null;
  onOpen: (item: RecentItem) => void;
}

export function RecentlyViewedStrip({ projectId, onOpen }: RecentlyViewedStripProps) {
  const { t } = useTranslation();
  const { items, clear, remove } = useRecentlyViewed(projectId);

  if (items.length === 0) return null;

  return (
    <div className="px-4 pt-3 pb-2 border-b border-border-light bg-surface-secondary/40">
      <div className="flex items-center gap-2 mb-2">
        <Clock size={12} className="text-content-tertiary" />
        <span className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
          {t('files.recent.title', { defaultValue: 'Recently viewed' })}
        </span>
        <button
          type="button"
          onClick={clear}
          className="ml-auto text-2xs text-content-quaternary hover:text-content-secondary transition-colors"
        >
          {t('files.recent.clear', { defaultValue: 'Clear' })}
        </button>
      </div>
      <div className="flex items-center gap-2 overflow-x-auto pb-1 -mx-0.5 px-0.5">
        {items.map((item) => (
          <RecentChip
            key={item.id}
            item={item}
            onOpen={() => onOpen(item)}
            onRemove={() => remove(item.id)}
          />
        ))}
      </div>
    </div>
  );
}

interface RecentChipProps {
  item: RecentItem;
  onOpen: () => void;
  onRemove: () => void;
}

function RecentChip({ item, onOpen, onRemove }: RecentChipProps) {
  const { t } = useTranslation();
  return (
    <div
      className={clsx(
        'group relative shrink-0 inline-flex items-center gap-1.5 h-8 pl-2.5 pr-1.5',
        'rounded-full border border-border-light bg-surface-elevated',
        'hover:border-oe-blue/40 hover:bg-surface-primary transition-colors',
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-content-secondary hover:text-content-primary max-w-[200px] truncate"
        title={item.name}
      >
        <span
          className="inline-flex h-4 px-1 items-center justify-center rounded text-2xs font-semibold uppercase bg-oe-blue/10 text-oe-blue tabular-nums"
          aria-hidden
        >
          {(item.extension ?? item.kind.charAt(0)).slice(0, 4)}
        </span>
        <span className="truncate">{item.name}</span>
      </button>
      <button
        type="button"
        onClick={onRemove}
        aria-label={t('files.recent.remove', { defaultValue: 'Remove from recent' })}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-content-quaternary hover:text-content-primary hover:bg-surface-secondary opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <X size={11} />
      </button>
    </div>
  );
}
