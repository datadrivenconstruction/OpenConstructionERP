import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { getIntlLocale } from '@/shared/lib/formatters';
import { TranslationManager } from './TranslationManager';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Eye,
  EyeOff,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ExternalLink,
  Loader2,
  Sun,
  Moon,
  Monitor,
  Pencil,
  Save,
} from 'lucide-react';
import { Card, CardHeader, CardContent, CardFooter, Button, Badge, InfoHint, Skeleton, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPatch } from '@/shared/lib/api';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useAuthStore } from '@/stores/useAuthStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { useToastStore } from '@/stores/useToastStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { aiApi, type AIProvider, type AIConnectionStatus, type AISettings } from '@/features/ai/api';

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
  keyPrefix: string;
  docsUrl: string;
  recommended?: boolean;
}

const AI_PROVIDERS: ProviderInfo[] = [
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    description: 'settings.ai_desc_anthropic',
    keyPrefix: 'sk-ant-',
    docsUrl: 'https://console.anthropic.com/settings/keys',
    recommended: true,
  },
  {
    id: 'openai',
    name: 'OpenAI GPT-4',
    description: 'settings.ai_desc_openai',
    keyPrefix: 'sk-',
    docsUrl: 'https://platform.openai.com/api-keys',
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    description: 'settings.ai_desc_gemini',
    keyPrefix: 'AI',
    docsUrl: 'https://aistudio.google.com/app/apikey',
  },
];

// ── Helpers ──────────────────────────────────────────────────────────────────

function maskApiKey(key: string | null | undefined): string {
  if (!key) return '';
  if (key.length <= 8) return '\u2022'.repeat(key.length);
  return key.slice(0, 8) + '\u2022'.repeat(Math.min(key.length - 8, 24));
}

function isKeySetForProvider(settings: AISettings | undefined, provider: AIProvider): boolean {
  if (!settings) return false;
  switch (provider) {
    case 'anthropic':
      return settings.anthropic_api_key_set;
    case 'openai':
      return settings.openai_api_key_set;
    case 'gemini':
      return settings.gemini_api_key_set;
  }
}

