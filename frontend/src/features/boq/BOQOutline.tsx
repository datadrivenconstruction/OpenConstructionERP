// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BOQOutline - a jump-to-section table of contents for the BOQ grid.
 *
 * On a large estimate, scrolling to a particular trade or section by hand is
 * slow. This popover lists every section header (nested sections indented) and
 * jumps the grid straight to the chosen one, flashing the row on arrival. It is
 * a navigation aid only: it never changes the data, the collapse state, or the
 * totals. The jump goes through the grid's imperative scrollToPosition handle,
 * which is re-callable so picking the same section twice still works.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ListTree, Search, X } from 'lucide-react';
import { isSection, type Position } from './api';

export interface BOQOutlineProps {
  /** The full, document-ordered positions list (sections + leaves). */
  positions: Position[];
  /** Jump the grid to this section/position id and flash it. */
  onJump: (positionId: string) => void;
}

interface OutlineItem {
  id: string;
  ordinal: string;
  description: string;
  /** Number of section ancestors, used to indent nested sections. */
  depth: number;
}

export function BOQOutline({ positions, onJump }: BOQOutlineProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);

  // Flat, document-ordered list of section headers with their nesting depth
  // (count of section ancestors). Leaf positions are excluded.
  const items = useMemo<OutlineItem[]>(() => {
    const byId = new Map(positions.map((p) => [p.id, p]));
    const depthOf = (p: Position): number => {
      let depth = 0;
      let parentId = p.parent_id;
      const guard = new Set<string>();
      while (parentId && !guard.has(parentId)) {
        guard.add(parentId);
        const parent = byId.get(parentId);
        if (!parent) break;
        if (isSection(parent)) depth += 1;
        parentId = parent.parent_id;
      }
      return depth;
    };
    return positions
      .filter(isSection)
      .map((s) => ({
        id: s.id,
        ordinal: s.ordinal ?? '',
        description: s.description ?? '',
        depth: depthOf(s),
      }));
  }, [positions]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) => it.description.toLowerCase().includes(q) || it.ordinal.toLowerCase().includes(q),
    );
  }, [items, query]);

  // Close on Escape or an outside click while the popover is open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        setOpen(false);
      }
    }
    function onDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [open]);

  // Start each open with a clean filter.
  useEffect(() => {
    if (open) setQuery('');
  }, [open]);

  const handleJump = (id: string) => {
    onJump(id);
    setOpen(false);
  };

  const sectionCount = items.length;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={sectionCount === 0}
        title={t('boq.outline_btn_hint', { defaultValue: 'Jump to a section' })}
        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <ListTree size={14} />
        {t('boq.outline_btn', { defaultValue: 'Outline' })}
      </button>

      {open && (
        <div
          role="menu"
          aria-label={t('boq.outline_title', { defaultValue: 'Sections' })}
          className="absolute right-0 z-30 mt-1 w-72 rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-fade-in"
        >
          {/* Filter */}
          <div className="border-b border-border-light p-2">
            <div className="relative">
              <Search
                size={13}
                className="pointer-events-none absolute start-2 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                autoFocus
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('boq.outline_filter_ph', { defaultValue: 'Filter sections...' })}
                aria-label={t('boq.outline_filter_ph', { defaultValue: 'Filter sections...' })}
                className="h-7 w-full rounded-md border border-border-light bg-surface-primary ps-7 pe-6 text-xs text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label={t('common.clear', { defaultValue: 'Clear' })}
                  className="absolute end-1.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-primary"
                >
                  <X size={13} />
                </button>
              )}
            </div>
          </div>

          {/* Section list */}
          <div className="max-h-80 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-content-tertiary">
                {sectionCount === 0
                  ? t('boq.outline_empty', { defaultValue: 'No sections yet' })
                  : t('boq.outline_no_match', { defaultValue: 'No sections match' })}
              </p>
            ) : (
              filtered.map((it) => (
                <button
                  key={it.id}
                  type="button"
                  role="menuitem"
                  onClick={() => handleJump(it.id)}
                  title={`${it.ordinal} ${it.description}`.trim()}
                  className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-xs text-content-primary hover:bg-surface-secondary transition-colors"
                  style={{ paddingLeft: `${12 + it.depth * 14}px` }}
                >
                  {it.ordinal && (
                    <span className="shrink-0 font-mono text-2xs text-content-tertiary tabular-nums">
                      {it.ordinal}
                    </span>
                  )}
                  <span className="truncate">
                    {it.description ||
                      t('boq.outline_untitled', { defaultValue: 'Untitled section' })}
                  </span>
                </button>
              ))
            )}
          </div>

          {sectionCount > 0 && (
            <div className="border-t border-border-light px-3 py-1.5 text-2xs text-content-tertiary">
              {t('boq.outline_count', { defaultValue: 'Sections ({{count}})', count: sectionCount })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
