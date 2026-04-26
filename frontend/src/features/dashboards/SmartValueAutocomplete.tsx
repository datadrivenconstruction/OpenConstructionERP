/**
 * Smart Value Autocomplete (T03).
 *
 * A debounced text input that pulls distinct values from a snapshot
 * column on every keystroke. Backend filters server-side via DuckDB
 * + rapidfuzz, so the dropdown is fast even for snapshots with 100k+
 * rows. Empty input returns the top-N values by frequency.
 *
 * Keyboard:
 *   ↑ / ↓   move highlight
 *   Enter   accept the highlighted suggestion
 *   Esc     close the dropdown
 *
 * The list is small (≤20 by default) so we render it as a plain
 * scrollable column — virtualisation overhead doesn't pay off below
 * a few hundred items. If `limit` exceeds 100, we still render the
 * plain list — the backend caps at 100 anyway.
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Search, ChevronDown, Loader2, X } from 'lucide-react';

import { getSmartValues, type SmartValue } from './api';

export interface SmartValueAutocompleteProps {
  snapshotId: string;
  column: string;
  value?: string;
  placeholder?: string;
  /** Called when the user picks a value (Enter, click). */
  onChange?: (value: string) => void;
  /** Called when the user clears the input. */
  onClear?: () => void;
  /** Debounce delay in milliseconds (default 250). */
  debounceMs?: number;
  /** Maximum suggestions to fetch (default 20, max 100). */
  limit?: number;
  className?: string;
  /** Disable the entire control (e.g. while parent is loading). */
  disabled?: boolean;
}

/**
 * For tests: this internal hook is exported so unit tests can verify
 * the debounce timing without spinning up the network layer.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);
  return debounced;
}

export function SmartValueAutocomplete({
  snapshotId,
  column,
  value: externalValue,
  placeholder,
  onChange,
  onClear,
  debounceMs = 250,
  limit = 20,
  className,
  disabled,
}: SmartValueAutocompleteProps) {
  const { t } = useTranslation();
  const listboxId = useId();

  const [internalValue, setInternalValue] = useState(externalValue ?? '');
  const [isOpen, setIsOpen] = useState(false);
  const [highlight, setHighlight] = useState<number>(-1);
  const [items, setItems] = useState<SmartValue[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Keep external value in sync — controlled-mode parent can reset us.
  useEffect(() => {
    if (externalValue !== undefined && externalValue !== internalValue) {
      setInternalValue(externalValue);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalValue]);

  const debouncedQuery = useDebouncedValue(internalValue, debounceMs);

  // Fetch matches whenever the debounced query changes (and dropdown is open).
  useEffect(() => {
    if (!isOpen || !snapshotId || !column) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    getSmartValues(snapshotId, column, { query: debouncedQuery, limit })
      .then((resp) => {
        if (cancelled) return;
        setItems(resp.items);
        setHighlight(resp.items.length > 0 ? 0 : -1);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
        setItems([]);
        setHighlight(-1);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, isOpen, snapshotId, column, limit]);

  // Close on outside click.
  useEffect(() => {
    if (!isOpen) return;
    function onDocClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [isOpen]);

  const handleAccept = useCallback(
    (val: string) => {
      setInternalValue(val);
      setIsOpen(false);
      setHighlight(-1);
      onChange?.(val);
    },
    [onChange],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (!isOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        setIsOpen(true);
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setHighlight((h) => Math.min(items.length - 1, h + 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setHighlight((h) => Math.max(0, h - 1));
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        const picked = highlight >= 0 ? items[highlight] : undefined;
        if (picked) {
          handleAccept(picked.value);
        } else if (internalValue) {
          handleAccept(internalValue);
        }
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setIsOpen(false);
        setHighlight(-1);
        return;
      }
    },
    [highlight, items, isOpen, handleAccept, internalValue],
  );

  const handleClear = useCallback(() => {
    setInternalValue('');
    setIsOpen(false);
    setItems([]);
    setHighlight(-1);
    onClear?.();
    onChange?.('');
    inputRef.current?.focus();
  }, [onChange, onClear]);

  const showClear = useMemo(() => internalValue.length > 0, [internalValue]);
  const ph =
    placeholder ??
    t('dashboards.value_autocomplete_ph', {
      defaultValue: 'Filter values…',
    });

  return (
    <div
      ref={containerRef}
      className={`relative ${className ?? ''}`}
      data-testid="smart-value-autocomplete"
    >
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            highlight >= 0 ? `${listboxId}-option-${highlight}` : undefined
          }
          value={internalValue}
          onChange={(e) => {
            setInternalValue(e.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={ph}
          disabled={disabled}
          className="w-full rounded border border-border-light bg-surface-primary px-7 py-1.5 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
          data-testid="smart-value-input"
        />
        <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-1">
          {isLoading && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-content-tertiary" />
          )}
          {showClear && !isLoading && (
            <button
              type="button"
              onClick={handleClear}
              className="rounded p-0.5 text-content-tertiary hover:text-content-primary"
              aria-label={t('common.clear', { defaultValue: 'Clear' })}
              data-testid="smart-value-clear"
            >
              <X className="h-3 w-3" />
            </button>
          )}
          {!showClear && !isLoading && (
            <ChevronDown className="h-3.5 w-3.5 text-content-tertiary" />
          )}
        </div>
      </div>

      {isOpen && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded border border-border-light bg-surface-primary shadow-lg"
          data-testid="smart-value-listbox"
        >
          {error && (
            <li className="px-3 py-2 text-xs text-rose-300">{error}</li>
          )}
          {!error && items.length === 0 && !isLoading && (
            <li className="px-3 py-2 text-xs text-content-tertiary">
              {t('dashboards.no_values_found', {
                defaultValue: 'No matching values',
              })}
            </li>
          )}
          {items.map((item, idx) => (
            <li
              key={`${item.value}-${idx}`}
              id={`${listboxId}-option-${idx}`}
              role="option"
              aria-selected={highlight === idx}
              onMouseEnter={() => setHighlight(idx)}
              onMouseDown={(e) => {
                // mousedown beats blur — accept the value before the
                // input loses focus.
                e.preventDefault();
                handleAccept(item.value);
              }}
              className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 text-sm ${
                highlight === idx
                  ? 'bg-oe-blue/10 text-content-primary'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
              data-testid={`smart-value-option-${idx}`}
            >
              <span className="truncate">{item.value}</span>
              <span className="shrink-0 text-xs text-content-tertiary tabular-nums">
                {item.count}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
