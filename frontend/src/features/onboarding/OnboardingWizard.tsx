import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import i18n from 'i18next';
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
  Globe,
  BookOpen,
  FolderOpen,
  Rocket,
  Package,
} from 'lucide-react';
import { Logo, Button, CountryFlag } from '@/shared/ui';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { aiApi, type AIProvider } from '@/features/ai/api';
import { apiPost } from '@/shared/lib/api';

// ── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 7;

// ── Language → Region mapping ──────────────────────────────────────────────

const LANG_TO_REGION: Record<string, string> = {
  de: 'DE_BERLIN',
  fr: 'FR_PARIS',
  es: 'SP_BARCELONA',
  pt: 'PT_SAOPAULO',
  ru: 'RU_STPETERSBURG',
  zh: 'ZH_SHANGHAI',
  ar: 'AR_DUBAI',
  hi: 'HI_MUMBAI',
  en: 'ENG_TORONTO',
  tr: 'ENG_TORONTO',
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

// ── Language → Demo project mapping ────────────────────────────────────────

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
  { id: 'ENG_TORONTO', name: 'English (US / UK / Canada)', city: 'Toronto', lang: 'English', currency: 'USD', flagId: 'us' },
  { id: 'DE_BERLIN', name: 'Germany / DACH', city: 'Berlin', lang: 'Deutsch', currency: 'EUR', flagId: 'de' },
  { id: 'FR_PARIS', name: 'France', city: 'Paris', lang: 'Fran\u00e7ais', currency: 'EUR', flagId: 'fr' },
  { id: 'SP_BARCELONA', name: 'Spain / Latin America', city: 'Barcelona', lang: 'Espa\u00f1ol', currency: 'EUR', flagId: 'es' },
  { id: 'PT_SAOPAULO', name: 'Brazil / Portugal', city: 'S\u00e3o Paulo', lang: 'Portugu\u00eas', currency: 'BRL', flagId: 'br' },
  { id: 'RU_STPETERSBURG', name: 'Russia / CIS', city: 'St. Petersburg', lang: '\u0420\u0443\u0441\u0441\u043a\u0438\u0439', currency: 'RUB', flagId: 'ru' },
  { id: 'AR_DUBAI', name: 'Middle East / Gulf', city: 'Dubai', lang: '\u0627\u0644\u0639\u0631\u0628\u064a\u0629', currency: 'AED', flagId: 'ae' },
  { id: 'ZH_SHANGHAI', name: 'China', city: 'Shanghai', lang: '\u4e2d\u6587', currency: 'CNY', flagId: 'cn' },
  { id: 'HI_MUMBAI', name: 'India / South Asia', city: 'Mumbai', lang: 'Hindi', currency: 'INR', flagId: 'in' },
];

// ── Resource Catalog definitions ────────────────────────────────────────────

interface ResourceCatalog {
  id: string;
  name: string;
  flagId: string;
  itemCount: number;
  lang: string;
}

const RESOURCE_CATALOGS: ResourceCatalog[] = [
  { id: 'ENG_TORONTO', name: 'North America', flagId: 'us', itemCount: 850, lang: 'English' },
  { id: 'DE_BERLIN', name: 'Germany / DACH', flagId: 'de', itemCount: 920, lang: 'Deutsch' },
  { id: 'FR_PARIS', name: 'France', flagId: 'fr', itemCount: 780, lang: 'Fran\u00e7ais' },
  { id: 'SP_BARCELONA', name: 'Spain / LatAm', flagId: 'es', itemCount: 710, lang: 'Espa\u00f1ol' },
  { id: 'PT_SAOPAULO', name: 'Brazil / Portugal', flagId: 'br', itemCount: 650, lang: 'Portugu\u00eas' },
  { id: 'RU_STPETERSBURG', name: 'Russia / CIS', flagId: 'ru', itemCount: 800, lang: '\u0420\u0443\u0441\u0441\u043a\u0438\u0439' },
  { id: 'AR_DUBAI', name: 'Middle East / Gulf', flagId: 'ae', itemCount: 620, lang: '\u0627\u0644\u0639\u0631\u0628\u064a\u0629' },
  { id: 'ZH_SHANGHAI', name: 'China', flagId: 'cn', itemCount: 740, lang: '\u4e2d\u6587' },
  { id: 'HI_MUMBAI', name: 'India / South Asia', flagId: 'in', itemCount: 680, lang: 'Hindi' },
  { id: 'GB_LONDON', name: 'United Kingdom', flagId: 'gb', itemCount: 870, lang: 'English' },
  { id: 'JP_TOKYO', name: 'Japan', flagId: 'jp', itemCount: 590, lang: '\u65e5\u672c\u8a9e' },
];

// ── Demo Project definitions ────────────────────────────────────────────────

