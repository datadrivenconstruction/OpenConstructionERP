// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useEffect, useMemo, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { X, Layers } from 'lucide-react';
import { Button, Input } from '@/shared/ui';
import { CurrencyPicker } from '@/shared/ui/CurrencyPicker';
import { useToastStore } from '@/stores/useToastStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { getUnitsForLocale } from '@/features/boq/boqHelpers';
import { unitLabel } from '@/shared/lib/unitLabels';
import { assembliesApi, type CreateAssemblyData } from './api';

/* -- Constants ------------------------------------------------------------ */

const CATEGORIES = [
  { value: 'concrete', key: 'assemblies.cat_concrete', defaultLabel: 'Concrete' },
  { value: 'masonry', key: 'assemblies.cat_masonry', defaultLabel: 'Masonry' },
  { value: 'steel', key: 'assemblies.cat_steel', defaultLabel: 'Steel' },
  { value: 'mep', key: 'assemblies.cat_mep', defaultLabel: 'MEP' },
  { value: 'earthwork', key: 'assemblies.cat_earthwork', defaultLabel: 'Earthwork' },
  { value: 'general', key: 'assemblies.cat_general', defaultLabel: 'General' },
];

// The value picked here becomes a KEY in the template's `classification`
// dict (see the submit handler below), so it must be a standard something
// downstream can read back. Two consumers read that dict: the library page,
// which badges the codes, and the BOQ section-path renderer in
// match_elements, which walks `classification_order()` and can only find a
// key that is in KNOWN_CLASSIFICATION_STANDARDS on the backend.
//
// UniFormat and Uniclass were offered here and are in neither. Picking one
// stored the code and then no reader anywhere could name it: the library
// guard renders only the keys badged below, and the BOQ renderer never looks
// the key up, so the estimator's own input vanished with no error. That is
// the same defect CreateProjectPage.tsx fixed on the project standards
// picker; this mirror was missed. Being in CLASSIFICATION_STANDARD_LABELS is
// not enough - a label exists so a stored code can be named, and 18 standards
// have one while only 13 are honoured.
const STANDARDS = [
  { value: 'din276', key: 'assemblies.std_din276', defaultLabel: 'DIN 276' },
  { value: 'nrm', key: 'assemblies.std_nrm', defaultLabel: 'NRM' },
  { value: 'masterformat', key: 'assemblies.std_masterformat', defaultLabel: 'MasterFormat' },
];

/* -- Modal ---------------------------------------------------------------- */

interface CreateAssemblyModalProps {
  open: boolean;
  onClose: () => void;
}

