// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Assignee field for the task form: a name typed freely, or a pick from the
 * project's contacts and, for those who may list them, the platform's users.
 *
 * The three kinds are stored differently, so the picker reports which one it
 * is. A user becomes the task's ``responsible_id`` (my-tasks and the assignment
 * notification follow it); a contact is kept as ``metadata.assignee_contact_id``
 * with its name; typed text stays a plain name, as before.
 *
 * The users list needs the manager permission (``users.list``). Asking for it
 * from an editor or viewer only earns a 403, so the query is not made for
 * them, and contacts, readable by every role, are the list they pick from.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { BookUser, User, X } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { normalizeRole, ROLE_RANK } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';
import { fetchContacts, type Contact } from '@/features/contacts/api';

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

export function contactDisplayName(c: Pick<Contact, 'first_name' | 'last_name' | 'company_name' | 'primary_email' | 'id'>): string {
  const person = [c.first_name, c.last_name].filter(Boolean).join(' ');
  return person || c.company_name || c.primary_email || c.id;
}

const MAX_OPTIONS = 50;

export function AssigneePicker({
  value,
  onChange,
  inputClassName,
  placeholder,
}: {
  value: AssigneeValue;
  onChange: (next: AssigneeValue) => void;
  inputClassName: string;
  placeholder?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const role = useAuthStore((s) => s.userRole);
  const mayListUsers =
    ((ROLE_RANK as Readonly<Record<string, number>>)[normalizeRole(role)] ?? 0) >= ROLE_RANK.manager;

  // Same cache as the schedule table's assignee cell.
  const { data: contactsPage } = useQuery({
    queryKey: ['contacts', 'list'],
    queryFn: () => fetchContacts({ limit: 200 }),
    staleTime: 120_000,
  });
  // Same raw-row cache the approval and issue pickers share.
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserRow[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: mayListUsers,
    retry: false,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const options = useMemo<Option[]>(() => {
    const all: Option[] = [
      ...(Array.isArray(users) ? users : []).map((u) => ({
        kind: 'user' as const,
        id: u.id,
        label: u.full_name || u.email,
        detail: u.email,
      })),
      ...(contactsPage?.items ?? []).map((c) => ({
        kind: 'contact' as const,
        id: c.id,
        label: contactDisplayName(c),
        detail: c.company_name && (c.first_name || c.last_name) ? c.company_name : c.primary_email ?? '',
      })),
    ];
    // A picked value shows its own name in the box; list everything then, so
    // opening the field again offers the alternatives, not only the match.
    const picked = !!(value.userId || value.contactId);
    const q = picked ? '' : value.name.trim().toLowerCase();
    const hits = q
      ? all.filter((o) => o.label.toLowerCase().includes(q) || o.detail.toLowerCase().includes(q))
      : all;
    return hits.slice(0, MAX_OPTIONS);
  }, [users, contactsPage, value]);

  const pick = (o: Option) => {
    onChange({
      name: o.label,
      userId: o.kind === 'user' ? o.id : '',
      contactId: o.kind === 'contact' ? o.id : '',
    });
    setOpen(false);
  };

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
          data-testid="task-assignee-input"
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
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false);
          }}
          className={`${inputClassName}${linked ? ' ps-9' : ''}${value.name ? ' pe-8' : ''}`}
          placeholder={placeholder}
        />
        {value.name && (
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
      {open && (
        <div
          role="listbox"
          className="absolute start-0 top-full z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-md"
        >
          {options.length === 0 ? (
            <div className="px-3 py-2 text-xs text-content-tertiary">
              {t('tasks.assignee_no_matches', {
                defaultValue: 'No matching contacts. The name you type is kept as written.',
              })}
            </div>
          ) : (
            options.map((o) => (
              <button
                key={`${o.kind}-${o.id}`}
                type="button"
                role="option"
                aria-selected={o.kind === 'user' ? value.userId === o.id : value.contactId === o.id}
                data-testid={`task-assignee-option-${o.kind}-${o.id}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(o)}
                className="flex w-full items-center gap-2 px-3 py-2 text-start text-sm transition-colors hover:bg-surface-secondary"
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
        </div>
      )}
    </div>
  );
}
