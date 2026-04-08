import { useState, useCallback, useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import i18n from 'i18next';
import clsx from 'clsx';
import {
  ArrowRight,
  ArrowLeft,
  Check,
  Sparkles,
  Eye,
  EyeOff,
  ExternalLink,
  Loader2,
  CheckCircle2,
  Database,
  FolderOpen,
  Rocket,
  Package,
  Building2,
  Calculator,
  ClipboardList,
  Pencil,
  Boxes,
  Settings2,
  type LucideIcon,
} from 'lucide-react';
import { Logo, Button, CountryFlag, Badge } from '@/shared/ui';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useToastStore } from '@/stores/useToastStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { aiApi, type AIProvider } from '@/features/ai/api';
import { apiPost } from '@/shared/lib/api';

// ── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 6;

// ── Language -> Region mapping ──────────────────────────────────────────────

const LANG_TO_REGION: Record<string, string> = {
  de: 'DE_BERLIN',
  fr: 'FR_PARIS',
  es: 'SP_BARCELONA',
  pt: 'PT_SAOPAULO',
  ru: 'RU_STPETERSBURG',
  zh: 'ZH_SHANGHAI',
  ar: 'AR_DUBAI',
  hi: 'HI_MUMBAI',
  en: 'USA_USD',
  tr: 'AR_DUBAI',
  it: 'SP_BARCELONA',
  ja: 'ZH_SHANGHAI',
  ko: 'ZH_SHANGHAI',
  nl: 'DE_BERLIN',
  pl: 'DE_BERLIN',
  cs: 'DE_BERLIN',
  sv: 'DE_BERLIN',
  no: 'DE_BERLIN',
  da: 'DE_BERLIN',
  fi: 'DE_BERLIN',
  bg: 'DE_BERLIN',
};

// ── Language -> Demo project mapping ────────────────────────────────────────

const LANG_TO_DEMO: Record<string, string> = {
  de: 'residential-berlin',
  en: 'medical-us',
  fr: 'school-paris',
  ar: 'warehouse-dubai',
};
const DEFAULT_DEMO = 'office-london';

// ── CWICR Database definitions ──────────────────────────────────────────────

interface CWICRDatabase {
  id: string;
  name: string;
  city: string;
  lang: string;
  currency: string;
  flagId: string;
}

const CWICR_DATABASES: CWICRDatabase[] = [
  { id: 'USA_USD', name: 'United States', city: 'New York', lang: 'English', currency: 'USD', flagId: 'us' },
  { id: 'UK_GBP', name: 'United Kingdom', city: 'London', lang: 'English', currency: 'GBP', flagId: 'gb' },
  { id: 'ENG_TORONTO', name: 'Canada / International', city: 'Toronto', lang: 'English', currency: 'CAD', flagId: 'ca' },
  { id: 'DE_BERLIN', name: 'Germany / DACH', city: 'Berlin', lang: 'Deutsch', currency: 'EUR', flagId: 'de' },
  { id: 'FR_PARIS', name: 'France', city: 'Paris', lang: 'Fran\u00e7ais', currency: 'EUR', flagId: 'fr' },
  { id: 'SP_BARCELONA', name: 'Spain / Latin America', city: 'Barcelona', lang: 'Espa\u00f1ol', currency: 'EUR', flagId: 'es' },
  { id: 'PT_SAOPAULO', name: 'Brazil / Portugal', city: 'S\u00e3o Paulo', lang: 'Portugu\u00eas', currency: 'BRL', flagId: 'br' },
  { id: 'RU_STPETERSBURG', name: 'Russia / CIS', city: 'St. Petersburg', lang: '\u0420\u0443\u0441\u0441\u043a\u0438\u0439', currency: 'RUB', flagId: 'ru' },
  { id: 'AR_DUBAI', name: 'Middle East / Gulf', city: 'Dubai', lang: '\u0627\u0644\u0639\u0631\u0628\u064a\u0629', currency: 'AED', flagId: 'ae' },
  { id: 'ZH_SHANGHAI', name: 'China', city: 'Shanghai', lang: '\u4e2d\u6587', currency: 'CNY', flagId: 'cn' },
  { id: 'HI_MUMBAI', name: 'India / South Asia', city: 'Mumbai', lang: 'Hindi', currency: 'INR', flagId: 'in' },
];

// ── AI Provider definitions ─────────────────────────────────────────────────

interface ProviderOption {
  id: AIProvider;
  name: string;
  description: string;
  docsUrl: string;
  recommended?: boolean;
}

const AI_PROVIDERS: ProviderOption[] = [
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    description: 'Best for construction estimation',
    docsUrl: 'https://console.anthropic.com/settings/keys',
    recommended: true,
  },
  {
    id: 'openai',
    name: 'OpenAI GPT-4',
    description: 'Widely supported',
    docsUrl: 'https://platform.openai.com/api-keys',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    description: 'Multimodal capabilities',
    docsUrl: 'https://aistudio.google.com/app/apikey',
  },
];

// ── Company Type Presets ────────────────────────────────────────────────────

type CompanyTypeKey =
  | 'general_contractor'
  | 'estimator'
  | 'project_management'
  | 'architecture_engineering'
  | 'full_enterprise';

interface CompanyPreset {
  key: CompanyTypeKey;
  labelKey: string;
  descriptionKey: string;
  icon: LucideIcon;
  enabledModules: string[];
  tags: string[];
  popular?: boolean;
}

const COMPANY_PRESETS: CompanyPreset[] = [
  {
    key: 'general_contractor',
    labelKey: 'onboarding.company_general_contractor',
    descriptionKey: 'onboarding.company_general_contractor_desc',
    icon: Building2,
    popular: true,
    tags: ['BOQ', 'Finance', 'Safety'],
    enabledModules: [
      'boq', 'projects', 'costs', 'assemblies', 'catalog', 'templates',
      'schedule', 'finance', 'procurement', 'safety', 'inspections',
      'punchlist', 'field-reports', 'tasks', 'meetings', 'documents',
      'risks', 'changeorders', 'contacts', 'reports', 'reporting',
      'analytics', 'validation', 'photos', 'ncr', 'requirements',
    ],
  },
  {
    key: 'estimator',
    labelKey: 'onboarding.company_estimator',
    descriptionKey: 'onboarding.company_estimator_desc',
    icon: Calculator,
    tags: ['BOQ', 'Costs', 'Takeoff', 'AI'],
    enabledModules: [
      'boq', 'projects', 'costs', 'assemblies', 'catalog', 'templates',
      'takeoff', 'pdf-takeoff', 'ai-estimate', 'advisor', 'validation',
      'reports', 'reporting', 'analytics', 'data-explorer', 'documents',
      'cost-benchmark',
    ],
  },
  {
    key: 'project_management',
    labelKey: 'onboarding.company_project_management',
    descriptionKey: 'onboarding.company_project_management_desc',
    icon: ClipboardList,
    tags: ['Schedule', 'Tasks', 'Finance'],
    enabledModules: [
      'projects', 'schedule', 'tasks', 'meetings', 'finance',
      'procurement', 'documents', 'cde', 'transmittals', 'rfi',
      'submittals', 'correspondence', 'risks', 'changeorders',
      'reporting', 'contacts', 'reports', 'analytics', 'markups',
      'photos', 'field-reports', 'requirements', 'inspections',
    ],
  },
  {
    key: 'architecture_engineering',
    labelKey: 'onboarding.company_architecture',
    descriptionKey: 'onboarding.company_architecture_desc',
    icon: Pencil,
    tags: ['Documents', 'CDE', 'BIM'],
    enabledModules: [
      'projects', 'documents', 'cde', 'bim', 'transmittals', 'rfi',
      'submittals', 'correspondence', 'takeoff', 'pdf-takeoff', 'boq',
      'costs', 'data-explorer', 'markups', 'photos', 'reports',
      'validation', 'sustainability',
    ],
  },
  {
    key: 'full_enterprise',
    labelKey: 'onboarding.company_full_enterprise',
    descriptionKey: 'onboarding.company_full_enterprise_desc',
    icon: Boxes,
    tags: [],
    enabledModules: [], // special case: all modules
  },
];