export function CreateAssemblyModal({ open, onClose }: CreateAssemblyModalProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  // Default the assembly currency to the user's preferred currency
  // (Regional Settings) instead of a hardcoded 'EUR' — a user working in
  // USD/GBP/BRL who doesn't open the dropdown would otherwise silently stamp
  // their assemblies as EUR. The field stays editable below.
  const rawPreferredCurrency = usePreferencesStore((s) => s.currency);
  const preferredCurrency = /^[A-Z]{3}$/.test(rawPreferredCurrency) ? rawPreferredCurrency : 'EUR';
  // Locale/imperial-aware unit dropdown, same primitive the BOQ editor uses:
  // the list carries imperial + locale-specific tokens (not metric-only), and
  // the seeded default follows the user's measurement system so an imperial
  // user opens on sqft instead of m2. Storage stays free-text/canonical.
  const measurementSystem = usePreferencesStore((s) => s.measurementSystem);
  const defaultUnit = measurementSystem === 'imperial' ? 'sqft' : 'm2';
  const unitOptions = useMemo(() => getUnitsForLocale(i18n.language), [i18n.language]);

  const [form, setForm] = useState({
    code: '',
    name: '',
    unit: defaultUnit,
    category: 'general',
    classificationStandard: '',
    classificationCode: '',
    currency: preferredCurrency,
    bid_factor: '1.00',
  });

  useEffect(() => {
    if (open) {
      setForm({
        code: '', name: '', unit: defaultUnit, category: 'general',
        classificationStandard: '', classificationCode: '',
        currency: preferredCurrency, bid_factor: '1.00',
      });
    }
  }, [open, preferredCurrency, defaultUnit]);

  const mutation = useMutation({
    mutationFn: (data: CreateAssemblyData) => assembliesApi.create(data),
    onSuccess: (assembly) => {
      queryClient.invalidateQueries({ queryKey: ['assemblies'] });
      onClose();
      navigate(`/assemblies/${assembly.id}`);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('assemblies.create_failed', { defaultValue: 'Failed to create assembly' }), message: err.message });
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.code.trim() || !form.name.trim()) return;

    const classification: Record<string, string> = {};
    if (form.classificationStandard && form.classificationCode) {
      classification[form.classificationStandard] = form.classificationCode;
    }

    mutation.mutate({
      code: form.code,
      name: form.name,
      unit: form.unit,
      category: form.category,
      classification: Object.keys(classification).length > 0 ? classification : undefined,
      // Fall back to the preferred currency if the custom field was left
      // blank, so an assembly never lands with an empty currency.
      currency: form.currency.trim() || preferredCurrency,
      bid_factor: parseFloat(form.bid_factor) || 1.0,
    });
  };

  const set = (field: string, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const selectClass =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none';

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
        onClick={onClose}
      />

      <div className="relative w-full max-w-2xl mx-4 max-h-[90vh] rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-primary/10">
              <Layers size={20} className="text-accent-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('assemblies.new_assembly', { defaultValue: 'New Assembly' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('assemblies.create_subtitle', { defaultValue: 'Create a reusable cost assembly' })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto px-6 pb-6 flex-1">
          <form id="create-assembly-form" onSubmit={handleSubmit} className="space-y-4">
            {/* Code & Name */}
            <div className="grid grid-cols-3 gap-4">
              <Input
                label={t('assemblies.code', { defaultValue: 'Code' })}
                value={form.code}
                onChange={(e) => set('code', e.target.value)}
                placeholder={t('assemblies.code_placeholder', { defaultValue: 'e.g. ASM-001' })}
                required aria-required="true"
                autoFocus
              />
              <div className="col-span-2">
                <Input
                  label={t('assemblies.name', { defaultValue: 'Name' })}
                  value={form.name}
                  onChange={(e) => set('name', e.target.value)}
                  placeholder={t('assemblies.name_placeholder', { defaultValue: 'e.g. Reinforced Concrete Wall C30/37' })}
                  required aria-required="true"
                />
              </div>
            </div>

            {/* Unit & Category */}
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-content-primary">{t('assemblies.unit', { defaultValue: 'Unit' })}</label>
                {/* Friendly, localized label (e.g. "m² · Square meter") while the
                    option value stays the canonical getUnitsForLocale token, so
                    imperial/locale coverage and canonical storage are unchanged. */}
                <select value={form.unit} onChange={(e) => set('unit', e.target.value)} className={selectClass}>
                  {unitOptions.map((u) => (
                    <option key={u} value={u}>{unitLabel(u, t)}</option>
                  ))}
                </select>
                <p className="text-xs text-content-tertiary">
                  {t('assemblies.unit_hint', {
                    defaultValue: 'The unit the finished rate is priced per (e.g. m² of wall). Each component can still use its own unit.',
                  })}
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-content-primary">{t('assemblies.category', { defaultValue: 'Category' })}</label>
                <select value={form.category} onChange={(e) => set('category', e.target.value)} className={selectClass}>
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>{t(c.key, { defaultValue: c.defaultLabel })}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Classification */}
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-content-primary">
                  {t('assemblies.classification_standard', { defaultValue: 'Classification Standard' })}
                </label>
                <select value={form.classificationStandard} onChange={(e) => set('classificationStandard', e.target.value)} className={selectClass}>
                  <option value="">{t('assemblies.none', { defaultValue: '-- None --' })}</option>
                  {STANDARDS.map((s) => (
                    <option key={s.value} value={s.value}>{t(s.key, { defaultValue: s.defaultLabel })}</option>
                  ))}
                </select>
              </div>
              <Input
                label={t('assemblies.classification_code', { defaultValue: 'Classification Code' })}
                value={form.classificationCode}
                onChange={(e) => set('classificationCode', e.target.value)}
                placeholder={t('assemblies.classification_code_placeholder', { defaultValue: 'e.g. 330' })}
                disabled={!form.classificationStandard}
              />
            </div>

            {/* Currency & Bid Factor */}
            <div className="grid grid-cols-2 gap-4">
              <CurrencyPicker
                id="create-assembly-currency"
                label={t('assemblies.currency', { defaultValue: 'Currency' })}
                value={form.currency}
                onChange={(code) => set('currency', code)}
                selectClassName={selectClass}
              />
              <Input
                label={t('assemblies.bid_factor', { defaultValue: 'Bid Factor' })}
                type="number"
                value={form.bid_factor}
                onChange={(e) => set('bid_factor', e.target.value)}
                placeholder="1.00"
                hint={t('assemblies.bid_factor_hint', { defaultValue: 'Multiplier applied to the total rate (1.00 = no markup)' })}
              />
            </div>

            {mutation.error && (
              <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
                {(mutation.error as Error).message || t('assemblies.create_failed', { defaultValue: 'Failed to create assembly' })}
              </div>
            )}
          </form>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light shrink-0">
          <Button variant="secondary" type="button" onClick={onClose}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button variant="primary" type="submit" form="create-assembly-form" loading={mutation.isPending}>
            {t('common.create', 'Create')}
          </Button>
        </div>
      </div>
    </div>
  );
}

// Route compat
export function CreateAssemblyPage() {
  const navigate = useNavigate();

  useEffect(() => {
    navigate('/assemblies', { state: { openCreateModal: true }, replace: true });
  }, [navigate]);

  return null;
}
