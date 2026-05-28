// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Address autocomplete dropdown — Nominatim-backed.
 *
 * Drop-in replacement for the bare <input> the project/anchor form used
 * to render. As the user types we:
 *
 *   1. Debounce 300 ms (per Nominatim ToS — also reduces backend load)
 *   2. Skip queries shorter than 3 chars
 *   3. Check the 5-minute in-memory cache (in api.ts)
 *   4. Hit ``GET /api/v1/geo-hub/geocode/suggest`` with AbortController
 *   5. Render up to 5 results with display name + country flag + coords
 *
 * Keyboard nav: ↑/↓ move highlight, Enter selects, Esc closes, Tab keeps
 * the typed text. All strings via ``useTranslation`` (en.ts has the
 * geo_hub.* keys).
 *
 * Errors degrade gracefully: a fetch failure renders an inline
 * "Try again later" hint rather than crashing the form. Geocoder
 * disabled (operator opt-out) renders a dedicated message.
 */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, MapPin, Search, AlertTriangle } from 'lucide-react';

import { ApiError } from '@/shared/lib/api';

import { geocodeSuggest } from './api';
import type { GeocodeSuggestion } from './types';

export interface AddressAutocompleteSelection {
  display_name: string;
  lat: number;
  lon: number;
  country_code: string | null;
  bbox: [number, number, number, number] | null;
  /** Structured address parts when Nominatim returned them. */
  address_parts: Record<string, string> | null;
}

interface AddressAutocompleteProps {
  /** Current text shown in the input (controlled). */
  value: string;
  /** Called on every keystroke (also when a suggestion is picked). */
  onChange: (value: string) => void;
  /** Called when the user selects a suggestion (click or Enter). */
  onSelect?: (selection: AddressAutocompleteSelection) => void;
  /** Optional placeholder; defaults to "Start typing an address…". */
  placeholder?: string;
  /** Optional id forwarded to the <input> for label-for linkage. */
  inputId?: string;
  /** Optional className applied to the <input>. */
  className?: string;
  /** Disable autocomplete (renders just the bare input). */
  disabled?: boolean;
  /** Optional aria-label when no visible <label> is paired. */
  ariaLabel?: string;
  /** Debounce delay in ms. Defaults to 300 (Nominatim ToS guidance). */
  debounceMs?: number;
  /** Max suggestions to fetch + render. Defaults to 5. */
  maxResults?: number;
}

const COUNTRY_FLAG_OFFSET = 0x1F1A5;

/** ISO-3166-1 alpha-2 → emoji flag. Returns null for invalid input. */
function flagFor(countryCode: string | null): string | null {
  if (!countryCode || countryCode.length !== 2) return null;
  const upper = countryCode.toUpperCase();
  if (!/^[A-Z]{2}$/.test(upper)) return null;
  const a = upper.charCodeAt(0) + COUNTRY_FLAG_OFFSET;
  const b = upper.charCodeAt(1) + COUNTRY_FLAG_OFFSET;
  try {
    return String.fromCodePoint(a, b);
  } catch {
    return null;
  }
}

