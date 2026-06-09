// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CountryCombobox — searchable picker for ISO 3166-1 alpha-2 codes with
// an opt-in "Custom region (free text)" fallback for users whose
// requirement doesn't fit any single country (e.g. "DACH", "EU-wide",
// "Middle East" for a property-development house-type catalogue).
//
// Why it exists: the modules using a country dropdown were each
// hard-coding ~12 most-common entries via plain <select>. Operators in
// other regions couldn't pick their country at all. This component
// presents the full 180+ ISO list with type-ahead search (English +
// local-script names) and lets the user fall back to a freeform label
// when the strict country model is the wrong abstraction.
//
// Behaviour contract:
//   * The picker holds either a known ISO code, "", or the sentinel
//     CUSTOM_SENTINEL string ("__custom__").
//   * When the user picks "Custom region (free text)", the picker
//     surfaces a sibling <input> and the parent stores the typed text
//     via `onCustomChange`. The country `value` becomes CUSTOM_SENTINEL.
//   * On submit the parent should translate CUSTOM_SENTINEL into a
//     {country_code: null, region_label: <custom>} payload pair.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, Search, X } from 'lucide-react';
import clsx from 'clsx';

import { CountryFlag } from '@/shared/ui/CountryFlag';
import {
  COUNTRIES,
  filterCountries,
  formatCountryLabel,
  getCountry,
  sortedCountries,
  type Country,
} from '@/shared/lib/countries';

/** Sentinel value stored in `value` when the user has chosen the
 * "Custom region (free text)" option. Parents should detect this and
 * read the freeform label from `customValue`. */
export const CUSTOM_SENTINEL = '__custom__';

export interface CountryComboboxProps {
  /** ISO alpha-2 code, "" for unset, or CUSTOM_SENTINEL for custom mode. */
  value: string;
  /** Free-text region label (only used when `value === CUSTOM_SENTINEL`). */
  customValue?: string;
  /** Called with the new ISO code or "" / CUSTOM_SENTINEL. */
  onChange: (next: string) => void;
  /** Called with the new custom-region label (only when in custom mode). */
  onCustomChange?: (next: string) => void;
  /** Show an extra "Global / no country" option at the top. */
  allowEmpty?: boolean;
  /** Show the "Custom region (free text)" option at the bottom. */
  allowCustom?: boolean;
  /** Placeholder for the trigger when no value is set. Defaults to a
   *  translated "Pick a country" via the i18n key
   *  `country_combobox.placeholder`. */
  placeholder?: string;
  /** id wired up to the trigger button for <label htmlFor=...> a11y. */
  id?: string;
  /** Disable the picker (still renders, no popover). */
  disabled?: boolean;
  className?: string;
}

/** Dataset size — exported as a smoke-test constant so tree-shaking
 *  doesn't drop the country list if a consumer only renders the picker
 *  via lazy state. */
export const COUNTRY_DATASET_SIZE = COUNTRIES.length;

