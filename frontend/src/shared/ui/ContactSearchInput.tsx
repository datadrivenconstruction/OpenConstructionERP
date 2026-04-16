/**
 * ContactSearchInput — Searchable dropdown for selecting contacts from the contacts module.
 *
 * Queries GET /api/v1/contacts/search?q=X as the user types, debounced.
 * Also provides a "Select from contacts" button to browse all contacts.
 * Renders a dropdown list of matching contacts with company name and type.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, X, BookUser, Loader2 } from 'lucide-react';
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
  /** When true, show the "Select from contacts" browse button */
  showBrowse?: boolean;
  /** Filter contacts by type(s) when browsing, e.g. ['supplier', 'subcontractor'] */
  browseContactTypes?: string[];
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
  showBrowse = true,
  browseContactTypes,
}: ContactSearchInputProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState(displayValue || '');
  const [results, setResults] = useState<ContactResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Browse-all state
  const [browseOpen, setBrowseOpen] = useState(false);
  const [allContacts, setAllContacts] = useState<ContactResult[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseFilter, setBrowseFilter] = useState('');
  const browseRef = useRef<HTMLDivElement>(null);
  const browseInputRef = useRef<HTMLInputElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
      if (browseRef.current && !browseRef.current.contains(e.target as Node)) {
        setBrowseOpen(false);
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

  // Focus filter input when browse opens
  useEffect(() => {
    if (browseOpen && browseInputRef.current) {
      browseInputRef.current.focus();
    }
  }, [browseOpen]);

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
      setBrowseOpen(false);
      setBrowseFilter('');
    },
    [onChange],
  );

  const handleClear = useCallback(() => {
    setQuery('');
    onChange('', '');
    setResults([]);
    setIsOpen(false);
  }, [onChange]);

  // Load all contacts for browse mode
  const handleBrowseOpen = useCallback(async () => {
    if (browseOpen) {
      setBrowseOpen(false);
      return;
    }
    setIsOpen(false);
    setBrowseOpen(true);
    setBrowseFilter('');
    setBrowseLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', '200');
      // If browseContactTypes provided, fetch each type and merge, or use first
      if (browseContactTypes && browseContactTypes.length === 1) {
        params.set('contact_type', browseContactTypes[0] ?? '');
      }
      const qs = params.toString();
      const res = await apiGet<ContactResult[] | { items: ContactResult[] }>(
        `/v1/contacts/${qs ? `?${qs}` : ''}`,
      );
      const list = Array.isArray(res) ? res : (res as { items: ContactResult[] }).items ?? [];
      // Client-side filter if multiple types specified
      if (browseContactTypes && browseContactTypes.length > 1) {
        setAllContacts(list.filter((c) => browseContactTypes.includes(c.contact_type)));
      } else {
        setAllContacts(list);
      }
    } catch {
      setAllContacts([]);
    } finally {
      setBrowseLoading(false);
    }
  }, [browseOpen, browseContactTypes]);

  // Client-side filter for browse list
  const filteredBrowse = useMemo(() => {
    if (!browseFilter.trim()) return allContacts;
    const q = browseFilter.toLowerCase();
    return allContacts.filter((c) => {
      const name = getDisplayName(c).toLowerCase();
      const email = (c.primary_email || '').toLowerCase();
      const type = (c.contact_type || '').toLowerCase();
      return name.includes(q) || email.includes(q) || type.includes(q);
    });
  }, [allContacts, browseFilter]);

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <div className={`relative ${className || ''}`}>
      <div className="flex items-center gap-2">
        {/* Search input */}
        <div ref={containerRef} className="relative flex-1">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
            <Search size={14} />
          </div>
          <input
            type="text"
            value={query}
            onChange={handleInputChange}
            onFocus={() => {
              if (results.length > 0 && !value) setIsOpen(true);
              setBrowseOpen(false);
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

          {/* Search Dropdown */}
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

        {/* Browse button */}
        {showBrowse && (
          <div ref={browseRef} className="relative shrink-0">
            <button
              type="button"
              onClick={handleBrowseOpen}
              title={t('contacts.select_from_contacts', { defaultValue: 'Select from contacts' })}
              className={`flex h-10 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition-all ${
                browseOpen
                  ? 'border-oe-blue bg-oe-blue/5 text-oe-blue'
                  : 'border-border text-content-secondary hover:border-oe-blue/40 hover:bg-surface-secondary hover:text-content-primary'
              }`}
            >
              <BookUser size={15} />
              <span className="hidden sm:inline">
                {t('contacts.select_from_contacts', { defaultValue: 'Select from contacts' })}
              </span>
            </button>

            {/* Browse dropdown */}
            {browseOpen && (
              <div className="absolute right-0 top-full mt-1 z-50 w-80 rounded-lg border border-border-light bg-surface-elevated shadow-lg">
                {/* Filter input inside dropdown */}
                <div className="p-2 border-b border-border-light">
                  <div className="relative">
                    <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2.5 text-content-tertiary">
                      <Search size={13} />
                    </div>
                    <input
                      ref={browseInputRef}
                      type="text"
                      value={browseFilter}
                      onChange={(e) => setBrowseFilter(e.target.value)}
                      placeholder={t('contacts.filter_contacts', { defaultValue: 'Filter contacts...' })}
                      className="h-8 w-full rounded-md border border-border bg-surface-primary pl-8 pr-3 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
                    />
                  </div>
                </div>

                {/* Contact list */}
                <div className="max-h-60 overflow-y-auto">
                  {browseLoading ? (
                    <div className="flex items-center gap-2 px-3 py-4 text-xs text-content-tertiary justify-center">
                      <Loader2 size={14} className="animate-spin" />
                      {t('common.loading', { defaultValue: 'Loading...' })}
                    </div>
                  ) : filteredBrowse.length === 0 ? (
                    <div className="px-3 py-4 text-xs text-content-tertiary text-center">
                      {allContacts.length === 0
                        ? t('contacts.no_contacts', { defaultValue: 'No contacts in directory' })
                        : t('contacts.no_results', { defaultValue: 'No contacts found' })}
                    </div>
                  ) : (
                    filteredBrowse.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => handleSelect(c)}
                        className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-secondary transition-colors ${
                          value === c.id ? 'bg-oe-blue/5' : ''
                        }`}
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

                {/* Footer with count */}
                {!browseLoading && allContacts.length > 0 && (
                  <div className="px-3 py-1.5 border-t border-border-light text-2xs text-content-tertiary text-center">
                    {browseFilter
                      ? t('contacts.showing_filtered', {
                          defaultValue: '{{count}} of {{total}} contacts',
                          count: filteredBrowse.length,
                          total: allContacts.length,
                        })
                      : t('contacts.total_contacts', {
                          defaultValue: '{{count}} contacts',
                          count: allContacts.length,
                        })}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
