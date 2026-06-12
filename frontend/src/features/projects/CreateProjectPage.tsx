import {
  useState, useEffect, useRef,
  type ChangeEvent, type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  X, FolderPlus, AlertTriangle, MapPin, Map as MapIcon, CloudSun,
  Check, ChevronLeft, ChevronRight, ChevronDown, Layers, Wand2, Zap,
  ArrowRight, Plus, Globe, Hash, CalendarDays, FileText,
} from 'lucide-react';
import { Button, Input, InfoHint } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useWidgetSettingsStore } from '@/stores/useWidgetSettingsStore';
import { AddressAutocomplete } from '@/features/geo-hub/AddressAutocomplete';
import type { AddressAutocompleteSelection } from '@/features/geo-hub/AddressAutocomplete';
import {
  projectsApi,
  type CreateProjectData,
  type Project,
  type WizardPreset,
  type ProfileSpec,
} from './api';
import { useTelemetry } from '@/shared/lib/telemetry';

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
      { value: 'EUR', label: 'EUR (€) - Euro' },
      { value: 'GBP', label: 'GBP (£) - British Pound' },
      { value: 'CHF', label: 'CHF (Fr.) - Swiss Franc' },
      { value: 'SEK', label: 'SEK (kr) - Swedish Krona' },
      { value: 'NOK', label: 'NOK (kr) - Norwegian Krone' },
      { value: 'DKK', label: 'DKK (kr) - Danish Krone' },
      { value: 'PLN', label: 'PLN (zł) - Polish Zloty' },
      { value: 'CZK', label: 'CZK (Kč) - Czech Koruna' },
      { value: 'TRY', label: 'TRY (₺) - Turkish Lira' },
      { value: 'RUB', label: 'RUB (₽) - Russian Ruble' },
      { value: 'HUF', label: 'HUF (Ft) - Hungarian Forint' },
      { value: 'RON', label: 'RON (lei) - Romanian Leu' },
      { value: 'BGN', label: 'BGN (лв) - Bulgarian Lev' },
      { value: 'HRK', label: 'HRK (kn) - Croatian Kuna' },
      { value: 'ISK', label: 'ISK (kr) - Icelandic Krona' },
    ],
  },
  {
    group: 'Americas',
    options: [
      { value: 'USD', label: 'USD ($) - US Dollar' },
      { value: 'CAD', label: 'CAD (C$) - Canadian Dollar' },
      { value: 'BRL', label: 'BRL (R$) - Brazilian Real' },
      { value: 'MXN', label: 'MXN (Mex$) - Mexican Peso' },
      { value: 'ARS', label: 'ARS (AR$) - Argentine Peso' },
      { value: 'CLP', label: 'CLP (CL$) - Chilean Peso' },
      { value: 'PEN', label: 'PEN (S/) - Peruvian Sol' },
      { value: 'COP', label: 'COP (COL$) - Colombian Peso' },
    ],
  },
  {
    group: 'Asia & Middle East',
    options: [
      { value: 'CNY', label: 'CNY (¥) - Chinese Yuan' },
      { value: 'JPY', label: 'JPY (¥) - Japanese Yen' },
      { value: 'KRW', label: 'KRW (₩) - South Korean Won' },
      { value: 'INR', label: 'INR (₹) - Indian Rupee' },
      { value: 'AED', label: 'AED (د.إ) - UAE Dirham' },
      { value: 'SAR', label: 'SAR (﷼) - Saudi Riyal' },
      { value: 'QAR', label: 'QAR (﷼) - Qatari Riyal' },
      { value: 'BHD', label: 'BHD (BD) - Bahraini Dinar' },
      { value: 'KWD', label: 'KWD (د.ك) - Kuwaiti Dinar' },
      { value: 'OMR', label: 'OMR (ر.ع.) - Omani Rial' },
      { value: 'SGD', label: 'SGD (S$) - Singapore Dollar' },
      { value: 'MYR', label: 'MYR (RM) - Malaysian Ringgit' },
      { value: 'THB', label: 'THB (฿) - Thai Baht' },
      { value: 'IDR', label: 'IDR (Rp) - Indonesian Rupiah' },
      { value: 'PHP', label: 'PHP (₱) - Philippine Peso' },
      { value: 'VND', label: 'VND (₫) - Vietnamese Dong' },
      { value: 'HKD', label: 'HKD (HK$) - Hong Kong Dollar' },
      { value: 'TWD', label: 'TWD (NT$) - Taiwan Dollar' },
      { value: 'ILS', label: 'ILS (₪) - Israeli Shekel' },
      { value: 'JOD', label: 'JOD (JD) - Jordanian Dinar' },
      { value: 'LBP', label: 'LBP (ل.ل) - Lebanese Pound' },
      { value: 'PKR', label: 'PKR (₨) - Pakistani Rupee' },
      { value: 'BDT', label: 'BDT (৳) - Bangladeshi Taka' },
      { value: 'LKR', label: 'LKR (Rs) - Sri Lankan Rupee' },
    ],
  },
  {
    group: 'Africa',
    options: [
      { value: 'ZAR', label: 'ZAR (R) - South African Rand' },
      { value: 'EGP', label: 'EGP (E£) - Egyptian Pound' },
      { value: 'NGN', label: 'NGN (₦) - Nigerian Naira' },
      { value: 'KES', label: 'KES (KSh) - Kenyan Shilling' },
      { value: 'MAD', label: 'MAD (د.م.) - Moroccan Dirham' },
      { value: 'TND', label: 'TND (DT) - Tunisian Dinar' },
      { value: 'GHS', label: 'GHS (GH₵) - Ghanaian Cedi' },
      { value: 'TZS', label: 'TZS (TSh) - Tanzanian Shilling' },
      { value: 'UGX', label: 'UGX (USh) - Ugandan Shilling' },
      { value: 'ETB', label: 'ETB (Br) - Ethiopian Birr' },
    ],
  },
  {
    group: 'Oceania',
    options: [
      { value: 'AUD', label: 'AUD (A$) - Australian Dollar' },
      { value: 'NZD', label: 'NZD (NZ$) - New Zealand Dollar' },
      { value: 'FJD', label: 'FJD (FJ$) - Fijian Dollar' },
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

// Create flow the user picked on the intro screen. 'choose' = the
// landing screen that offers the two paths; 'wizard' = the 5-step
// guided setup; 'classic' = the old single-window form (essentials
// only — region/type/scope use sensible defaults under the hood).
type CreateMode = 'choose' | 'wizard' | 'classic';

// ── Modal ─────────────────────────────────────────────────────────────────

interface CreateProjectModalProps {
  open: boolean;
  onClose: () => void;
  /**
   * Slice 4 — edit mode. When set, the modal re-opens the SAME wizard
   * for an existing project: name/region/standard/currency/locale and
   * the current profile are prefilled, no project is created, and
   * submit calls `applyProfile` on this id. The component is NOT
   * forked — this is a mode prop, the steps/UX are identical.
   */
  editProjectId?: string;
}

export function CreateProjectModal({
  open,
  onClose,
  editProjectId,
}: CreateProjectModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { track } = useTelemetry();
  const isEdit = !!editProjectId;

  // Which create flow we're in. Always starts on the chooser so the
  // user is offered the wizard vs. the old single-window form.
  const [mode, setMode] = useState<CreateMode>('choose');
  const [step, setStep] = useState(1);
  // Furthest step the user has reached — gates which stepper dots are
  // clickable (you can jump back to a visited step, never skip forward).
  const [maxStep, setMaxStep] = useState(1);
  // Inline "discard changes?" confirm shown when closing a dirty wizard.
  const [confirmingClose, setConfirmingClose] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // Element that had focus before the wizard opened — focus is returned
  // here on close so keyboard / screen-reader users are not stranded.
  const returnFocusRef = useRef<HTMLElement | null>(null);
  // The safe default ("Keep editing") in the discard confirm — focused
  // when the confirm opens so Enter never lands on "Discard".
  const keepEditingRef = useRef<HTMLButtonElement>(null);

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
  // String-backed so the user can clear / type freely; parsed + clamped
  // to [0.5, 2.0] on blur and at submit (0 / empty no longer snap to 1).
  const [regionalFactorStr, setRegionalFactorStr] = useState('1.00');
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
  // Free-text query for the Nominatim autocomplete row that sits above
  // the 4 structured inputs. Selecting a result fills the parts below.
  const [addressSearchQuery, setAddressSearchQuery] = useState('');

  function applyAutocompleteSelection(sel: AddressAutocompleteSelection) {
    const parts = sel.address_parts ?? {};
    // Nominatim returns ``road`` for street name and ``house_number``
    // separately — we concatenate for the single-line "street" field.
    const street = [parts.house_number, parts.road ?? parts.street]
      .filter((v): v is string => typeof v === 'string' && v.trim() !== '')
      .join(' ')
      .trim();
    if (street) setAddressStreet(street);
    const city = parts.city || parts.town || parts.village;
    if (city) setAddressCity(city);
    if (parts.country) setAddressCountry(parts.country);
    if (parts.postcode) setAddressPostal(parts.postcode);
    // Keep the search field in sync with the picked display name so the
    // dropdown closes cleanly and the user sees what they accepted.
    setAddressSearchQuery(sel.display_name);
  }

  // Quick-create extras — all optional Phase-12 expansion fields the
  // backend `ProjectCreate` schema already accepts. Empty string means
  // "not provided" and is normalised to null/omitted in the payload.
  const [projectCode, setProjectCode] = useState('');
  const [projectType, setProjectType] = useState('');
  const [clientName, setClientName] = useState('');
  const [contractValue, setContractValue] = useState('');
  const [budgetEstimate, setBudgetEstimate] = useState('');
  const [plannedStart, setPlannedStart] = useState('');
  const [plannedEnd, setPlannedEnd] = useState('');

  // Quick-create progressive disclosure. The whole "Optional details"
  // block is user-collapsible (open by default so the first few fields
  // are visible without a click), and within it only the first handful
  // of fields show until the user clicks "Show more" — so a fast
  // project create needs no scrolling, while power users can still
  // reveal every optional parameter.
  const [optionalOpen, setOptionalOpen] = useState(true);
  const [showAllOptional, setShowAllOptional] = useState(false);

  const mapEnabled = useWidgetSettingsStore((s) => s.projectMapEnabled);
  const weatherEnabled = useWidgetSettingsStore((s) => s.projectWeatherEnabled);
  const toggleMap = useWidgetSettingsStore((s) => s.toggleProjectMap);
  const toggleWeather = useWidgetSettingsStore((s) => s.toggleProjectWeather);

  // Restore focus to the trigger element (the page's "New project"
  // button) whenever the wizard actually closes — wraps every close
  // path so success, cancel and discard all return focus correctly.
  const close = () => {
    onClose();
    const el = returnFocusRef.current;
    if (el && typeof el.focus === 'function') {
      // Defer so the trigger is back in the DOM/tab order first.
      requestAnimationFrame(() => el.focus());
    }
  };

  // Reset everything when the modal opens
  useEffect(() => {
    if (open) {
      returnFocusRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      setMode('choose');
      setStep(1);
      setMaxStep(1);
      setConfirmingClose(false);
      setForm({ name: '', description: '', region: '', classification_standard: '', currency: '', locale: 'en' });
      setCustomRegion('');
      setCustomStandard('');
      setCustomCurrency('');
      setRegionalFactorStr('1.00');
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
      setProjectCode('');
      setProjectType('');
      setClientName('');
      setContractValue('');
      setBudgetEstimate('');
      setPlannedStart('');
      setPlannedEnd('');
      // Force the edit-mode prefill to re-run on (re)open; the prefill
      // effect then overrides the defaults above once data arrives.
      setPrefilledFor(null);
      // Create flow opens the wizard funnel here; edit flow emits
      // `setup_rerun` from the prefill effect instead.
      if (!isEdit) track('wizard_started', { mode: 'create' });
    }
  }, [open, isEdit, track]);

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

  // ── Edit mode (Slice 4) — load the existing project + its profile so
  // every step prefills. Component is shared, not forked. ───────────────
  const { data: editProject } = useQuery<Project>({
    queryKey: ['project', editProjectId],
    queryFn: () => projectsApi.get(editProjectId!),
    enabled: open && isEdit,
    staleTime: 60_000,
  });
  const { data: editProfile } = useQuery({
    queryKey: ['project-profile', editProjectId],
    queryFn: () => projectsApi.getProfile(editProjectId!),
    enabled: open && isEdit,
    staleTime: 60_000,
    retry: false,
  });

  // Prefill the wizard from the loaded project + profile. Runs once the
  // data arrives (and again if the user reopens for a different id).
  const [prefilledFor, setPrefilledFor] = useState<string | null>(null);
  useEffect(() => {
    if (!open || !isEdit || !editProject) return;
    if (prefilledFor === editProject.id) return;
    setForm({
      name: editProject.name,
      description: editProject.description ?? '',
      region: editProject.region ?? '',
      classification_standard: editProject.classification_standard ?? '',
      currency: editProject.currency ?? '',
      locale: editProject.locale ?? 'en',
    });
    if (editProfile) {
      setPreset(editProfile.profile.preset || 'custom');
      setActivity(editProfile.profile.activity ?? []);
      setPhases(editProfile.profile.phases ?? []);
      setRole(editProfile.profile.role || 'general_contractor');
      setSize(editProfile.profile.size || 'medium');
      setFocusMode(editProfile.profile.focus_mode_enabled);
    }
    // Skip the chooser — jump straight into the guided wizard with
    // every visited step navigable for step-back editing.
    setMode('wizard');
    setStep(1);
    setMaxStep(STEP_COUNT);
    setPrefilledFor(editProject.id);
    track('setup_rerun', { project_id: editProject.id });
  }, [open, isEdit, editProject, editProfile, prefilledFor, track]);

  const trimmedName = form.name.trim();
  const duplicateExists =
    trimmedName.length > 0 &&
    existingProjects.some(
      (p) =>
        p.id !== editProjectId &&
        p.name.trim().toLowerCase() === trimmedName.toLowerCase(),
    );

  useEffect(() => {
    setDuplicateConfirmed(false);
  }, [trimmedName]);

  // When the preset changes, re-seed the activity/phase multi-selects with
  // that preset's sensible defaults (the user can still tweak them).
  const choosePreset = (id: string) => {
    // Re-clicking the already-selected card must not wipe scope edits
    // the user may have made on the next step.
    if (id === preset) return;
    setPreset(id);
    track('preset_selected', { preset: id, edit: isEdit });
    const d = PRESET_DEFAULTS[id];
    if (d) {
      setActivity(d.activity);
      setPhases(d.phases);
    }
  };

  const selectedPreset = presets.find((p) => p.id === preset);

  // Resolved values (the typed text wins when "Custom…" is picked) —
  // used for the gate, the submit payload, and the review summary so
  // none of them ever shows or stores the literal "__custom__".
  const effectiveRegion =
    form.region === '__custom__' ? customRegion.trim() : (form.region ?? '');
  const effectiveStandard =
    form.classification_standard === '__custom__'
      ? customStandard.trim()
      : (form.classification_standard ?? '');
  const effectiveCurrency =
    form.currency === '__custom__' ? customCurrency.trim() : (form.currency ?? '');

  // Any meaningful input → closing should confirm before discarding.
  const dirty =
    step > 1 ||
    trimmedName.length > 0 ||
    !!form.description ||
    !!form.region ||
    !!form.currency ||
    !!form.classification_standard ||
    addressStreet !== '' || addressCity !== '' ||
    addressCountry !== '' || addressPostal !== '';

  // Move focus into the step body when the step changes so keyboard /
  // screen-reader users land on the new content (step 1 keeps the
  // name field's autoFocus).
  useEffect(() => {
    if (step > 1) bodyRef.current?.focus();
  }, [step]);

  // When the discard confirm opens, move focus onto the safe action so
  // a reflexive Enter keeps the work instead of destroying it.
  useEffect(() => {
    if (confirmingClose) keepEditingRef.current?.focus();
  }, [confirmingClose]);

  // Focus trap — Tab / Shift+Tab cycle within the dialog so keyboard
  // and screen-reader users can't fall behind the modal onto the page.
  useEffect(() => {
    if (!open) return;
    const onTab = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      // While the discard confirm is up it is itself a modal layer —
      // trap inside it so Tab can't reach the step controls behind it.
      const root =
        (dialogRef.current?.querySelector<HTMLElement>(
          '[role="alertdialog"]',
        ) ?? dialogRef.current) || null;
      if (!root) return;
      const focusable = Array.from(
        root.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
        // The dialog sits inside a position:fixed overlay, so
        // ``offsetParent`` is null for every node here — use rect
        // presence (works regardless of positioning) for the
        // is-visible test.
      ).filter(
        (el) => el.getClientRects().length > 0 || el === document.activeElement,
      );
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey) {
        if (active === first || !root.contains(active)) {
          e.preventDefault();
          last.focus();
        }
      } else if (active === last || !root.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onTab, true);
    return () => document.removeEventListener('keydown', onTab, true);
  }, [open]);

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

      // Custom picks send the normalized effective values (trimmed, and
      // uppercased for the currency code) instead of the raw input text.
      const data: CreateProjectData = {
        ...form,
        region: form.region === '__custom__' ? effectiveRegion : form.region,
        classification_standard:
          form.classification_standard === '__custom__'
            ? effectiveStandard
            : form.classification_standard,
        currency:
          form.currency === '__custom__' ? effectiveCurrency.toUpperCase() : form.currency,
        regional_factor: clampFactor(regionalFactorStr),
        address: hasAnyAddress ? addressParts : null,
        // Optional Phase-12 expansion fields — only include when filled
        // so an untouched Quick-create form still posts a minimal body.
        project_code: projectCode.trim() || null,
        project_type: projectType.trim() || null,
        client_id: clientName.trim() || null,
        contract_value: contractValue.trim() || null,
        budget_estimate: budgetEstimate.trim() || null,
        planned_start_date: plannedStart.trim() || null,
        planned_end_date: plannedEnd.trim() || null,
      };

      // Edit mode (Slice 4): the project already exists — patch its
      // core fields, then re-apply the profile via the SAME endpoint
      // (POST /{id}/profile) the create flow uses. No project is made.
      if (isEdit && editProjectId) {
        await projectsApi.update(editProjectId, {
          name: data.name,
          description: data.description,
          region: data.region,
          classification_standard: data.classification_standard,
          currency: data.currency,
          locale: data.locale,
        });
        await projectsApi.applyProfile(editProjectId, buildSpec());
        return { id: editProjectId } as Project;
      }

      const project = await projectsApi.create(data);
      // Best-effort profile apply — a failure here must not lose the
      // already-created project; we surface a soft warning instead.
      try {
        await projectsApi.applyProfile(project.id, buildSpec());
      } catch {
        addToast({
          type: 'warning',
          title: t('project_wizard.profile_apply_failed', {
            defaultValue: 'Project created, but the module setup could not be applied - you can re-run it from Project Settings.',
          }),
        });
      }
      return project;
    },
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      // The header project switcher caches under its own key; without this
      // its stale-list purge effect clears the just-activated project.
      queryClient.invalidateQueries({ queryKey: ['projects-switcher'] });
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      queryClient.invalidateQueries({
        queryKey: ['project-profile', project.id],
      });
      track('setup_completed', {
        project_id: project.id,
        preset,
        edit: isEdit,
      });
      addToast({
        type: 'success',
        title: isEdit
          ? t('project_wizard.setup_updated', {
              defaultValue: 'Project setup updated',
            })
          : t('toasts.project_created', {
              defaultValue: 'Project created successfully',
            }),
      });
      // A freshly created project becomes the active one, so every
      // project-scoped tab (BOQ, Costs, Finance, Schedule, 5D) shows it
      // right away instead of the previous selection or the all-projects
      // mix - new users expect their new project to be "current".
      if (!isEdit) {
        useProjectContextStore
          .getState()
          .setActiveProject(project.id, trimmedName || project.name || '');
      }
      // Navigate away — no focus return here (we're leaving the page).
      onClose();
      navigate(`/projects/${project.id}`);
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.project_create_failed', { defaultValue: 'Failed to create project' }), message: error.message });
    },
  });

  const requestClose = () => {
    if (mutation.isPending) return;
    if (dirty) {
      setConfirmingClose(true);
      return;
    }
    close();
  };

  const set = (field: keyof CreateProjectData, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const toggleIn = (
    list: string[],
    val: string,
    setter: (v: string[]) => void,
    kind?: 'activity' | 'phase',
  ) => {
    const present = list.includes(val);
    setter(present ? list.filter((x) => x !== val) : [...list, val]);
    if (kind) {
      // Scope chips change the resolved module set — closest
      // user-meaningful "module toggled" signal in this wizard.
      track('module_toggled', { kind, value: val, on: !present });
    }
  };

  if (!open) return null;

  // Per-step gate for the Next button. The duplicate-name case is NOT
  // a gate here — Next stays enabled so the two-click "proceed anyway"
  // confirm in next() is actually reachable (it wasn't before: a
  // disabled button can't fire the confirm).
  const canAdvance = (() => {
    if (step === 1) return !!trimmedName;
    if (step === 2) {
      // Region + currency are fundamental (cost DB, VAT, BOQ pricing).
      // A "Custom…" pick with an empty text box is an empty value, so
      // effectiveX being blank already blocks it. Standard stays
      // optional unless the user explicitly chose "Custom…".
      if (!effectiveRegion || !effectiveCurrency) return false;
      if (form.classification_standard === '__custom__' && !effectiveStandard)
        return false;
      return true;
    }
    if (step === 3) return !!preset;
    return true;
  })();

  // Full-form gate for the final Create button. Step 2's per-step gate
  // can be bypassed by jumping back via a visited stepper dot and
  // clearing a required field, so the submit re-checks the same
  // invariants here and names the first missing one for the user.
  const submitBlockReason = (() => {
    if (!trimmedName)
      return mode === 'classic'
        ? t('project_wizard.need_name_quick', {
            defaultValue: 'Enter a project name.',
          })
        : t('project_wizard.need_name', {
            defaultValue: 'Enter a project name (step 1).',
          });
    // Quick create promises "only the name is required" - region and
    // currency stay optional there and remain editable later. The guided
    // wizard keeps them as step-2 gates. A "Custom..." pick with an empty
    // text box blocks both modes (the user explicitly chose custom).
    if (mode !== 'classic') {
      if (!effectiveRegion)
        return t('project_wizard.need_region', {
          defaultValue: 'Pick a region (step 2).',
        });
      if (!effectiveCurrency)
        return t('project_wizard.need_currency', {
          defaultValue: 'Pick a currency (step 2).',
        });
    }
    if (form.region === '__custom__' && !effectiveRegion)
      return t('project_wizard.need_custom_region_quick', {
        defaultValue: 'Type the custom region or set Region back to none.',
      });
    if (form.currency === '__custom__' && !effectiveCurrency)
      return t('project_wizard.need_custom_currency_quick', {
        defaultValue: 'Enter the custom currency code.',
      });
    if (form.classification_standard === '__custom__' && !effectiveStandard)
      return mode === 'classic'
        ? t('project_wizard.need_custom_standard_quick', {
            defaultValue: 'Type the custom standard or set it back to none.',
          })
        : t('project_wizard.need_standard', {
            defaultValue: 'Enter the custom classification standard (step 2).',
          });
    return null;
  })();
  const canSubmit = submitBlockReason === null;

  const isLast = step === STEP_COUNT;

  const goTo = (s: number) => {
    const clamped = Math.min(STEP_COUNT, Math.max(1, s));
    setStep(clamped);
    setMaxStep((m) => Math.max(m, clamped));
  };

  const next = () => {
    // First Next on a duplicate name arms the confirm; the warning
    // text flips to "Click Next again to proceed anyway".
    if (step === 1 && duplicateExists && !duplicateConfirmed) {
      setDuplicateConfirmed(true);
      return;
    }
    if (!isLast && canAdvance) goTo(step + 1);
  };
  const back = () => goTo(step - 1);

  // Enter advances (or creates on the last step); never hijack Enter
  // inside a textarea (newlines) or when a button/select is focused
  // (those have their own Enter semantics). Escape requests close.
  const onKeyDownModal = (e: KeyboardEvent<HTMLDivElement>) => {
    const tag = (e.target as HTMLElement).tagName;
    if (e.key === 'Escape') {
      // A focused native <select> uses Escape to close its own
      // dropdown — don't also tear down the wizard in that case.
      if (tag === 'SELECT') return;
      e.stopPropagation();
      // When the discard confirm is up, Escape takes the safe,
      // non-destructive path: dismiss the confirm and keep editing
      // (it must never silently throw the work away).
      if (confirmingClose) {
        setConfirmingClose(false);
        return;
      }
      requestClose();
      return;
    }
    if (e.key !== 'Enter') return;
    if (tag === 'TEXTAREA' || tag === 'BUTTON' || tag === 'SELECT') return;
    if (confirmingClose) return;
    // The chooser screen has no Enter action — let focus/click handle it.
    if (mode === 'choose') return;
    e.preventDefault();
    if (mode === 'classic' || isLast) {
      if (canSubmit && !mutation.isPending) mutation.mutate();
    } else {
      next();
    }
  };

  const STEP_TITLES = [
    t('project_wizard.step_basics', { defaultValue: 'Basics' }),
    t('project_wizard.step_region', { defaultValue: 'Region & currency' }),
    t('project_wizard.step_type', { defaultValue: 'Project type' }),
    t('project_wizard.step_scope', { defaultValue: 'Scope' }),
    t('project_wizard.step_review', { defaultValue: 'Site & review' }),
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onKeyDown={onKeyDownModal}
    >
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
        onClick={requestClose}
        aria-hidden
      />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cpw-title"
        className="relative w-full max-w-2xl mx-4 max-h-[90vh] rounded-xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue/10">
              <FolderPlus size={20} className="text-oe-blue" />
            </div>
            <div>
              <h2 id="cpw-title" className="text-lg font-semibold text-content-primary">
                {isEdit
                  ? t('project_wizard.edit_setup_title', {
                      defaultValue: 'Edit project setup',
                    })
                  : t('projects.new_project', { defaultValue: 'New Project' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {mode === 'choose'
                  ? t('project_wizard.choose_subtitle', {
                      defaultValue: 'Choose how you want to set this project up',
                    })
                  : mode === 'classic'
                    ? t('project_wizard.classic_subtitle', {
                        defaultValue: 'Quick create - just the essentials',
                      })
                    : t('project_wizard.step_of', {
                        defaultValue: 'Step {{n}} of {{total}} · {{title}}',
                        n: step, total: STEP_COUNT, title: STEP_TITLES[step - 1],
                      })}
              </p>
            </div>
          </div>
          <button
            onClick={requestClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Stepper — wizard only. grid-cols-N guarantees equal,
            non-collapsing columns. Visited dots are buttons (jump
            back); the current + future dots are not navigable
            forward (no step skipping). */}
        {mode === 'wizard' && (
        <div className="px-6 pb-4 shrink-0">
          <div className="relative">
            {/* neutral track behind the dots — the dots themselves carry
                all progress state, so no same-colour camouflage. */}
            <div className="absolute left-3 right-3 top-3 h-px bg-border-light" />
            <div
              className="relative grid"
              style={{ gridTemplateColumns: `repeat(${STEP_COUNT}, minmax(0, 1fr))` }}
            >
              {Array.from({ length: STEP_COUNT }, (_, i) => i + 1).map((s) => {
                const navigable = s <= maxStep && s !== step;
                const dotCls = `flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ring-4 ring-surface-elevated transition-colors ${
                  s < step
                    ? 'bg-oe-blue text-white'
                    : s === step
                      ? 'bg-oe-blue text-white ring-oe-blue/25'
                      : 'bg-surface-secondary text-content-tertiary border border-border-light'
                }`;
                return (
                  <div key={s} className="flex flex-col items-center gap-1.5 min-w-0">
                    {navigable ? (
                      <button
                        type="button"
                        onClick={() => setStep(s)}
                        aria-label={STEP_TITLES[s - 1]}
                        className={dotCls + ' cursor-pointer hover:opacity-90'}
                      >
                        {s < step ? <Check size={13} /> : s}
                      </button>
                    ) : (
                      <div
                        className={dotCls}
                        aria-current={s === step ? 'step' : undefined}
                      >
                        {s < step ? <Check size={13} /> : s}
                      </div>
                    )}
                    <span
                      className={`hidden sm:block text-[10px] leading-tight text-center truncate max-w-[88px] ${
                        s === step
                          ? 'text-content-secondary font-medium'
                          : 'text-content-quaternary'
                      }`}
                    >
                      {STEP_TITLES[s - 1]}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
        )}

        {/* Body — scrollable */}
        <div
          ref={bodyRef}
          tabIndex={-1}
          aria-label={
            mode === 'choose'
              ? t('project_wizard.choose_subtitle', { defaultValue: 'Choose how you want to set this project up' })
              : mode === 'classic'
                ? t('project_wizard.classic_subtitle', { defaultValue: 'Quick create - just the essentials' })
                : STEP_TITLES[step - 1]
          }
          className="overflow-y-auto px-6 pb-6 flex-1 outline-none"
        >
          {/* Mode chooser — the landing screen. Offers the guided
              wizard or the old single-window quick form. */}
          {mode === 'choose' && (
            <div className="space-y-3">
              <InfoHint
                text={t('project_wizard.choose_hint', {
                  defaultValue:
                    'New here, or want a tailored module setup? Use the guided wizard. Know exactly what you need? Quick create gets you a project in one screen.',
                })}
              />
              <button
                type="button"
                onClick={() => { setMode('classic'); setStep(1); }}
                className="group w-full text-left rounded-xl border border-border-light hover:border-oe-blue hover:bg-oe-blue/5 transition-all p-4 flex items-start gap-3.5"
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
                  <Zap size={20} />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-semibold text-content-primary">
                    {t('project_wizard.choose_classic_title', { defaultValue: 'Quick create' })}
                  </span>
                  <p className="mt-1 text-xs leading-relaxed text-content-tertiary">
                    {t('project_wizard.choose_classic_blurb', {
                      defaultValue:
                        'Every project setting on one screen - name, region, currency, address, client, dates and budget. Only the name is required; everything else is optional and editable later.',
                    })}
                  </p>
                </div>
                <ArrowRight size={16} className="mt-1 shrink-0 text-content-quaternary transition-transform group-hover:translate-x-0.5 group-hover:text-oe-blue" />
              </button>
              <button
                type="button"
                onClick={() => { setMode('wizard'); setStep(1); setMaxStep(1); }}
                className="group w-full text-left rounded-xl border border-border-light hover:border-oe-blue hover:bg-oe-blue/5 transition-all p-4 flex items-start gap-3.5"
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface-secondary text-content-secondary">
                  <Wand2 size={20} />
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-semibold text-content-primary">
                    {t('project_wizard.choose_wizard_title', { defaultValue: 'Guided setup' })}
                  </span>
                  <p className="mt-1 text-xs leading-relaxed text-content-tertiary">
                    {t('project_wizard.choose_wizard_blurb', {
                      defaultValue:
                        '5 short steps - region, project type and scope. Pre-selects the right modules and a focused sidebar for the work you do.',
                    })}
                  </p>
                </div>
                <ArrowRight size={16} className="mt-1 shrink-0 text-content-quaternary transition-transform group-hover:translate-x-0.5 group-hover:text-oe-blue" />
              </button>
            </div>
          )}

          {/* Quick create — a single-window superset form. Every project
              setting the wizard collects is here on one screen. Only the
              project name is required (it is the sole non-defaulted field
              on the backend `ProjectCreate` schema); everything else is
              grouped under an explicit Optional section. */}
          {mode === 'classic' && (
            <div className="space-y-5">
              <InfoHint
                text={t('projects.create.required_hint', {
                  defaultValue:
                    'Only the project name is required - everything else is optional and can be edited later in Project Settings.',
                })}
              />

              {/* Required */}
              <div className="space-y-4">
                <div>
                  <label
                    htmlFor="qc-name"
                    className="text-sm font-medium text-content-primary block mb-1.5"
                  >
                    {t('projects.project_name')}
                    <span aria-hidden className="ml-0.5 text-red-600 dark:text-red-400">*</span>
                    <span className="ml-1.5 rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-600 dark:bg-red-900/30 dark:text-red-300">
                      {t('projects.create.required_badge', { defaultValue: 'Required' })}
                    </span>
                  </label>
                  <Input
                    id="qc-name"
                    aria-required="true"
                    value={form.name}
                    onChange={(e) => set('name', e.target.value)}
                    placeholder={t('projects.project_name_placeholder', { defaultValue: 'e.g. Office Tower Downtown' })}
                    autoFocus
                  />
                </div>
                {duplicateExists && (
                  <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 px-3 py-2 -mt-2">
                    <AlertTriangle size={16} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                    <div className="text-xs">
                      <p className="font-medium text-amber-900 dark:text-amber-200">
                        {t('projects.duplicate_name_warning', { defaultValue: 'A project with this name already exists.' })}
                      </p>
                      <p className="text-amber-800 dark:text-amber-300 mt-0.5">
                        {duplicateConfirmed
                          ? t('projects.duplicate_name_confirm_again_create', { defaultValue: 'Click Create again to proceed anyway.' })
                          : t('projects.duplicate_name_confirm_hint_create', { defaultValue: 'Change the name, or click Create again to proceed anyway.' })}
                      </p>
                    </div>
                  </div>
                )}
              </div>

              {/* Optional — everything below is optional. The whole
                  block is user-collapsible, and inside it only the
                  first few fields show until "Show more" is clicked. */}
              <div className="space-y-4 rounded-xl border border-border-light bg-surface-secondary/20 p-4">
                <button
                  type="button"
                  onClick={() => setOptionalOpen((v) => !v)}
                  aria-expanded={optionalOpen}
                  aria-controls="qc-optional-body"
                  className="flex w-full items-center justify-between gap-2 text-left -m-1 p-1 rounded-lg hover:bg-surface-secondary/40 transition-colors"
                >
                  <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('projects.create.optional_section', { defaultValue: 'Optional details' })}
                  </span>
                  <span className="flex items-center gap-1 text-[11px] font-medium text-content-tertiary">
                    {optionalOpen
                      ? t('projects.create.optional_hide', { defaultValue: 'Hide' })
                      : t('projects.create.optional_show', { defaultValue: 'Show' })}
                    <ChevronDown
                      size={14}
                      className={`transition-transform duration-fast ease-oe ${optionalOpen ? 'rotate-180' : ''}`}
                    />
                  </span>
                </button>

                <div
                  id="qc-optional-body"
                  hidden={!optionalOpen}
                  className="space-y-4"
                >
                {/* Description & notes */}
                <div className="rounded-xl border border-border-light bg-surface-primary/40 p-4 space-y-3">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                      <FileText size={15} />
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('projects.create.grp_description_title', { defaultValue: 'Description & notes' })}
                      </p>
                      <p className="text-[11px] text-content-tertiary">
                        {t('projects.create.grp_description_sub', { defaultValue: 'Scope, context - anything useful later. Optional.' })}
                      </p>
                    </div>
                  </div>
                  <textarea
                    id="qc-description"
                    value={form.description}
                    onChange={(e) => set('description', e.target.value)}
                    placeholder={t('projects.description_placeholder', { defaultValue: 'Project description, scope, notes...' })}
                    rows={2}
                    className="w-full rounded-lg border border-border px-3 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary resize-none"
                  />
                </div>

                {/* Classification & localization */}
                <div className="rounded-xl border border-border-light bg-surface-primary/40 p-4 space-y-3">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                      <Globe size={15} />
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('projects.create.grp_localization_title', { defaultValue: 'Classification & localization' })}
                      </p>
                      <p className="text-[11px] text-content-tertiary">
                        {t('projects.create.grp_localization_sub', { defaultValue: 'Region, standard, currency and language. Optional - editable later.' })}
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <GroupedSelectField
                      label={t('projects.region', { defaultValue: 'Region' })}
                      optional
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                      value={form.region ?? ''}
                      groups={REGION_GROUPS}
                      placeholder={t('projects.select_region', { defaultValue: '-- Select region --' })}
                      onChange={(v) => set('region', v)}
                    />
                    {form.region === '__custom__' && (
                      <CustomValueInput
                        value={customRegion}
                        onChange={setCustomRegion}
                        placeholder={t('projects.enter_custom_region', { defaultValue: 'Enter custom region...' })}
                        emptyHint={t('project_wizard.custom_region_required', { defaultValue: 'Type your region to continue.' })}
                      />
                    )}
                  </div>
                  <div>
                    <GroupedSelectField
                      label={t('projects.classification_standard', { defaultValue: 'Classification Standard' })}
                      optional
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                      value={form.classification_standard ?? ''}
                      groups={STANDARD_GROUPS}
                      placeholder={t('projects.select_standard', { defaultValue: '-- Select standard --' })}
                      onChange={(v) => set('classification_standard', v)}
                    />
                    {form.classification_standard === '__custom__' && (
                      <CustomValueInput
                        value={customStandard}
                        onChange={setCustomStandard}
                        placeholder={t('projects.enter_custom_standard', { defaultValue: 'Enter custom standard...' })}
                        emptyHint={t('project_wizard.custom_standard_required', { defaultValue: 'Type the standard name to continue.' })}
                      />
                    )}
                  </div>
                  <div>
                    <GroupedSelectField
                      label={t('projects.currency', { defaultValue: 'Currency' })}
                      optional
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                      value={form.currency ?? ''}
                      groups={CURRENCY_GROUPS}
                      placeholder={t('projects.select_currency', { defaultValue: '-- Select currency --' })}
                      onChange={(v) => set('currency', v)}
                    />
                    {form.currency === '__custom__' && (
                      <CustomValueInput
                        value={customCurrency}
                        onChange={setCustomCurrency}
                        placeholder={t('projects.enter_custom_currency', { defaultValue: 'e.g. XAF' })}
                        emptyHint={t('project_wizard.custom_currency_required', { defaultValue: 'Type the ISO currency code to continue.' })}
                        maxLength={10}
                      />
                    )}
                  </div>
                  <SelectField
                    label={t('projects.language', { defaultValue: 'Language' })}
                    optional
                    optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    value={form.locale ?? 'en'}
                    options={LANGUAGES}
                    onChange={(v) => set('locale', v)}
                  />
                  </div>
                </div>

                {/* Progressive disclosure — one click reveals every
                    remaining optional group as visual cards. */}
                {!showAllOptional && (
                  <button
                    type="button"
                    onClick={() => setShowAllOptional(true)}
                    aria-expanded={false}
                    aria-controls="qc-optional-more"
                    className="group flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-oe-blue/40 bg-oe-blue/5 px-4 py-3 text-sm font-medium text-oe-blue transition-colors hover:bg-oe-blue/10"
                  >
                    <Plus size={15} />
                    {t('projects.create.show_more', { defaultValue: 'Show all options' })}
                    <ChevronDown size={14} className="transition-transform group-hover:translate-y-0.5" />
                  </button>
                )}

                <div
                  id="qc-optional-more"
                  hidden={!showAllOptional}
                  className="space-y-4"
                >
                {/* Identification */}
                <div className="rounded-xl border border-border-light bg-surface-primary/40 p-4 space-y-3">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                      <Hash size={15} />
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('projects.create.grp_identification_title', { defaultValue: 'Identification' })}
                      </p>
                      <p className="text-[11px] text-content-tertiary">
                        {t('projects.create.grp_identification_sub', { defaultValue: 'Code, type and client. Optional - auto-filled where possible.' })}
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <OptionalLabel
                      htmlFor="qc-project-code"
                      text={t('projects.project_code', { defaultValue: 'Project number / code' })}
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    />
                    <input
                      id="qc-project-code"
                      type="text"
                      value={projectCode}
                      onChange={(e) => setProjectCode(e.target.value)}
                      maxLength={50}
                      placeholder={t('projects.project_code_placeholder', { defaultValue: 'Auto-generated if left blank' })}
                      className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  </div>
                  <div>
                    <OptionalLabel
                      htmlFor="qc-project-type"
                      text={t('projects.project_type', { defaultValue: 'Project type' })}
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    />
                    <input
                      id="qc-project-type"
                      type="text"
                      value={projectType}
                      onChange={(e) => setProjectType(e.target.value)}
                      maxLength={50}
                      placeholder={t('projects.project_type_placeholder', { defaultValue: 'e.g. Residential, Infrastructure' })}
                      className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <OptionalLabel
                      htmlFor="qc-client"
                      text={t('projects.client_owner', { defaultValue: 'Client / owner' })}
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    />
                    <input
                      id="qc-client"
                      type="text"
                      value={clientName}
                      onChange={(e) => setClientName(e.target.value)}
                      maxLength={36}
                      placeholder={t('projects.client_owner_placeholder', { defaultValue: 'Client or owner name' })}
                      className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  </div>
                  </div>
                </div>

                {/* Site address */}
                <div className="rounded-xl border border-border-light bg-surface-primary/40 p-4 space-y-3">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                      <MapPin size={15} />
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('projects.address', { defaultValue: 'Site address' })}
                      </p>
                      <p className="text-[11px] text-content-tertiary">
                        {t('projects.address_hint', { defaultValue: 'Optional - enables the location map and weather forecast' })}
                      </p>
                    </div>
                  </div>
                  {/* Address autocomplete — picks Nominatim suggestions
                      and fills the 4 structured inputs below. The user
                      can still type/edit each part manually. */}
                  <AddressAutocomplete
                    value={addressSearchQuery}
                    onChange={setAddressSearchQuery}
                    onSelect={applyAutocompleteSelection}
                    ariaLabel={t('projects.address_search', { defaultValue: 'Search address' })}
                  />
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <input type="text" value={addressStreet} onChange={(e) => setAddressStreet(e.target.value)} aria-label={t('projects.address_street', { defaultValue: 'Street & number' })} placeholder={t('projects.address_street', { defaultValue: 'Street & number' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                    <input type="text" value={addressCity} onChange={(e) => setAddressCity(e.target.value)} aria-label={t('projects.address_city', { defaultValue: 'City' })} placeholder={t('projects.address_city', { defaultValue: 'City' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                    <input type="text" value={addressCountry} onChange={(e) => setAddressCountry(e.target.value)} aria-label={t('projects.address_country', { defaultValue: 'Country' })} placeholder={t('projects.address_country', { defaultValue: 'Country' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                    <input type="text" value={addressPostal} onChange={(e) => setAddressPostal(e.target.value)} aria-label={t('projects.address_postal', { defaultValue: 'Postal code' })} placeholder={t('projects.address_postal', { defaultValue: 'Postal code' })} className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent" />
                  </div>
                  <div className="flex items-center gap-4 pt-1 border-t border-border-light/60 mt-1">
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

                {/* Schedule & budget */}
                <div className="rounded-xl border border-border-light bg-surface-primary/40 p-4 space-y-3">
                  <div className="flex items-center gap-2.5">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                      <CalendarDays size={15} />
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-content-primary">
                        {t('projects.create.grp_schedule_title', { defaultValue: 'Schedule & budget' })}
                      </p>
                      <p className="text-[11px] text-content-tertiary">
                        {t('projects.create.grp_schedule_sub', { defaultValue: 'Dates, budget, contract value and the regional cost factor. Optional.' })}
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <OptionalLabel
                      htmlFor="qc-start"
                      text={t('projects.planned_start_date', { defaultValue: 'Planned start date' })}
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    />
                    <input
                      id="qc-start"
                      type="date"
                      value={plannedStart}
                      onChange={(e) => setPlannedStart(e.target.value)}
                      className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  </div>
                  <div>
                    <OptionalLabel
                      htmlFor="qc-end"
                      text={t('projects.planned_end_date', { defaultValue: 'Planned end date' })}
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    />
                    <input
                      id="qc-end"
                      type="date"
                      value={plannedEnd}
                      onChange={(e) => setPlannedEnd(e.target.value)}
                      min={plannedStart || undefined}
                      className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  </div>
                  <div>
                    <OptionalLabel
                      htmlFor="qc-budget"
                      text={t('projects.budget_estimate', { defaultValue: 'Budget estimate' })}
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    />
                    <input
                      id="qc-budget"
                      type="text"
                      inputMode="decimal"
                      value={budgetEstimate}
                      onChange={(e) => setBudgetEstimate(e.target.value)}
                      maxLength={50}
                      placeholder={t('projects.budget_estimate_placeholder', { defaultValue: 'e.g. 1500000' })}
                      className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary tabular-nums placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  </div>
                  <div>
                    <OptionalLabel
                      htmlFor="qc-contract"
                      text={t('projects.contract_value', { defaultValue: 'Contract value' })}
                      optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                    />
                    <input
                      id="qc-contract"
                      type="text"
                      inputMode="decimal"
                      value={contractValue}
                      onChange={(e) => setContractValue(e.target.value)}
                      maxLength={50}
                      placeholder={t('projects.contract_value_placeholder', { defaultValue: 'e.g. 1800000' })}
                      className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary tabular-nums placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                    />
                  </div>
                </div>

                <div>
                  <OptionalLabel
                    htmlFor="qc-regional-factor"
                    text={t('projects.regional_factor', { defaultValue: 'Regional Factor' })}
                    optionalText={t('projects.create.optional_badge', { defaultValue: 'Optional' })}
                  />
                  <input
                    id="qc-regional-factor"
                    type="number"
                    min="0.5"
                    max="2.0"
                    step="0.01"
                    inputMode="decimal"
                    value={regionalFactorStr}
                    onChange={(e) => setRegionalFactorStr(e.target.value)}
                    onBlur={() => setRegionalFactorStr(clampFactor(regionalFactorStr).toFixed(2))}
                    placeholder="1.00"
                    className="h-10 w-full max-w-[200px] rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary tabular-nums placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
                  />
                  <p className="mt-1 text-xs text-content-tertiary">
                    {t('projects.regional_factor_hint', { defaultValue: 'Multiply all rates by this factor (e.g. 1.12 = +12% over base).' })}
                  </p>
                </div>
                </div>
                </div>

                {showAllOptional && (
                  <button
                    type="button"
                    onClick={() => setShowAllOptional(false)}
                    aria-expanded
                    aria-controls="qc-optional-more"
                    className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-border-light px-4 py-2 text-xs font-medium text-content-tertiary transition-colors hover:bg-surface-secondary/40 hover:text-content-primary"
                  >
                    <ChevronDown size={14} className="rotate-180" />
                    {t('projects.create.show_less', { defaultValue: 'Show fewer options' })}
                  </button>
                )}
                </div>
              </div>

              <p className="text-[11px] text-content-quaternary">
                {t('project_wizard.classic_defaults_note', {
                  defaultValue:
                    'Modules and lifecycle scope use the full-lifecycle default. Switch to the guided setup to tailor them, or change everything later in Project Settings.',
                })}
              </p>
            </div>
          )}

          {/* Step 1 — Basics */}
          {mode === 'wizard' && step === 1 && (
            <div className="space-y-4">
              <InfoHint text={t('project_wizard.basics_hint', { defaultValue: 'Give the project a clear, unique name. You can change everything later in Project Settings.' })} />
              <Input
                label={t('projects.project_name')}
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder={t('projects.project_name_placeholder', { defaultValue: 'e.g. Office Tower Downtown' })}
                required aria-required="true"
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
          {mode === 'wizard' && step === 2 && (
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
                    <CustomValueInput
                      value={customRegion}
                      onChange={setCustomRegion}
                      placeholder={t('projects.enter_custom_region', { defaultValue: 'Enter custom region...' })}
                      emptyHint={t('project_wizard.custom_region_required', { defaultValue: 'Type your region to continue.' })}
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
                    <CustomValueInput
                      value={customStandard}
                      onChange={setCustomStandard}
                      placeholder={t('projects.enter_custom_standard', { defaultValue: 'Enter custom standard...' })}
                      emptyHint={t('project_wizard.custom_standard_required', { defaultValue: 'Type the standard name to continue.' })}
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
                    <CustomValueInput
                      value={customCurrency}
                      onChange={setCustomCurrency}
                      placeholder={t('projects.enter_custom_currency', { defaultValue: 'e.g. XAF' })}
                      emptyHint={t('project_wizard.custom_currency_required', { defaultValue: 'Type the ISO currency code to continue.' })}
                      maxLength={10}
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
                  inputMode="decimal"
                  value={regionalFactorStr}
                  onChange={(e) => setRegionalFactorStr(e.target.value)}
                  onBlur={() =>
                    setRegionalFactorStr(clampFactor(regionalFactorStr).toFixed(2))
                  }
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
          {mode === 'wizard' && step === 3 && (
            <div className="space-y-3">
              <InfoHint text={t('project_wizard.type_hint', { defaultValue: 'Pick the closest match. This pre-selects the modules and route for your project - nothing is locked, you can refine on the next step.' })} />
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
                        {t(`project_wizard.preset_blurb.${p.id}`, {
                          defaultValue: p.blurb_en,
                        })}
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
          {mode === 'wizard' && step === 4 && (
            <div className="space-y-5">
              <InfoHint text={t('project_wizard.scope_hint', { defaultValue: 'These refine which modules are emphasised. Defaults come from the project type you picked - adjust only if needed.' })} />
              <div>
                <p className="text-sm font-semibold text-content-primary mb-2">
                  {t('project_wizard.activities', { defaultValue: 'What will you do on this project?' })}
                </p>
                <div className="flex flex-wrap gap-2">
                  {ACTIVITIES.map((a) => (
                    <Chip
                      key={a}
                      active={activity.includes(a)}
                      onClick={() => toggleIn(activity, a, setActivity, 'activity')}
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
                      onClick={() => toggleIn(phases, ph, setPhases, 'phase')}
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
          {mode === 'wizard' && step === 5 && (
            <div className="space-y-4">
              <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <MapPin size={14} className="text-oe-blue" />
                  <label className="text-sm font-semibold text-content-primary">
                    {t('projects.address', { defaultValue: 'Site address' })}
                  </label>
                  <span className="text-[10px] text-content-quaternary">
                    {t('projects.address_hint', { defaultValue: 'Optional - enables the location map and weather forecast' })}
                  </span>
                </div>
                {/* Address autocomplete (all-on-one variant) — same
                    handler fills the structured inputs on pick. */}
                <AddressAutocomplete
                  value={addressSearchQuery}
                  onChange={setAddressSearchQuery}
                  onSelect={applyAutocompleteSelection}
                  ariaLabel={t('projects.address_search', { defaultValue: 'Search address' })}
                />
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
                  <SummaryRow
                    label={t('projects.region', { defaultValue: 'Region' })}
                    value={
                      form.region === '__custom__'
                        ? (customRegion.trim() || '—')
                        : (labelFor(REGION_GROUPS, form.region ?? '') || '—')
                    }
                  />
                  <SummaryRow
                    label={t('projects.currency', { defaultValue: 'Currency' })}
                    value={
                      form.currency === '__custom__'
                        ? (customCurrency.trim() || '—')
                        : (labelFor(CURRENCY_GROUPS, form.currency ?? '') || '—')
                    }
                  />
                  <SummaryRow
                    label={t('projects.classification_standard', { defaultValue: 'Classification Standard' })}
                    value={
                      form.classification_standard === '__custom__'
                        ? (customStandard.trim() || '—')
                        : (labelFor(STANDARD_GROUPS, form.classification_standard ?? '') || '—')
                    }
                  />
                  <SummaryRow
                    label={t('projects.language', { defaultValue: 'Language' })}
                    value={
                      LANGUAGES.find((l) => l.value === form.locale)?.label ??
                      (form.locale || '—')
                    }
                  />
                  <SummaryRow
                    label={t('projects.regional_factor', { defaultValue: 'Regional Factor' })}
                    value={clampFactor(regionalFactorStr).toFixed(2)}
                  />
                  <SummaryRow
                    label={t('project_wizard.step_type', { defaultValue: 'Project type' })}
                    value={selectedPreset ? t(selectedPreset.label_key, { defaultValue: selectedPreset.label_en }) : humanize(preset)}
                  />
                  <SummaryRow
                    label={t('project_wizard.role', { defaultValue: 'Your role' })}
                    value={t(`project_wizard.role_opt.${role}`, { defaultValue: humanize(role) })}
                  />
                  <SummaryRow
                    label={t('project_wizard.size', { defaultValue: 'Project size' })}
                    value={t(`project_wizard.size_opt.${size}`, { defaultValue: cap(size) })}
                  />
                  <SummaryRow
                    label={t('project_wizard.activities', { defaultValue: 'Activities' })}
                    value={String(activity.length)}
                  />
                  <SummaryRow
                    label={t('project_wizard.phases', { defaultValue: 'Phases' })}
                    value={String(phases.length)}
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

        {/* Footer — left = back/cancel, right = the mode's primary
            action. The chooser has no primary (the two cards are the
            action); classic + wizard's last step submit; other wizard
            steps advance. */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-border-light shrink-0">
          <Button
            variant="secondary"
            type="button"
            onClick={
              mode === 'choose'
                ? requestClose
                : mode === 'classic'
                  ? () => setMode('choose')
                  : step === 1
                    // Edit mode has no chooser to fall back to — step-1
                    // Back closes the re-wizard instead.
                    ? (isEdit ? requestClose : () => setMode('choose'))
                    : back
            }
            disabled={mutation.isPending}
          >
            {mode === 'choose'
              ? t('common.cancel')
              : (step === 1 && isEdit)
                ? t('common.cancel')
                : <span className="flex items-center gap-1"><ChevronLeft size={15} />{t('common.back', { defaultValue: 'Back' })}</span>}
          </Button>
          {mode === 'choose' ? null : mode === 'classic' || isLast ? (
            <div className="flex items-center gap-3 min-w-0">
              {!canSubmit && submitBlockReason && (
                <span className="hidden sm:flex items-center gap-1 text-xs text-amber-700 dark:text-amber-300 min-w-0">
                  <AlertTriangle size={13} className="shrink-0" />
                  <span className="truncate">{submitBlockReason}</span>
                </span>
              )}
              <Button
                variant="primary"
                type="button"
                onClick={() => {
                  // Idempotent: a double-click / Enter-then-click must
                  // never fire two create requests.
                  if (!canSubmit || mutation.isPending) return;
                  // Quick-create has no "Next" to arm the duplicate
                  // confirm, so the first Create on a dup name arms it
                  // and the second proceeds (mirrors the wizard's
                  // two-click "proceed anyway").
                  if (mode === 'classic' && duplicateExists && !duplicateConfirmed) {
                    setDuplicateConfirmed(true);
                    return;
                  }
                  mutation.mutate();
                }}
                loading={mutation.isPending}
                disabled={!canSubmit || mutation.isPending}
                title={!canSubmit ? (submitBlockReason ?? undefined) : undefined}
              >
                {isEdit
                  ? t('project_wizard.save_setup', {
                      defaultValue: 'Save setup',
                    })
                  : t('common.create')}
              </Button>
            </div>
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

        {/* Discard-confirmation overlay — a multi-step wizard must not
            silently throw away everything on a stray backdrop click /
            Escape. */}
        {confirmingClose && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-surface-elevated/85 backdrop-blur-sm">
            <div
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="cpw-discard-title"
              className="mx-6 max-w-sm rounded-xl border border-border-light bg-surface-elevated p-5 shadow-xl text-center"
            >
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30">
                <AlertTriangle size={18} className="text-amber-600 dark:text-amber-400" />
              </div>
              <p
                id="cpw-discard-title"
                className="text-sm font-semibold text-content-primary"
              >
                {t('project_wizard.discard_title', { defaultValue: 'Discard this project setup?' })}
              </p>
              <p className="mt-1 text-xs text-content-tertiary">
                {t('project_wizard.discard_body', { defaultValue: 'Your answers on every step will be lost. This cannot be undone.' })}
              </p>
              <div className="mt-4 flex items-center justify-center gap-2">
                <Button
                  ref={keepEditingRef}
                  variant="secondary"
                  type="button"
                  onClick={() => setConfirmingClose(false)}
                >
                  {t('project_wizard.keep_editing', { defaultValue: 'Keep editing' })}
                </Button>
                <Button
                  variant="danger"
                  type="button"
                  onClick={() => {
                    setConfirmingClose(false);
                    close();
                  }}
                >
                  {t('project_wizard.discard', { defaultValue: 'Discard' })}
                </Button>
              </div>
            </div>
          </div>
        )}
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

/** Resolve a select value to its human label by scanning the option
 *  groups. Falls back to the raw value (custom entries, unknown keys). */
function labelFor(groups: OptionGroup[], value: string): string {
  if (!value) return '';
  for (const g of groups) {
    const o = g.options.find((x) => x.value === value);
    if (o) return o.label;
  }
  return value;
}

function clampFactor(raw: string): number {
  const n = Number.parseFloat(raw);
  if (!Number.isFinite(n)) return 1.0;
  return Math.min(2.0, Math.max(0.5, n));
}

/** Free-text input shown when "Custom…" is picked. When the user has
 *  chosen Custom but left it blank it is the thing blocking Next, so it
 *  marks itself aria-invalid and explains why instead of the user
 *  staring at a silently-disabled button. */
function CustomValueInput({
  value,
  onChange,
  placeholder,
  emptyHint,
  maxLength,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  emptyHint: string;
  maxLength?: number;
}) {
  const invalid = value.trim().length === 0;
  return (
    <>
      <input
        type="text"
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        aria-invalid={invalid}
        className={`mt-2 h-10 w-full rounded-lg border bg-surface-primary px-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:border-transparent ${
          invalid
            ? 'border-amber-400 focus:ring-amber-400'
            : 'border-border focus:ring-oe-blue'
        }`}
      />
      {invalid && (
        <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">
          {emptyHint}
        </p>
      )}
    </>
  );
}

/** Field label with an explicit "(optional)" badge, so Quick-create
 *  users can tell at a glance which fields are not required. */
function OptionalLabel({
  htmlFor,
  text,
  optionalText,
}: {
  htmlFor: string;
  text: string;
  optionalText: string;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-sm font-medium text-content-primary block mb-1.5"
    >
      {text}
      <span className="ml-1.5 text-[11px] font-normal text-content-tertiary">
        ({optionalText})
      </span>
    </label>
  );
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
      <dd
        className="text-content-primary font-medium text-right truncate"
        title={value}
      >
        {value}
      </dd>
    </>
  );
}

// ── Grouped Select (with <optgroup>) ──────────────────────────────────────

function GroupedSelectField({
  label, value, groups, placeholder, onChange, optional, optionalText,
}: {
  label: string;
  value: string;
  groups: OptionGroup[];
  placeholder?: string;
  onChange: (v: string) => void;
  optional?: boolean;
  optionalText?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-content-primary">
        {label}
        {optional && (
          <span className="ml-1.5 text-[11px] font-normal text-content-tertiary">
            ({optionalText})
          </span>
        )}
      </label>
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
  label, value, options, onChange, optional, optionalText,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  optional?: boolean;
  optionalText?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-content-primary">
        {label}
        {optional && (
          <span className="ml-1.5 text-[11px] font-normal text-content-tertiary">
            ({optionalText})
          </span>
        )}
      </label>
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
