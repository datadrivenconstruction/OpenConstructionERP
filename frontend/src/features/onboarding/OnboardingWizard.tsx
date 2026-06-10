import { useState, useCallback, useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
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
  Home,
  Globe,
  Languages,
  Layers,
  ChevronDown,
  XCircle,
  MinusCircle,
  AlertTriangle,
  HardHat,
  Briefcase,
  Box,
  type LucideIcon,
} from 'lucide-react';
import { Logo, Button, CountryFlag, Badge } from '@/shared/ui';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useToastStore } from '@/stores/useToastStore';
import {
  useBackgroundInstallStore,
  type BgInstallStep,
  type BackgroundInstall,
} from '@/stores/useBackgroundInstallStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { BrandingEditorModal } from '@/app/layout/CustomBranding';
import { aiApi, type AIProvider } from '@/features/ai/api';
import { apiGet, apiPost, extractErrorMessageFromBody } from '@/shared/lib/api';
import {
  ALL_MODULES,
  MODULE_GROUPS,
  CORE_MODULE_KEYS,
  TOTAL_MODULE_COUNT,
} from './modules';
import {
  COUNTRY_PACKS,
  DEFAULT_COUNTRY_PACK,
  getCountryPack,
  type CountryPack,
} from './countryPacks';
import {
  fetchInstalledPacks,
  fullInstallPackStream,
  packInitials,
  packCountryCode,
  packCountryName,
  partnerPackLogoUrl,
  FULL_INSTALL_STEPS,
  type InstalledPartnerPack,
  type FullInstallStepName,
  type FullInstallStepStatus,
} from './partnerPacksApi';

// ── Constants ────────────────────────────────────────────────────────────────

const TOTAL_STEPS = 6;

// ── Language -> Region mapping ──────────────────────────────────────────────

// Language → recommended CWICR region. Updated 2026-04-28 — most languages now
// have a proper local database; previously several locales fell back to
// DE_BERLIN/SP_BARCELONA/ZH_SHANGHAI as approximations.
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
  tr: 'TR_ISTANBUL',
  it: 'IT_ROME',
  ja: 'JA_TOKYO',
  ko: 'KO_SEOUL',
  nl: 'NL_AMSTERDAM',
  pl: 'PL_WARSAW',
  cs: 'CS_PRAGUE',
  hr: 'HR_ZAGREB',
  sv: 'SV_STOCKHOLM',
  no: 'SV_STOCKHOLM',
  da: 'SV_STOCKHOLM',
  fi: 'SV_STOCKHOLM',
  bg: 'BG_SOFIA',
  ro: 'RO_BUCHAREST',
  th: 'TH_BANGKOK',
  vi: 'VI_HANOI',
  id: 'ID_JAKARTA',
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
  // Anglosphere
  { id: 'USA_USD', name: 'United States', city: 'New York', lang: 'English', currency: 'USD', flagId: 'us' },
  { id: 'UK_GBP', name: 'United Kingdom', city: 'London', lang: 'English', currency: 'GBP', flagId: 'gb' },
  { id: 'ENG_TORONTO', name: 'Canada / International', city: 'Toronto', lang: 'English', currency: 'CAD', flagId: 'ca' },
  { id: 'AU_SYDNEY', name: 'Australia', city: 'Sydney', lang: 'English', currency: 'AUD', flagId: 'au' },
  { id: 'NZ_AUCKLAND', name: 'New Zealand', city: 'Auckland', lang: 'English', currency: 'NZD', flagId: 'nz' },
  // Western Europe
  { id: 'DE_BERLIN', name: 'Germany / DACH', city: 'Berlin', lang: 'Deutsch', currency: 'EUR', flagId: 'de' },
  { id: 'FR_PARIS', name: 'France', city: 'Paris', lang: 'Fran\u00e7ais', currency: 'EUR', flagId: 'fr' },
  { id: 'IT_ROME', name: 'Italy', city: 'Rome', lang: 'Italiano', currency: 'EUR', flagId: 'it' },
  { id: 'SP_BARCELONA', name: 'Spain / Latin America', city: 'Barcelona', lang: 'Espa\u00f1ol', currency: 'EUR', flagId: 'es' },
  { id: 'NL_AMSTERDAM', name: 'Netherlands', city: 'Amsterdam', lang: 'Nederlands', currency: 'EUR', flagId: 'nl' },
  // Central / Eastern Europe
  { id: 'PL_WARSAW', name: 'Poland', city: 'Warsaw', lang: 'Polski', currency: 'PLN', flagId: 'pl' },
  { id: 'CS_PRAGUE', name: 'Czech Republic', city: 'Prague', lang: 'Cestina', currency: 'CZK', flagId: 'cz' },
  { id: 'HR_ZAGREB', name: 'Croatia', city: 'Zagreb', lang: 'Hrvatski', currency: 'EUR', flagId: 'hr' },
  { id: 'BG_SOFIA', name: 'Bulgaria', city: 'Sofia', lang: 'Balgarski', currency: 'BGN', flagId: 'bg' },
  { id: 'RO_BUCHAREST', name: 'Romania', city: 'Bucharest', lang: 'Romana', currency: 'RON', flagId: 'ro' },
  { id: 'SV_STOCKHOLM', name: 'Sweden', city: 'Stockholm', lang: 'Svenska', currency: 'SEK', flagId: 'se' },
  { id: 'TR_ISTANBUL', name: 'T\u00fcrkiye', city: 'Istanbul', lang: 'T\u00fcrk\u00e7e', currency: 'TRY', flagId: 'tr' },
  { id: 'RU_STPETERSBURG', name: 'Russia / CIS', city: 'St. Petersburg', lang: '\u0420\u0443\u0441\u0441\u043a\u0438\u0439', currency: 'RUB', flagId: 'ru' },
  // Middle East / Africa
  { id: 'AR_DUBAI', name: 'Middle East / Gulf', city: 'Dubai', lang: '\u0627\u0644\u0639\u0631\u0628\u064a\u0629', currency: 'AED', flagId: 'ae' },
  { id: 'ZA_JOHANNESBURG', name: 'South Africa', city: 'Johannesburg', lang: 'English', currency: 'ZAR', flagId: 'za' },
  { id: 'NG_LAGOS', name: 'Nigeria', city: 'Lagos', lang: 'English', currency: 'NGN', flagId: 'ng' },
  // Asia-Pacific
  { id: 'ZH_SHANGHAI', name: 'China', city: 'Shanghai', lang: '\u4e2d\u6587', currency: 'CNY', flagId: 'cn' },
  { id: 'JA_TOKYO', name: 'Japan', city: 'Tokyo', lang: '\u65e5\u672c\u8a9e', currency: 'JPY', flagId: 'jp' },
  { id: 'KO_SEOUL', name: 'South Korea', city: 'Seoul', lang: '\ud55c\uad6d\uc5b4', currency: 'KRW', flagId: 'kr' },
  { id: 'TH_BANGKOK', name: 'Thailand', city: 'Bangkok', lang: '\u0e44\u0e17\u0e22', currency: 'THB', flagId: 'th' },
  { id: 'VI_HANOI', name: 'Vietnam', city: 'Hanoi', lang: 'Ti\u1ebfng Vi\u1ec7t', currency: 'VND', flagId: 'vn' },
  { id: 'ID_JAKARTA', name: 'Indonesia', city: 'Jakarta', lang: 'Bahasa Indonesia', currency: 'IDR', flagId: 'id' },
  { id: 'HI_MUMBAI', name: 'India / South Asia', city: 'Mumbai', lang: 'Hindi', currency: 'INR', flagId: 'in' },
  // Americas
  { id: 'PT_SAOPAULO', name: 'Brazil / Portugal', city: 'S\u00e3o Paulo', lang: 'Portugu\u00eas', currency: 'BRL', flagId: 'br' },
  { id: 'MX_MEXICOCITY', name: 'Mexico', city: 'Mexico City', lang: 'Espa\u00f1ol', currency: 'MXN', flagId: 'mx' },
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
// The profile catalogue lives in the backend as the single source of truth
// (``backend/app/core/onboarding_presets.py``, served by
// ``GET /v1/users/onboarding-presets/``). The Modules page reads the same
// endpoint, so onboarding and /modules can never drift. Each preset's module
// keys match the ``ALL_MODULES`` catalogue in ./modules and the sidebar's
// ``ROUTE_MODULE_KEY``, which is what lets a profile actually shape the menu.

interface ApiCompanyPreset {
  key: string;
  label: string;
  description: string;
  icon: string;
  tags: string[];
  enabled_modules: string[];
  module_count: number;
}

const PRESET_ICON_MAP: Record<string, LucideIcon> = {
  Building2, Calculator, ClipboardList, Pencil, Home, Boxes, HardHat, Briefcase, Box,
};

function presetIcon(name: string): LucideIcon {
  return PRESET_ICON_MAP[name] ?? Boxes;
}

/** Localised label/description for a preset, falling back to the backend's
 *  English copy when a locale string is not present. */
function usePresetText() {
  const { t } = useTranslation();
  return {
    label: (p: ApiCompanyPreset) =>
      t(`onboarding.company_${p.key}`, { defaultValue: p.label }),
    description: (p: ApiCompanyPreset) =>
      t(`onboarding.company_${p.key}_desc`, { defaultValue: p.description }),
  };
}

// Minimal fallback used only if the presets endpoint is unreachable. The SPA is
// served by the same backend, so in practice the fetch always succeeds and the
// live nine profiles are shown.
const FALLBACK_PRESETS: ApiCompanyPreset[] = [
  {
    key: 'full_enterprise',
    label: 'Full Enterprise',
    description: 'Every module across the full construction lifecycle.',
    icon: 'Boxes',
    tags: [],
    enabled_modules: ALL_MODULES.filter((m) => !m.core).map((m) => m.key),
    module_count: ALL_MODULES.filter((m) => !m.core).length,
  },
];

/** Fetch the company-type presets (shares the Modules-page query cache). */
function useOnboardingPresets(): ApiCompanyPreset[] {
  const { data } = useQuery({
    queryKey: ['onboarding-presets'],
    queryFn: () => apiGet<ApiCompanyPreset[]>('/v1/users/onboarding-presets/'),
    staleTime: 5 * 60 * 1000,
  });
  return data && data.length > 0 ? data : FALLBACK_PRESETS;
}

/** The module keys a preset enables (full_enterprise = every non-core module). */
function presetModuleSet(preset: ApiCompanyPreset): Set<string> {
  if (preset.key === 'full_enterprise') {
    return new Set(ALL_MODULES.filter((m) => !m.core).map((m) => m.key));
  }
  return new Set(preset.enabled_modules);
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function maskApiKey(key: string): string {
  if (key.length <= 8) return '\u2022'.repeat(key.length);
  return key.slice(0, 8) + '\u2022'.repeat(Math.min(key.length - 8, 24));
}

/**
 * Window event fired the moment onboarding is marked completed (any exit
 * path: finish, skip-all, skip-setup, country-pack install). The global
 * ProductTour listens for this so its first-run auto-start can fire the
 * instant onboarding ends instead of only on the next reload, and, more
 * importantly, so the tour never mounts while onboarding is still open.
 */
export const ONBOARDING_COMPLETED_EVENT = 'oe:onboarding-completed';

/** Mark onboarding as completed (local fast-path + best-effort server sync). */
export function markOnboardingCompleted(): void {
  try {
    localStorage.setItem('oe_onboarding_completed', 'true');
  } catch {
    // Storage unavailable -- ignore.
  }
  // Notify the global ProductTour (gated to start only AFTER onboarding) that
  // it may now auto-start. Dispatched on every completion path because they
  // all funnel through this helper. Guarded for non-browser (SSR/test) envs.
  try {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(ONBOARDING_COMPLETED_EVENT));
    }
  } catch {
    // CustomEvent unavailable -- ignore; the tour falls back to its
    // route/storage re-evaluation on the next dashboard mount.
  }
  // Best-effort server sync so the per-user completed flag is set on every
  // exit path (skip, the explore-all link, apply-a-pack), not just the full
  // "finish" save. Fire-and-forget: the local flag already stops a re-prompt
  // on this browser, and the dashboard first-run redirect reads the server
  // flag for fresh browsers and brand-new accounts.
  void apiPost('/v1/users/me/onboarding/complete/', undefined).catch(() => {
    /* non-critical */
  });
}

/** Check whether onboarding has been completed. */
export function isOnboardingCompleted(): boolean {
  try {
    return localStorage.getItem('oe_onboarding_completed') === 'true';
  } catch {
    return false;
  }
}