export function CountryCombobox({
  value,
  customValue = '',
  onChange,
  onCustomChange,
  allowEmpty = false,
  allowCustom = true,
  placeholder,
  id,
  disabled = false,
  className,
}: CountryComboboxProps) {
  const { t } = useTranslation();
  const resolvedPlaceholder =
    placeholder ??
    t('country_combobox.placeholder', { defaultValue: 'Pick a country' });
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [highlight, setHighlight] = useState(0);

  const isCustom = value === CUSTOM_SENTINEL;
  const selectedCountry = useMemo(() => (isCustom ? null : getCountry(value)), [value, isCustom]);

  const filtered = useMemo(() => filterCountries(query, 100), [query]);
  // Total option list = [empty?, ...filtered, custom?]
  const options = useMemo(() => {
    const out: Array<
      | { kind: 'empty' }
      | { kind: 'country'; country: Country }
      | { kind: 'custom' }
    > = [];
    if (allowEmpty && !query) out.push({ kind: 'empty' });
    for (const c of filtered) out.push({ kind: 'country', country: c });
    if (allowCustom && !query) out.push({ kind: 'custom' });
    return out;
  }, [filtered, allowEmpty, allowCustom, query]);

  // Reset highlight when the option list changes.
  useEffect(() => {
    setHighlight(0);
  }, [query, open]);

  // Close on outside click.
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

  // Focus the search input on open.
  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 0);
    }
  }, [open]);

  const pickOption = (idx: number) => {
    const opt = options[idx];
    if (!opt) return;
    if (opt.kind === 'empty') {
      onChange('');
    } else if (opt.kind === 'custom') {
      onChange(CUSTOM_SENTINEL);
    } else {
      onChange(opt.country.code);
    }
    setOpen(false);
    setQuery('');
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, options.length - 1));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      pickOption(highlight);
    }
  };

  // Scroll highlighted item into view.
  useEffect(() => {
    if (!open) return;
    const node = listRef.current?.querySelector<HTMLElement>(
      `[data-idx="${highlight}"]`,
    );
    node?.scrollIntoView({ block: 'nearest' });
  }, [highlight, open]);

  // Trigger label
  let triggerInner: React.ReactNode;
  if (isCustom) {
    triggerInner = (
      <span className="flex items-center gap-2 min-w-0">
        <span className="inline-flex h-4 w-6 items-center justify-center rounded-[2px] bg-oe-blue/15 text-[10px] font-semibold text-oe-blue">
          ✱
        </span>
        <span className="truncate text-content-primary">
          {customValue ||
            t('country_combobox.custom_region', { defaultValue: 'Custom region (free text)' })}
        </span>
      </span>
    );
  } else if (selectedCountry) {
    triggerInner = (
      <span className="flex items-center gap-2 min-w-0">
        <CountryFlag code={selectedCountry.code} size={18} />
        <span className="truncate text-content-primary">
          {formatCountryLabel(selectedCountry)}
        </span>
        <span className="ml-1 text-xs text-content-tertiary">{selectedCountry.code}</span>
      </span>
    );
  } else {
    triggerInner = <span className="text-content-tertiary">{resolvedPlaceholder}</span>;
  }

  return (
    <div className={clsx('relative', className)}>
      <button
        id={id}
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        onKeyDown={handleKey}
        className={clsx(
          'flex h-9 w-full items-center justify-between gap-2 rounded-lg border bg-surface-primary px-3 text-sm',
          'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
          'border-border hover:border-content-tertiary transition-colors',
          'disabled:opacity-60 disabled:pointer-events-none',
        )}
      >
        <span className="flex-1 min-w-0 text-left">{triggerInner}</span>
        <ChevronDown
          size={16}
          className={clsx(
            'shrink-0 text-content-tertiary transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div
          ref={popoverRef}
          className={clsx(
            'absolute z-[60] mt-1 w-full overflow-hidden rounded-lg border border-border bg-surface-elevated shadow-xl',
            'animate-scale-in origin-top',
          )}
        >
          <div className="flex items-center gap-2 border-b border-border-light bg-surface-secondary px-3 py-2">
            <Search size={14} className="text-content-tertiary" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKey}
              placeholder={t('country_combobox.search_placeholder', {
                defaultValue: 'Search country (English or local script)…',
              })}
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-content-tertiary"
              aria-label={t('country_combobox.search_aria', { defaultValue: 'Search countries' })}
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                aria-label="Clear search"
                className="text-content-tertiary hover:text-content-primary"
              >
                <X size={14} />
              </button>
            )}
          </div>
          <ul
            ref={listRef}
            role="listbox"
            aria-label="Countries"
            className="max-h-72 overflow-y-auto py-1"
          >
            {options.length === 0 ? (
              <li className="px-3 py-3 text-center text-xs text-content-tertiary">
                {t('country_combobox.no_match', {
                  defaultValue: 'No country matches "{{query}}". Switch to',
                  query,
                })}{' '}
                <button
                  type="button"
                  onClick={() => {
                    onChange(CUSTOM_SENTINEL);
                    onCustomChange?.(query);
                    setOpen(false);
                    setQuery('');
                  }}
                  className="text-oe-blue underline-offset-2 hover:underline"
                >
                  Custom region
                </button>
                ?
              </li>
            ) : (
              options.map((opt, idx) => {
                const isHi = idx === highlight;
                if (opt.kind === 'empty') {
                  const selected = value === '' && !isCustom;
                  return (
                    <li
                      key="__empty__"
                      role="option"
                      aria-selected={selected}
                      data-idx={idx}
                      onMouseEnter={() => setHighlight(idx)}
                      onClick={() => pickOption(idx)}
                      className={clsx(
                        'flex cursor-pointer items-center gap-2 px-3 py-2 text-sm',
                        isHi && 'bg-oe-blue/10',
                      )}
                    >
                      <span className="inline-flex h-4 w-6 items-center justify-center rounded-[2px] bg-content-tertiary/15 text-[10px] text-content-tertiary">
                        ✕
                      </span>
                      <span className="flex-1 text-content-secondary italic">
                        {t('country_combobox.global_none', {
                          defaultValue: 'Global / no country',
                        })}
                      </span>
                      {selected && <Check size={14} className="text-oe-blue" />}
                    </li>
                  );
                }
                if (opt.kind === 'custom') {
                  const selected = isCustom;
                  return (
                    <li
                      key="__custom__"
                      role="option"
                      aria-selected={selected}
                      data-idx={idx}
                      onMouseEnter={() => setHighlight(idx)}
                      onClick={() => pickOption(idx)}
                      className={clsx(
                        'flex cursor-pointer items-center gap-2 border-t border-border-light/60 px-3 py-2 text-sm',
                        isHi && 'bg-oe-blue/10',
                      )}
                    >
                      <span className="inline-flex h-4 w-6 items-center justify-center rounded-[2px] bg-oe-blue/15 text-[10px] font-semibold text-oe-blue">
                        ✱
                      </span>
                      <span className="flex-1 text-content-primary">
                        {t('country_combobox.custom_region', {
                          defaultValue: 'Custom region (free text)',
                        })}
                      </span>
                      {selected && <Check size={14} className="text-oe-blue" />}
                    </li>
                  );
                }
                const c = opt.country;
                const selected = value === c.code && !isCustom;
                return (
                  <li
                    key={c.code}
                    role="option"
                    aria-selected={selected}
                    data-idx={idx}
                    onMouseEnter={() => setHighlight(idx)}
                    onClick={() => pickOption(idx)}
                    className={clsx(
                      'flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm',
                      isHi && 'bg-oe-blue/10',
                    )}
                  >
                    <CountryFlag code={c.code} size={18} />
                    <span className="flex-1 truncate text-content-primary">{c.name}</span>
                    {c.nameLocal && c.nameLocal !== c.name && (
                      <span className="truncate text-xs text-content-tertiary">
                        {c.nameLocal}
                      </span>
                    )}
                    <span className="ml-1 font-mono text-[10px] uppercase text-content-tertiary">
                      {c.code}
                    </span>
                    {selected && <Check size={14} className="text-oe-blue" />}
                  </li>
                );
              })
            )}
          </ul>
          <div className="border-t border-border-light/60 bg-surface-secondary px-3 py-1.5 text-[10px] text-content-tertiary">
            {t('country_combobox.footer_hint', {
              defaultValue: '{{count}} countries · ↑↓ to navigate · ↵ to pick',
              count: sortedCountries().length,
            })}
          </div>
        </div>
      )}

      {isCustom && (
        <input
          type="text"
          value={customValue}
          onChange={(e) => onCustomChange?.(e.target.value)}
          placeholder="DACH, EU-wide, Middle East, …"
          maxLength={80}
          className={clsx(
            'mt-2 h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm',
            'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
          )}
          aria-label="Custom region label"
        />
      )}
    </div>
  );
}
