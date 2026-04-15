import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Search,
  Plus,
  ChevronDown,
  Mail,
  Phone,
  Building2,
  X,
  ShieldCheck,
  Clock,
  ShieldAlert,
  ShieldX,
  Upload,
  Download,
  Loader2,
  FileDown,
  Users,
  HardHat,
  Truck,
  Briefcase,
  CreditCard,
  MapPin,
  User,
  Pencil,
  Trash2,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, CountryFlag, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useCreateShortcut } from '@/shared/hooks/useCreateShortcut';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchContacts,
  createContact,
  updateContact,
  deleteContact,
  importContactsFile,
  exportContacts,
  downloadContactsTemplate,
  type Contact,
  type ContactType,
  type PrequalificationStatus,
  type CreateContactPayload,
  type ImportResult,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

const CONTACT_TYPES: ContactType[] = ['client', 'subcontractor', 'supplier', 'consultant'];

const TYPE_BADGE_VARIANT: Record<ContactType, 'blue' | 'warning' | 'success' | 'neutral'> = {
  client: 'blue',
  subcontractor: 'warning',
  supplier: 'success',
  consultant: 'neutral',
  internal: 'neutral',
};

const PREQUAL_CONFIG: Record<
  PrequalificationStatus,
  { icon: React.ElementType; cls: string; labelKey: string; defaultLabel: string }