// ── Background ready-pack install driver ────────────────────────────────────
//
// The ready-made pack install used to BLOCK: it streamed every step server-side
// (apply pack -> language -> cost databases -> sample projects) and only let the
// user continue once everything finished, which spun for a long time with no
// useful status. The founder wants the LANGUAGE applied first and fast, the user
// continuing into the app the moment language + a minimal workspace are ready,
// and the heavy provisioning to keep running in the BACKGROUND with a small,
// non-blocking progress indicator.
//
// ``startBackgroundReadyPackInstall`` drives the SAME fail-soft SSE stream the
// blocking path used, but: (1) it is module-scoped, not tied to any component,
// so it survives the navigation into the app; (2) it writes live progress into
// the global ``useBackgroundInstallStore`` so the root-mounted
// ``BackgroundInstallBanner`` can render it from anywhere; and (3) it resolves a
// "language is ready" promise the instant the ``locale`` step lands, so the
// caller can route the user in immediately while the rest keeps loading.

/** Turn a finished step's detail payload into a short human string for the banner. */
function bgStepDetail(step: string, detail: Record<string, unknown>): string | undefined {
  const num = (k: string): number | undefined => {
    const v = detail[k];
    return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
  };
  if (step === 'cost_db') {
    const items = num('items');
    if (items && items > 0) return items.toLocaleString();
  }
  if (step === 'resources') {
    const resources = num('resources');
    if (resources && resources > 0) return resources.toLocaleString();
  }
  if (step === 'demos') {
    const installed = detail['installed'];
    if (Array.isArray(installed) && installed.length > 0) return String(installed.length);
  }
  return undefined;
}

/**
 * Start a ready-made pack install that keeps provisioning in the background.
 *
 * Resolves the returned promise as soon as the LANGUAGE step lands (the critical
 * fast piece) so the caller can route the user into the app, then keeps the SSE
 * stream running on its own. ``onLanguageReady`` fires with the resolved locale
 * the moment language is applied. The global background-install store is updated
 * throughout so the banner reflects live progress; the stream is fail-soft and
 * always reaches a terminal state, so the banner never spins forever.
 *
 * @returns A promise that resolves ``true`` once language is ready (the user may
 *   continue), or ``false`` if the install failed before language was applied
 *   (apply step errored) so the caller can fall back to the step-by-step flow.
 */
