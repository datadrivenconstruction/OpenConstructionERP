import { useState, useCallback, useEffect, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { getIntlLocale } from '@/shared/lib/formatters';
import { TranslationManager } from './TranslationManager';
import { BackupRestore } from './BackupRestore';
import { RegionalSettings } from './RegionalSettings';
import { WebhookLeads } from './WebhookLeads';
import VectorStatusCard from './VectorStatusCard';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Eye,
  EyeOff,
  CheckCircle2,
  XCircle,
  Package,
  AlertCircle,
  ExternalLink,
  Loader2,
  Sun,
  Moon,
  Monitor,
  Pencil,
  Save,
  Lock,
  User,
  Globe,
  Sparkles,
  Plug,
  ShieldAlert,
  SlidersHorizontal,
  Layers,
  LogOut,
  ChevronRight,
  Wrench,
  LayoutGrid,
} from 'lucide-react';
import { Card, CardHeader, CardContent, CardFooter, Button, Badge, InfoHint, Skeleton, Breadcrumb } from '@/shared/ui';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { DashboardLayoutManager } from '@/features/dashboard/DashboardLayoutManager';
import { UpdateNotification } from '@/shared/ui/UpdateChecker';
import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useAuthStore } from '@/stores/useAuthStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { useToastStore } from '@/stores/useToastStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { aiApi, type AIProvider, type AIConnectionStatus, type AISettings } from '@/features/ai/api';
import { BIMConverterStatusBanner } from '@/features/bim/BIMConverterStatusBanner';

// ── Types ────────────────────────────────────────────────────────────────────

interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: string;
  locale: string;
  is_active: boolean;
  created_at: string;
}

// ── AI Provider definitions ──────────────────────────────────────────────────

interface ProviderInfo {
  id: AIProvider;
  name: string;
  description: string;
  descriptionDefault: string;
  keyPrefix: string;
  docsUrl: string;
  recommended?: boolean;
  region: 'global' | 'china' | 'russia';
}

const AI_PROVIDERS: ProviderInfo[] = [
  // ── Global ──────────────────────────────────────────────────────────
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    description: 'settings.ai_desc_anthropic',
    descriptionDefault: 'Claude Sonnet / Opus — best for construction estimation and analysis',
    keyPrefix: 'sk-ant-',
    docsUrl: 'https://console.anthropic.com/settings/keys',
    recommended: true,
    region: 'global',
  },
  {
    id: 'openai',
    name: 'OpenAI GPT-4',
    description: 'settings.ai_desc_openai',
    descriptionDefault: 'GPT-4o / o1 — strong general-purpose AI with broad knowledge',
    keyPrefix: 'sk-',
    docsUrl: 'https://platform.openai.com/api-keys',
    region: 'global',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    description: 'settings.ai_desc_gemini',
    descriptionDefault: 'Gemini Pro — multimodal AI with Google ecosystem integration',
    keyPrefix: 'AI',
    docsUrl: 'https://aistudio.google.com/app/apikey',
    region: 'global',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    description: 'settings.ai_desc_openrouter',
    descriptionDefault: 'Aggregator — access many AI models through a single API key',
    keyPrefix: 'sk-or-',
    docsUrl: 'https://openrouter.ai/keys',
    region: 'global',
  },
  {
    id: 'mistral',
    name: 'Mistral AI',
    description: 'settings.ai_desc_mistral',
    descriptionDefault: 'Mistral Large — European AI with strong multilingual support',
    keyPrefix: '',
    docsUrl: 'https://console.mistral.ai/api-keys',
    region: 'global',
  },
  {
    id: 'groq',
    name: 'Groq',
    description: 'settings.ai_desc_groq',
    descriptionDefault: 'Ultra-fast inference for Llama and Mixtral models',
    keyPrefix: 'gsk_',
    docsUrl: 'https://console.groq.com/keys',
    region: 'global',
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    description: 'settings.ai_desc_deepseek',
    descriptionDefault: 'DeepSeek V3 — cost-effective AI with strong reasoning',
    keyPrefix: 'sk-',
    docsUrl: 'https://platform.deepseek.com/api_keys',
    region: 'global',
  },
  {
    id: 'together',
    name: 'Together AI',
    description: 'settings.ai_desc_together',
    descriptionDefault: 'Open-source model hosting — Llama, Qwen, and more',
    keyPrefix: '',
    docsUrl: 'https://api.together.ai/settings/api-keys',
    region: 'global',
  },
  {
    id: 'fireworks',
    name: 'Fireworks AI',
    description: 'settings.ai_desc_fireworks',
    descriptionDefault: 'Fast inference platform for open-source and fine-tuned models',
    keyPrefix: '',
    docsUrl: 'https://fireworks.ai/account/api-keys',
    region: 'global',
  },
  {
    id: 'perplexity',
    name: 'Perplexity',
    description: 'settings.ai_desc_perplexity',
    descriptionDefault: 'AI with real-time internet search and citation support',
    keyPrefix: 'pplx-',
    docsUrl: 'https://www.perplexity.ai/settings/api',
    region: 'global',
  },
  {
    id: 'cohere',
    name: 'Cohere',
    description: 'settings.ai_desc_cohere',
    descriptionDefault: 'Enterprise AI for RAG, search, and text generation',
    keyPrefix: '',
    docsUrl: 'https://dashboard.cohere.com/api-keys',
    region: 'global',
  },
  {
    id: 'ai21',
    name: 'AI21 Labs (Jamba)',
    description: 'settings.ai_desc_ai21',
    descriptionDefault: 'Jamba — efficient large language model for enterprise use',
    keyPrefix: '',
    docsUrl: 'https://studio.ai21.com/account/api-key',
    region: 'global',
  },
  {
    id: 'xai',
    name: 'xAI (Grok)',
    description: 'settings.ai_desc_xai',
    descriptionDefault: 'Grok — AI model with real-time knowledge',
    keyPrefix: 'xai-',
    docsUrl: 'https://console.x.ai/',
    region: 'global',
  },
  {
    id: 'zhipu',
    name: 'Zhipu AI (GLM)',
    description: 'settings.ai_desc_zhipu',
    descriptionDefault: 'GLM-4 — leading Chinese AI model for enterprise applications',
    keyPrefix: '',
    docsUrl: 'https://open.bigmodel.cn/usercenter/apikeys',
    region: 'global',
  },
  {
    id: 'yandex',
    name: 'Yandex GPT',
    description: 'settings.ai_desc_yandex',
    descriptionDefault: 'YandexGPT — multilingual AI model with strong language understanding',
    keyPrefix: '',
    docsUrl: 'https://console.yandex.cloud/folders',
    region: 'global',
  },
  {
    id: 'baidu',
    name: 'Baidu (ERNIE Bot)',
    description: 'settings.ai_desc_baidu',
    descriptionDefault: 'ERNIE Bot — Baidu AI for Chinese language and enterprise tasks',
    keyPrefix: '',
    docsUrl: 'https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application',
    region: 'global',
  },
  {
    id: 'ollama',
    name: 'Ollama (Local)',
    description: 'settings.ai_desc_ollama',
    descriptionDefault: 'Ollama — run local LLMs via OpenAI-compatible API. No API key required.',
    keyPrefix: '',
    docsUrl: 'https://ollama.ai/',
    region: 'global',
  },
  {
    id: 'kimi',
    name: 'Kimi (Moonshot AI)',
    description: 'settings.ai_desc_kimi',
    descriptionDefault: 'Kimi 2.6 — Moonshot AI with strong reasoning and long context for construction documents.',
    keyPrefix: 'sk-',
    docsUrl: 'https://platform.moonshot.cn/console/api-keys',
    region: 'global',
  },
  {
    id: 'vllm',
    name: 'vLLM (Local)',
    description: 'settings.ai_desc_vllm',
    descriptionDefault: 'vLLM — high-throughput local LLM inference server with OpenAI-compatible API. No API key required by default.',
    keyPrefix: '',
    docsUrl: 'https://docs.vllm.ai/',
    region: 'global',
  },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

function maskApiKey(key: string | null | undefined): string {
  if (!key) return '';
  if (key.length <= 8) return '•'.repeat(key.length);
  return key.slice(0, 8) + '•'.repeat(Math.min(key.length - 8, 24));
}

