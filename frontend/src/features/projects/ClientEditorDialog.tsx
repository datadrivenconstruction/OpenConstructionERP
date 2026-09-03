// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClientEditorDialog - edit a client contact end-to-end without leaving the
 * screen it was right-clicked on: name, brand colour, email, phone and an
 * ordered list of addresses (add / edit inline / remove / set primary /
 * reorder). Saving is ONE PATCH through saveClientDetails, which mirrors
 * the primary address into the contact's plain `address` column so the
 * upstream Contacts screen keeps showing it.
 *
 * Portalled to <body> (so it can sit over the project wizard or a card).
 * Escape / outside click close; Enter in the last field saves. Every key
 * and mouse event inside is stopped so an enclosing dialog / combobox
 * never reacts to it.
 */
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowDown,
  ArrowUp,
  Building2,
  MapPin,
  Plus,
  Star,
  Trash2,
  X,
} from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import type { Contact } from '@/features/contacts/api';
import {
  ADDRESS_LABEL_PICKS,
  addAddress,
  clientAddresses,
  contactColor,
  contactDisplayName,
  moveAddress,
  removeAddress,
  saveClientDetails,
  setPrimaryAddress,
  updateAddress,
  validateAddress,
  type ClientAddress,
} from './clients';
import { ClientColorSwatch } from './ClientColorSwatch';

export interface ClientEditorDialogProps {
  /** The client to edit; null renders nothing. */
  contact: Contact | null;
  onClose: () => void;
  /** Called with the saved contact after a successful PATCH. */
  onSaved?: (contact: Contact) => void;
}

const FIELD =
  'h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent';
const LABEL = 'mb-1 block text-xs font-medium text-content-secondary';

interface FormState {
  name: string;
  color: string;
  email: string;
  phone: string;
  addresses: ClientAddress[];
}

function formFrom(contact: Contact): FormState {
  return {
    name: (contact.company_name ?? '').trim() || contactDisplayName(contact),
    color: contactColor(contact),
    email: contact.primary_email ?? '',
    phone: contact.primary_phone ?? '',
    addresses: clientAddresses(contact),
  };
}

