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
} from 'lucide-react';
import { Logo, Button, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi, type CreateProjectData } from '@/features/projects/api';
import { aiApi, type AIProvider } from '@/features/ai/api';

// ── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 4;

interface RegionPreset {
  id: string;
  flag: string;
  label: string;
  currency: string;
  standard: string;
  locale: string;
}

const REGIONS: RegionPreset[] = [
  { id: 'DACH', flag: '\uD83C\uDDE9\uD83C\uDDEA', label: 'DACH', currency: 'EUR', standard: 'din276', locale: 'de' },
  { id: 'UK', flag: '\uD83C\uDDEC\uD83C\uDDE7', label: 'UK', currency: 'GBP', standard: 'nrm', locale: 'en' },
  { id: 'US', flag: '\uD83C\uDDFA\uD83C\uDDF8', label: 'US', currency: 'USD', standard: 'masterformat', locale: 'en' },
  { id: 'France', flag: '\uD83C\uDDEB\uD83C\uDDF7', label: 'France', currency: 'EUR', standard: 'din276', locale: 'fr' },
  { id: 'Spain', flag: '\uD83C\uDDEA\uD83C\uDDF8', label: 'Spain', currency: 'EUR', standard: 'din276', locale: 'es' },
  { id: 'Italy', flag: '\uD83C\uDDEE\uD83C\uDDF9', label: 'Italy', currency: 'EUR', standard: 'din276', locale: 'it' },
  { id: 'GulfStates', flag: '\uD83C\uDDE6\uD83C\uDDEA', label: 'Gulf', currency: 'USD', standard: 'din276', locale: 'en' },
  { id: 'INTL', flag: '\uD83C\uDF0D', label: 'Other', currency: 'USD', standard: 'masterformat', locale: 'en' },
];

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

const PROJECT_TEMPLATES = [
  { id: 'residential', label: 'Residential', icon: '\uD83C\uDFE0' },
  { id: 'office', label: 'Office', icon: '\uD83C\uDFE2' },
  { id: 'warehouse', label: 'Warehouse', icon: '\uD83C\uDFED' },
  { id: 'school', label: 'School', icon: '\uD83C\uDFEB' },
  { id: 'hospital', label: 'Hospital', icon: '\uD83C\uDFE5' },
  { id: 'hotel', label: 'Hotel', icon: '\uD83C\uDFE8' },
  { id: 'retail', label: 'Retail', icon: '\uD83D\uDED2' },
  { id: 'infrastructure', label: 'Infrastructure', icon: '\uD83C\uDF09' },
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

// ── Progress Bar ─────────────────────────────────────────────────────────────

function ProgressDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div
            className={`h-2.5 rounded-full transition-all duration-500 ease-oe ${
              i < current
                ? 'w-2.5 bg-oe-blue'
                : i === current
                  ? 'w-8 bg-oe-blue'
                  : 'w-2.5 bg-border'
            }`}
          />
        </div>
      ))}
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
          defaultValue: 'The professional construction cost estimation platform. Let\'s set up your workspace in 2 minutes.',
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

// ── Step 2: Region ───────────────────────────────────────────────────────────

function StepRegion({
  selected,
  onSelect,
  onNext,
  onBack,
}: {
  selected: RegionPreset | null;
  onSelect: (region: RegionPreset) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-center animate-fade-in">
      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.region_title', { defaultValue: 'Where do you work?' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary max-w-md text-center">
        {t('onboarding.region_subtitle', {
          defaultValue:
            'This sets your default currency, classification standard, and language.',
        })}
      </p>

      <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3 w-full max-w-lg">
        {REGIONS.map((region) => {
          const isSelected = selected?.id === region.id;
          return (
            <button
              key={region.id}
              type="button"
              onClick={() => onSelect(region)}
              className={`flex flex-col items-center gap-2 rounded-2xl px-4 py-5 transition-all duration-normal ease-oe ${
                isSelected
                  ? 'bg-oe-blue-subtle border-2 border-oe-blue ring-2 ring-oe-blue/10 scale-[1.02]'
                  : 'border-2 border-border-light bg-surface-elevated hover:bg-surface-secondary hover:border-border hover:scale-[1.01]'
              }`}
            >
              <span className="text-3xl">{region.flag}</span>
              <span
                className={`text-sm font-semibold ${
                  isSelected ? 'text-oe-blue' : 'text-content-primary'
                }`}
              >
                {region.label}
              </span>
            </button>
          );
        })}
      </div>

      {selected && (
        <div className="mt-5 flex items-center gap-4 text-xs text-content-tertiary animate-fade-in">
          <span>
            {t('onboarding.region_currency', { defaultValue: 'Currency' })}:{' '}
            <strong className="text-content-secondary">{selected.currency}</strong>
          </span>
          <span className="text-border">|</span>
          <span>
            {t('onboarding.region_standard', { defaultValue: 'Standard' })}:{' '}
            <strong className="text-content-secondary">
              {selected.standard.toUpperCase()}
            </strong>
          </span>
          <span className="text-border">|</span>
          <span>
            {t('onboarding.region_locale', { defaultValue: 'Language' })}:{' '}
            <strong className="text-content-secondary">{selected.locale}</strong>
          </span>
        </div>
      )}

      <div className="mt-10 flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
        <Button
          variant="primary"
          onClick={onNext}
          disabled={!selected}
          icon={<ArrowRight size={16} />}
          iconPosition="right"
        >
          {t('common.continue', { defaultValue: 'Continue' })}
        </Button>
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
          message: result.latency_ms
            ? `${result.latency_ms}ms response time`
            : undefined,
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
          defaultValue: 'Connect AI for instant estimates',
        })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary">
        {t('onboarding.ai_subtitle', { defaultValue: 'Optional — you can set this up later in Settings.' })}
      </p>

      {/* Provider selection */}
      <div className="mt-8 w-full max-w-md space-y-2">
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
        <Button
          variant="secondary"
          onClick={onNext}
        >
          {t('onboarding.skip', { defaultValue: 'Skip for now' })}
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

