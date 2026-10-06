// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Choosing the record a link field points at.
 *
 * A link is stored as an id, and an id is the one thing a person must never be
 * asked to type. So the field is a search box over the target's records (a
 * contract, a contact, a schedule activity...) that shows each by its name,
 * and the list view shows the name too, fetched in one batch per target.
 *
 * Both lookups go through the module builder's own endpoints, which check
 * the project and the target module's read permission. A stored id the reader
 * may not see comes back without a label, and is shown as "not visible to
 * you" rather than as a raw id or as an empty cell that looks unset.
 */
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueries, useQuery } from '@tanstack/react-query';
import { ChevronDown, Loader2, Search, X } from 'lucide-react';
import clsx from 'clsx';

import { lookupLabels, lookupRecords, type LinkTarget, type LookupItem } from './api';

/**
 * A refusal, as opposed to a failure.
 *
 * Picking a team member needs the right to list users, which an editor may
 * not have. That is an answer, "you cannot choose from this", so it is shown
 * as one and never retried; any other error is a failure worth retrying.
 */
export function isForbidden(error: unknown): boolean {
  // Read off the status rather than `instanceof ApiError`, so an error from
  // any layer that carries one counts.
  return typeof error === 'object' && error !== null && (error as { status?: unknown }).status === 403;
}

const retryUnlessForbidden = (count: number, error: unknown) => !isForbidden(error) && count < 2;

/**
 * Labels for a set of stored link ids, one request per target and id set.
 *
 * `labels` is empty while loading; `loaded` says whether a missing id is
 * missing because it is still on its way or because the reader may not see it.
 */
export function useLinkLabels(target: LinkTarget | null | undefined, ids: readonly string[]) {
  const unique = useMemo(() => [...new Set(ids.filter(Boolean))].sort(), [ids]);
  const query = useQuery({
    queryKey: ['module-builder', 'link-labels', target ?? '', unique],
    queryFn: () => lookupLabels(target as LinkTarget, unique),
    enabled: Boolean(target) && unique.length > 0,
    staleTime: 5 * 60_000,
    retry: retryUnlessForbidden,
  });
  // A refused labels request is the same answer as an empty one: none of
  // these are visible to this reader.
  const forbidden = isForbidden(query.error);
  return {
    labels: query.data?.labels ?? {},
    loaded: query.isSuccess || forbidden || unique.length === 0,
    failed: query.isError && !forbidden,
  };
}

/**
 * Labels for every link column of a list at once: one request per target,
 * however many columns and rows point at it.
 */
export function useLinkLabelsByTarget(requests: ReadonlyArray<{ target: LinkTarget; ids: readonly string[] }>) {
  const byTarget = useMemo(() => {
    const merged = new Map<LinkTarget, Set<string>>();
    for (const { target, ids } of requests) {
      const set = merged.get(target) ?? new Set<string>();
      for (const id of ids) if (id) set.add(id);
      merged.set(target, set);
    }
    return [...merged.entries()]
      .map(([target, ids]) => ({ target, ids: [...ids].sort() }))
      .filter((r) => r.ids.length > 0);
  }, [requests]);

  const results = useQueries({
    queries: byTarget.map(({ target, ids }) => ({
      queryKey: ['module-builder', 'link-labels', target, ids],
      queryFn: () => lookupLabels(target, ids),
      staleTime: 5 * 60_000,
      retry: retryUnlessForbidden,
    })),
  });

  const labels: Partial<Record<LinkTarget, Record<string, string>>> = {};
  const loaded: Partial<Record<LinkTarget, boolean>> = {};
  byTarget.forEach(({ target }, i) => {
    labels[target] = results[i]?.data?.labels ?? {};
    loaded[target] = (results[i]?.isSuccess || isForbidden(results[i]?.error)) ?? false;
  });
  return { labels, loaded };
}

/** Wait this long after the last keystroke before searching. */
const SEARCH_DEBOUNCE_MS = 250;

export interface LinkPickerProps {
  id?: string;
  target: LinkTarget;
  /** The project a scoped record belongs to; the search stays inside it. */
  projectId: string | null;
  /** The stored id, or '' for none. */
  value: string;
  onChange: (id: string) => void;
  /** The field's own label, for the accessible name. */
  label: string;
  invalid?: boolean;
}