interface DemoProject {
  id: string;
  name: string;
  flagId: string;
  description: string;
  budget: string;
  positions: number;
}

const DEMO_PROJECTS: DemoProject[] = [
  {
    id: 'residential-berlin',
    name: 'Residential Complex Berlin',
    flagId: 'de',
    description: '8-storey residential building with underground parking, DIN 276 classification',
    budget: '\u20ac12.4M',
    positions: 340,
  },
  {
    id: 'office-london',
    name: 'Office Tower London',
    flagId: 'gb',
    description: 'Grade A office building, 15 floors, NRM 1/2 compliant estimate',
    budget: '\u00a318.7M',
    positions: 520,
  },
  {
    id: 'school-paris',
    name: 'School Complex Paris',
    flagId: 'fr',
    description: 'Primary school with gymnasium and canteen, French standards',
    budget: '\u20ac6.2M',
    positions: 280,
  },
  {
    id: 'warehouse-dubai',
    name: 'Logistics Warehouse Dubai',
    flagId: 'ae',
    description: 'Climate-controlled warehouse 12,000 m\u00b2 with office block',
    budget: '$8.9M',
    positions: 190,
  },
  {
    id: 'medical-us',
    name: 'Medical Center Houston',
    flagId: 'us',
    description: 'Outpatient medical facility, MasterFormat division structure',
    budget: '$22.1M',
    positions: 610,
  },
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
    // Storage unavailable — ignore.
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

/** Mini flag component — uses bundled inline SVGs */
function MiniFlag({ code }: { code: string }) {
  return <CountryFlag code={code} size={32} className="shadow-xs border border-black/5" />;
}

// ── Progress Bar ─────────────────────────────────────────────────────────────

function ProgressBar({ current, total }: { current: number; total: number }) {
  const { t } = useTranslation();
  const stepLabels = [
    t('onboarding.step_welcome', { defaultValue: 'Welcome' }),
    t('onboarding.step_language', { defaultValue: 'Language' }),
    t('onboarding.step_costdb', { defaultValue: 'Cost DB' }),
    t('onboarding.step_catalog', { defaultValue: 'Catalog' }),
    t('onboarding.step_demos', { defaultValue: 'Demos' }),
    t('onboarding.step_ai', { defaultValue: 'AI' }),
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
                  className={`h-0.5 flex-1 rounded-full transition-colors duration-500 ${
                    i <= current ? 'bg-oe-blue' : 'bg-border-light'
                  }`}
                />
              )}
              <div
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold transition-all duration-500 ease-oe ${
                  i < current
                    ? 'bg-oe-blue text-white'
                    : i === current
                      ? 'bg-oe-blue text-white ring-4 ring-oe-blue/20 scale-110'
                      : 'bg-surface-secondary text-content-tertiary border border-border-light'
                }`}
              >
                {i < current ? <Check size={14} /> : i + 1}
              </div>
              {i < total - 1 && (
                <div
                  className={`h-0.5 flex-1 rounded-full transition-colors duration-500 ${
                    i < current ? 'bg-oe-blue' : 'bg-border-light'
                  }`}
                />
              )}
            </div>
            <span
              className={`text-2xs font-medium transition-colors ${
                i === current
                  ? 'text-oe-blue'
                  : i < current
                    ? 'text-content-secondary'
                    : 'text-content-quaternary'
              }`}
            >
              {stepLabels[i] ?? ''}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Step 1: Welcome ──────────────────────────────────────────────────────────

function StepWelcome({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-center justify-center text-center animate-fade-in">
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

// ── Step 2: Language Selection ───────────────────────────────────────────────

function StepLanguage({
  onNext,
  onBack,
  onLanguageChange,
}: {
  onNext: () => void;
  onBack: () => void;
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
    <div className="flex flex-col items-center animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle mb-4">
        <Globe size={24} className="text-oe-blue" />
      </div>

      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.language_title', { defaultValue: 'Choose Your Language' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.language_subtitle', {
          defaultValue: 'Select the interface language. You can change this anytime in Settings.',
        })}
      </p>

      {/* Language grid */}
      <div className="mt-6 w-full max-w-xl grid grid-cols-3 sm:grid-cols-4 gap-2">
        {SUPPORTED_LANGUAGES.map((lang) => {
          const isSelected = selected === lang.code;
          return (
            <button
              key={lang.code}
              onClick={() => handleSelect(lang.code)}
              className={`
                relative flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-left
                border transition-all duration-normal ease-oe
                ${
                  isSelected
                    ? 'border-oe-blue bg-oe-blue-subtle/40 ring-2 ring-oe-blue/20'
                    : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary active:scale-[0.98]'
                }
              `}
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

      <div className="mt-8 flex items-center gap-3">
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

// ── Step 3: Cost Database ───────────────────────────────────────────────────

function StepCostDatabase({
  onNext,
  onBack,
  selectedLang,
}: {
  onNext: () => void;
  onBack: () => void;
  selectedLang: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const suggestedRegion = getSuggestedRegion(selectedLang);

  const [loading, setLoading] = useState<string | null>(null);
  const [loadedDb, setLoadedDb] = useState<{ id: string; count: number } | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // Timer for elapsed time display
  useEffect(() => {
    if (!loading) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [loading]);

  const handleLoad = useCallback(
    async (db: CWICRDatabase) => {
      if (loading) return;
      setLoading(db.id);

      try {
        const token = useAuthStore.getState().accessToken;
        const res = await fetch(`/api/v1/costs/load-cwicr/${db.id}`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });

        if (res.ok) {
          const data = await res.json();
          const imported = data.imported ?? 0;
          setLoadedDb({ id: db.id, count: imported });

          // Persist to localStorage
          try {
            const existing = JSON.parse(localStorage.getItem('oe_loaded_databases') || '[]') as string[];
            if (!existing.includes(db.id)) {
              localStorage.setItem('oe_loaded_databases', JSON.stringify([...existing, db.id]));
            }
          } catch {
            // ignore
          }

          addToast({
            type: 'success',
            title: `${db.name} loaded`,
            message: `${imported.toLocaleString()} cost items imported`,
          });
        } else {
          const err = await res.json().catch(() => ({ detail: 'Failed to load database' }));
          addToast({
            type: 'error',
            title: `Failed to load ${db.name}`,
            message: err.detail || 'Unknown error',
          });
        }
      } catch {
        addToast({ type: 'error', title: t('common.connection_error', { defaultValue: 'Connection error' }) });
      } finally {
        setLoading(null);
      }
    },
    [loading, addToast, t],
  );

  // Sort databases with suggested region first
  const sortedDatabases = [...CWICR_DATABASES].sort((a, b) => {
    if (a.id === suggestedRegion) return -1;
    if (b.id === suggestedRegion) return 1;
    return 0;
  });

  return (
    <div className="flex flex-col items-center animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle mb-4">
        <Database size={24} className="text-oe-blue" />
      </div>

      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.cost_db_title', { defaultValue: 'Cost Database' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.cost_db_subtitle', {
          defaultValue: 'Load a pricing database for accurate estimates. Choose your region:',
        })}
      </p>

      {/* Database grid */}
      <div className="mt-6 w-full max-w-xl grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {sortedDatabases.map((db) => {
          const isLoading = loading === db.id;
          const isLoaded = loadedDb?.id === db.id;
          const isSuggested = db.id === suggestedRegion && !loadedDb;
          return (
            <button
              key={db.id}
              onClick={() => handleLoad(db)}
              disabled={isLoading || (loading !== null && loading !== db.id)}
              className={`
                relative flex items-center gap-3 rounded-xl px-3.5 py-3 text-left
                border transition-all duration-normal ease-oe
                ${isLoaded
                  ? 'border-semantic-success/30 bg-semantic-success-bg/40'
                  : isLoading
                    ? 'border-oe-blue/40 bg-oe-blue-subtle/30'
                    : isSuggested
                      ? 'border-oe-blue/30 bg-oe-blue-subtle/20 ring-1 ring-oe-blue/10'
                      : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary active:scale-[0.98]'
                }
                ${loading !== null && !isLoading && !isLoaded ? 'opacity-40 pointer-events-none' : ''}
              `}
            >
              <MiniFlag code={db.flagId} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-content-primary">{db.name}</span>
                  {isLoaded && (
                    <CheckCircle2 size={14} className="text-semantic-success shrink-0" />
                  )}
                  {isSuggested && !isLoading && (
                    <span className="inline-flex items-center rounded-full bg-oe-blue-subtle px-1.5 py-0.5 text-2xs font-medium text-oe-blue">
                      {t('onboarding.suggested', { defaultValue: 'Suggested' })}
                    </span>
                  )}
                </div>
                <div className="text-2xs text-content-tertiary">
                  {db.city} · {db.lang} · {db.currency}
                </div>
              </div>
              {isLoading && (
                <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" />
              )}
            </button>
          );
        })}
      </div>

      {/* Loading progress */}
      {loading && (
        <div className="mt-4 w-full max-w-xl rounded-xl border border-oe-blue/20 bg-oe-blue-subtle/10 p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Loader2 size={16} className="animate-spin text-oe-blue" />
              <span className="text-sm font-medium text-content-primary">
                {t('onboarding.loading_database', { defaultValue: 'Importing 55,000+ cost items...' })}
              </span>
            </div>
            <span className="text-xs font-mono text-oe-blue bg-oe-blue-subtle rounded-full px-2 py-0.5">{elapsed}s</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div
              className="h-full rounded-full bg-gradient-to-r from-oe-blue via-blue-400 to-oe-blue animate-[indeterminate_1.5s_ease-in-out_infinite]"
              style={{ width: '40%' }}
            />
          </div>
          <div className="mt-2 flex items-center gap-4 text-xs text-content-tertiary">
            <span>{t('onboarding.loading_step1', { defaultValue: 'Downloading regional pricing data...' })}</span>
            <span className="ml-auto">{t('onboarding.loading_database_hint', { defaultValue: '~1-3 minutes' })}</span>
          </div>
        </div>
      )}

      {/* Success message */}
      {loadedDb && !loading && (() => {
        const loadedInfo = CWICR_DATABASES.find((d) => d.id === loadedDb.id);
        return (
          <div className="mt-4 w-full max-w-xl rounded-xl border border-semantic-success/30 bg-semantic-success-bg/40 p-4 animate-fade-in">
            <div className="flex items-center gap-3">
              {loadedInfo && <MiniFlag code={loadedInfo.flagId} />}
              <div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-semantic-success" />
                  <span className="text-sm font-semibold text-semantic-success">
                    {loadedInfo?.name ?? loadedDb.id}
                  </span>
                </div>
                <span className="text-xs text-content-secondary">
                  {loadedDb.count.toLocaleString()}{' '}
                  {t('onboarding.items_loaded', { defaultValue: 'cost items loaded successfully' })}
                </span>
              </div>
            </div>
          </div>
        );
      })()}

      <p className="mt-4 text-xs text-content-tertiary text-center max-w-md">
        {t('onboarding.cost_db_hint', {
          defaultValue: 'You can add more databases later in Cost Database \u2192 Import.',
        })}
      </p>

      <div className="mt-6 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button variant="secondary" onClick={onNext}>
          {t('onboarding.skip', { defaultValue: 'Skip' })}
        </Button>
        {loadedDb && (
          <Button
            variant="primary"
            onClick={onNext}
            icon={<ArrowRight size={16} />}
            iconPosition="right"
          >
            {t('common.continue', { defaultValue: 'Continue' })}
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Step 4: Resource Catalog ────────────────────────────────────────────────

function StepResourceCatalog({
  onNext,
  onBack,
  selectedLang,
}: {
  onNext: () => void;
  onBack: () => void;
  selectedLang: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const suggestedRegion = getSuggestedRegion(selectedLang);

  const [loading, setLoading] = useState<string | null>(null);
  const [loadedCatalog, setLoadedCatalog] = useState<{ id: string; count: number } | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // Timer for elapsed time display
  useEffect(() => {
    if (!loading) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [loading]);

  const handleLoad = useCallback(
    async (catalog: ResourceCatalog) => {
      if (loading) return;
      setLoading(catalog.id);

      try {
        const data = await apiPost<{ imported: number }>(`/v1/catalog/import/${catalog.id}`);
        const imported = data.imported ?? catalog.itemCount;
        setLoadedCatalog({ id: catalog.id, count: imported });

        addToast({
          type: 'success',
          title: `${catalog.name} catalog loaded`,
          message: `${imported.toLocaleString()} resources imported`,
        });
      } catch {
        addToast({
          type: 'error',
          title: t('common.connection_error', { defaultValue: 'Connection error' }),
          message: t('onboarding.catalog_error', { defaultValue: 'Failed to import resource catalog' }),
        });
      } finally {
        setLoading(null);
      }
    },
    [loading, addToast, t],
  );

  // Sort catalogs with suggested region first
  const sortedCatalogs = [...RESOURCE_CATALOGS].sort((a, b) => {
    if (a.id === suggestedRegion) return -1;
    if (b.id === suggestedRegion) return 1;
    return 0;
  });

  return (
    <div className="flex flex-col items-center animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle mb-4">
        <BookOpen size={24} className="text-oe-blue" />
      </div>

      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.catalog_title', { defaultValue: 'Resource Catalog' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.catalog_subtitle', {
          defaultValue: 'Load a catalog of materials, labor, equipment, and assemblies for your region:',
        })}
      </p>

      {/* Catalog grid */}
      <div className="mt-6 w-full max-w-xl grid grid-cols-2 sm:grid-cols-3 gap-2.5">
        {sortedCatalogs.map((catalog) => {
          const isLoading = loading === catalog.id;
          const isLoaded = loadedCatalog?.id === catalog.id;
          const isSuggested = catalog.id === suggestedRegion && !loadedCatalog;
          return (
            <button
              key={catalog.id}
              onClick={() => handleLoad(catalog)}
              disabled={isLoading || (loading !== null && loading !== catalog.id)}
              className={`
                relative flex items-center gap-3 rounded-xl px-3.5 py-3 text-left
                border transition-all duration-normal ease-oe
                ${isLoaded
                  ? 'border-semantic-success/30 bg-semantic-success-bg/40'
                  : isLoading
                    ? 'border-oe-blue/40 bg-oe-blue-subtle/30'
                    : isSuggested
                      ? 'border-oe-blue/30 bg-oe-blue-subtle/20 ring-1 ring-oe-blue/10'
                      : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary active:scale-[0.98]'
                }
                ${loading !== null && !isLoading && !isLoaded ? 'opacity-40 pointer-events-none' : ''}
              `}
            >
              <MiniFlag code={catalog.flagId} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-content-primary truncate">{catalog.name}</span>
                  {isLoaded && (
                    <CheckCircle2 size={14} className="text-semantic-success shrink-0" />
                  )}
                  {isSuggested && !isLoading && (
                    <span className="inline-flex items-center rounded-full bg-oe-blue-subtle px-1.5 py-0.5 text-2xs font-medium text-oe-blue">
                      {t('onboarding.suggested', { defaultValue: 'Suggested' })}
                    </span>
                  )}
                </div>
                <div className="text-2xs text-content-tertiary">
                  {catalog.lang} · {catalog.itemCount.toLocaleString()} {t('onboarding.items', { defaultValue: 'items' })}
                </div>
              </div>
              {isLoading && (
                <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" />
              )}
            </button>
          );
        })}
      </div>

      {/* Loading progress */}
      {loading && (
        <div className="mt-4 w-full max-w-xl rounded-xl border border-border-light bg-surface-tertiary p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Loader2 size={14} className="animate-spin text-oe-blue" />
              <span className="text-sm font-medium text-content-primary">
                {t('onboarding.loading_catalog', { defaultValue: 'Importing resource catalog...' })}
              </span>
            </div>
            <span className="text-xs text-content-tertiary font-mono">{elapsed}s</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div
              className="h-full animate-shimmer rounded-full bg-oe-blue opacity-70 bg-[length:200%_100%]"
              style={{ width: '100%' }}
            />
          </div>
        </div>
      )}

      {/* Success message */}
      {loadedCatalog && !loading && (
        <div className="mt-4 w-full max-w-xl rounded-xl border border-semantic-success/30 bg-semantic-success-bg/40 p-4 animate-fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-semantic-success" />
            <span className="text-sm font-semibold text-semantic-success">
              {loadedCatalog.count.toLocaleString()}{' '}
              {t('onboarding.resources_loaded', { defaultValue: 'resources loaded' })}
            </span>
          </div>
        </div>
      )}

      <p className="mt-4 text-xs text-content-tertiary text-center max-w-md">
        {t('onboarding.catalog_hint', {
          defaultValue: 'Catalogs include materials, labor rates, equipment, and pre-built assemblies.',
        })}
      </p>

      <div className="mt-6 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button variant="secondary" onClick={onNext}>
          {t('onboarding.skip', { defaultValue: 'Skip' })}
        </Button>
        {loadedCatalog && (
          <Button
            variant="primary"
            onClick={onNext}
            icon={<ArrowRight size={16} />}
            iconPosition="right"
          >
            {t('common.continue', { defaultValue: 'Continue' })}
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Step 5: Demo Projects ───────────────────────────────────────────────────

function StepDemoProjects({
  onNext,
  onBack,
  selectedLang,
}: {
  onNext: () => void;
  onBack: () => void;
  selectedLang: string;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const suggestedDemoId = getSuggestedDemo(selectedLang);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => {
    return new Set([suggestedDemoId]);
  });
  const [installing, setInstalling] = useState(false);
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set());
  const [progress, setProgress] = useState({ current: 0, total: 0 });

  const toggleProject = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleInstall = useCallback(async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    setInstalling(true);
    setProgress({ current: 0, total: ids.length });

    const installed = new Set<string>();

    for (let i = 0; i < ids.length; i++) {
      const demoId = ids[i]!;
      setProgress({ current: i + 1, total: ids.length });
      try {
        await apiPost(`/demo/install/${demoId}`);
        installed.add(demoId);
      } catch {
        addToast({
          type: 'error',
          title: t('onboarding.demo_install_error', { defaultValue: 'Failed to install demo project' }),
          message: demoId,
        });
      }
    }

    setInstalledIds(installed);
    setInstalling(false);

    if (installed.size > 0) {
      addToast({
        type: 'success',
        title: t('onboarding.demo_installed', { defaultValue: 'Demo projects installed' }),
        message: `${installed.size} / ${ids.length}`,
      });
    }
  }, [selectedIds, addToast, t]);

  const allInstalled = installedIds.size > 0 && !installing;

  return (
    <div className="flex flex-col items-center animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle mb-4">
        <FolderOpen size={24} className="text-oe-blue" />
      </div>

      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.demo_title', { defaultValue: 'Demo Projects' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.demo_subtitle', {
          defaultValue: 'Install sample projects to explore the platform. Select one or more:',
        })}
      </p>

      {/* Demo project cards */}
      <div className="mt-6 w-full max-w-xl space-y-2.5">
        {DEMO_PROJECTS.map((project) => {
          const isSelected = selectedIds.has(project.id);
          const isInstalled = installedIds.has(project.id);
          const isSuggested = project.id === suggestedDemoId;
          return (
            <button
              key={project.id}
              onClick={() => !installing && !allInstalled && toggleProject(project.id)}
              disabled={installing || allInstalled}
              className={`
                relative flex w-full items-start gap-3.5 rounded-xl px-4 py-3.5 text-left
                border transition-all duration-normal ease-oe
                ${isInstalled
                  ? 'border-semantic-success/30 bg-semantic-success-bg/40'
                  : isSelected
                    ? 'border-oe-blue/40 bg-oe-blue-subtle/20 ring-1 ring-oe-blue/10'
                    : 'border-border-light bg-surface-elevated hover:border-border hover:bg-surface-secondary'
                }
                ${installing ? 'pointer-events-none' : ''}
              `}
            >
              {/* Checkbox */}
              <div
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border-2 transition-all duration-fast ${
                  isSelected || isInstalled
                    ? isInstalled
                      ? 'border-semantic-success bg-semantic-success'
                      : 'border-oe-blue bg-oe-blue'
                    : 'border-content-tertiary bg-transparent'
                }`}
              >
                {(isSelected || isInstalled) && <Check size={12} className="text-white" />}
              </div>

              <MiniFlag code={project.flagId} />

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-content-primary">{project.name}</span>
                  {isSuggested && !isInstalled && (
                    <span className="inline-flex items-center rounded-full bg-oe-blue-subtle px-1.5 py-0.5 text-2xs font-medium text-oe-blue">
                      {t('onboarding.suggested', { defaultValue: 'Suggested' })}
                    </span>
                  )}
                  {isInstalled && (
                    <CheckCircle2 size={14} className="text-semantic-success shrink-0" />
                  )}
                </div>
                <p className="mt-0.5 text-xs text-content-secondary leading-relaxed">
                  {project.description}
                </p>
                <div className="mt-1.5 flex items-center gap-3 text-2xs text-content-tertiary">
                  <span>{t('onboarding.budget', { defaultValue: 'Budget' })}: {project.budget}</span>
                  <span>{project.positions} {t('onboarding.positions', { defaultValue: 'positions' })}</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Install progress */}
      {installing && (
        <div className="mt-4 w-full max-w-xl rounded-xl border border-border-light bg-surface-tertiary p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Loader2 size={14} className="animate-spin text-oe-blue" />
              <span className="text-sm font-medium text-content-primary">
                {t('onboarding.installing_demos', { defaultValue: 'Installing demo projects...' })}
              </span>
            </div>
            <span className="text-xs text-content-tertiary font-mono">
              {progress.current} / {progress.total}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div
              className="h-full rounded-full bg-oe-blue transition-all duration-300 ease-oe"
              style={{ width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-6 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button variant="secondary" onClick={onNext}>
          {t('onboarding.skip', { defaultValue: 'Skip' })}
        </Button>
        {!allInstalled && selectedIds.size > 0 && (
          <Button
            variant="primary"
            onClick={handleInstall}
            loading={installing}
            icon={<Package size={16} />}
          >
            {t('onboarding.install_selected', { defaultValue: 'Install Selected' })} ({selectedIds.size})
          </Button>
        )}
        {allInstalled && (
          <Button
            variant="primary"
            onClick={onNext}
            icon={<ArrowRight size={16} />}
            iconPosition="right"
          >
            {t('common.continue', { defaultValue: 'Continue' })}
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Step 6: AI Setup ────────────────────────────────────────────────────────

function StepAI({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedProvider, setSelectedProvider] = useState<AIProvider>('anthropic');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);

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
      onNext();
    },
    onError: () => {
      // Even if save fails, let them proceed
      onNext();
    },
  });

  const handleContinue = useCallback(() => {
    if (apiKey.trim()) {
      saveMutation.mutate();
    } else {
      onNext();
    }
  }, [apiKey, saveMutation, onNext]);

  return (
    <div className="flex flex-col items-center animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle mb-4">
        <Sparkles size={24} className="text-oe-blue" />
      </div>

      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.ai_title', {
          defaultValue: 'AI Provider (Optional)',
        })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.ai_subtitle', {
          defaultValue: 'Connect an AI provider for smart features:',
        })}
      </p>

      {/* Feature list */}
      <ul className="mt-4 space-y-1.5 text-sm text-content-secondary max-w-md w-full">
        <li className="flex items-center gap-2">
          <span className="text-content-tertiary">&bull;</span>
          {t('onboarding.ai_feature_1', { defaultValue: 'Generate estimates from text descriptions' })}
        </li>
        <li className="flex items-center gap-2">
          <span className="text-content-tertiary">&bull;</span>
          {t('onboarding.ai_feature_2', { defaultValue: 'Analyze photos of buildings' })}
        </li>
        <li className="flex items-center gap-2">
          <span className="text-content-tertiary">&bull;</span>
          {t('onboarding.ai_feature_3', { defaultValue: 'Parse PDF documents automatically' })}
        </li>
      </ul>

      {/* Provider selection */}
      <div className="mt-6 w-full max-w-md space-y-2">
        {AI_PROVIDERS.map((provider) => {
          const isSelected = selectedProvider === provider.id;
          return (
            <button
              key={provider.id}
              type="button"
              onClick={() => {
                setSelectedProvider(provider.id);
                setApiKey('');
                setShowKey(false);
              }}
              className={`relative flex w-full items-center gap-3 rounded-xl px-4 py-3.5 text-left transition-all duration-normal ease-oe ${
                isSelected
                  ? 'bg-oe-blue-subtle border-2 border-oe-blue ring-2 ring-oe-blue/10'
                  : 'border-2 border-border-light hover:bg-surface-secondary hover:border-border'
              }`}
            >
              <div
                className={`h-4 w-4 shrink-0 rounded-full border-2 transition-colors duration-fast ${
                  isSelected
                    ? 'border-oe-blue bg-oe-blue'
                    : 'border-content-tertiary bg-transparent'
                }`}
              >
                {isSelected && (
                  <div className="flex h-full w-full items-center justify-center">
                    <div className="h-1.5 w-1.5 rounded-full bg-white" />
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-sm font-semibold ${
                      isSelected ? 'text-oe-blue' : 'text-content-primary'
                    }`}
                  >
                    {provider.name}
                  </span>
                  {provider.recommended && (
                    <span className="inline-flex items-center rounded-full bg-oe-blue-subtle px-1.5 py-0.5 text-2xs font-medium text-oe-blue">
                      {t('onboarding.recommended', { defaultValue: 'Recommended' })}
                    </span>
                  )}
                </div>
                <p className="text-xs text-content-secondary mt-0.5">
                  {provider.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      {/* API Key input */}
      <div className="mt-6 w-full max-w-md">
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-sm font-medium text-content-primary">
            {t('onboarding.api_key', { defaultValue: 'API Key' })}
          </label>
          <a
            href={AI_PROVIDERS.find((p) => p.id === selectedProvider)?.docsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-oe-blue hover:underline"
          >
            {t('onboarding.get_api_key', { defaultValue: 'Get an API key' })}
            <ExternalLink size={11} />
          </a>
        </div>
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
              defaultValue: 'Paste your API key here...',
            })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 pr-20 font-mono text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-normal ease-oe hover:border-content-tertiary"
          />
          <button
            type="button"
            onClick={() => setShowKey(!showKey)}
            className="absolute inset-y-0 right-0 flex items-center px-3 text-content-tertiary hover:text-content-primary transition-colors duration-fast"
            tabIndex={-1}
          >
            {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            <span className="ml-1 text-xs">{showKey ? 'Hide' : 'Show'}</span>
          </button>
        </div>

        {apiKey.trim() && (
          <div className="mt-3 flex justify-start">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending}
              icon={
                testMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : undefined
              }
            >
              {testMutation.isPending
                ? t('onboarding.testing', { defaultValue: 'Testing...' })
                : t('onboarding.test_connection', { defaultValue: 'Test Connection' })}
            </Button>
          </div>
        )}
      </div>

      <div className="mt-8 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button variant="secondary" onClick={onNext}>
          {t('onboarding.skip', { defaultValue: 'Skip' })}
        </Button>
        {apiKey.trim() && (
          <Button
            variant="primary"
            onClick={handleContinue}
            loading={saveMutation.isPending}
            icon={<ArrowRight size={16} />}
            iconPosition="right"
          >
            {t('onboarding.save_continue', { defaultValue: 'Save & Continue' })}
          </Button>
        )}
      </div>
    </div>
  );
}

// ── Step 7: Finish ──────────────────────────────────────────────────────────

function StepFinish({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // Gather what was installed from localStorage
  const loadedDbs = (() => {
    try {
      return JSON.parse(localStorage.getItem('oe_loaded_databases') || '[]') as string[];
    } catch {
      return [];
    }
  })();

  const handleFinish = useCallback(() => {
    markOnboardingCompleted();
    navigate('/');
  }, [navigate]);

  return (
    <div className="flex flex-col items-center justify-center text-center animate-fade-in">
      <div className="mb-6">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-semantic-success-bg/60 ring-4 ring-semantic-success/10">
          <Rocket size={32} className="text-semantic-success" />
        </div>
      </div>

      <h2 className="text-3xl font-bold text-content-primary">
        {t('onboarding.finish_title', { defaultValue: 'You\'re All Set!' })}
      </h2>

      <p className="mt-3 max-w-md text-base text-content-secondary leading-relaxed">
        {t('onboarding.finish_subtitle', {
          defaultValue: 'Your workspace is configured and ready to use. Here\'s a summary of what was set up:',
        })}
      </p>

      {/* Summary card */}
      <div className="mt-6 w-full max-w-md rounded-xl border border-border-light bg-surface-elevated p-5 text-left space-y-3">
        {/* Language */}
        <div className="flex items-center gap-3">
          <Globe size={16} className="text-oe-blue shrink-0" />
          <span className="text-sm text-content-primary">
            {t('onboarding.summary_language', { defaultValue: 'Language' })}:
          </span>
          <span className="text-sm font-semibold text-content-primary ml-auto">
            {SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language)?.name || i18n.language}
          </span>
        </div>

        {/* Cost DB */}
        <div className="flex items-center gap-3">
          <Database size={16} className="text-oe-blue shrink-0" />
          <span className="text-sm text-content-primary">
            {t('onboarding.summary_cost_db', { defaultValue: 'Cost Database' })}:
          </span>
          <span className="text-sm font-semibold text-content-primary ml-auto">
            {loadedDbs.length > 0
              ? loadedDbs.map((id) => CWICR_DATABASES.find((d) => d.id === id)?.name || id).join(', ')
              : t('onboarding.summary_skipped', { defaultValue: 'Skipped' })}
          </span>
        </div>

        {/* Resource Catalog */}
        <div className="flex items-center gap-3">
          <BookOpen size={16} className="text-oe-blue shrink-0" />
          <span className="text-sm text-content-primary">
            {t('onboarding.summary_catalog', { defaultValue: 'Resource Catalog' })}:
          </span>
          <span className="text-sm font-semibold text-content-primary ml-auto">
            <CheckCircle2 size={14} className="inline text-semantic-success" />
          </span>
        </div>

        {/* AI */}
        <div className="flex items-center gap-3">
          <Sparkles size={16} className="text-oe-blue shrink-0" />
          <span className="text-sm text-content-primary">
            {t('onboarding.summary_ai', { defaultValue: 'AI Provider' })}:
          </span>
          <span className="text-sm font-semibold text-content-primary ml-auto">
            <CheckCircle2 size={14} className="inline text-semantic-success" />
          </span>
        </div>
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
          icon={<ArrowRight size={18} />}
          iconPosition="right"
        >
          {t('onboarding.go_to_dashboard', { defaultValue: 'Go to Dashboard' })}
        </Button>
      </div>
    </div>
  );
}

// ── Main Wizard ──────────────────────────────────────────────────────────────

export function OnboardingWizard() {
  const [step, setStep] = useState(0);
  const [selectedLang, setSelectedLang] = useState(() => i18n.language?.split('-')[0] || 'en');

  const goNext = useCallback(() => {
    setStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  }, []);

  const goBack = useCallback(() => {
    setStep((s) => Math.max(s - 1, 0));
  }, []);

  const handleLanguageChange = useCallback((lang: string) => {
    setSelectedLang(lang);
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-surface-primary">
      {/* Top bar with progress */}
      <div className="px-8 pt-6 pb-4 max-w-4xl mx-auto w-full">
        <ProgressBar current={step} total={TOTAL_STEPS} />
      </div>

      {/* Main content area */}
      <div className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-[640px]">
          {step === 0 && <StepWelcome onNext={goNext} />}
          {step === 1 && (
            <StepLanguage onNext={goNext} onBack={goBack} onLanguageChange={handleLanguageChange} />
          )}
          {step === 2 && <StepCostDatabase onNext={goNext} onBack={goBack} selectedLang={selectedLang} />}
          {step === 3 && <StepResourceCatalog onNext={goNext} onBack={goBack} selectedLang={selectedLang} />}
          {step === 4 && <StepDemoProjects onNext={goNext} onBack={goBack} selectedLang={selectedLang} />}
          {step === 5 && <StepAI onNext={goNext} onBack={goBack} />}
          {step === 6 && <StepFinish onBack={goBack} />}
        </div>
      </div>
    </div>
  );
}