// ── Module catalog for review step ──────────────────────────────────────────

interface ModuleDef {
  key: string;
  labelKey: string;
  descriptionKey: string;
  group: string;
  core?: boolean;
}

const MODULE_GROUPS = [
  { id: 'core', labelKey: 'onboarding.mod_group_core' },
  { id: 'estimation', labelKey: 'onboarding.mod_group_estimation' },
  { id: 'takeoff', labelKey: 'onboarding.mod_group_takeoff' },
  { id: 'ai', labelKey: 'onboarding.mod_group_ai' },
  { id: 'planning', labelKey: 'onboarding.mod_group_planning' },
  { id: 'finance', labelKey: 'onboarding.mod_group_finance' },
  { id: 'communication', labelKey: 'onboarding.mod_group_communication' },
  { id: 'documents', labelKey: 'onboarding.mod_group_documents' },
  { id: 'quality', labelKey: 'onboarding.mod_group_quality' },
  { id: 'field', labelKey: 'onboarding.mod_group_field' },
];

const ALL_MODULES: ModuleDef[] = [
  // Core (always on)
  { key: 'dashboard', labelKey: 'nav.dashboard', descriptionKey: 'onboarding.mod_dashboard_desc', group: 'core', core: true },
  { key: 'projects', labelKey: 'projects.title', descriptionKey: 'onboarding.mod_projects_desc', group: 'core', core: true },
  { key: 'contacts', labelKey: 'contacts.title', descriptionKey: 'onboarding.mod_contacts_desc', group: 'core', core: true },
  // Estimation
  { key: 'boq', labelKey: 'boq.title', descriptionKey: 'onboarding.mod_boq_desc', group: 'estimation' },
  { key: 'costs', labelKey: 'costs.title', descriptionKey: 'onboarding.mod_costs_desc', group: 'estimation' },
  { key: 'assemblies', labelKey: 'nav.assemblies', descriptionKey: 'onboarding.mod_assemblies_desc', group: 'estimation' },
  { key: 'catalog', labelKey: 'catalog.title', descriptionKey: 'onboarding.mod_catalog_desc', group: 'estimation' },
  { key: 'validation', labelKey: 'validation.title', descriptionKey: 'onboarding.mod_validation_desc', group: 'estimation' },
  // Takeoff & BIM
  { key: 'takeoff', labelKey: 'nav.takeoff_overview', descriptionKey: 'onboarding.mod_takeoff_desc', group: 'takeoff' },
  { key: 'pdf-takeoff', labelKey: 'nav.pdf_measurements', descriptionKey: 'onboarding.mod_pdf_takeoff_desc', group: 'takeoff' },
  { key: 'bim', labelKey: 'nav.bim_viewer', descriptionKey: 'onboarding.mod_bim_desc', group: 'takeoff' },
  { key: 'data-explorer', labelKey: 'nav.cad_bim_explorer', descriptionKey: 'onboarding.mod_data_explorer_desc', group: 'takeoff' },
  // AI
  { key: 'ai-estimate', labelKey: 'nav.ai_estimate', descriptionKey: 'onboarding.mod_ai_estimate_desc', group: 'ai' },
  { key: 'advisor', labelKey: 'nav.ai_advisor', descriptionKey: 'onboarding.mod_advisor_desc', group: 'ai' },
  // Planning
  { key: 'schedule', labelKey: 'schedule.title', descriptionKey: 'onboarding.mod_schedule_desc', group: 'planning' },
  { key: 'tasks', labelKey: 'tasks.title', descriptionKey: 'onboarding.mod_tasks_desc', group: 'planning' },
  { key: '5d', labelKey: 'nav.5d_cost_model', descriptionKey: 'onboarding.mod_5d_desc', group: 'planning' },
  // Finance
  { key: 'finance', labelKey: 'finance.title', descriptionKey: 'onboarding.mod_finance_desc', group: 'finance' },
  { key: 'procurement', labelKey: 'procurement.title', descriptionKey: 'onboarding.mod_procurement_desc', group: 'finance' },
  { key: 'tendering', labelKey: 'tendering.title', descriptionKey: 'onboarding.mod_tendering_desc', group: 'finance' },
  { key: 'changeorders', labelKey: 'nav.change_orders', descriptionKey: 'onboarding.mod_changeorders_desc', group: 'finance' },
  // Communication
  { key: 'meetings', labelKey: 'meetings.title', descriptionKey: 'onboarding.mod_meetings_desc', group: 'communication' },
  { key: 'rfi', labelKey: 'rfi.title', descriptionKey: 'onboarding.mod_rfi_desc', group: 'communication' },
  { key: 'submittals', labelKey: 'submittals.title', descriptionKey: 'onboarding.mod_submittals_desc', group: 'communication' },
  { key: 'transmittals', labelKey: 'transmittals.title', descriptionKey: 'onboarding.mod_transmittals_desc', group: 'communication' },
  { key: 'correspondence', labelKey: 'correspondence.title', descriptionKey: 'onboarding.mod_correspondence_desc', group: 'communication' },
  // Documents
  { key: 'documents', labelKey: 'nav.documents', descriptionKey: 'onboarding.mod_documents_desc', group: 'documents' },
  { key: 'cde', labelKey: 'cde.title', descriptionKey: 'onboarding.mod_cde_desc', group: 'documents' },
  { key: 'photos', labelKey: 'nav.photos', descriptionKey: 'onboarding.mod_photos_desc', group: 'documents' },
  { key: 'markups', labelKey: 'nav.markups', descriptionKey: 'onboarding.mod_markups_desc', group: 'documents' },
  // Quality & Safety
  { key: 'inspections', labelKey: 'inspections.title', descriptionKey: 'onboarding.mod_inspections_desc', group: 'quality' },
  { key: 'ncr', labelKey: 'ncr.title', descriptionKey: 'onboarding.mod_ncr_desc', group: 'quality' },
  { key: 'safety', labelKey: 'safety.title', descriptionKey: 'onboarding.mod_safety_desc', group: 'quality' },
  { key: 'punchlist', labelKey: 'nav.punchlist', descriptionKey: 'onboarding.mod_punchlist_desc', group: 'quality' },
  { key: 'risks', labelKey: 'nav.risk_register', descriptionKey: 'onboarding.mod_risks_desc', group: 'quality' },
  // Field
  { key: 'field-reports', labelKey: 'nav.field_reports', descriptionKey: 'onboarding.mod_field_reports_desc', group: 'field' },
  { key: 'requirements', labelKey: 'nav.requirements', descriptionKey: 'onboarding.mod_requirements_desc', group: 'field' },
  { key: 'reports', labelKey: 'nav.reports', descriptionKey: 'onboarding.mod_reports_desc', group: 'field' },
  { key: 'reporting', labelKey: 'nav.reporting', descriptionKey: 'onboarding.mod_reporting_desc', group: 'field' },
  { key: 'analytics', labelKey: 'nav.analytics', descriptionKey: 'onboarding.mod_analytics_desc', group: 'field' },
  { key: 'sustainability', labelKey: 'nav.sustainability', descriptionKey: 'onboarding.mod_sustainability_desc', group: 'field' },
  { key: 'cost-benchmark', labelKey: 'nav.cost_benchmark', descriptionKey: 'onboarding.mod_cost_benchmark_desc', group: 'field' },
  { key: 'collaboration', labelKey: 'nav.collaboration', descriptionKey: 'onboarding.mod_collaboration_desc', group: 'field' },
  { key: 'templates', labelKey: 'nav.templates', descriptionKey: 'onboarding.mod_templates_desc', group: 'field' },
];

