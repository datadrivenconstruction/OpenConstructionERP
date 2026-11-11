// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Assignee field: a pick from the caller's contacts and, for those who may list
 * them, the platform's users, or (where the caller allows it) a name typed
 * freely. Used by the task form and by the schedule table's assignee cell.
 *
 * The kinds are stored differently, so the picker reports which one it is. A
 * user becomes a task's ``responsible_id`` (my-tasks and the assignment
 * notification follow it); a contact is sent by id and the server decides what
 * it links; typed text stays a plain name.
 *
 * The first 200 contacts are listed on open. Typing also asks the contacts
 * search, so a directory larger than that page still finds the one person.
 *
 * The users list needs the manager permission (``users.list``). Asking for it
 * from an editor or viewer only earns a 403, so the query is not made for
 * them, and contacts, readable by every role, are the list they pick from.
 *
 * The list is portalled to the body with fixed positioning: inside a
 * scrolling table (the schedule grid) an absolute list was clipped away.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { BookUser, User, X } from 'lucide-react';
import { apiGet, type Page } from '@/shared/lib/api';
import { normalizeRole, ROLE_RANK } from '@/shared/lib/roles';
import { matchesSearch } from '@/shared/lib/highlightMatch';
import { useAuthStore } from '@/stores/useAuthStore';
import { fetchContacts, type Contact } from './api';

export interface AssigneeValue {
  /** What the field shows: the picked name, or the text typed. */
  name: string;
  /** Set when a platform user was picked. */
  userId: string;
  /** Set when a contact was picked. */
  contactId: string;
}

interface UserRow {
  id: string;
  email: string;
  full_name: string;
  is_active?: boolean;
}

interface Option {
  kind: 'user' | 'contact';
  id: string;
  label: string;
  detail: string;
}

type ContactRow = Pick<Contact, 'id' | 'first_name' | 'last_name' | 'company_name' | 'primary_email'>;

export function contactDisplayName(c: ContactRow): string {
  const person = [c.first_name, c.last_name].filter(Boolean).join(' ');
  return person || c.company_name || c.primary_email || c.id;
}

const MAX_OPTIONS = 50;

