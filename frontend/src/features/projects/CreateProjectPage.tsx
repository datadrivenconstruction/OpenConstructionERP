import { useState, useEffect, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  X, FolderPlus, AlertTriangle, MapPin, Map as MapIcon, CloudSun,
  Check, ChevronLeft, ChevronRight, Layers,
} from 'lucide-react';
import { Button, Input, InfoHint } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useWidgetSettingsStore } from '@/stores/useWidgetSettingsStore';
import {
  projectsApi,
  type CreateProjectData,
  type Project,
  type WizardPreset,
  type ProfileSpec,
} from './api';

// ── Regions (grouped by continent) ────────────────────────────────────────

export interface OptionGroup {
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

// Project region → backend REGION_PACK key (scoring is a strict dict
// lookup with no aliasing, so we must hand it an exact pack key or ''
// — an unknown region simply contributes 0 to the region axis, which
// is a graceful no-op, not an error).
const REGION_TO_PACK: Record<string, string> = {
  DACH: 'dach',
  UK: 'uk',
  US: 'us',
  Canada: 'us',
  Russia: 'russia_cis',
  Brazil: 'latam',
  Mexico: 'latam',
  LatinAmerica: 'latam',
  MiddleEast: 'mena',
  GulfStates: 'mena',
  NorthAfrica: 'mena',
  China: 'asia_pacific',
  Japan: 'asia_pacific',
  Korea: 'asia_pacific',
  SoutheastAsia: 'asia_pacific',
  Australia: 'asia_pacific',
  NewZealand: 'asia_pacific',
  India: 'india',
};

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

export const CURRENCY_GROUPS: OptionGroup[] = [
  {
    group: 'Europe',
    options: [
      { value: 'EUR', label: 'EUR (€) — Euro' },
      { value: 'GBP', label: 'GBP (£) — British Pound' },
      { value: 'CHF', label: 'CHF (Fr.) — Swiss Franc' },
      { value: 'SEK', label: 'SEK (kr) — Swedish Krona' },
      { value: 'NOK', label: 'NOK (kr) — Norwegian Krone' },
      { value: 'DKK', label: 'DKK (kr) — Danish Krone' },
      { value: 'PLN', label: 'PLN (zł) — Polish Zloty' },
      { value: 'CZK', label: 'CZK (Kč) — Czech Koruna' },
      { value: 'TRY', label: 'TRY (₺) — Turkish Lira' },
      { value: 'RUB', label: 'RUB (₽) — Russian Ruble' },
      { value: 'HUF', label: 'HUF (Ft) — Hungarian Forint' },
      { value: 'RON', label: 'RON (lei) — Romanian Leu' },
      { value: 'BGN', label: 'BGN (лв) — Bulgarian Lev' },
      { value: 'HRK', label: 'HRK (kn) — Croatian Kuna' },
      { value: 'ISK', label: 'ISK (kr) — Icelandic Krona' },
    ],
  },
  {
    group: 'Americas',
    options: [
      { value: 'USD', label: 'USD ($) — US Dollar' },
      { value: 'CAD', label: 'CAD (C$) — Canadian Dollar' },
      { value: 'BRL', label: 'BRL (R$) — Brazilian Real' },
      { value: 'MXN', label: 'MXN (Mex$) — Mexican Peso' },
      { value: 'ARS', label: 'ARS (AR$) — Argentine Peso' },
      { value: 'CLP', label: 'CLP (CL$) — Chilean Peso' },
      { value: 'PEN', label: 'PEN (S/) — Peruvian Sol' },
      { value: 'COP', label: 'COP (COL$) — Colombian Peso' },
    ],
  },
  {
    group: 'Asia & Middle East',
    options: [
      { value: 'CNY', label: 'CNY (¥) — Chinese Yuan' },
      { value: 'JPY', label: 'JPY (¥) — Japanese Yen' },
      { value: 'KRW', label: 'KRW (₩) — South Korean Won' },
      { value: 'INR', label: 'INR (₹) — Indian Rupee' },
      { value: 'AED', label: 'AED (د.إ) — UAE Dirham' },
      { value: 'SAR', label: 'SAR (﷼) — Saudi Riyal' },
      { value: 'QAR', label: 'QAR (﷼) — Qatari Riyal' },
      { value: 'BHD', label: 'BHD (BD) — Bahraini Dinar' },
      { value: 'KWD', label: 'KWD (د.ك) — Kuwaiti Dinar' },
      { value: 'OMR', label: 'OMR (ر.ع.) — Omani Rial' },
      { value: 'SGD', label: 'SGD (S$) — Singapore Dollar' },
      { value: 'MYR', label: 'MYR (RM) — Malaysian Ringgit' },
      { value: 'THB', label: 'THB (฿) — Thai Baht' },
      { value: 'IDR', label: 'IDR (Rp) — Indonesian Rupiah' },
      { value: 'PHP', label: 'PHP (₱) — Philippine Peso' },
      { value: 'VND', label: 'VND (₫) — Vietnamese Dong' },
      { value: 'HKD', label: 'HKD (HK$) — Hong Kong Dollar' },
      { value: 'TWD', label: 'TWD (NT$) — Taiwan Dollar' },
      { value: 'ILS', label: 'ILS (₪) — Israeli Shekel' },
      { value: 'JOD', label: 'JOD (JD) — Jordanian Dinar' },
      { value: 'LBP', label: 'LBP (ل.ل) — Lebanese Pound' },
      { value: 'PKR', label: 'PKR (₨) — Pakistani Rupee' },
      { value: 'BDT', label: 'BDT (৳) — Bangladeshi Taka' },
      { value: 'LKR', label: 'LKR (Rs) — Sri Lankan Rupee' },
    ],
  },
  {
    group: 'Africa',
    options: [
      { value: 'ZAR', label: 'ZAR (R) — South African Rand' },
      { value: 'EGP', label: 'EGP (E£) — Egyptian Pound' },
      { value: 'NGN', label: 'NGN (₦) — Nigerian Naira' },
      { value: 'KES', label: 'KES (KSh) — Kenyan Shilling' },
      { value: 'MAD', label: 'MAD (د.م.) — Moroccan Dirham' },
      { value: 'TND', label: 'TND (DT) — Tunisian Dinar' },
      { value: 'GHS', label: 'GHS (GH₵) — Ghanaian Cedi' },
      { value: 'TZS', label: 'TZS (TSh) — Tanzanian Shilling' },
      { value: 'UGX', label: 'UGX (USh) — Ugandan Shilling' },
      { value: 'ETB', label: 'ETB (Br) — Ethiopian Birr' },
    ],
  },
  {
    group: 'Oceania',
    options: [
      { value: 'AUD', label: 'AUD (A$) — Australian Dollar' },
      { value: 'NZD', label: 'NZD (NZ$) — New Zealand Dollar' },
      { value: 'FJD', label: 'FJD (FJ$) — Fijian Dollar' },
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
  { value: 'fr', label: 'Français' },
  { value: 'es', label: 'Español' },
  { value: 'it', label: 'Italiano' },
  { value: 'pt', label: 'Português' },
  { value: 'nl', label: 'Nederlands' },
  { value: 'pl', label: 'Polski' },
  { value: 'cs', label: 'Čeština' },
  { value: 'ru', label: 'Русский' },
  { value: 'tr', label: 'Türkçe' },
  { value: 'ar', label: 'العربية' },
  { value: 'zh', label: '中文' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'th', label: 'ไทย' },
  { value: 'vi', label: 'Tiếng Việt' },
  { value: 'id', label: 'Bahasa Indonesia' },
  { value: 'sv', label: 'Svenska' },
  { value: 'no', label: 'Norsk' },
  { value: 'da', label: 'Dansk' },
  { value: 'fi', label: 'Suomi' },
];

// ── Profile scoring axes (valid values mirror the backend) ────────────────

const ACTIVITIES = [
  'bim_quality_check', 'cost_estimation', 'tender_preparation',
  'construction_execution', 'property_development', 'site_management',
  'consulting', 'facility_management',
];
const PHASES = ['concept', 'design', 'tender', 'procurement', 'construction', 'handover'];
const ROLES = [
  'client_owner', 'general_contractor', 'bim_consultant', 'bim_manager',
  'designer_architect', 'subcontractor', 'cost_engineer', 'developer',
];
const SIZES = ['small', 'medium', 'large', 'enterprise'];

// Sensible activity/phase defaults per preset so a user who just picks a
// preset and clicks through still gets a well-scored profile. These only
// seed the multi-selects; the user can change anything.
const PRESET_DEFAULTS: Record<string, { activity: string[]; phases: string[] }> = {
  bim_quality_check: { activity: ['bim_quality_check'], phases: ['design'] },
  cost_estimation_only: { activity: ['cost_estimation'], phases: ['design', 'tender'] },
  tender_preparation: { activity: ['tender_preparation'], phases: ['tender', 'procurement'] },
  full_construction_lifecycle: {
    activity: ['cost_estimation', 'construction_execution'],
    phases: ['concept', 'design', 'tender', 'procurement', 'construction', 'handover'],
  },
  property_development: {
    activity: ['property_development'],
    phases: ['concept', 'design', 'construction'],
  },
  site_management: { activity: ['site_management'], phases: ['construction', 'handover'] },
  bim_consulting: { activity: ['consulting', 'bim_quality_check'], phases: ['design'] },
  facility_management: { activity: ['facility_management'], phases: ['handover'] },
  custom: { activity: [], phases: [] },
};

type PresetAxes = { activity: string[]; phases: string[] };
const NO_AXES: PresetAxes = { activity: [], phases: [] };
// Initial wizard default — resolved through the same guarded lookup
// as runtime preset changes so strict index access stays sound.
const INITIAL_AXES: PresetAxes =
  PRESET_DEFAULTS.full_construction_lifecycle ?? NO_AXES;

const STEP_COUNT = 5;

// ── Modal ─────────────────────────────────────────────────────────────────

interface CreateProjectModalProps {
  open: boolean;
  onClose: () => void;
}

export function CreateProjectModal({ open, onClose }: CreateProjectModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [step, setStep] = useState(1);

  const [form, setForm] = useState<CreateProjectData>({
    name: '',
    description: '',
    region: '',
    classification_standard: '',
    currency: '',
    locale: 'en',
  });

  const [customRegion, setCustomRegion] = useState('');
  const [customStandard, setCustomStandard] = useState('');
  const [customCurrency, setCustomCurrency] = useState('');
  const [regionalFactor, setRegionalFactor] = useState<number>(1.0);
  const [duplicateConfirmed, setDuplicateConfirmed] = useState(false);

  // Profile (Slice 1) answers
  const [preset, setPreset] = useState('full_construction_lifecycle');
  const [size, setSize] = useState('medium');
  const [role, setRole] = useState('general_contractor');
  const [activity, setActivity] = useState<string[]>(INITIAL_AXES.activity);
  const [phases, setPhases] = useState<string[]>(INITIAL_AXES.phases);
  const [focusMode, setFocusMode] = useState(true);

  // Address — assembled into the JSON `address` object on submit.
  const [addressStreet, setAddressStreet] = useState('');
  const [addressCity, setAddressCity] = useState('');
  const [addressCountry, setAddressCountry] = useState('');
  const [addressPostal, setAddressPostal] = useState('');

  const mapEnabled = useWidgetSettingsStore((s) => s.projectMapEnabled);
  const weatherEnabled = useWidgetSettingsStore((s) => s.projectWeatherEnabled);
  const toggleMap = useWidgetSettingsStore((s) => s.toggleProjectMap);
  const toggleWeather = useWidgetSettingsStore((s) => s.toggleProjectWeather);

  // Reset everything when the modal opens
  useEffect(() => {
    if (open) {
      setStep(1);
      setForm({ name: '', description: '', region: '', classification_standard: '', currency: '', locale: 'en' });
      setCustomRegion('');
      setCustomStandard('');
      setCustomCurrency('');
      setRegionalFactor(1.0);
      setDuplicateConfirmed(false);
      setPreset('full_construction_lifecycle');
      setSize('medium');
      setRole('general_contractor');
      setActivity(INITIAL_AXES.activity);
      setPhases(INITIAL_AXES.phases);
      setFocusMode(true);
      setAddressStreet('');
      setAddressCity('');
      setAddressCountry('');
      setAddressPostal('');
    }
  }, [open]);

  const { data: existingProjects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    enabled: open,
    staleTime: 5 * 60_000,
  });

  const {
    data: presets = [],
    isLoading: presetsLoading,
    isError: presetsError,
  } = useQuery<WizardPreset[]>({
    queryKey: ['wizard-presets'],
    queryFn: projectsApi.wizardPresets,
    enabled: open,
    staleTime: 30 * 60_000,
  });

  const trimmedName = form.name.trim();
  const duplicateExists =
    trimmedName.length > 0 &&
    existingProjects.some(
      (p) => p.name.trim().toLowerCase() === trimmedName.toLowerCase(),
    );

  useEffect(() => {
    setDuplicateConfirmed(false);
  }, [trimmedName]);

  // When the preset changes, re-seed the activity/phase multi-selects with
  // that preset's sensible defaults (the user can still tweak them).
  const choosePreset = (id: string) => {
    setPreset(id);
    const d = PRESET_DEFAULTS[id];
    if (d) {
      setActivity(d.activity);
      setPhases(d.phases);
    }
  };

  const selectedPreset = presets.find((p) => p.id === preset);

  const buildSpec = (): ProfileSpec => ({
    preset,
    activity,
    phases,
    role,
    size,
    region: REGION_TO_PACK[form.region ?? ''] ?? '',
    language: form.locale || 'en',
    extensions_enabled: [],
    focus_mode_enabled: focusMode,
    setup_completion: { wizard: 'slice2', completed_at: new Date().toISOString() },
    manual_overrides: {},
  });

  const mutation = useMutation({
    mutationFn: async () => {
      const addressParts = {
        street: addressStreet.trim() || null,
        city: addressCity.trim() || null,
        country: addressCountry.trim() || null,
        postal_code: addressPostal.trim() || null,
      };
      const hasAnyAddress = Object.values(addressParts).some((v) => !!v);

      const data: CreateProjectData = {
        ...form,
        region: form.region === '__custom__' ? customRegion : form.region,
        classification_standard:
          form.classification_standard === '__custom__'
            ? customStandard
            : form.classification_standard,
        currency: form.currency === '__custom__' ? customCurrency : form.currency,
        regional_factor: regionalFactor,
        address: hasAnyAddress ? addressParts : null,
      };

      const project = await projectsApi.create(data);
      // Best-effort profile apply — a failure here must not lose the
      // already-created project; we surface a soft warning instead.
      try {
        await projectsApi.applyProfile(project.id, buildSpec());
      } catch {
        addToast({
          type: 'warning',
          title: t('project_wizard.profile_apply_failed', {
            defaultValue: 'Project created, but the module setup could not be applied — you can re-run it from Project Settings.',
          }),
        });
      }
      return project;
    },
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({ type: 'success', title: t('toasts.project_created', { defaultValue: 'Project created successfully' }) });
      onClose();
      navigate(`/projects/${project.id}`);
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.project_create_failed', { defaultValue: 'Failed to create project' }), message: error.message });
    },
  });

  const set = (field: keyof CreateProjectData, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const toggleIn = (
    list: string[],
    val: string,
    setter: (v: string[]) => void,
  ) => setter(list.includes(val) ? list.filter((x) => x !== val) : [...list, val]);

  if (!open) return null;

  // Per-step gate for the Next button.
  const canAdvance = (() => {
    if (step === 1) {
      if (!trimmedName) return false;
      if (duplicateExists && !duplicateConfirmed) return false;
      return true;
    }
    if (step === 3) return !!preset;
    return true;
  })();

  const isLast = step === STEP_COUNT;

  const next = () => {
    if (step === 1 && duplicateExists && !duplicateConfirmed) {
      setDuplicateConfirmed(true);
      return;
    }
    if (!isLast) setStep((s) => Math.min(STEP_COUNT, s + 1));
  };
  const back = () => setStep((s) => Math.max(1, s - 1));

  const STEP_TITLES = [
    t('project_wizard.step_basics', { defaultValue: 'Basics' }),
    t('project_wizard.step_region', { defaultValue: 'Region & currency' }),
    t('project_wizard.step_type', { defaultValue: 'Project type' }),
    t('project_wizard.step_scope', { defaultValue: 'Scope' }),
    t('project_wizard.step_review', { defaultValue: 'Site & review' }),
  ];

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
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue/10">
              <FolderPlus size={20} className="text-oe-blue" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('projects.new_project', { defaultValue: 'New Project' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('project_wizard.step_of', {
                  defaultValue: 'Step {{n}} of {{total}} · {{title}}',
                  n: step, total: STEP_COUNT, title: STEP_TITLES[step - 1],
                })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Stepper — grid-cols-N guarantees equal, non-collapsing
            columns (a nested flex-1 circle + flex-1 connector layout
            shrinks the completed circles to ~0 on a narrow modal). */}
        <div className="px-6 pb-4 shrink-0">
          <div className="relative">
            {/* neutral track behind the dots — the dots themselves carry
                all progress state, so no same-colour camouflage. */}
            <div className="absolute left-3 right-3 top-1/2 -translate-y-1/2 h-px bg-border-light" />
            <div
              className="relative grid"
              style={{ gridTemplateColumns: `repeat(${STEP_COUNT}, minmax(0, 1fr))` }}
            >
              {Array.from({ length: STEP_COUNT }, (_, i) => i + 1).map((s) => (
                <div key={s} className="flex justify-center">
                  <div
                    className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ring-4 ring-surface-elevated transition-colors ${
                      s < step
                        ? 'bg-oe-blue text-white'
                        : s === step
                          ? 'bg-oe-blue text-white ring-oe-blue/25'
                          : 'bg-surface-secondary text-content-tertiary border border-border-light'
                    }`}
                  >
                    {s < step ? <Check size={13} /> : s}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Body — scrollable */}
        <div className="overflow-y-auto px-6 pb-6 flex-1">
          {/* Step 1 — Basics */}
          {step === 1 && (
            <div className="space-y-4">
              <InfoHint text={t('project_wizard.basics_hint', { defaultValue: 'Give the project a clear, unique name. You can change everything later in Project Settings.' })} />
              <Input
                label={t('projects.project_name')}
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder={t('projects.project_name_placeholder', { defaultValue: 'e.g. Office Tower Downtown' })}
                required
                autoFocus
              />
              {duplicateExists && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 px-3 py-2 -mt-2">
                  <AlertTriangle size={16} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                  <div className="text-xs">
                    <p className="font-medium text-amber-900 dark:text-amber-200">
                      {t('projects.duplicate_name_warning', { defaultValue: 'A project with this name already exists.' })}
                    </p>
                    <p className="text-amber-800 dark:text-amber-300 mt-0.5">
                      {duplicateConfirmed
                        ? t('projects.duplicate_name_confirm_again', { defaultValue: 'Click Next again to proceed anyway.' })
                        : t('projects.duplicate_name_confirm_hint', { defaultValue: 'Change the name, or click Next again to proceed anyway.' })}
                    </p>
                  </div>
                </div>
              )}
              <div>
                <label className="text-sm font-medium text-content-primary block mb-1.5">
                  {t('projects.description', { defaultValue: 'Description' })}
                </label>
                <textarea
                  value={form.description}
                  onChange={(e) => set('description', e.target.value)}
                  placeholder={t('projects.description_placeholder', { defaultValue: 'Project description, scope, notes...' })}
                  rows={3}
                  className="w-full rounded-lg border border-border px-3 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary resize-none"
                />
              </div>
            </div>
          )}

          {/* Step 2 — Region & currency */}
          {step === 2 && (
            <div className="space-y-4">
              <InfoHint text={t('projects.create_hint', { defaultValue: 'Region determines available cost databases and VAT rates. Classification standard defines the cost-structure schema for your BOQ. Currency sets all pricing in the BOQ.' })} />
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
                      placeholder={t('projects.enter_custom_region', { defaultValue: 'Enter custom region...' })}
                      className="mt-2 h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  )}
                </div>
                <div>
                  <GroupedSelectField
                    label={t('projects.classification_standard', { defaultValue: 'Classification Standard' })}
                    value={form.classification_standard ?? ''}
                    groups={STANDARD_GROUPS}
                    placeholder={t('projects.select_standard', { defaultValue: '-- Select standard --' })}
                    onChange={(v) => set('classification_standard', v)}
                  />
                  {form.classification_standard === '__custom__' && (
                    <input
                      type="text"
                      value={customStandard}
                      onChange={(e: ChangeEvent<HTMLInputElement>) => setCustomStandard(e.target.value)}
                      placeholder={t('projects.enter_custom_standard', { defaultValue: 'Enter custom standard...' })}
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
                    placeholder={t('projects.select_currency', { defaultValue: '-- Select currency --' })}
                    onChange={(v) => set('currency', v)}
                  />
                  {form.currency === '__custom__' && (
                    <input
                      type="text"
                      value={customCurrency}
                      onChange={(e: ChangeEvent<HTMLInputElement>) => setCustomCurrency(e.target.value)}
                      placeholder={t('projects.enter_custom_currency', { defaultValue: 'e.g. XAF' })}
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
                  {t('projects.regional_factor_hint', { defaultValue: 'Multiply all rates by this factor (e.g. 1.12 = +12% over base).' })}
                </p>
              </div>
            </div>
          )}

          {/* Step 3 — Project type (preset) */}
          {step === 3 && (
            <div className="space-y-3">
              <InfoHint text={t('project_wizard.type_hint', { defaultValue: 'Pick the closest match. This pre-selects the modules and route for your project — nothing is locked, you can refine on the next step.' })} />
              {presetsLoading && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div
                      key={i}
                      className="rounded-xl border border-border-light bg-surface-primary p-3 animate-pulse"
                    >
                      <div className="h-3.5 w-2/3 rounded bg-surface-secondary" />
                      <div className="mt-2 h-2.5 w-full rounded bg-surface-secondary/70" />
                      <div className="mt-1.5 h-2.5 w-1/3 rounded bg-surface-secondary/50" />
                    </div>
                  ))}
                </div>
              )}
              {presetsError && !presetsLoading && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 px-3 py-2 text-xs">
                  <AlertTriangle size={15} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                  <span className="text-amber-800 dark:text-amber-300">
                    {t('project_wizard.presets_error', { defaultValue: 'Couldn’t load project types. You can still continue with the default and refine modules later in Project Settings.' })}
                  </span>
                </div>
              )}
              <div
                className={`grid grid-cols-1 sm:grid-cols-2 gap-2.5 ${
                  presetsLoading || presetsError ? 'hidden' : ''
                }`}
              >
                {presets.map((p) => {
                  const selected = p.id === preset;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => choosePreset(p.id)}
                      className={`text-left rounded-xl border p-3 transition-all ${
                        selected
                          ? 'border-oe-blue bg-oe-blue/5 ring-1 ring-oe-blue'
                          : 'border-border-light hover:border-content-tertiary bg-surface-primary'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-content-primary">
                          {t(p.label_key, { defaultValue: p.label_en })}
                        </span>
                        {selected && <Check size={15} className="text-oe-blue shrink-0" />}
                      </div>
                      <p className="text-xs text-content-tertiary mt-1 leading-snug">
                        {p.blurb_en}
                      </p>
                      <p className="text-[11px] text-content-quaternary mt-1.5 flex items-center gap-1">
                        <Layers size={11} />
                        {t('project_wizard.module_count', {
                          defaultValue: '{{n}} modules',
                          n: p.module_count,
                        })}
                      </p>
                    </button>
                  );
                })}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                <SelectField
                  label={t('project_wizard.size', { defaultValue: 'Project size' })}
                  value={size}
                  options={SIZES.map((s) => ({
                    value: s,
                    label: t(`project_wizard.size_opt.${s}`, { defaultValue: cap(s) }),
                  }))}
                  onChange={setSize}
                />
                <SelectField
                  label={t('project_wizard.role', { defaultValue: 'Your role' })}
                  value={role}
                  options={ROLES.map((r) => ({
                    value: r,
                    label: t(`project_wizard.role_opt.${r}`, { defaultValue: humanize(r) }),
                  }))}
                  onChange={setRole}
                />
              </div>
            </div>
          )}

          {/* Step 4 — Scope (activity / phases / focus) */}
          {step === 4 && (
            <div className="space-y-5">
              <InfoHint text={t('project_wizard.scope_hint', { defaultValue: 'These refine which modules are emphasised. Defaults come from the project type you picked — adjust only if needed.' })} />
              <div>
                <p className="text-sm font-semibold text-content-primary mb-2">
                  {t('project_wizard.activities', { defaultValue: 'What will you do on this project?' })}
                </p>
                <div className="flex flex-wrap gap-2">
                  {ACTIVITIES.map((a) => (
                    <Chip
                      key={a}
                      active={activity.includes(a)}
                      onClick={() => toggleIn(activity, a, setActivity)}
                      label={t(`project_wizard.activity_opt.${a}`, { defaultValue: humanize(a) })}
                    />
                  ))}
                </div>
              </div>
              <div>
                <p className="text-sm font-semibold text-content-primary mb-2">
                  {t('project_wizard.phases', { defaultValue: 'Lifecycle phases in scope' })}
                </p>
                <div className="flex flex-wrap gap-2">
                  {PHASES.map((ph) => (
                    <Chip
                      key={ph}
                      active={phases.includes(ph)}
                      onClick={() => toggleIn(phases, ph, setPhases)}
                      label={t(`project_wizard.phase_opt.${ph}`, { defaultValue: cap(ph) })}
                    />
                  ))}
                </div>
              </div>
              <label className="flex items-start gap-2.5 rounded-xl border border-border-light bg-surface-secondary/30 p-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={focusMode}
                  onChange={(e) => setFocusMode(e.target.checked)}
                  className="h-4 w-4 mt-0.5 rounded border-border accent-oe-blue"
                />
                <span className="text-xs">
                  <span className="block font-medium text-content-primary">
                    {t('project_wizard.focus_mode', { defaultValue: 'Focus mode' })}
                  </span>
                  <span className="text-content-tertiary">
                    {t('project_wizard.focus_mode_hint', { defaultValue: 'Show a numbered, phase-grouped sidebar with off-scope modules greyed out. You can toggle this any time.' })}
                  </span>
                </span>
              </label>
            </div>
          )}

          {/* Step 5 — Site & review */}
          {step === 5 && (
            <div className="space-y-4">
              <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <MapPin size={14} className="text-oe-blue" />
                  <label className="text-sm font-semibold text-content-primary">
                    {t('projects.address', { defaultValue: 'Site address' })}
                  </label>
                  <span className="text-[10px] text-content-quaternary">
                    {t('projects.address_hint', { defaultValue: 'Optional — enables the location map and weather forecast' })}
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input type="text" value={addressStreet} onChange={(e) => setAddressStreet(e.target.value)} placeholder={t('projects.address_street', { defaultValue: 'Street & number' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                  <input type="text" value={addressCity} onChange={(e) => setAddressCity(e.target.value)} placeholder={t('projects.address_city', { defaultValue: 'City' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                  <input type="text" value={addressCountry} onChange={(e) => setAddressCountry(e.target.value)} placeholder={t('projects.address_country', { defaultValue: 'Country' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                  <input type="text" value={addressPostal} onChange={(e) => setAddressPostal(e.target.value)} placeholder={t('projects.address_postal', { defaultValue: 'Postal code' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                </div>
                <div className="flex items-center gap-4 pt-1 border-t border-border-light/60 mt-2">
                  <span className="text-xs text-content-tertiary">
                    {t('projects.widgets_for_project', { defaultValue: 'Show on this project:' })}
                  </span>
                  <label className="inline-flex items-center gap-1.5 text-xs text-content-primary cursor-pointer">
                    <input type="checkbox" checked={mapEnabled} onChange={toggleMap} className="h-3.5 w-3.5 rounded border-border accent-oe-blue" />
                    <MapIcon size={11} className="text-oe-blue" />
                    {t('widget_settings.map', { defaultValue: 'Map' })}
                  </label>
                  <label className="inline-flex items-center gap-1.5 text-xs text-content-primary cursor-pointer">
                    <input type="checkbox" checked={weatherEnabled} onChange={toggleWeather} className="h-3.5 w-3.5 rounded border-border accent-oe-blue" />
                    <CloudSun size={11} className="text-oe-blue" />
                    {t('widget_settings.weather', { defaultValue: 'Weather' })}
                  </label>
                </div>
              </div>

              {/* Summary */}
              <div className="rounded-xl border border-border-light p-4">
                <p className="text-sm font-semibold text-content-primary mb-2.5">
                  {t('project_wizard.review', { defaultValue: 'Review' })}
                </p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                  <SummaryRow label={t('projects.project_name')} value={trimmedName || '—'} />
                  <SummaryRow label={t('projects.region', { defaultValue: 'Region' })} value={form.region || '—'} />
                  <SummaryRow label={t('projects.currency', { defaultValue: 'Currency' })} value={form.currency || '—'} />
                  <SummaryRow
                    label={t('project_wizard.step_type', { defaultValue: 'Project type' })}
                    value={selectedPreset ? t(selectedPreset.label_key, { defaultValue: selectedPreset.label_en }) : preset}
                  />
                  <SummaryRow
                    label={t('project_wizard.modules', { defaultValue: 'Modules' })}
                    value={selectedPreset ? String(selectedPreset.module_count) : '—'}
                  />
                  <SummaryRow
                    label={t('project_wizard.focus_mode', { defaultValue: 'Focus mode' })}
                    value={focusMode ? t('common.on', { defaultValue: 'On' }) : t('common.off', { defaultValue: 'Off' })}
                  />
                </dl>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-border-light shrink-0">
          <Button
            variant="secondary"
            type="button"
            onClick={step === 1 ? onClose : back}
            disabled={mutation.isPending}
          >
            {step === 1
              ? t('common.cancel')
              : <span className="flex items-center gap-1"><ChevronLeft size={15} />{t('common.back', { defaultValue: 'Back' })}</span>}
          </Button>
          {isLast ? (
            <Button
              variant="primary"
              type="button"
              onClick={() => mutation.mutate()}
              loading={mutation.isPending}
              disabled={!trimmedName}
            >
              {t('common.create')}
            </Button>
          ) : (
            <Button
              variant="primary"
              type="button"
              onClick={next}
              disabled={!canAdvance}
            >
              <span className="flex items-center gap-1">
                {t('common.next', { defaultValue: 'Next' })}
                <ChevronRight size={15} />
              </span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// Route compat — redirect to /projects and open modal
export function CreateProjectPage() {
  const navigate = useNavigate();
  useEffect(() => {
    navigate('/projects', { state: { openCreateModal: true }, replace: true });
  }, [navigate]);
  return null;
}

// ── small helpers ─────────────────────────────────────────────────────────

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function humanize(s: string): string {
  return s.split('_').map(cap).join(' ');
}

function Chip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        active
          ? 'border-oe-blue bg-oe-blue text-white'
          : 'border-border-light bg-surface-primary text-content-secondary hover:border-content-tertiary'
      }`}
    >
      {label}
    </button>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-content-tertiary">{label}</dt>
      <dd className="text-content-primary font-medium text-right truncate">{value}</dd>
    </>
  );
}

// ── Grouped Select (with <optgroup>) ──────────────────────────────────────

function GroupedSelectField({
  label, value, groups, placeholder, onChange,
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
  label, value, options, onChange,
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