const CORE_MODULE_KEYS = new Set(ALL_MODULES.filter((m) => m.core).map((m) => m.key));

// ── Helpers ──────────────────────────────────────────────────────────────────

function maskApiKey(key: string): string {
  if (key.length <= 8) return '\u2022'.repeat(key.length);
  return key.slice(0, 8) + '\u2022'.repeat(Math.min(key.length - 8, 24));
}

/** Mark onboarding as completed in localStorage. */
export function markOnboardingCompleted(): void {
  try {
    localStorage.setItem('oe_onboarding_completed', 'true');
  } catch {
    // Storage unavailable -- ignore.
  }
}

/** Check whether onboarding has been completed. */
export function isOnboardingCompleted(): boolean {
  try {
    return localStorage.getItem('oe_onboarding_completed') === 'true';
  } catch {
    return false;
  }
}

/** Get the suggested region for the current language */
function getSuggestedRegion(lang?: string): string {
  const code = lang || i18n.language || 'en';
  const base = code.split('-')[0] ?? 'en';
  return LANG_TO_REGION[base] ?? 'ENG_TORONTO';
}

/** Get the suggested demo project IDs for the current language */
function getSuggestedDemo(lang?: string): string {
  const code = lang || i18n.language || 'en';
  const base = code.split('-')[0] ?? 'en';
  return LANG_TO_DEMO[base] ?? DEFAULT_DEMO;
}

// ── Fade wrapper for step transitions ───────────────────────────────────────

function StepTransition({ children, stepKey }: { children: ReactNode; stepKey: number }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Trigger fade-in on mount
    const frame = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div
      key={stepKey}
      className={clsx(
        'transition-all duration-300 ease-out',
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3',
      )}
    >
      {children}
    </div>
  );
}

// ── Toggle Switch component ─────────────────────────────────────────────────

function ToggleSwitch({
  enabled,
  onToggle,
  disabled,
}: {
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      onClick={onToggle}
      disabled={disabled}
      className={clsx(
        'group relative inline-flex h-[26px] w-[48px] shrink-0 cursor-pointer rounded-full p-[3px] transition-all duration-300 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/50',
        enabled
          ? 'bg-gradient-to-r from-oe-blue to-blue-500 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.1)]'
          : 'bg-gray-200 dark:bg-gray-700 shadow-[inset_0_1px_3px_rgba(0,0,0,0.1)]',
        disabled && 'opacity-50 cursor-not-allowed',
      )}
    >
      <span
        className={clsx(
          'pointer-events-none flex h-5 w-5 items-center justify-center rounded-full bg-white shadow-lg ring-0 transition-all duration-300 ease-in-out',
          enabled ? 'translate-x-[22px] scale-[1.05]' : 'translate-x-0 scale-100',
        )}
      >
        {enabled && <Check size={11} className="text-oe-blue" strokeWidth={3} />}
      </span>
    </button>
  );
}

// ── Progress Bar ─────────────────────────────────────────────────────────────

