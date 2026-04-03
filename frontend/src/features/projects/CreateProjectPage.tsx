import { useState, type FormEvent, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Button, Input, Card, InfoHint, Breadcrumb } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi, type CreateProjectData } from './api';

// ── Regions (grouped by continent) ────────────────────────────────────────

interface OptionGroup {
  group: string;
  options: { value: string; label: string }[];
}

const REGION_GROUPS: OptionGroup[] = [
  {
    group: 'Europe',
    options: [
      { value: 'DACH', label: 'DACH (Germany, Austria, Switzerland)' },
      { value: 'UK', label: 'United Kingdom' },
      { value: 'Nordics', label: 'Nordics (Sweden, Norway, Denmark, Finland)' },
      { value: 'France', label: 'France' },
      { value: 'Spain', label: 'Spain' },
      { value: 'Italy', label: 'Italy' },
      { value: 'Netherlands', label: 'Netherlands' },
      { value: 'Poland', label: 'Poland' },
      { value: 'Czech', label: 'Czech Republic' },
      { value: 'Turkey', label: 'Turkey' },
      { value: 'Russia', label: 'Russia' },
    ],
  },
  {
    group: 'Americas',
    options: [
      { value: 'US', label: 'United States' },
      { value: 'Canada', label: 'Canada' },
      { value: 'Brazil', label: 'Brazil' },
      { value: 'Mexico', label: 'Mexico' },
      { value: 'LatinAmerica', label: 'Latin America (Other)' },
    ],
  },
  {
    group: 'Asia & Middle East',
    options: [
      { value: 'China', label: 'China' },
      { value: 'Japan', label: 'Japan' },
      { value: 'Korea', label: 'South Korea' },
      { value: 'India', label: 'India' },
      { value: 'SoutheastAsia', label: 'Southeast Asia' },
      { value: 'MiddleEast', label: 'Middle East (General)' },
      { value: 'GulfStates', label: 'Gulf States (UAE, Saudi Arabia, Qatar)' },
    ],
  },
  {
    group: 'Africa',
    options: [
      { value: 'NorthAfrica', label: 'North Africa' },
      { value: 'SouthAfrica', label: 'South Africa' },
      { value: 'EastAfrica', label: 'East Africa' },
      { value: 'WestAfrica', label: 'West Africa' },
    ],
  },
  {
    group: 'Oceania',
    options: [
      { value: 'Australia', label: 'Australia' },
      { value: 'NewZealand', label: 'New Zealand' },
    ],
  },
  {
    group: 'Other',
    options: [
      { value: 'INTL', label: 'International / Multi-region' },
      { value: '__custom__', label: 'Custom...' },
    ],
  },
];

// ── Classification Standards ──────────────────────────────────────────────

const STANDARD_GROUPS: OptionGroup[] = [
  {
    group: 'Common Standards',
    options: [
      { value: 'din276', label: 'DIN 276 (Germany / DACH)' },
      { value: 'nrm', label: 'NRM 1/2 (United Kingdom)' },
      { value: 'masterformat', label: 'MasterFormat (US / Canada)' },
      { value: 'uniformat', label: 'UniFormat (US)' },
      { value: 'uniclass', label: 'Uniclass (UK)' },
      { value: 'omniclass', label: 'OmniClass (International)' },
      { value: 'gbt', label: 'GB/T (China)' },
    ],
  },
  {
    group: 'Other',
    options: [{ value: '__custom__', label: 'Custom...' }],
  },
];

// ── Currencies (all major construction market currencies) ─────────────────