function startBackgroundReadyPackInstall(
  slug: string,
  country: string,
  opts: {
    onLanguageReady: (locale: string) => void;
    demoCount?: number;
  },
): Promise<boolean> {
  const store = useBackgroundInstallStore.getState();
  // Seed a minimal checklist up front so the banner has rows before the stream's
  // ``start`` frame arrives; the real labels replace these on ``start``.
  const seed: BgInstallStep[] = [
    { step: 'apply_pack', label: i18n.t('onboarding.pp_step_apply', { defaultValue: 'Apply pack' }), status: 'pending' },
    { step: 'locale', label: i18n.t('onboarding.pp_step_locale', { defaultValue: 'Language' }), status: 'pending' },
    { step: 'cost_db', label: i18n.t('onboarding.pp_step_cost_db', { defaultValue: 'Cost database' }), status: 'pending' },
    { step: 'demos', label: i18n.t('onboarding.pp_step_demos', { defaultValue: 'Example projects' }), status: 'pending' },
  ];
  store.begin(slug, country, seed);

  return new Promise<boolean>((resolve) => {
    let settled = false;
    let applyFailed = false;
    let localeApplied = false;

    const finishLanguage = (ok: boolean) => {
      if (settled) return;
      settled = true;
      resolve(ok);
    };

    void fullInstallPackStream(
      slug,
      (evt) => {
        const s = useBackgroundInstallStore.getState();
        if (evt.type === 'start') {
          // Replace the seed with the server's real, localized step list.
          const steps: BgInstallStep[] = evt.steps.map((d) => ({
            step: d.step,
            label: i18n.t(d.label_key, { defaultValue: d.label }),
            status: 'pending',
          }));
          s.begin(slug, country, steps);
        } else if (evt.type === 'step_start') {
          s.markRunning(evt.step);
        } else if (evt.type === 'step_done') {
          s.markDone(evt.step, evt.status, bgStepDetail(evt.step, evt.detail));
          if (evt.step === 'apply_pack' && evt.status === 'error') {
            // Apply failed before language could be applied -- the whole install
            // cannot proceed. Tell the caller to fall back to step-by-step.
            applyFailed = true;
          }
          if (evt.step === 'locale') {
            // Language is the fast critical piece. Apply it client-side and let
            // the caller route the user in, even though cost DBs / demos are
            // still loading in the background.
            if (!applyFailed) {
              const locale =
                typeof evt.detail['locale'] === 'string' ? (evt.detail['locale'] as string) : null;
              if (locale && !localeApplied) {
                localeApplied = true;
                opts.onLanguageReady(locale);
              }
              finishLanguage(true);
            }
          }
        } else if (evt.type === 'done') {
          const hadError = evt.steps.some((st) => st.status === 'error');
          s.finish(hadError);
          // If the stream ended without ever applying language (e.g. a pack with
          // no locale, or an early apply error), release the caller now so it is
          // never left awaiting forever.
          finishLanguage(!applyFailed && evt.ok);
        }
      },
      { demoCount: opts.demoCount ?? 2 },
    ).catch(() => {
      // Transport failure: mark any still-running rows as errored and release
      // the caller so onboarding does not hang.
      const s = useBackgroundInstallStore.getState();
      const inst = s.install;
      if (inst) {
        for (const row of inst.steps) {
          if (row.status === 'running' || row.status === 'pending') {
            s.markDone(row.step, 'error');
          }
        }
        s.finish(true);
      }
      finishLanguage(localeApplied);
    });
  });
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

  // Percent of the track filled. Anchors the animated progress line
  // independent of how the dots themselves are laid out so that the
  // bar is continuous even on narrow viewports where labels wrap.
  const pct = total > 1 ? (current / (total - 1)) * 100 : 0;

  return (
    <div className="w-full">
      <div className="relative">
        {/* Track behind everything — continuous line. */}
        <div className="absolute top-[14px] start-[14px] end-[14px] h-[3px] rounded-full bg-border-light/80 dark:bg-white/10" />
        {/* Filled portion — animates on step change. */}
        <div
          className="absolute top-[14px] start-[14px] h-[3px] rounded-full bg-gradient-to-r from-oe-blue via-blue-500 to-purple-500 transition-[width] duration-500 ease-oe"
          style={{ width: `calc(${pct}% - ${pct === 0 ? 0 : 14}px)` }}
          aria-hidden
        />
        {/* Step dots + labels */}
        <div className="relative flex items-start justify-between">
          {Array.from({ length: total }).map((_, i) => {
            const done = i < current;
            const here = i === current;
            return (
              <div key={i} className="flex flex-col items-center gap-1.5 min-w-0 flex-1">
                <div
                  className={clsx(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-2xs font-bold transition-all duration-500 ease-oe',
                    done
                      ? 'bg-oe-blue text-white shadow-sm'
                      : here
                        ? 'bg-white dark:bg-surface-elevated text-oe-blue ring-2 ring-oe-blue shadow-[0_0_0_4px_rgba(37,99,235,0.18)] scale-110'
                        : 'bg-surface-secondary text-content-tertiary',
                  )}
                >
                  {done ? <Check size={13} strokeWidth={3} /> : i + 1}
                </div>
                <span
                  className={clsx(
                    'text-[10px] font-medium transition-colors whitespace-nowrap hidden sm:block',
                    here
                      ? 'text-oe-blue'
                      : done
                        ? 'text-content-secondary'
                        : 'text-content-quaternary',
                  )}
                >
                  {stepLabels[i] ?? ''}
                </span>
              </div>
            );
          })}
        </div>
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

  // BUG-LANG-AUTODETECT: ``i18nextLng`` may already hold a stale value
  // from a previous tester / demo session even on a fresh admin
  // registration, so a US-Windows en-US browser landed in Polish UI.
  // The fix splits "explicit user choice" from "any past i18next
  // default" — only ``oe_lang_explicit`` (set when the user clicks Next
  // on the language step, see ``onSelect`` below) blocks re-detection.
  useEffect(() => {
    const explicit = localStorage.getItem('oe_lang_explicit');
    if (explicit) return;
    const detected = navigator.language?.split('-')[0] || 'en';
    const match = SUPPORTED_LANGUAGES.find((l) => l.code === detected);
    const target = match ? match.code : 'en';
    if (target !== i18n.language) {
      i18n.changeLanguage(target);
      onLanguageChange(target);
    }
    setSelected(target);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col items-center text-center">
      {/* Logo with a soft decorative halo behind it. */}
      <div className="relative mb-3">
        <div
          className="absolute inset-0 -m-6 rounded-full blur-2xl opacity-60"
          style={{
            background:
              'radial-gradient(circle, rgba(37, 99, 235, 0.35), transparent 70%)',
          }}
          aria-hidden
        />
        <div className="relative">
          <Logo size="lg" animate />
        </div>
      </div>

      <Badge variant="blue" size="sm" className="mb-2">
        <Sparkles size={11} className="me-1" />
        {t('onboarding.welcome_eyebrow', { defaultValue: 'Construction estimation, reimagined' })}
      </Badge>

      <h1 className="text-2xl sm:text-3xl font-bold text-content-primary tracking-tight">
        {t('onboarding.welcome_title', { defaultValue: 'Welcome to OpenConstructionERP' })}
      </h1>

      <p className="mt-2 max-w-md text-sm sm:text-base text-content-secondary leading-relaxed">
        {t('onboarding.welcome_subtitle', {
          defaultValue:
            'The professional construction cost estimation platform. Set up your workspace in a few simple steps.',
        })}
      </p>

      {/* Language grid — 24 languages, flag + native name. */}
      <div className="mt-5 w-full">
        <div className="mb-2 flex items-center justify-center gap-2 text-xs font-medium text-content-tertiary uppercase tracking-wider">
          <span className="h-px w-8 bg-border-light" aria-hidden />
          {t('onboarding.welcome_pick_language', { defaultValue: 'Pick your language' })}
          <span className="h-px w-8 bg-border-light" aria-hidden />
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2.5">
          {SUPPORTED_LANGUAGES.map((lang) => {
            const isSelected = selected === lang.code;
            return (
              <button
                key={lang.code}
                onClick={() => handleSelect(lang.code)}
                className={clsx(
                  'relative flex items-center gap-3 rounded-xl px-3.5 py-3 text-start',
                  'backdrop-blur-md transition-all duration-normal ease-oe',
                  isSelected
                    ? 'bg-oe-blue-subtle/70 ring-2 ring-oe-blue/50 shadow-sm shadow-oe-blue/15'
                    : 'bg-surface-elevated/50 ring-1 ring-white/50 dark:ring-white/10 shadow-sm shadow-black/[0.04] hover:bg-oe-blue-subtle/30 hover:-translate-y-0.5 hover:shadow-md hover:shadow-black/[0.06] active:scale-[0.98]',
                )}
              >
                <CountryFlag code={lang.country} size={24} className="shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-content-primary truncate">
                    {lang.name}
                  </div>
                  <div className="text-2xs text-content-tertiary uppercase tracking-wide">
                    {lang.code}
                  </div>
                </div>
                {isSelected && (
                  <CheckCircle2 size={14} className="text-oe-blue shrink-0" />
                )}
              </button>
            );
          })}
        </div>
      </div>

      <Button
        variant="primary"
        size="lg"
        onClick={() => {
          // BUG-LANG-AUTODETECT — record that the user explicitly committed
          // to a language via the wizard. The auto-detect useEffect above
          // checks this flag to distinguish "real choice" from "stale
          // ``i18nextLng`` left over from a previous tester or demo
          // session". Without this set, an English-Windows browser whose
          // ``i18nextLng`` happens to read ``pl`` (because someone else
          // demoed the build in Polish) would silently switch back to
          // Polish on the next page load.
          localStorage.setItem('oe_lang_explicit', '1');
          onNext();
        }}
        icon={<ArrowRight size={18} />}
        iconPosition="right"
        className="mt-5 shadow-lg shadow-oe-blue/20"
      >
        {t('onboarding.get_started', { defaultValue: 'Get Started' })}
      </Button>
    </div>
  );
}

// ── Step 2: "How would you like to start?" ──────────────────────────────────

function StepStartChoice({
  onQuickStart,
  onChooseProfile,
  onReadyPack,
  onBack,
}: {
  onQuickStart: () => void;
  onChooseProfile: () => void;
  /** Open the ready-made pack picker (a turnkey country starter pack). */
  onReadyPack: () => void;
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

      <div className="mt-10 w-full max-w-5xl grid grid-cols-1 sm:grid-cols-3 gap-5">
        {/* Quick Start card */}
        <button
          onClick={onQuickStart}
          className={clsx(
            'group relative flex flex-col items-start rounded-3xl p-8 text-left min-h-[340px]',
            'bg-surface-elevated/70 backdrop-blur-md shadow-sm shadow-black/[0.04]',
            'hover:bg-oe-blue-subtle/30 hover:shadow-2xl hover:shadow-oe-blue/10 hover:-translate-y-1',
            'transition-all duration-300 ease-oe active:scale-[0.98]',
          )}
        >
          <Badge variant="blue" size="sm" className="mb-4">
            {t('onboarding.recommended', { defaultValue: 'Recommended' })}
          </Badge>
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-oe-blue-subtle text-oe-blue-text mb-5 transition-all duration-300 group-hover:bg-oe-blue group-hover:text-white group-hover:shadow-lg group-hover:shadow-oe-blue/20">
            <Sparkles size={26} />
          </div>
          <h3 className="text-xl font-bold text-content-primary">
            {t('onboarding.quick_start', { defaultValue: 'Quick Start' })}
          </h3>
          <p className="mt-2.5 text-sm text-content-secondary leading-relaxed">
            {t('onboarding.quick_start_desc', {
              defaultValue: 'All essential modules pre-activated. Start working immediately.',
            })}
          </p>
        </button>

        {/* Ready-made pack card — a turnkey country starter pack that
            provisions modules, regional config and sample data in one click,
            then skips straight to the finish step. */}
        <button
          onClick={onReadyPack}
          className={clsx(
            'group relative flex flex-col items-start rounded-3xl p-8 text-left min-h-[340px]',
            'bg-surface-elevated/70 backdrop-blur-md shadow-sm shadow-black/[0.04]',
            'hover:bg-oe-blue-subtle/30 hover:shadow-2xl hover:shadow-oe-blue/10 hover:-translate-y-1',
            'transition-all duration-300 ease-oe active:scale-[0.98]',
          )}
        >
          <Badge variant="blue" size="sm" className="mb-4">
            {t('onboarding.turnkey', { defaultValue: 'Turnkey' })}
          </Badge>
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-oe-blue-subtle text-oe-blue-text mb-5 transition-all duration-300 group-hover:bg-oe-blue group-hover:text-white group-hover:shadow-lg group-hover:shadow-oe-blue/20">
            <Boxes size={26} />
          </div>
          <h3 className="text-xl font-bold text-content-primary">
            {t('onboarding.ready_pack', { defaultValue: 'Ready-made Pack' })}
          </h3>
          <p className="mt-2.5 text-sm text-content-secondary leading-relaxed">
            {t('onboarding.ready_pack_desc', {
              defaultValue:
                'Pick a country starter pack. It installs the language, cost databases, modules and sample projects for you.',
            })}
          </p>
        </button>

        {/* Choose profile card */}
        <button
          onClick={onChooseProfile}
          className={clsx(
            'group relative flex flex-col items-start rounded-3xl p-8 text-left min-h-[340px]',
            'bg-surface-elevated/70 backdrop-blur-md shadow-sm shadow-black/[0.04]',
            'hover:bg-oe-blue-subtle/30 hover:shadow-2xl hover:shadow-oe-blue/10 hover:-translate-y-1',
            'transition-all duration-300 ease-oe active:scale-[0.98]',
          )}
        >
          <div className="h-[22px] mb-4" aria-hidden />
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-secondary text-content-secondary mb-5 transition-all duration-300 group-hover:bg-oe-blue group-hover:text-white group-hover:shadow-lg group-hover:shadow-oe-blue/20">
            <Settings2 size={26} />
          </div>
          <h3 className="text-xl font-bold text-content-primary">
            {t('onboarding.choose_profile', { defaultValue: 'Choose Your Profile' })}
          </h3>
          <p className="mt-2.5 text-sm text-content-secondary leading-relaxed">
            {t('onboarding.choose_profile_desc', {
              defaultValue: 'Select your role and customize which modules you need.',
            })}
          </p>
        </button>
      </div>

      <div className="mt-5">
        <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
          {t('common.back', { defaultValue: 'Back' })}
        </Button>
      </div>
    </div>
  );
}

// ── Step 2b: Ready-made pack picker ─────────────────────────────────────────
//
// A turnkey starter pack: the user picks one country pack from a clean icon
// grid, we run the same one-click full-install the country picker uses
// (``fullInstallPack`` -> apply pack + locale + cost DB + vector DB + demos),
// then skip the remaining onboarding steps and jump straight to Finish. The
// completion path (``markOnboardingCompleted``, run by the caller via
// ``onInstalled``) is identical to the normal Finish, so the tour-gating event
// still fires. On failure we fall back to the normal multi-step flow with a
// clear message (``onFallback``).

function ReadyPackPicker({
  onActivateLocale,
  onInstalled,
  onFallback,
  onBack,
}: {
  /** Activate the pack's locale client-side (shared with the wizard). */
  onActivateLocale: (locale: string) => void;
  /** Called once the pack is fully installed; the wizard records the slug
   *  and advances to the Finish step. */
  onInstalled: (slug: string) => void;
  /** Called when install fails so the wizard can drop back to the normal
   *  multi-step flow with a clear message. */
  onFallback: () => void;
  /** Return to the start-choice cards. */
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['partner-pack', 'installed'],
    queryFn: fetchInstalledPacks,
    staleTime: 60_000,
  });

  const packs: InstalledPartnerPack[] = data?.installed ?? [];

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);
  const [installedSlug, setInstalledSlug] = useState<string | null>(null);
  // Live progress for the in-flight install, mirrored from the global
  // background-install store the driver writes to. The picker renders the
  // prominent progress UI from this while it waits for language to be ready;
  // the same store keeps driving the root banner after the user routes in.
  const bgInstall = useBackgroundInstallStore((s) => s.install);

  // Default-select the first pack once they load.
  useEffect(() => {
    if (!selectedSlug && packs.length > 0) {
      setSelectedSlug(packs[0]?.slug ?? null);
    }
  }, [packs, selectedSlug]);

  const selectedPack = packs.find((p) => p.slug === selectedSlug) ?? null;

  const handleSelect = useCallback(
    (slug: string) => {
      if (installing) return;
      setSelectedSlug(slug);
    },
    [installing],
  );

  const handleInstall = useCallback(
    async (pack: InstalledPartnerPack) => {
      if (installing) return;
      setInstalling(true);
      setInstalledSlug(null);

      // Kick off the background install. This applies the pack and the LANGUAGE
      // first and fast, then keeps loading the cost databases and sample
      // projects on its own while the user is already in the app. The promise
      // resolves the moment language is ready, so we route the user in
      // immediately instead of making them wait for everything. Live progress
      // for the heavy steps shows in the root-mounted background banner.
      try {
        const ready = await startBackgroundReadyPackInstall(pack.slug, packCountryName(pack), {
          demoCount: 2,
          onLanguageReady: (locale) => onActivateLocale(locale),
        });

        if (ready) {
          setInstalledSlug(pack.slug);
          // Fallback: if the stream finished before it could report a locale,
          // still surface the pack's declared default locale.
          onActivateLocale(pack.default_locale);
          addToast({
            type: 'success',
            title: t('onboarding.pp_language_ready', {
              defaultValue: '{{country}} is ready, finishing setup in the background',
              country: packCountryName(pack),
            }),
          });
          // Brief pause so the language/checklist tick is visible, then hand
          // control back to the wizard which records the slug and jumps to
          // Finish. The rest of the install keeps running in the background.
          window.setTimeout(() => onInstalled(pack.slug), 700);
        } else {
          // Apply failed before language could be applied -- fall back to the
          // normal multi-step flow. The background banner already shows the
          // failed step.
          addToast({
            type: 'error',
            title: t('onboarding.ready_pack_failed', {
              defaultValue: 'Could not finish the ready-made pack',
            }),
            message: t('onboarding.ready_pack_fallback', {
              defaultValue: 'Continuing with step-by-step setup instead.',
            }),
          });
          // Abandon the pack: clear the background banner so it does not linger
          // with a failed install while the user does step-by-step setup.
          useBackgroundInstallStore.getState().dismiss();
          setInstalling(false);
          onFallback();
        }
      } catch (err) {
        addToast({
          type: 'error',
          title: t('onboarding.ready_pack_failed', {
            defaultValue: 'Could not finish the ready-made pack',
          }),
          message: err instanceof Error ? err.message : t('onboarding.ready_pack_fallback', {
            defaultValue: 'Continuing with step-by-step setup instead.',
          }),
        });
        useBackgroundInstallStore.getState().dismiss();
        setInstalling(false);
        onFallback();
      }
    },
    [installing, onActivateLocale, onInstalled, onFallback, addToast, t],
  );

  return (
    <div className="flex flex-col items-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue-subtle text-oe-blue-text mb-4">
        <Boxes size={24} />
      </div>
      <h2 className="text-2xl font-bold text-content-primary">
        {t('onboarding.ready_pack_title', { defaultValue: 'Pick a ready-made pack' })}
      </h2>
      <p className="mt-2 text-sm text-content-secondary text-center max-w-md">
        {t('onboarding.ready_pack_subtitle', {
          defaultValue:
            'One click sets up the language, cost databases, modules and sample projects. You can change anything later.',
        })}
      </p>

      {isLoading && (
        <div className="mt-8 flex items-center justify-center gap-2 py-8 text-sm text-content-tertiary">
          <Loader2 size={16} className="animate-spin text-oe-blue" />
          {t('onboarding.pp_loading', { defaultValue: 'Loading available country packs…' })}
        </div>
      )}

      {!isLoading && (isError || packs.length === 0) && (
        <div className="mt-8 w-full max-w-md">
          <div className="flex items-start gap-2 rounded-xl bg-amber-50 dark:bg-amber-950/20 px-3 py-3 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span>
              {t('onboarding.ready_pack_none', {
                defaultValue:
                  'No ready-made packs are available right now. Continue with step-by-step setup instead.',
              })}
            </span>
          </div>
          <div className="mt-5 flex items-center justify-center gap-3">
            <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
              {t('common.back', { defaultValue: 'Back' })}
            </Button>
            <Button variant="primary" onClick={onFallback} icon={<ArrowRight size={16} />} iconPosition="right">
              {t('onboarding.ready_pack_continue_steps', { defaultValue: 'Continue setup' })}
            </Button>
          </div>
        </div>
      )}

      {/* Pack icon grid — tidy square tiles, one per pack. */}
      {!isLoading && packs.length > 0 && (
        <div className="mt-7 grid w-full max-w-3xl grid-cols-2 gap-3 sm:grid-cols-3">
          {packs.map((pack) => {
            const isSelected = selectedSlug === pack.slug;
            const country = packCountryName(pack);
            const flag = packCountryCode(pack);
            return (
              <button
                key={pack.slug}
                type="button"
                onClick={() => handleSelect(pack.slug)}
                disabled={installing}
                aria-pressed={isSelected}
                className={clsx(
                  'group relative flex flex-col items-center gap-2.5 rounded-xl p-4 text-center transition-all duration-200',
                  isSelected
                    ? 'bg-oe-blue-subtle/50 ring-2 ring-oe-blue/45 shadow-sm'
                    : 'bg-surface-secondary/70 ring-1 ring-transparent hover:bg-surface-secondary hover:shadow-sm hover:-translate-y-0.5',
                  installing && 'opacity-60 cursor-not-allowed',
                )}
              >
                {isSelected && (
                  <span className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-oe-blue text-white shadow-sm">
                    <Check size={12} strokeWidth={3} />
                  </span>
                )}
                <PackLogo pack={pack} />
                <div className="flex items-center gap-1.5">
                  {flag && <CountryFlag code={flag} size={14} className="shrink-0" />}
                  <span className="truncate text-sm font-semibold text-content-primary">
                    {country}
                  </span>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-0.5 text-2xs text-content-quaternary">
                  <span className="inline-flex items-center gap-1">
                    <Languages size={11} />
                    {pack.default_locale.toUpperCase()}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Database size={11} />
                    {pack.default_currency}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Install confirm / progress for the chosen pack. The progress block is
          deliberately large and legible (tall progress bar, prominent percent,
          big step rows) so setup status is unmistakable. It reads live from the
          background-install store, so it keeps showing real per-step progress
          even though the heavy steps finish in the background. */}
      {!isLoading && selectedPack && (
        <div className="mt-6 w-full max-w-lg">
          {installing && (
            <ReadyPackProgressPanel
              install={bgInstall}
              country={packCountryName(selectedPack)}
              languageReady={installedSlug !== null}
            />
          )}

          <Button
            variant="primary"
            onClick={() => handleInstall(selectedPack)}
            loading={installing}
            disabled={installing}
            icon={installedSlug ? <CheckCircle2 size={16} /> : <Rocket size={16} />}
            className="w-full"
          >
            {installedSlug
              ? t('onboarding.pp_continue_to_app', {
                  defaultValue: 'Continue to {{country}}',
                  country: packCountryName(selectedPack),
                })
              : installing
                ? t('onboarding.pp_preparing', {
                    defaultValue: 'Preparing {{country}}…',
                    country: packCountryName(selectedPack),
                  })
                : t('onboarding.ready_pack_install', {
                    defaultValue: 'Set up {{country}}',
                    country: packCountryName(selectedPack),
                  })}
          </Button>

          {!installing && (
            <p className="mt-2 text-center text-2xs text-content-tertiary">
              {t('onboarding.ready_pack_install_hint_bg', {
                defaultValue:
                  'The language is applied first so you can start right away. Cost databases and sample projects keep loading in the background.',
              })}
            </p>
          )}
        </div>
      )}

      {!installing && (
        <div className="mt-5">
          <Button variant="ghost" onClick={onBack} icon={<ArrowLeft size={16} />}>
            {t('common.back', { defaultValue: 'Back' })}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Lucide icon for any stream step id (superset of the five §5 steps). */
function streamStepIcon(step: string): LucideIcon {
  switch (step) {
    case 'apply_pack':
      return Package;
    case 'locale':
      return Languages;
    case 'cost_db':
      return Database;
    case 'resources':
      return Layers;
    case 'vector_db':
      return Boxes;
    case 'demos':
      return FolderOpen;
    default:
      return Package;
  }
}

/**
 * Prominent, large progress panel shown while a ready-made pack is being set up
 * on the onboarding step. Renders a tall determinate progress bar, a big
 * percent + status line, and a legible per-step checklist that flips each row
 * to its final state as the server works through it.
 *
 * It reads from the live ``useBackgroundInstallStore`` snapshot (``install``),
 * so it keeps reflecting real progress for the steps that finish in the
 * background after the user has continued into the app.
 */
function ReadyPackProgressPanel({
  install,
  country,
  languageReady,
}: {
  install: BackgroundInstall | null;
  country: string;
  languageReady: boolean;
}) {
  const { t } = useTranslation();

  const steps = install?.steps ?? [];
  const total = steps.length;
  const finished = steps.filter(
    (s) => s.status === 'ok' || s.status === 'skipped' || s.status === 'error',
  ).length;
  const pct = total > 0 ? Math.round((finished / total) * 100) : languageReady ? 100 : 5;
  const runningStep = steps.find((s) => s.status === 'running');

  return (
    <div className="mb-5 rounded-2xl border border-border-light/70 bg-surface-secondary/40 p-5 dark:border-white/10">
      {/* Big status headline + prominent percent. */}
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          {languageReady ? (
            <CheckCircle2 size={20} className="shrink-0 text-semantic-success" />
          ) : (
            <Loader2 size={20} className="shrink-0 animate-spin text-oe-blue" />
          )}
          <span className="truncate text-base font-semibold text-content-primary">
            {languageReady
              ? t('onboarding.pp_language_ready_short', {
                  defaultValue: '{{country}} is ready',
                  country,
                })
              : t('onboarding.pp_checklist_running', {
                  defaultValue: 'Setting up {{country}}…',
                  country,
                })}
          </span>
        </div>
        <span className="shrink-0 text-2xl font-bold tabular-nums text-content-primary">
          {pct}%
        </span>
      </div>

      {/* Tall determinate progress bar. */}
      <div className="h-3 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className="h-full rounded-full bg-oe-blue transition-all duration-500 ease-out"
          style={{ width: `${Math.max(pct, 5)}%` }}
        />
      </div>

      {/* Current-step caption. */}
      <p className="mt-2 min-h-[1.25rem] text-sm text-content-secondary">
        {languageReady
          ? t('onboarding.pp_continue_hint', {
              defaultValue: 'You can continue now. The rest keeps loading in the background.',
            })
          : runningStep
            ? runningStep.label
            : t('onboarding.pp_starting', { defaultValue: 'Starting setup…' })}
      </p>

      {/* Large, legible per-step checklist. */}
      {steps.length > 0 && (
        <ul className="mt-4 space-y-2.5">
          {steps.map((s) => {
            const StepIcon = streamStepIcon(s.step);
            return (
              <li key={s.step} className="flex items-center gap-3 text-sm">
                <ChecklistGlyph state={s.status} />
                <StepIcon size={16} className="shrink-0 text-content-quaternary" />
                <span
                  className={clsx(
                    'flex-1',
                    s.status === 'ok'
                      ? 'font-medium text-content-primary'
                      : s.status === 'error'
                        ? 'text-semantic-error'
                        : s.status === 'running'
                          ? 'font-medium text-content-primary'
                          : 'text-content-secondary',
                  )}
                >
                  {s.label}
                </span>
                {s.detail && (
                  <span className="shrink-0 text-xs text-content-tertiary tabular-nums">
                    {s.detail}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Step 3: Company Profile (industry cards) ────────────────────────────────

function StepCompanyProfile({
  onNext,
  onBack,
  presets,
  selectedType,
  onSelectType,
  onConfigureIndividually,
}: {
  onNext: () => void;
  onBack: () => void;
  presets: ApiCompanyPreset[];
  selectedType: string | null;
  onSelectType: (key: string) => void;
  onConfigureIndividually: () => void;
}) {
  const { t } = useTranslation();
  const text = usePresetText();

  const handleSelect = useCallback(
    (key: string) => {
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
        {presets.filter((p) => p.key !== 'full_enterprise').map((preset) => {
          const isSelected = selectedType === preset.key;
          const Icon = presetIcon(preset.icon);
          const moduleCount = preset.module_count;
          const visibleTags = preset.tags.slice(0, 3);
          const extraCount = moduleCount - visibleTags.length;

          return (
            <button
              key={preset.key}
              onClick={() => handleSelect(preset.key)}
              className={clsx(
                'group relative flex flex-col items-start rounded-2xl p-5 text-left',
                'transition-all duration-300 ease-oe',
                isSelected
                  ? 'bg-oe-blue-subtle/40 ring-2 ring-oe-blue/45 shadow-lg shadow-oe-blue/10'
                  : 'bg-surface-elevated shadow-sm shadow-black/[0.04] hover:bg-oe-blue-subtle/15 hover:shadow-md hover:-translate-y-0.5 active:scale-[0.99]',
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
                {preset.key === 'general_contractor' && (
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
                {text.label(preset)}
              </h3>
              <p className="mt-1 text-sm text-content-secondary leading-snug">
                {text.description(preset)}
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
        const enterprise = presets.find((p) => p.key === 'full_enterprise');
        if (!enterprise) return null;
        const isSelected = selectedType === 'full_enterprise';
        const Icon = presetIcon(enterprise.icon);

        return (
          <button
            onClick={() => handleSelect('full_enterprise')}
            className={clsx(
              'mt-3 w-full max-w-2xl group relative flex items-center gap-4 rounded-2xl p-5 text-left',
              'transition-all duration-300 ease-oe',
              isSelected
                ? 'bg-oe-blue-subtle/40 ring-2 ring-oe-blue/45 shadow-lg shadow-oe-blue/10'
                : 'bg-surface-elevated shadow-sm shadow-black/[0.04] hover:bg-oe-blue-subtle/15 hover:shadow-md hover:-translate-y-0.5 active:scale-[0.99]',
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
                  {text.label(enterprise)}
                </h3>
                {isSelected && <CheckCircle2 size={16} className="text-oe-blue" />}
              </div>
              <p className="mt-0.5 text-sm text-content-secondary">
                {text.description(enterprise)}
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
                count: TOTAL_MODULE_COUNT,
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

      {/* AI Tools toggle */}
      <div className="mt-4 w-full max-w-2xl">
        <div className="flex items-center justify-between rounded-xl bg-surface-elevated shadow-sm shadow-black/[0.04] px-4 py-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-50 dark:bg-violet-950/30 shrink-0">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-violet-600"><path d="M12 2a4 4 0 0 1 4 4v1a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V6a4 4 0 0 1 4-4Z"/><path d="M16 11v1a4 4 0 1 1-8 0v-1"/><path d="M12 19v3"/><path d="M8 22h8"/></svg>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-content-primary">
                {t('onboarding.ai_tools', { defaultValue: 'AI-Powered Tools' })}
              </p>
              <p className="text-xs text-content-tertiary truncate">
                {t('onboarding.ai_tools_desc', {
                  defaultValue: 'AI estimation, cost advisor, project intelligence. Requires API key (Anthropic, OpenAI, or Gemini).',
                })}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              const aiKeys = ALL_MODULES.filter((m) => m.group === 'ai').map((m) => m.key);
              const anyEnabled = aiKeys.some((k) => enabledModules.has(k));
              for (const k of aiKeys) {
                if (anyEnabled && enabledModules.has(k)) onToggleModule(k);
                if (!anyEnabled && !enabledModules.has(k)) onToggleModule(k);
              }
            }}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
              ALL_MODULES.filter((m) => m.group === 'ai').some((m) => enabledModules.has(m.key))
                ? 'bg-oe-blue'
                : 'bg-gray-300 dark:bg-gray-600'
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition duration-200 ease-in-out ${
                ALL_MODULES.filter((m) => m.group === 'ai').some((m) => enabledModules.has(m.key))
                  ? 'translate-x-5'
                  : 'translate-x-0'
              }`}
            />
          </button>
        </div>
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
              <div className="rounded-xl bg-surface-elevated shadow-sm shadow-black/[0.04] overflow-hidden divide-y divide-border-light/40">
                {groupModules.map((mod) => {
                  const isCore = !!mod.core;
                  const isEnabled = isCore || enabledModules.has(mod.key);
                  return (
                    <div
                      key={mod.key}
                      className="flex items-center justify-between py-2.5 px-4 gap-3 overflow-hidden"
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

// ── Country Pack picker (Step 5 lead experience) ────────────────────────────

/** Per-component install status used by the Country Pack card. */
type PackComponentState = 'idle' | 'running' | 'done' | 'error' | 'skipped';

/** Small status glyph for a Country Pack component (locale / DB / demo). */
function PackStatusGlyph({ state }: { state: PackComponentState }) {
  if (state === 'running') {
    return <Loader2 size={15} className="animate-spin text-oe-blue shrink-0" aria-hidden />;
  }
  if (state === 'done') {
    return <CheckCircle2 size={15} className="text-semantic-success shrink-0" aria-hidden />;
  }
  if (state === 'skipped') {
    return <span className="text-2xs text-content-quaternary shrink-0">—</span>;
  }
  if (state === 'error') {
    return <span className="text-2xs font-semibold text-semantic-error shrink-0">!</span>;
  }
  return (
    <span className="h-2 w-2 rounded-full bg-border-light dark:bg-white/15 shrink-0" aria-hidden />
  );
}

// ── Partner-pack one-click installer (primary "Set up by country") ──────────

/** Lucide icon to render for each ``full-install`` step in the checklist. */
const FULL_INSTALL_STEP_ICONS: Record<FullInstallStepName, LucideIcon> = {
  apply_pack: Package,
  locale: Languages,
  cost_db: Database,
  vector_db: Boxes,
  demos: FolderOpen,
};

/** Per-step UI state while/after the orchestrated install runs. */
type ChecklistState = 'pending' | 'running' | FullInstallStepStatus;

/**
 * A small square logo tile for a partner pack in the picker grid.
 *
 * The packs ship *wide wordmark* logos (≈5:1, e.g. 240×50) sized for the
 * co-brand strip; jammed into this ~40px square they render as an
 * illegible sliver (the "logos not visible / badly thought out" report).
 * For a compact square slot the right, always-legible treatment is a
 * monogram badge: a rounded square (radius lg = 10px) filled with the
 * pack's own brand colour and the pack's initials in medium-weight white.
 *
 * This deliberately replaces the previous ``<img src=/logo/{slug}>`` — the
 * wordmark endpoint returns 200, but a 5:1 mark in a 40px square is an
 * unreadable sliver, and on the slow first paint it briefly showed raw alt
 * text ("…Construction Pack logo"). The monogram is brand-correct, legible,
 * and can never 404 or flash a broken image. The wide wordmark is still used
 * where it has room (the co-brand strip + the /modules Partner Packs grid).
 */
function PackLogo({ pack }: { pack: InstalledPartnerPack }) {
  const [imgError, setImgError] = useState(false);
  // Each pack now ships a real designed emblem (square app-icon: brand-colour
  // gradient + skyline/building motif), which reads well at this 40px tile.
  // Fall back to a brand-coloured monogram only if the image can't load.
  if (pack.branding?.has_logo && !imgError) {
    return (
      <img
        src={partnerPackLogoUrl(pack.slug)}
        alt={`${pack.partner_name} logo`}
        className="h-10 w-10 shrink-0 rounded-lg object-contain shadow-sm ring-1 ring-black/5 dark:ring-white/10"
        onError={() => setImgError(true)}
      />
    );
  }
  // Brand gradient from the pack's own colours; falls back to the app blue
  // when a pack omits them. Two-stop gradient gives the flat badge depth.
  const initials = packInitials(pack);
  const from = pack.branding?.primary_color || '#2563eb';
  const to = pack.branding?.accent_color || from;
  return (
    <span
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white shadow-sm ring-1 ring-black/5 dark:ring-white/10 select-none"
      style={{ backgroundImage: `linear-gradient(135deg, ${from}, ${to})` }}
      aria-hidden
    >
      <span className="text-sm font-semibold tracking-tight leading-none">{initials}</span>
    </span>
  );
}

/**
 * Frosted-glass card showing the selected pack's description, clamped to a
 * few lines with a keyboard-accessible Show more / Show less toggle.
 *
 * Matches the app's glass treatment (semi-transparent elevated surface +
 * ``backdrop-blur`` + hairline border, radius lg). Collapses to 3 lines via
 * ``line-clamp-3``; the toggle only renders when the text is actually long
 * enough to be clipped, so short descriptions never grow a dead button.
 */
function PackDescriptionCard({ description }: { description: string }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const text = description?.trim();
  if (!text) return null;

  // Heuristic: only offer expand/collapse when the copy is long enough to be
  // clipped by line-clamp-3 (≈ 150+ chars at this width). Avoids a useless
  // "Show more" on a one-liner.
  const isLong = text.length > 150;

  return (
    <div className="mb-4 rounded-lg border border-border-light/70 dark:border-white/10 bg-surface-elevated/70 dark:bg-white/[0.04] backdrop-blur-md p-3 shadow-sm shadow-black/[0.03]">
      <p
        className={clsx(
          'text-xs leading-relaxed text-content-secondary',
          !expanded && isLong && 'line-clamp-3',
        )}
      >
        {text}
      </p>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-1.5 inline-flex items-center gap-1 text-2xs font-semibold text-oe-blue hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 rounded"
        >
          {expanded
            ? t('onboarding.pp_show_less', { defaultValue: 'Show less' })
            : t('onboarding.pp_show_more', { defaultValue: 'Show more' })}
          <ChevronDown
            size={12}
            className={clsx('transition-transform duration-200', expanded && 'rotate-180')}
            aria-hidden
          />
        </button>
      )}
    </div>
  );
}

/** Status glyph for one row of the orchestrated-install checklist. */
function ChecklistGlyph({ state }: { state: ChecklistState }) {
  if (state === 'running') {
    return <Loader2 size={16} className="animate-spin text-oe-blue shrink-0" aria-hidden />;
  }
  if (state === 'ok') {
    return <CheckCircle2 size={16} className="text-semantic-success shrink-0" aria-hidden />;
  }
  if (state === 'skipped') {
    return <MinusCircle size={16} className="text-content-quaternary shrink-0" aria-hidden />;
  }
  if (state === 'error') {
    return <XCircle size={16} className="text-semantic-error shrink-0" aria-hidden />;
  }
  // pending
  return (
    <span className="h-2.5 w-2.5 rounded-full bg-border-light dark:bg-white/15 shrink-0" aria-hidden />
  );
}

function PartnerPackInstaller({
  onActivateLocale,
}: {
  /** Activate the pack's locale client-side (shared with the wizard). */
  onActivateLocale: (locale: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  const {
    data,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['partner-pack', 'installed'],
    queryFn: fetchInstalledPacks,
    staleTime: 60_000,
  });

  const packs: InstalledPartnerPack[] = data?.installed ?? [];

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);
  // Per-step checklist state, keyed by the five §5 step names.
  const [stepStates, setStepStates] = useState<Record<FullInstallStepName, ChecklistState>>(
    () => ({ apply_pack: 'pending', locale: 'pending', cost_db: 'pending', vector_db: 'pending', demos: 'pending' }),
  );
  const [installedSlug, setInstalledSlug] = useState<string | null>(null);
  const [installFailed, setInstallFailed] = useState(false);

  // Default-select the first pack once they load.
  useEffect(() => {
    if (!selectedSlug && packs.length > 0) {
      setSelectedSlug(packs[0]?.slug ?? null);
    }
  }, [packs, selectedSlug]);

  const selectedPack = packs.find((p) => p.slug === selectedSlug) ?? null;

  const resetChecklist = useCallback(() => {
    setStepStates({
      apply_pack: 'pending',
      locale: 'pending',
      cost_db: 'pending',
      vector_db: 'pending',
      demos: 'pending',
    });
    setInstalledSlug(null);
    setInstallFailed(false);
  }, []);

  const handleSelect = useCallback(
    (slug: string) => {
      if (installing) return;
      setSelectedSlug(slug);
      resetChecklist();
    },
    [installing, resetChecklist],
  );

  const handleInstall = useCallback(
    async (pack: InstalledPartnerPack) => {
      if (installing) return;
      setInstalling(true);
      setInstallFailed(false);
      setInstalledSlug(null);
      // Reset the checklist to pending; the SSE stream below flips each row to
      // running and then to its final status as the server runs the steps, so
      // the user watches real per-step progress instead of one frozen spinner.
      setStepStates({
        apply_pack: 'pending',
        locale: 'pending',
        cost_db: 'pending',
        vector_db: 'skipped',
        demos: 'pending',
      });

      let ok = false;
      try {
        await fullInstallPackStream(
          pack.slug,
          (evt) => {
            if (evt.type === 'step_start') {
              const k = evt.step as FullInstallStepName;
              setStepStates((prev) => (k in prev ? { ...prev, [k]: 'running' } : prev));
            } else if (evt.type === 'step_done') {
              const k = evt.step as FullInstallStepName;
              setStepStates((prev) => (k in prev ? { ...prev, [k]: evt.status } : prev));
            } else if (evt.type === 'done') {
              ok = evt.ok;
            }
          },
          { demoCount: 2 },
        );

        if (ok) {
          setInstalledSlug(pack.slug);
          // Activate the pack's locale client-side, then send the user to
          // their freshly installed country projects.
          onActivateLocale(pack.default_locale);
          addToast({
            type: 'success',
            title: t('onboarding.pp_install_success', {
              defaultValue: '{{country}} workspace installed',
              country: packCountryName(pack),
            }),
          });
          // Brief pause so the green checklist is visible before routing.
          window.setTimeout(() => {
            markOnboardingCompleted();
            navigate('/projects');
          }, 900);
        } else {
          setInstallFailed(true);
          addToast({
            type: 'error',
            title: t('onboarding.pp_install_partial', {
              defaultValue: 'Some setup steps did not complete',
            }),
            message: t('onboarding.pp_install_partial_desc', {
              defaultValue: 'Review the checklist below. Completed steps are kept.',
            }),
          });
        }
      } catch (err) {
        // A thrown error (timeout / network) marks every still-running step
        // as failed so nothing spins forever.
        setStepStates((prev) => {
          const next = { ...prev };
          for (const k of FULL_INSTALL_STEPS) {
            if (next[k] === 'running') next[k] = 'error';
          }
          return next;
        });
        setInstallFailed(true);
        addToast({
          type: 'error',
          title: t('onboarding.pp_install_error', {
            defaultValue: 'Failed to install the country workspace',
          }),
          message: err instanceof Error ? err.message : undefined,
        });
      } finally {
        setInstalling(false);
      }
    },
    [installing, onActivateLocale, addToast, t, navigate],
  );

  const stepLabel = useCallback(
    (step: FullInstallStepName): string => {
      switch (step) {
        case 'apply_pack':
          return t('onboarding.pp_step_apply', { defaultValue: 'Apply pack' });
        case 'locale':
          return t('onboarding.pp_step_locale', { defaultValue: 'Language' });
        case 'cost_db':
          return t('onboarding.pp_step_cost_db', { defaultValue: 'Cost database' });
        case 'vector_db':
          return t('onboarding.pp_step_vector_db', { defaultValue: 'Vector database' });
        case 'demos':
          return t('onboarding.pp_step_demos', { defaultValue: 'Example projects' });
      }
    },
    [t],
  );

  const showChecklist = installing || installedSlug !== null || installFailed;

  return (
    <div className="rounded-2xl bg-surface-elevated shadow-sm shadow-black/[0.04] p-6">
      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
          <Globe size={20} />
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-bold text-content-primary">
            {t('onboarding.country_pack_title', { defaultValue: 'Set up by country' })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('onboarding.pp_subtitle', {
              defaultValue: 'Install a complete localized workspace - language, both cost databases, and example projects - in one click',
            })}
          </p>
        </div>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-content-tertiary">
          <Loader2 size={16} className="animate-spin text-oe-blue" />
          {t('onboarding.pp_loading', { defaultValue: 'Loading available country packs…' })}
        </div>
      )}

      {!isLoading && isError && (
        <div className="flex items-center gap-2 rounded-xl bg-amber-50 dark:bg-amber-950/20 px-3 py-3 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle size={15} className="shrink-0" />
          {t('onboarding.pp_load_error', {
            defaultValue: 'Could not load country packs. You can still pick a country below.',
          })}
        </div>
      )}

      {!isLoading && !isError && packs.length === 0 && (
        <div className="rounded-xl bg-surface-secondary/50 px-3 py-4 text-center text-xs text-content-tertiary">
          {t('onboarding.pp_none_installed', {
            defaultValue: 'No partner packs are installed yet. Pick a country below to set up language and classification.',
          })}
        </div>
      )}

      {/* Pack grid */}
      {!isLoading && packs.length > 0 && (
        <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {packs.map((pack) => {
            const isSelected = selectedSlug === pack.slug;
            const country = packCountryName(pack);
            const flag = packCountryCode(pack);
            return (
              <button
                key={pack.slug}
                type="button"
                onClick={() => handleSelect(pack.slug)}
                disabled={installing}
                aria-pressed={isSelected}
                className={clsx(
                  'flex items-start gap-3 rounded-xl p-3 text-left transition-all duration-200',
                  isSelected
                    ? 'bg-oe-blue-subtle/50 ring-2 ring-oe-blue/40 shadow-sm'
                    : 'bg-surface-secondary/70 hover:bg-surface-secondary hover:shadow-sm',
                  installing && 'opacity-60 cursor-not-allowed',
                )}
              >
                <PackLogo pack={pack} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    {flag && <CountryFlag code={flag} size={16} className="shrink-0" />}
                    <span className="truncate text-sm font-semibold text-content-primary">
                      {country}
                    </span>
                    {isSelected && <Check size={14} className="ms-auto shrink-0 text-oe-blue" />}
                  </div>
                  <div className="truncate text-2xs text-content-tertiary">
                    {pack.partner_name}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-2xs text-content-quaternary">
                    <span className="inline-flex items-center gap-1">
                      <Languages size={11} />
                      {pack.default_locale.toUpperCase()}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Database size={11} />
                      {pack.default_currency}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Selected pack description — frosted-glass, expandable */}
      {!isLoading && selectedPack && (
        <PackDescriptionCard description={selectedPack.description} />
      )}

      {/* Progress checklist — the five orchestrated steps */}
      {showChecklist && selectedPack && (
        <div className="mb-4 rounded-xl bg-surface-secondary/50 p-3">
          <div className="mb-2 text-xs font-semibold text-content-secondary">
            {installedSlug
              ? t('onboarding.pp_checklist_done', { defaultValue: 'Workspace ready' })
              : installFailed
                ? t('onboarding.pp_checklist_partial', { defaultValue: 'Setup finished with issues' })
                : t('onboarding.pp_checklist_running', {
                    defaultValue: 'Setting up {{country}}…',
                    country: packCountryName(selectedPack),
                  })}
          </div>
          <ul className="space-y-1.5">
            {FULL_INSTALL_STEPS.map((step) => {
              const StepIcon = FULL_INSTALL_STEP_ICONS[step];
              const state = stepStates[step];
              return (
                <li key={step} className="flex items-center gap-2.5 text-xs">
                  <ChecklistGlyph state={state} />
                  <StepIcon size={13} className="shrink-0 text-content-quaternary" />
                  <span
                    className={clsx(
                      'flex-1',
                      state === 'ok'
                        ? 'text-content-primary'
                        : state === 'error'
                          ? 'text-semantic-error'
                          : 'text-content-secondary',
                    )}
                  >
                    {stepLabel(step)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Primary one-click install */}
      {!isLoading && packs.length > 0 && selectedPack && (
        <Button
          variant="primary"
          onClick={() => handleInstall(selectedPack)}
          loading={installing}
          disabled={installing || installedSlug === selectedPack.slug}
          icon={installedSlug === selectedPack.slug ? <CheckCircle2 size={16} /> : <Rocket size={16} />}
          className="w-full"
        >
          {installedSlug === selectedPack.slug
            ? t('onboarding.pp_installed', {
                defaultValue: '{{country}} workspace installed',
                country: packCountryName(selectedPack),
              })
            : installing
              ? t('onboarding.pp_installing', {
                  defaultValue: 'Installing {{country}} workspace…',
                  country: packCountryName(selectedPack),
                })
              : t('onboarding.pp_install', {
                  defaultValue: 'Install {{country}} workspace',
                  country: packCountryName(selectedPack),
                })}
        </Button>
      )}

      {installedSlug && (
        <p className="mt-2 text-center text-2xs text-content-tertiary">
          {t('onboarding.pp_redirecting', {
            defaultValue: 'Opening your example projects…',
          })}
        </p>
      )}
    </div>
  );
}

/** A single à-la-carte component row inside the customize panel. */
function PackComponentRow({
  icon,
  label,
  detail,
  state,
  actionLabel,
  doneLabel,
  skippedLabel,
  onAction,
  disabled,
}: {
  icon: ReactNode;
  label: string;
  detail: string;
  state: PackComponentState;
  actionLabel: string;
  doneLabel: string;
  skippedLabel: string;
  onAction: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-surface-secondary/60 px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-elevated text-content-secondary">
          {icon}
        </span>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-content-primary">{label}</div>
          <div className="truncate text-2xs text-content-tertiary">{detail}</div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {state === 'done' ? (
          <span className="flex items-center gap-1 text-2xs font-medium text-semantic-success">
            <CheckCircle2 size={13} />
            {doneLabel}
          </span>
        ) : state === 'skipped' ? (
          <span className="text-2xs text-content-quaternary">{skippedLabel}</span>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            onClick={onAction}
            disabled={disabled || state === 'running'}
            icon={state === 'running' ? <Loader2 size={12} className="animate-spin" /> : undefined}
          >
            {actionLabel}
          </Button>
        )}
      </div>
    </div>
  );
}

// Secondary "Other countries" picker — for markets without a dedicated
// partner pack. Generic presets cover language + classification (+ an optional
// relational cost DB); they intentionally install NO demo projects (the
// partner-pack installer above owns the fully-worked country demos). See
// docs/country-pack-oneclick/DESIGN.md §7.
function CountryPackCard({
  packs,
  selectedPack,
  onSelectPack,
  onInstallPack,
  onPackLocale,
  onPackDb,
  installing,
  localeState,
  dbState,
  customizeOpen,
  onToggleCustomize,
  recordedClassification,
}: {
  packs: CountryPack[];
  selectedPack: CountryPack;
  onSelectPack: (pack: CountryPack) => void;
  onInstallPack: (pack: CountryPack) => void;
  onPackLocale: (pack: CountryPack) => void;
  onPackDb: (pack: CountryPack) => void;
  installing: boolean;
  localeState: PackComponentState;
  dbState: PackComponentState;
  customizeOpen: boolean;
  onToggleCustomize: () => void;
  recordedClassification: string | null;
}) {
  const { t } = useTranslation();
  const [packQuery, setPackQuery] = useState('');

  const filteredPacks = (() => {
    const q = packQuery.trim().toLowerCase();
    if (!q) return packs;
    return packs.filter(
      (p) =>
        t(p.labelKey, { defaultValue: p.labelDefault }).toLowerCase().includes(q) ||
        p.labelDefault.toLowerCase().includes(q) ||
        p.region.toLowerCase().includes(q) ||
        p.classification.toLowerCase().includes(q) ||
        p.id.toLowerCase().includes(q),
    );
  })();

  const packLabel = t(selectedPack.labelKey, { defaultValue: selectedPack.labelDefault });
  const allDone = localeState === 'done' && dbState === 'done';

  return (
    <div className="rounded-2xl bg-surface-elevated shadow-sm shadow-black/[0.04] p-6">
      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary text-content-secondary">
          <Globe size={20} />
        </div>
        <div className="min-w-0">
          <h3 className="text-base font-bold text-content-primary">
            {t('onboarding.other_countries_title', { defaultValue: 'Other countries' })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('onboarding.other_countries_subtitle', {
              defaultValue: 'No partner pack yet? Set the language and classification for your market',
            })}
          </p>
        </div>
      </div>

      {/* Country filter */}
      <div className="mb-2">
        <input
          type="search"
          value={packQuery}
          onChange={(e) => setPackQuery(e.target.value)}
          placeholder={t('onboarding.country_pack_filter_placeholder', {
            defaultValue: 'Find your country…',
          })}
          disabled={installing}
          className="w-full rounded-lg bg-surface-secondary/70 px-3 py-1.5 text-xs text-content-primary placeholder:text-content-quaternary border border-transparent focus:border-oe-blue/40 focus:outline-none focus:bg-surface-secondary disabled:opacity-50"
        />
      </div>

      {/* Country grid */}
      <div className="mb-4 grid max-h-56 grid-cols-2 gap-2 overflow-y-auto pr-1 -mr-1 sm:grid-cols-3">
        {filteredPacks.length === 0 && (
          <div className="col-span-full py-6 text-center text-xs text-content-tertiary">
            {t('onboarding.country_pack_no_results', {
              defaultValue: 'No countries match "{{q}}"',
              q: packQuery,
            })}
          </div>
        )}
        {filteredPacks.map((pack) => {
          const isSelected = selectedPack.id === pack.id;
          return (
            <button
              key={pack.id}
              type="button"
              onClick={() => !installing && onSelectPack(pack)}
              disabled={installing}
              aria-pressed={isSelected}
              className={clsx(
                'flex items-center gap-2 rounded-xl px-3 py-2 text-left transition-all duration-200',
                isSelected
                  ? 'bg-oe-blue-subtle/50 ring-2 ring-oe-blue/40 shadow-sm'
                  : 'bg-surface-secondary/70 hover:bg-surface-secondary hover:shadow-sm',
                installing && 'opacity-60 cursor-not-allowed',
              )}
            >
              <CountryFlag code={pack.flagId} size={18} className="shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium text-content-primary">
                  {t(pack.labelKey, { defaultValue: pack.labelDefault })}
                </div>
                <div className="text-2xs text-content-quaternary">{pack.classification}</div>
              </div>
              {isSelected && <Check size={14} className="shrink-0 text-oe-blue" />}
            </button>
          );
        })}
      </div>

      {/* What the selected pack includes — at-a-glance chips with live status */}
      <div className="mb-4 rounded-xl bg-surface-secondary/50 p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-content-secondary">
          <CountryFlag code={selectedPack.flagId} size={16} className="shrink-0" />
          {t('onboarding.country_pack_includes', {
            defaultValue: '{{country}} pack includes',
            country: packLabel,
          })}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-2xs text-content-tertiary">
          <span className="inline-flex items-center gap-1.5">
            <PackStatusGlyph state={localeState} />
            <Languages size={12} className="text-content-quaternary" />
            {t('onboarding.country_pack_locale', { defaultValue: 'Language' })}: {selectedPack.locale.toUpperCase()}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <PackStatusGlyph state={dbState} />
            <Database size={12} className="text-content-quaternary" />
            {t('onboarding.country_pack_db', { defaultValue: 'Cost database' })}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Layers size={12} className="text-content-quaternary" />
            {selectedPack.classification}
          </span>
        </div>
      </div>

      {/* Primary one-click install */}
      <Button
        variant="primary"
        onClick={() => onInstallPack(selectedPack)}
        loading={installing}
        disabled={installing || allDone}
        icon={allDone ? <CheckCircle2 size={16} /> : <Rocket size={16} />}
        className="w-full"
      >
        {allDone
          ? t('onboarding.country_pack_installed', {
              defaultValue: '{{country}} pack installed',
              country: packLabel,
            })
          : installing
            ? t('onboarding.country_pack_installing', {
                defaultValue: 'Installing {{country}} pack…',
                country: packLabel,
              })
            : t('onboarding.country_pack_install', {
                defaultValue: 'Install {{country}} pack',
                country: packLabel,
              })}
      </Button>

      {recordedClassification && (
        <p className="mt-2 text-center text-2xs text-content-tertiary">
          {t('onboarding.country_pack_classification_set', {
            defaultValue: 'Classification set to {{standard}}',
            standard: recordedClassification,
          })}
        </p>
      )}

      {/* Customize / install separately */}
      <button
        type="button"
        onClick={onToggleCustomize}
        aria-expanded={customizeOpen}
        className="mt-3 flex w-full items-center justify-center gap-1.5 text-xs font-medium text-oe-blue hover:underline"
      >
        {customizeOpen
          ? t('onboarding.country_pack_hide_customize', { defaultValue: 'Hide options' })
          : t('onboarding.country_pack_customize', { defaultValue: 'Customize / install separately' })}
        <ChevronDown
          size={13}
          className={clsx('transition-transform duration-200', customizeOpen && 'rotate-180')}
        />
      </button>

      {customizeOpen && (
        <div className="mt-3 space-y-2">
          <PackComponentRow
            icon={<Languages size={15} />}
            label={t('onboarding.country_pack_locale', { defaultValue: 'Language' })}
            detail={selectedPack.locale.toUpperCase()}
            state={localeState}
            actionLabel={t('onboarding.country_pack_apply', { defaultValue: 'Apply' })}
            doneLabel={t('onboarding.country_pack_applied', { defaultValue: 'Applied' })}
            skippedLabel="—"
            onAction={() => onPackLocale(selectedPack)}
            disabled={installing}
          />
          <PackComponentRow
            icon={<Database size={15} />}
            label={t('onboarding.country_pack_db', { defaultValue: 'Cost database' })}
            detail={selectedPack.region}
            state={dbState}
            actionLabel={t('onboarding.load_database', { defaultValue: 'Load Database' })}
            doneLabel={t('onboarding.demo_installed', { defaultValue: 'Installed' })}
            skippedLabel="—"
            onAction={() => onPackDb(selectedPack)}
            disabled={installing}
          />
        </div>
      )}
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

  // ── Country Pack state ──
  // Default-select the pack whose region matches the language-suggested
  // region (e.g. picking French in step 1 pre-selects the France pack); fall
  // back to the first showcase pack (US) if nothing matches.
  const [selectedPackId, setSelectedPackId] = useState<string>(() => {
    const base = selectedLang.split('-')[0] ?? 'en';
    const byLocale = COUNTRY_PACKS.find((p) => p.locale === base);
    const byRegion = COUNTRY_PACKS.find((p) => p.region === suggestedRegion);
    return (byLocale ?? byRegion ?? DEFAULT_COUNTRY_PACK).id;
  });
  // Per-component status for the active generic preset (locale + cost DB only;
  // demos are handled exclusively by the partner-pack installer).
  const [packLocaleState, setPackLocaleState] = useState<PackComponentState>('idle');
  const [packDbState, setPackDbState] = useState<PackComponentState>('idle');
  const [packInstalling, setPackInstalling] = useState(false);
  // À la carte: expandable "Customize / install separately" panel.
  const [packCustomizeOpen, setPackCustomizeOpen] = useState(false);
  // Record the classification standard chosen via the pack (stored locally so
  // it can be read by the workspace; mirrors how loaded databases are tracked).
  const [recordedClassification, setRecordedClassification] = useState<string | null>(null);

  const selectedPack = getCountryPack(selectedPackId) ?? DEFAULT_COUNTRY_PACK;

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

  // Generalized cost-DB loader. Loads an explicit ``region`` (defaults to the
  // currently selected one) and returns ``true`` on success so callers that
  // chain components (the Country Pack "install all" flow) can react. Shared
  // by the region grid (manual path) and the Country Pack picker.
  const loadCostDb = useCallback(
    async (region: string): Promise<boolean> => {
      if (loadingDb || (loadedDb && loadedDb.id === region)) return !!loadedDb;
      setLoadingDb(true);

      const dbName = CWICR_DATABASES.find((d) => d.id === region)?.name ?? region;
      const taskId = `db-${region}-${Date.now()}`;

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

        const res = await fetch(`/api/v1/costs/load-cwicr/${region}`, {
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
          setLoadedDb({ id: region, count: imported });

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
            if (!existing.includes(region)) {
              localStorage.setItem(
                'oe_loaded_databases',
                JSON.stringify([...existing, region]),
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
          return true;
        }
        const err = await res.json().catch(() => ({ detail: 'Failed to load database' }));
        updateQueueTask(taskId, { status: 'error', progress: 0, error: extractErrorMessageFromBody(err) ?? 'Failed' });
        addToast({
          type: 'error',
          title: 'Failed to load database',
          message: extractErrorMessageFromBody(err) ?? 'Unknown error',
        });
        return false;
      } catch {
        updateQueueTask(taskId, { status: 'error', progress: 0, error: 'Connection error' });
        addToast({
          type: 'error',
          title: t('common.connection_error', { defaultValue: 'Connection error' }),
        });
        return false;
      } finally {
        setLoadingDb(false);
      }
    },
    [loadingDb, loadedDb, addToast, t, addQueueTask, updateQueueTask],
  );

  // Region-grid (manual path) load button: load whatever region is selected.
  const handleLoadDb = useCallback(() => {
    void loadCostDb(selectedRegion);
  }, [loadCostDb, selectedRegion]);

  // Generalized demo installer. Installs an explicit ``demoId`` and returns
  // ``true`` on success. Built-in demo ids only — POST /api/demo/install/{id}.
  const installDemoProject = useCallback(
    async (demoId: string): Promise<boolean> => {
      setInstallingDemo(true);
      try {
        await apiPost(`/demo/install/${demoId}`, undefined, { longRunning: true });
        setDemoInstalled(true);
        addToast({
          type: 'success',
          title: t('onboarding.demo_installed', { defaultValue: 'Demo project installed' }),
        });
        return true;
      } catch {
        addToast({
          type: 'error',
          title: t('onboarding.demo_install_error', {
            defaultValue: 'Failed to install demo project',
          }),
        });
        return false;
      } finally {
        setInstallingDemo(false);
      }
    },
    [addToast, t],
  );

  // Manual path: install the language-suggested demo.
  const handleInstallDemo = useCallback(() => {
    void installDemoProject(suggestedDemoId);
  }, [installDemoProject, suggestedDemoId]);

  // ── Country Pack component runners ──────────────────────────────────────

  /** Set the UI locale and persist it as an explicit user choice. */
  const applyLocale = useCallback((locale: string) => {
    i18n.changeLanguage(locale);
    try {
      localStorage.setItem('oe_lang_explicit', '1');
    } catch {
      // storage unavailable — locale still applied for this session
    }
  }, []);

  /** Record the workspace cost-classification standard locally. */
  const recordClassification = useCallback((classification: string) => {
    setRecordedClassification(classification);
    try {
      localStorage.setItem('oe_classification', classification);
    } catch {
      // ignore — non-critical preference
    }
  }, []);

  // À la carte: set just the pack's locale.
  const handlePackLocale = useCallback(
    (pack: CountryPack) => {
      setPackLocaleState('running');
      applyLocale(pack.locale);
      recordClassification(pack.classification);
      setPackLocaleState('done');
    },
    [applyLocale, recordClassification],
  );

  // À la carte: load just the pack's cost database.
  const handlePackDb = useCallback(
    async (pack: CountryPack) => {
      setSelectedRegion(pack.region);
      setPackDbState('running');
      const ok = await loadCostDb(pack.region);
      setPackDbState(ok ? 'done' : 'error');
    },
    [loadCostDb],
  );

  // One-click (generic preset): apply language + classification and load the
  // relational cost DB. No demo — fully-worked demos are installed only via the
  // partner-pack installer (DESIGN §7). Endpoint called:
  //   - POST /api/v1/costs/load-cwicr/{region}
  // Locale + classification are applied client-side.
  const handleInstallPack = useCallback(
    async (pack: CountryPack) => {
      if (packInstalling) return;
      setPackInstalling(true);

      // 1) Locale + classification — instant, client-side.
      setPackLocaleState('running');
      applyLocale(pack.locale);
      recordClassification(pack.classification);
      setPackLocaleState('done');

      // 2) Cost database.
      setPackDbState('running');
      const dbOk = await loadCostDb(pack.region);
      setPackDbState(dbOk ? 'done' : 'error');

      setPackInstalling(false);
    },
    [packInstalling, applyLocale, recordClassification, loadCostDb],
  );

  // When the user switches the active preset, reset its per-component status and
  // align the manual region grid with the preset's region for consistency.
  const handleSelectPack = useCallback((pack: CountryPack) => {
    setSelectedPackId(pack.id);
    setSelectedRegion(pack.region);
    setPackLocaleState('idle');
    setPackDbState('idle');
  }, []);

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
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('onboarding.ai_save_failed', { defaultValue: 'Failed to save AI settings' }), message: err.message });
    },
  });

  const handleContinue = useCallback(async () => {
    // If the user neither picked a generic preset nor loaded a DB manually,
    // fall back to background-loading the active preset's region so a fresh
    // workspace still gets a sensible cost database. The preset flow already
    // owns its own progress, so only kick this off when nothing is in flight.
    const dbUntouched =
      packDbState === 'idle' && packLocaleState === 'idle' && !loadedDb && !loadingDb;
    if (backgroundLoad && dbUntouched && selectedRegion) {
      // Fire and forget — don't await, just start in background.
      handleLoadDb();
      // Apply the active preset's locale + classification too, so a one-tap
      // "Continue" still localizes the workspace.
      applyLocale(selectedPack.locale);
      recordClassification(selectedPack.classification);
      addToast({
        type: 'info',
        title: t('onboarding.db_loading_bg', { defaultValue: 'Loading database in background...' }),
        message: t('onboarding.db_loading_bg_desc', {
          defaultValue: 'You can continue working. We\'ll notify you when it\'s ready.',
        }),
      });
    } else if (installDemo && !demoInstalled && !installingDemo) {
      // Advanced manual path: install the toggled built-in demo project.
      handleInstallDemo();
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
    packDbState,
    packLocaleState,
    selectedPack,
    applyLocale,
    recordClassification,
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

  // Region filter (added 2026-04-28: with 30 regions the full grid is too tall
  // for a single onboarding step; the filter lets the user narrow down quickly
  // by name / city / currency / language before scrolling).
  const [regionQuery, setRegionQuery] = useState('');
  const filteredRegions = (() => {
    const q = regionQuery.trim().toLowerCase();
    if (!q) return CWICR_DATABASES;
    return CWICR_DATABASES.filter((db) => {
      return (
        db.name.toLowerCase().includes(q) ||
        db.city.toLowerCase().includes(q) ||
        db.currency.toLowerCase().includes(q) ||
        db.lang.toLowerCase().includes(q) ||
        db.id.toLowerCase().includes(q)
      );
    });
  })();

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
        {/* ── Partner packs: the lead, one-click full-workspace install ──── */}
        <PartnerPackInstaller onActivateLocale={applyLocale} />

        {/* ── Other countries: generic presets (language + classification) ── */}
        <CountryPackCard
          packs={COUNTRY_PACKS}
          selectedPack={selectedPack}
          onSelectPack={handleSelectPack}
          onInstallPack={handleInstallPack}
          onPackLocale={handlePackLocale}
          onPackDb={handlePackDb}
          installing={packInstalling}
          localeState={packLocaleState}
          dbState={packDbState}
          customizeOpen={packCustomizeOpen}
          onToggleCustomize={() => setPackCustomizeOpen((v) => !v)}
          recordedClassification={recordedClassification}
        />

        {/* ── Advanced / manual setup ──────────────────────────────────── */}
        <details className="group rounded-2xl bg-surface-elevated/60 shadow-sm shadow-black/[0.04]">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 text-sm font-medium text-content-secondary hover:text-content-primary transition-colors">
            <span className="flex items-center gap-2">
              <Settings2 size={16} className="text-content-tertiary" />
              {t('onboarding.advanced_manual_setup', {
                defaultValue: 'Advanced - pick a region manually or connect AI',
              })}
            </span>
            <ChevronDown
              size={16}
              className="text-content-tertiary transition-transform duration-200 group-open:rotate-180"
            />
          </summary>

          <div className="space-y-4 p-4 pt-0">
        {/* Card 1: Cost Database — full width */}
        <div className="rounded-2xl bg-surface-elevated shadow-sm shadow-black/[0.04] p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
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

          {/* Region filter — keeps the 30-region grid manageable */}
          <div className="mb-2">
            <input
              type="search"
              value={regionQuery}
              onChange={(e) => setRegionQuery(e.target.value)}
              placeholder={t('onboarding.region_filter_placeholder', {
                defaultValue: 'Filter by country, city, or currency…',
              })}
              disabled={loadingDb || !!loadedDb}
              className="w-full rounded-lg bg-surface-secondary/70 px-3 py-1.5 text-xs text-content-primary placeholder:text-content-quaternary border border-transparent focus:border-oe-blue/40 focus:outline-none focus:bg-surface-secondary disabled:opacity-50"
            />
          </div>

          {/* All regions as selectable cards (scrollable for 30 entries) */}
          <div className="max-h-72 overflow-y-auto pr-1 -mr-1 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 mb-3">
            {filteredRegions.length === 0 && (
              <div className="col-span-full py-6 text-center text-xs text-content-tertiary">
                {t('onboarding.region_filter_no_results', {
                  defaultValue: 'No regions match "{{q}}"',
                  q: regionQuery,
                })}
              </div>
            )}
            {filteredRegions.map((db) => {
              const isSelected = selectedRegion === db.id;
              return (
                <button
                  key={db.id}
                  onClick={() => !loadingDb && !loadedDb && setSelectedRegion(db.id)}
                  disabled={loadingDb || !!loadedDb}
                  className={clsx(
                    'flex items-center gap-2 rounded-xl px-3 py-2 text-left transition-all duration-200',
                    isSelected
                      ? 'bg-oe-blue-subtle/50 ring-2 ring-oe-blue/40 shadow-sm'
                      : 'bg-surface-secondary/70 hover:bg-surface-secondary hover:shadow-sm',
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
        <div className="rounded-2xl bg-surface-elevated shadow-sm shadow-black/[0.04] p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
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
        <div className="rounded-2xl bg-surface-elevated shadow-sm shadow-black/[0.04]">
          <button
            type="button"
            onClick={() => setAiExpanded(!aiExpanded)}
            className="w-full flex items-center justify-between p-6"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
                <Sparkles size={20} />
              </div>
              <div className="text-left">
                <h3 className="text-base font-bold text-content-primary">
                  {t('onboarding.connect_ai', { defaultValue: 'Connect AI Provider' })}
                </h3>
                <p className="text-xs text-content-tertiary">
                  {t('onboarding.ai_optional', { defaultValue: 'Optional - smart estimation features' })}
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
        </details>
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
          {t('onboarding.skip', { defaultValue: 'Skip - set up later' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleContinue}
          loading={saveMutation.isPending || installingDemo || packInstalling}
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

/**
 * "Make your workspace yours" — an optional, last-step personalization card on
 * the Finish screen. Opens the exact same {@link BrandingEditorModal} the
 * sidebar uses, so the company logo / name a user sets here behaves identically
 * to editing it later from the sidebar (single source of truth — the shared
 * ``useBrandingStore``). Shows a live preview of the chosen brand.
 */
function WorkspaceBrandingCard() {
  const { t } = useTranslation();
  const { mode, logoDataUrl, companyName } = useBrandingStore();
  const [editing, setEditing] = useState(false);
  const customised = mode === 'logo' || mode === 'text';

  return (
    <div className="mt-7 w-full max-w-md mx-auto">
      <div className="flex items-center gap-3 rounded-2xl border border-border-light bg-surface-elevated/70 backdrop-blur-md p-4 text-left shadow-sm shadow-black/[0.04]">
        {/* Brand preview tile — user logo when set, else a neutral glyph. */}
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle overflow-hidden">
          {mode === 'logo' && logoDataUrl ? (
            <img
              src={logoDataUrl}
              alt={companyName || 'Logo'}
              className="h-full w-full object-contain"
              draggable={false}
            />
          ) : (
            <Building2 size={22} className="text-oe-blue" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary truncate">
            {customised && companyName
              ? companyName
              : t('onboarding.brand_title', { defaultValue: 'Make your workspace yours' })}
          </p>
          <p className="text-xs text-content-tertiary truncate">
            {customised
              ? t('onboarding.brand_set', {
                  defaultValue: 'Your brand shows in the sidebar and the browser tab',
                })
              : t('onboarding.brand_hint', {
                  defaultValue: 'Add your company logo or name (optional)',
                })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-3 py-1.5 text-xs font-semibold text-oe-blue hover:bg-oe-blue/10 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        >
          <Pencil size={13} />
          {customised
            ? t('common.edit', { defaultValue: 'Edit' })
            : t('onboarding.brand_add', { defaultValue: 'Add' })}
        </button>
      </div>
      {editing && <BrandingEditorModal onClose={() => setEditing(false)} />}
    </div>
  );
}

function StepFinish({
  onBack,
  companyType,
  enabledModules,
  presets,
  packInstalled = false,
}: {
  onBack: () => void;
  companyType: string | null;
  enabledModules: Set<string>;
  presets: ApiCompanyPreset[];
  /** A ready-made pack already provisioned modules + regional config + sample
   *  data server-side. When true, Finish must NOT overwrite those module
   *  preferences or re-POST a generic onboarding payload, and it lands on the
   *  freshly seeded projects. */
  packInstalled?: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setModuleEnabled = useModuleStore((s) => s.setModuleEnabled);
  const setViewMode = useViewModeStore((s) => s.setMode);
  const text = usePresetText();
  const [saving, setSaving] = useState(false);

  const selectedPreset = companyType
    ? presets.find((p) => p.key === companyType)
    : undefined;
  const presetLabel = selectedPreset ? text.label(selectedPreset) : null;

  const enabledCount = enabledModules.size + CORE_MODULE_KEYS.size;

  const handleFinish = useCallback(async () => {
    setSaving(true);

    // Apply advanced mode (default for onboarding) in every path.
    setViewMode('advanced');

    if (packInstalled) {
      // The ready-made pack already configured modules, locale, classification
      // and sample data on the server. Don't clobber that here -- just mark
      // onboarding complete (which fires the tour-gating event) and open the
      // seeded projects.
      markOnboardingCompleted();
      setSaving(false);
      navigate('/projects');
      return;
    }

    // 1. Apply module preferences to the store
    const allModuleKeys = ALL_MODULES.map((m) => m.key);
    for (const key of allModuleKeys) {
      if (!CORE_MODULE_KEYS.has(key)) {
        setModuleEnabled(key, enabledModules.has(key));
      }
    }

    // 2. Save onboarding state to server
    try {
      await apiPost('/v1/users/me/onboarding/', {
        company_type: companyType ?? 'full_enterprise',
        enabled_modules: Array.from(enabledModules),
        interface_mode: 'advanced',
        completed: true,
      });
    } catch {
      // Non-critical -- local state is already applied
    }

    // 3. Mark completed locally
    markOnboardingCompleted();

    setSaving(false);
    navigate('/');
  }, [companyType, enabledModules, navigate, packInstalled, setModuleEnabled, setViewMode]);

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
        {packInstalled
          ? t('onboarding.finish_subtitle_pack', {
              defaultValue:
                'Your ready-made pack is installed. Language, cost databases, modules and sample projects are all set up.',
            })
          : t('onboarding.finish_subtitle', {
              defaultValue: 'Your workspace is configured and ready to use.',
            })}
      </p>

      {/* Summary line */}
      <div className="mt-5 inline-flex items-center gap-2 rounded-full bg-surface-secondary px-4 py-2 text-sm text-content-primary">
        {packInstalled ? (
          <>
            <span className="font-semibold">
              {t('onboarding.ready_pack', { defaultValue: 'Ready-made Pack' })}
            </span>
            <span className="text-content-tertiary">|</span>
            <span>
              {t('onboarding.finish_pack_seeded', { defaultValue: 'Sample projects ready' })}
            </span>
            <span className="text-content-tertiary">|</span>
            <span>
              {SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language)?.name || i18n.language}
            </span>
          </>
        ) : (
          <>
            {companyType && presetLabel && (
              <>
                <span className="font-semibold">{presetLabel}</span>
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
          </>
        )}
      </div>

      <p className="mt-5 text-xs text-content-tertiary max-w-md">
        {t('onboarding.finish_hint', {
          defaultValue: 'You can adjust all settings later from the Settings page.',
        })}
      </p>

      {/* Optional personalization — set the company logo / name now, using the
          same editor the sidebar uses. Purely optional; the brand also stays
          editable from the sidebar at any time. */}
      <WorkspaceBrandingCard />

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

      {/* Explore-all CTA — links to /modules so users can see the full
          88-module marketplace post-onboarding. Persists onboarding-complete
          before navigation so users don't get bounced back into the wizard. */}
      <div className="mt-6">
        <Link
          to="/modules"
          onClick={markOnboardingCompleted}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:underline transition-colors"
        >
          <Package size={14} />
          {t('onboarding.explore_all_modules', {
            defaultValue: 'Explore all {{count}} modules',
            count: TOTAL_MODULE_COUNT,
          })}
          <ArrowRight size={12} />
        </Link>
      </div>
    </div>
  );
}

// ── Main Wizard ──────────────────────────────────────────────────────────────

export function OnboardingWizard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [selectedLang, setSelectedLang] = useState(() => i18n.language?.split('-')[0] || 'en');
  const presets = useOnboardingPresets();
  const [companyType, setCompanyType] = useState<string | null>(null);
  const [enabledModules, setEnabledModules] = useState<Set<string>>(
    () => new Set(ALL_MODULES.filter((m) => !m.core).map((m) => m.key)),
  );

  /* ONBOARD-MODAL: the wizard itself had NO completed-flag guard — it
     always rendered step 0 ("Welcome to OpenConstructionERP"). It is only
     mounted at the /onboarding route, but anything that routes there
     (the dashboard first-run redirect, a stale bookmark, a back-button,
     QA navigation) re-showed the welcome modal even for users who already
     finished onboarding. Gate the wizard on the SAME localStorage flag
     the dashboard redirect uses (`oe_onboarding_completed`, via the
     shared `isOnboardingCompleted()` helper) and bounce completed users
     straight to the app. The Settings "restart onboarding" action removes
     that flag *before* navigating here, so an intentional re-run still
     works (flag absent → guard passes → wizard shows). Computed once at
     mount so finishing the wizard (which sets the flag) doesn't yank the
     UI out from under the success step. */
  const [alreadyCompleted] = useState(() => isOnboardingCompleted());

  useEffect(() => {
    if (alreadyCompleted) {
      navigate('/', { replace: true });
    }
  }, [alreadyCompleted, navigate]);

  // Track whether user chose "Quick Start" (skip profile + modules, go to data)
  const [quickStart, setQuickStart] = useState(false);
  // Track whether module config step should be shown
  const [showModuleConfig, setShowModuleConfig] = useState(false);
  // Ready-made pack flow: when true, step 1 swaps its choice cards for the
  // pack picker. ``packInstalledSlug`` records the slug once a pack is fully
  // installed so the Finish step shows pack-appropriate copy and does not
  // overwrite the modules the pack just configured.
  const [readyPackView, setReadyPackView] = useState(false);
  const [packInstalledSlug, setPackInstalledSlug] = useState<string | null>(null);

  // Persistent escape hatch (top-right, every step): switch the whole app to
  // English, mark the language choice as explicit so the locale auto-detect
  // never overrides it, complete onboarding exactly like the finish path, and
  // drop the user straight on the dashboard. No confirmation dialog.
  const handleSkipAll = useCallback(() => {
    void i18n.changeLanguage('en');
    try {
      localStorage.setItem('oe_lang_explicit', '1');
    } catch {
      // Storage unavailable -- ignore.
    }
    markOnboardingCompleted();
    navigate('/dashboard');
  }, [navigate]);

  const goNext = useCallback(() => {
    setStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  }, []);

  const goBack = useCallback(() => {
    setStep((s) => Math.max(s - 1, 0));
  }, []);

  const handleLanguageChange = useCallback((lang: string) => {
    setSelectedLang(lang);
  }, []);

  const handleSelectCompanyType = useCallback(
    (key: string) => {
      setCompanyType(key);
      // Apply the preset's module set (full_enterprise = every non-core module).
      const preset = presets.find((p) => p.key === key);
      if (preset) setEnabledModules(presetModuleSet(preset));
    },
    [presets],
  );

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

  // ── Ready-made pack handlers ──────────────────────────────────────────────

  /** Set the UI locale and persist it as an explicit user choice (shared with
   *  the country-pack data step). */
  const applyLocale = useCallback((locale: string) => {
    i18n.changeLanguage(locale);
    try {
      localStorage.setItem('oe_lang_explicit', '1');
    } catch {
      // storage unavailable -- locale still applied for this session
    }
  }, []);

  /** "Ready-made Pack" card -> swap the step-1 cards for the pack picker. */
  const handleReadyPack = useCallback(() => {
    setReadyPackView(true);
  }, []);

  /** Pack fully installed -> record the slug and jump straight to Finish.
   *  ``markOnboardingCompleted`` (and its tour-gating event) runs from the
   *  Finish step's primary action, so the completion path matches the normal
   *  flow exactly. */
  const handleReadyPackInstalled = useCallback((slug: string) => {
    setPackInstalledSlug(slug);
    setReadyPackView(false);
    setStep(5);
  }, []);

  /** Install failed -> fall back to the normal multi-step flow (the picker
   *  already surfaced a clear toast explaining the fallback). */
  const handleReadyPackFallback = useCallback(() => {
    setReadyPackView(false);
    setQuickStart(false);
    setShowModuleConfig(false);
    setStep(2); // company profile
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

  // Onboarding already finished: render nothing while the effect above
  // redirects to the app. Returning null (instead of the wizard) is what
  // actually stops the "Welcome to OpenConstructionERP" modal from
  // flashing on top of /settings & friends. (ONBOARD-MODAL)
  if (alreadyCompleted) {
    return null;
  }

  return (
    <div className="relative flex min-h-screen flex-col bg-surface-primary overflow-hidden">
      {/* ── Decorative background: soft mesh + subtle grid ──────────────
          Pure decoration, no interaction. Respects prefers-reduced-motion
          because the gradients are static (no keyframe animation beyond
          the slow `animate-oe-pulse` already bundled). */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        {/* Soft radial mesh — two offset blobs with the brand palette. */}
        <div
          className="absolute -top-40 -start-40 h-[520px] w-[520px] rounded-full blur-3xl opacity-[0.35] dark:opacity-[0.22]"
          style={{
            background:
              'radial-gradient(circle at center, rgba(37, 99, 235, 0.55), transparent 70%)',
          }}
        />
        <div
          className="absolute top-1/3 -end-32 h-[460px] w-[460px] rounded-full blur-3xl opacity-[0.30] dark:opacity-[0.18]"
          style={{
            background:
              'radial-gradient(circle at center, rgba(168, 85, 247, 0.45), transparent 70%)',
          }}
        />
        <div
          className="absolute bottom-[-160px] start-1/3 h-[420px] w-[420px] rounded-full blur-3xl opacity-[0.25] dark:opacity-[0.15]"
          style={{
            background:
              'radial-gradient(circle at center, rgba(14, 165, 233, 0.40), transparent 70%)',
          }}
        />
        {/* Fine grid overlay — 1px lines every 40px, 4% opacity. Works in
            both light and dark themes. */}
        <div
          className="absolute inset-0 opacity-[0.02] dark:opacity-[0.035]"
          style={{
            backgroundImage:
              'linear-gradient(to right, currentColor 1px, transparent 1px), linear-gradient(to bottom, currentColor 1px, transparent 1px)',
            backgroundSize: '40px 40px',
          }}
        />
      </div>

      {/* ── Sticky glass header with progress + skip ────────────────── */}
      <div className="sticky top-0 z-10 bg-surface-primary/85 backdrop-blur-xl">
        <div className="max-w-3xl mx-auto w-full px-6 sm:px-8 py-4">
          <div className="flex items-center justify-between gap-4 mb-6">
            <div className="flex items-center gap-2 shrink-0">
              <Logo size="sm" />
              <span className="text-[11px] font-semibold text-content-tertiary uppercase tracking-wider hidden sm:inline">
                {t('onboarding.setup_label', { defaultValue: 'Setup wizard' })}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs tabular-nums text-content-tertiary hidden sm:inline">
                {t('onboarding.progress_step_x_of_y', {
                  defaultValue: 'Step {{current}} of {{total}}',
                  current: step + 1,
                  total: TOTAL_STEPS,
                })}
              </span>
              {step > 0 && step < TOTAL_STEPS - 1 && (
                <button
                  type="button"
                  onClick={() => setStep(TOTAL_STEPS - 1)}
                  className="text-xs font-medium text-content-tertiary hover:text-content-secondary transition-colors"
                >
                  {t('onboarding.skip_setup', { defaultValue: 'Skip setup' })}
                </button>
              )}
              {/* Persistent escape hatch on every step: open the app now in
                  English. A quiet secondary pill so it never competes with the
                  wizard's primary CTA. */}
              <button
                type="button"
                onClick={handleSkipAll}
                className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-elevated/70 px-3 py-1 text-xs font-medium text-content-tertiary backdrop-blur-sm transition-colors hover:border-oe-blue/40 hover:bg-surface-elevated hover:text-content-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
              >
                <Globe size={13} strokeWidth={2} />
                {t('onboarding.skip_all', { defaultValue: 'Skip setup - open in English' })}
              </button>
            </div>
          </div>
          <ProgressBar current={step} total={TOTAL_STEPS} />
        </div>
      </div>

      {/* ── Main content — sits on the glass card over the mesh ──────
          Tight vertical padding so a 6-step wizard fits without scroll
          on ~768-viewport laptops. Previously ``pt-10 pb-24`` + card
          ``py-8 sm:py-12`` added ~150px of shell chrome alone. */}
      <div className="relative flex flex-1 items-start justify-center px-4 sm:px-6 pt-4 pb-8">
        <div className="w-full max-w-[960px]">
          <div className="px-6 sm:px-10 py-6 sm:py-8">
            <StepTransition stepKey={step}>
              {step === 0 && (
                <StepWelcome onNext={goNext} onLanguageChange={handleLanguageChange} />
              )}
              {step === 1 && !readyPackView && (
                <StepStartChoice
                  onQuickStart={handleQuickStart}
                  onChooseProfile={handleChooseProfile}
                  onReadyPack={handleReadyPack}
                  onBack={goBack}
                />
              )}
              {step === 1 && readyPackView && (
                <ReadyPackPicker
                  onActivateLocale={applyLocale}
                  onInstalled={handleReadyPackInstalled}
                  onFallback={handleReadyPackFallback}
                  onBack={() => setReadyPackView(false)}
                />
              )}
              {step === 2 && (
                <StepCompanyProfile
                  onNext={handleNextFromProfile}
                  onBack={() => setStep(1)}
                  presets={presets}
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
                  onBack={() => (packInstalledSlug ? setStep(1) : setStep(4))}
                  companyType={companyType}
                  enabledModules={enabledModules}
                  presets={presets}
                  packInstalled={packInstalledSlug !== null}
                />
              )}
            </StepTransition>
          </div>

          {/* Trust footer — small line directly below the card. */}
          <p className="mt-3 text-center text-[11px] text-content-tertiary">
            {t('onboarding.footer_trust', {
              defaultValue:
                'Free and open-source · Your data stays on your server · AGPL-3.0',
            })}
          </p>
        </div>
      </div>
    </div>
  );
}