function ProgressBar({ current, total }: { current: number; total: number }) {
  const { t } = useTranslation();
  const stepLabels = [
    t('onboarding.step_welcome', { defaultValue: 'Welcome' }),
    t('onboarding.step_start', { defaultValue: 'Start' }),
    t('onboarding.step_profile', { defaultValue: 'Profile' }),
    t('onboarding.step_modules', { defaultValue: 'Modules' }),
    t('onboarding.step_data', { defaultValue: 'Data' }),
    t('onboarding.step_finish', { defaultValue: 'Finish' }),
  ];

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-3">
        {Array.from({ length: total }).map((_, i) => (
          <div key={i} className="flex flex-col items-center gap-1 flex-1">
            <div className="flex items-center w-full">
              {i > 0 && (
                <div
                  className={clsx(
                    'h-0.5 flex-1 rounded-full transition-colors duration-500',
                    i <= current ? 'bg-oe-blue' : 'bg-border-light',
                  )}
                />
              )}
              <div
                className={clsx(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-2xs font-bold transition-all duration-500 ease-oe',
                  i < current
                    ? 'bg-oe-blue text-white'
                    : i === current
                      ? 'bg-oe-blue text-white ring-4 ring-oe-blue/20 scale-110'
                      : 'bg-surface-secondary text-content-tertiary border border-border-light',
                )}
              >
                {i < current ? <Check size={12} /> : i + 1}
              </div>
              {i < total - 1 && (
                <div
                  className={clsx(
                    'h-0.5 flex-1 rounded-full transition-colors duration-500',
                    i < current ? 'bg-oe-blue' : 'bg-border-light',
                  )}
                />
              )}
            </div>
            <span
              className={clsx(
                'text-2xs font-medium transition-colors whitespace-nowrap',
                i === current
                  ? 'text-oe-blue'
                  : i < current
                    ? 'text-content-secondary'
                    : 'text-content-quaternary',
              )}
            >
              {stepLabels[i] ?? ''}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Step 1: Welcome + Language ───────────────────────────────────────────────

function StepWelcome({
  onNext,
  onLanguageChange,
}: {
  onNext: () => void;
  onLanguageChange: (lang: string) => void;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState(() => {
    const detected = navigator.language?.split('-')[0] || 'en';
    const match = SUPPORTED_LANGUAGES.find((l) => l.code === detected);
    return match ? match.code : 'en';
  });

  const handleSelect = useCallback(
    (code: string) => {
      setSelected(code);
      i18n.changeLanguage(code);
      onLanguageChange(code);
    },
    [onLanguageChange],
  );

  // Auto-detect on mount
  useEffect(() => {
    const detected = navigator.language?.split('-')[0] || 'en';
    const match = SUPPORTED_LANGUAGES.find((l) => l.code === detected);
    if (match && match.code !== i18n.language) {
      i18n.changeLanguage(match.code);
      onLanguageChange(match.code);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col items-center justify-center text-center">
      <div className="mb-8">
        <Logo size="xl" animate />
      </div>

      <h1 className="text-4xl font-bold text-content-primary tracking-tight">
        {t('onboarding.welcome_title', { defaultValue: 'Welcome to OpenConstructionERP' })}
      </h1>

      <p className="mt-4 max-w-md text-lg text-content-secondary leading-relaxed">
        {t('onboarding.welcome_subtitle', {
          defaultValue:
            'The professional construction cost estimation platform.\nSet up your workspace in a few simple steps.',
        })}
      </p>

      {/* Language grid */}
      <div className="mt-8 w-full max-w-xl grid grid-cols-3 sm:grid-cols-4 gap-2">
        {SUPPORTED_LANGUAGES.map((lang) => {
          const isSelected = selected === lang.code;
          return (
            <button
              key={lang.code}
              onClick={() => handleSelect(lang.code)}
              className={clsx(
                'relative flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-left',
                'border transition-all duration-normal ease-oe',
                isSelected
                  ? 'border-oe-blue bg-oe-blue-subtle/40 ring-2 ring-oe-blue/20'
                  : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary active:scale-[0.98]',
              )}
            >
              <CountryFlag code={lang.country} size={20} className="shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-content-primary truncate">
                  {lang.name}
                </div>
                <div className="text-2xs text-content-tertiary uppercase">{lang.code}</div>
              </div>
              {isSelected && (
                <CheckCircle2 size={14} className="text-oe-blue shrink-0" />
              )}
            </button>
          );
        })}
      </div>

      <Button
        variant="primary"
        size="lg"
        onClick={onNext}
        icon={<ArrowRight size={18} />}
        iconPosition="right"
        className="mt-10"
      >
        {t('onboarding.get_started', { defaultValue: 'Get Started' })}
      </Button>

      <p className="mt-6 text-xs text-content-tertiary">
        {t('onboarding.welcome_hint', {
          defaultValue: 'Free and open source. No credit card required.',
        })}
      </p>
    </div>
  );
}

// ── Step 2: "How would you like to start?" ──────────────────────────────────

function StepStartChoice({
  onQuickStart,
  onChooseProfile,
  onBack,
}: {
  onQuickStart: () => void;
  onChooseProfile: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-center">
      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.start_choice_title', { defaultValue: 'How would you like to start?' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.start_choice_subtitle', {
          defaultValue: 'Choose a quick setup or customize your experience.',
        })}
      </p>

      <div className="mt-8 w-full max-w-lg grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Quick Start card */}
        <button
          onClick={onQuickStart}
          className={clsx(
            'group relative flex flex-col items-start rounded-2xl p-6 text-left',
            'border-2 border-border-light bg-surface-elevated',
            'hover:border-oe-blue hover:bg-oe-blue-subtle/20 hover:shadow-lg hover:shadow-oe-blue/5',
            'transition-all duration-300 ease-oe active:scale-[0.98]',
          )}
        >
          <Badge variant="blue" size="sm" className="mb-4">
            {t('onboarding.recommended', { defaultValue: 'Recommended' })}
          </Badge>
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue mb-4 transition-all duration-300 group-hover:bg-oe-blue group-hover:text-white group-hover:shadow-lg group-hover:shadow-oe-blue/20">
            <Sparkles size={24} />
          </div>
          <h3 className="text-lg font-bold text-content-primary">
            {t('onboarding.quick_start', { defaultValue: 'Quick Start' })}
          </h3>
          <p className="mt-2 text-sm text-content-secondary leading-relaxed">
            {t('onboarding.quick_start_desc', {
              defaultValue: 'All essential modules pre-activated. Start working immediately.',
            })}
          </p>
        </button>

        {/* Choose profile card */}
        <button
          onClick={onChooseProfile}
          className={clsx(
            'group relative flex flex-col items-start rounded-2xl p-6 text-left',
            'border-2 border-border-light bg-surface-elevated',
            'hover:border-oe-blue hover:bg-oe-blue-subtle/20 hover:shadow-lg hover:shadow-oe-blue/5',
            'transition-all duration-300 ease-oe active:scale-[0.98]',
          )}
        >
          <div className="h-5 mb-4" aria-hidden />
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-surface-secondary text-content-secondary mb-4 transition-all duration-300 group-hover:bg-oe-blue group-hover:text-white group-hover:shadow-lg group-hover:shadow-oe-blue/20">
            <Settings2 size={24} />
          </div>
          <h3 className="text-lg font-bold text-content-primary">
            {t('onboarding.choose_profile', { defaultValue: 'Choose Your Profile' })}
          </h3>
          <p className="mt-2 text-sm text-content-secondary leading-relaxed">
            {t('onboarding.choose_profile_desc', {
              defaultValue: 'Select your role and customize which modules you need.',
            })}
          </p>
        </button>
      </div>

      <div className="mt-8">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
      </div>
    </div>
  );
}

// ── Step 3: Company Profile (industry cards) ────────────────────────────────

function StepCompanyProfile({
  onNext,
  onBack,
  selectedType,
  onSelectType,
  onConfigureIndividually,
}: {
  onNext: () => void;
  onBack: () => void;
  selectedType: CompanyTypeKey | null;
  onSelectType: (key: CompanyTypeKey) => void;
  onConfigureIndividually: () => void;
}) {
  const { t } = useTranslation();

  const handleSelect = useCallback(
    (key: CompanyTypeKey) => {
      onSelectType(key);
    },
    [onSelectType],
  );

  return (
    <div className="flex flex-col items-center">
      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.profile_title', { defaultValue: 'What best describes your work?' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.profile_subtitle', {
          defaultValue: "We'll pre-select the right modules. You can always change this later.",
        })}
      </p>

      {/* Profile cards: 2 column grid on desktop, 1 on mobile */}
      <div className="mt-6 w-full max-w-2xl grid grid-cols-1 sm:grid-cols-2 gap-3">
        {COMPANY_PRESETS.filter((p) => p.key !== 'full_enterprise').map((preset) => {
          const isSelected = selectedType === preset.key;
          const Icon = preset.icon;
          const moduleCount = preset.enabledModules.length;
          const visibleTags = preset.tags.slice(0, 3);
          const extraCount = moduleCount - visibleTags.length;

          return (
            <button
              key={preset.key}
              onClick={() => handleSelect(preset.key)}
              className={clsx(
                'group relative flex flex-col items-start rounded-2xl p-5 text-left',
                'border-2 transition-all duration-300 ease-oe',
                isSelected
                  ? 'border-oe-blue bg-oe-blue-subtle/30 ring-4 ring-oe-blue/10 shadow-md shadow-oe-blue/5'
                  : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary hover:shadow-sm active:scale-[0.99]',
              )}
            >
              <div className="flex items-center gap-2 mb-3">
                <div
                  className={clsx(
                    'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-all duration-300',
                    isSelected
                      ? 'bg-oe-blue text-white shadow-lg shadow-oe-blue/20'
                      : 'bg-surface-secondary text-content-secondary group-hover:bg-surface-tertiary',
                  )}
                >
                  <Icon size={20} />
                </div>
                {preset.popular && (
                  <Badge variant="blue" size="sm">
                    {t('onboarding.popular', { defaultValue: 'Popular' })}
                  </Badge>
                )}
                {isSelected && (
                  <CheckCircle2 size={16} className="text-oe-blue ml-auto" />
                )}
              </div>

              <h3
                className={clsx(
                  'text-base font-bold transition-colors',
                  isSelected ? 'text-oe-blue' : 'text-content-primary',
                )}
              >
                {t(preset.labelKey, { defaultValue: preset.key })}
              </h3>
              <p className="mt-1 text-sm text-content-secondary leading-snug">
                {t(preset.descriptionKey, { defaultValue: '' })}
              </p>

              {/* Module tags */}
              <div className="mt-3 flex flex-wrap gap-1.5">
                {visibleTags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center rounded-full bg-surface-tertiary px-2 py-0.5 text-2xs font-medium text-content-secondary"
                  >
                    {tag}
                  </span>
                ))}
                {extraCount > 0 && (
                  <span className="inline-flex items-center rounded-full bg-surface-tertiary px-2 py-0.5 text-2xs font-medium text-content-tertiary">
                    +{extraCount} {t('onboarding.more', { defaultValue: 'more' })}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Full Enterprise — wide card */}
      {(() => {
        const enterprise = COMPANY_PRESETS.find((p) => p.key === 'full_enterprise');
        if (!enterprise) return null;
        const isSelected = selectedType === 'full_enterprise';
        const Icon = enterprise.icon;

        return (
          <button
            onClick={() => handleSelect('full_enterprise')}
            className={clsx(
              'mt-3 w-full max-w-2xl group relative flex items-center gap-4 rounded-2xl p-5 text-left',
              'border-2 transition-all duration-300 ease-oe',
              isSelected
                ? 'border-oe-blue bg-oe-blue-subtle/30 ring-4 ring-oe-blue/10 shadow-md shadow-oe-blue/5'
                : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary hover:shadow-sm active:scale-[0.99]',
            )}
          >
            <div
              className={clsx(
                'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-all duration-300',
                isSelected
                  ? 'bg-oe-blue text-white shadow-lg shadow-oe-blue/20'
                  : 'bg-surface-secondary text-content-secondary group-hover:bg-surface-tertiary',
              )}
            >
              <Icon size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h3
                  className={clsx(
                    'text-base font-bold transition-colors',
                    isSelected ? 'text-oe-blue' : 'text-content-primary',
                  )}
                >
                  {t(enterprise.labelKey, { defaultValue: 'Full Enterprise' })}
                </h3>
                {isSelected && <CheckCircle2 size={16} className="text-oe-blue" />}
              </div>
              <p className="mt-0.5 text-sm text-content-secondary">
                {t(enterprise.descriptionKey, {
                  defaultValue: 'Complete construction lifecycle -- everything enabled',
                })}
              </p>
            </div>
            <span
              className={clsx(
                'shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold transition-all',
                isSelected
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-secondary text-content-tertiary',
              )}
            >
              {t('onboarding.all_modules', {
                defaultValue: 'All {{count}} modules',
                count: ALL_MODULES.length,
              })}
            </span>
          </button>
        );
      })()}

      {/* Configure individually button */}
      <button
        onClick={onConfigureIndividually}
        className="mt-4 text-sm font-medium text-oe-blue hover:underline transition-colors"
      >
        {t('onboarding.configure_individually', { defaultValue: 'Configure individually' })}
      </button>

      <div className="mt-6 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button
          variant="primary"
          onClick={onNext}
          disabled={!selectedType}
          icon={<ArrowRight size={16} />}
          iconPosition="right"
        >
          {t('common.continue', { defaultValue: 'Continue' })}
        </Button>
      </div>
    </div>
  );
}

// ── Step 4: Module Configuration (toggle list) ─────────────────────────────

function StepModuleConfig({
  onNext,
  onBack,
  enabledModules,
  onToggleModule,
}: {
  onNext: () => void;
  onBack: () => void;
  enabledModules: Set<string>;
  onToggleModule: (key: string) => void;
}) {
  const { t } = useTranslation();
  const enabledCount = enabledModules.size + CORE_MODULE_KEYS.size;
  const totalCount = ALL_MODULES.length;

  return (
    <div className="flex flex-col items-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle mb-4">
        <Package size={24} className="text-oe-blue" />
      </div>

      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.modules_title', { defaultValue: 'Your Modules' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.modules_subtitle', {
          defaultValue: 'Enable or disable modules as needed. You can change this anytime in Settings.',
        })}
      </p>

      <div className="mt-2 text-sm font-medium text-oe-blue">
        {enabledCount} / {totalCount}{' '}
        {t('onboarding.modules_active', { defaultValue: 'modules active' })}
      </div>

      {/* Module list grouped by category */}
      <div className="mt-4 w-full max-w-2xl max-h-[50vh] overflow-y-auto pr-1 space-y-5 scrollbar-thin">
        {MODULE_GROUPS.map((group) => {
          const groupModules = ALL_MODULES.filter((m) => m.group === group.id);
          if (groupModules.length === 0) return null;

          return (
            <div key={group.id}>
              <h3 className="text-xs font-bold text-content-tertiary uppercase tracking-wider mb-1 px-4">
                {t(group.labelKey, { defaultValue: group.id })}
              </h3>
              <div className="rounded-xl border border-border-light bg-surface-elevated overflow-hidden">
                {groupModules.map((mod) => {
                  const isCore = !!mod.core;
                  const isEnabled = isCore || enabledModules.has(mod.key);
                  return (
                    <div
                      key={mod.key}
                      className="flex items-center justify-between py-2.5 px-4 border-b border-border-light last:border-b-0 gap-3 overflow-hidden"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-content-primary truncate">
                            {t(mod.labelKey, { defaultValue: mod.key })}
                          </span>
                          {isCore && (
                            <Badge variant="blue" size="sm">
                              {t('onboarding.core', { defaultValue: 'Core' })}
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-content-tertiary mt-0.5 truncate">
                          {t(mod.descriptionKey, { defaultValue: '' })}
                        </p>
                      </div>
                      <ToggleSwitch
                        enabled={isEnabled}
                        onToggle={() => !isCore && onToggleModule(mod.key)}
                        disabled={isCore}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button
          variant="primary"
          onClick={onNext}
          icon={<ArrowRight size={16} />}
          iconPosition="right"
        >
          {t('common.continue', { defaultValue: 'Continue' })}
        </Button>
      </div>
    </div>
  );
}

// ── Step 5: Data Setup (combined) ───────────────────────────────────────────

function StepDataSetup({
  onNext,
  onBack,
  selectedLang,
  backgroundLoad,
}: {
  onNext: () => void;
  onBack: () => void;
  selectedLang: string;
  backgroundLoad?: boolean;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const suggestedRegion = getSuggestedRegion(selectedLang);
  const suggestedDemoId = getSuggestedDemo(selectedLang);

  // ── Cost Database state ──
  const [selectedRegion, setSelectedRegion] = useState(suggestedRegion);
  const [loadingDb, setLoadingDb] = useState(false);
  const [loadedDb, setLoadedDb] = useState<{ id: string; count: number } | null>(null);
  const [dbProgress, setDbProgress] = useState(0);

  // ── Demo Project state ──
  const [installDemo, setInstallDemo] = useState(true);
  const [installingDemo, setInstallingDemo] = useState(false);
  const [demoInstalled, setDemoInstalled] = useState(false);

  // ── AI state ──
  const [selectedProvider, setSelectedProvider] = useState<AIProvider>('anthropic');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);

  // ── DB loading progress simulation ──
  useEffect(() => {
    if (!loadingDb) {
      setDbProgress(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(() => {
      const secs = Math.floor((Date.now() - start) / 1000);
      const pct = Math.min(
        95,
        Math.round(
          secs < 3
            ? secs * 8
            : secs < 10
              ? 24 + (secs - 3) * 6
              : secs < 30
                ? 66 + (secs - 10) * 1.2
                : 90 + Math.min(5, (secs - 30) * 0.2),
        ),
      );
      setDbProgress(pct);
    }, 500);
    return () => clearInterval(interval);
  }, [loadingDb]);

  const addQueueTask = useUploadQueueStore((s) => s.addTask);
  const updateQueueTask = useUploadQueueStore((s) => s.updateTask);

  const handleLoadDb = useCallback(async () => {
    if (loadingDb || loadedDb) return;
    setLoadingDb(true);

    const dbName = CWICR_DATABASES.find((d) => d.id === selectedRegion)?.name ?? selectedRegion;
    const taskId = `db-${selectedRegion}-${Date.now()}`;

    // Add to global queue so FloatingQueuePanel shows progress
    addQueueTask({
      id: taskId,
      type: 'import',
      filename: `${dbName} Cost Database`,
      status: 'processing',
      progress: 10,
      message: t('onboarding.db_loading_status', { defaultValue: 'Loading cost database...' }),
    });

    try {
      const token = useAuthStore.getState().accessToken;
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5 * 60 * 1000);

      updateQueueTask(taskId, { progress: 30, message: t('onboarding.db_downloading', { defaultValue: 'Downloading from server...' }) });

      const res = await fetch(`/api/v1/costs/load-cwicr/${selectedRegion}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        updateQueueTask(taskId, { progress: 80, message: t('onboarding.db_importing', { defaultValue: 'Importing items...' }) });

        const data = await res.json();
        const imported = data.imported ?? 0;
        setDbProgress(100);
        setLoadedDb({ id: selectedRegion, count: imported });

        // Update queue task to completed
        updateQueueTask(taskId, {
          status: 'completed',
          progress: 100,
          message: `${imported.toLocaleString()} items imported`,
        });

        try {
          const existing = JSON.parse(
            localStorage.getItem('oe_loaded_databases') || '[]',
          ) as string[];
          if (!existing.includes(selectedRegion)) {
            localStorage.setItem(
              'oe_loaded_databases',
              JSON.stringify([...existing, selectedRegion]),
            );
          }
        } catch {
          // ignore
        }

        addToast({
          type: 'success',
          title: `${dbName} loaded`,
          message: `${imported.toLocaleString()} cost items imported`,
        });
      } else {
        const err = await res.json().catch(() => ({ detail: 'Failed to load database' }));
        updateQueueTask(taskId, { status: 'error', progress: 0, error: err.detail || 'Failed' });
        addToast({
          type: 'error',
          title: 'Failed to load database',
          message: err.detail || 'Unknown error',
        });
      }
    } catch {
      updateQueueTask(taskId, { status: 'error', progress: 0, error: 'Connection error' });
      addToast({
        type: 'error',
        title: t('common.connection_error', { defaultValue: 'Connection error' }),
      });
    } finally {
      setLoadingDb(false);
    }
  }, [loadingDb, loadedDb, selectedRegion, addToast, t]);

  const handleInstallDemo = useCallback(async () => {
    setInstallingDemo(true);
    try {
      await apiPost(`/demo/install/${suggestedDemoId}`);
      setDemoInstalled(true);
      addToast({
        type: 'success',
        title: t('onboarding.demo_installed', { defaultValue: 'Demo project installed' }),
      });
    } catch {
      addToast({
        type: 'error',
        title: t('onboarding.demo_install_error', {
          defaultValue: 'Failed to install demo project',
        }),
      });
    } finally {
      setInstallingDemo(false);
    }
  }, [suggestedDemoId, addToast, t]);

  const testMutation = useMutation({
    mutationFn: () => aiApi.testConnection(selectedProvider),
    onSuccess: (result) => {
      if (result.success) {
        addToast({
          type: 'success',
          title: t('onboarding.ai_test_success', { defaultValue: 'Connection successful!' }),
          message: result.latency_ms ? `${result.latency_ms}ms response time` : undefined,
        });
      } else {
        addToast({
          type: 'error',
          title: t('onboarding.ai_test_failed', { defaultValue: 'Connection failed' }),
          message: result.message,
        });
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('onboarding.ai_test_error', { defaultValue: 'Test failed' }),
        message: err.message,
      });
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!apiKey.trim()) return Promise.resolve(null);
      const keyField = `${selectedProvider}_api_key`;
      return aiApi.updateSettings({
        provider: selectedProvider,
        [keyField]: apiKey.trim(),
      } as Parameters<typeof aiApi.updateSettings>[0]);
    },
    onSuccess: () => {
      if (apiKey.trim()) {
        addToast({
          type: 'success',
          title: t('onboarding.ai_saved', { defaultValue: 'AI settings saved' }),
        });
      }
    },
  });

  const handleContinue = useCallback(async () => {
    // Start background DB loading if region selected but not loaded yet
    if (backgroundLoad && selectedRegion && !loadedDb && !loadingDb) {
      // Fire and forget — don't await, just start in background
      handleLoadDb();
      addToast({
        type: 'info',
        title: t('onboarding.db_loading_bg', { defaultValue: 'Loading database in background...' }),
        message: t('onboarding.db_loading_bg_desc', {
          defaultValue: 'You can continue working. We\'ll notify you when it\'s ready.',
        }),
      });
    }
    // Install demo if toggled on and not yet installed
    if (installDemo && !demoInstalled && !installingDemo) {
      handleInstallDemo(); // also fire and forget in background
    }
    // Save AI key if provided
    if (apiKey.trim()) {
      saveMutation.mutate();
    }
    onNext();
  }, [
    backgroundLoad,
    selectedRegion,
    loadedDb,
    loadingDb,
    handleLoadDb,
    installDemo,
    demoInstalled,
    installingDemo,
    handleInstallDemo,
    apiKey,
    saveMutation,
    onNext,
  ]);

  // Show all regions
  const [aiExpanded, setAiExpanded] = useState(false);

  return (
    <div className="flex flex-col items-center">
      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.data_setup_title', { defaultValue: 'Data Setup' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.data_setup_subtitle', {
          defaultValue: 'Optional setup steps. You can skip any or all of these.',
        })}
      </p>

      <div className="mt-6 w-full max-w-2xl space-y-4">
        {/* Card 1: Cost Database — full width */}
        <div className="rounded-2xl border border-border-light bg-surface-elevated p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
              <Database size={20} />
            </div>
            <div>
              <h3 className="text-base font-bold text-content-primary">
                {t('onboarding.load_cost_db', { defaultValue: 'Load Cost Database' })}
              </h3>
              <p className="text-xs text-content-tertiary">
                {t('onboarding.cost_db_optional', { defaultValue: '55,000+ pricing items' })}
              </p>
            </div>
          </div>

          {/* All regions as selectable cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 mb-3">
            {CWICR_DATABASES.map((db) => {
              const isSelected = selectedRegion === db.id;
              return (
                <button
                  key={db.id}
                  onClick={() => !loadingDb && !loadedDb && setSelectedRegion(db.id)}
                  disabled={loadingDb || !!loadedDb}
                  className={clsx(
                    'flex items-center gap-2 rounded-xl px-3 py-2 text-left border transition-all duration-200',
                    isSelected
                      ? 'border-oe-blue bg-oe-blue-subtle/40 ring-2 ring-oe-blue/20 shadow-sm'
                      : 'border-border-light bg-surface-primary hover:border-border hover:bg-surface-secondary',
                    (loadingDb || !!loadedDb) && 'opacity-60 cursor-not-allowed',
                  )}
                >
                  <CountryFlag code={db.flagId} size={18} className="shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-content-primary truncate">{db.name}</div>
                    <div className="text-2xs text-content-quaternary">{db.currency}</div>
                  </div>
                  {isSelected && <Check size={14} className="text-oe-blue shrink-0" />}
                </button>
              );
            })}
          </div>

          {/* Load button / progress / success */}
          <div>
            {loadedDb ? (
              <div className="flex items-center gap-2 text-sm text-semantic-success">
                <CheckCircle2 size={16} />
                <span className="font-medium">
                  {loadedDb.count.toLocaleString()}{' '}
                  {t('onboarding.items_loaded', { defaultValue: 'items loaded' })}
                </span>
              </div>
            ) : loadingDb ? (
              <div>
                <div className="flex items-center gap-2 text-sm text-content-secondary mb-2">
                  <Loader2 size={14} className="animate-spin text-oe-blue" />
                  <span>{dbProgress}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-500 transition-all duration-500 ease-out"
                    style={{ width: `${dbProgress}%` }}
                  />
                </div>
              </div>
            ) : (
              <Button variant="secondary" size="sm" onClick={handleLoadDb}>
                {t('onboarding.load_database', { defaultValue: 'Load Database' })}
              </Button>
            )}
          </div>
        </div>

        {/* Card 2: Demo Project — full width, simple toggle */}
        <div className="rounded-2xl border border-border-light bg-surface-elevated p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                <FolderOpen size={20} />
              </div>
              <div>
                <h3 className="text-base font-bold text-content-primary">
                  {t('onboarding.install_demo', { defaultValue: 'Install Demo Project' })}
                </h3>
                <p className="text-xs text-content-tertiary">
                  {t('onboarding.demo_optional', { defaultValue: 'Sample project to explore' })}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {demoInstalled ? (
                <div className="flex items-center gap-2 text-sm text-semantic-success">
                  <CheckCircle2 size={16} />
                  <span className="font-medium">
                    {t('onboarding.demo_installed', { defaultValue: 'Installed' })}
                  </span>
                </div>
              ) : installingDemo ? (
                <div className="flex items-center gap-2 text-sm text-content-secondary">
                  <Loader2 size={14} className="animate-spin text-oe-blue" />
                </div>
              ) : (
                <ToggleSwitch
                  enabled={installDemo}
                  onToggle={() => setInstallDemo(!installDemo)}
                />
              )}
            </div>
          </div>
        </div>

        {/* Card 3: AI Provider — collapsible */}
        <div className="rounded-2xl border border-border-light bg-surface-elevated">
          <button
            type="button"
            onClick={() => setAiExpanded(!aiExpanded)}
            className="w-full flex items-center justify-between p-6"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                <Sparkles size={20} />
              </div>
              <div className="text-left">
                <h3 className="text-base font-bold text-content-primary">
                  {t('onboarding.connect_ai', { defaultValue: 'Connect AI Provider' })}
                </h3>
                <p className="text-xs text-content-tertiary">
                  {t('onboarding.ai_optional', { defaultValue: 'Optional — smart estimation features' })}
                </p>
              </div>
            </div>
            <ArrowRight
              size={16}
              className={clsx(
                'text-content-tertiary transition-transform duration-200 shrink-0',
                aiExpanded && 'rotate-90',
              )}
            />
          </button>

          {aiExpanded && (
            <div className="px-6 pb-6 pt-0 space-y-3">
              {/* Provider selector */}
              <select
                value={selectedProvider}
                onChange={(e) => {
                  setSelectedProvider(e.target.value as AIProvider);
                  setApiKey('');
                  setShowKey(false);
                }}
                className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
              >
                {AI_PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.recommended ? ' *' : ''}
                  </option>
                ))}
              </select>

              {/* API key input */}
              <div className="relative">
                <input
                  type="text"
                  value={showKey ? apiKey : apiKey ? maskApiKey(apiKey) : ''}
                  onChange={(e) => {
                    if (showKey) {
                      setApiKey(e.target.value);
                    } else {
                      setApiKey(e.target.value);
                      setShowKey(true);
                    }
                  }}
                  onFocus={() => {
                    if (apiKey && !showKey) setShowKey(true);
                  }}
                  placeholder={t('onboarding.api_key_placeholder', {
                    defaultValue: 'Paste API key...',
                  })}
                  className="h-9 w-full rounded-lg border border-border bg-surface-primary px-3 pr-8 font-mono text-xs text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute inset-y-0 right-0 flex items-center px-2 text-content-tertiary hover:text-content-primary transition-colors"
                  tabIndex={-1}
                >
                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>

              {/* Test and docs link */}
              <div className="flex items-center justify-between">
                <a
                  href={AI_PROVIDERS.find((p) => p.id === selectedProvider)?.docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-2xs text-oe-blue hover:underline"
                >
                  {t('onboarding.get_api_key', { defaultValue: 'Get key' })}
                  <ExternalLink size={10} />
                </a>
                {apiKey.trim() && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => testMutation.mutate()}
                    disabled={testMutation.isPending}
                    icon={
                      testMutation.isPending ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : undefined
                    }
                  >
                    {testMutation.isPending
                      ? t('onboarding.testing', { defaultValue: 'Testing...' })
                      : t('onboarding.test', { defaultValue: 'Test' })}
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <p className="mt-4 text-xs text-content-tertiary text-center max-w-md">
        {t('onboarding.data_setup_hint', {
          defaultValue: 'All of these can be configured later in Settings.',
        })}
      </p>

      <div className="mt-6 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button variant="secondary" onClick={onNext}>
          {t('onboarding.skip', { defaultValue: 'Skip — set up later' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleContinue}
          loading={saveMutation.isPending || installingDemo}
          icon={<ArrowRight size={16} />}
          iconPosition="right"
        >
          {t('common.continue', { defaultValue: 'Continue' })}
        </Button>
      </div>
    </div>
  );
}

// ── Step 6: Summary + Finish ────────────────────────────────────────────────

function StepFinish({
  onBack,
  companyType,
  enabledModules,
}: {
  onBack: () => void;
  companyType: CompanyTypeKey | null;
  enabledModules: Set<string>;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setModuleEnabled = useModuleStore((s) => s.setModuleEnabled);
  const setViewMode = useViewModeStore((s) => s.setMode);
  const [saving, setSaving] = useState(false);

  const presetLabel = companyType
    ? COMPANY_PRESETS.find((p) => p.key === companyType)?.labelKey
    : null;

  const enabledCount = enabledModules.size + CORE_MODULE_KEYS.size;

  const handleFinish = useCallback(async () => {
    setSaving(true);

    // 1. Apply module preferences to the store
    const allModuleKeys = ALL_MODULES.map((m) => m.key);
    for (const key of allModuleKeys) {
      if (!CORE_MODULE_KEYS.has(key)) {
        setModuleEnabled(key, enabledModules.has(key));
      }
    }

    // 2. Apply advanced mode (default for onboarding)
    setViewMode('advanced');

    // 3. Save onboarding state to server
    try {
      await apiPost('/v1/users/me/onboarding', {
        company_type: companyType ?? 'full_enterprise',
        enabled_modules: Array.from(enabledModules),
        interface_mode: 'advanced',
        completed: true,
      });
    } catch {
      // Non-critical -- local state is already applied
    }

    // 4. Mark completed locally
    markOnboardingCompleted();

    setSaving(false);
    navigate('/');
  }, [companyType, enabledModules, navigate, setModuleEnabled, setViewMode]);

  return (
    <div className="flex flex-col items-center justify-center text-center">
      {/* Confetti-like animation via pulsing rings */}
      <div className="relative mb-6">
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-24 w-24 rounded-full bg-semantic-success/5 animate-ping" />
        </div>
        <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-semantic-success-bg/60 ring-4 ring-semantic-success/10">
          <Rocket size={32} className="text-semantic-success" />
        </div>
      </div>

      <h2 className="text-3xl font-bold text-content-primary">
        {t('onboarding.finish_title', { defaultValue: "You're All Set!" })}
      </h2>

      <p className="mt-3 max-w-md text-base text-content-secondary leading-relaxed">
        {t('onboarding.finish_subtitle', {
          defaultValue:
            "Your workspace is configured and ready to use.",
        })}
      </p>

      {/* Summary line */}
      <div className="mt-5 inline-flex items-center gap-2 rounded-full bg-surface-secondary px-4 py-2 text-sm text-content-primary">
        {companyType && presetLabel && (
          <>
            <span className="font-semibold">
              {t(presetLabel, { defaultValue: companyType })}
            </span>
            <span className="text-content-tertiary">|</span>
          </>
        )}
        <span>
          {enabledCount} {t('onboarding.modules_label', { defaultValue: 'modules' })}
        </span>
        <span className="text-content-tertiary">|</span>
        <span>
          {SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language)?.name || i18n.language}
        </span>
      </div>

      <p className="mt-5 text-xs text-content-tertiary max-w-md">
        {t('onboarding.finish_hint', {
          defaultValue: 'You can adjust all settings later from the Settings page.',
        })}
      </p>

      <div className="mt-8 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button
          variant="primary"
          size="lg"
          onClick={handleFinish}
          loading={saving}
          icon={<ArrowRight size={18} />}
          iconPosition="right"
        >
          {t('onboarding.start_working', { defaultValue: 'Start Working' })}
        </Button>
      </div>
    </div>
  );
}

// ── Main Wizard ──────────────────────────────────────────────────────────────

export function OnboardingWizard() {
  const [step, setStep] = useState(0);
  const [selectedLang, setSelectedLang] = useState(() => i18n.language?.split('-')[0] || 'en');
  const [companyType, setCompanyType] = useState<CompanyTypeKey | null>(null);
  const [enabledModules, setEnabledModules] = useState<Set<string>>(
    () => new Set(ALL_MODULES.filter((m) => !m.core).map((m) => m.key)),
  );

  // Track whether user chose "Quick Start" (skip profile + modules, go to data)
  const [quickStart, setQuickStart] = useState(false);
  // Track whether module config step should be shown
  const [showModuleConfig, setShowModuleConfig] = useState(false);

  const goNext = useCallback(() => {
    setStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  }, []);

  const goBack = useCallback(() => {
    setStep((s) => Math.max(s - 1, 0));
  }, []);

  const handleLanguageChange = useCallback((lang: string) => {
    setSelectedLang(lang);
  }, []);

  const handleSelectCompanyType = useCallback((key: CompanyTypeKey) => {
    setCompanyType(key);
    // Apply the preset modules
    const preset = COMPANY_PRESETS.find((p) => p.key === key);
    if (preset) {
      if (key === 'full_enterprise') {
        setEnabledModules(new Set(ALL_MODULES.filter((m) => !m.core).map((m) => m.key)));
      } else {
        setEnabledModules(new Set(preset.enabledModules));
      }
    }
  }, []);

  const handleToggleModule = useCallback((key: string) => {
    setEnabledModules((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  // Step 2 handlers
  const handleQuickStart = useCallback(() => {
    setQuickStart(true);
    setShowModuleConfig(false);
    // Set all modules enabled (full enterprise quick start)
    setEnabledModules(new Set(ALL_MODULES.filter((m) => !m.core).map((m) => m.key)));
    setCompanyType('full_enterprise');
    // Jump to step 4 (data setup) -- step indices: 0=welcome, 1=choice, 2=profile, 3=modules, 4=data, 5=finish
    setStep(4);
  }, []);

  const handleChooseProfile = useCallback(() => {
    setQuickStart(false);
    setShowModuleConfig(false);
    // Go to step 2 (profile)
    setStep(2);
  }, []);

  const handleConfigureIndividually = useCallback(() => {
    setShowModuleConfig(true);
    setStep(3);
  }, []);

  // Handle back from step 4 (data) -- depends on quick start
  const handleBackFromData = useCallback(() => {
    if (quickStart) {
      setStep(1); // back to start choice
    } else if (showModuleConfig) {
      setStep(3); // back to module config
    } else {
      setStep(2); // back to profile
    }
  }, [quickStart, showModuleConfig]);

  // Handle next from step 2 (profile) -- ALWAYS show modules so user can review/customize
  const handleNextFromProfile = useCallback(() => {
    setShowModuleConfig(true);
    setStep(3); // always go to module review
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-surface-primary">
      {/* Top bar with progress */}
      <div className="px-8 pt-6 pb-4 max-w-3xl mx-auto w-full">
        <ProgressBar current={step} total={TOTAL_STEPS} />
      </div>

      {/* Main content area */}
      <div className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-[720px]">
          <StepTransition stepKey={step}>
            {step === 0 && (
              <StepWelcome onNext={goNext} onLanguageChange={handleLanguageChange} />
            )}
            {step === 1 && (
              <StepStartChoice
                onQuickStart={handleQuickStart}
                onChooseProfile={handleChooseProfile}
                onBack={goBack}
              />
            )}
            {step === 2 && (
              <StepCompanyProfile
                onNext={handleNextFromProfile}
                onBack={() => setStep(1)}
                selectedType={companyType}
                onSelectType={handleSelectCompanyType}
                onConfigureIndividually={handleConfigureIndividually}
              />
            )}
            {step === 3 && (
              <StepModuleConfig
                onNext={() => setStep(4)}
                onBack={() => setStep(2)}
                enabledModules={enabledModules}
                onToggleModule={handleToggleModule}
              />
            )}
            {step === 4 && (
              <StepDataSetup
                onNext={() => {
                  // Move to finish — background loading happens inside StepDataSetup
                  setStep(5);
                }}
                onBack={handleBackFromData}
                selectedLang={selectedLang}
                backgroundLoad
              />
            )}
            {step === 5 && (
              <StepFinish
                onBack={() => setStep(4)}
                companyType={companyType}
                enabledModules={enabledModules}
              />
            )}
          </StepTransition>
        </div>
      </div>
    </div>
  );
}