function StatusIndicator({ status, lastTested }: { status: AIConnectionStatus; lastTested: string | null }) {
  const { t } = useTranslation();

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

function formatTimeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ── AI Configuration Card ────────────────────────────────────────────────────

function AIConfigurationCard({ animationDelay }: { animationDelay: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // State
  const [selectedProvider, setSelectedProvider] = useState<AIProvider>('anthropic');
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [hasUnsavedKey, setHasUnsavedKey] = useState(false);

  // Fetch current settings
  const { data: settings } = useQuery({
    queryKey: ['ai-settings'],
    queryFn: aiApi.getSettings,
    retry: false,
  });

  // Sync provider selection when settings are loaded
  useEffect(() => {
    if (settings?.provider) {
      setSelectedProvider(settings.provider);
    }
  }, [settings?.provider]);

  const hasKeySet = isKeySetForProvider(settings, selectedProvider);

  // Test connection mutation
  const testMutation = useMutation({
    mutationFn: () => aiApi.testConnection(selectedProvider),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
      if (result.success) {
        addToast({
          type: 'success',
          title: t('settings.ai_test_success', { defaultValue: 'Connection successful' }),
          message: result.latency_ms
            ? t('settings.ai_test_latency', {
                defaultValue: 'Response time: {{ms}}ms',
                ms: result.latency_ms,
              })
            : undefined,
        });
      } else {
        addToast({
          type: 'error',
          title: t('settings.ai_test_failed', { defaultValue: 'Connection failed' }),
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
      const update: Record<string, string | null> = {
        provider: selectedProvider,
      };
      if (hasUnsavedKey && apiKeyInput.trim()) {
        const keyField = `${selectedProvider}_api_key`;
        update[keyField] = apiKeyInput.trim();
      }
      return aiApi.updateSettings(update as Parameters<typeof aiApi.updateSettings>[0]);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
      setApiKeyInput('');
      setHasUnsavedKey(false);
      setShowKey(false);
      addToast({
        type: 'success',
        title: t('settings.ai_saved', { defaultValue: 'AI settings saved' }),
      });
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
  }, []);

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
    <Card className="animate-card-in" style={{ animationDelay }}>
      <CardHeader
        title={t('settings.ai_title', { defaultValue: 'AI Configuration' })}
        subtitle={t('settings.ai_subtitle', {
          defaultValue: 'Choose your AI provider for estimation and analysis',
        })}
      />
      <CardContent>
        <div className="space-y-5">
          {/* Provider selection */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-3">
              {t('settings.ai_provider', { defaultValue: 'AI Provider' })}
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
              {AI_PROVIDERS.map((provider) => {
                const isSelected = selectedProvider === provider.id;
                const hasKey = isKeySetForProvider(settings, provider.id);

                return (
                  <button
                    key={provider.id}
                    type="button"
                    onClick={() => handleProviderChange(provider.id)}
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
                      {t(provider.description, { defaultValue: provider.description })}
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
              <label className="text-sm font-medium text-content-primary">
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
                type={showKey && hasUnsavedKey ? 'text' : 'text'}
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
          disabled={saveMutation.isPending}
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

function InterfaceModeCard({ animationDelay }: { animationDelay: string }) {
  const { t } = useTranslation();
  const mode = useViewModeStore((s) => s.mode);
  const setMode = useViewModeStore((s) => s.setMode);
  const isAdvanced = mode === 'advanced';

  return (
    <Card className="animate-card-in" style={{ animationDelay }}>
      <CardHeader
        title={t('settings.interface_mode_title', { defaultValue: 'Interface Mode' })}
        subtitle={t('settings.interface_mode_subtitle', { defaultValue: 'Control which features are visible in the navigation' })}
      />
      <CardContent>
        <div className="flex gap-3">
          <button
            onClick={() => setMode('simple')}
            className={`flex-1 flex flex-col items-center gap-2 rounded-xl px-4 py-4 border-2 transition-all ${
              !isAdvanced
                ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
            }`}
          >
            <span className="text-sm font-semibold">{t('nav.mode_simple', { defaultValue: 'Simple' })}</span>
            <span className="text-2xs text-center">{t('settings.mode_simple_detail', { defaultValue: 'Essential estimation tools. Clean interface for focused work.' })}</span>
            <span className={`mt-1 inline-flex h-5 items-center rounded-full px-2 text-2xs font-bold tracking-wide ${
              !isAdvanced ? 'bg-oe-blue/15 text-oe-blue' : 'bg-surface-tertiary text-content-tertiary'
            }`}>STD</span>
          </button>
          <button
            onClick={() => setMode('advanced')}
            className={`flex-1 flex flex-col items-center gap-2 rounded-xl px-4 py-4 border-2 transition-all ${
              isAdvanced
                ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                : 'border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
            }`}
          >
            <span className="text-sm font-semibold">{t('nav.mode_advanced', { defaultValue: 'Advanced' })}</span>
            <span className="text-2xs text-center">{t('settings.mode_advanced_detail', { defaultValue: 'Full professional toolset with all modules and features visible.' })}</span>
            <span className={`mt-1 inline-flex h-5 items-center rounded-full px-2 text-2xs font-bold tracking-wide ${
              isAdvanced ? 'bg-oe-blue/15 text-oe-blue' : 'bg-surface-tertiary text-content-tertiary'
            }`}>PRO</span>
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

function AppearanceCard({ animationDelay }: { animationDelay: string }) {
  const { t } = useTranslation();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);

  return (
    <Card className="animate-card-in" style={{ animationDelay }}>
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

// ── Main Settings Page ───────────────────────────────────────────────────────

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const logout = useAuthStore((s) => s.logout);
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [editingProfile, setEditingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState({ full_name: '' });

  const { data: profile, isPending: profileLoading } = useQuery({
    queryKey: ['me'],
    queryFn: () => apiGet<UserProfile>('/v1/users/me'),
    retry: false,
  });

  const profileMutation = useMutation({
    mutationFn: (data: { full_name: string }) =>
      apiPatch<UserProfile>('/v1/users/me', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me'] });
      setEditingProfile(false);
      addToast({ type: 'success', title: t('toasts.profile_updated', { defaultValue: 'Profile updated' }) });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('nav.settings', 'Settings') },
      ]} className="mb-2" />

      <div className="animate-card-in" style={{ animationDelay: '0ms' }}>
        <h1 className="text-2xl font-bold text-content-primary">{t('nav.settings', 'Settings')}</h1>
        <p className="mt-1 text-sm text-content-secondary">{t('settings.subtitle', { defaultValue: 'Manage your account and preferences' })}</p>
      </div>

      {/* Profile */}
      <Card className="animate-card-in" style={{ animationDelay: '100ms' }}>
        <CardHeader title={t('settings.profile_title', { defaultValue: 'Profile' })} subtitle={t('settings.profile_subtitle', { defaultValue: 'Your personal information' })} />
        <CardContent>
          {profile ? (
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-oe-blue text-xl font-bold text-white">
                  {profile.full_name?.charAt(0)?.toUpperCase() || 'U'}
                </div>
                <div className="flex-1 min-w-0">
                  {editingProfile ? (
                    <div className="flex items-center gap-2">
                      <input
                        value={profileForm.full_name}
                        onChange={(e) => setProfileForm({ full_name: e.target.value })}
                        className="text-base font-semibold text-content-primary bg-surface-secondary rounded-lg px-3 py-1.5 border border-border-light focus:outline-none focus:ring-2 focus:ring-oe-blue/30 w-48"
                        placeholder={t('settings.full_name', { defaultValue: 'Full name' })}
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') profileMutation.mutate({ full_name: profileForm.full_name });
                          if (e.key === 'Escape') setEditingProfile(false);
                        }}
                      />
                      <button
                        onClick={() => profileMutation.mutate({ full_name: profileForm.full_name })}
                        disabled={!profileForm.full_name.trim() || profileMutation.isPending}
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-oe-blue hover:bg-oe-blue-subtle transition-colors disabled:opacity-50"
                        title={t('common.save')}
                      >
                        <Save size={16} />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <div className="text-base font-semibold text-content-primary">{profile.full_name}</div>
                      <button
                        onClick={() => {
                          setProfileForm({ full_name: profile.full_name || '' });
                          setEditingProfile(true);
                        }}
                        className="flex h-6 w-6 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-secondary transition-colors"
                        title={t('common.edit')}
                      >
                        <Pencil size={12} />
                      </button>
                    </div>
                  )}
                  <div className="text-sm text-content-secondary">{profile.email}</div>
                  <Badge variant="blue" size="sm" className="mt-1">{profile.role}</Badge>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4 pt-2 border-t border-border-light">
                <div>
                  <span className="text-xs text-content-tertiary">{t('settings.member_since', { defaultValue: 'Member since' })}</span>
                  <div className="text-sm text-content-primary">{new Date(profile.created_at).toLocaleDateString(getIntlLocale())}</div>
                </div>
                <div>
                  <span className="text-xs text-content-tertiary">{t('settings.status', { defaultValue: 'Status' })}</span>
                  <div><Badge variant={profile.is_active ? 'success' : 'error'} size="sm" dot>{profile.is_active ? t('settings.active', { defaultValue: 'Active' }) : t('settings.inactive', { defaultValue: 'Inactive' })}</Badge></div>
                </div>
              </div>
            </div>
          ) : profileLoading ? (
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <Skeleton className="h-14 w-14 rounded-full" />
                <div className="space-y-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-48" />
                  <Skeleton className="h-5 w-16 rounded-full" />
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-content-secondary">{t('settings.profile_error', { defaultValue: 'Could not load profile' })}</p>
          )}
        </CardContent>
      </Card>

      {/* Interface Mode */}
      <InterfaceModeCard animationDelay="120ms" />

      {/* AI Configuration */}
      <InfoHint className="animate-card-in" text={t('settings.ai_guidance', { defaultValue: 'AI features (estimation, takeoff analysis, semantic search) require an API key. Anthropic Claude is recommended for best accuracy. Keys are stored encrypted and never leave your server.' })} />
      <AIConfigurationCard animationDelay="150ms" />

      {/* Language */}
      <Card className="animate-card-in" style={{ animationDelay: '200ms' }}>
        <CardHeader title={t('settings.language_title', { defaultValue: 'Language & Region' })} subtitle={t('settings.language_subtitle', { defaultValue: 'Choose your preferred language' })} />
        <CardContent>
          <div className="grid grid-cols-4 sm:grid-cols-5 gap-2">
            {SUPPORTED_LANGUAGES.map((lang) => {
              const isActive = i18n.language === lang.code;
              return (
                <button
                  key={lang.code}
                  onClick={() => i18n.changeLanguage(lang.code)}
                  className={`flex flex-col items-center gap-1 rounded-xl px-3 py-3 text-center transition-all duration-normal ease-oe ${
                    isActive
                      ? 'bg-oe-blue-subtle border-2 border-oe-blue text-oe-blue'
                      : 'border-2 border-transparent hover:bg-surface-secondary text-content-secondary hover:text-content-primary'
                  }`}
                >
                  <span className="text-lg">{lang.flag}</span>
                  <span className="text-2xs font-medium truncate w-full">{lang.name}</span>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Appearance */}
      <AppearanceCard animationDelay="250ms" />

      {/* Translation Manager */}
      <div className="animate-card-in" style={{ animationDelay: '300ms' }}>
        <TranslationManager />
      </div>

      {/* Danger zone */}
      <Card className="animate-card-in border-semantic-error/20" style={{ animationDelay: '350ms' }}>
        <CardHeader title={t('settings.account_title', { defaultValue: 'Account' })} subtitle={t('settings.account_subtitle', { defaultValue: 'Sign out or manage your account' })} />
        <CardContent>
          <Button
            variant="danger"
            onClick={() => { logout(); window.location.href = '/login'; }}
          >
            {t('settings.sign_out', { defaultValue: 'Sign Out' })}
          </Button>
        </CardContent>
      </Card>

      {/* About link */}
      <div className="mt-6 text-center">
        <a href="/about" className="text-sm text-content-tertiary hover:text-oe-blue transition-colors">
          {t('settings.about_link', { defaultValue: 'About OpenConstructionERP' })} →
        </a>
      </div>
    </div>
  );
}