function isKeySetForProvider(settings: AISettings | undefined, provider: AIProvider): boolean {
  if (!settings) return false;
  const key = `${provider}_api_key_set` as keyof AISettings;
  return !!settings[key];
}

function StatusIndicator({ status, lastTested }: { status: AIConnectionStatus; lastTested: string | null }) {
  const { t } = useTranslation();
  const formatTimeAgo = useFormatTimeAgo();

  switch (status) {
    case 'connected':
      return (
        <div className="flex items-center gap-2 text-sm">
          <CheckCircle2 size={16} className="text-semantic-success" />
          <span className="text-semantic-success font-medium">
            {t('settings.ai_connected', { defaultValue: 'Connected' })}
          </span>
          {lastTested && (
            <span className="text-content-tertiary text-xs">
              {t('settings.ai_last_tested', {
                defaultValue: '(last tested: {{time}})',
                time: formatTimeAgo(lastTested),
              })}
            </span>
          )}
        </div>
      );
    case 'error':
      return (
        <div className="flex items-center gap-2 text-sm">
          <XCircle size={16} className="text-semantic-error" />
          <span className="text-semantic-error font-medium">
            {t('settings.ai_error', { defaultValue: 'Connection error' })}
          </span>
        </div>
      );
    case 'not_configured':
    default:
      return (
        <div className="flex items-center gap-2 text-sm">
          <AlertCircle size={16} className="text-content-tertiary" />
          <span className="text-content-tertiary">
            {t('settings.ai_not_configured', { defaultValue: 'Not configured' })}
          </span>
        </div>
      );
  }
}

function useFormatTimeAgo() {
  const { t } = useTranslation();
  return (dateStr: string): string => {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return t('settings.time_just_now', { defaultValue: 'just now' });
    if (mins < 60) return t('settings.time_minutes_ago', { defaultValue: '{{count}}m ago', count: mins });
    const hours = Math.floor(mins / 60);
    if (hours < 24) return t('settings.time_hours_ago', { defaultValue: '{{count}}h ago', count: hours });
    const days = Math.floor(hours / 24);
    return t('settings.time_days_ago', { defaultValue: '{{count}}d ago', count: days });
  };
}

// ── AI Configuration Card ────────────────────────────────────────────────────

function AIConfigurationCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // State
  const [selectedProvider, setSelectedProvider] = useState<AIProvider>('anthropic');
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [hasUnsavedKey, setHasUnsavedKey] = useState(false);
  // Per-provider model-id override. Empty string = use the platform default.
  const [modelInput, setModelInput] = useState('');
  const [modelTouched, setModelTouched] = useState(false);
  // Custom base URL for local providers (Ollama, vLLM)
  const [baseUrlInput, setBaseUrlInput] = useState('');
  const [baseUrlTouched, setBaseUrlTouched] = useState(false);

  // Fetch current settings
  const { data: settings } = useQuery({
    queryKey: ['ai-settings'],
    queryFn: aiApi.getSettings,
    retry: false,
  });

  // Sync provider selection from preferred_model when settings are loaded
  useEffect(() => {
    if (settings?.preferred_model) {
      const model = settings.preferred_model;
      const providerMap: Record<string, AIProvider> = {
        anthropic: 'anthropic', claude: 'anthropic',
        openai: 'openai', gpt: 'openai',
        gemini: 'gemini', google: 'gemini',
        openrouter: 'openrouter',
        mistral: 'mistral',
        groq: 'groq',
        deepseek: 'deepseek',
        together: 'together',
        fireworks: 'fireworks',
        perplexity: 'perplexity',
        cohere: 'cohere',
        ai21: 'ai21', jamba: 'ai21',
        xai: 'xai', grok: 'xai',
        zhipu: 'zhipu', glm: 'zhipu',
        baidu: 'baidu', ernie: 'baidu',
        yandex: 'yandex',
        ollama: 'ollama',
        vllm: 'vllm',
        kimi: 'kimi', moonshot: 'kimi',
      };
      const matched = Object.entries(providerMap).find(([key]) => model.includes(key));
      if (matched) setSelectedProvider(matched[1]);
    } else if (settings?.provider) {
      setSelectedProvider(settings.provider);
    }
  }, [settings?.preferred_model, settings?.provider]);

  // Reflect the saved model override for the selected provider. When the
  // user has not overridden it, leave the field blank and show the platform
  // default as the placeholder so it stays current automatically.
  useEffect(() => {
    setModelInput(settings?.model_overrides?.[selectedProvider] ?? '');
    setModelTouched(false);
  }, [selectedProvider, settings?.model_overrides]);

  // Reflect the saved custom base URL for local providers
  useEffect(() => {
    if (selectedProvider === 'ollama') {
      setBaseUrlInput(settings?.ollama_base_url ?? '');
    } else if (selectedProvider === 'vllm') {
      setBaseUrlInput(settings?.vllm_base_url ?? '');
    } else {
      setBaseUrlInput('');
    }
    setBaseUrlTouched(false);
  }, [selectedProvider, settings?.ollama_base_url, settings?.vllm_base_url]);

  const defaultModel = settings?.default_models?.[selectedProvider] ?? '';
  const hasKeySet = isKeySetForProvider(settings, selectedProvider);

  // Test connection mutation — auto-saves unsaved key / model before testing
  // so the test exercises the exact provider + model id the real estimate
  // calls will use (this is what surfaces stale-model failures early).
  const testMutation = useMutation({
    mutationFn: async () => {
      const needsSave =
        (hasUnsavedKey && apiKeyInput.trim()) || modelTouched || baseUrlTouched;
      if (needsSave) {
        const update: Record<string, unknown> = { preferred_model: selectedProvider };
        if (hasUnsavedKey && apiKeyInput.trim()) {
          update[`${selectedProvider}_api_key`] = apiKeyInput.trim();
        }
        if (modelTouched) {
          // Blank string clears the override (server falls back to default).
          update.model_overrides = { [selectedProvider]: modelInput.trim() };
        }
        if (baseUrlTouched) {
          const urlKey = `${selectedProvider}_base_url`;
          update[urlKey] = baseUrlInput.trim() || null;
        }
        await aiApi.updateSettings(update as Parameters<typeof aiApi.updateSettings>[0]);
      }
      return aiApi.testConnection(selectedProvider);
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
      if (hasUnsavedKey) {
        setApiKeyInput('');
        setHasUnsavedKey(false);
        setShowKey(false);
      }
      setModelTouched(false);
      setBaseUrlTouched(false);
      // Same broadcast as the Save handler — the test path can also save.
      try {
        window.dispatchEvent(new CustomEvent('oe:ai-settings-updated'));
      } catch {
        /* non-fatal */
      }
      if (result.success) {
        const parts: string[] = [];
        if (result.model) {
          parts.push(
            t('settings.ai_test_model', {
              defaultValue: 'Model: {{model}}',
              model: result.model,
            }),
          );
        }
        if (result.latency_ms) {
          parts.push(
            t('settings.ai_test_latency', {
              defaultValue: 'Response time: {{ms}}ms',
              ms: result.latency_ms,
            }),
          );
        }
        addToast({
          type: 'success',
          title: t('settings.ai_test_success', { defaultValue: 'Connection successful' }),
          message: parts.length ? parts.join(' · ') : undefined,
        });
      } else {
        addToast({
          type: 'error',
          title: t('settings.ai_test_failed', { defaultValue: 'Connection failed' }),
          // Surface the provider's actual error (e.g. "model not found —
          // change the model name in Settings > AI") so the user can act.
          message: result.message,
        });
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.ai_test_error', { defaultValue: 'Test failed' }),
        message: err.message,
      });
    },
  });

  // Save settings mutation
  const saveMutation = useMutation({
    mutationFn: () => {
      const update: Record<string, unknown> = {
        preferred_model: selectedProvider,
      };
      if (hasUnsavedKey && apiKeyInput.trim()) {
        const keyField = `${selectedProvider}_api_key`;
        update[keyField] = apiKeyInput.trim();
      }
      if (modelTouched) {
        // Blank string clears the override (server uses the default).
        update.model_overrides = { [selectedProvider]: modelInput.trim() };
      }
      if (baseUrlTouched) {
        const urlKey = `${selectedProvider}_base_url`;
        update[urlKey] = baseUrlInput.trim() || null;
      }
      return aiApi.updateSettings(update as Parameters<typeof aiApi.updateSettings>[0]);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
      setApiKeyInput('');
      setHasUnsavedKey(false);
      setShowKey(false);
      setModelTouched(false);
      setBaseUrlTouched(false);
      addToast({
        type: 'success',
        title: t('settings.ai_saved', { defaultValue: 'AI settings saved' }),
      });
      // Let the floating chat (and any other panels probing AI status)
      // refresh themselves immediately instead of waiting for the next
      // re-mount.
      try {
        window.dispatchEvent(new CustomEvent('oe:ai-settings-updated'));
      } catch {
        /* CustomEvent unavailable in IE — non-fatal. */
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('settings.ai_save_error', { defaultValue: 'Failed to save settings' }),
        message: err.message,
      });
    },
  });

  const handleProviderChange = useCallback((provider: AIProvider) => {
    setSelectedProvider(provider);
    setApiKeyInput('');
    setHasUnsavedKey(false);
    setShowKey(false);
    setBaseUrlInput('');
    setBaseUrlTouched(false);
    aiApi.updateSettings({ preferred_model: provider }).then(() => {
      queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
    }).catch(() => { /* ignore — will save on next explicit Save */ });
  }, [queryClient]);

  const handleKeyChange = useCallback((value: string) => {
    setApiKeyInput(value);
    setHasUnsavedKey(true);
  }, []);

  const displayValue = hasUnsavedKey
    ? showKey
      ? apiKeyInput
      : apiKeyInput
        ? maskApiKey(apiKeyInput)
        : ''
    : hasKeySet
      ? 'sk-••••••••••••••••'
      : '';

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title={t('settings.ai_title', { defaultValue: 'AI Configuration' })}
        subtitle={t('settings.ai_subtitle', {
          defaultValue: 'Choose your AI provider for estimation and analysis',
        })}
      />
      <CardContent>
        <div className="space-y-6">
          {/* Provider selection */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1">
              {t('settings.ai_provider', { defaultValue: 'AI Provider' })}
            </label>
            <p className="text-xs text-content-tertiary mb-3">
              {t('settings.ai_provider_help', { defaultValue: 'Pick the LLM provider whose API key you have. Recommended: Anthropic Claude.' })}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {AI_PROVIDERS.map((provider) => {
                const isSelected = selectedProvider === provider.id;
                const hasKey = isKeySetForProvider(settings, provider.id);

                return (
                  <button
                    key={provider.id}
                    type="button"
                    onClick={() => handleProviderChange(provider.id)}
                    aria-pressed={isSelected}
                    aria-label={`${provider.name}${isSelected ? ` (${t('settings.ai_selected', { defaultValue: 'selected' })})` : ''}`}
                    className={`relative flex flex-col items-start gap-1 rounded-xl px-4 py-3 text-left transition-all duration-normal ease-oe ${
                      isSelected
                        ? 'bg-oe-blue-subtle border-2 border-oe-blue ring-2 ring-oe-blue/10'
                        : 'border-2 border-border-light hover:bg-surface-secondary hover:border-border'
                    }`}
                  >
                    {provider.recommended && (
                      <Badge variant="blue" size="sm" className="absolute -top-2.5 right-2 z-10">
                        {t('settings.ai_recommended', { defaultValue: 'Recommended' })}
                      </Badge>
                    )}
                    <div className="flex items-center gap-2">
                      <div
                        className={`h-3.5 w-3.5 rounded-full border-2 transition-colors duration-fast ${
                          isSelected ? 'border-oe-blue bg-oe-blue' : 'border-content-tertiary bg-transparent'
                        }`}
                      >
                        {isSelected && (
                          <div className="flex h-full w-full items-center justify-center">
                            <div className="h-1.5 w-1.5 rounded-full bg-white" />
                          </div>
                        )}
                      </div>
                      <span
                        className={`text-sm font-semibold ${
                          isSelected ? 'text-oe-blue' : 'text-content-primary'
                        }`}
                      >
                        {provider.name}
                      </span>
                    </div>
                    <p className="text-xs text-content-secondary pl-5.5 leading-relaxed">
                      {t(provider.description, { defaultValue: provider.descriptionDefault })}
                    </p>
                    {hasKey && (
                      <Badge variant="success" size="sm" className="mt-1 ml-5.5">
                        {t('settings.ai_key_set', { defaultValue: 'Key configured' })}
                      </Badge>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* API Key input */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="ai-api-key" className="text-sm font-medium text-content-primary">
                {t('settings.ai_api_key', { defaultValue: 'API Key' })}
              </label>
              <a
                href={AI_PROVIDERS.find((p) => p.id === selectedProvider)?.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-oe-blue hover:underline"
              >
                {t('settings.ai_get_key', { defaultValue: 'Get an API key' })}
                <ExternalLink size={11} />
              </a>
            </div>
            <div className="relative group">
              <input
                id="ai-api-key"
                type={showKey && hasUnsavedKey ? 'text' : 'password'}
                value={hasUnsavedKey ? apiKeyInput : displayValue}
                onChange={(e) => handleKeyChange(e.target.value)}
                placeholder={
                  hasKeySet
                    ? t('settings.ai_key_placeholder_existing', {
                        defaultValue: 'Enter new key to replace existing...',
                      })
                    : t('settings.ai_key_placeholder', {
                        defaultValue: `Paste your ${AI_PROVIDERS.find((p) => p.id === selectedProvider)?.keyPrefix || ''}... key here`,
                      })
                }
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 pr-20 font-mono text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue focus:shadow-[0_0_0_4px_rgba(0,113,227,0.08)] transition-all duration-normal ease-oe hover:border-content-tertiary"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                aria-label={showKey ? t('settings.hide_key', { defaultValue: 'Hide' }) : t('settings.show_key', { defaultValue: 'Show' })}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-content-tertiary hover:text-content-primary transition-colors duration-fast"
                tabIndex={-1}
              >
                {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                <span className="ml-1 text-xs">{showKey ? t('settings.hide_key', { defaultValue: 'Hide' }) : t('settings.show_key', { defaultValue: 'Show' })}</span>
              </button>
            </div>
            <p className="mt-1.5 text-xs text-content-tertiary">
              {t('settings.ai_key_hint', {
                defaultValue: 'Your API key is encrypted and stored securely. It is never shared.',
              })}
            </p>
          </div>

          {/* Custom base URL for local providers (Ollama, vLLM) */}
          {(selectedProvider === 'ollama' || selectedProvider === 'vllm') && (
            <div>
              <label
                htmlFor="ai-base-url"
                className="text-sm font-medium text-content-primary block mb-1.5"
              >
                {t('settings.ai_base_url', { defaultValue: 'Server URL' })}
              </label>
              <input
                id="ai-base-url"
                type="text"
                value={baseUrlInput}
                onChange={(e) => {
                  setBaseUrlInput(e.target.value);
                  setBaseUrlTouched(true);
                }}
                placeholder={
                  selectedProvider === 'ollama'
                    ? 'http://localhost:11434'
                    : 'http://localhost:8000'
                }
                spellCheck={false}
                autoComplete="off"
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 font-mono text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-normal ease-oe hover:border-content-tertiary"
              />
              <p className="mt-1.5 text-xs text-content-tertiary">
                {t('settings.ai_base_url_hint', {
                  defaultValue:
                    'Enter the server address including port. The /v1/chat/completions path is appended automatically.',
                })}
              </p>
            </div>
          )}

          {/* Model name override — lets users track provider model
              renames/retirements without waiting for an app update. */}
          <div>
            <label
              htmlFor="ai-model-name"
              className="text-sm font-medium text-content-primary block mb-1.5"
            >
              {t('settings.ai_model_name', { defaultValue: 'Model name' })}
            </label>
            <input
              id="ai-model-name"
              type="text"
              value={modelInput}
              onChange={(e) => {
                setModelInput(e.target.value);
                setModelTouched(true);
              }}
              placeholder={
                defaultModel
                  ? t('settings.ai_model_placeholder', {
                      defaultValue: 'Default: {{model}}',
                      model: defaultModel,
                    })
                  : t('settings.ai_model_placeholder_generic', {
                      defaultValue: 'Leave blank to use the provider default',
                    })
              }
              spellCheck={false}
              autoComplete="off"
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 font-mono text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-all duration-normal ease-oe hover:border-content-tertiary"
            />
            <p className="mt-1.5 text-xs text-content-tertiary">
              {t('settings.ai_model_hint', {
                defaultValue:
                  'AI providers rename and retire models over time. If a connection fails with a "model not found" error, set the exact current model id here (e.g. gemini-2.5-flash, anthropic/claude-sonnet-4). Leave blank to use the recommended default.',
              })}
            </p>
          </div>

          {/* Status */}
          <div className="rounded-lg bg-surface-secondary/50 px-4 py-3">
            <StatusIndicator
              status={settings?.status || 'not_configured'}
              lastTested={settings?.last_tested_at || null}
            />
          </div>
        </div>
      </CardContent>

      <CardFooter>
        <Button
          variant="secondary"
          onClick={() => testMutation.mutate()}
          disabled={testMutation.isPending || (!hasKeySet && !hasUnsavedKey)}
          title={hasUnsavedKey || modelTouched || baseUrlTouched ? t('settings.ai_test_save_hint', { defaultValue: 'Save changes and test connection' }) : t('settings.ai_test', { defaultValue: 'Test Connection' })}
          icon={
            testMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : undefined
          }
        >
          {testMutation.isPending
            ? t('settings.ai_testing', { defaultValue: 'Testing...' })
            : t('settings.ai_test', { defaultValue: 'Test Connection' })}
        </Button>
        <Button
          variant="primary"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || (!hasUnsavedKey && !modelTouched && !baseUrlTouched && selectedProvider === settings?.provider)}
          loading={saveMutation.isPending}
        >
          {t('settings.ai_save_btn', { defaultValue: 'Save Settings' })}
        </Button>
      </CardFooter>
    </Card>
  );
}

// ── Appearance Card ─────────────────────────────────────────────────────────

const THEME_OPTIONS = [
  { value: 'light' as const, icon: Sun, labelKey: 'settings.theme_light', defaultLabel: 'Light' },
  { value: 'dark' as const, icon: Moon, labelKey: 'settings.theme_dark', defaultLabel: 'Dark' },
  { value: 'system' as const, icon: Monitor, labelKey: 'settings.theme_system', defaultLabel: 'System' },
];

function InterfaceModeCard() {
  const { t } = useTranslation();
  const mode = useViewModeStore((s) => s.mode);
  const setMode = useViewModeStore((s) => s.setMode);
  const isAdvanced = mode === 'advanced';

  return (
    <Card>
      <CardHeader
        title={t('settings.interface_mode_title', { defaultValue: 'Interface Mode' })}
        subtitle={t('settings.interface_mode_subtitle', { defaultValue: 'Control which features are visible in the navigation' })}
      />
      <CardContent>
        <div className="flex gap-3">
          <button
            onClick={() => setMode('simple')}
            aria-pressed={!isAdvanced}
            aria-label={t('nav.mode_simple', { defaultValue: 'Simple' })}
            className={`flex-1 flex flex-col items-center gap-2 rounded-xl px-4 py-4 border-2 transition-all ${
              !isAdvanced
                ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
            }`}
          >
            <span className="text-sm font-semibold">{t('nav.mode_simple', { defaultValue: 'Simple' })}</span>
            <span className="text-xs text-center leading-snug">{t('settings.mode_simple_detail', { defaultValue: 'Essential estimation tools. Clean interface for focused work.' })}</span>
            <span className={`mt-1 inline-flex h-5 items-center rounded-full px-2 text-2xs font-bold tracking-wide ${
              !isAdvanced ? 'bg-oe-blue/15 text-oe-blue' : 'bg-surface-tertiary text-content-tertiary'
            }`}>STD</span>
          </button>
          <button
            onClick={() => setMode('advanced')}
            aria-pressed={isAdvanced}
            aria-label={t('nav.mode_advanced', { defaultValue: 'Advanced' })}
            className={`flex-1 flex flex-col items-center gap-2 rounded-xl px-4 py-4 border-2 transition-all ${
              isAdvanced
                ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
            }`}
          >
            <span className="text-sm font-semibold">{t('nav.mode_advanced', { defaultValue: 'Advanced' })}</span>
            <span className="text-xs text-center leading-snug">{t('settings.mode_advanced_detail', { defaultValue: 'Full professional toolset with all modules and features visible.' })}</span>
            <span className={`mt-1 inline-flex h-5 items-center rounded-full px-2 text-2xs font-bold tracking-wide ${
              isAdvanced ? 'bg-oe-blue/15 text-oe-blue' : 'bg-surface-tertiary text-content-tertiary'
            }`}>PRO</span>
          </button>
        </div>
        <Link
          to="/modules"
          className="mt-4 flex items-center gap-2.5 rounded-lg border border-border-light bg-surface-secondary/40 px-4 py-3 text-left transition-all hover:bg-surface-secondary hover:border-border"
        >
          <Package size={16} className="shrink-0 text-oe-blue" />
          <div className="min-w-0">
            <span className="text-sm font-medium text-content-primary">
              {t('settings.modules_link_title', { defaultValue: 'Modules' })}
            </span>
            <p className="text-xs text-content-tertiary mt-0.5">
              {t('settings.modules_link_desc', { defaultValue: 'Enable, disable, and configure individual modules in the Modules section.' })}
            </p>
          </div>
          <ChevronRight size={16} className="ml-auto shrink-0 text-content-quaternary" />
        </Link>
      </CardContent>
    </Card>
  );
}

function AppearanceCard() {
  const { t } = useTranslation();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);

  return (
    <Card>
      <CardHeader
        title={t('settings.appearance_title', { defaultValue: 'Appearance' })}
        subtitle={t('settings.appearance_subtitle', {
          defaultValue: 'Choose your preferred color scheme',
        })}
      />
      <CardContent>
        <div className="grid grid-cols-3 gap-3">
          {THEME_OPTIONS.map((option) => {
            const isActive = theme === option.value;
            const Icon = option.icon;
            return (
              <button
                key={option.value}
                onClick={() => setTheme(option.value)}
                aria-pressed={isActive}
                aria-label={t(option.labelKey, { defaultValue: option.defaultLabel })}
                className={`flex flex-col items-center gap-2.5 rounded-xl px-4 py-4 text-center transition-all duration-normal ease-oe ${
                  isActive
                    ? 'bg-oe-blue-subtle border-2 border-oe-blue text-oe-blue'
                    : 'border-2 border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                }`}
              >
                <Icon size={22} strokeWidth={1.75} />
                <span className="text-sm font-medium">
                  {t(option.labelKey, { defaultValue: option.defaultLabel })}
                </span>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Profile Card ─────────────────────────────────────────────────────────────

interface ProfileCardProps {
  profile: UserProfile | undefined;
  loading: boolean;
  editing: boolean;
  setEditing: (v: boolean) => void;
  formName: string;
  setFormName: (v: string) => void;
  onSave: () => void;
  saving: boolean;
}

function ProfileCard({ profile, loading, editing, setEditing, formName, setFormName, onSave, saving }: ProfileCardProps) {
  const { t } = useTranslation();

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title={t('settings.profile_title', { defaultValue: 'Profile' })}
        subtitle={t('settings.profile_subtitle', { defaultValue: 'Your personal information and account status' })}
      />
      <CardContent>
        {profile ? (
          <div className="flex flex-col sm:flex-row sm:items-center gap-5">
            {/* Avatar */}
            <div
              className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-oe-blue to-oe-blue-hover text-3xl font-bold text-white shadow-sm"
              aria-hidden="true"
            >
              {profile.full_name?.charAt(0)?.toUpperCase() || 'U'}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0 space-y-3">
              {/* Name + edit */}
              <div>
                <label className="text-2xs uppercase tracking-wider text-content-tertiary font-semibold">
                  {t('settings.full_name', { defaultValue: 'Full name' })}
                </label>
                {editing ? (
                  <div className="mt-1 flex items-center gap-2">
                    <input
                      value={formName}
                      onChange={(e) => setFormName(e.target.value)}
                      className="text-base font-semibold text-content-primary bg-surface-secondary rounded-lg px-3 py-1.5 border border-border-light focus:outline-none focus:ring-2 focus:ring-oe-blue/30 max-w-xs"
                      placeholder={t('settings.full_name', { defaultValue: 'Full name' })}
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') onSave();
                        if (e.key === 'Escape') setEditing(false);
                      }}
                    />
                    <Button
                      onClick={onSave}
                      disabled={!formName.trim() || saving}
                      loading={saving}
                      size="sm"
                      icon={!saving ? <Save size={14} /> : undefined}
                    >
                      {t('common.save', { defaultValue: 'Save' })}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setEditing(false)}
                    >
                      {t('common.cancel', { defaultValue: 'Cancel' })}
                    </Button>
                  </div>
                ) : (
                  <div className="mt-0.5 flex items-center gap-2">
                    <div className="text-lg font-semibold text-content-primary truncate">{profile.full_name}</div>
                    <button
                      onClick={() => {
                        setFormName(profile.full_name || '');
                        setEditing(true);
                      }}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
                      aria-label={t('settings.edit_profile', { defaultValue: 'Edit profile name' })}
                      title={t('common.edit', { defaultValue: 'Edit' })}
                    >
                      <Pencil size={14} />
                    </button>
                  </div>
                )}
              </div>

              {/* Meta grid */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3 border-t border-border-light">
                <div>
                  <span className="text-2xs uppercase tracking-wider text-content-tertiary font-semibold block">
                    {t('settings.email_label', { defaultValue: 'Email' })}
                  </span>
                  <div className="mt-0.5 text-sm text-content-primary truncate">{profile.email}</div>
                </div>
                <div>
                  <span className="text-2xs uppercase tracking-wider text-content-tertiary font-semibold block">
                    {t('settings.role_label', { defaultValue: 'Role' })}
                  </span>
                  <div className="mt-0.5">
                    <Badge variant="blue" size="sm">{profile.role}</Badge>
                  </div>
                </div>
                <div>
                  <span className="text-2xs uppercase tracking-wider text-content-tertiary font-semibold block">
                    {t('settings.status', { defaultValue: 'Status' })}
                  </span>
                  <div className="mt-0.5">
                    <Badge variant={profile.is_active ? 'success' : 'error'} size="sm" dot>
                      {profile.is_active
                        ? t('settings.active', { defaultValue: 'Active' })
                        : t('settings.inactive', { defaultValue: 'Inactive' })}
                    </Badge>
                  </div>
                </div>
              </div>

              {/* Member since */}
              <div className="text-xs text-content-tertiary">
                {t('settings.member_since', { defaultValue: 'Member since' })}{' '}
                <span className="text-content-secondary font-medium">
                  {new Date(profile.created_at).toLocaleDateString(getIntlLocale())}
                </span>
              </div>
            </div>
          </div>
        ) : loading ? (
          <div className="flex items-center gap-5">
            <Skeleton className="h-20 w-20 rounded-2xl" />
            <div className="space-y-2 flex-1">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-48" />
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
          </div>
        ) : (
          <p className="text-sm text-content-secondary">
            {t('settings.profile_error', { defaultValue: 'Could not load profile' })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Tab definitions ──────────────────────────────────────────────────────────

type SettingsTab = 'general' | 'dashboard' | 'account' | 'regional' | 'converters' | 'ai' | 'integrations' | 'advanced';

interface TabDef {
  id: SettingsTab;
  labelKey: string;
  defaultLabel: string;
  icon: typeof User;
  descKey: string;
  descDefault: string;
}

const DEFAULT_TAB: TabDef = {
  id: 'general',
  labelKey: 'settings.tab_general',
  defaultLabel: 'General',
  icon: SlidersHorizontal,
  descKey: 'settings.tab_general_desc',
  descDefault: 'Profile, theme, and interface mode',
};

const TABS: readonly TabDef[] = [
  DEFAULT_TAB,
  { id: 'dashboard',    labelKey: 'settings.tab_dashboard',    defaultLabel: 'Dashboard',    icon: LayoutGrid, descKey: 'settings.tab_dashboard_desc',  descDefault: 'Reorder, show or hide dashboard sections' },
  { id: 'account',      labelKey: 'settings.tab_account',      defaultLabel: 'Account',      icon: User,     descKey: 'settings.tab_account_desc',      descDefault: 'Password and sign out' },
  { id: 'regional',     labelKey: 'settings.tab_regional',     defaultLabel: 'Regional',     icon: Globe,    descKey: 'settings.tab_regional_desc',     descDefault: 'Language, timezone, and formats' },
  { id: 'converters',   labelKey: 'settings.tab_converters',   defaultLabel: 'Converters',  icon: Layers,   descKey: 'settings.tab_converters_desc',   descDefault: 'DDC converters — installed versions and GitHub sources' },
  { id: 'ai',           labelKey: 'settings.tab_ai',           defaultLabel: 'AI',           icon: Sparkles, descKey: 'settings.tab_ai_desc',           descDefault: 'AI provider and semantic search' },
  { id: 'integrations', labelKey: 'settings.tab_integrations', defaultLabel: 'Integrations', icon: Plug,     descKey: 'settings.tab_integrations_desc', descDefault: 'Slack, Teams, Telegram, webhooks' },
  { id: 'advanced',     labelKey: 'settings.tab_advanced',     defaultLabel: 'Advanced',     icon: Wrench,   descKey: 'settings.tab_advanced_desc',     descDefault: 'Backup, databases, setup wizard' },
];

// ── Main Settings Page ───────────────────────────────────────────────────────

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const logout = useAuthStore((s) => s.logout);
  const setTokens = useAuthStore((s) => s.setTokens);
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [editingProfile, setEditingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState({ full_name: '' });

  const { data: profile, isPending: profileLoading } = useQuery({
    queryKey: ['me'],
    queryFn: () => apiGet<UserProfile>('/v1/users/me/'),
    retry: false,
  });

  const profileMutation = useMutation({
    mutationFn: (data: { full_name: string }) =>
      apiPatch<UserProfile>('/v1/users/me/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me'] });
      setEditingProfile(false);
      addToast({ type: 'success', title: t('toasts.profile_updated', { defaultValue: 'Profile updated' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  // ── Change password ──────────────────────────────────────────────────
  const [pwForm, setPwForm] = useState({ current: '', new_: '', confirm: '' });
  const [showPwFields, setShowPwFields] = useState(false);

  const pwMutation = useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiPost<{ access_token: string; refresh_token: string }>('/v1/users/me/change-password/', body),
    onSuccess: (data) => {
      const remember = localStorage.getItem('oe_remember') === '1';
      const email = useAuthStore.getState().userEmail ?? undefined;
      setTokens(data.access_token, data.refresh_token, remember, email);
      setPwForm({ current: '', new_: '', confirm: '' });
      setShowPwFields(false);
      addToast({ type: 'success', title: t('settings.password_changed', { defaultValue: 'Password changed successfully' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  const pwValid = pwForm.current.length >= 8 && pwForm.new_.length >= 8 && pwForm.new_ === pwForm.confirm;

  // ── Tab state with URL sync ──────────────────────────────────────────
  const [searchParams, setSearchParams] = useSearchParams();
  // Resolve legacy/renamed tab ids so old bookmarks keep working.
  // ``?tab=bimcad`` was the pre-v4.6 id for the CAD/BIM panel which was
  // renamed to ``converters`` in #76 — landing on the stale URL used to
  // silently fall back to General, making it look like the redesign had
  // been reverted.
  const TAB_ALIASES: Record<string, SettingsTab> = {
    bimcad: 'converters',
    'bim-cad': 'converters',
    'bim_cad': 'converters',
    cad: 'converters',
  };
  const rawTab = searchParams.get('tab') ?? '';
  const initialTab = (TAB_ALIASES[rawTab] ?? (rawTab as SettingsTab)) || 'general';
  const validTabIds = useMemo(() => TABS.map((t) => t.id), []);
  const [activeTab, setActiveTab] = useState<SettingsTab>(
    validTabIds.includes(initialTab) ? initialTab : 'general',
  );

  const handleTabChange = useCallback((id: SettingsTab) => {
    setActiveTab(id);
    const params = new URLSearchParams(searchParams);
    params.set('tab', id);
    setSearchParams(params, { replace: true });
    // Scroll panel back to top so new tab content starts at the visual anchor
    if (typeof window !== 'undefined') {
      const panel = document.getElementById('settings-content');
      if (panel) panel.scrollTo?.({ top: 0, behavior: 'smooth' });
    }
  }, [searchParams, setSearchParams]);

  // Arrow-key keyboard nav for the settings tab strip. Mobile is a
  // horizontal scroll, desktop is a vertical sidebar — accept both
  // orientations so the same handler serves both. (WCAG 2.1.1)
  const onTabKeyDown = useTabKeyboardNav<SettingsTab>({
    ids: validTabIds,
    activeId: activeTab,
    onChange: handleTabChange,
    orientation: 'both',
  });

  const activeTabDef: TabDef = TABS.find((tab) => tab.id === activeTab) ?? DEFAULT_TAB;
  const ActiveIcon = activeTabDef.icon;

  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          { label: t('nav.settings', 'Settings') },
        ]}
        className="mb-4"
      />

      {/* Update notification — surfaced in Settings so users see new
          versions even if they dismissed the sidebar widget for the session. */}
      <div className="-mx-4 sm:-mx-7 mb-6">
        <UpdateNotification forceShow hideDismiss />
      </div>

      {/* Page header */}
      <div className="mb-6 animate-card-in">
        <h1 className="text-2xl font-bold text-content-primary">{t('nav.settings', 'Settings')}</h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('settings.subtitle', { defaultValue: 'Manage your account and preferences' })}
        </p>
      </div>

      {/* ── Two-column layout: sidebar nav + content ──────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)] gap-6 lg:gap-8">
        {/* Sticky sidebar (desktop) / horizontal pills (mobile) */}
        <aside className="lg:sticky lg:top-4 lg:self-start">
          {/* Mobile: horizontal scrollable pills */}
          <div
            role="tablist"
            aria-label={t('nav.settings', 'Settings')}
            aria-orientation="horizontal"
            data-testid="settings-tabs"
            onKeyDown={onTabKeyDown}
            className="lg:hidden -mx-4 px-4 flex gap-2 overflow-x-auto pb-2 scrollbar-thin"
          >
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  role="tab"
                  type="button"
                  aria-selected={isActive}
                  aria-controls="settings-content"
                  id={`settings-tab-${tab.id}`}
                  data-testid={`settings-tab-${tab.id}`}
                  tabIndex={isActive ? 0 : -1}
                  onClick={() => handleTabChange(tab.id)}
                  className={`shrink-0 inline-flex items-center gap-2 px-3.5 py-2 rounded-full text-sm font-medium transition-all ${
                    isActive
                      ? 'bg-oe-blue text-content-inverse shadow-xs'
                      : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
                  }`}
                >
                  <Icon size={14} strokeWidth={2} />
                  {t(tab.labelKey, { defaultValue: tab.defaultLabel })}
                </button>
              );
            })}
          </div>

          {/* Desktop: vertical sidebar nav */}
          <nav
            role="tablist"
            aria-label={t('nav.settings', 'Settings')}
            aria-orientation="vertical"
            onKeyDown={onTabKeyDown}
            className="hidden lg:flex flex-col gap-1 rounded-xl border border-border-light bg-surface-elevated p-2 shadow-xs"
          >
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  role="tab"
                  type="button"
                  aria-selected={isActive}
                  aria-controls="settings-content"
                  id={`settings-tab-${tab.id}-desktop`}
                  data-testid={`settings-tab-${tab.id}-desktop`}
                  tabIndex={isActive ? 0 : -1}
                  onClick={() => handleTabChange(tab.id)}
                  className={`group flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-all duration-fast ${
                    isActive
                      ? 'bg-oe-blue-subtle text-oe-blue'
                      : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary'
                  }`}
                >
                  <Icon size={16} strokeWidth={2} className="shrink-0" />
                  <span className="text-sm font-medium flex-1 truncate">
                    {t(tab.labelKey, { defaultValue: tab.defaultLabel })}
                  </span>
                  {isActive && (
                    <ChevronRight size={14} className="shrink-0 opacity-70" />
                  )}
                </button>
              );
            })}
          </nav>

          {/* About link */}
          <div className="hidden lg:block mt-4 px-3 text-center">
            <Link
              to="/about"
              className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-oe-blue transition-colors"
            >
              {t('settings.about_link', { defaultValue: 'About OpenConstructionERP' })}
              <ChevronRight size={11} />
            </Link>
          </div>
        </aside>

        {/* ── Tab content ──────────────────────────────────────────── */}
        <div
          id="settings-content"
          role="tabpanel"
          aria-labelledby={`settings-tab-${activeTab}-desktop`}
          className="min-w-0"
        >
          {/* Active section header */}
          <div className="mb-5 flex items-start gap-3 animate-card-in">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
              <ActiveIcon size={20} strokeWidth={2} />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-content-primary">
                {t(activeTabDef.labelKey, { defaultValue: activeTabDef.defaultLabel })}
              </h2>
              <p className="text-sm text-content-secondary mt-0.5">
                {t(activeTabDef.descKey, { defaultValue: activeTabDef.descDefault })}
              </p>
            </div>
          </div>

          {/* Cards grid: 2 cols desktop, 1 col mobile. Cards can opt into
              full-width via `lg:col-span-2`. */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 [&>*]:animate-card-in">

          {/* ── GENERAL ──────────────────────────────────────────── */}
          {activeTab === 'general' && (
            <>
              <ProfileCard
                profile={profile}
                loading={profileLoading}
                editing={editingProfile}
                setEditing={setEditingProfile}
                formName={profileForm.full_name}
                setFormName={(v) => setProfileForm({ full_name: v })}
                onSave={() => profileMutation.mutate({ full_name: profileForm.full_name })}
                saving={profileMutation.isPending}
              />
              <AppearanceCard />
              <InterfaceModeCard />
            </>
          )}

          {/* ── DASHBOARD LAYOUT ─────────────────────────────────── */}
          {activeTab === 'dashboard' && (
            <Card className="lg:col-span-2">
              <CardHeader
                title={t('dashboard.layout.title', { defaultValue: 'Customize dashboard' })}
                subtitle={t('settings.dashboard_layout_subtitle', {
                  defaultValue:
                    'Choose which sections appear on your dashboard and in what order. This is personal to you and saved to this browser.',
                })}
              />
              <CardContent>
                <DashboardLayoutManager />
              </CardContent>
            </Card>
          )}

          {/* ── ACCOUNT ──────────────────────────────────────────── */}
          {activeTab === 'account' && (
            <>
              {/* Change password */}
              <Card className="lg:col-span-2">
                <CardHeader
                  title={t('settings.change_password_title', { defaultValue: 'Change Password' })}
                  subtitle={t('settings.change_password_subtitle', { defaultValue: 'Update your account password. Minimum 8 characters.' })}
                />
                <CardContent>
                  {showPwFields ? (
                    <form
                      className="space-y-4 max-w-md"
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (pwValid && !pwMutation.isPending) {
                          pwMutation.mutate({ current_password: pwForm.current, new_password: pwForm.new_ });
                        }
                      }}
                    >
                      <div>
                        <label htmlFor="pw-current" className="block text-sm font-medium text-content-primary mb-1">
                          {t('settings.current_password', { defaultValue: 'Current password' })}
                        </label>
                        <input
                          id="pw-current"
                          type="password"
                          autoComplete="current-password"
                          className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors"
                          value={pwForm.current}
                          onChange={(e) => setPwForm((f) => ({ ...f, current: e.target.value }))}
                        />
                      </div>
                      <div>
                        <label htmlFor="pw-new" className="block text-sm font-medium text-content-primary mb-1">
                          {t('settings.new_password', { defaultValue: 'New password' })}
                        </label>
                        <input
                          id="pw-new"
                          type="password"
                          autoComplete="new-password"
                          className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors"
                          placeholder={t('settings.password_min_hint', { defaultValue: 'Minimum 8 characters' })}
                          value={pwForm.new_}
                          onChange={(e) => setPwForm((f) => ({ ...f, new_: e.target.value }))}
                        />
                        <p className="mt-1 text-xs text-content-tertiary">
                          {t('settings.password_min_hint', { defaultValue: 'Minimum 8 characters' })}
                        </p>
                      </div>
                      <div>
                        <label htmlFor="pw-confirm" className="block text-sm font-medium text-content-primary mb-1">
                          {t('settings.confirm_new_password', { defaultValue: 'Confirm new password' })}
                        </label>
                        <input
                          id="pw-confirm"
                          type="password"
                          autoComplete="new-password"
                          className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors"
                          value={pwForm.confirm}
                          onChange={(e) => setPwForm((f) => ({ ...f, confirm: e.target.value }))}
                        />
                        {pwForm.confirm && pwForm.new_ !== pwForm.confirm && (
                          <p className="mt-1 text-xs text-semantic-error">
                            {t('settings.passwords_mismatch', { defaultValue: 'Passwords do not match' })}
                          </p>
                        )}
                      </div>
                      <div className="flex gap-2 pt-1">
                        <Button type="submit" disabled={!pwValid || pwMutation.isPending} loading={pwMutation.isPending}>
                          {t('settings.update_password', { defaultValue: 'Update Password' })}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => { setPwForm({ current: '', new_: '', confirm: '' }); setShowPwFields(false); }}
                        >
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                    </form>
                  ) : (
                    <Button variant="secondary" onClick={() => setShowPwFields(true)} icon={<Lock size={14} />}>
                      {t('settings.change_password', { defaultValue: 'Change Password' })}
                    </Button>
                  )}
                </CardContent>
              </Card>

              {/* Danger zone */}
              <Card className="lg:col-span-2 border-semantic-error/30 bg-semantic-error-bg/40">
                <CardHeader
                  title={t('settings.danger_zone_title', { defaultValue: 'Danger Zone' })}
                  subtitle={t('settings.danger_zone_subtitle', { defaultValue: 'Irreversible or sensitive account actions' })}
                  action={<ShieldAlert size={20} className="text-semantic-error" aria-hidden="true" />}
                />
                <CardContent>
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 rounded-lg border border-semantic-error/20 bg-surface-elevated px-4 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-content-primary">
                        {t('settings.sign_out_title', { defaultValue: 'Sign out of all sessions' })}
                      </p>
                      <p className="text-xs text-content-secondary mt-0.5">
                        {t('settings.sign_out_desc', { defaultValue: 'You will need to enter your credentials to access OpenConstructionERP again.' })}
                      </p>
                    </div>
                    <Button
                      variant="danger"
                      icon={<LogOut size={14} />}
                      onClick={() => { logout(); window.location.href = '/login'; }}
                    >
                      {t('settings.sign_out', { defaultValue: 'Sign Out' })}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </>
          )}

          {/* ── REGIONAL ─────────────────────────────────────────── */}
          {activeTab === 'regional' && (
            <>
              {/* Language picker */}
              <Card className="lg:col-span-2">
                <CardHeader
                  title={t('settings.language_title', { defaultValue: 'Language & Region' })}
                  subtitle={t('settings.language_subtitle', { defaultValue: 'Choose your preferred language for the interface' })}
                />
                <CardContent>
                  <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-2">
                    {SUPPORTED_LANGUAGES.map((lang) => {
                      const isActive = i18n.language === lang.code;
                      return (
                        <button
                          key={lang.code}
                          onClick={() => {
                            i18n.changeLanguage(lang.code);
                            apiPatch('/v1/users/me/', { locale: lang.code }).then(() => {
                              queryClient.invalidateQueries({ queryKey: ['me'] });
                            }).catch(() => {});
                          }}
                          aria-pressed={isActive}
                          aria-label={`${lang.name} (${lang.code})`}
                          className={`flex flex-col items-center gap-1 rounded-xl px-3 py-3 text-center transition-all duration-normal ease-oe ${
                            isActive
                              ? 'bg-oe-blue-subtle border-2 border-oe-blue text-oe-blue'
                              : 'border-2 border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                          }`}
                        >
                          <span className="text-lg">{lang.flag}</span>
                          <span className="text-2xs font-medium truncate w-full" title={lang.name}>
                            {lang.name}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>

              {/* Regional Settings (timezone, units, formats, currency) */}
              <RegionalSettings />

              {/* Translation Manager */}
              <div>
                <TranslationManager />
              </div>
            </>
          )}

          {/* ── Converters ───────────────────────────────────────── */}
          {activeTab === 'converters' && (
            <div className="lg:col-span-2">
              <ConverterStatusPanel />
            </div>
          )}

          {/* ── AI ────────────────────────────────────────────────── */}
          {activeTab === 'ai' && (
            <>
              <div className="lg:col-span-2">
                <InfoHint
                  text={t('settings.ai_guidance', { defaultValue: 'AI features (estimation, takeoff analysis, semantic search) require an API key. Anthropic Claude is recommended for best accuracy. Keys are stored encrypted and never leave your server.' })}
                />
              </div>
              <AIConfigurationCard />
              <div className="lg:col-span-2">
                <VectorStatusCard />
              </div>
            </>
          )}

          {/* ── INTEGRATIONS ─────────────────────────────────────── */}
          {activeTab === 'integrations' && (
            <div className="lg:col-span-2 space-y-6">
              <Card>
                <CardHeader
                  title={t('integrations.title', { defaultValue: 'Integrations' })}
                  subtitle={t('integrations.desc', { defaultValue: 'Connect Teams, Slack, Telegram, Discord, Webhooks' })}
                />
                <CardContent>
                  <Link
                    to="/integrations"
                    className="inline-flex items-center gap-2 px-4 py-2.5 rounded-full border border-oe-blue/20 bg-oe-blue/[0.04] text-oe-blue text-sm font-medium hover:bg-oe-blue/10 transition-colors"
                  >
                    <Plug size={14} />
                    {t('integrations.configure', { defaultValue: 'Configure Integrations' })}
                  </Link>
                </CardContent>
              </Card>
              <WebhookLeads />
            </div>
          )}

          {/* ── ADVANCED ─────────────────────────────────────────── */}
          {activeTab === 'advanced' && (
            <>
              <div className="lg:col-span-2">
                <BackupRestore />
              </div>

              <Card className="lg:col-span-2">
                <CardHeader
                  title={t('settings.maintenance_title', { defaultValue: 'Maintenance & Setup' })}
                  subtitle={t('settings.maintenance_subtitle', { defaultValue: 'Cost databases, demo data, and the initial setup wizard' })}
                />
                <CardContent>
                  <ul className="divide-y divide-border-light rounded-xl border border-border-light bg-surface-secondary/30">
                    <li className="flex flex-col sm:flex-row sm:items-center gap-3 p-4">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
                        <Package size={18} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-content-primary">
                          {t('settings.databases_title', { defaultValue: 'Databases & Resources' })}
                        </p>
                        <p className="text-xs text-content-secondary mt-0.5 leading-relaxed">
                          {t('settings.databases_subtitle', { defaultValue: 'Load cost databases, resource catalogs, and demo projects' })}
                        </p>
                      </div>
                      <Link to="/setup/databases" className="sm:ml-auto shrink-0">
                        <Button variant="secondary" size="sm" icon={<ChevronRight size={14} />} iconPosition="right">
                          {t('common.open', { defaultValue: 'Open' })}
                        </Button>
                      </Link>
                    </li>
                    <li className="flex flex-col sm:flex-row sm:items-center gap-3 p-4">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
                        <Wrench size={18} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-content-primary">
                          {t('settings.setup_wizard_title', { defaultValue: 'Setup Wizard' })}
                        </p>
                        <p className="text-xs text-content-secondary mt-0.5 leading-relaxed">
                          {t('settings.setup_wizard_subtitle', { defaultValue: 'Re-run the initial setup to change language, install databases, catalogs, or demo projects' })}
                        </p>
                      </div>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<ChevronRight size={14} />}
                        iconPosition="right"
                        className="sm:ml-auto shrink-0"
                        onClick={() => {
                          try { localStorage.removeItem('oe_onboarding_completed'); } catch { /* ignore storage errors */ }
                          window.location.href = '/onboarding';
                        }}
                      >
                        {t('common.open', { defaultValue: 'Open' })}
                      </Button>
                    </li>
                  </ul>
                </CardContent>
              </Card>
            </>
          )}
          </div>{/* End cards grid */}

          {/* About link — mobile only (desktop has it in sidebar) */}
          <div className="lg:hidden mt-8 text-center">
            <Link
              to="/about"
              className="inline-flex items-center gap-1 text-sm text-content-tertiary hover:text-oe-blue transition-colors"
            >
              {t('settings.about_link', { defaultValue: 'About OpenConstructionERP' })}
              <ChevronRight size={12} />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Converters panel ────────────────────────────────────────────────────────
// Lists every DDC CAD/BIM converter, shows installed-vs-latest version and
// a link to the corresponding source on GitHub. Backed by
// /api/system/converters/version-check (cached server-side for 6 h).

interface ConverterRow {
  id: string;
  name: string;
  exe: string;
  installed: boolean;
  installed_path: string | null;
  installed_size: number | null;
  installed_sha: string | null;
  latest_size: number | null;
  latest_sha: string | null;
  is_outdated: boolean;
  download_url: string | null;
  html_url: string | null;
}

interface ConverterStatusResponse {
  converters: ConverterRow[];
  any_outdated: boolean;
  network_ok: boolean;
  checked_at: string;
  ttl_seconds: number;
}

const DDC_REPO_URL =
  'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto';

function formatBytes(n: number | null): string {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function ConverterStatusPanel() {
  const { t } = useTranslation();
  const { data, isLoading, isError, refetch, isFetching } = useQuery<ConverterStatusResponse>({
    queryKey: ['system', 'converters', 'version-check'],
    queryFn: () => apiGet<ConverterStatusResponse>('/api/system/converters/version-check'),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <div className="space-y-4">
      {/* Live health banner — same component used on /bim. Surfaces smoke
       *  tests (verify=true), one-click install / update / re-check actions
       *  with live progress, and a top-level "{{ok}}/{{total}} working"
       *  pill. This is what the user wanted parity with: "проверки версий
       *  и показа какие версии используются в платформе - похожи на ту что
       *  есть в БИМ разделе". */}
      <BIMConverterStatusBanner />

      <Card>
      <CardHeader
        title={t('settings.converters_title', { defaultValue: 'Converters' })}
        subtitle={t('settings.converters_subtitle', {
          defaultValue:
            'DDC cad2data pipeline — installed bridges and the latest source available on GitHub.',
        })}
        action={
          <button
            type="button"
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
            disabled={isFetching}
            aria-label={t('common.refresh', { defaultValue: 'Refresh' })}
          >
            {isFetching ? <Loader2 size={12} className="animate-spin" /> : <Package size={12} />}
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </button>
        }
      />
      <CardContent>
        <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-secondary/40 px-3.5 py-2.5">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-content-primary">
              {t('settings.converters_source_title', {
                defaultValue: 'Source repository',
              })}
            </p>
            <p className="text-2xs text-content-tertiary">
              {t('settings.converters_source_desc', {
                defaultValue:
                  'Open-source converters for Revit (RVT), IFC, DWG and DGN, maintained by DataDrivenConstruction.',
              })}
            </p>
          </div>
          <a
            href={DDC_REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-oe-blue/30 bg-oe-blue/[0.04] px-2.5 py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          >
            <ExternalLink size={12} />
            {t('settings.converters_open_repo', { defaultValue: 'GitHub repo' })}
          </a>
        </div>

        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}

        {!isLoading && isError && (
          <div className="rounded-lg border border-red-300/40 bg-red-50 px-3 py-3 text-xs text-red-900 dark:bg-red-950/40 dark:text-red-100">
            <div className="flex items-start gap-2">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <div className="space-y-1">
                <div className="font-semibold">
                  {t('settings.converters_error_title', {
                    defaultValue: 'Could not check converter versions',
                  })}
                </div>
                <div className="opacity-80">
                  {t('settings.converters_error_hint', {
                    defaultValue:
                      'The backend could not reach GitHub. Installed converters still work — only the up-to-date check is unavailable.',
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {!isLoading && !isError && data && (
          <>
            {!data.network_ok && (
              <div className="mb-3 rounded-md border border-amber-300/40 bg-amber-50 px-3 py-2 text-2xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                {t('settings.converters_offline_hint', {
                  defaultValue:
                    'GitHub is not reachable from the server right now. Showing installed-only status; the up-to-date check is skipped.',
                })}
              </div>
            )}
            <ul className="space-y-2">
              {data.converters.map((c) => {
                const status: 'outdated' | 'current' | 'missing' = !c.installed
                  ? 'missing'
                  : c.is_outdated
                    ? 'outdated'
                    : 'current';
                const statusLabel =
                  status === 'missing'
                    ? t('settings.converter_status_missing', { defaultValue: 'Not installed' })
                    : status === 'outdated'
                      ? t('settings.converter_status_outdated', { defaultValue: 'Update available' })
                      : t('settings.converter_status_current', { defaultValue: 'Up to date' });
                const statusClass =
                  status === 'missing'
                    ? 'bg-slate-100 text-slate-700 ring-1 ring-slate-300/60 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700'
                    : status === 'outdated'
                      ? 'bg-amber-100 text-amber-900 ring-1 ring-amber-300/60 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-700/60'
                      : 'bg-emerald-100 text-emerald-900 ring-1 ring-emerald-300/60 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-700/60';
                const StatusIcon = status === 'current' ? CheckCircle2 : status === 'outdated' ? AlertCircle : XCircle;
                return (
                  <li
                    key={c.id}
                    className="flex items-start gap-3 rounded-lg border border-border-light bg-surface-secondary/30 px-3.5 py-3"
                  >
                    <div className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-tertiary text-content-secondary">
                      <Layers size={14} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-content-primary">
                          {c.name}
                        </span>
                        <span className="font-mono text-2xs text-content-tertiary">
                          {c.exe}
                        </span>
                        <span
                          className={['inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium', statusClass].join(' ')}
                        >
                          <StatusIcon size={11} />
                          {statusLabel}
                        </span>
                      </div>
                      <dl className="mt-1.5 grid grid-cols-1 gap-x-4 gap-y-0.5 text-2xs text-content-tertiary sm:grid-cols-2">
                        <div className="flex items-center gap-1.5">
                          <dt className="font-medium uppercase tracking-wider">
                            {t('settings.converter_installed', { defaultValue: 'Installed' })}
                          </dt>
                          <dd className="font-mono">
                            {c.installed
                              ? `${formatBytes(c.installed_size)} · ${c.installed_sha?.slice(0, 7) ?? '—'}`
                              : '—'}
                          </dd>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <dt className="font-medium uppercase tracking-wider">
                            {t('settings.converter_latest', { defaultValue: 'Latest' })}
                          </dt>
                          <dd className="font-mono">
                            {c.latest_sha
                              ? `${formatBytes(c.latest_size)} · ${c.latest_sha.slice(0, 7)}`
                              : t('settings.converter_unknown', { defaultValue: 'Unknown' })}
                          </dd>
                        </div>
                      </dl>
                      {c.installed_path && (
                        <p
                          className="mt-1 truncate font-mono text-2xs text-content-tertiary"
                          title={c.installed_path}
                        >
                          {c.installed_path}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col gap-1.5">
                      {c.html_url && (
                        <a
                          href={c.html_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-2xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
                        >
                          <ExternalLink size={11} />
                          {t('settings.converter_view_source', { defaultValue: 'GitHub' })}
                        </a>
                      )}
                      {c.download_url && (
                        <a
                          href={c.download_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          download
                          className={[
                            'inline-flex items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium',
                            status === 'outdated' || status === 'missing'
                              ? 'border border-oe-blue/30 bg-oe-blue/[0.04] text-oe-blue hover:bg-oe-blue/10'
                              : 'border border-border-light text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
                          ].join(' ')}
                        >
                          <Package size={11} />
                          {status === 'missing'
                            ? t('settings.converter_install', { defaultValue: 'Download' })
                            : status === 'outdated'
                              ? t('settings.converter_update', { defaultValue: 'Update' })
                              : t('settings.converter_reinstall', { defaultValue: 'Re-download' })}
                        </a>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="mt-3 text-2xs text-content-tertiary">
              {t('settings.converters_checked_at', {
                defaultValue: 'Last checked: {{when}} (cached for 6 h)',
                when: new Date(data.checked_at).toLocaleString(getIntlLocale()),
              })}
            </p>
          </>
        )}
      </CardContent>
    </Card>
    </div>
  );
}