export function AddressAutocomplete({
  value,
  onChange,
  onSelect,
  placeholder,
  inputId,
  className,
  disabled,
  ariaLabel,
  debounceMs = 300,
  maxResults = 5,
}: AddressAutocompleteProps) {
  const { t } = useTranslation();
  const reactId = useId();
  const listboxId = `${reactId}-listbox`;
  const optionIdPrefix = `${reactId}-opt-`;

  const [suggestions, setSuggestions] = useState<GeocodeSuggestion[]>([]);
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorKind, setErrorKind] = useState<
    'none' | 'network' | 'disabled' | 'rate_limited'
  >('none');
  const [highlighted, setHighlighted] = useState<number>(-1);

  // Track the latest fetch so a stale response doesn't overwrite a
  // newer one. AbortController also lets us cancel the inflight request
  // on every keystroke.
  const abortRef = useRef<AbortController | null>(null);
  const lastQueryRef = useRef<string>('');
  const debounceTimerRef = useRef<number | null>(null);
  // ``justSelected`` suppresses the next fetch (selecting fires onChange
  // with the picked display_name; we don't want to re-suggest on top of
  // a freshly accepted value).
  const justSelectedRef = useRef<boolean>(false);

  const runFetch = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (trimmed.length < 3) {
        setSuggestions([]);
        setIsOpen(false);
        setIsLoading(false);
        setErrorKind('none');
        return;
      }
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      lastQueryRef.current = trimmed;
      setIsLoading(true);
      setErrorKind('none');
      // Open the dropdown immediately so the user sees a "Searching…"
      // row while Nominatim's 1 req/s upstream cooks (cold cache can
      // take 5–10 s). Otherwise the input looks broken.
      setIsOpen(true);
      try {
        const res = await geocodeSuggest(trimmed, {
          limit: maxResults,
          signal: ctrl.signal,
        });
        // Stale-response guard — drop if the query changed under us.
        if (lastQueryRef.current !== trimmed) return;
        if (res.geocoder_disabled) {
          setErrorKind('disabled');
          setSuggestions([]);
          setIsOpen(true);
          return;
        }
        setSuggestions(res.suggestions);
        setIsOpen(true);
        setHighlighted(res.suggestions.length > 0 ? 0 : -1);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') return;
        if (err instanceof ApiError && err.status === 429) {
          setErrorKind('rate_limited');
        } else {
          setErrorKind('network');
        }
        setSuggestions([]);
        setIsOpen(true);
      } finally {
        if (lastQueryRef.current === trimmed) {
          setIsLoading(false);
        }
      }
    },
    [maxResults],
  );

  // Debounce keystroke → fetch.
  useEffect(() => {
    if (disabled) return;
    if (justSelectedRef.current) {
      // Suppress one cycle after a select.
      justSelectedRef.current = false;
      return;
    }
    if (debounceTimerRef.current !== null) {
      window.clearTimeout(debounceTimerRef.current);
    }
    if (!value || value.trim().length < 3) {
      setSuggestions([]);
      setIsOpen(false);
      setErrorKind('none');
      return;
    }
    debounceTimerRef.current = window.setTimeout(() => {
      runFetch(value);
    }, debounceMs);
    return () => {
      if (debounceTimerRef.current !== null) {
        window.clearTimeout(debounceTimerRef.current);
      }
    };
  }, [value, debounceMs, disabled, runFetch]);

  // Tear down inflight request on unmount.
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
      if (debounceTimerRef.current !== null) {
        window.clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const select = useCallback(
    (suggestion: GeocodeSuggestion) => {
      justSelectedRef.current = true;
      const lat = Number(suggestion.lat);
      const lon = Number(suggestion.lon);
      const bbox = (() => {
        if (!suggestion.bbox || suggestion.bbox.length !== 4) return null;
        const parsed = suggestion.bbox.map((v) => Number(v));
        if (parsed.some((v) => !Number.isFinite(v))) return null;
        return parsed as [number, number, number, number];
      })();
      onChange(suggestion.display_name);
      onSelect?.({
        display_name: suggestion.display_name,
        lat,
        lon,
        country_code: suggestion.country_code,
        bbox,
        address_parts: suggestion.address_parts ?? null,
      });
      setIsOpen(false);
      setHighlighted(-1);
    },
    [onChange, onSelect],
  );

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!isOpen) {
      if (event.key === 'ArrowDown' && suggestions.length > 0) {
        event.preventDefault();
        setIsOpen(true);
        setHighlighted(0);
      }
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlighted((idx) => (idx + 1) % Math.max(suggestions.length, 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlighted((idx) =>
        idx <= 0 ? suggestions.length - 1 : idx - 1,
      );
    } else if (event.key === 'Home' && suggestions.length > 0) {
      // WAI-ARIA combobox: Home jumps to the first option. Without it,
      // long suggestion lists trap keyboard users at the bottom.
      event.preventDefault();
      setHighlighted(0);
    } else if (event.key === 'End' && suggestions.length > 0) {
      event.preventDefault();
      setHighlighted(suggestions.length - 1);
    } else if (event.key === 'Enter') {
      if (highlighted >= 0 && highlighted < suggestions.length) {
        const picked = suggestions[highlighted];
        if (picked) {
          event.preventDefault();
          select(picked);
        }
      }
    } else if (event.key === 'Escape') {
      event.preventDefault();
      setIsOpen(false);
      setHighlighted(-1);
    } else if (event.key === 'Tab') {
      // Tab keeps the typed text — close the dropdown without picking.
      setIsOpen(false);
    }
  }

  const showInlineLoader = isLoading && value.trim().length >= 3;
  const activeOptionId =
    highlighted >= 0 && highlighted < suggestions.length
      ? `${optionIdPrefix}${highlighted}`
      : undefined;

  const dropdownVisible =
    isOpen &&
    (suggestions.length > 0 ||
      errorKind !== 'none' ||
      value.trim().length >= 3);

  const renderErrorRow = () => {
    if (errorKind === 'disabled') {
      return (
        <li
          className={[
            'flex items-start gap-2 px-3 py-2 text-xs text-content-secondary',
          ].join(' ')}
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-500" />
          <span>
            {t('geo_hub.autocomplete.disabled', {
              defaultValue:
                'Geocoder is disabled in this deploy — enter coordinates manually below.',
            })}
          </span>
        </li>
      );
    }
    if (errorKind === 'network') {
      return (
        <li
          className={[
            'flex items-start gap-2 px-3 py-2 text-xs text-content-secondary',
          ].join(' ')}
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-red-500" />
          <span>
            {t('geo_hub.autocomplete.network_error', {
              defaultValue:
                'Address lookup is temporarily unavailable. Try again in a moment.',
            })}
          </span>
        </li>
      );
    }
    if (errorKind === 'rate_limited') {
      return (
        <li
          className={[
            'flex items-start gap-2 px-3 py-2 text-xs text-content-secondary',
          ].join(' ')}
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-500" />
          <span>
            {t('geo_hub.autocomplete.rate_limited', {
              defaultValue:
                'Too many lookups right now — wait a few seconds and retry.',
            })}
          </span>
        </li>
      );
    }
    return null;
  };

  return (
    <div className="relative w-full">
      <div className="relative">
        <Search
          size={14}
          strokeWidth={2}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          aria-hidden
        />
        <input
          id={inputId ?? reactId}
          type="text"
          value={value}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          placeholder={
            placeholder ??
            t('geo_hub.autocomplete.placeholder', {
              defaultValue: 'Start typing an address…',
            })
          }
          aria-label={ariaLabel}
          aria-autocomplete="list"
          aria-expanded={dropdownVisible}
          aria-controls={dropdownVisible ? listboxId : undefined}
          aria-activedescendant={activeOptionId}
          role="combobox"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (suggestions.length > 0) setIsOpen(true);
          }}
          onBlur={() => {
            // Defer close so a click on a suggestion still fires.
            window.setTimeout(() => setIsOpen(false), 120);
          }}
          className={[
            'h-10 w-full rounded-lg border border-border bg-surface-primary',
            'px-3 pl-9 pr-9 text-sm text-content-primary',
            'placeholder:text-content-tertiary',
            'focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent',
            disabled ? 'opacity-60 cursor-not-allowed' : '',
            className ?? '',
          ].join(' ')}
          data-testid="geo-address-autocomplete-input"
        />
        {showInlineLoader && (
          <Loader2
            size={14}
            className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-content-tertiary"
            aria-hidden
          />
        )}
      </div>
      {dropdownVisible && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={t('geo_hub.autocomplete.list_aria', {
            defaultValue: 'Address suggestions',
          })}
          aria-busy={isLoading || undefined}
          className={[
            'absolute z-30 mt-1 w-full max-h-72 overflow-y-auto rounded-lg',
            'border border-border bg-surface-primary shadow-lg ring-1 ring-black/5',
          ].join(' ')}
          data-testid="geo-address-autocomplete-list"
        >
          {renderErrorRow()}
          {suggestions.length === 0 &&
            errorKind === 'none' &&
            value.trim().length >= 3 &&
            isLoading && (
              <li
                className="flex items-center gap-2 px-3 py-2 text-xs text-content-tertiary"
                data-testid="geo-address-autocomplete-loading"
              >
                <Loader2 size={13} className="animate-spin" aria-hidden />
                <span>
                  {t('geo_hub.autocomplete.searching', {
                    defaultValue: 'Searching…',
                  })}
                </span>
              </li>
            )}
          {suggestions.length === 0 &&
            errorKind === 'none' &&
            value.trim().length >= 3 &&
            !isLoading && (
              <li className="px-3 py-2 text-xs text-content-tertiary">
                {t('geo_hub.autocomplete.no_results', {
                  defaultValue:
                    'No matches — check spelling or paste coordinates below.',
                })}
              </li>
            )}
          {suggestions.map((s, idx) => {
            const isHi = idx === highlighted;
            const flag = flagFor(s.country_code);
            const optId = `${optionIdPrefix}${idx}`;
            return (
              <li
                key={`${s.display_name}-${idx}`}
                id={optId}
                role="option"
                aria-selected={isHi}
                onMouseDown={(e) => {
                  // Prevent the input's onBlur from firing before our click.
                  e.preventDefault();
                  select(s);
                }}
                onMouseEnter={() => setHighlighted(idx)}
                className={[
                  'flex cursor-pointer items-start gap-2 px-3 py-2 text-xs',
                  isHi
                    ? 'bg-oe-blue/10 text-content-primary'
                    : 'text-content-secondary hover:bg-surface-secondary',
                ].join(' ')}
                data-testid="geo-address-autocomplete-option"
              >
                <span className="mt-0.5 text-base leading-none" aria-hidden>
                  {flag ?? <MapPin size={13} strokeWidth={2} />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium text-content-primary">
                    {s.display_name}
                  </div>
                  <div className="mt-0.5 font-mono text-2xs tabular-nums text-content-tertiary">
                    {Number(s.lat).toFixed(4)}, {Number(s.lon).toFixed(4)}
                    {s.country_code ? ` · ${s.country_code.toUpperCase()}` : ''}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default AddressAutocomplete;
