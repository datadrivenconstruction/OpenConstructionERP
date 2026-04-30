import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { boqApi, type CostAutocompleteItem } from './api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { AutocompleteTooltip } from './AutocompleteTooltip';

/**
 * Autocomplete suggestion for cost items.
 *
 * When the user types 2+ characters in a description cell, this component
 * fetches matching cost items and shows a dropdown. Selecting an item fills
 * the description, unit, and unit_rate fields.
 *
 * Phase F (v2.7.0) — hover tooltip on suggestions:
 *   • mouseenter on a row → 300 ms delay → render ``<AutocompleteTooltip />``
 *     anchored to the right of the row (auto-flips on overflow).
 *   • mouseleave / keydown / dropdown close → hide.
 *   • Keyboard ArrowUp/ArrowDown navigation never triggers the tooltip
 *     (the spec calls for deliberate mouse hover only).
 *   • Skipped entirely on touch devices (matchMedia ``(hover: hover)``).
 */

const TOOLTIP_HOVER_DELAY_MS = 300;

interface AutocompleteInputProps {
  /** Current value of the input field. */
  value: string;
  /** Called when the user commits a value (blur or Enter). */
  onCommit: (value: string) => void;
  /** Called when the user selects an autocomplete suggestion. */
  onSelectSuggestion: (item: CostAutocompleteItem) => void;
  /** Called when the user cancels editing (Escape). */
  onCancel: () => void;
  /** Placeholder text. */
  placeholder?: string;
}

/** Detect hover-capable pointing devices. SSR-safe. */
function isHoverCapableDevice(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  try {
    return window.matchMedia('(hover: hover)').matches;
  } catch {
    return false;
  }
}

/**
 * Map an ISO 4217 currency code (or empty/undefined) to a short symbol
 * for the tooltip. Falls back to the raw code so the user always sees
 * *something* meaningful.
 */
function currencySymbolFor(currency: string | undefined | null): string {
  if (!currency) return '';
  const code = currency.toUpperCase();
  switch (code) {
    case 'EUR':
      return '€';
    case 'USD':
    case 'CAD':
    case 'AUD':
    case 'NZD':
    case 'MXN':
    case 'BRL':
    case 'ARS':
      return '$';
    case 'GBP':
      return '£';
    case 'JPY':
    case 'CNY':
      return '¥';
    case 'INR':
      return '₹';
    case 'RUB':
      return '₽';
    case 'PLN':
      return 'zł';
    case 'CZK':
      return 'Kč';
    case 'CHF':
      return 'CHF';
    default:
      return code;
  }
}

