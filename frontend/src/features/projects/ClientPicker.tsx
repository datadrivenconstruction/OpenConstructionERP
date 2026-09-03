// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClientPicker - a searchable combobox over the client directory.
 *
 * The value it owns is the project's `client_id`: a contact id once a client
 * is picked, '' when cleared, or a legacy free-text name on a project that
 * was saved before the picker existed (shown as-is, clearable, never silently
 * rewritten). Typing filters the `client` contacts; the last row of the list
 * always offers to add the typed text as a NEW client contact, which is then
 * selected in place - so a project can be filed under a client that has
 * never been entered without leaving the form.
 */
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Building2, X, Search, AlertTriangle, Pencil, Palette, MapPin } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import {
  clientLabel,
  contactDisplayName,
  createClientContact,
  findClient,
  findClientByName,
  formatAddress,
  isUuid,
  primaryAddress,
  useClientDirectory,
} from './clients';
import { ClientColorSwatch, type ClientColorSwatchHandle } from './ClientColorSwatch';
import { ClientMenu, useClientMenu, type ClientMenuItem } from './ClientMenu';
import { ClientEditorDialog } from './ClientEditorDialog';
import type { Contact } from '@/features/contacts/api';

const MAX_ROWS = 8;

/** Portalled surfaces that belong to this picker even though they sit
 *  outside its DOM subtree: a click there must not count as "outside". */
export const PORTALLED_OWN_SURFACES =
  '[role="menu"], [data-client-editor-dialog], [data-testid="client-color-popover"]';

export interface ClientPickerProps {
  /** id of the text input, so an external `<label htmlFor>` can bind to it. */
  id?: string;
  /** contact id | legacy free-text name | '' */
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  disabled?: boolean;
  autoFocus?: boolean;
}

const FIELD_CLS =
  'h-10 w-full rounded-lg border border-border bg-surface-primary text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent';

