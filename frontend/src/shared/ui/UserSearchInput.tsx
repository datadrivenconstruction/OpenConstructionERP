/**
 * UserSearchInput — Searchable dropdown for selecting internal users (team members).
 *
 * Queries GET /api/v1/users/?limit=50 and filters client-side as user types.
 * Used for: meeting chairperson, task assignee, inspection inspector, submittal reviewer, etc.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { X, User } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';

interface UserResult {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

export interface UserSearchInputProps {
  value: string;
  displayValue?: string;
  onChange: (userId: string, displayName: string) => void;
  placeholder?: string;
  className?: string;
}

export function UserSearchInput({
  value,
  displayValue,
  onChange,
  placeholder,
  className,
}: UserSearchInputProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState(displayValue || '');
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserResult[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
  });

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

  const filtered = query.trim()
    ? users.filter(
        (u) =>
          u.full_name.toLowerCase().includes(query.toLowerCase()) ||
          u.email.toLowerCase().includes(query.toLowerCase()),
      )
    : users;

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      setQuery(val);
      if (value) onChange('', '');
      setIsOpen(true);
    },
    [value, onChange],
  );

  const handleSelect = useCallback(
    (user: UserResult) => {
      setQuery(user.full_name);
      onChange(user.id, user.full_name);
      setIsOpen(false);
    },
    [onChange],
  );

  const handleClear = useCallback(() => {
    setQuery('');
    onChange('', '');
    setIsOpen(false);
  }, [onChange]);

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <div ref={containerRef} className={`relative ${className || ''}`}>
      <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
        <User size={14} />
      </div>
      <input
        type="text"
        value={query}
        onChange={handleInputChange}
        onFocus={() => setIsOpen(true)}
        placeholder={placeholder || t('common.search_users', { defaultValue: 'Search team members...' })}
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

      {isOpen && filtered.length > 0 && (
        <div className="absolute left-0 top-full mt-1 z-50 w-full max-h-48 overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-md">
          {filtered.map((u) => (
            <button
              key={u.id}
              type="button"
              onClick={() => handleSelect(u)}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm hover:bg-surface-secondary transition-colors"
            >
              <div className="w-6 h-6 rounded-full bg-oe-blue flex items-center justify-center text-white text-2xs font-bold shrink-0">
                {u.full_name?.[0]?.toUpperCase() || '?'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-content-primary truncate">{u.full_name}</div>
                <div className="text-xs text-content-tertiary truncate">{u.email}</div>
              </div>
              <span className="text-2xs text-content-quaternary capitalize shrink-0">{u.role}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
