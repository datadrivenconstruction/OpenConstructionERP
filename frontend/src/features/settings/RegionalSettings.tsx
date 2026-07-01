/**
 * RegionalSettings — regional preferences panel for the Settings page.
 *
 * Shows timezone, measurement system, paper size, date format, number format,
 * and currency. Changes are persisted to the backend via PATCH and updated
 * in the local preferences store for immediate UI effect.
 */

import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Globe, Ruler, FileText, Calendar, Hash, DollarSign, Search, Check } from 'lucide-react';
import clsx from 'clsx';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { apiGet, apiPatch } from '@/shared/lib/api';
import { usePreferencesStore, type MeasurementSystem, type DateFormat, type NumberLocale } from '@/stores/usePreferencesStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  CUSTOM_CURRENCY_SENTINEL,
  normalizeCurrencyCode,
  isValidCurrencyCode,
} from '@/features/projects/currencyGroups';

// ── Static data ──────────────────────────────────────────────────────────────

const TIMEZONES = [
  'UTC',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'Europe/Madrid',
  'Europe/Rome',
  'Europe/Amsterdam',
  'Europe/Brussels',
  'Europe/Vienna',
  'Europe/Zurich',
  'Europe/Warsaw',
  'Europe/Prague',
  'Europe/Stockholm',
  'Europe/Oslo',
  'Europe/Helsinki',
  'Europe/Moscow',
  'Europe/Istanbul',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Bangkok',
  'Asia/Singapore',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Australia/Sydney',
  'Pacific/Auckland',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Toronto',
  'America/Sao_Paulo',
] as const;

const PAPER_SIZES = [
  { value: 'A4', label: 'A4 (210 x 297 mm)' },
  { value: 'A3', label: 'A3 (297 x 420 mm)' },
  { value: 'Letter', label: 'Letter (8.5 x 11 in)' },
  { value: 'Legal', label: 'Legal (8.5 x 14 in)' },
] as const;

const DATE_FORMATS: { value: DateFormat; example: string }[] = [
  { value: 'DD.MM.YYYY', example: '07.04.2026' },
  { value: 'MM/DD/YYYY', example: '04/07/2026' },
  { value: 'YYYY-MM-DD', example: '2026-04-07' },
];

interface NumberFormatOption {
  locale: NumberLocale;
  label: string;
  example: string;
}

const NUMBER_FORMATS: NumberFormatOption[] = [
  { locale: 'de-DE', label: '1.234,56 (DE / ES)', example: '1.234,56' },
  { locale: 'en-US', label: '1,234.56 (US)', example: '1,234.56' },
  { locale: 'fr-FR', label: '1 234,56 (FR)', example: '1 234,56' },
  { locale: 'en-GB', label: '1,234.56 (GB)', example: '1,234.56' },
  { locale: 'ru-RU', label: '1 234,56 (RU)', example: '1 234,56' },
  { locale: 'es-MX', label: '1,234.56 (MX)', example: '1,234.56' },
];

