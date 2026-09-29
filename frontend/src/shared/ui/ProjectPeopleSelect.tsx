// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ProjectPeopleSelect - pick a person from the ones on THIS project.
 *
 * The people pickers in this tree offer every active account in the
 * deployment, which on a real install is a list of hundreds where the four
 * names that belong to this job are somewhere in the middle. This one reads
 * the project roster first.
 *
 * Two properties are load-bearing and easy to get wrong:
 *
 * 1. The value handed back is the roster line's ``user_id``, never its ``id``.
 *    Every assignee column in this codebase (``punchlist.assigned_to``,
 *    ``rfi.assigned_to``, ``rfi.ball_in_court``) stores a user id in a bare
 *    GUID/String column with no foreign key, so writing a roster-line id there
 *    fails silently: nothing errors, and every reader that resolves the column
 *    to a person finds nobody.
 *
 * 2. Roster people with no account are listed, disabled, and labelled - not
 *    hidden. Most of a site has no login, and a site manager who cannot find
 *    the foreman in the list needs to see why he is not pickable, or they will
 *    go and create a duplicate account for him.
 *
 * The fallback to the whole workspace keys on "no selectable roster line",
 * NOT on "empty roster". A project whose roster is full of subcontractors with
 * no accounts has plenty of rows and nobody assignable, and keying on row
 * count would leave the picker empty on exactly that project.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useTranslation } from 'react-i18next';
import { X, User } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { listRoster } from '@/features/teams/api';

interface UserResult {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

/** One row of the dropdown, already resolved to what it offers. */
interface PersonOption {
  /** The user id to store. Empty for somebody who holds no account. */
  userId: string;
  name: string;
  /** Firm, trade or email - whatever identifies this person on site. */
  detail: string;
  assignable: boolean;
  /** True when the row came from the project roster rather than the fallback. */
  onProject: boolean;
}

export interface ProjectPeopleSelectProps {
  /** The stored user id. */
  value: string;
  /** Name to show for `value` when the caller already knows it. */
  displayValue?: string;
  onChange: (userId: string, displayName: string) => void;
  /** Project whose roster is offered. Falls back to the workspace when empty. */
  projectId: string;
  placeholder?: string;
  className?: string;
  id?: string;
}

export function ProjectPeopleSelect({
  value,
  displayValue,
  onChange,
  projectId,
  placeholder,
  className,
  id,
}: ProjectPeopleSelectProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState(displayValue || '');
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: roster = [] } = useQuery({
    queryKey: ['roster', projectId],
    // Unwrapped here rather than downstream: the picker needs the rows, and
    // the ['roster'] cache entry is shared with the roster tab, so both
    // readers have to agree on what sits under the key.
    queryFn: () => listRoster(projectId).then((page) => page.items),
    enabled: !!projectId,
    staleTime: 60_000,
  });

  const canListUsers = useHasPermission('users.list');
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserResult[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: canListUsers,
  });

  const { options, fromRoster } = useMemo(() => {
    const active = roster.filter((m) => m.is_active);
    const assignable = active.filter((m) => m.user_id && !m.user_is_inactive);

    if (assignable.length === 0) {
      return {
        fromRoster: false,
        options: users.map<PersonOption>((u) => ({
          userId: u.id,
          name: u.full_name || u.email,
          detail: u.email,
          assignable: true,
          onProject: false,
        })),
      };
    }

    const rosterOptions = active.map<PersonOption>((m) => ({
      userId: m.user_id && !m.user_is_inactive ? m.user_id : '',
      name: m.display_name,
      detail: [m.company_name, m.site_role_label || m.trade_label].filter(Boolean).join(' · '),
      assignable: !!m.user_id && !m.user_is_inactive,
      onProject: true,
    }));

    // Accounts that hold project access but nobody put on the roster stay
    // offerable: the roster is young on most projects, and a picker that
    // forgets somebody already using the project reads as a bug.
    const known = new Set(rosterOptions.map((o) => o.userId).filter(Boolean));
    const rest = users
      .filter((u) => !known.has(u.id))
      .map<PersonOption>((u) => ({
        userId: u.id,
        name: u.full_name || u.email,
        detail: u.email,
        assignable: true,
        onProject: false,
      }));

    return { fromRoster: true, options: [...rosterOptions, ...rest] };
  }, [roster, users]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (displayValue !== undefined) setQuery(displayValue);
  }, [displayValue]);

  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? options.filter((o) => `${o.name} ${o.detail}`.toLowerCase().includes(needle))
    : options;

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setQuery(e.target.value);
      if (value) onChange('', '');
      setIsOpen(true);
    },
    [value, onChange],
  );

  const handleSelect = useCallback(
    (option: PersonOption) => {
      if (!option.assignable) return;
      setQuery(option.name);
      onChange(option.userId, option.name);
      setIsOpen(false);
    },
    [onChange],
  );

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <div ref={containerRef} className={`relative ${className || ''}`}>
      <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
        <User size={14} />
      </div>
      <input
        id={id}
        type="text"
        value={query}
        onChange={handleInputChange}
        onFocus={() => setIsOpen(true)}
        placeholder={
          placeholder || t('people.search_placeholder', 'Search the people on this project')
        }
        className={inputCls}
      />
      {(query || value) && (
        <button
          type="button"
          onClick={() => {
            setQuery('');
            onChange('', '');
            setIsOpen(false);
          }}
          aria-label={t('common.clear', { defaultValue: 'Clear' })}
          className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary hover:text-content-primary"
        >
          <X size={14} />
        </button>
      )}

      {isOpen && (
        <div className="absolute left-0 top-full z-50 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-md">
          <p className="border-b border-border-light px-3 py-1.5 text-2xs text-content-tertiary">
            {fromRoster
              ? t('people.group_on_project', 'People on this project')
              : t('people.group_workspace', 'Everyone in this workspace')}
          </p>
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-content-tertiary">
              {t('people.none_match', 'Nobody matches that search')}
            </p>
          ) : (
            filtered.map((option, i) => (
              <button
                key={option.userId || `${option.name}-${i}`}
                type="button"
                disabled={!option.assignable}
                onClick={() => handleSelect(option)}
                title={
                  option.assignable
                    ? undefined
                    : t(
                        'people.no_login_hint',
                        'On the roster, but with no account. Only people who can sign in can be assigned work.',
                      )
                }
                className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors ${
                  option.assignable
                    ? 'hover:bg-surface-secondary'
                    : 'cursor-not-allowed opacity-60'
                }`}
              >
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue text-2xs font-bold text-white">
                  {option.name?.[0]?.toUpperCase() || '?'}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-content-primary">{option.name}</div>
                  <div className="truncate text-xs text-content-tertiary">{option.detail}</div>
                </div>
                {!option.assignable ? (
                  <span className="shrink-0 text-2xs text-content-quaternary">
                    {t('people.no_login', 'No login')}
                  </span>
                ) : !option.onProject && fromRoster ? (
                  <span className="shrink-0 text-2xs text-content-quaternary">
                    {t('people.not_on_roster', 'Not on the roster')}
                  </span>
                ) : null}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default ProjectPeopleSelect;
