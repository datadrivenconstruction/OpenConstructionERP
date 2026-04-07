import { useState, useMemo, useCallback } from 'react';
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
  Shield,
  Upload,
  Download,
  Loader2,
  FileDown,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, CountryFlag } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchContacts,
  createContact,
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
};

const PREQUAL_CONFIG: Record<
  PrequalificationStatus,
  { icon: React.ElementType; cls: string; labelKey: string; defaultLabel: string }
> = {
  none: {
    icon: Shield,
    cls: 'text-content-quaternary',
    labelKey: 'contacts.prequal_none',
    defaultLabel: 'None',
  },
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

interface ContactFormData {
  company_name: string;
  contact_name: string;
  contact_type: ContactType;
  email: string;
  phone: string;
  country: string;
  address: string;
  prequalification_status: PrequalificationStatus;
  notes: string;
}

const EMPTY_FORM: ContactFormData = {
  company_name: '',
  contact_name: '',
  contact_type: 'client',
  email: '',
  phone: '',
  country: '',
  address: '',
  prequalification_status: 'none',
  notes: '',
};

function AddContactModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: ContactFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ContactFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof ContactFormData>(key: K, value: ContactFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const companyError = touched && form.company_name.trim().length === 0;
  const canSubmit = form.company_name.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('contacts.add_contact', { defaultValue: 'Add Contact' })}
          </h2>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-4">
          {/* Company Name */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('contacts.field_company', { defaultValue: 'Company Name' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.company_name}
              onChange={(e) => {
                set('company_name', e.target.value);
                setTouched(true);
              }}
              placeholder={t('contacts.company_placeholder', {
                defaultValue: 'e.g. Acme Construction Ltd.',
              })}
              className={clsx(
                inputCls,
                companyError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {companyError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('contacts.company_required', { defaultValue: 'Company name is required' })}
              </p>
            )}
          </div>

          {/* Two-column: Contact Name + Type */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('contacts.field_name', { defaultValue: 'Contact Name' })}
              </label>
              <input
                value={form.contact_name}
                onChange={(e) => set('contact_name', e.target.value)}
                className={inputCls}
                placeholder={t('contacts.name_placeholder', { defaultValue: 'Full name' })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('contacts.field_type', { defaultValue: 'Type' })}
              </label>
              <select
                value={form.contact_type}
                onChange={(e) => set('contact_type', e.target.value as ContactType)}
                className={inputCls}
              >
                {CONTACT_TYPES.map((ct) => (
                  <option key={ct} value={ct}>
                    {t(`contacts.type_${ct}`, {
                      defaultValue: ct.charAt(0).toUpperCase() + ct.slice(1),
                    })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Two-column: Email + Phone */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
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
              <label className="block text-sm font-medium text-content-secondary mb-1">
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

          {/* Two-column: Country + Prequalification */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('contacts.field_country', { defaultValue: 'Country' })}
              </label>
              <input
                value={form.country}
                onChange={(e) => set('country', e.target.value)}
                className={inputCls}
                placeholder={t('contacts.country_placeholder', {
                  defaultValue: 'e.g. DE, US, GB',
                })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
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

          {/* Address */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('contacts.field_address', { defaultValue: 'Address' })}
            </label>
            <input
              value={form.address}
              onChange={(e) => set('address', e.target.value)}
              className={inputCls}
              placeholder={t('contacts.address_placeholder', {
                defaultValue: 'Street, City, ZIP',
              })}
            />
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
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
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>
              {t('contacts.create_contact', { defaultValue: 'Create Contact' })}
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('contacts.import_contacts', { defaultValue: 'Import Contacts' })}
          </h2>
          <button
            onClick={onClose}
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
                    {result.errors.slice(0, 20).map((err, i) => (
                      <li key={i}>
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

function ContactCard({ contact }: { contact: Contact }) {
  const { t } = useTranslation();
  const prequal = PREQUAL_CONFIG[contact.prequalification_status] ?? PREQUAL_CONFIG.none;
  const PrequalIcon = prequal.icon;

  return (
    <Card className="p-4 animate-card-in hover:shadow-md transition-shadow">
      {/* Top: company + type badge */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue font-bold text-sm shrink-0">
            {contact.company_name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-content-primary truncate">
              {contact.company_name}
            </h3>
            {contact.contact_name && (
              <p className="text-xs text-content-secondary truncate">{contact.contact_name}</p>
            )}
          </div>
        </div>
        <Badge variant={TYPE_BADGE_VARIANT[contact.contact_type]} size="sm">
          {t(`contacts.type_${contact.contact_type}`, {
            defaultValue: contact.contact_type.charAt(0).toUpperCase() + contact.contact_type.slice(1),
          })}
        </Badge>
      </div>

      {/* Contact details */}
      <div className="mt-3 space-y-1.5">
        {contact.email && (
          <div className="flex items-center gap-2 text-xs text-content-secondary">
            <Mail size={12} className="shrink-0 text-content-tertiary" />
            <span className="truncate">{contact.email}</span>
          </div>
        )}
        {contact.phone && (
          <div className="flex items-center gap-2 text-xs text-content-secondary">
            <Phone size={12} className="shrink-0 text-content-tertiary" />
            <span>{contact.phone}</span>
          </div>
        )}
      </div>

      {/* Bottom row: country + prequal */}
      <div className="mt-3 pt-2.5 border-t border-border-light flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {contact.country && (
            <>
              <CountryFlag code={contact.country} size={14} />
              <span className="text-xs text-content-tertiary">{contact.country}</span>
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
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ContactsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // State
  const [showAddModal, setShowAddModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<ContactType | ''>('');
  const [countryFilter, setCountryFilter] = useState('');

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
          c.company_name.toLowerCase().includes(q) ||
          c.contact_name.toLowerCase().includes(q) ||
          c.email.toLowerCase().includes(q),
      );
    }
    if (countryFilter.trim()) {
      const cf = countryFilter.toLowerCase();
      list = list.filter((c) => c.country.toLowerCase().includes(cf));
    }
    return list;
  }, [contacts, searchQuery, countryFilter]);

  // Unique countries for filter display
  const countries = useMemo(() => {
    const set = new Set<string>();
    contacts.forEach((c) => {
      if (c.country) set.add(c.country);
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
        title: t('contacts.created', { defaultValue: 'Contact created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  // Export mutation
  const exportMut = useMutation({
    mutationFn: exportContacts,
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('contacts.export_success', { defaultValue: 'Export complete' }),
        message: t('contacts.export_success_msg', { defaultValue: 'Excel file downloaded.' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('contacts.export_failed', { defaultValue: 'Export failed' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: ContactFormData) => {
      createMut.mutate({
        company_name: formData.company_name,
        contact_name: formData.contact_name,
        contact_type: formData.contact_type,
        email: formData.email || undefined,
        phone: formData.phone || undefined,
        country: formData.country || undefined,
        address: formData.address || undefined,
        prequalification_status: formData.prequalification_status,
        notes: formData.notes || undefined,
      });
    },
    [createMut],
  );

  return (
    <div className="max-w-content mx-auto animate-fade-in">
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
        <h1 className="text-2xl font-bold text-content-primary">
          {t('contacts.page_title', { defaultValue: 'Contacts Directory' })}
        </h1>
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
            onClick={() => setShowAddModal(true)}
            icon={<Plus size={16} />}
          >
            {t('contacts.add_contact', { defaultValue: 'Add Contact' })}
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
            icon={<Building2 size={24} strokeWidth={1.5} />}
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
                    defaultValue: 'Add your first contact to get started',
                  })
            }
            action={
              !searchQuery && !typeFilter && !countryFilter
                ? {
                    label: t('contacts.add_contact', { defaultValue: 'Add Contact' }),
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
                <ContactCard key={contact.id} contact={contact} />
              ))}
            </div>
          </>
        )}
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <AddContactModal
          onClose={() => setShowAddModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
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
    </div>
  );
}