const CURRENCIES = [
  { code: 'EUR', symbol: '\u20AC', name: 'Euro' },
  { code: 'USD', symbol: '$', name: 'US Dollar' },
  { code: 'GBP', symbol: '\u00A3', name: 'British Pound' },
  { code: 'CHF', symbol: 'CHF', name: 'Swiss Franc' },
  { code: 'SEK', symbol: 'kr', name: 'Swedish Krona' },
  { code: 'NOK', symbol: 'kr', name: 'Norwegian Krone' },
  { code: 'DKK', symbol: 'kr', name: 'Danish Krone' },
  { code: 'PLN', symbol: 'z\u0142', name: 'Polish Zloty' },
  { code: 'CZK', symbol: 'K\u010D', name: 'Czech Koruna' },
  { code: 'HUF', symbol: 'Ft', name: 'Hungarian Forint' },
  { code: 'RUB', symbol: '\u20BD', name: 'Russian Ruble' },
  { code: 'TRY', symbol: '\u20BA', name: 'Turkish Lira' },
  { code: 'AED', symbol: 'AED', name: 'UAE Dirham' },
  { code: 'SAR', symbol: 'SAR', name: 'Saudi Riyal' },
  { code: 'INR', symbol: '\u20B9', name: 'Indian Rupee' },
  { code: 'CNY', symbol: '\u00A5', name: 'Chinese Yuan' },
  { code: 'JPY', symbol: '\u00A5', name: 'Japanese Yen' },
  { code: 'KRW', symbol: '\u20A9', name: 'South Korean Won' },
  { code: 'AUD', symbol: 'A$', name: 'Australian Dollar' },
  { code: 'CAD', symbol: 'C$', name: 'Canadian Dollar' },
  { code: 'BRL', symbol: 'R$', name: 'Brazilian Real' },
  { code: 'MXN', symbol: 'MX$', name: 'Mexican Peso' },
  { code: 'SGD', symbol: 'S$', name: 'Singapore Dollar' },
  { code: 'NZD', symbol: 'NZ$', name: 'New Zealand Dollar' },
  // Africa
  { code: 'ZAR', symbol: 'R', name: 'South African Rand' },
  { code: 'NGN', symbol: '₦', name: 'Nigerian Naira' },
  { code: 'EGP', symbol: 'E£', name: 'Egyptian Pound' },
  { code: 'KES', symbol: 'KSh', name: 'Kenyan Shilling' },
  { code: 'GHS', symbol: '₵', name: 'Ghanaian Cedi' },
  { code: 'MAD', symbol: 'DH', name: 'Moroccan Dirham' },
  { code: 'TND', symbol: 'TND', name: 'Tunisian Dinar' },
  { code: 'DZD', symbol: 'DA', name: 'Algerian Dinar' },
  { code: 'ETB', symbol: 'Br', name: 'Ethiopian Birr' },
  { code: 'UGX', symbol: 'USh', name: 'Ugandan Shilling' },
  { code: 'TZS', symbol: 'TSh', name: 'Tanzanian Shilling' },
  { code: 'RWF', symbol: 'FRw', name: 'Rwandan Franc' },
  { code: 'XOF', symbol: 'CFA', name: 'West African CFA Franc' },
  { code: 'XAF', symbol: 'FCFA', name: 'Central African CFA Franc' },
  { code: 'AOA', symbol: 'Kz', name: 'Angolan Kwanza' },
  { code: 'MZN', symbol: 'MT', name: 'Mozambique Metical' },
  { code: 'BWP', symbol: 'P', name: 'Botswana Pula' },
  { code: 'ZMW', symbol: 'ZK', name: 'Zambian Kwacha' },
  { code: 'NAD', symbol: 'N$', name: 'Namibia Dollar' },
  { code: 'MGA', symbol: 'Ar', name: 'Malagasy Ariary' },
] as const;

// ── Backend preferences shape ────────────────────────────────────────────────

interface UserPreferencesResponse {
  timezone?: string;
  measurement_system?: string;
  paper_size?: string;
  date_format?: string;
  number_format?: string;
  // MONEY-BUG FIX: the backend persists the currency under `currency_code`
  // (UserPreferencesUpdate / UserPreferencesResponse / User.currency_code).
  // The FE previously sent/read `currency`, which the backend silently dropped
  // (no extra="forbid"), so the chosen currency never round-tripped and
  // vanished on reload. Use the real wire key so it persists server-side.
  currency_code?: string;
}

// ── Searchable Dropdown ──────────────────────────────────────────────────────