> = {
  pending: {
    icon: Clock,
    cls: 'text-amber-500',
    labelKey: 'contacts.prequal_pending',
    defaultLabel: 'Pending',
  },
  approved: {
    icon: ShieldCheck,
    cls: 'text-green-600 dark:text-green-400',
    labelKey: 'contacts.prequal_approved',
    defaultLabel: 'Approved',
  },
  expired: {
    icon: ShieldAlert,
    cls: 'text-orange-500',
    labelKey: 'contacts.prequal_expired',
    defaultLabel: 'Expired',
  },
  rejected: {
    icon: ShieldX,
    cls: 'text-semantic-error',
    labelKey: 'contacts.prequal_rejected',
    defaultLabel: 'Rejected',
  },
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Add Contact Modal ─────────────────────────────────────────────────── */

const TYPE_CARD_CONFIG: Record<ContactType, { icon: React.ElementType; color: string }> = {
  client: { icon: Users, color: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950/30 dark:border-blue-800' },
  subcontractor: { icon: HardHat, color: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800' },
  supplier: { icon: Truck, color: 'text-green-600 bg-green-50 border-green-200 dark:text-green-400 dark:bg-green-950/30 dark:border-green-800' },
  consultant: { icon: Briefcase, color: 'text-gray-600 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700' },
  internal: { icon: Users, color: 'text-indigo-600 bg-indigo-50 border-indigo-200 dark:text-indigo-400 dark:bg-indigo-950/30 dark:border-indigo-800' },
};

function SectionHeader({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <div className="flex items-center gap-2 pt-2 pb-1">
      <Icon size={14} className="text-content-tertiary" />
      <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">{label}</span>
      <div className="flex-1 h-px bg-border-light" />
    </div>
  );
}

interface ContactFormData {
  company_name: string;
  legal_name: string;
  vat_number: string;
  first_name: string;
  last_name: string;
  contact_type: ContactType;
  email: string;
  phone: string;
  website: string;
  country: string;
  address: string;
  payment_terms: string;
  prequalification_status: PrequalificationStatus;
  notes: string;
}

const EMPTY_FORM: ContactFormData = {
  company_name: '',
  legal_name: '',
  vat_number: '',
  first_name: '',
  last_name: '',
  contact_type: 'client',
  email: '',
  phone: '',
  website: '',
  country: '',
  address: '',
  payment_terms: '30',
  prequalification_status: 'pending',
  notes: '',
};

function AddContactModal({
  onClose,
  onSubmit,
  isPending,
  initialData,
  isEdit,
}: {
  onClose: () => void;
  onSubmit: (data: ContactFormData) => void;
  isPending: boolean;
  initialData?: ContactFormData | null;
  isEdit?: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ContactFormData>(initialData || EMPTY_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const set = <K extends keyof ContactFormData>(key: K, value: ContactFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors((prev) => { const next = { ...prev }; delete next[key]; return next; });
  };

  const canSubmit = form.company_name.trim().length > 0 || form.first_name.trim().length > 0 || form.last_name.trim().length > 0;

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    const hasName = form.first_name.trim() || form.last_name.trim();
    if (!form.company_name.trim() && !hasName) {
      e.company_name = t('contacts.company_or_name_required', { defaultValue: 'Company name or contact name is required' });
    }
    if (form.country.trim() && form.country.trim().length !== 2) {
      e.country = t('contacts.country_code_invalid', { defaultValue: 'Country code must be exactly 2 letters (ISO 3166-1 alpha-2, e.g. DE, US, GB)' });
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = () => {
    if (!validate()) return;
    onSubmit(form);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[85vh] flex flex-col" role="dialog" aria-label={isEdit ? t('contacts.edit_contact', { defaultValue: 'Edit Contact' }) : t('contacts.add_contact', { defaultValue: 'Add Contact' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light sticky top-0 z-10 bg-surface-elevated rounded-t-xl">
          <h2 className="text-lg font-semibold text-content-primary">
            {isEdit
              ? t('contacts.edit_contact', { defaultValue: 'Edit Contact' })
              : t('contacts.add_contact', { defaultValue: 'Add Contact' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-5 overflow-y-auto flex-1">
          {/* ── Contact Type ── */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('contacts.field_type', { defaultValue: 'Contact Type' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {CONTACT_TYPES.map((ct) => {
                const cfg = TYPE_CARD_CONFIG[ct];
                const TypeIcon = cfg.icon;
                const selected = form.contact_type === ct;
                return (
                  <button
                    key={ct}
                    type="button"
                    onClick={() => set('contact_type', ct)}
                    className={clsx(
                      'flex flex-col items-center gap-1.5 rounded-lg border-2 px-3 py-3 text-center transition-all',
                      selected
                        ? cfg.color + ' ring-2 ring-oe-blue/30'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <TypeIcon size={20} />
                    <span className="text-xs font-medium">
                      {t(`contacts.type_${ct}`, {
                        defaultValue: ct.charAt(0).toUpperCase() + ct.slice(1),
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Company Section ── */}
          <SectionHeader icon={Building2} label={t('contacts.section_company', { defaultValue: 'Company' })} />

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('contacts.field_company', { defaultValue: 'Company Name' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.company_name}
              onChange={(e) => set('company_name', e.target.value)}
              placeholder={t('contacts.company_placeholder', {
                defaultValue: 'e.g. Acme Construction Ltd.',
              })}
              className={clsx(
                inputCls,
                errors.company_name &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {errors.company_name && (
              <p className="mt-1 text-xs text-semantic-error">
                {errors.company_name}
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_legal_name', { defaultValue: 'Legal Name' })}
              </label>
              <input
                value={form.legal_name}
                onChange={(e) => set('legal_name', e.target.value)}
                className={inputCls}
                placeholder={t('contacts.legal_name_placeholder', { defaultValue: 'Registered legal entity name' })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_vat', { defaultValue: 'VAT / Tax ID' })}
              </label>
              <input
                value={form.vat_number}
                onChange={(e) => set('vat_number', e.target.value)}
                className={inputCls}
                placeholder={t('contacts.vat_placeholder', { defaultValue: 'e.g. DE123456789' })}
              />
            </div>
          </div>

          {/* ── Person Section ── */}
          <SectionHeader icon={User} label={t('contacts.section_person', { defaultValue: 'Contact Person' })} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_first_name', { defaultValue: 'First Name' })}
              </label>
              <input
                value={form.first_name}
                onChange={(e) => set('first_name', e.target.value)}
                className={inputCls}
                placeholder={t('contacts.first_name_placeholder', { defaultValue: 'John' })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_last_name', { defaultValue: 'Last Name' })}
              </label>
              <input
                value={form.last_name}
                onChange={(e) => set('last_name', e.target.value)}
                className={inputCls}
                placeholder={t('contacts.last_name_placeholder', { defaultValue: 'Doe' })}
              />
            </div>
          </div>

          {/* ── Contact Details Section ── */}
          <SectionHeader icon={Mail} label={t('contacts.section_contact', { defaultValue: 'Contact Details' })} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_email', { defaultValue: 'Email' })}
              </label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => set('email', e.target.value)}
                className={inputCls}
                placeholder="name@company.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_phone', { defaultValue: 'Phone' })}
              </label>
              <input
                type="tel"
                value={form.phone}
                onChange={(e) => set('phone', e.target.value)}
                className={inputCls}
                placeholder="+49 170 1234567"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('contacts.field_website', { defaultValue: 'Website' })}
            </label>
            <input
              type="url"
              value={form.website}
              onChange={(e) => set('website', e.target.value)}
              className={inputCls}
              placeholder="https://www.example.com"
            />
          </div>

          {/* ── Address Section ── */}
          <SectionHeader icon={MapPin} label={t('contacts.section_address', { defaultValue: 'Address' })} />

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('contacts.field_country', { defaultValue: 'Country' })}
            </label>
            <input
              value={form.country}
              onChange={(e) => set('country', e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 2))}
              maxLength={2}
              className={clsx(inputCls, errors.country && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
              placeholder={t('contacts.country_placeholder', {
                defaultValue: 'e.g. DE, US, GB',
              })}
            />
            {errors.country && (
              <p className="mt-1 text-xs text-semantic-error">{errors.country}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('contacts.field_address', { defaultValue: 'Address' })}
            </label>
            <textarea
              value={form.address}
              onChange={(e) => set('address', e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('contacts.address_placeholder', {
                defaultValue: 'Street address, City, ZIP / Postal code',
              })}
            />
          </div>

          {/* ── Payment & Status Section ── */}
          <SectionHeader icon={CreditCard} label={t('contacts.section_payment', { defaultValue: 'Payment & Status' })} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_payment_terms', { defaultValue: 'Payment Terms' })}
              </label>
              <div className="flex items-center gap-2">
                {['30', '45', '60'].map((days) => (
                  <button
                    key={days}
                    type="button"
                    onClick={() => set('payment_terms', days)}
                    className={clsx(
                      'flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-all text-center',
                      form.payment_terms === days
                        ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue ring-1 ring-oe-blue/30'
                        : 'border-border text-content-tertiary hover:border-border-light hover:text-content-secondary',
                    )}
                  >
                    {days} {t('contacts.days', { defaultValue: 'days' })}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('contacts.field_prequal', { defaultValue: 'Prequalification' })}
              </label>
              <select
                value={form.prequalification_status}
                onChange={(e) =>
                  set('prequalification_status', e.target.value as PrequalificationStatus)
                }
                className={inputCls}
              >
                {(
                  Object.keys(PREQUAL_CONFIG) as PrequalificationStatus[]
                ).map((ps) => (
                  <option key={ps} value={ps}>
                    {t(PREQUAL_CONFIG[ps].labelKey, {
                      defaultValue: PREQUAL_CONFIG[ps].defaultLabel,
                    })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('contacts.field_notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('contacts.notes_placeholder', {
                defaultValue: 'Additional notes...',
              })}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light sticky bottom-0 z-10 bg-surface-elevated rounded-b-xl">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>
              {isEdit
                ? t('contacts.save_contact', { defaultValue: 'Save Changes' })
                : t('contacts.create_contact', { defaultValue: 'Create Contact' })}
            </span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Import Contacts Modal ─────────────────────────────────────────────── */

function ImportContactsModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: (result: ImportResult) => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }, []);

  const handleImport = async () => {
    if (!file) return;
    setIsPending(true);
    setError(null);
    try {
      const res = await importContactsFile(file);
      setResult(res);
      onSuccess(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setIsPending(false);
    }
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('contacts.import_contacts', { defaultValue: 'Import Contacts' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('contacts.import_contacts', { defaultValue: 'Import Contacts' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Drop zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            className={clsx(
              'flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer',
              dragActive
                ? 'border-oe-blue bg-oe-blue-subtle/20'
                : 'border-border hover:border-oe-blue/50',
            )}
            onClick={() => {
              const input = document.createElement('input');
              input.type = 'file';
              input.accept = '.xlsx,.csv,.xls';
              input.onchange = (e) => {
                const f = (e.target as HTMLInputElement).files?.[0];
                if (f) setFile(f);
              };
              input.click();
            }}
          >
            <Upload size={24} className="text-content-tertiary mb-2" />
            <p className="text-sm text-content-secondary text-center">
              {file
                ? file.name
                : t('contacts.drop_file', {
                    defaultValue: 'Drop Excel or CSV file here, or click to browse',
                  })}
            </p>
            <p className="text-xs text-content-quaternary mt-1">
              {t('contacts.file_types', { defaultValue: '.xlsx, .csv — max 10 MB' })}
            </p>
          </div>

          {/* Template download */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              downloadContactsTemplate();
            }}
            className="flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            <FileDown size={13} />
            {t('contacts.download_template', { defaultValue: 'Download import template' })}
          </button>

          {/* Error */}
          {error && (
            <div className="rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 p-3 text-sm text-semantic-error">
              {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3 text-sm text-content-primary space-y-1">
              <p>
                {t('contacts.import_result', {
                  defaultValue: 'Imported: {{imported}}, Skipped: {{skipped}}, Errors: {{errors}}',
                  imported: result.imported,
                  skipped: result.skipped,
                  errors: result.errors.length,
                })}
              </p>
              {result.errors.length > 0 && (
                <details className="text-xs text-content-tertiary">
                  <summary className="cursor-pointer">
                    {t('contacts.show_errors', { defaultValue: 'Show error details' })}
                  </summary>
                  <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
                    {result.errors.slice(0, 20).map((err) => (
                      <li key={`row-${err.row}`}>
                        {t('contacts.row_error', {
                          defaultValue: 'Row {{row}}: {{error}}',
                          row: err.row,
                          error: err.error,
                        })}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose}>
            {result
              ? t('common.close', { defaultValue: 'Close' })
              : t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {!result && (
            <Button
              variant="primary"
              onClick={handleImport}
              disabled={!file || isPending}
            >
              {isPending ? (
                <Loader2 size={16} className="animate-spin mr-1.5" />
              ) : (
                <Upload size={16} className="mr-1.5" />
              )}
              <span>{t('contacts.import_btn', { defaultValue: 'Import' })}</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Contact Card ──────────────────────────────────────────────────────── */

const ContactCard = React.memo(function ContactCard({
  contact,
  onEdit,
  onDelete,
}: {
  contact: Contact;
  onEdit: (contact: Contact) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  const prequal = PREQUAL_CONFIG[contact.prequalification_status as PrequalificationStatus] ?? PREQUAL_CONFIG.pending;
  const PrequalIcon = prequal.icon;
  const displayName = contact.company_name || [contact.first_name, contact.last_name].filter(Boolean).join(' ') || '—';
  const personName = [contact.first_name, contact.last_name].filter(Boolean).join(' ');

  return (
    <Card className="p-4 animate-card-in hover:shadow-md transition-shadow group">
      {/* Top: company + type badge + actions */}
      <div className="flex items-start justify-between gap-2">
        <div
          className="flex items-center gap-2.5 min-w-0 flex-1 cursor-pointer"
          onClick={() => onEdit(contact)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onEdit(contact); }}
        >
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue font-bold text-sm shrink-0">
            {displayName.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-content-primary truncate">
              {displayName}
            </h3>
            {personName && contact.company_name && (
              <p className="text-xs text-content-secondary truncate">{personName}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Badge variant={TYPE_BADGE_VARIANT[contact.contact_type] ?? 'neutral'} size="sm">
            {t(`contacts.type_${contact.contact_type}`, {
              defaultValue: contact.contact_type.charAt(0).toUpperCase() + contact.contact_type.slice(1),
            })}
          </Badge>
          <div className="flex items-center gap-0 opacity-0 group-hover:opacity-100 transition-opacity ml-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEdit(contact)}
              className="!p-1 text-content-quaternary hover:text-oe-blue h-auto"
              title={t('common.edit', { defaultValue: 'Edit' })}
            >
              <Pencil size={12} />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(contact.id)}
              className="!p-1 text-content-quaternary hover:text-red-500 h-auto"
              title={t('common.delete', { defaultValue: 'Delete' })}
            >
              <Trash2 size={12} />
            </Button>
          </div>
        </div>
      </div>

      {/* Contact details */}
      <div className="mt-3 space-y-1.5">
        {contact.primary_email && (
          <div className="flex items-center gap-2 text-xs text-content-secondary">
            <Mail size={12} className="shrink-0 text-content-tertiary" />
            <span className="truncate">{contact.primary_email}</span>
          </div>
        )}
        {contact.primary_phone && (
          <div className="flex items-center gap-2 text-xs text-content-secondary">
            <Phone size={12} className="shrink-0 text-content-tertiary" />
            <span>{contact.primary_phone}</span>
          </div>
        )}
      </div>

      {/* Bottom row: country + prequal */}
      <div className="mt-3 pt-2.5 border-t border-border-light flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {contact.country_code && (
            <>
              <CountryFlag code={contact.country_code} size={14} />
              <span className="text-xs text-content-tertiary">{contact.country_code}</span>
            </>
          )}
        </div>
        <div className={clsx('flex items-center gap-1 text-xs', prequal.cls)} title={t(prequal.labelKey, { defaultValue: prequal.defaultLabel })}>
          <PrequalIcon size={13} />
          <span className="hidden sm:inline">
            {t(prequal.labelKey, { defaultValue: prequal.defaultLabel })}
          </span>
        </div>
      </div>
    </Card>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ContactsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // State
  const [showAddModal, setShowAddModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<ContactType | ''>('');
  const [countryFilter, setCountryFilter] = useState('');

  // "n" shortcut → open new contact form
  useCreateShortcut(
    useCallback(() => setShowAddModal(true), []),
    !showAddModal && !showImportModal,
  );

  // Data
  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ['contacts', typeFilter],
    queryFn: () =>
      fetchContacts({
        contact_type: typeFilter || undefined,
        limit: 50,
      }),
  });

  // Client-side search + country filter
  const filtered = useMemo(() => {
    let list = contacts;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (c) =>
          (c.company_name || '').toLowerCase().includes(q) ||
          (c.first_name || '').toLowerCase().includes(q) ||
          (c.last_name || '').toLowerCase().includes(q) ||
          (c.primary_email || '').toLowerCase().includes(q),
      );
    }
    if (countryFilter.trim()) {
      const cf = countryFilter.toLowerCase();
      list = list.filter((c) => (c.country_code || '').toLowerCase().includes(cf));
    }
    return list;
  }, [contacts, searchQuery, countryFilter]);

  // Unique countries for filter display
  const countries = useMemo(() => {
    const set = new Set<string>();
    contacts.forEach((c) => {
      if (c.country_code) set.add(c.country_code);
    });
    return Array.from(set).sort();
  }, [contacts]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateContactPayload) => createContact(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contacts'] });
      setShowAddModal(false);
      addToast({
        type: 'success',
        title: t('contacts.created', { defaultValue: 'Contact created successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('contacts.create_failed', { defaultValue: 'Failed to create contact' }),
        message: e.message,
      }),
  });

  // Export mutation
  const exportMut = useMutation({
    mutationFn: exportContacts,
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('contacts.export_success', { defaultValue: 'Contacts exported successfully' }),
        message: t('contacts.export_success_msg', { defaultValue: 'Excel file has been downloaded.' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('contacts.export_failed', { defaultValue: 'Failed to export contacts' }),
        message: e.message,
      }),
  });

  // Edit mutation
  const editMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<CreateContactPayload> }) =>
      updateContact(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contacts'] });
      setShowAddModal(false);
      setEditingContact(null);
      addToast({
        type: 'success',
        title: t('contacts.updated', { defaultValue: 'Contact updated successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('contacts.update_failed', { defaultValue: 'Failed to update contact' }),
        message: e.message,
      }),
  });

  // Delete mutation
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteContact(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contacts'] });
      addToast({
        type: 'success',
        title: t('contacts.deleted', { defaultValue: 'Contact deleted' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('contacts.delete_failed', { defaultValue: 'Failed to delete contact' }),
        message: e.message,
      }),
  });

  const { confirm, ...confirmProps } = useConfirm();

  const formDataFromContact = useCallback((c: Contact): ContactFormData => ({
    company_name: c.company_name || '',
    legal_name: c.legal_name || '',
    vat_number: c.vat_number || '',
    first_name: c.first_name || '',
    last_name: c.last_name || '',
    contact_type: c.contact_type,
    email: c.primary_email || '',
    phone: c.primary_phone || '',
    website: c.website || '',
    country: c.country_code || '',
    address: c.address && typeof c.address === 'object' && 'text' in c.address
      ? String(c.address.text)
      : '',
    payment_terms: c.payment_terms_days || '30',
    prequalification_status: (c.prequalification_status as PrequalificationStatus) || 'pending',
    notes: c.notes || '',
  }), []);

  const handleEditContact = useCallback((contact: Contact) => {
    setEditingContact(contact);
    setShowAddModal(true);
  }, []);

  const handleDeleteContact = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('contacts.confirm_delete_title', { defaultValue: 'Delete contact?' }),
        message: t('contacts.confirm_delete_msg', { defaultValue: 'This contact will be permanently deleted.' }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(id);
    },
    [deleteMut, confirm, t],
  );

  const handleCreateSubmit = useCallback(
    (formData: ContactFormData) => {
      createMut.mutate({
        contact_type: formData.contact_type,
        first_name: formData.first_name || undefined,
        last_name: formData.last_name || undefined,
        company_name: formData.company_name || undefined,
        legal_name: formData.legal_name || undefined,
        vat_number: formData.vat_number || undefined,
        primary_email: formData.email || undefined,
        primary_phone: formData.phone || undefined,
        website: formData.website || undefined,
        country_code: formData.country || undefined,
        address: formData.address ? { text: formData.address } : undefined,
        payment_terms_days: formData.payment_terms || undefined,
        prequalification_status: formData.prequalification_status || undefined,
        notes: formData.notes || undefined,
      });
    },
    [createMut],
  );

  const handleEditSubmit = useCallback(
    (formData: ContactFormData) => {
      if (!editingContact) return;
      editMut.mutate({
        id: editingContact.id,
        data: {
          contact_type: formData.contact_type,
          first_name: formData.first_name || undefined,
          last_name: formData.last_name || undefined,
          company_name: formData.company_name || undefined,
          legal_name: formData.legal_name || undefined,
          vat_number: formData.vat_number || undefined,
          primary_email: formData.email || undefined,
          primary_phone: formData.phone || undefined,
          website: formData.website || undefined,
          country_code: formData.country || undefined,
          address: formData.address ? { text: formData.address } : undefined,
          payment_terms_days: formData.payment_terms || undefined,
          prequalification_status: formData.prequalification_status || undefined,
          notes: formData.notes || undefined,
        },
      });
    },
    [editMut, editingContact],
  );

  return (
    <div className="w-full animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('contacts.title', { defaultValue: 'Contacts' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('contacts.page_title', { defaultValue: 'Contacts Directory' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('contacts.subtitle', { defaultValue: 'Manage clients, subcontractors, suppliers, and consultants' })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={
              exportMut.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Download size={14} />
              )
            }
            onClick={() => exportMut.mutate()}
            disabled={exportMut.isPending}
          >
            {t('contacts.export', { defaultValue: 'Export' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Upload size={14} />}
            onClick={() => setShowImportModal(true)}
          >
            {t('contacts.import', { defaultValue: 'Import' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowAddModal(true)}
            icon={<Plus size={14} />}
          >
            {t('contacts.new_contact', { defaultValue: 'New Contact' })}
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <Card padding="none" className="mb-6">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
          {/* Search */}
          <div className="relative flex-1">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
              <Search size={16} />
            </div>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('contacts.search_placeholder', {
                defaultValue: 'Search contacts...',
              })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            />
          </div>

          {/* Type filter */}
          <div className="relative">
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as ContactType | '')}
              className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-44"
            >
              <option value="">
                {t('contacts.filter_all_types', { defaultValue: 'All Types' })}
              </option>
              {CONTACT_TYPES.map((ct) => (
                <option key={ct} value={ct}>
                  {t(`contacts.type_${ct}`, {
                    defaultValue: ct.charAt(0).toUpperCase() + ct.slice(1),
                  })}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>

          {/* Country filter */}
          <div className="relative">
            <select
              value={countryFilter}
              onChange={(e) => setCountryFilter(e.target.value)}
              className="h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-36"
            >
              <option value="">
                {t('contacts.filter_all_countries', { defaultValue: 'All Countries' })}
              </option>
              {countries.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
              <ChevronDown size={14} />
            </div>
          </div>
        </div>
      </Card>

      {/* Results */}
      <div>
        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Card key={i} className="p-4">
                <div className="flex items-center gap-2.5">
                  <div className="h-9 w-9 animate-pulse rounded-lg bg-surface-tertiary" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-3/4 animate-pulse rounded bg-surface-tertiary" />
                    <div className="h-3 w-1/2 animate-pulse rounded bg-surface-tertiary" />
                  </div>
                </div>
              </Card>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Building2 size={28} strokeWidth={1.5} />}
            title={
              searchQuery || typeFilter || countryFilter
                ? t('contacts.no_results', { defaultValue: 'No matching contacts' })
                : t('contacts.no_contacts', { defaultValue: 'No contacts yet' })
            }
            description={
              searchQuery || typeFilter || countryFilter
                ? t('contacts.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('contacts.no_contacts_hint', {
                    defaultValue: 'Your contacts directory stores clients, subcontractors, and suppliers. Import from CSV or add them manually to build your network.',
                  })
            }
            action={
              !searchQuery && !typeFilter && !countryFilter
                ? {
                    label: t('contacts.new_contact', { defaultValue: 'New Contact' }),
                    onClick: () => setShowAddModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-4 text-sm text-content-tertiary">
              {t('contacts.showing_count', {
                defaultValue: '{{count}} contacts',
                count: filtered.length,
              })}
            </p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((contact) => (
                <ContactCard
                  key={contact.id}
                  contact={contact}
                  onEdit={handleEditContact}
                  onDelete={handleDeleteContact}
                />
              ))}
            </div>
          </>
        )}
      </div>

      {/* Add / Edit Modal */}
      {showAddModal && (
        <AddContactModal
          onClose={() => { setShowAddModal(false); setEditingContact(null); }}
          onSubmit={editingContact ? handleEditSubmit : handleCreateSubmit}
          isPending={editingContact ? editMut.isPending : createMut.isPending}
          initialData={editingContact ? formDataFromContact(editingContact) : null}
          isEdit={!!editingContact}
        />
      )}

      {/* Import Modal */}
      {showImportModal && (
        <ImportContactsModal
          onClose={() => setShowImportModal(false)}
          onSuccess={() => {
            qc.invalidateQueries({ queryKey: ['contacts'] });
          }}
        />
      )}

      {/* Confirm Dialog (for delete) */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