export function AssigneePicker({
  value,
  onChange,
  inputClassName,
  placeholder,
  includeUsers = true,
  testIdPrefix = 'task-assignee',
  ariaLabel,
  disabled = false,
  noMatchesText,
  onDismiss,
}: {
  value: AssigneeValue;
  onChange: (next: AssigneeValue) => void;
  inputClassName: string;
  placeholder?: string;
  /** Offer platform users next to contacts (managers only, see above). */
  includeUsers?: boolean;
  testIdPrefix?: string;
  ariaLabel?: string;
  disabled?: boolean;
  /** Shown when nothing matches; the default speaks of keeping typed text. */
  noMatchesText?: string;
  /** Called when the list closes without a pick (outside click, Escape). */
  onDismiss?: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const [listStyle, setListStyle] = useState<CSSProperties>({});
  const role = useAuthStore((s) => s.userRole);
  const mayListUsers =
    includeUsers && ((ROLE_RANK as Readonly<Record<string, number>>)[normalizeRole(role)] ?? 0) >= ROLE_RANK.manager;

  // A picked value shows its own name in the box; list everything then, so
  // opening the field again offers the alternatives, not only the match.
  const picked = !!(value.userId || value.contactId);
  const query = picked ? '' : value.name.trim();

  // Same cache as every other contacts dropdown.
  const { data: contactsPage } = useQuery({
    queryKey: ['contacts', 'list'],
    queryFn: () => fetchContacts({ limit: 200 }),
    staleTime: 120_000,
    enabled: open,
  });
  const { data: searchPage } = useQuery({
    queryKey: ['contacts', 'search', query],
    queryFn: () => apiGet<Page<ContactRow>>(`/v1/contacts/search/?q=${encodeURIComponent(query)}&limit=20`),
    staleTime: 30_000,
    enabled: open && query.length > 0,
    retry: false,
  });
  // Same raw-row cache the approval and issue pickers share.
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserRow[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: open && mayListUsers,
    retry: false,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (boxRef.current?.contains(target) || listRef.current?.contains(target)) return;
      setOpen(false);
      onDismiss?.();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open, onDismiss]);

  // Anchor the portalled list under the field (above it near the viewport
  // bottom), following any scroll container the field sits in.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = boxRef.current?.getBoundingClientRect();
      if (!r) return;
      const below = window.innerHeight - r.bottom;
      const up = below < 248 && r.top > below;
      setListStyle({
        position: 'fixed',
        left: r.left,
        width: Math.max(r.width, 240),
        ...(up ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
      });
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open]);

  const options = useMemo<Option[]>(() => {
    const contactRows = new Map<string, ContactRow>();
    for (const c of [...(searchPage?.items ?? []), ...(contactsPage?.items ?? [])]) contactRows.set(c.id, c);
    const all: Option[] = [
      ...(mayListUsers && Array.isArray(users) ? users : []).map((u) => ({
        kind: 'user' as const,
        id: u.id,
        label: u.full_name || u.email,
        detail: u.email,
      })),
      ...[...contactRows.values()].map((c) => ({
        kind: 'contact' as const,
        id: c.id,
        label: contactDisplayName(c),
        detail: c.company_name && (c.first_name || c.last_name) ? c.company_name : c.primary_email ?? '',
      })),
    ];
    const hits = query ? all.filter((o) => matchesSearch(query, o.label, o.detail)) : all;
    return hits.slice(0, MAX_OPTIONS);
  }, [users, mayListUsers, contactsPage, searchPage, query]);

  const pick = (o: Option) => {
    onChange({
      name: o.label,
      userId: o.kind === 'user' ? o.id : '',
      contactId: o.kind === 'contact' ? o.id : '',
    });
    setOpen(false);
  };

  useEffect(() => setActive(0), [query, open]);

  const linked = value.userId ? 'user' : value.contactId ? 'contact' : null;

  return (
    <div ref={boxRef} className="relative">
      <div className="relative">
        {linked && (
          <span
            className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-oe-blue"
            title={
              linked === 'user'
                ? t('tasks.assignee_linked_user', { defaultValue: 'Linked to a user' })
                : t('tasks.assignee_linked_contact', { defaultValue: 'Linked to a contact' })
            }
          >
            {linked === 'user' ? <User size={14} /> : <BookUser size={14} />}
          </span>
        )}
        <input
          data-testid={`${testIdPrefix}-input`}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          value={value.name}
          // Typing over a pick turns it back into a plain name.
          onChange={(e) => {
            onChange({ name: e.target.value, userId: '', contactId: '' });
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          aria-label={ariaLabel}
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setOpen(false);
              onDismiss?.();
            } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault();
              setOpen(true);
              const step = e.key === 'ArrowDown' ? 1 : -1;
              setActive((i) => (options.length ? (i + step + options.length) % options.length : 0));
            } else if (e.key === 'Enter' && open && options[active]) {
              // Enter takes the highlighted match, so a typed name is never left unsaved.
              e.preventDefault();
              pick(options[active]);
            }
          }}
          className={`${inputClassName}${linked ? ' ps-9' : ''}${value.name ? ' pe-8' : ''}`}
          placeholder={placeholder}
        />
        {value.name && !disabled && (
          <button
            type="button"
            onClick={() => onChange({ name: '', userId: '', contactId: '' })}
            aria-label={t('common.clear', { defaultValue: 'Clear' })}
            className="absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary hover:text-content-primary"
          >
            <X size={14} />
          </button>
        )}
      </div>
      {open &&
        createPortal(
        <div
          ref={listRef}
          role="listbox"
          data-testid={`${testIdPrefix}-listbox`}
          style={listStyle}
          className="z-[1000] max-h-60 overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-md"
        >
          {options.length === 0 ? (
            <div className="px-3 py-2 text-xs text-content-tertiary">
              {noMatchesText ??
                t('tasks.assignee_no_matches', {
                  defaultValue: 'No matching contacts. The name you type is kept as written.',
                })}
            </div>
          ) : (
            options.map((o, i) => (
              <button
                key={`${o.kind}-${o.id}`}
                type="button"
                role="option"
                aria-selected={o.kind === 'user' ? value.userId === o.id : value.contactId === o.id}
                data-testid={`${testIdPrefix}-option-${o.kind}-${o.id}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(o)}
                onMouseEnter={() => setActive(i)}
                className={`flex w-full items-center gap-2 px-3 py-2 text-start text-sm transition-colors hover:bg-surface-secondary${
                  i === active ? ' bg-surface-secondary' : ''
                }`}
              >
                {o.kind === 'user' ? (
                  <User size={13} className="shrink-0 text-content-tertiary" />
                ) : (
                  <BookUser size={13} className="shrink-0 text-content-tertiary" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-content-primary">{o.label}</span>
                  {o.detail && <span className="block truncate text-xs text-content-tertiary">{o.detail}</span>}
                </span>
                <span className="shrink-0 text-2xs text-content-tertiary">
                  {o.kind === 'user'
                    ? t('tasks.assignee_kind_user', { defaultValue: 'User' })
                    : t('tasks.assignee_kind_contact', { defaultValue: 'Contact' })}
                </span>
              </button>
            ))
          )}
        </div>,
          document.body,
        )}
    </div>
  );
}