export function ClientEditorDialog({ contact, onClose, onSaved }: ClientEditorDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState<FormState | null>(null);
  const [showErrors, setShowErrors] = useState(false);

  // (Re)seed whenever a different contact is opened. Remember what had
  // focus (the pencil, the pill, a menu's trigger) so closing hands it back.
  const openerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!contact) {
      setForm(null);
      return;
    }
    const active = document.activeElement;
    if (active instanceof HTMLElement && !panelRef.current?.contains(active)) {
      openerRef.current = active;
    }
    setForm(formFrom(contact));
    setShowErrors(false);
    return () => {
      const opener = openerRef.current;
      openerRef.current = null;
      if (!opener || !opener.isConnected) return;
      // Only when nothing else has claimed focus meanwhile.
      const now = document.activeElement;
      if (now && now !== document.body && !panelRef.current?.contains(now)) return;
      opener.focus();
    };
  }, [contact]);

  // Focus the name field once the form has actually rendered - the seed
  // above runs a render before the inputs exist.
  const hasForm = form !== null;
  const contactId = contact?.id;
  useEffect(() => {
    if (!hasForm) return;
    // The input exists by now, so focus it at once; the frame callback
    // covers a host that re-renders the portal on the same tick.
    nameRef.current?.focus();
    const raf = requestAnimationFrame(() => nameRef.current?.focus());
    return () => cancelAnimationFrame(raf);
  }, [hasForm, contactId]);

  // Escape closes even when focus sits outside the panel (the pencil that
  // opened it, the page behind). Capture phase so an enclosing wizard does
  // not close as well; the colour popover and context menus own their own
  // Escape, so keys inside them are left alone.
  useEffect(() => {
    if (!contact) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const target = e.target as HTMLElement | null;
      if (target?.closest?.('[data-testid="client-color-popover"], [role="menu"]')) return;
      e.preventDefault();
      e.stopPropagation();
      onClose();
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [contact, onClose]);

  const mutation = useMutation({
    mutationFn: (f: FormState) =>
      saveClientDetails(contact!, {
        name: f.name,
        brand_color: f.color,
        primary_email: f.email,
        primary_phone: f.phone,
        addresses: f.addresses,
      }),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['contacts'] });
      addToast({
        type: 'success',
        title: t('projects.client_editor.saved', {
          defaultValue: 'Client "{{name}}" saved',
          name: contactDisplayName(saved),
        }),
      });
      onSaved?.(saved);
      onClose();
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('projects.client_editor.save_failed', { defaultValue: 'Could not save the client' }),
        message: error.message,
      });
    },
  });

  const errors = useMemo(() => {
    if (!form) return { name: '', addresses: new Map<string, { line1?: string; postcode?: string }>() };
    const addr = new Map<string, { line1?: string; postcode?: string }>();
    for (const a of form.addresses) {
      const raw = validateAddress(a);
      const e: { line1?: string; postcode?: string } = {};
      if (raw.line1) e.line1 = t('projects.client_editor.need_line1', { defaultValue: 'Address line 1 is required' });
      if (raw.postcode) e.postcode = t('projects.client_editor.bad_postcode', { defaultValue: 'Not a valid postcode' });
      if (e.line1 || e.postcode) addr.set(a.id, e);
    }
    return {
      name: form.name.trim() ? '' : t('projects.client_editor.need_name', { defaultValue: 'A client name is required' }),
      addresses: addr,
    };
  }, [form, t]);
  const valid = !errors.name && errors.addresses.size === 0;

  const save = () => {
    if (!form || mutation.isPending) return;
    if (!valid) {
      setShowErrors(true);
      return;
    }
    mutation.mutate(form);
  };

  // Outside click closes (the swatch popover and any context menu are
  // portalled siblings; clicks there must not count as outside).
  useEffect(() => {
    if (!contact) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (panelRef.current?.contains(target)) return;
      if (target.closest('[data-testid="client-color-popover"], [role="menu"]')) return;
      onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [contact, onClose]);

  if (!contact || !form) return null;

  const patch = (p: Partial<FormState>) => setForm((f) => (f ? { ...f, ...p } : f));
  const patchAddr = (id: string, p: Partial<Omit<ClientAddress, 'id' | 'is_primary'>>) =>
    setForm((f) => (f ? { ...f, addresses: updateAddress(f.addresses, id, p) } : f));

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    // Nothing here belongs to a wizard / combobox around us.
    e.stopPropagation();
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === 'Enter') {
      const el = e.target as HTMLElement;
      if (el.tagName === 'INPUT' && el.dataset.lastField === 'true') {
        e.preventDefault();
        save();
      }
    }
  };
  const stop = (e: ReactMouseEvent) => e.stopPropagation();

  const lastAddress = form.addresses[form.addresses.length - 1];
  const name = form.name.trim() || contactDisplayName(contact);

  return createPortal(
    <div
      className="fixed inset-0 z-[85] flex items-center justify-center p-4"
      onKeyDown={onKeyDown}
      onMouseDown={stop}
      onClick={stop}
      onContextMenu={stop}
      data-client-editor-dialog
    >
      {/* The backdrop is inside the event-stopping wrapper, so the
          document-level "outside click" never sees it: close from here. */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-hidden
        data-testid="client-editor-backdrop"
        onMouseDown={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="client-editor"
        className="relative flex max-h-[90vh] w-full max-w-xl flex-col rounded-xl border border-border-light bg-surface-elevated shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-border-light px-5 py-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
            <Building2 size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="truncate text-base font-semibold text-content-primary">
              {t('projects.client_editor.title', { defaultValue: 'Edit client' })}
            </h2>
            <p className="truncate text-xs text-content-tertiary">{name}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto]">
            <div>
              <label className={LABEL} htmlFor={`${titleId}-name`}>
                {t('projects.client_editor.name', { defaultValue: 'Client name' })}
              </label>
              <input
                ref={nameRef}
                id={`${titleId}-name`}
                type="text"
                value={form.name}
                onChange={(e) => patch({ name: e.target.value })}
                maxLength={255}
                autoComplete="organization"
                aria-invalid={showErrors && !!errors.name}
                data-testid="client-editor-name"
                className={`${FIELD} ${showErrors && errors.name ? 'border-red-400' : ''}`}
              />
              {showErrors && errors.name && <p className="mt-1 text-xs text-red-600">{errors.name}</p>}
            </div>
            <div>
              <span className={LABEL}>{t('projects.client_color.title', { defaultValue: 'Client colour' })}</span>
              <div className="flex h-9 items-center gap-2">
                <ClientColorSwatch
                  value={form.color}
                  onChange={(hex) => patch({ color: hex })}
                  clientName={name}
                  size="md"
                  data-testid="client-editor-swatch"
                />
                <span className="font-mono text-xs text-content-tertiary">
                  {form.color || t('projects.client_color.none', { defaultValue: 'No colour' })}
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor={`${titleId}-email`}>
                {t('contacts.email', { defaultValue: 'Email' })}
              </label>
              <input
                id={`${titleId}-email`}
                type="email"
                value={form.email}
                onChange={(e) => patch({ email: e.target.value })}
                autoComplete="email"
                data-testid="client-editor-email"
                className={FIELD}
              />
            </div>
            <div>
              <label className={LABEL} htmlFor={`${titleId}-phone`}>
                {t('contacts.phone', { defaultValue: 'Phone' })}
              </label>
              <input
                id={`${titleId}-phone`}
                type="tel"
                value={form.phone}
                onChange={(e) => patch({ phone: e.target.value })}
                autoComplete="tel"
                data-last-field={form.addresses.length === 0 ? 'true' : undefined}
                data-testid="client-editor-phone"
                className={FIELD}
              />
            </div>
          </div>

          {/* Addresses */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
                <MapPin size={14} className="text-content-tertiary" />
                {t('projects.client_editor.addresses', { defaultValue: 'Addresses' })}
                <span className="text-xs font-normal text-content-tertiary">({form.addresses.length})</span>
              </h3>
              <button
                type="button"
                onClick={() => patch({ addresses: addAddress(form.addresses) })}
                data-testid="client-editor-add-address"
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue-subtle"
              >
                <Plus size={13} />
                {t('projects.client_editor.add_address', { defaultValue: 'Add address' })}
              </button>
            </div>

            {form.addresses.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border px-3 py-3 text-center text-xs text-content-tertiary">
                {t('projects.client_editor.no_addresses', {
                  defaultValue: 'No addresses yet - add a head office, site, postal or billing address.',
                })}
              </p>
            ) : (
              <ul className="space-y-2" data-testid="client-editor-addresses">
                {form.addresses.map((a, i) => {
                  const err = showErrors ? errors.addresses.get(a.id) : undefined;
                  const isLast = a.id === lastAddress?.id;
                  return (
                    <li
                      key={a.id}
                      data-testid="client-editor-address"
                      data-primary={a.is_primary || undefined}
                      className={`rounded-lg border p-3 ${
                        a.is_primary ? 'border-oe-blue/40 bg-oe-blue-subtle/30' : 'border-border-light bg-surface-primary/40'
                      }`}
                    >
                      <div className="mb-2 flex items-center gap-1.5">
                        <input
                          type="text"
                          list={`${titleId}-labels`}
                          value={a.label}
                          onChange={(e) => patchAddr(a.id, { label: e.target.value })}
                          placeholder={t('projects.client_editor.label_placeholder', { defaultValue: 'Label (e.g. Head office)' })}
                          maxLength={60}
                          aria-label={t('projects.client_editor.label', { defaultValue: 'Address label' })}
                          data-testid="client-editor-address-label"
                          className={`${FIELD} h-8 max-w-[220px] text-xs`}
                        />
                        <div className="hidden gap-1 sm:flex">
                          {ADDRESS_LABEL_PICKS.map((pick) => (
                            <button
                              key={pick}
                              type="button"
                              onClick={() => patchAddr(a.id, { label: pick })}
                              className={`rounded-full border px-2 py-0.5 text-[10px] ${
                                a.label === pick
                                  ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                                  : 'border-border-light text-content-tertiary hover:text-content-primary'
                              }`}
                            >
                              {pick}
                            </button>
                          ))}
                        </div>
                        <span className="ms-auto flex shrink-0 items-center gap-0.5">
                          <button
                            type="button"
                            onClick={() => patch({ addresses: setPrimaryAddress(form.addresses, a.id) })}
                            aria-pressed={a.is_primary}
                            title={
                              a.is_primary
                                ? t('projects.client_editor.is_primary', { defaultValue: 'Primary address' })
                                : t('projects.client_editor.set_primary', { defaultValue: 'Set as primary' })
                            }
                            data-testid="client-editor-address-primary"
                            className={`rounded-md p-1 ${a.is_primary ? 'text-amber-500' : 'text-content-tertiary hover:text-amber-500'}`}
                          >
                            <Star size={14} fill={a.is_primary ? 'currentColor' : 'none'} />
                          </button>
                          <button
                            type="button"
                            disabled={i === 0}
                            onClick={() => patch({ addresses: moveAddress(form.addresses, a.id, -1) })}
                            title={t('common.move_up', { defaultValue: 'Move up' })}
                            aria-label={t('common.move_up', { defaultValue: 'Move up' })}
                            data-testid="client-editor-address-up"
                            className="rounded-md p-1 text-content-tertiary hover:text-content-primary disabled:opacity-30"
                          >
                            <ArrowUp size={14} />
                          </button>
                          <button
                            type="button"
                            disabled={i === form.addresses.length - 1}
                            onClick={() => patch({ addresses: moveAddress(form.addresses, a.id, 1) })}
                            title={t('common.move_down', { defaultValue: 'Move down' })}
                            aria-label={t('common.move_down', { defaultValue: 'Move down' })}
                            data-testid="client-editor-address-down"
                            className="rounded-md p-1 text-content-tertiary hover:text-content-primary disabled:opacity-30"
                          >
                            <ArrowDown size={14} />
                          </button>
                          <button
                            type="button"
                            onClick={() => patch({ addresses: removeAddress(form.addresses, a.id) })}
                            title={t('common.remove', { defaultValue: 'Remove' })}
                            aria-label={t('common.remove', { defaultValue: 'Remove' })}
                            data-testid="client-editor-address-remove"
                            className="rounded-md p-1 text-content-tertiary hover:text-semantic-error"
                          >
                            <Trash2 size={14} />
                          </button>
                        </span>
                      </div>
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-6">
                        <div className="sm:col-span-3">
                          <input
                            type="text"
                            value={a.line1}
                            onChange={(e) => patchAddr(a.id, { line1: e.target.value })}
                            placeholder={t('projects.client_editor.line1', { defaultValue: 'Address line 1' })}
                            aria-label={t('projects.client_editor.line1', { defaultValue: 'Address line 1' })}
                            aria-invalid={!!err?.line1}
                            autoComplete="off"
                            data-testid="client-editor-address-line1"
                            className={`${FIELD} h-8 text-xs ${err?.line1 ? 'border-red-400' : ''}`}
                          />
                          {err?.line1 && <p className="mt-0.5 text-[11px] text-red-600">{err.line1}</p>}
                        </div>
                        <div className="sm:col-span-3">
                          <input
                            type="text"
                            value={a.line2}
                            onChange={(e) => patchAddr(a.id, { line2: e.target.value })}
                            placeholder={t('projects.client_editor.line2', { defaultValue: 'Address line 2 (optional)' })}
                            aria-label={t('projects.client_editor.line2', { defaultValue: 'Address line 2' })}
                            autoComplete="off"
                            className={`${FIELD} h-8 text-xs`}
                          />
                        </div>
                        <div className="sm:col-span-2">
                          <input
                            type="text"
                            value={a.suburb}
                            onChange={(e) => patchAddr(a.id, { suburb: e.target.value })}
                            placeholder={t('projects.client_editor.suburb', { defaultValue: 'Suburb / city' })}
                            aria-label={t('projects.client_editor.suburb', { defaultValue: 'Suburb / city' })}
                            autoComplete="off"
                            data-testid="client-editor-address-suburb"
                            className={`${FIELD} h-8 text-xs`}
                          />
                        </div>
                        <div className="sm:col-span-1">
                          <input
                            type="text"
                            value={a.state}
                            onChange={(e) => patchAddr(a.id, { state: e.target.value })}
                            placeholder={t('projects.client_editor.state', { defaultValue: 'State' })}
                            aria-label={t('projects.client_editor.state', { defaultValue: 'State' })}
                            autoComplete="off"
                            className={`${FIELD} h-8 text-xs`}
                          />
                        </div>
                        <div className="sm:col-span-1">
                          <input
                            type="text"
                            inputMode="numeric"
                            value={a.postcode}
                            onChange={(e) => patchAddr(a.id, { postcode: e.target.value })}
                            placeholder={t('projects.client_editor.postcode', { defaultValue: 'Postcode' })}
                            aria-label={t('projects.client_editor.postcode', { defaultValue: 'Postcode' })}
                            aria-invalid={!!err?.postcode}
                            autoComplete="off"
                            data-testid="client-editor-address-postcode"
                            className={`${FIELD} h-8 text-xs ${err?.postcode ? 'border-red-400' : ''}`}
                          />
                          {err?.postcode && <p className="mt-0.5 text-[11px] text-red-600">{err.postcode}</p>}
                        </div>
                        <div className="sm:col-span-2">
                          <input
                            type="text"
                            value={a.country}
                            onChange={(e) => patchAddr(a.id, { country: e.target.value })}
                            placeholder={t('projects.client_editor.country', { defaultValue: 'Country' })}
                            aria-label={t('projects.client_editor.country', { defaultValue: 'Country' })}
                            autoComplete="off"
                            data-last-field={isLast ? 'true' : undefined}
                            data-testid="client-editor-address-country"
                            className={`${FIELD} h-8 text-xs`}
                          />
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
            <datalist id={`${titleId}-labels`}>
              {ADDRESS_LABEL_PICKS.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 border-t border-border-light px-5 py-3">
          <p className="text-[11px] text-content-tertiary">
            {t('projects.client_editor.enter_hint', { defaultValue: 'Enter in the last field saves · Esc closes' })}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-9 rounded-md px-3 text-sm text-content-secondary hover:bg-surface-secondary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="button"
              onClick={save}
              disabled={mutation.isPending}
              data-testid="client-editor-save"
              className="h-9 rounded-md bg-oe-blue px-4 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
            >
              {mutation.isPending
                ? t('common.saving', { defaultValue: 'Saving...' })
                : t('common.save', { defaultValue: 'Save' })}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
