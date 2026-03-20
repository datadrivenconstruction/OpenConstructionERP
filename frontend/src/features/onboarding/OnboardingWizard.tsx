import { useState, useCallback, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  ArrowLeft,
  Check,
  Sparkles,
  Eye,
  EyeOff,
  ExternalLink,
  Loader2,
  Building2,
  CheckCircle2,
  Database,
} from 'lucide-react';
import { Logo, Button, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi, type CreateProjectData } from '@/features/projects/api';
import { aiApi, type AIProvider } from '@/features/ai/api';

// ── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 4;
const TOKEN_KEY = 'oe_access_token';

interface RegionPreset {
  id: string;
  label: string;
  currency: string;
  standard: string;
  locale: string;
}

const REGIONS: RegionPreset[] = [
  { id: 'DACH', label: 'DACH', currency: 'EUR', standard: 'din276', locale: 'de' },
  { id: 'UK', label: 'UK', currency: 'GBP', standard: 'nrm', locale: 'en' },
  { id: 'US', label: 'US', currency: 'USD', standard: 'masterformat', locale: 'en' },
  { id: 'France', label: 'France', currency: 'EUR', standard: 'din276', locale: 'fr' },
  { id: 'Spain', label: 'Spain', currency: 'EUR', standard: 'din276', locale: 'es' },
  { id: 'Italy', label: 'Italy', currency: 'EUR', standard: 'din276', locale: 'it' },
  { id: 'GulfStates', label: 'Gulf', currency: 'USD', standard: 'din276', locale: 'en' },
  { id: 'INTL', label: 'Other', currency: 'USD', standard: 'masterformat', locale: 'en' },
];

const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'AED', 'BRL', 'RUB', 'CNY', 'INR'] as const;
const STANDARDS = ['din276', 'nrm', 'masterformat'] as const;

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

/** Mini flag component using flagcdn.com */
function MiniFlag({ code }: { code: string }) {
  return (
    <img
      src={`https://flagcdn.com/w40/${code}.png`}
      srcSet={`https://flagcdn.com/w80/${code}.png 2x`}
      width="32"
      height="20"
      alt={code}
      className="rounded-sm shrink-0 shadow-xs border border-black/5 object-cover"
      style={{ width: 32, height: 20 }}
      loading="lazy"
    />
  );
}

// ── Progress Bar ─────────────────────────────────────────────────────────────