const CURRENCY_GROUPS: OptionGroup[] = [
  {
    group: 'Europe',
    options: [
      { value: 'EUR', label: 'EUR (\u20ac) \u2014 Euro' },
      { value: 'GBP', label: 'GBP (\u00a3) \u2014 British Pound' },
      { value: 'CHF', label: 'CHF (Fr.) \u2014 Swiss Franc' },
      { value: 'SEK', label: 'SEK (kr) \u2014 Swedish Krona' },
      { value: 'NOK', label: 'NOK (kr) \u2014 Norwegian Krone' },
      { value: 'DKK', label: 'DKK (kr) \u2014 Danish Krone' },
      { value: 'PLN', label: 'PLN (z\u0142) \u2014 Polish Zloty' },
      { value: 'CZK', label: 'CZK (K\u010d) \u2014 Czech Koruna' },
      { value: 'TRY', label: 'TRY (\u20ba) \u2014 Turkish Lira' },
      { value: 'RUB', label: 'RUB (\u20bd) \u2014 Russian Ruble' },
      { value: 'HUF', label: 'HUF (Ft) \u2014 Hungarian Forint' },
      { value: 'RON', label: 'RON (lei) \u2014 Romanian Leu' },
      { value: 'BGN', label: 'BGN (\u043b\u0432) \u2014 Bulgarian Lev' },
      { value: 'HRK', label: 'HRK (kn) \u2014 Croatian Kuna' },
      { value: 'ISK', label: 'ISK (kr) \u2014 Icelandic Krona' },
    ],
  },
  {
    group: 'Americas',
    options: [
      { value: 'USD', label: 'USD ($) \u2014 US Dollar' },
      { value: 'CAD', label: 'CAD (C$) \u2014 Canadian Dollar' },
      { value: 'BRL', label: 'BRL (R$) \u2014 Brazilian Real' },
      { value: 'MXN', label: 'MXN (Mex$) \u2014 Mexican Peso' },
      { value: 'ARS', label: 'ARS (AR$) \u2014 Argentine Peso' },
      { value: 'CLP', label: 'CLP (CL$) \u2014 Chilean Peso' },
      { value: 'PEN', label: 'PEN (S/) \u2014 Peruvian Sol' },
      { value: 'COP', label: 'COP (COL$) \u2014 Colombian Peso' },
    ],
  },
  {
    group: 'Asia & Middle East',
    options: [
      { value: 'CNY', label: 'CNY (\u00a5) \u2014 Chinese Yuan' },
      { value: 'JPY', label: 'JPY (\u00a5) \u2014 Japanese Yen' },
      { value: 'KRW', label: 'KRW (\u20a9) \u2014 South Korean Won' },
      { value: 'INR', label: 'INR (\u20b9) \u2014 Indian Rupee' },
      { value: 'AED', label: 'AED (\u062f.\u0625) \u2014 UAE Dirham' },
      { value: 'SAR', label: 'SAR (\ufdfc) \u2014 Saudi Riyal' },
      { value: 'QAR', label: 'QAR (\ufdfc) \u2014 Qatari Riyal' },
      { value: 'BHD', label: 'BHD (BD) \u2014 Bahraini Dinar' },
      { value: 'KWD', label: 'KWD (\u062f.\u0643) \u2014 Kuwaiti Dinar' },
      { value: 'OMR', label: 'OMR (\u0631.\u0639.) \u2014 Omani Rial' },
      { value: 'SGD', label: 'SGD (S$) \u2014 Singapore Dollar' },
      { value: 'MYR', label: 'MYR (RM) \u2014 Malaysian Ringgit' },
      { value: 'THB', label: 'THB (\u0e3f) \u2014 Thai Baht' },
      { value: 'IDR', label: 'IDR (Rp) \u2014 Indonesian Rupiah' },
      { value: 'PHP', label: 'PHP (\u20b1) \u2014 Philippine Peso' },
      { value: 'VND', label: 'VND (\u20ab) \u2014 Vietnamese Dong' },
      { value: 'HKD', label: 'HKD (HK$) \u2014 Hong Kong Dollar' },
      { value: 'TWD', label: 'TWD (NT$) \u2014 Taiwan Dollar' },
      { value: 'ILS', label: 'ILS (\u20aa) \u2014 Israeli Shekel' },
      { value: 'JOD', label: 'JOD (JD) \u2014 Jordanian Dinar' },
      { value: 'LBP', label: 'LBP (\u0644.\u0644) \u2014 Lebanese Pound' },
      { value: 'PKR', label: 'PKR (\u20a8) \u2014 Pakistani Rupee' },
      { value: 'BDT', label: 'BDT (\u09f3) \u2014 Bangladeshi Taka' },
      { value: 'LKR', label: 'LKR (Rs) \u2014 Sri Lankan Rupee' },
    ],
  },
  {
    group: 'Africa',
    options: [
      { value: 'ZAR', label: 'ZAR (R) \u2014 South African Rand' },
      { value: 'EGP', label: 'EGP (E\u00a3) \u2014 Egyptian Pound' },
      { value: 'NGN', label: 'NGN (\u20a6) \u2014 Nigerian Naira' },
      { value: 'KES', label: 'KES (KSh) \u2014 Kenyan Shilling' },
      { value: 'MAD', label: 'MAD (\u062f.\u0645.) \u2014 Moroccan Dirham' },
      { value: 'TND', label: 'TND (DT) \u2014 Tunisian Dinar' },
      { value: 'GHS', label: 'GHS (GH\u20b5) \u2014 Ghanaian Cedi' },
      { value: 'TZS', label: 'TZS (TSh) \u2014 Tanzanian Shilling' },
      { value: 'UGX', label: 'UGX (USh) \u2014 Ugandan Shilling' },
      { value: 'ETB', label: 'ETB (Br) \u2014 Ethiopian Birr' },
    ],
  },
  {
    group: 'Oceania',
    options: [
      { value: 'AUD', label: 'AUD (A$) \u2014 Australian Dollar' },
      { value: 'NZD', label: 'NZD (NZ$) \u2014 New Zealand Dollar' },
      { value: 'FJD', label: 'FJD (FJ$) \u2014 Fijian Dollar' },
    ],
  },
  {
    group: 'Other',
    options: [{ value: '__custom__', label: 'Custom...' }],
  },
];

