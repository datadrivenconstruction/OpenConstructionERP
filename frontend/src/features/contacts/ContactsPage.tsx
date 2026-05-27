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
  User,
  Pencil,
  Trash2,
  Info,
  AlertTriangle,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  CountryFlag,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useCreateShortcut } from '@/shared/hooks/useCreateShortcut';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchContacts,
  fetchContactTags,
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

const CONTACT_TYPES: ContactType[] = [
  'customer',
  'lead',
  'client',
  'subcontractor',
  'supplier',
  'consultant',
];

/* Tag-prefix → display group used by the CRM chip strip. The order
 * defines the row order rendered in the UI. */
const TAG_GROUPS: { prefix: string; label: string }[] = [
  { prefix: 'group:', label: 'Tier' },
  { prefix: 'topic:', label: 'Topic' },
  { prefix: 'lang:', label: 'Language' },
  { prefix: 'country:', label: 'Country' },
  { prefix: 'inbox:', label: 'Inbox' },
  { prefix: 'consent:', label: 'Consent' },
];

/* Cap per group so the strip stays scannable at 6.6K contacts. */
const TAG_GROUP_CAP = 8;

const LS_INFO_DISMISSED = 'oe_contacts_info_dismissed';

const TYPE_BADGE_VARIANT: Record<ContactType, 'blue' | 'warning' | 'success' | 'neutral'> = {
  client: 'blue',
  subcontractor: 'warning',
  supplier: 'success',
  consultant: 'neutral',
  internal: 'neutral',
  lead: 'warning',
  customer: 'success',
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
  lead: { icon: User, color: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800' },
  customer: { icon: Users, color: 'text-emerald-600 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-950/30 dark:border-emerald-800' },
};

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

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="xl"
      title={
        isEdit
          ? t('contacts.edit_contact', { defaultValue: 'Edit Contact' })
          : t('contacts.add_contact', { defaultValue: 'Add Contact' })
      }
      footer={
        <>
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
        </>
      }
    >
      {/* Contact type picker — 4-wide tile row */}
      <WideModalSection columns={1}>
        <WideModalField
          label={t('contacts.field_type', { defaultValue: 'Contact Type' })}
          required
        >
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
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
        </WideModalField>
      </WideModalSection>

      {/* Company */}
      <WideModalSection
        title={t('contacts.section_company', { defaultValue: 'Company' })}
        columns={2}
      >
        <WideModalField
          label={t('contacts.field_company', { defaultValue: 'Company Name' })}
          required
          span={2}
          error={errors.company_name}
        >
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
          />
        </WideModalField>

        <WideModalField label={t('contacts.field_legal_name', { defaultValue: 'Legal Name' })}>
          <input
            value={form.legal_name}
            onChange={(e) => set('legal_name', e.target.value)}
            className={inputCls}
            placeholder={t('contacts.legal_name_placeholder', { defaultValue: 'Registered legal entity name' })}
          />
        </WideModalField>

        <WideModalField label={t('contacts.field_vat', { defaultValue: 'VAT / Tax ID' })}>
          <input
            value={form.vat_number}
            onChange={(e) => set('vat_number', e.target.value)}
            className={inputCls}
            placeholder={t('contacts.vat_placeholder', { defaultValue: 'e.g. DE123456789' })}
          />
        </WideModalField>
      </WideModalSection>

      {/* Person */}
      <WideModalSection
        title={t('contacts.section_person', { defaultValue: 'Contact Person' })}
        columns={2}
      >
        <WideModalField label={t('contacts.field_first_name', { defaultValue: 'First Name' })}>
          <input
            value={form.first_name}
            onChange={(e) => set('first_name', e.target.value)}
            className={inputCls}
            placeholder={t('contacts.first_name_placeholder', { defaultValue: 'John' })}
          />
        </WideModalField>

        <WideModalField label={t('contacts.field_last_name', { defaultValue: 'Last Name' })}>
          <input
            value={form.last_name}
            onChange={(e) => set('last_name', e.target.value)}
            className={inputCls}
            placeholder={t('contacts.last_name_placeholder', { defaultValue: 'Doe' })}
          />
        </WideModalField>
      </WideModalSection>

      {/* Contact details */}
      <WideModalSection
        title={t('contacts.section_contact', { defaultValue: 'Contact Details' })}
        columns={2}
      >
        <WideModalField label={t('contacts.field_email', { defaultValue: 'Email' })}>
          <input
            type="email"
            value={form.email}
            onChange={(e) => set('email', e.target.value)}
            className={inputCls}
            placeholder="name@company.com"
          />
        </WideModalField>

        <WideModalField label={t('contacts.field_phone', { defaultValue: 'Phone' })}>
          <input
            type="tel"
            value={form.phone}
            onChange={(e) => set('phone', e.target.value)}
            className={inputCls}
            placeholder="+49 170 1234567"
          />
        </WideModalField>

        <WideModalField label={t('contacts.field_website', { defaultValue: 'Website' })} span={2}>
          <input
            type="url"
            value={form.website}
            onChange={(e) => set('website', e.target.value)}
            className={inputCls}
            placeholder="https://www.example.com"
          />
        </WideModalField>
      </WideModalSection>

      {/* Address */}
      <WideModalSection
        title={t('contacts.section_address', { defaultValue: 'Address' })}
        columns={2}
      >
        <WideModalField
          label={t('contacts.field_country', { defaultValue: 'Country' })}
          error={errors.country}
        >
          <input
            value={form.country}
            onChange={(e) =>
              set('country', e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 2))
            }
            maxLength={2}
            className={clsx(
              inputCls,
              errors.country && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
            )}
            placeholder={t('contacts.country_placeholder', {
              defaultValue: 'e.g. DE, US, GB',
            })}
          />
        </WideModalField>

        <WideModalField label={t('contacts.field_address', { defaultValue: 'Address' })}>
          <textarea
            value={form.address}
            onChange={(e) => set('address', e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            placeholder={t('contacts.address_placeholder', {
              defaultValue: 'Street address, City, ZIP / Postal code',
            })}
          />
        </WideModalField>
      </WideModalSection>

      {/* Payment & Status */}
      <WideModalSection
        title={t('contacts.section_payment', { defaultValue: 'Payment & Status' })}
        columns={2}
      >
        <WideModalField
          label={t('contacts.field_payment_terms', { defaultValue: 'Payment Terms' })}
        >
          <div className="flex items-center gap-2">
            {['30', '45', '60'].map((days) => (
              <button
                key={days}
                type="button"
                onClick={() => set('payment_terms', days)}
                className={clsx(
                  'flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-all text-center',
                  form.payment_terms === days
                    ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text ring-1 ring-oe-blue/30'
                    : 'border-border text-content-tertiary hover:border-border-light hover:text-content-secondary',
                )}
              >
                {days} {t('contacts.days', { defaultValue: 'days' })}
              </button>
            ))}
          </div>
        </WideModalField>

        <WideModalField label={t('contacts.field_prequal', { defaultValue: 'Prequalification' })}>
          <select
            value={form.prequalification_status}
            onChange={(e) =>
              set('prequalification_status', e.target.value as PrequalificationStatus)
            }
            className={inputCls}
          >
            {(Object.keys(PREQUAL_CONFIG) as PrequalificationStatus[]).map((ps) => (
              <option key={ps} value={ps}>
                {t(PREQUAL_CONFIG[ps].labelKey, {
                  defaultValue: PREQUAL_CONFIG[ps].defaultLabel,
                })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('contacts.field_notes', { defaultValue: 'Notes' })}
          span={2}
        >
          <textarea
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            placeholder={t('contacts.notes_placeholder', {
              defaultValue: 'Additional notes...',
            })}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
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
      setError(err instanceof Error ? err.message : t('contacts.import_failed', { defaultValue: 'Import failed' }));
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
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
              {t('contacts.file_types', { defaultValue: '.xlsx, .csv' })}
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
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text font-bold text-sm shrink-0">
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

      {/* Module-bridge tags (v3117). Shown when the contact participates
         in PropDev / brokers / vendors / … modules. Each tag is a small
         badge so the user can spot at a glance which modules reference
         this contact. */}
      {contact.module_tags && contact.module_tags.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {contact.module_tags.map((tag) => (
            <Badge key={tag} size="sm" variant="blue">
              {t(`contacts.module_tag_${tag}`, {
                defaultValue: tag.replace(/_/g, ' '),
              })}
            </Badge>
          ))}
        </div>
      )}

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
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [infoDismissed, setInfoDismissed] = useState(
    () => localStorage.getItem(LS_INFO_DISMISSED) === '1',
  );

  // "n" shortcut → open new contact form
  useCreateShortcut(
    useCallback(() => setShowAddModal(true), []),
    !showAddModal && !showImportModal,
  );

  // Data
  const {
    data: contacts = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['contacts', typeFilter, selectedTags],
    queryFn: () =>
      fetchContacts({
        contact_type: typeFilter || undefined,
        tags: selectedTags.length > 0 ? selectedTags : undefined,
        // Bumped to 500 so the CRM tier views (e.g. ~3,500 inbound leads)
        // surface enough rows for client-side search to feel right after
        // chip filtering. The backend caps at 500.
        limit: 500,
      }),
  });

  // CRM tag facets — feeds the chip strip above the search bar.
  const { data: tagFacets = [] } = useQuery({
    queryKey: ['contacts', 'tags'],
    queryFn: fetchContactTags,
    staleTime: 60_000,
  });

  /* Group facets by prefix and cap per group so the chip strip stays
   * scannable. Tags without a known prefix bucket land under "Other". */
  const groupedFacets = useMemo(() => {
    const buckets = new Map<string, { tag: string; count: number; label: string }[]>();
    for (const def of TAG_GROUPS) {
      buckets.set(def.label, []);
    }
    buckets.set('Other', []);

    for (const facet of tagFacets) {
      const group = TAG_GROUPS.find((g) => facet.tag.startsWith(g.prefix));
      const label = group ? facet.tag.slice(group.prefix.length) : facet.tag;
      const target = buckets.get(group?.label ?? 'Other')!;
      target.push({ tag: facet.tag, count: facet.count, label });
    }
    return Array.from(buckets.entries())
      .map(([label, items]) => ({ label, items: items.slice(0, TAG_GROUP_CAP) }))
      .filter((g) => g.items.length > 0);
  }, [tagFacets]);

  const toggleTag = useCallback((tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }, []);

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

      {/* Purpose / help banner — explains the directory and how it
          connects to the rest of the platform. */}
      {!infoDismissed && (
        <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800 dark:border-blue-700 dark:bg-blue-950/30 dark:text-blue-300 relative">
          <button
            onClick={() => {
              setInfoDismissed(true);
              localStorage.setItem(LS_INFO_DISMISSED, '1');
            }}
            className="absolute top-2 right-2 flex h-6 w-6 items-center justify-center rounded text-blue-400 hover:text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-900/40 dark:hover:text-blue-200 transition-colors"
            aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
          >
            <X size={14} />
          </button>
          <div className="flex items-center gap-2 mb-1">
            <Info size={16} />
            <span className="font-semibold">
              {t('contacts.info_title', { defaultValue: 'About the Contacts Directory' })}
            </span>
          </div>
          <p className="text-xs pr-6">
            {t('contacts.info_body', {
              defaultValue:
                'A single, shared address book for every organisation and person on your projects — clients, subcontractors, suppliers, and consultants. Prequalification status flags who is approved to bid or be awarded work.',
            })}{' '}
            {t('contacts.info_link_hint', {
              defaultValue:
                'Contacts are reused across the platform: as RFI / submittal ball-in-court, transmittal recipients, correspondence parties, and tender invitees. Keep this list clean and everything downstream stays consistent.',
            })}
          </p>
        </div>
      )}

      {/* CRM tag-chip strip — surfaces metadata.tags from imported
          contacts so a user can pivot the list by tier / topic / language /
          country / inbox / consent without typing into search. AND-combined:
          selecting two chips returns only contacts that carry both tags. */}
      {groupedFacets.length > 0 && (
        <Card padding="none" className="mb-4">
          <div className="flex flex-col gap-2 p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('contacts.filter_by_tag', { defaultValue: 'Quick filter' })}
              </span>
              {selectedTags.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSelectedTags([])}
                  className="text-xs font-medium text-oe-blue hover:underline"
                >
                  {t('contacts.clear_tags', {
                    defaultValue: 'Clear ({{n}})',
                    n: selectedTags.length,
                  })}
                </button>
              )}
            </div>
            {groupedFacets.map((group) => (
              <div key={group.label} className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 w-16 shrink-0 text-[11px] font-medium uppercase tracking-wide text-content-tertiary">
                  {group.label}
                </span>
                {group.items.map((item) => {
                  const active = selectedTags.includes(item.tag);
                  return (
                    <button
                      key={item.tag}
                      type="button"
                      onClick={() => toggleTag(item.tag)}
                      aria-pressed={active}
                      className={clsx(
                        'h-7 rounded-full border px-2.5 text-xs font-medium transition-colors',
                        active
                          ? 'border-oe-blue bg-oe-blue text-white'
                          : 'border-border bg-surface-primary text-content-secondary hover:border-border-light hover:text-content-primary',
                      )}
                    >
                      {item.label}
                      <span
                        className={clsx(
                          'ml-1.5 text-[10px]',
                          active ? 'text-white/80' : 'text-content-tertiary',
                        )}
                      >
                        {item.count}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </Card>
      )}

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

          {/* Type filter — visible chip group (Probe-D P2-9). Was a hidden
              select; promoted to chips so the 4 contact types are
              discoverable at a glance and don't blend into the wall of
              buttons elsewhere on the page. Only 4 types so no
              "Show more" is needed; if CONTACT_TYPES grows beyond 6
              the >6 entries should collapse behind a "More (N)" chip. */}
          <div
            role="group"
            aria-label={t('contacts.filter_by_type', { defaultValue: 'Filter by contact type' })}
            data-testid="contacts-type-chips"
            className="flex flex-wrap items-center gap-1.5"
          >
            <button
              type="button"
              data-testid="contacts-type-chip-all"
              onClick={() => setTypeFilter('')}
              aria-pressed={typeFilter === ''}
              className={clsx(
                'h-8 px-3 rounded-full border text-xs font-medium transition-colors',
                typeFilter === ''
                  ? 'border-oe-blue bg-oe-blue text-white'
                  : 'border-border bg-surface-primary text-content-secondary hover:border-border-light hover:text-content-primary',
              )}
            >
              {t('contacts.filter_all_types', { defaultValue: 'All Types' })}
            </button>
            {CONTACT_TYPES.map((ct) => {
              const active = typeFilter === ct;
              return (
                <button
                  key={ct}
                  type="button"
                  data-testid={`contacts-type-chip-${ct}`}
                  onClick={() => setTypeFilter(active ? '' : ct)}
                  aria-pressed={active}
                  className={clsx(
                    'h-8 px-3 rounded-full border text-xs font-medium transition-colors',
                    active
                      ? 'border-oe-blue bg-oe-blue text-white'
                      : 'border-border bg-surface-primary text-content-secondary hover:border-border-light hover:text-content-primary',
                  )}
                >
                  {t(`contacts.type_${ct}`, {
                    defaultValue: ct.charAt(0).toUpperCase() + ct.slice(1),
                  })}
                </button>
              );
            })}
          </div>

          {/* Country filter */}
          <div className="relative">
            <select
              value={countryFilter}
              onChange={(e) => setCountryFilter(e.target.value)}
              aria-label={t('a11y.contacts.country_filter', {
                defaultValue: 'Filter contacts by country',
              })}
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
        ) : isError ? (
          <EmptyState
            icon={<AlertTriangle size={28} strokeWidth={1.5} />}
            title={t('contacts.load_failed', {
              defaultValue: 'Could not load contacts',
            })}
            description={
              error instanceof Error
                ? error.message
                : t('contacts.load_failed_hint', {
                    defaultValue:
                      'Something went wrong fetching the directory. Please try again.',
                  })
            }
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => refetch(),
            }}
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Building2 size={28} strokeWidth={1.5} />}
            title={
              searchQuery || typeFilter || countryFilter || selectedTags.length > 0
                ? t('contacts.no_results', { defaultValue: 'No matching contacts' })
                : t('contacts.no_contacts', { defaultValue: 'No contacts yet' })
            }
            description={
              searchQuery || typeFilter || countryFilter || selectedTags.length > 0
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
                    /* Empty-state copy unified per Probe-D P2-11 —
                       "Create your first {entity}" pattern. */
                    label: t('contacts.create_first', { defaultValue: 'Create your first contact' }),
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
