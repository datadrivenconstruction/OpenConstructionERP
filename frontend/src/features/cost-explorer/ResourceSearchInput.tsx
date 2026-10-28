// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shared resource autocomplete for the Cost Explorer. Searches the catalog
// price book as the user types and calls `onPick` with the chosen resource, so
// an estimator finds a material / labour / plant line by name instead of having
// to know its raw code. Reused by the "By resources" and "Substitute" tabs.

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/shared/ui';
import { searchCatalogResources, type CatalogResource } from './api';

export interface ResourceSearchInputProps {
  onPick: (resource: CatalogResource) => void;
  region?: string | null;
  placeholder?: string;
  /** Codes already chosen - shown as "added" and not re-pickable. */
  excludeCodes?: string[];
  autoFocus?: boolean;
  /**
   * id for the underlying input so a caller can wire a visible
   * `<label htmlFor={id}>`. When set, that label becomes the field's accessible
   * name and the internal aria-label is dropped (avoids a Label-in-Name
   * mismatch); when omitted, the field falls back to its own aria-label.
   */
  id?: string;
}

export function ResourceSearchInput({
  onPick,
  region,
  placeholder,
  excludeCodes = [],
  autoFocus,
  id,
}: ResourceSearchInputProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const optionId = (i: number) => `${listboxId}-opt-${i}`;

  // Translate the resource type ("labor" / "material" / "equipment" / ...) via a
  // per-type key, falling back to the raw value so an unmapped type still reads
  // sensibly instead of leaking a bare English/data token into the dropdown.
  const typeLabel = (type: string) =>
    t(`costExplorer.resourceType.${type.trim().toLowerCase()}`, { defaultValue: type });

  // Debounce so a fast typist does not fire a request per keystroke.
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query.trim()), 220);
    return () => window.clearTimeout(id);
  }, [query]);

  const enabled = debounced.length >= 2;
  const { data, isFetching } = useQuery({
    queryKey: ['cost-explorer', 'catalog-search', debounced, region ?? ''],
    queryFn: ({ signal }) => searchCatalogResources(debounced, { region, limit: 12, signal }),
    enabled,
    staleTime: 60_000,
  });

  const excluded = useMemo(() => new Set(excludeCodes), [excludeCodes]);
  const results = useMemo(() => data ?? [], [data]);

  // Keep the highlighted row on a still-pickable (non-excluded) option, both on
  // a new search and when the exclude set changes under the cursor.
  useEffect(() => {
    setHighlight((h) => {
      if (results.length === 0) return 0;
      if (results[h] && !excluded.has(results[h].resource_code)) return h;
      const first = results.findIndex((r) => !excluded.has(r.resource_code));
      return first >= 0 ? first : 0;
    });
  }, [results, excluded]);

  // Close the dropdown on an outside click.
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  function pick(resource: CatalogResource) {
    if (excluded.has(resource.resource_code)) return;
    onPick(resource);
    setQuery('');
    setDebounced('');
    setOpen(false);
    // Keep focus on the field so a few resources can be added in a row without
    // having to click back into the input after each pick.
    inputRef.current?.focus();
  }

  // Advance the highlight to the next non-excluded option, wrapping around.
  function nextSelectable(from: number, dir: 1 | -1): number {
    if (results.length === 0) return from;
    let i = from;
    for (let step = 0; step < results.length; step++) {
      i = (i + dir + results.length) % results.length;
      const r = results[i];
      if (r && !excluded.has(r.resource_code)) return i;
    }
    return from;
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    // Escape closes the dropdown even when it only shows "No matching
    // resources", so a keyboard user is never stuck having to click away.
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (results.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => nextSelectable(h, 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => nextSelectable(h, -1));
    } else if (e.key === 'Enter') {
      const chosen = results[highlight];
      if (chosen) {
        e.preventDefault();
        pick(chosen);
      }
    }
  }

  const showDropdown = open && enabled;

  return (
    <div ref={boxRef} className="relative">
      <Input
        ref={inputRef}
        id={id}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        autoFocus={autoFocus}
        icon={<Search className="h-4 w-4" aria-hidden />}
        suffix={
          query ? (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setDebounced('');
              }}
              className="pointer-events-auto text-content-tertiary hover:text-content-secondary"
              aria-label={t('common.clear', { defaultValue: 'Clear' })}
            >
              <X className="h-4 w-4" />
            </button>
          ) : undefined
        }
        placeholder={placeholder ?? t('costExplorer.picker.placeholder', { defaultValue: 'Search materials, labour, plant by name or code' })}
        aria-label={id ? undefined : t('costExplorer.picker.aria', { defaultValue: 'Search catalog resources' })}
        role="combobox"
        aria-expanded={showDropdown}
        aria-controls={showDropdown ? listboxId : undefined}
        aria-autocomplete="list"
        aria-activedescendant={showDropdown && results[highlight] ? optionId(highlight) : undefined}
      />

      {showDropdown && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={t('costExplorer.picker.aria', { defaultValue: 'Search catalog resources' })}
          className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-md border border-border-light bg-surface-primary shadow-lg"
        >
          {isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-sm text-content-tertiary">
              {t('common.searching', { defaultValue: 'Searching...' })}
            </div>
          )}
          {!isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-sm text-content-tertiary">
              {t('costExplorer.picker.noResults', { defaultValue: 'No matching resources' })}
            </div>
          )}
          {results.map((r, i) => {
            const isExcluded = excluded.has(r.resource_code);
            return (
              <button
                key={`${r.resource_code}-${r.region ?? ''}-${i}`}
                id={optionId(i)}
                role="option"
                aria-selected={i === highlight && !isExcluded}
                type="button"
                disabled={isExcluded}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => pick(r)}
                className={[
                  'flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm',
                  isExcluded ? 'cursor-not-allowed opacity-45' : 'cursor-pointer',
                  i === highlight && !isExcluded ? 'bg-surface-tertiary' : 'hover:bg-surface-tertiary',
                ].join(' ')}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium text-content-primary">{r.name || r.resource_code}</span>
                  <span className="block truncate text-xs text-content-tertiary">
                    {r.resource_code}
                    {r.resource_type ? ` · ${typeLabel(r.resource_type)}` : ''}
                    {r.unit ? ` · ${r.unit}` : ''}
                    {r.region ? ` · ${r.region}` : ''}
                  </span>
                </span>
                {isExcluded && (
                  <span className="shrink-0 text-xs text-content-tertiary">
                    {t('costExplorer.picker.added', { defaultValue: 'added' })}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