// ── Languages ─────────────────────────────────────────────────────────────

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'de', label: 'Deutsch' },
  { value: 'fr', label: 'Fran\u00e7ais' },
  { value: 'es', label: 'Espa\u00f1ol' },
  { value: 'it', label: 'Italiano' },
  { value: 'pt', label: 'Portugu\u00eas' },
  { value: 'nl', label: 'Nederlands' },
  { value: 'pl', label: 'Polski' },
  { value: 'cs', label: '\u010ce\u0161tina' },
  { value: 'ru', label: '\u0420\u0443\u0441\u0441\u043a\u0438\u0439' },
  { value: 'tr', label: 'T\u00fcrk\u00e7e' },
  { value: 'ar', label: '\u0627\u0644\u0639\u0631\u0628\u064a\u0629' },
  { value: 'zh', label: '\u4e2d\u6587' },
  { value: 'ja', label: '\u65e5\u672c\u8a9e' },
  { value: 'ko', label: '\ud55c\uad6d\uc5b4' },
  { value: 'hi', label: '\u0939\u093f\u0928\u094d\u0926\u0940' },
  { value: 'th', label: '\u0e44\u0e17\u0e22' },
  { value: 'vi', label: 'Ti\u1ebfng Vi\u1ec7t' },
  { value: 'id', label: 'Bahasa Indonesia' },
  { value: 'sv', label: 'Svenska' },
  { value: 'no', label: 'Norsk' },
  { value: 'da', label: 'Dansk' },
  { value: 'fi', label: 'Suomi' },
];

// ── Component ─────────────────────────────────────────────────────────────

