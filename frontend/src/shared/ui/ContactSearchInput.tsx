/**
 * ContactSearchInput — Searchable dropdown for selecting contacts from the contacts module.
 *
 * Queries GET /api/v1/contacts/search?q=X as the user types, debounced.
 * Renders a dropdown list of matching contacts with company name and type.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';

interface ContactResult {
  id: string;
  company_name: string | null;
  first_name: string | null;
  last_name: string | null;
  contact_type: string;
  primary_email: string | null;
}

interface ContactSearchResponse {
  items: ContactResult[];
  total: number;
}

export interface ContactSearchInputProps {
  value: string;
  displayValue?: string;
  onChange: (contactId: string, displayName: string) => void;
  placeholder?: string;
  className?: string;
}

function getDisplayName(c: ContactResult): string {
  const parts: string[] = [];
  if (c.company_name) parts.push(c.company_name);
  if (c.first_name || c.last_name) {
    parts.push([c.first_name, c.last_name].filter(Boolean).join(' '));
  }
  return parts.join(' - ') || c.primary_email || c.id;
}

export function ContactSearchInput({
  value,
  displayValue,
  onChange,
  placeholder,
  className,
}: ContactSearchInputProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState(displayValue || '');
  const [results, setResults] = useState<ContactResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Sync display value from prop
  useEffect(() => {
    if (displayValue !== undefined) {
      setQuery(displayValue);
    }
  }, [displayValue]);

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 1) {
      setResults([]);
      setIsOpen(false);
      return;
    }
    setIsLoading(true);
    try {
      const data = await apiGet<ContactSearchResponse>(
        `/v1/contacts/search?q=${encodeURIComponent(q)}&limit=10`,
      );
      setResults(data.items || []);
      setIsOpen(true);
    } catch {
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      setQuery(val);
      // Clear selection if user edits
      if (value) {
        onChange('', '');
      }
      // Debounced search
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => doSearch(val), 300);
    },
    [value, onChange, doSearch],
  );

  const handleSelect = useCallback(
    (contact: ContactResult) => {
      const name = getDisplayName(contact);
      setQuery(name);
      onChange(contact.id, name);
      setIsOpen(false);
    },
    [onChange],
  );

  const handleClear = useCallback(() => {
    setQuery('');
    onChange('', '');
    setResults([]);
    setIsOpen(false);
  }, [onChange]);

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <div ref={containerRef} className={`relative ${className || ''}`}>
      <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
        <Search size={14} />
      </div>
      <input
        type="text"
        value={query}
        onChange={handleInputChange}
        onFocus={() => {
          if (results.length > 0 && !value) setIsOpen(true);
        }}
        placeholder={placeholder || t('contacts.search_placeholder', { defaultValue: 'Search contacts...' })}
        className={inputCls}
      />
      {(query || value) && (
        <button
          type="button"
          onClick={handleClear}
          className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary hover:text-content-primary"
        >
          <X size={14} />
        </button>
      )}

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute left-0 top-full mt-1 z-50 w-full max-h-48 overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-md">
          {isLoading ? (
            <div className="px-3 py-2 text-xs text-content-tertiary">
              {t('common.searching', { defaultValue: 'Searching...' })}
            </div>
          ) : results.length === 0 ? (
            <div className="px-3 py-2 text-xs text-content-tertiary">
              {t('contacts.no_results', { defaultValue: 'No contacts found' })}
            </div>
          ) : (
            results.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => handleSelect(c)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-secondary transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-content-primary truncate">{getDisplayName(c)}</div>
                  {c.primary_email && (
                    <div className="text-xs text-content-tertiary truncate">{c.primary_email}</div>
                  )}
                </div>
                <span className="text-2xs text-content-tertiary capitalize shrink-0">
                  {c.contact_type}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