export function AutocompleteInput({
  value,
  onCommit,
  onSelectSuggestion,
  onCancel,
  placeholder,
}: AutocompleteInputProps) {
  const [inputValue, setInputValue] = useState(value);
  const [suggestions, setSuggestions] = useState<CostAutocompleteItem[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [isLoading, setIsLoading] = useState(false);

  // Hover tooltip state (Phase F). The pair (item, rect) is set together
  // after a 300 ms delay so we never render a tooltip for a row the user
  // only flicked across.
  const [hoveredItem, setHoveredItem] = useState<CostAutocompleteItem | null>(null);
  const [hoveredRect, setHoveredRect] = useState<DOMRect | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hover detection runs once per mount so SSR stays safe.
  const hoverCapable = useMemo(() => isHoverCapableDevice(), []);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
        onCommit(inputValue);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [inputValue, onCommit]);

  // Debounced fetch — uses active region from global store for filtering
  const fetchSuggestions = useCallback(async (query: string) => {
    if (query.length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }

    setIsLoading(true);
    try {
      // Read active region at call time to always get latest
      const { useCostDatabaseStore } = await import('@/stores/useCostDatabaseStore');
      const region = useCostDatabaseStore.getState().activeRegion || undefined;
      const items = await boqApi.autocomplete(query, 8, region);
      setSuggestions(items);
      setShowDropdown(items.length > 0);
      setSelectedIndex(-1);
    } catch {
      setSuggestions([]);
      setShowDropdown(false);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleInputChange = useCallback(
    (text: string) => {
      setInputValue(text);

      // Clear any pending debounce
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }

      // Debounce the API call by 300ms
      debounceRef.current = setTimeout(() => {
        fetchSuggestions(text);
      }, 300);
    },
    [fetchSuggestions],
  );

  // Cleanup debounce + hover timer on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      if (hoverTimerRef.current) {
        clearTimeout(hoverTimerRef.current);
      }
    };
  }, []);

  /** Clear any pending hover timer + the visible tooltip. */
  const clearHover = useCallback(() => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setHoveredItem(null);
    setHoveredRect(null);
  }, []);

  const handleSelect = useCallback(
    (item: CostAutocompleteItem) => {
      clearHover();
      setShowDropdown(false);
      setInputValue(item.description);
      onSelectSuggestion(item);
    },
    [onSelectSuggestion, clearHover],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      // Any keyboard activity hides the tooltip — keyboard navigation
      // must never coexist with a hover preview (per spec).
      clearHover();

      if (e.key === 'Escape') {
        if (showDropdown) {
          setShowDropdown(false);
        } else {
          onCancel();
        }
        return;
      }

      if (e.key === 'Enter') {
        const selected = suggestions[selectedIndex];
        if (showDropdown && selectedIndex >= 0 && selected) {
          e.preventDefault();
          handleSelect(selected);
        } else {
          onCommit(inputValue);
        }
        return;
      }

      if (e.key === 'Tab') {
        const selected = suggestions[selectedIndex];
        if (showDropdown && selectedIndex >= 0 && selected) {
          // Tab on a highlighted suggestion picks it (matches the BOQ
          // editor expectation that Tab moves the focus *after* applying
          // the current selection — see issue #102 follow-up).
          e.preventDefault();
          handleSelect(selected);
          return;
        }
        setShowDropdown(false);
        onCommit(inputValue);
        return;
      }

      if (showDropdown && suggestions.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSelectedIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0));
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSelectedIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1));
        }
      }
    },
    [showDropdown, selectedIndex, suggestions, inputValue, onCommit, onCancel, handleSelect, clearHover],
  );

  const handleSuggestionMouseEnter = useCallback(
    (item: CostAutocompleteItem, idx: number, target: HTMLElement) => {
      setSelectedIndex(idx);
      if (!hoverCapable) return; // Skip on touch / no-hover devices.
      // Snapshot the rect immediately so it doesn't drift if the user
      // scrolls during the 300 ms delay.
      const rect = target.getBoundingClientRect();
      if (hoverTimerRef.current) {
        clearTimeout(hoverTimerRef.current);
      }
      hoverTimerRef.current = setTimeout(() => {
        setHoveredItem(item);
        setHoveredRect(rect);
        hoverTimerRef.current = null;
      }, TOOLTIP_HOVER_DELAY_MS);
    },
    [hoverCapable],
  );

  const handleSuggestionMouseLeave = useCallback(() => {
    clearHover();
  }, [clearHover]);

  /** Format rate for display. */
  const fmtRate = (rate: number) =>
    new Intl.NumberFormat(getIntlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
      rate,
    );

  return (
    <div ref={containerRef} className="relative">
      {/* Input field */}
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => handleInputChange(e.target.value)}
        onKeyDown={handleKeyDown}
        className="w-full bg-surface-elevated border border-oe-blue/40 rounded px-1.5 py-0.5 outline-none text-sm text-content-primary ring-2 ring-oe-blue/20"
        placeholder={placeholder}
      />

      {/* Loading indicator */}
      {isLoading && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2">
          <div className="h-3 w-3 rounded-full border-2 border-oe-blue/30 border-t-oe-blue animate-spin" />
        </div>
      )}

      {/* Dropdown */}
      {showDropdown && suggestions.length > 0 && (
        <div className="absolute left-0 top-full mt-1 z-[100] w-[480px] max-h-[320px] overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-lg animate-fade-in">
          {/* AI Search header */}
          <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-border-light bg-gradient-to-r from-violet-50 to-blue-50 dark:from-violet-950/30 dark:to-blue-950/30">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="text-violet-500 shrink-0">
              <path d="M8 1l1.5 4.5L14 7l-4.5 1.5L8 13l-1.5-4.5L2 7l4.5-1.5L8 1z" fill="currentColor" />
            </svg>
            <span className="text-[10px] font-medium text-violet-600 dark:text-violet-400">
              AI Semantic Search
            </span>
            <span className="text-[10px] text-content-tertiary ml-auto">
              {suggestions.length} matches
            </span>
          </div>
          {suggestions.map((item, idx) => (
            <button
              key={item.code}
              type="button"
              data-testid="autocomplete-suggestion"
              onMouseDown={(e) => {
                // Use mouseDown to fire before blur
                e.preventDefault();
                handleSelect(item);
              }}
              onMouseEnter={(e) => handleSuggestionMouseEnter(item, idx, e.currentTarget)}
              onMouseLeave={handleSuggestionMouseLeave}
              className={`flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors ${
                idx === selectedIndex
                  ? 'bg-oe-blue-subtle/40'
                  : 'hover:bg-surface-secondary'
              } ${idx > 0 ? 'border-t border-border-light' : ''}`}
            >
              {/* Main content */}
              <div className="min-w-0 flex-1">
                <p className="text-sm text-content-primary truncate">{item.description}</p>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span className="text-2xs text-content-tertiary font-mono">{item.code}</span>
                  {item.classification && Object.keys(item.classification).length > 0 && (
                    <span className="text-[9px] px-1 py-0 rounded bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400 font-medium">
                      {Object.values(item.classification)[0]}
                    </span>
                  )}
                </div>
              </div>

              {/* Unit */}
              <span className="shrink-0 text-xs text-content-secondary font-mono uppercase bg-surface-secondary px-1.5 py-0.5 rounded">
                {item.unit}
              </span>

              {/* Rate */}
              <span className="shrink-0 text-sm text-content-primary tabular-nums font-medium w-20 text-right">
                {fmtRate(item.rate)}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Hover tooltip (rendered into a portal). The tooltip itself has
          ``pointer-events: none`` so it never steals input from the row. */}
      {hoveredItem && hoveredRect && (
        <AutocompleteTooltip
          item={hoveredItem}
          anchorRect={hoveredRect}
          currencySymbol={currencySymbolFor(hoveredItem.currency)}
        />
      )}
    </div>
  );
}
