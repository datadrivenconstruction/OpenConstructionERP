// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SearchableSelect - a type-ahead picker for lists too long to scroll.
//
// Why it exists: a native <select> gives the user one tool for finding an
// entry, which is scrolling, and it stops being a tool somewhere around thirty
// options. The resource picker on the schedule Resources tab lists every
// resource in the installation - crews, plant, staff, subcontractors - in one
// flat run, and a user reported that picking one means scrolling a long list
// with no way to type what they are looking for.
//
// It also answers the second half of that report. Two resources can carry the
// same name and differ only by the project they are filed under or by their
// code, and a label of just the name makes those two rows indistinguishable.
// So an option can carry a `hint` (rendered monospace at the right, for a code)
// and a `meta` (rendered dim after the label, for a qualifier like the owning
// project). Both are searched, not just displayed - a user who knows the code
// can type the code.
//
// Deliberately generic. There were already four hand-rolled search-and-filter
// lists in this tree (the country picker, the catalogue picker, the assembly
// picker, the cost-item autocomplete), each with its own keyboard handling and
// its own bugs. This is the one to reach for next time, and the country picker
// is the template it was built from so the two behave the same way.

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, Search, X } from 'lucide-react';
import clsx from 'clsx';

import { foldForSearch, highlightMatch } from '@/shared/lib/highlightMatch';

export interface SearchableSelectOption {
  /** The stored value. Must be unique across the option list. */
  value: string;
  /** Primary text. This is what the trigger shows and what gets highlighted. */
  label: string;
  /** Short code shown monospace on the right of the row. Searched. */
  hint?: string;
  /** Qualifier shown dim after the label - a project, a location, a status.
   *  Searched. This is what separates two resources with the same name. */
  meta?: string;
  /** Heading this option is filed under. Options carrying the same group are
   *  drawn together beneath one sticky header. */
  group?: string;
  /** Extra text nobody sees but everybody can search by (synonyms, an id). */
  keywords?: string;
  disabled?: boolean;
}

export interface SearchableSelectProps {
  value: string;
  onChange: (next: string) => void;
  options: SearchableSelectOption[];
  /** id wired to the trigger so a sibling <label htmlFor> reaches it. */
  id?: string;
  /** Trigger text when nothing is picked. */
  placeholder?: string;
  searchPlaceholder?: string;
  /** Offer a "none" row at the top of the list which stores "". */
  allowEmpty?: boolean;
  /** Label for that row. Defaults to a translated "None". */
  emptyLabel?: string;
  /** Render a skeleton instead of the trigger. */
  loading?: boolean;
  disabled?: boolean;
  /** Below this many options the search box is hidden - a five-item list does
   *  not need one and a search box on it just looks like clutter. */
  searchThreshold?: number;
  className?: string;
  /** Extra classes for the popover, for the rare caller that has to escape a
   *  clipping ancestor. */
  popoverClassName?: string;
  /** Lands on the trigger, so a selector that used to find the <select> this
   *  replaced still finds the control. */
  'data-testid'?: string;
}

type Row =
  | { kind: 'empty'; idx: number }
  | { kind: 'option'; idx: number; option: SearchableSelectOption }
  | { kind: 'group'; label: string };

/** Everything about an option a query is allowed to match. */
function haystack(o: SearchableSelectOption): string {
  return foldForSearch([o.label, o.hint, o.meta, o.group, o.keywords].filter(Boolean).join(' '));
}