export function ClientPicker({
  id,
  value,
  onChange,
  placeholder,
  disabled = false,
  autoFocus = false,
}: ClientPickerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const reactId = useId();
  const inputId = id ?? `client-picker-${reactId}`;
  const listId = `${inputId}-listbox`;

  const { data: directory = [], isLoading, isError } = useClientDirectory();

  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on an outside click - the list is positioned over whatever sits
  // below the field, so it must not linger once the user moves on.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest?.(PORTALLED_OWN_SURFACES)) return;
      if (rootRef.current && !rootRef.current.contains(target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // ── Right-click / pencil: edit a client in place ──────────────────────
  const [editing, setEditing] = useState<Contact | null>(null);
  const pillMenu = useClientMenu();
  const pillSwatchRef = useRef<ClientColorSwatchHandle>(null);
  const rowMenu = useClientMenu();
  const [rowMenuContact, setRowMenuContact] = useState<Contact | null>(null);
  const rowSwatchRefs = useRef(new Map<string, ClientColorSwatchHandle>());

  const editLabel = t('projects.client_menu.edit', { defaultValue: 'Edit client...' });
  const colourLabel = t('projects.client_menu.set_colour', { defaultValue: 'Set colour...' });

  const trimmed = query.trim();
  const matches = useMemo<Contact[]>(() => {
    const needle = trimmed.toLowerCase();
    const rows = needle
      ? directory.filter((c) => {
          const hay = [
            c.company_name,
            c.first_name,
            c.last_name,
            c.primary_email,
            c.legal_name,
          ]
            .map((s) => (s ?? '').toLowerCase())
            .join(' ');
          return hay.includes(needle);
        })
      : directory;
    return [...rows]
      .sort((a, b) => contactDisplayName(a).localeCompare(contactDisplayName(b)))
      .slice(0, MAX_ROWS);
  }, [directory, trimmed]);

  // Offer "add as new" only for text that does not already name a client
  // exactly - picking the existing row is always the right answer there.
  const exact = findClientByName(trimmed, directory);
  const canAdd = trimmed.length > 0 && !exact;
  const optionCount = matches.length + (canAdd ? 1 : 0);

  useEffect(() => {
    setActive(0);
  }, [trimmed, open]);

  const select = (contact: Contact) => {
    onChange(contact.id);
    setQuery('');
    setOpen(false);
  };

  // "Add as a new client" is a two-beat flow: the first activation opens a
  // small confirm strip with an optional brand-colour pick, the second
  // creates the contact (and writes the colour when one was picked).
  const [pendingAdd, setPendingAdd] = useState<{ name: string; color: string } | null>(null);
  useEffect(() => {
    // Typing on abandons the strip. Merely closing the list (Escape, a
    // click elsewhere) keeps it, so a colour picked before the list was
    // dismissed is still there when it reopens for the same text.
    setPendingAdd(null);
  }, [trimmed]);

  // After "Clear" the search input is a different element from the pill
  // that was clicked, so focus it once it exists rather than racing the
  // re-render with a requestAnimationFrame.
  const focusWhenEmpty = useRef(false);
  useEffect(() => {
    if (value.trim() || !focusWhenEmpty.current) return;
    focusWhenEmpty.current = false;
    inputRef.current?.focus();
  }, [value]);

  const createMutation = useMutation({
    mutationFn: ({ name, color }: { name: string; color: string }) =>
      createClientContact(name, color),
    onSuccess: (contact) => {
      // Refresh every contacts list (the directory included) so the new
      // client shows up in the picker and the Contacts page alike.
      queryClient.invalidateQueries({ queryKey: ['contacts'] });
      addToast({
        type: 'success',
        title: t('projects.client_picker.created', {
          defaultValue: 'Client "{{name}}" added to Contacts',
          name: contactDisplayName(contact),
        }),
      });
      select(contact);
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('projects.client_picker.create_failed', {
          defaultValue: 'Could not add the client',
        }),
        message: error.message,
      });
    },
  });

  const addTyped = () => {
    if (!canAdd || createMutation.isPending) return;
    if (!pendingAdd || pendingAdd.name !== trimmed) {
      setPendingAdd({ name: trimmed, color: '' });
      return;
    }
    createMutation.mutate(pendingAdd);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      if (optionCount > 0) setActive((i) => (i + 1) % optionCount);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (optionCount > 0) setActive((i) => (i - 1 + optionCount) % optionCount);
      return;
    }
    if (e.key === 'Enter') {
      if (!open) return;
      e.preventDefault();
      if (active < matches.length) {
        const row = matches[active];
        if (row) select(row);
      } else if (canAdd) {
        addTyped();
      }
      return;
    }
    if (e.key === 'Escape' && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    }
  };

  const clear = () => {
    focusWhenEmpty.current = true;
    onChange('');
    setQuery('');
    setOpen(false);
  };

  // ── Selected state ─────────────────────────────────────────────────────
  if (value.trim()) {
    const legacy = !isUuid(value);
    const selectedContact = findClient(value, directory);
    const label = clientLabel(
      value,
      directory,
      isLoading
        ? t('common.loading', { defaultValue: 'Loading...' })
        : t('projects.client_picker.unknown', { defaultValue: 'Unknown client' }),
    );
    const pillItems: ClientMenuItem[] = [
      {
        key: 'edit',
        label: editLabel,
        icon: <Pencil size={13} />,
        disabled: !selectedContact,
        onSelect: () => setEditing(selectedContact ?? null),
      },
      {
        key: 'colour',
        label: colourLabel,
        icon: <Palette size={13} />,
        disabled: !selectedContact,
        onSelect: () => pillSwatchRef.current?.open(),
      },
      {
        key: 'clear',
        label: t('projects.client_menu.clear', { defaultValue: 'Clear selection' }),
        icon: <X size={13} />,
        separatorBefore: true,
        disabled,
        onSelect: clear,
      },
    ];
    const pillAddress = formatAddress(primaryAddress(selectedContact));
    return (
      <div
        ref={rootRef}
        className={`${FIELD_CLS} flex items-center gap-2 px-3`}
        data-testid="client-picker-selected"
        onContextMenu={pillMenu.openAt}
        title={pillAddress ? `${label}\n${pillAddress}` : label}
      >
        <Building2 size={14} className="shrink-0 text-oe-blue" />
        {selectedContact && (
          <ClientColorSwatch
            ref={pillSwatchRef}
            contact={selectedContact}
            clientName={label}
            size="sm"
            data-testid="client-picker-selected-swatch"
          />
        )}
        <span className="min-w-0 flex-1 truncate">
          {label}
          {pillAddress && (
            <span className="ms-2 text-xs text-content-tertiary">{pillAddress}</span>
          )}
        </span>
        {selectedContact && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setEditing(selectedContact);
            }}
            disabled={disabled}
            className="shrink-0 rounded-md p-1 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary disabled:opacity-50"
            aria-label={editLabel}
            title={editLabel}
            data-testid="client-picker-edit"
          >
            <Pencil size={13} />
          </button>
        )}
        <ClientMenu anchor={pillMenu.anchor} items={pillItems} onClose={pillMenu.close} title={label} />
        <ClientEditorDialog contact={editing} onClose={() => setEditing(null)} />
        {legacy && (
          <span
            className="shrink-0 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-amber-200/60 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/20"
            title={t('projects.client_picker.legacy_hint', {
              defaultValue:
                'This client was typed as plain text and is not linked to a contact. Clear it and pick or add a client to link it.',
            })}
          >
            {t('projects.client_picker.legacy', { defaultValue: 'not linked' })}
          </span>
        )}
        <button
          type="button"
          onClick={clear}
          disabled={disabled}
          className="shrink-0 rounded-md p-1 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary disabled:opacity-50"
          aria-label={t('projects.client_picker.clear', { defaultValue: 'Clear client' })}
          title={t('projects.client_picker.clear', { defaultValue: 'Clear client' })}
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  // ── Search state ───────────────────────────────────────────────────────
  const showList = open && !disabled;
  const rowItems: ClientMenuItem[] = [
    {
      key: 'edit',
      label: editLabel,
      icon: <Pencil size={13} />,
      onSelect: () => {
        setOpen(false);
        setEditing(rowMenuContact);
      },
    },
    {
      key: 'colour',
      label: colourLabel,
      icon: <Palette size={13} />,
      onSelect: () => {
        if (rowMenuContact) rowSwatchRefs.current.get(rowMenuContact.id)?.open();
      },
    },
    {
      key: 'select',
      label: t('projects.client_menu.select', { defaultValue: 'Select this client' }),
      icon: <Building2 size={13} />,
      separatorBefore: true,
      onSelect: () => {
        if (rowMenuContact) select(rowMenuContact);
      },
    },
  ];
  return (
    <div ref={rootRef} className="relative">
      <ClientMenu
        anchor={rowMenu.anchor}
        items={rowItems}
        onClose={rowMenu.close}
        title={rowMenuContact ? contactDisplayName(rowMenuContact) : undefined}
      />
      <ClientEditorDialog contact={editing} onClose={() => setEditing(null)} />
      <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-content-tertiary">
        <Search size={14} />
      </div>
      <input
        ref={inputRef}
        id={inputId}
        type="text"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && optionCount > 0 ? `${listId}-opt-${active}` : undefined}
        autoComplete="off"
        value={query}
        disabled={disabled}
        autoFocus={autoFocus}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        maxLength={255}
        placeholder={
          placeholder ??
          t('projects.client_picker.placeholder', {
            defaultValue: 'Search clients or type a new one',
          })
        }
        className={`${FIELD_CLS} ps-9 pe-3`}
        data-testid="client-picker-input"
      />
      {showList && (
        <div
          className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border border-border bg-surface-elevated shadow-lg"
          // Keep focus on the input while a row is clicked so the blur
          // never closes the list before the click lands.
          onMouseDown={(e) => e.preventDefault()}
        >
          <ul id={listId} role="listbox" className="max-h-64 overflow-y-auto py-1">
            {isLoading && (
              <li className="px-3 py-2 text-xs text-content-tertiary">
                {t('projects.client_picker.loading', { defaultValue: 'Loading clients...' })}
              </li>
            )}
            {isError && (
              <li className="flex items-center gap-1.5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                <AlertTriangle size={12} />
                {t('projects.client_picker.load_failed', {
                  defaultValue: 'Could not load the client directory',
                })}
              </li>
            )}
            {!isLoading && !isError && matches.length === 0 && !canAdd && (
              <li className="px-3 py-2 text-xs text-content-tertiary">
                {t('projects.client_picker.empty', {
                  defaultValue: 'No clients yet - type a name to add one',
                })}
              </li>
            )}
            {matches.map((c, i) => {
              const name = contactDisplayName(c);
              const address = formatAddress(primaryAddress(c));
              const secondary = c.primary_email || c.primary_phone || '';
              const isActive = i === active;
              return (
                <li
                  key={c.id}
                  id={`${listId}-opt-${i}`}
                  role="option"
                  aria-selected={isActive}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => select(c)}
                  onContextMenu={(e) => {
                    setRowMenuContact(c);
                    rowMenu.openAt(e);
                  }}
                  title={address || undefined}
                  className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-sm ${
                    isActive ? 'bg-oe-blue-subtle text-oe-blue-text' : 'text-content-primary'
                  }`}
                >
                  <ClientColorSwatch
                    ref={(h) => {
                      if (h) rowSwatchRefs.current.set(c.id, h);
                      else rowSwatchRefs.current.delete(c.id);
                    }}
                    contact={c}
                    clientName={name}
                    size="xs"
                  />
                  <span className="min-w-0 flex-1 truncate">
                    {name}
                    {address && (
                      <span className="ms-1.5 inline-flex items-center gap-0.5 text-[11px] text-content-tertiary">
                        <MapPin size={10} />
                        {address}
                      </span>
                    )}
                  </span>
                  {secondary && (
                    <span className="shrink-0 truncate text-xs text-content-tertiary">
                      {secondary}
                    </span>
                  )}
                </li>
              );
            })}
            {canAdd && (
              <li
                id={`${listId}-opt-${matches.length}`}
                role="option"
                aria-selected={active === matches.length}
                onMouseEnter={() => setActive(matches.length)}
                onClick={addTyped}
                aria-disabled={createMutation.isPending}
                className={`flex cursor-pointer items-center gap-2 border-t border-border-light px-3 py-2 text-sm font-medium ${
                  active === matches.length
                    ? 'bg-oe-blue-subtle text-oe-blue-text'
                    : 'text-oe-blue'
                } ${createMutation.isPending ? 'opacity-60' : ''}`}
                data-testid="client-picker-add"
              >
                <span className="min-w-0 flex-1 truncate">
                  {createMutation.isPending
                    ? t('projects.client_picker.adding', { defaultValue: 'Adding...' })
                    : pendingAdd
                      ? t('projects.client_picker.add_confirm', {
                          defaultValue: "Add '{{name}}' - press Enter or click again",
                          name: trimmed,
                        })
                      : t('projects.client_picker.add', {
                          defaultValue: "＋ Add '{{name}}' as a new client",
                          name: trimmed,
                        })}
                </span>
              </li>
            )}
          </ul>
          {pendingAdd && canAdd && !createMutation.isPending && (
            <div
              className="flex items-center gap-2 border-t border-border-light bg-surface-secondary/60 px-3 py-2 text-xs text-content-secondary"
              data-testid="client-picker-add-color"
            >
              <ClientColorSwatch
                value={pendingAdd.color}
                onChange={(hex) => setPendingAdd((p) => (p ? { ...p, color: hex } : p))}
                clientName={pendingAdd.name}
                size="sm"
                data-testid="client-picker-add-swatch"
              />
              <span className="min-w-0 flex-1 truncate">
                {pendingAdd.color
                  ? t('projects.client_picker.color_picked', {
                      defaultValue: 'Brand colour {{hex}}',
                      hex: pendingAdd.color,
                    })
                  : t('projects.client_picker.color_optional', {
                      defaultValue: 'Brand colour (optional) - click the swatch',
                    })}
              </span>
              <button
                type="button"
                onClick={addTyped}
                className="shrink-0 rounded-md bg-oe-blue px-2 py-1 text-xs font-medium text-white hover:opacity-90"
                data-testid="client-picker-add-confirm"
              >
                {t('projects.client_picker.add_short', { defaultValue: 'Add client' })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