function StepCreateProject({
  region,
  onBack,
}: {
  region: RegionPreset | null;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [name, setName] = useState(
    t('onboarding.default_project_name', { defaultValue: 'My First Project' }),
  );
  const [template, setTemplate] = useState('residential');
  const [area, setArea] = useState('1000');

  const createMutation = useMutation({
    mutationFn: async () => {
      // Create the project
      const projectData: CreateProjectData = {
        name: name.trim() || 'My First Project',
        description: `Created during onboarding. Template: ${template}, Area: ${area} m\u00B2`,
        region: region?.id || 'INTL',
        classification_standard: region?.standard || 'masterformat',
        currency: region?.currency || 'USD',
        locale: region?.locale || 'en',
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
          defaultValue: 'Your workspace is ready. Let\'s start estimating.',
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
        {t('onboarding.project_title', { defaultValue: 'Create your first project' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary">
        {t('onboarding.project_subtitle', {
          defaultValue: 'Choose a template to get started quickly.',
        })}
      </p>

      <form onSubmit={handleSubmit} className="mt-8 w-full max-w-md space-y-6">
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

        {/* Template */}
        <div>
          <label className="text-sm font-medium text-content-primary block mb-3">
            {t('onboarding.project_type', { defaultValue: 'Building Type' })}
          </label>
          <div className="grid grid-cols-4 gap-2">
            {PROJECT_TEMPLATES.map((tmpl) => {
              const isSelected = template === tmpl.id;
              return (
                <button
                  key={tmpl.id}
                  type="button"
                  onClick={() => setTemplate(tmpl.id)}
                  className={`flex flex-col items-center gap-1.5 rounded-xl px-2 py-3 transition-all duration-normal ease-oe ${
                    isSelected
                      ? 'bg-oe-blue-subtle border-2 border-oe-blue text-oe-blue scale-[1.02]'
                      : 'border-2 border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                  }`}
                >
                  <span className="text-xl">{tmpl.icon}</span>
                  <span className="text-2xs font-medium truncate w-full text-center">
                    {tmpl.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Area */}
        <Input
          label={t('onboarding.project_area', { defaultValue: 'Gross Floor Area (m\u00B2)' })}
          value={area}
          onChange={(e) => setArea(e.target.value)}
          type="number"
          min="1"
          placeholder="1000"
        />

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
            icon={<Check size={16} />}
            iconPosition="right"
            className="flex-1"
          >
            {t('onboarding.create_project', {
              defaultValue: 'Create Project & Start Estimating',
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
  const [selectedRegion, setSelectedRegion] = useState<RegionPreset | null>(null);
  const { i18n } = useTranslation();

  // Update i18n language when region changes
  useEffect(() => {
    if (selectedRegion) {
      i18n.changeLanguage(selectedRegion.locale);
    }
  }, [selectedRegion, i18n]);

  const goNext = useCallback(() => {
    setStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  }, []);

  const goBack = useCallback(() => {
    setStep((s) => Math.max(s - 1, 0));
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-surface-secondary">
      {/* Top bar with progress */}
      <div className="flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          <Logo size="sm" />
          <span className="text-sm font-semibold text-content-primary tracking-tight">
            Open<span className="text-oe-blue">Estimator</span>
            <span className="text-2xs text-content-tertiary ml-1">.io</span>
          </span>
        </div>
        <ProgressDots current={step} total={TOTAL_STEPS} />
        <div className="text-xs text-content-tertiary tabular-nums">
          {step + 1} / {TOTAL_STEPS}
        </div>
      </div>

      {/* Main content area */}
      <div className="flex flex-1 items-center justify-center px-6 pb-12">
        <div className="w-full max-w-2xl">
          {step === 0 && <StepWelcome onNext={goNext} />}
          {step === 1 && (
            <StepRegion
              selected={selectedRegion}
              onSelect={setSelectedRegion}
              onNext={goNext}
              onBack={goBack}
            />
          )}
          {step === 2 && <StepAI onNext={goNext} onBack={goBack} />}
          {step === 3 && <StepCreateProject region={selectedRegion} onBack={goBack} />}
        </div>
      </div>
    </div>
  );
}