export function CreateProjectPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [form, setForm] = useState<CreateProjectData>({
    name: '',
    description: '',
    region: '',
    classification_standard: '',
    currency: '',
    locale: 'en',
  });

  // Custom value inputs shown when "__custom__" is selected
  const [customRegion, setCustomRegion] = useState('');
  const [customStandard, setCustomStandard] = useState('');
  const [customCurrency, setCustomCurrency] = useState('');
  const [regionalFactor, setRegionalFactor] = useState<number>(1.0);

  const mutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('toasts.project_created', { defaultValue: 'Project created' }) });
      navigate(`/projects/${project.id}`);
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;

    // Resolve custom values before submitting
    const data: CreateProjectData = {
      ...form,
      region: form.region === '__custom__' ? customRegion : form.region,
      classification_standard:
        form.classification_standard === '__custom__'
          ? customStandard
          : form.classification_standard,
      currency: form.currency === '__custom__' ? customCurrency : form.currency,
      regional_factor: regionalFactor,
    };

    mutation.mutate(data);
  };

  const set = (field: keyof CreateProjectData, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  return (
    <div className="max-w-2xl mx-auto animate-fade-in">
      <Breadcrumb
        className="mb-4"
        items={[
          { label: t('projects.title', 'Projects'), to: '/projects' },
          { label: t('projects.new_project', 'New Project') },
        ]}
      />

      <h1 className="text-2xl font-bold text-content-primary mb-4">
        {t('projects.new_project')}
      </h1>

      {/* Field-level hints */}
      <InfoHint className="mb-6" text={t('projects.create_hint', { defaultValue: 'Region determines available cost databases and VAT rates. Classification standard defines the cost structure: DIN 276 for DACH countries, NRM for UK, MasterFormat for US/Canada, UniFormat for Oceania. Currency sets all pricing in the BOQ.' })} />

      <Card>
        <form onSubmit={handleSubmit} className="space-y-5">
          <Input
            label={t('projects.project_name')}
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder={t('projects.project_name_placeholder', {
              defaultValue: 'e.g. Office Tower Downtown',
            })}
            required
            autoFocus
          />

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('projects.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder={t('projects.description_placeholder', {
                defaultValue: 'Project description, scope, notes...',
              })}
              rows={3}
              className="w-full rounded-lg border border-border px-3 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary resize-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <GroupedSelectField
                label={t('projects.region', { defaultValue: 'Region' })}
                value={form.region ?? ''}
                groups={REGION_GROUPS}
                placeholder={t('projects.select_region', { defaultValue: '-- Select region --' })}
                onChange={(v) => set('region', v)}
              />
              {form.region === '__custom__' && (
                <input
                  type="text"
                  value={customRegion}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setCustomRegion(e.target.value)}
                  placeholder={t('projects.enter_custom_region', {
                    defaultValue: 'Enter custom region...',
                  })}
                  className="mt-2 h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                />
              )}
            </div>
            <div>
              <GroupedSelectField
                label={t('projects.classification_standard', {
                  defaultValue: 'Classification Standard',
                })}
                value={form.classification_standard ?? ''}
                groups={STANDARD_GROUPS}
                placeholder={t('projects.select_standard', {
                  defaultValue: '-- Select standard --',
                })}
                onChange={(v) => set('classification_standard', v)}
              />
              {form.classification_standard === '__custom__' && (
                <input
                  type="text"
                  value={customStandard}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setCustomStandard(e.target.value)}
                  placeholder={t('projects.enter_custom_standard', {
                    defaultValue: 'Enter custom standard...',
                  })}
                  className="mt-2 h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                />
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <GroupedSelectField
                label={t('projects.currency', { defaultValue: 'Currency' })}
                value={form.currency ?? ''}
                groups={CURRENCY_GROUPS}
                placeholder={t('projects.select_currency', {
                  defaultValue: '-- Select currency --',
                })}
                onChange={(v) => set('currency', v)}
              />
              {form.currency === '__custom__' && (
                <input
                  type="text"
                  value={customCurrency}
                  onChange={(e: ChangeEvent<HTMLInputElement>) => setCustomCurrency(e.target.value)}
                  placeholder={t('projects.enter_custom_currency', {
                    defaultValue: 'e.g. XAF',
                  })}
                  maxLength={10}
                  className="mt-2 h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                />
              )}
            </div>
            <SelectField
              label={t('projects.language', { defaultValue: 'Language' })}
              value={form.locale ?? 'en'}
              options={LANGUAGES}
              onChange={(v) => set('locale', v)}
            />
          </div>

          {/* Regional price coefficient */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-secondary">
              {t('projects.regional_factor', { defaultValue: 'Regional Factor' })}
            </label>
            <input
              type="number"
              min="0.5"
              max="2.0"
              step="0.01"
              value={regionalFactor}
              onChange={(e) => setRegionalFactor(parseFloat(e.target.value) || 1.0)}
              placeholder="1.00"
              className="h-10 w-full max-w-[200px] rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary tabular-nums placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            />
            <p className="mt-1 text-xs text-content-tertiary">
              {t('projects.regional_factor_hint', { defaultValue: 'Multiply all rates by this factor (e.g. Munich = 1.12, Berlin = 1.05)' })}
            </p>
          </div>

          {mutation.error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {(mutation.error as Error).message || t('projects.create_error', { defaultValue: 'Failed to create project' })}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="secondary" type="button" onClick={() => navigate('/projects')}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={mutation.isPending}>
              {t('common.create')}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

// ── Grouped Select (with <optgroup>) ──────────────────────────────────────

function GroupedSelectField({
  label,
  value,
  groups,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  groups: OptionGroup[];
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-content-primary">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none"
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {groups.map((g) => (
          <optgroup key={g.group} label={t(`projects.group_${g.group.toLowerCase().replace(/[^a-z0-9]/g, '_')}`, { defaultValue: g.group })}>
            {g.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

// ── Flat Select (for language etc.) ───────────────────────────────────────

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-content-primary">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