function SearchableSelect<T extends string>({
  value,
  options,
  onChange,
  renderOption,
  placeholder,
}: {
  value: T;
  options: readonly T[] | { value: T; label: string }[];
  onChange: (val: T) => void;
  renderOption?: (opt: T) => string;
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  // Normalize options
  const normalized = useMemo(() => {
    return (options as (T | { value: T; label: string })[]).map((opt) => {
      if (typeof opt === 'string') return { value: opt as T, label: renderOption ? renderOption(opt as T) : (opt as string) };
      return opt as { value: T; label: string };
    });
  }, [options, renderOption]);

  const filtered = useMemo(() => {
    if (!search) return normalized;
    const q = search.toLowerCase();
    return normalized.filter(
      (o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
    );
  }, [normalized, search]);

  const selectedLabel = normalized.find((o) => o.value === value)?.label ?? value;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => { setOpen(!open); setSearch(''); }}
        className={clsx(
          'flex h-9 w-full items-center justify-between rounded-lg border px-3',
          'text-sm text-content-primary bg-surface-primary',
          'transition-all duration-fast ease-oe',
          open
            ? 'border-oe-blue ring-2 ring-oe-blue/20'
            : 'border-border hover:border-content-tertiary',
        )}
      >
        <span className="truncate">{selectedLabel}</span>
        <svg
          className={clsx('h-4 w-4 text-content-tertiary transition-transform', open && 'rotate-180')}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && (
        <>
          {/* Backdrop to close */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-1 w-full rounded-xl border border-border-light bg-surface-elevated shadow-lg overflow-hidden">
            {/* Search input */}
            <div className="px-2 py-1.5 border-b border-border-light">
              <div className="relative">
                <Search
                  size={13}
                  className="absolute left-2 top-1/2 -translate-y-1/2 text-content-quaternary pointer-events-none"
                />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={placeholder}
                  className="w-full rounded-md border border-border-light bg-surface-secondary pl-7 pr-2 py-1 text-xs text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue/40"
                  autoFocus
                />
              </div>
            </div>
            <div className="max-h-48 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <p className="px-3 py-2 text-xs text-content-tertiary text-center">
                  {placeholder}
                </p>
              ) : (
                filtered.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => { onChange(opt.value); setOpen(false); }}
                    className={clsx(
                      'flex w-full items-center gap-2 px-3 py-1.5 text-sm transition-colors',
                      opt.value === value
                        ? 'bg-oe-blue-subtle text-oe-blue-text font-medium'
                        : 'text-content-primary hover:bg-surface-secondary',
                    )}
                  >
                    <span className="truncate flex-1 text-left">{opt.label}</span>
                    {opt.value === value && <Check size={14} className="shrink-0" />}
                  </button>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Toggle Button Group ──────────────────────────────────────────────────────

function ToggleGroup<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (val: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            aria-pressed={active}
            className={clsx(
              'flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-fast',
              active
                ? 'bg-oe-blue-subtle border-2 border-oe-blue text-oe-blue-text'
                : 'border-2 border-border-light text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ── RegionalSettings Component ───────────────────────────────────────────────

export function RegionalSettings({ animationDelay = '0ms' }: { animationDelay?: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const setPreference = usePreferencesStore((s) => s.setPreference);
  const storeCurrency = usePreferencesStore((s) => s.currency);
  const storeMeasurement = usePreferencesStore((s) => s.measurementSystem);
  const storeDateFormat = usePreferencesStore((s) => s.dateFormat);
  const storeNumberLocale = usePreferencesStore((s) => s.numberLocale);

  // Fetch current preferences from backend
  const { data: prefs } = useQuery({
    queryKey: ['user-preferences'],
    queryFn: () => apiGet<UserPreferencesResponse>('/v1/users/me/preferences/'),
    retry: false,
    staleTime: 60_000,
  });

  // Local state — seeded from backend, falls back to store
  const timezone = prefs?.timezone ?? 'UTC';
  const measurementSystem = (prefs?.measurement_system as MeasurementSystem) ?? storeMeasurement;
  const paperSize = prefs?.paper_size ?? 'A4';
  const dateFormat = (prefs?.date_format as DateFormat) ?? storeDateFormat;
  const numberFormat = (prefs?.number_format as NumberLocale) ?? storeNumberLocale;
  // MONEY-BUG FIX: read the persisted server value from `currency_code`
  // (the real backend field) instead of the non-existent `currency`, so a
  // saved currency survives reload. Do NOT hardcode 'EUR' here — fall back to
  // the local store, which carries the user's last-selected currency.
  const currency = prefs?.currency_code ?? storeCurrency;

  // Patch mutation
  const patchMutation = useMutation({
    mutationFn: (update: Partial<UserPreferencesResponse>) =>
      apiPatch<UserPreferencesResponse>('/v1/users/me/preferences/', update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-preferences'] });
      addToast({
        type: 'success',
        title: t('settings.preferences_saved', { defaultValue: 'Preferences saved' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.preferences_error', { defaultValue: 'Failed to save preferences' }),
        message: err.message,
      });
    },
  });

  const handleChange = useCallback(
    (field: keyof UserPreferencesResponse, value: string) => {
      // Update backend
      patchMutation.mutate({ [field]: value });

      // Update local store for immediate UI effect
      switch (field) {
        // MONEY-BUG FIX: the wire field is `currency_code` (backend key); the
        // local Zustand store still uses `currency` / `defaultCurrency`.
        case 'currency_code':
          setPreference('currency', value);
          setPreference('defaultCurrency', value);
          break;
        case 'measurement_system':
          setPreference('measurementSystem', value as MeasurementSystem);
          break;
        case 'date_format':
          setPreference('dateFormat', value as DateFormat);
          break;
        case 'number_format':
          setPreference('numberLocale', value as NumberLocale);
          break;
      }
    },
    [patchMutation, setPreference],
  );

  // Build currency options for SearchableSelect, ending with a "Custom..."
  // entry so an operator whose currency is not in the curated list can still
  // set it as the global default (the backend currency column is free-form).
  const currencyOptions = useMemo(
    () => [
      ...CURRENCIES.map((c) => ({
        value: c.code as string,
        label: `${c.symbol} ${c.code} - ${c.name}`,
      })),
      {
        value: CUSTOM_CURRENCY_SENTINEL,
        label: t('currency_picker.custom_option', { defaultValue: 'Custom...' }),
      },
    ],
    [t],
  );

  // A persisted currency that is not one of the curated codes means the user
  // is on a custom default; reflect that by selecting "Custom..." and seeding
  // the free-text input. Local state keeps the input visible while the field
  // is mid-edit (so an in-progress empty value does not snap back to a preset).
  const currencyIsCustom =
    currency !== '' && !CURRENCIES.some((c) => c.code === currency);
  const [customCurrencyMode, setCustomCurrencyMode] = useState(currencyIsCustom);
  const showCustomCurrency = customCurrencyMode || currencyIsCustom;
  // Edit the free-text code in a local draft and only persist (one PATCH +
  // one toast) on blur / Enter, instead of firing a request per keystroke.
  // While the user has not yet typed (draft is null) the input mirrors the
  // persisted custom currency, so a server-loaded custom code shows correctly
  // even though `currency` arrives after first render.
  const [customCurrencyDraft, setCustomCurrencyDraft] = useState<string | null>(null);
  const customCurrencyValue = customCurrencyDraft ?? (currencyIsCustom ? currency : '');
  const customCurrencyInvalid =
    customCurrencyValue.trim().length > 0 && !isValidCurrencyCode(customCurrencyValue);

  const commitCustomCurrency = useCallback(() => {
    const code = normalizeCurrencyCode(customCurrencyValue);
    if (code && code !== currency) handleChange('currency_code', code);
  }, [customCurrencyValue, currency, handleChange]);

  return (
    <Card className="animate-card-in" style={{ animationDelay }}>
      <CardHeader
        title={t('settings.regional_title', { defaultValue: 'Regional Settings' })}
        subtitle={t('settings.regional_subtitle', {
          defaultValue: 'Configure timezone, units, formats, and currency',
        })}
      />
      <CardContent>
        <div className="space-y-5">
          {/* Timezone */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <Globe size={14} className="text-content-tertiary" />
              {t('settings.timezone', { defaultValue: 'Timezone' })}
            </label>
            <SearchableSelect
              value={timezone}
              options={TIMEZONES as unknown as readonly string[]}
              onChange={(val) => handleChange('timezone', val)}
              renderOption={(tz) => tz.replace(/_/g, ' ')}
              placeholder={t('common.search', { defaultValue: 'Search...' })}
            />
          </div>

          {/* Measurement System */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <Ruler size={14} className="text-content-tertiary" />
              {t('settings.measurement_system', { defaultValue: 'Measurement System' })}
            </label>
            <ToggleGroup
              value={measurementSystem}
              options={[
                {
                  value: 'metric' as MeasurementSystem,
                  label: t('settings.metric', { defaultValue: 'Metric (m, kg)' }),
                },
                {
                  value: 'imperial' as MeasurementSystem,
                  label: t('settings.imperial', { defaultValue: 'Imperial (ft, lb)' }),
                },
              ]}
              onChange={(val) => handleChange('measurement_system', val)}
            />
          </div>

          {/* Paper Size */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <FileText size={14} className="text-content-tertiary" />
              {t('settings.paper_size', { defaultValue: 'Paper Size' })}
            </label>
            <ToggleGroup
              value={paperSize}
              options={PAPER_SIZES.map((p) => ({ value: p.value, label: p.label }))}
              onChange={(val) => handleChange('paper_size', val)}
            />
          </div>

          {/* Date Format */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <Calendar size={14} className="text-content-tertiary" />
              {t('settings.date_format', { defaultValue: 'Date Format' })}
            </label>
            <ToggleGroup
              value={dateFormat}
              options={DATE_FORMATS.map((f) => ({
                value: f.value,
                label: f.example,
              }))}
              onChange={(val) => handleChange('date_format', val)}
            />
          </div>

          {/* Number Format */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <Hash size={14} className="text-content-tertiary" />
              {t('settings.number_format', { defaultValue: 'Number Format' })}
            </label>
            <ToggleGroup
              value={numberFormat}
              options={NUMBER_FORMATS.map((f) => ({
                value: f.locale,
                label: f.label,
              }))}
              onChange={(val) => handleChange('number_format', val)}
            />
          </div>

          {/* Currency */}
          {/* MONEY-BUG FIX: handleChange uses the real backend wire key
              `currency_code` so the chosen currency is persisted server-side
              and survives reload (was `currency`, silently dropped by the
              backend because UserPreferencesUpdate only declares currency_code). */}
          <div>
            <label className="flex items-center gap-2 text-sm font-medium text-content-primary mb-1.5">
              <DollarSign size={14} className="text-content-tertiary" />
              {t('settings.currency', { defaultValue: 'Currency' })}
            </label>
            <SearchableSelect
              value={showCustomCurrency ? CUSTOM_CURRENCY_SENTINEL : currency}
              options={currencyOptions}
              onChange={(val) => {
                if (val === CUSTOM_CURRENCY_SENTINEL) {
                  // Reveal the free-text input; only persist once the user types
                  // a code (avoid writing the literal sentinel to the backend).
                  setCustomCurrencyMode(true);
                  setCustomCurrencyDraft(currencyIsCustom ? currency : '');
                  return;
                }
                setCustomCurrencyMode(false);
                setCustomCurrencyDraft(null);
                handleChange('currency_code', val);
              }}
              placeholder={t('common.search', { defaultValue: 'Search...' })}
            />
            {showCustomCurrency && (
              <>
                <input
                  type="text"
                  value={customCurrencyValue}
                  onChange={(e) => setCustomCurrencyDraft(normalizeCurrencyCode(e.target.value))}
                  onBlur={commitCustomCurrency}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      commitCustomCurrency();
                    }
                  }}
                  placeholder={t('currency_picker.custom_placeholder', { defaultValue: 'e.g. XAF' })}
                  maxLength={10}
                  aria-label={t('currency_picker.custom_aria', {
                    defaultValue: 'Custom currency code',
                  })}
                  aria-invalid={customCurrencyInvalid}
                  className={clsx(
                    'mt-2 h-10 w-full rounded-lg border bg-surface-primary px-3 text-sm text-content-primary uppercase placeholder:normal-case placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:border-transparent',
                    customCurrencyInvalid
                      ? 'border-amber-400 focus:ring-amber-400'
                      : 'border-border focus:ring-oe-blue',
                  )}
                />
                {customCurrencyInvalid && (
                  <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">
                    {t('currency_picker.custom_hint', {
                      defaultValue: 'Use a 3-letter ISO code (e.g. XAF) so amounts format correctly.',
                    })}
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