export function LinkPicker({ id, target, projectId, value, onChange, label, invalid }: LinkPickerProps) {
  const { t } = useTranslation();
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [active, setActive] = useState(0);
  // The label of a record chosen in this session, so the box shows it at once
  // instead of asking the server for a name it just handed us.
  const [chosen, setChosen] = useState<LookupItem | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const results = useQuery({
    queryKey: ['module-builder', 'lookup', target, projectId ?? '', debounced],
    queryFn: () => lookupRecords(target, { projectId, q: debounced, limit: 20 }),
    enabled: open,
    staleTime: 30_000,
    retry: retryUnlessForbidden,
  });
  const items = results.data?.items ?? [];

  const knownIds = useMemo(() => (value && chosen?.id !== value ? [value] : []), [value, chosen]);
  const { labels, loaded } = useLinkLabels(target, knownIds);
  const currentLabel =
    !value ? '' : chosen?.id === value ? chosen.label : labels[value] ?? (loaded ? null : '');

  const pick = (item: LookupItem) => {
    setChosen(item);
    onChange(item.id);
    setOpen(false);
    setQuery('');
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!open) setOpen(true);
      setActive((i) => Math.min(i + 1, Math.max(items.length - 1, 0)));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter' && open) {
      event.preventDefault();
      const item = items[active];
      if (item) pick(item);
    } else if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  const shown = open ? query : currentLabel ?? '';

  return (
    <div ref={rootRef} className="relative" data-testid={`link-picker-${target}`}>
      <div
        className={clsx(
          'flex items-center gap-2 rounded-lg border bg-surface-primary px-3 py-2 text-sm',
          'focus-within:ring-2 focus-within:ring-oe-blue/40',
          invalid ? 'border-semantic-error' : 'border-border-light',
        )}
      >
        <Search size={14} aria-hidden className="shrink-0 text-content-quaternary" />
        <input
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label={id ? undefined : label}
          autoComplete="off"
          value={shown}
          placeholder={
            currentLabel === null
              ? t('runtime_module.link_hidden', { defaultValue: 'Not visible to you' })
              : t('runtime_module.link_placeholder', { defaultValue: 'Search to choose a record' })
          }
          onFocus={() => {
            setOpen(true);
            setActive(0);
          }}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          className="min-w-0 flex-1 bg-transparent text-content-primary placeholder:text-content-quaternary focus:outline-none"
        />
        {value ? (
          <button
            type="button"
            onClick={() => {
              setChosen(null);
              onChange('');
            }}
            aria-label={t('common.clear', { defaultValue: 'Clear' })}
            className="shrink-0 rounded p-0.5 text-content-tertiary hover:text-content-primary"
            data-testid="link-picker-clear"
          >
            <X size={13} />
          </button>
        ) : (
          <ChevronDown size={14} aria-hidden className="shrink-0 text-content-quaternary" />
        )}
      </div>

      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          className="absolute z-30 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-border-light bg-surface-primary py-1 shadow-lg"
        >
          {results.isLoading ? (
            <li className="flex items-center gap-2 px-3 py-2 text-xs text-content-tertiary">
              <Loader2 size={12} className="animate-spin" />
              {t('common.loading', { defaultValue: 'Loading...' })}
            </li>
          ) : isForbidden(results.error) ? (
            <li className="px-3 py-2 text-xs text-content-tertiary" data-testid="link-picker-forbidden">
              {t('runtime_module.link_forbidden', {
                defaultValue: 'You do not have access to choose from this list.',
              })}
            </li>
          ) : results.isError ? (
            <li className="px-3 py-2 text-xs text-semantic-error">
              {t('runtime_module.link_failed', { defaultValue: 'The list could not be loaded' })}
            </li>
          ) : items.length === 0 ? (
            <li className="px-3 py-2 text-xs text-content-tertiary">
              {t('runtime_module.link_no_matches', { defaultValue: 'Nothing matches' })}
            </li>
          ) : (
            items.map((item, index) => (
              <li
                key={item.id}
                role="option"
                aria-selected={item.id === value}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(item)}
                onMouseEnter={() => setActive(index)}
                className={clsx(
                  'cursor-pointer px-3 py-1.5',
                  index === active ? 'bg-surface-secondary' : '',
                  item.id === value && 'font-medium',
                )}
              >
                <span className="block truncate text-sm text-content-primary">{item.label}</span>
                {item.sublabel && (
                  <span className="block truncate text-xs text-content-tertiary">{item.sublabel}</span>
                )}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
