// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import {
  Eye, EyeOff, Mail, Lock, Globe, ChevronDown, Pencil,
  Sun, Moon, Monitor,
} from 'lucide-react';
import { Button, Input, Logo, CountryFlag } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { BrandingEditorModal } from '@/app/layout/CustomBranding';
import { extractErrorMessageFromBody } from '@/shared/lib/api';
import { isTauri } from '@/shared/lib/desktop';
import { APP_VERSION } from '@/shared/lib/version';
import { loginFailureKindFromResponse } from './loginError';
import { AuthBackground } from './AuthBackground';
import {
  shouldAttemptDesktopBootstrap,
  shouldQueryFirstRun,
  type FirstRunStatus,
} from './desktopBootstrap';
import { safeNextPath } from './nextPath';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { useThemeStore } from '@/stores/useThemeStore';

/* Segmented theme switch (Light / Dark / System) for the login page. */
function ThemeSwitch() {
  const { t } = useTranslation();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const opts = [
    { mode: 'light' as const, icon: Sun, label: t('theme.light', { defaultValue: 'Light' }) },
    { mode: 'dark' as const, icon: Moon, label: t('theme.dark', { defaultValue: 'Dark' }) },
    { mode: 'system' as const, icon: Monitor, label: t('theme.system', { defaultValue: 'System' }) },
  ];
  return (
    <div
      role="radiogroup"
      aria-label={t('theme.label', { defaultValue: 'Theme' })}
      className="flex items-center gap-0.5 rounded-xl border border-border-light bg-surface-elevated/85 backdrop-blur-sm p-0.5 shadow-sm"
    >
      {opts.map(({ mode, icon: Icon, label }) => {
        const active = theme === mode;
        return (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={active}
            title={label}
            aria-label={label}
            onClick={() => setTheme(mode)}
            className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
              active
                ? 'bg-oe-blue text-white shadow-sm'
                : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary'
            }`}
          >
            <Icon size={15} strokeWidth={2} />
          </button>
        );
      })}
    </div>
  );
}

export function LoginPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const setTokens = useAuthStore((s) => s.setTokens);
  // White-label brand (same localStorage store the in-app sidebar editor
  // writes to). When a tenant has set a logo / company name we show it
  // on the login card instead of the default OpenConstructionERP wordmark.
  const { mode: brandMode, logoDataUrl: brandLogo, companyName: brandName } =
    useBrandingStore();
  const brandCustomised = brandMode === 'logo' || brandMode === 'text';
  // Pull the workspace brand from the server so an invited user sees it on this
  // very first (pre-auth) screen, not just the browser that set it (issue #272).
  // Public endpoint, best-effort: the card paints instantly from localStorage
  // and this reconciles to whatever the workspace admin saved.
  useEffect(() => {
    void useBrandingStore.getState().hydrateFromServer();
  }, []);
  // `?next=/path` lets guarded routes send the user back to where they wanted
  // to go after login. Falls back to `/` for direct visits. Shared with the
  // authenticated-route guard (AuthedHome) so a redirect race between the two
  // cannot silently drop the `next` (the demo deep-link bug).
  const nextPath = safeNextPath(location.search);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [rememberMe, setRememberMe] = useState(
    () => localStorage.getItem('oe_remember') === '1',
  );
  const [langOpen, setLangOpen] = useState(false);
  const [brandOpen, setBrandOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);

  // Desktop first-run: when running inside the Tauri shell with no stored
  // token and no deliberate manual logout this session, we silently auto-sign
  // in to the local workspace owner. Seed the pending flag synchronously so the
  // very first paint shows "Preparing your workspace..." rather than flashing
  // the login form before the bootstrap effect runs.
  const [bootstrapping, setBootstrapping] = useState(() => {
    if (typeof window === 'undefined') return false;
    const stored =
      localStorage.getItem('oe_access_token') || sessionStorage.getItem('oe_access_token');
    const manual = sessionStorage.getItem('oe_manual_login');
    return shouldQueryFirstRun(isTauri, Boolean(stored), manual);
  });

  const currentLang =
    SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language) ?? SUPPORTED_LANGUAGES[0]!;

  // Clear form on mount (prevents pre-fill after logout)
  useEffect(() => {
    setEmail('');
    setPassword('');
    setError('');
  }, []);


  // Desktop auto-bootstrap. Runs once on mount. On ANY failure it silently
  // falls back to the normal login form (clears `bootstrapping`); it never
  // surfaces an error to the user because manual login is always a valid path.
  useEffect(() => {
    if (!bootstrapping) return;
    let cancelled = false;

    const run = async () => {
      try {
        const res = await fetch('/api/v1/auth/first-run', {
          headers: { Accept: 'application/json' },
        });
        if (!res.ok) throw new Error('first-run probe failed');
        const status = (await res.json()) as FirstRunStatus;

        const manual = sessionStorage.getItem('oe_manual_login');
        if (!shouldAttemptDesktopBootstrap(status, false, manual)) {
          throw new Error('bootstrap not applicable');
        }

        const bootRes = await fetch('/api/v1/auth/desktop-bootstrap', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });
        if (!bootRes.ok) throw new Error('desktop bootstrap failed');
        const data = (await bootRes.json()) as {
          access_token?: string;
          refresh_token?: string;
          user?: { email?: string };
        };
        if (!data.access_token || !data.refresh_token) {
          throw new Error('bootstrap response missing tokens');
        }
        if (cancelled) return;

        // Persist through the existing auth store path with remember=true so the
        // desktop owner stays signed in across launches.
        setTokens(data.access_token, data.refresh_token, true, data.user?.email);
        navigate(status.onboarding_completed === true ? '/dashboard' : '/onboarding', {
          replace: true,
        });
      } catch {
        // Silent fallback to the manual login form.
        if (!cancelled) setBootstrapping(false);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
    // Mount-only: the gate inputs are read fresh inside `run`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/api/v1/users/auth/login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        // A proxy answering 502 for a backend that is down is a response, not
        // a network error, so the catch below never sees it. Without this the
        // outage lands on the credentials wording and the person is told the
        // one thing we know is untrue: nothing read their password. A 4xx
        // carrying no message we can read is that same outage told by whatever
        // stands in front of us, so the body decides alongside the status.
        const data = await res.json().catch(() => null);
        const parsed = extractErrorMessageFromBody(data);
        if (loginFailureKindFromResponse(res.status, parsed) === 'unavailable') {
          setError(
            t('auth.server_unavailable', {
              defaultValue:
                'The server did not answer, so your details were never checked. Try again in a moment.',
            }),
          );
          return;
        }
        setError(parsed || t('auth.invalid_credentials', 'Invalid email or password'));
        return;
      }
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token, rememberMe, email);
      navigate(nextPath, { replace: true });
    } catch {
      setError(t('auth.connection_error', 'Unable to connect to server. Please try again.'));
    } finally {
      setLoading(false);
    }
  };



  // Desktop first-run: clean centered pending state while we silently sign in
  // to the local workspace. Falls back to the form on any failure (see effect).
  if (bootstrapping) {
    return (
      <div className="relative flex h-screen flex-col items-center justify-center bg-surface-secondary overflow-hidden">
        <AuthBackground />
        <div className="relative z-10 flex flex-col items-center gap-5 px-6 text-center">
          <Logo size="lg" animate />
          <svg
            className="h-7 w-7 animate-spin text-oe-blue"
            viewBox="0 0 24 24"
            aria-hidden
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
              fill="none"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          <p className="text-sm font-medium text-content-secondary">
            {t('auth.preparing_workspace', { defaultValue: 'Preparing your workspace...' })}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative grid h-screen grid-cols-1 lg:grid-cols-2 bg-surface-secondary overflow-hidden">
      <AuthBackground />

      {/* Local style block - premium glass variant + drifting orb keyframes
          scoped to the login page. Pattern mirrors LoginPageNext.tsx. */}
      <style>{`
        .login-glass-pro {
          background:
            linear-gradient(135deg, rgba(255,255,255,0.78) 0%, rgba(255,255,255,0.62) 100%);
          backdrop-filter: blur(28px) saturate(180%);
          -webkit-backdrop-filter: blur(28px) saturate(180%);
          border: 1px solid rgba(255, 255, 255, 0.85);
          box-shadow:
            0 36px 80px -28px rgba(14, 165, 233, 0.30),
            0 14px 36px -12px rgba(15, 23, 42, 0.12),
            0 2px 6px -1px rgba(15, 23, 42, 0.06),
            inset 0 1px 0 rgba(255, 255, 255, 0.95),
            inset 0 0 0 1px rgba(255, 255, 255, 0.35);
        }
        .dark .login-glass-pro {
          background:
            linear-gradient(135deg, rgba(22, 26, 36, 0.78) 0%, rgba(15, 17, 23, 0.66) 100%);
          border-color: transparent;
          box-shadow:
            0 30px 80px -24px rgba(14, 165, 233, 0.35),
            0 12px 40px -12px rgba(0, 0, 0, 0.55),
            0 2px 6px -2px rgba(0, 0, 0, 0.4);
        }
        .login-glass-pro::after {
          content: '';
          position: absolute;
          inset: 0;
          border-radius: inherit;
          pointer-events: none;
          background:
            radial-gradient(120% 80% at 0% 0%, rgba(14, 165, 233, 0.05), transparent 65%);
          mix-blend-mode: soft-light;
        }
        .dark .login-glass-pro::after {
          background:
            radial-gradient(120% 80% at 0% 0%, rgba(14, 165, 233, 0.18), transparent 60%),
            radial-gradient(120% 80% at 100% 100%, rgba(139, 92, 246, 0.16), transparent 60%);
          mix-blend-mode: screen;
        }
        @keyframes login-orb-drift-a {
          0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
          50%      { transform: translate3d(30px, -22px, 0) scale(1.08); }
        }
        @keyframes login-orb-drift-b {
          0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
          50%      { transform: translate3d(-26px, 28px, 0) scale(0.94); }
        }
        @keyframes login-orb-drift-c {
          0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
          50%      { transform: translate3d(20px, 32px, 0) scale(1.05); }
        }
        .login-orb-a { animation: login-orb-drift-a 12s ease-in-out infinite; }
        .login-orb-b { animation: login-orb-drift-b 14s ease-in-out infinite; }
        .login-orb-c { animation: login-orb-drift-c 10s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .login-orb-a, .login-orb-b, .login-orb-c { animation: none; }
        }
      `}</style>

      {/* ── Ambient mesh blobs (LEFT half only) ─────────────────────────
          Restrained palette - single faint sky blob behind the form column
          so the glass card sits on a near-white field. Dark mode keeps the
          original richer blob set for depth. */}
      <div className="absolute inset-y-0 start-0 end-1/2 z-0 pointer-events-none overflow-hidden hidden lg:block">
        <div className="absolute top-[-12%] left-[-6%] w-[520px] h-[520px] rounded-full bg-sky-300/10 dark:bg-oe-blue/35 blur-[120px] animate-blob-slow-1 mix-blend-screen" />
        <div className="absolute bottom-[-18%] right-[2%] w-[400px] h-[400px] rounded-full bg-cyan-200/10 dark:bg-violet-500/35 blur-[110px] animate-blob-slow-4 mix-blend-screen hidden dark:block" />
      </div>

      {/* Mobile-only ambient blobs (single column layout) */}
      <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden lg:hidden">
        <div className="absolute top-[-12%] left-[-6%] w-[520px] h-[520px] rounded-full bg-sky-300/10 dark:bg-oe-blue/35 blur-[110px] animate-blob-slow-1 mix-blend-screen" />
      </div>

      {/* Theme + Language - top right (enlarged for /login so discoverable). */}
      <div className="absolute top-4 right-4 z-30 flex items-center gap-2">
        <ThemeSwitch />
        <div className="relative" ref={langRef}>
        <button
          onClick={() => setLangOpen(!langOpen)}
          className="flex items-center gap-2 rounded-xl border border-border-light bg-surface-elevated/85 backdrop-blur-sm px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-elevated hover:border-oe-blue/30 transition-colors shadow-sm"
        >
          <Globe size={16} className="text-content-tertiary" />
          <CountryFlag code={currentLang.country} size={20} />
          <span className="hidden sm:inline">{currentLang.name}</span>
          <ChevronDown size={14} className={`text-content-tertiary transition-transform ${langOpen ? 'rotate-180' : ''}`} />
        </button>
        {langOpen && (
          <div className="absolute right-0 mt-2 w-64 max-h-80 overflow-y-auto rounded-xl border border-border-light bg-surface-elevated shadow-xl py-1 animate-stagger-in">
            {SUPPORTED_LANGUAGES.map((lang) => {
              const isActive = i18n.language === lang.code;
              const english = 'english' in lang ? (lang as { english?: string }).english : undefined;
              return (
                <button
                  key={lang.code}
                  onClick={() => { i18n.changeLanguage(lang.code); setLangOpen(false); }}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-sm transition-colors ${isActive ? 'bg-oe-blue/10 text-oe-blue font-medium' : 'text-content-primary hover:bg-surface-secondary'}`}
                >
                  <CountryFlag code={lang.country} size={18} />
                  <span className="truncate">
                    {lang.name}
                    {english && (
                      <span className="ml-1 text-2xs text-content-tertiary">({english})</span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        )}
        </div>
      </div>

      {/* ── Right column on lg+: calm neutral brand panel.
          Order swap (lg:order-2) puts the form on the left so it's the
          first thing the eye lands on - primary action priority. The
          panel carries the product mark and a one-line tagline only; the
          vendor marketing that used to live here (headline, stat tiles,
          module honeycomb, value props) was removed. */}
      <div className="hidden lg:flex relative z-10 lg:order-2 flex-col items-center justify-center px-12 py-6 overflow-hidden">
        <div className="absolute inset-0 pointer-events-none -z-10 bg-gradient-to-br from-surface-secondary via-surface-secondary to-oe-blue/[0.04] dark:to-oe-blue/[0.08]" aria-hidden />

        <div className="flex flex-col items-center text-center animate-stagger-in" style={{ animationDelay: '60ms' }}>
          {brandCustomised ? (
            brandMode === 'logo' && brandLogo ? (
              <img
                src={brandLogo}
                alt={brandName || 'Custom logo'}
                className="block max-h-24 w-auto max-w-[320px] object-contain"
                draggable={false}
              />
            ) : (
              <span
                className="block max-w-[420px] truncate text-4xl font-extrabold text-content-primary leading-none"
                style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif", letterSpacing: '-0.02em' }}
                title={brandName}
              >
                {brandName}
              </span>
            )
          ) : (
            <div className="flex items-center gap-3">
              <Logo size="lg" />
              <span
                className="text-3xl font-medium text-content-primary whitespace-nowrap"
                style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif", letterSpacing: '-0.02em' }}
              >
                Open<span className="text-oe-blue">Construction</span><span className="text-content-quaternary">ERP</span>
              </span>
            </div>
          )}
          <p className="mt-4 text-base text-content-secondary">
            {t('login.workspace_tagline', { defaultValue: 'Construction project workspace' })}
          </p>
        </div>

        {/* Footer: licence link (AGPL-3.0 obligation) + running version. */}
        <div className="absolute bottom-5 flex items-center gap-2 text-[11px] text-content-quaternary/70 animate-stagger-in" style={{ animationDelay: '200ms' }}>
          <a href="/api/source" target="_blank" rel="noopener noreferrer" className="hover:text-content-tertiary transition-colors">AGPL-3.0</a>
          <span className="opacity-40">&middot;</span>
          <span className="font-mono tabular-nums">v{APP_VERSION}</span>
        </div>
      </div>

      {/* Center column removed - tags moved to left panel footer */}

      {/* ── Left column on lg+: logo + form (primary action). ── */}
      <div className="relative flex items-center justify-center p-4 sm:p-6 z-10 lg:order-1 overflow-hidden">
        {/* Form column backdrop - clean near-white field on lg+ so the
            glass card reads against a calm canvas. The decorative show
            (orbs / mesh) lives on the marketing column on the right. */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden hidden lg:block" aria-hidden>
          {/* Dark mode: use #070912 (DARKER than #0f1117 surface-primary so
              form inputs lift visibly off the column backdrop). Previously
              #0b0d12 — too close to input bg, made inputs invisible. */}
          <div className="absolute inset-0 bg-white dark:bg-[#070912]" />
          <div className="absolute inset-0 bg-gradient-to-l from-white/0 via-white/60 to-white dark:from-[#070912]/0 dark:via-[#070912]/60 dark:to-[#070912]" />
          {/* Tiny far-corner sky tint just to soften the edge - the glass
              still has something to lift off, but the field reads white. */}
          <div className="absolute -top-24 -left-24 w-[420px] h-[420px] rounded-full bg-sky-100/55 dark:bg-sky-500/10 blur-[110px]" />
        </div>
        <div className="w-full max-w-[380px] relative z-10">
          {/* Logo - tenant white-label (logo / company name) when set via
              the in-app sidebar editor; otherwise the default brand. The
              small "by OpenConstructionERP" attribution stays visible in
              customised modes (AGPL-3.0 requirement). */}
          <div className="relative mb-5 flex flex-col items-center animate-stagger-in" style={{ animationDelay: '0ms' }}>
            {/* Brand + edit-pencil row - grouped together and visually
                centered in the form column (previously the pencil was
                pinned to the far right edge which made the brand block
                look off-centre relative to the form below). */}
            <div className="flex items-center gap-2">
              {brandCustomised ? (
                <div className="flex flex-col items-center">
                  {brandMode === 'logo' && brandLogo ? (
                    <img
                      src={brandLogo}
                      alt={brandName || 'Custom logo'}
                      className="block max-h-16 w-auto max-w-full object-contain"
                      draggable={false}
                    />
                  ) : (
                    <span
                      className="block max-w-full truncate text-center text-3xl font-extrabold text-content-primary leading-none"
                      style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif", letterSpacing: '-0.02em' }}
                      title={brandName}
                    >
                      {brandName}
                    </span>
                  )}
                  {/* "by OpenConstructionERP" - subordinate attribution that
                      stays visible (AGPL-3.0). Mirrors CustomBranding.tsx. */}
                  <span
                    className="mt-2 block text-[11px] leading-none text-content-tertiary"
                    style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif", letterSpacing: '0.02em' }}
                  >
                    by{' '}
                    <span className="font-semibold tracking-tight">
                      Open<span className="text-oe-blue/80">Construction</span>
                      <span className="text-content-quaternary">ERP</span>
                    </span>
                  </span>
                </div>
              ) : (
                <div className="flex items-center gap-2.5">
                  <Logo size="md" animate />
                  <span
                    className="text-2xl font-medium text-content-primary whitespace-nowrap"
                    style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif", letterSpacing: '-0.02em' }}
                  >
                    Open<span className="text-oe-blue">Construction</span><span className="text-content-quaternary">ERP</span>
                  </span>
                </div>
              )}
              {/* White-label trigger - same editor as the in-app sidebar
                  brand control, available pre-auth so a tenant can put
                  their own logo on the sign-in screen. */}
              <button
                type="button"
                onClick={() => setBrandOpen(true)}
                className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-border-light bg-surface-elevated/60 text-content-tertiary backdrop-blur-sm transition-colors hover:border-oe-blue/40 hover:bg-oe-blue/5 hover:text-oe-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                aria-label={t('login.brand_edit', { defaultValue: 'Customize logo' })}
                title={t('login.brand_edit', { defaultValue: 'Customize logo' })}
              >
                <Pencil size={13} strokeWidth={2.25} />
              </button>
            </div>
            <p className="mt-2 text-sm text-content-tertiary">
              {t('login.workspace_tagline', { defaultValue: 'Professional construction project workspace' })}
            </p>
          </div>


          {/* Form - premium multi-layer glass.
              login-glass-pro adds layered borders, a coloured ambient drop
              shadow, an inset highlight, and a soft-light overlay tint via
              ::after. The DOM-level top sheen below adds the rim-light line. */}
          <div
            className="login-glass-pro relative rounded-2xl px-6 py-5 animate-form-scale-in"
            style={{ animationDelay: '150ms' }}
          >
            {/* Top-edge sheen - bright highlight along the rim */}
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-6 top-0 h-px rounded-t-2xl"
              style={{
                background:
                  'linear-gradient(90deg, transparent, rgba(255,255,255,0.95), transparent)',
              }}
            />
            {/* Inner soft glow gradient on the top-left corner */}
            <div
              aria-hidden
              className="pointer-events-none absolute top-0 left-0 w-32 h-32 rounded-tl-2xl opacity-60"
              style={{
                background:
                  'radial-gradient(circle at 0% 0%, rgba(255,255,255,0.5), transparent 70%)',
              }}
            />
            {/* Visually hidden h1 for screen readers + a11y tools - visible text uses h2 below */}
            <h1 className="sr-only">{t('auth.login', 'Sign in')}</h1>
            <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
              <h2 className="text-base font-semibold text-content-primary mb-0.5">{t('auth.login', 'Sign in')}</h2>
              <p className="text-xs text-content-secondary mb-4">{t('auth.login_subtitle', 'Enter your credentials to access your workspace')}</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3" aria-label={t('auth.login', 'Sign in')}>
              <div className="animate-stagger-in" style={{ animationDelay: '280ms' }}>
                <Input id="login-email" name="email" label={t('auth.email', 'Email')} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="email" required aria-required="true" autoFocus icon={<Mail size={15} />} />
              </div>

              <div className="flex flex-col gap-1 animate-stagger-in" style={{ animationDelay: '340ms' }}>
                <div className="flex items-center justify-between">
                  <label htmlFor="login-password" className="text-sm font-medium text-content-primary">{t('auth.password', 'Password')}</label>
                  <Link to="/forgot-password" className="text-2xs font-medium text-oe-blue hover:text-oe-blue-hover transition-colors">{t('auth.forgot_password', 'Forgot password?')}</Link>
                </div>
                <div className="relative">
                  <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary"><Lock size={15} /></div>
                  <input id="login-password" name="password" type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={t('auth.password_placeholder', 'Enter your password')} autoComplete="current-password" required aria-required="true" minLength={8} className="h-9 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-9 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary" />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? t('auth.hide_password', 'Hide password') : t('auth.show_password', 'Show password')} className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary hover:text-content-secondary transition-colors" tabIndex={-1}>
                    {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </div>

              <div className="animate-stagger-in" style={{ animationDelay: '380ms' }}>
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input type="checkbox" checked={rememberMe} onChange={(e) => setRememberMe(e.target.checked)} className="h-3.5 w-3.5 rounded border-border text-oe-blue focus:ring-oe-blue accent-oe-blue" />
                  <span className="text-xs text-content-secondary">{t('auth.remember_me', 'Remember me for 30 days')}</span>
                </label>
              </div>

              {error && (
                <div
                  data-testid="login-error"
                  className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error animate-stagger-in"
                >
                  <span className="shrink-0 mt-0.5">!</span><span>{error}</span>
                </div>
              )}

              <div className="animate-stagger-in" style={{ animationDelay: '400ms' }}>
                <Button type="submit" variant="primary" size="lg" loading={loading} className="w-full btn-shimmer">{t('auth.login', 'Sign in')}</Button>
              </div>
            </form>

            <div className="mt-4 border-t border-border-light pt-3.5 animate-stagger-in" style={{ animationDelay: '460ms' }}>
              <p className="text-center text-xs text-content-secondary">
                {t('auth.no_account', "Don't have an account?")}{' '}
                <Link to="/register" className="font-medium text-oe-blue hover:text-oe-blue-hover transition-colors">{t('auth.create_account', 'Create account')}</Link>
              </p>
            </div>
          </div>


          <div className="lg:hidden mt-2 text-center text-2xs text-content-quaternary">
            <a href="/api/source" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">AGPL-3.0</a>
          </div>
          {/* Running build version - always visible so it's obvious which
              version is live on a fresh open. Matches the Sidebar / About
              treatment (v{APP_VERSION}). */}
          <div className="mt-3 text-center text-2xs font-mono text-content-quaternary/80 tabular-nums">
            v{APP_VERSION}
          </div>
        </div>
      </div>

      {/* ── White-label branding editor (pre-auth) ── */}
      {brandOpen && <BrandingEditorModal onClose={() => setBrandOpen(false)} />}

    </div>
  );
}
