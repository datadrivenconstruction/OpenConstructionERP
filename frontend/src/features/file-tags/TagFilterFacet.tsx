// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Collapsible multi-select tag filter for the file-manager toolbar.
 *
 * Rendered as a button → dropdown panel with one checkbox per tag.
 * Emits the list of selected tag ids via `onChange`; the file-manager
 * is responsible for re-fetching the filtered list (or filtering
 * client-side via the tags map).
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, Tag } from 'lucide-react';
import clsx from 'clsx';
import { useFileTags } from './hooks';
import type { TagRecord } from './types';

interface TagFilterFacetProps {
  projectId: string;
  selectedTagIds: string[];
  onChange: (tagIds: string[]) => void;
  className?: string | undefined;
}

export function TagFilterFacet({
  projectId,
  selectedTagIds,
  onChange,
  className,
}: TagFilterFacetProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const tagsQuery = useFileTags(projectId);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  function toggle(id: string) {
    if (selectedTagIds.includes(id)) {
      onChange(selectedTagIds.filter((x) => x !== id));
    } else {
      onChange([...selectedTagIds, id]);
    }
  }

  const tags = tagsQuery.data ?? [];
  const selectedCount = selectedTagIds.length;
  const grouped = groupByCategory(tags);

  return (
    <div ref={containerRef} className={clsx('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={clsx(
          'flex items-center gap-1.5 h-9 px-3 text-xs font-medium rounded-lg border border-border-light text-content-secondary hover:bg-surface-secondary',
          selectedCount > 0 && 'border-oe-blue text-oe-blue bg-oe-blue/5',
        )}
      >
        <Tag size={12} />
        {selectedCount === 0
          ? t('files.tags.filter_label', { defaultValue: 'Tags' })
          : t('files.tags.filter_label_count', {
              defaultValue: 'Tags · {{count}}',
              count: selectedCount,
            })}
        <ChevronDown
          size={11}
          className={clsx('transition-transform', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute right-0 top-full mt-1 w-64 max-h-80 overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-lg z-20 p-2"
        >
          {tags.length === 0 && (
            <p className="px-2 py-3 text-xs text-content-tertiary text-center">
              {t('files.tags.no_tags', {
                defaultValue: 'No tags in this project yet.',
              })}
            </p>
          )}
          {selectedCount > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="w-full mb-1 px-2 py-1 text-2xs text-content-tertiary text-start hover:bg-surface-secondary rounded"
            >
              {t('files.tags.clear_filter', { defaultValue: 'Clear filter' })}
            </button>
          )}
          {Object.entries(grouped).map(([category, items]) => (
            <div key={category} className="mb-2">
              <p className="px-2 py-1 text-2xs uppercase tracking-wide text-content-tertiary">
                {category === 'uncategorized'
                  ? t('files.tags.uncategorized', { defaultValue: 'Other' })
                  : t(`files.tags.category.${category}`, {
                      defaultValue: category,
                    })}
              </p>
              {items.map((tag) => {
                const checked = selectedTagIds.includes(tag.id);
                return (
                  <label
                    key={tag.id}
                    role="option"
                    aria-selected={checked}
                    className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-surface-secondary text-xs"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(tag.id)}
                      className="rounded border-border-light text-oe-blue focus:ring-oe-blue/20"
                    />
                    <span
                      aria-hidden="true"
                      className="inline-block h-2 w-2 rounded-full shrink-0"
                      style={{ backgroundColor: tag.color }}
                    />
                    <span className="truncate text-content-primary">
                      {tag.display_name}
                    </span>
                    <span className="ms-auto text-2xs text-content-tertiary tabular-nums">
                      {tag.assignment_count}
                    </span>
                  </label>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function groupByCategory(tags: TagRecord[]): Record<string, TagRecord[]> {
  const out: Record<string, TagRecord[]> = {};
  for (const tag of tags) {
    const key = tag.category ?? 'uncategorized';
    if (!out[key]) out[key] = [];
    out[key]!.push(tag);
  }
  return out;
}