export function SearchableSelect({
  value,
  onChange,
  options,
  id,
  placeholder,
  searchPlaceholder,
  allowEmpty = false,
  emptyLabel,
  loading = false,
  disabled = false,
  searchThreshold = 8,
  className,
  popoverClassName,
  'data-testid': testId,
}: SearchableSelectProps) {
  const { t } = useTranslation();
  const reactId = useId();
  const listboxId = `${id ?? reactId}-listbox`;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selected = useMemo(() => options.find((o) => o.value === value), [options, value]);

  const filtered = useMemo(() => {
    const q = foldForSearch(query.trim());
    if (!q) return options;
    // Whole query first, then all terms. Same order of preference as the
    // highlighter, so a row that survives the filter always has something
    // marked on it.
    const phrase = options.filter((o) => haystack(o).includes(q));
    if (phrase.length > 0) return phrase;
    const terms = q.split(/\s+/).filter((s) => s.length >= 2);
    if (terms.length === 0) return [];
    return options.filter((o) => {
      const hay = haystack(o);
      return terms.every((term) => hay.includes(term));
    });
  }, [options, query]);

  // Flatten to rows so the keyboard walks exactly what the eye sees: group
  // headers are rows in the list but never land under the cursor.
  const { rows, pickable } = useMemo(() => {
    const out: Row[] = [];
    let idx = 0;
    if (allowEmpty && !query.trim()) out.push({ kind: 'empty', idx: idx++ });
    let lastGroup: string | undefined;
    for (const option of filtered) {
      if (option.group && option.group !== lastGroup) {
        out.push({ kind: 'group', label: option.group });
        lastGroup = option.group;
      }
      out.push({ kind: 'option', idx: idx++, option });
    }
    return { rows: out, pickable: idx };
  }, [filtered, allowEmpty, query]);

  useEffect(() => {
    setHighlight(0);
  }, [query, open]);

  // Opening on a set value should land the cursor on that value rather than at
  // the top - the user's own answer to "which one is picked" is the row they
  // want to see first.
  useEffect(() => {
    if (!open) return;
    const at = rows.find((r) => r.kind === 'option' && r.option.value === value);
    if (at && at.kind === 'option') setHighlight(at.idx);
    // rows is intentionally not a dependency: this is the on-open placement,
    // and re-running it as the user types would fight the arrow keys.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (popoverRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const showSearch = options.length >= searchThreshold;

  useEffect(() => {
    if (open && showSearch) setTimeout(() => searchRef.current?.focus(), 0);
  }, [open, showSearch]);

  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${highlight}"]`)?.scrollIntoView({
      block: 'nearest',
    });
  }, [highlight, open]);

  const close = (returnFocus = true) => {
    setOpen(false);
    setQuery('');
    if (returnFocus) triggerRef.current?.focus();
  };

  const pick = (idx: number) => {
    const row = rows.find((r) => r.kind !== 'group' && r.idx === idx);
    if (!row || row.kind === 'group') return;
    if (row.kind === 'empty') {
      onChange('');
      close();
      return;
    }
    if (row.option.disabled) return;
    onChange(row.option.value);
    close();
  };

  const step = (delta: number) => {
    if (pickable === 0) return;
    setHighlight((h) => Math.min(Math.max(h + delta, 0), pickable - 1));
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        close();
        break;
      case 'ArrowDown':
        e.preventDefault();
        step(1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        step(-1);
        break;
      case 'Home':
        e.preventDefault();
        setHighlight(0);
        break;
      case 'End':
        e.preventDefault();
        setHighlight(Math.max(pickable - 1, 0));
        break;
      case 'Enter':
        e.preventDefault();
        pick(highlight);
        break;
      case 'Tab':
        close(false);
        break;
      default:
        break;
    }
  };

  if (loading) {
    return <div className={clsx('h-9 animate-pulse rounded-lg bg-surface-secondary', className)} />;
  }

  return (
    <div className={clsx('relative', className)}>
      <button
        id={id}
        ref={triggerRef}
        type="button"
        data-testid={testId}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        disabled={disabled || options.length === 0}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={handleKey}
        className={clsx(
          'flex h-9 w-full items-center justify-between gap-2 rounded-lg border bg-surface-primary px-3 text-sm',
          'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
          'border-border hover:border-content-tertiary transition-colors',
          'disabled:opacity-60 disabled:pointer-events-none',
        )}
      >
        <span className="flex min-w-0 flex-1 items-center gap-2 text-left">
          {selected ? (
            <>
              <span className="truncate text-content-primary">{selected.label}</span>
              {selected.meta && (
                <span className="truncate text-xs text-content-tertiary">{selected.meta}</span>
              )}
              {selected.hint && (
                <span className="ml-auto shrink-0 font-mono text-[10px] text-content-tertiary">
                  {selected.hint}
                </span>
              )}
            </>
          ) : (
            <span className="truncate text-content-tertiary">
              {placeholder ??
                t('searchable_select.placeholder', { defaultValue: 'Select an option' })}
            </span>
          )}
        </span>
        <ChevronDown
          size={16}
          className={clsx('shrink-0 text-content-tertiary transition-transform', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div
          ref={popoverRef}
          className={clsx(
            'absolute z-[60] mt-1 w-full overflow-hidden rounded-lg border border-border bg-surface-elevated shadow-xl',
            'animate-scale-in origin-top',
            popoverClassName,
          )}
        >
          {showSearch && (
            <div className="flex items-center gap-2 border-b border-border-light bg-surface-secondary px-3 py-2">
              <Search size={14} className="shrink-0 text-content-tertiary" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKey}
                placeholder={
                  searchPlaceholder ??
                  t('searchable_select.search_placeholder', { defaultValue: 'Type to filter…' })
                }
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-content-tertiary"
                aria-label={
                  searchPlaceholder ??
                  t('searchable_select.search_placeholder', { defaultValue: 'Type to filter…' })
                }
                aria-controls={listboxId}
              />
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery('');
                    searchRef.current?.focus();
                  }}
                  aria-label={t('searchable_select.clear', { defaultValue: 'Clear the filter' })}
                  className="shrink-0 text-content-tertiary hover:text-content-primary"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          )}

          <ul id={listboxId} ref={listRef} role="listbox" className="max-h-72 overflow-y-auto py-1">
            {pickable === 0 ? (
              <li className="px-3 py-4 text-center text-xs text-content-tertiary">
                {t('searchable_select.no_match', {
                  defaultValue: 'Nothing matches "{{query}}"',
                  query: query.trim(),
                })}
              </li>
            ) : (
              rows.map((row, i) => {
                if (row.kind === 'group') {
                  return (
                    <li
                      key={`g-${row.label}-${i}`}
                      role="presentation"
                      className="sticky top-0 z-[1] bg-surface-elevated px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-content-tertiary"
                    >
                      {row.label}
                    </li>
                  );
                }
                const isHi = row.idx === highlight;
                if (row.kind === 'empty') {
                  const isSel = value === '';
                  return (
                    <li
                      key="__empty__"
                      role="option"
                      aria-selected={isSel}
                      data-idx={row.idx}
                      onMouseEnter={() => setHighlight(row.idx)}
                      onClick={() => pick(row.idx)}
                      className={clsx(
                        'flex cursor-pointer items-center gap-2 px-3 py-2 text-sm',
                        isHi && 'bg-oe-blue/10',
                      )}
                    >
                      <span className="flex-1 italic text-content-secondary">
                        {emptyLabel ?? t('searchable_select.none', { defaultValue: 'None' })}
                      </span>
                      {isSel && <Check size={14} className="shrink-0 text-oe-blue" />}
                    </li>
                  );
                }
                const o = row.option;
                const isSel = o.value === value;
                return (
                  <li
                    key={o.value}
                    role="option"
                    aria-selected={isSel}
                    aria-disabled={o.disabled || undefined}
                    data-idx={row.idx}
                    onMouseEnter={() => setHighlight(row.idx)}
                    onClick={() => pick(row.idx)}
                    className={clsx(
                      'flex items-center gap-2 px-3 py-1.5 text-sm',
                      o.disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
                      isHi && !o.disabled && 'bg-oe-blue/10',
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate text-content-primary">
                      {highlightMatch(o.label, query)}
                      {o.meta && (
                        <span className="ml-1.5 text-xs text-content-tertiary">
                          {highlightMatch(o.meta, query)}
                        </span>
                      )}
                    </span>
                    {o.hint && (
                      <span className="shrink-0 font-mono text-[10px] text-content-tertiary">
                        {highlightMatch(o.hint, query)}
                      </span>
                    )}
                    {isSel && <Check size={14} className="shrink-0 text-oe-blue" />}
                  </li>
                );
              })
            )}
          </ul>

          {showSearch && pickable > 0 && (
            <div className="border-t border-border-light/60 bg-surface-secondary px-3 py-1.5 text-[10px] text-content-tertiary">
              {t('searchable_select.footer', {
                defaultValue: '{{shown}} of {{total}} · ↑↓ to move · ↵ to pick',
                shown: filtered.length,
                total: options.length,
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