function ProgressBar({ current, total }: { current: number; total: number }) {
  const percentage = ((current + 1) / total) * 100;

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          {Array.from({ length: total }).map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold transition-all duration-500 ease-oe ${
                  i < current
                    ? 'bg-oe-blue text-white'
                    : i === current
                      ? 'bg-oe-blue text-white ring-4 ring-oe-blue/20'
                      : 'bg-surface-secondary text-content-tertiary border border-border-light'
                }`}
              >
                {i < current ? <Check size={14} /> : i + 1}
              </div>
              {i < total - 1 && (
                <div
                  className={`h-0.5 w-8 rounded-full transition-colors duration-500 ${
                    i < current ? 'bg-oe-blue' : 'bg-border-light'
                  }`}
                />
              )}
            </div>
          ))}
        </div>
        <span className="text-xs text-content-tertiary tabular-nums">
          {current + 1} / {total}
        </span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className="h-full rounded-full bg-oe-blue transition-all duration-500 ease-oe"
          style={{ width: `${percentage}%` }}
        />
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
        {t('onboarding.welcome_title', { defaultValue: 'Welcome to OpenEstimator.io' })}
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

// ── Step 2: Load Cost Database ───────────────────────────────────────────────

function StepCostDatabase({
  onNext,
  onBack,
}: {
  onNext: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

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
        const token = localStorage.getItem(TOKEN_KEY);
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
        addToast({ type: 'error', title: 'Connection error' });
      } finally {
        setLoading(null);
      }
    },
    [loading, addToast],
  );

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
      <div className="mt-8 w-full max-w-xl grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {CWICR_DATABASES.map((db) => {
          const isLoading = loading === db.id;
          const isLoaded = loadedDb?.id === db.id;
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
        <div className="mt-4 w-full max-w-xl rounded-xl border border-border-light bg-surface-tertiary p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Loader2 size={14} className="animate-spin text-oe-blue" />
              <span className="text-sm font-medium text-content-primary">
                {t('onboarding.loading_database', { defaultValue: 'Importing database...' })}
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
          <p className="mt-2 text-xs text-content-tertiary">
            {t('onboarding.loading_database_hint', {
              defaultValue: 'Loading ~55,000 items. This takes 1-3 minutes.',
            })}
          </p>
        </div>
      )}

      {/* Success message */}
      {loadedDb && !loading && (
        <div className="mt-4 w-full max-w-xl rounded-xl border border-semantic-success/30 bg-semantic-success-bg/40 p-4 animate-fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-semantic-success" />
            <span className="text-sm font-semibold text-[#15803d]">
              {loadedDb.count.toLocaleString()}{' '}
              {t('onboarding.items_loaded', { defaultValue: 'items loaded' })}
            </span>
          </div>
        </div>
      )}

      <p className="mt-4 text-xs text-content-tertiary text-center max-w-md">
        {t('onboarding.cost_db_hint', {
          defaultValue: 'You can add more databases later in Cost Database \u2192 Import.',
        })}
      </p>

      <div className="mt-8 flex items-center gap-3">
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

// ── Step 3: AI Setup ─────────────────────────────────────────────────────────

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

      <div className="mt-10 flex items-center gap-3">
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

// ── Step 4: Create First Project ─────────────────────────────────────────────

function StepCreateProject({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [name, setName] = useState(
    t('onboarding.default_project_name', { defaultValue: 'My First Project' }),
  );
  const [region, setRegion] = useState('DACH');
  const [currency, setCurrency] = useState('EUR');
  const [standard, setStandard] = useState('din276');

  // Sync currency/standard when region changes
  const handleRegionChange = useCallback((regionId: string) => {
    setRegion(regionId);
    const preset = REGIONS.find((r) => r.id === regionId);
    if (preset) {
      setCurrency(preset.currency);
      setStandard(preset.standard);
    }
  }, []);

  const createMutation = useMutation({
    mutationFn: async () => {
      const projectData: CreateProjectData = {
        name: name.trim() || 'My First Project',
        description: 'Created during onboarding',
        region,
        classification_standard: standard,
        currency,
        locale: REGIONS.find((r) => r.id === region)?.locale || 'en',
      };
      return projectsApi.create(projectData);
    },
    onSuccess: (project) => {
      markOnboardingCompleted();
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({
        type: 'success',
        title: t('onboarding.project_created', { defaultValue: 'Project created!' }),
        message: t('onboarding.project_created_msg', {
          defaultValue: "Your workspace is ready. Let's start estimating.",
        }),
      });
      navigate(`/projects/${project.id}`);
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('onboarding.project_error', { defaultValue: 'Failed to create project' }),
        message: err.message,
      });
    },
  });

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      createMutation.mutate();
    },
    [createMutation],
  );

  return (
    <div className="flex flex-col items-center animate-fade-in">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle mb-4">
        <Building2 size={24} className="text-oe-blue" />
      </div>

      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.project_title', { defaultValue: 'Your First Project' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary">
        {t('onboarding.project_subtitle', {
          defaultValue: 'Set up your first project to get started.',
        })}
      </p>

      <form onSubmit={handleSubmit} className="mt-8 w-full max-w-md space-y-5">
        {/* Project name */}
        <Input
          label={t('onboarding.project_name', { defaultValue: 'Project Name' })}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('onboarding.project_name_placeholder', {
            defaultValue: 'e.g. Office Tower Downtown',
          })}
          required
          autoFocus
        />

        {/* Region / Currency / Standard selectors */}
        <div className="grid grid-cols-3 gap-3">
          {/* Region */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('onboarding.region', { defaultValue: 'Region' })}
            </label>
            <select
              value={region}
              onChange={(e) => handleRegionChange(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            >
              {REGIONS.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>

          {/* Currency */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('onboarding.currency', { defaultValue: 'Currency' })}
            </label>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          {/* Standard */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('onboarding.standard', { defaultValue: 'Standard' })}
            </label>
            <select
              value={standard}
              onChange={(e) => setStandard(e.target.value)}
              className="h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
            >
              {STANDARDS.map((s) => (
                <option key={s} value={s}>
                  {s === 'din276' ? 'DIN 276' : s === 'nrm' ? 'NRM' : 'MasterFormat'}
                </option>
              ))}
            </select>
          </div>
        </div>

        {createMutation.error && (
          <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
            {(createMutation.error as Error).message ||
              t('onboarding.create_error', { defaultValue: 'Failed to create project' })}
          </div>
        )}

        <div className="flex items-center gap-3 pt-2">
          <Button variant="ghost" type="button" onClick={onBack} icon={<ArrowLeft size={16} />}>
            {t('common.back', { defaultValue: 'Back' })}
          </Button>
          <Button
            variant="primary"
            type="submit"
            loading={createMutation.isPending}
            icon={<ArrowRight size={16} />}
            iconPosition="right"
            className="flex-1"
          >
            {t('onboarding.create_project', {
              defaultValue: 'Create & Start Estimating',
            })}
          </Button>
        </div>
      </form>
    </div>
  );
}

// ── Main Wizard ──────────────────────────────────────────────────────────────

export function OnboardingWizard() {
  const [step, setStep] = useState(0);

  const goNext = useCallback(() => {
    setStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  }, []);

  const goBack = useCallback(() => {
    setStep((s) => Math.max(s - 1, 0));
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-white">
      {/* Top bar with progress */}
      <div className="px-8 pt-6 pb-4 max-w-3xl mx-auto w-full">
        <ProgressBar current={step} total={TOTAL_STEPS} />
      </div>

      {/* Main content area */}
      <div className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-[600px]">
          {step === 0 && <StepWelcome onNext={goNext} />}
          {step === 1 && <StepCostDatabase onNext={goNext} onBack={goBack} />}
          {step === 2 && <StepAI onNext={goNext} onBack={goBack} />}
          {step === 3 && <StepCreateProject onBack={goBack} />}
        </div>
      </div>
    </div>
  );
}
