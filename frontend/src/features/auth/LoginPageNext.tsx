// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Experimental login page — v3.
 *
 * Left half: aurora + cursor spotlight under a grid of module tiles
 * (mirrors the dashboard's module visualisation — same Lucide icons,
 * same colour language, same icon-on-coloured-square pattern).
 *
 * Right half: clean white form pane — solid background for max
 * readability. No rotating ring, no glass on the form itself.
 *
 * Mounted at /login-next so /login stays untouched while we iterate.
 */
import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import {
  Eye, EyeOff, Mail, Lock, Globe, ChevronDown,
  Table2, Database, Layers, Box, Ruler, Sparkles,
  CalendarDays, ShieldCheck, BrainCircuit, Boxes,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Button, Input, Logo, CountryFlag } from '@/shared/ui';
import { safeNextPath } from './nextPath';
import { useAuthStore } from '@/stores/useAuthStore';
import { extractErrorMessageFromBody } from '@/shared/lib/api';
import { loginFailureKindFromResponse } from './loginError';
import { AuthBackground } from './AuthBackground';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';

interface ModuleTile {
  icon: LucideIcon;
  label: string;
  stat: string;
  hint: string;
  tone: 'blue' | 'violet' | 'emerald' | 'amber' | 'rose' | 'cyan' | 'indigo' | 'teal';
}

const TONE_STYLES: Record<ModuleTile['tone'], { bg: string; fg: string; ring: string }> = {
  blue:    { bg: 'bg-[#007AFF]/12',  fg: 'text-[#007AFF]',  ring: 'ring-[#007AFF]/15' },
  violet:  { bg: 'bg-violet-500/10', fg: 'text-violet-600', ring: 'ring-violet-500/15' },
  emerald: { bg: 'bg-emerald-500/10',fg: 'text-emerald-600',ring: 'ring-emerald-500/15' },
  amber:   { bg: 'bg-amber-500/10',  fg: 'text-amber-600',  ring: 'ring-amber-500/15' },
  rose:    { bg: 'bg-rose-500/10',   fg: 'text-rose-600',   ring: 'ring-rose-500/15' },
  cyan:    { bg: 'bg-cyan-500/10',   fg: 'text-cyan-600',   ring: 'ring-cyan-500/15' },
  indigo:  { bg: 'bg-indigo-500/10', fg: 'text-indigo-600', ring: 'ring-indigo-500/15' },
  teal:    { bg: 'bg-teal-500/10',   fg: 'text-teal-600',   ring: 'ring-teal-500/15' },
};

export function LoginPageNext() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const setTokens = useAuthStore((s) => s.setTokens);
  // Routed at /login-next, so this is a second front door and has to validate
  // the redirect exactly as /login does. It used to carry its own weaker copy
  // of the check, which accepted auth routes and let a backslash authority
  // through. Both doors now share one helper so they cannot drift again.
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
  const langRef = useRef<HTMLDivElement>(null);
  const heroRef = useRef<HTMLDivElement>(null);

  const currentLang =
    SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language) ?? SUPPORTED_LANGUAGES[0]!;

  useEffect(() => {
    setEmail('');
    setPassword('');
    setError('');
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Cursor spotlight — track mouse and write to CSS custom properties on
  // the hero element. The gradient lookup happens inside CSS, so React
  // never re-renders for mouse moves.
  const onHeroMouseMove = useCallback((e: ReactMouseEvent<HTMLDivElement>) => {
    const el = heroRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - rect.left}px`);
    el.style.setProperty('--my', `${e.clientY - rect.top}px`);
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
        // Same reasoning as the other sign-in screen: a 5xx, and equally a 4xx
        // with no message in it, means nothing read the password, so the
        // credentials wording would be a claim we cannot support.
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

  // Module tiles — first-run / empty-state view. New users haven't
  // imported anything yet, so each tile shows an em-dash for the stat
  // and an onboarding cue for the hint instead of fake metrics.
  const modules: ModuleTile[] = [
    { icon: Table2,       label: t('nav.boq', 'Bill of Quantities'), stat: '—', hint: t('login.zero_boq', 'create first BOQ'),       tone: 'blue' },
    { icon: Database,     label: t('nav.costs', 'Cost Database'),    stat: '—', hint: t('login.zero_costs', 'import to start'),       tone: 'cyan' },
    { icon: Layers,       label: t('nav.assemblies', 'Assemblies'),  stat: '—', hint: t('login.zero_assemblies', 'no recipes yet'),    tone: 'violet' },
    { icon: Boxes,        label: t('nav.catalog', 'Catalog'),        stat: '—', hint: t('login.zero_catalog', 'add resources'),       tone: 'indigo' },
    { icon: Ruler,        label: t('nav.takeoff', 'PDF Takeoff'),    stat: '—', hint: t('login.zero_takeoff', 'upload a drawing'),    tone: 'amber' },
    { icon: Box,          label: t('nav.bim', 'BIM Viewer'),         stat: '—', hint: t('login.zero_bim', 'no models yet'),           tone: 'teal' },
    { icon: Sparkles,     label: t('nav.ai_estimate', 'AI Estimate'), stat: t('login.zero_ai', 'Ready'), hint: t('login.zero_ai_hint', 'BETA'), tone: 'rose' },
    { icon: BrainCircuit, label: t('nav.intelligence', 'Project IQ'), stat: '—', hint: t('login.zero_iq', 'awaiting data'),            tone: 'violet' },
    { icon: CalendarDays, label: t('nav.schedule', '4D Schedule'),    stat: '—', hint: t('login.zero_schedule', 'no tasks'),           tone: 'cyan' },
    { icon: ShieldCheck,  label: t('nav.validation', 'Validation'),   stat: '—', hint: t('login.zero_validation', 'run checks'),      tone: 'emerald' },
  ];

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-surface-secondary">
      {/* Original BIM cost-table background — sits at the bottom layer
          and shows through the aurora at low opacity on the left only. */}
      <AuthBackground />

      {/* Page-scoped CSS — keeps this experimental page self-contained. */}
      <style>{`
        @keyframes oeAuroraSpin {
          0%   { transform: translate(-50%, -50%) rotate(0deg); }
          100% { transform: translate(-50%, -50%) rotate(360deg); }
        }
        @keyframes oeFloat {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(-5px); }
        }
        @keyframes oeShimmer {
          0%   { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes oeRingPulse {
          0%   { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.50); }
          70%  { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
          100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }

        /* Sky base - very pale, near-white blue. Reads as a bright
           daylight horizon, not a saturated marketing hero. */
        .oe-hero {
          background:
            radial-gradient(120% 90% at 20% 10%,  rgba(224, 242, 254, 0.65) 0%, transparent 60%),
            radial-gradient(110% 80% at 80% 90%,  rgba(219, 234, 254, 0.55) 0%, transparent 60%),
            linear-gradient(160deg, #f8fcff 0%, #f0f9ff 45%, #eaf4ff 100%);
        }
        .dark .oe-hero {
          background:
            radial-gradient(120% 90% at 20% 10%,  rgba(30, 64, 175, 0.45) 0%, transparent 60%),
            radial-gradient(110% 80% at 80% 90%,  rgba(14, 116, 144, 0.45) 0%, transparent 60%),
            linear-gradient(160deg, #0c1929 0%, #0a1628 45%, #061021 100%);
        }

        /* Aurora - soft sky/cyan tint, low opacity so the surface
           stays light and the module tiles read clearly. */
        .oe-aurora {
          position: absolute;
          inset: 0;
          overflow: hidden;
          pointer-events: none;
        }
        .oe-aurora::before,
        .oe-aurora::after,
        .oe-aurora > .oe-aurora-c {
          content: "";
          position: absolute;
          left: 50%;
          top: 50%;
          width: 160vmax;
          height: 160vmax;
          border-radius: 50%;
          filter: blur(80px);
          opacity: 0.40;
          mix-blend-mode: multiply;
          pointer-events: none;
        }
        .dark .oe-aurora::before,
        .dark .oe-aurora::after,
        .dark .oe-aurora > .oe-aurora-c {
          mix-blend-mode: screen;
          opacity: 0.55;
        }
        /* sky-300 - light daylight sky, gentle */
        .oe-aurora::before {
          background: conic-gradient(from 0deg,
            rgba(125, 211, 252, 0.55),
            rgba(186, 230, 253, 0.0),
            rgba(125, 211, 252, 0.0),
            rgba(125, 211, 252, 0.55));
          animation: oeAuroraSpin 38s linear infinite;
        }
        /* cyan-200 - paler haze */
        .oe-aurora::after {
          background: conic-gradient(from 90deg,
            rgba(165, 243, 252, 0.50),
            rgba(125, 211, 252, 0.0),
            rgba(165, 243, 252, 0.0),
            rgba(165, 243, 252, 0.50));
          animation: oeAuroraSpin 52s linear infinite reverse;
        }
        /* blue-200 - soft cloud */
        .oe-aurora > .oe-aurora-c {
          background: conic-gradient(from 200deg,
            rgba(191, 219, 254, 0.50),
            rgba(186, 230, 253, 0.0),
            rgba(191, 219, 254, 0.0),
            rgba(191, 219, 254, 0.50));
          animation: oeAuroraSpin 64s linear infinite;
        }

        /* Mouse spotlight - only renders if --mx/--my are set. */
        .oe-spot {
          position: absolute;
          inset: 0;
          pointer-events: none;
          background: radial-gradient(420px circle at var(--mx, 50%) var(--my, 50%),
            rgba(255, 255, 255, 0.40),
            transparent 60%);
          mix-blend-mode: soft-light;
          opacity: 0.95;
          transition: background 0.05s linear;
        }

        /* Glass module tiles. */
        .oe-tile {
          background:
            linear-gradient(135deg, rgba(255,255,255,0.62) 0%, rgba(255,255,255,0.34) 100%);
          backdrop-filter: blur(22px) saturate(170%);
          -webkit-backdrop-filter: blur(22px) saturate(170%);
          border: 1px solid rgba(255,255,255,0.55);
          box-shadow:
            0 14px 40px -16px rgba(20, 20, 40, 0.18),
            inset 0 1px 0 rgba(255, 255, 255, 0.65);
          transition:
            transform 0.35s cubic-bezier(0.2, 0.8, 0.2, 1),
            box-shadow 0.35s cubic-bezier(0.2, 0.8, 0.2, 1),
            border-color 0.35s ease;
        }
        .dark .oe-tile {
          background:
            linear-gradient(135deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0.03) 100%);
          border-color: rgba(255,255,255,0.10);
          box-shadow:
            0 14px 40px -16px rgba(0, 0, 0, 0.55),
            inset 0 1px 0 rgba(255, 255, 255, 0.08);
        }
        .oe-tile:hover {
          transform: translateY(-3px);
          border-color: rgba(0, 122, 255, 0.35);
          box-shadow:
            0 22px 50px -18px rgba(0, 90, 210, 0.30),
            inset 0 1px 0 rgba(255, 255, 255, 0.8);
        }

        /* Lite glass for demo accounts (right side stays solid white,
           but the demo tiles need a touch of glass over the white). */
        .oe-glass-lite {
          background:
            linear-gradient(135deg, rgba(248,250,252,0.95) 0%, rgba(241,245,249,0.85) 100%);
          border: 1px solid rgba(15,23,42,0.06);
          box-shadow:
            0 4px 12px -4px rgba(20, 20, 40, 0.06),
            inset 0 1px 0 rgba(255, 255, 255, 0.9);
        }
        .dark .oe-glass-lite {
          background:
            linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%);
          border-color: rgba(255,255,255,0.08);
        }

        /* Tiny live-pulse dot. */
        .oe-pulse {
          position: relative;
        }
        .oe-pulse::after {
          content: "";
          position: absolute;
          inset: 0;
          border-radius: inherit;
          animation: oeRingPulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }

        /* Animated spectrum bar - sky-only palette. */
        .oe-spec-bar {
          background: linear-gradient(90deg,
            rgba(2,132,199,0.95), rgba(14,165,233,0.95), rgba(56,189,248,0.95),
            rgba(2,132,199,0.95));
          background-size: 300% 100%;
          animation: oeShimmer 6s linear infinite;
        }

        .oe-tile-float-a { animation: oeFloat 7s ease-in-out infinite; }
        .oe-tile-float-b { animation: oeFloat 8.5s ease-in-out infinite 1.2s; }

        /* Form pane - solid white, soft shadow, NOT glass. The whole
           right column reads as a clean, paper-white panel for max
           form readability. */
        .oe-form-pane {
          background: #ffffff;
          border: 1px solid rgba(15, 23, 42, 0.06);
          box-shadow:
            0 30px 60px -30px rgba(20, 20, 40, 0.18),
            0 1px 0 rgba(255, 255, 255, 1) inset;
        }
        .dark .oe-form-pane {
          background: #0f172a;
          border-color: rgba(255, 255, 255, 0.06);
          box-shadow:
            0 30px 60px -30px rgba(0, 0, 0, 0.6),
            0 1px 0 rgba(255, 255, 255, 0.04) inset;
        }

        /* Typography - Plus Jakarta Sans for everything, Instrument
           Serif for the editorial headline accent. */
        .oe-font-display {
          font-family: 'Plus Jakarta Sans', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
          font-feature-settings: 'cv11', 'ss01', 'ss03';
          font-variant-numeric: tabular-nums;
        }
        .oe-font-serif {
          font-family: 'Instrument Serif', 'Iowan Old Style', 'Apple Garamond', Georgia, serif;
          font-feature-settings: 'liga', 'dlig';
          letter-spacing: -0.01em;
        }
      `}</style>

      {/* Preview badge — top-left so users know this is /login-next. */}
      <div className="absolute top-4 left-4 z-30">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/40 bg-white/60 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-content-secondary backdrop-blur-md dark:border-white/10 dark:bg-white/10 dark:text-white/70">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
          </span>
          Preview · /login-next
        </span>
      </div>

      {/* Language switcher */}
      <div className="absolute top-4 right-4 z-30" ref={langRef}>
        <button
          onClick={() => setLangOpen(!langOpen)}
          className="flex items-center gap-2 rounded-xl border border-border-light bg-surface-primary px-3.5 py-2.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary hover:border-oe-blue/30 transition-all shadow-sm"
        >
          <Globe size={15} className="text-content-tertiary" />
          <CountryFlag code={currentLang.country} size={18} />
          <span className="hidden sm:inline">{currentLang.name}</span>
          <ChevronDown size={14} className={`text-content-tertiary transition-transform ${langOpen ? 'rotate-180' : ''}`} />
        </button>
        {langOpen && (
          <div className="absolute right-0 mt-2 w-56 max-h-80 overflow-y-auto rounded-xl border border-border-light bg-surface-elevated shadow-xl py-1 animate-stagger-in">
            {SUPPORTED_LANGUAGES.map((lang) => {
              const isActive = i18n.language === lang.code;
              return (
                <button
                  key={lang.code}
                  onClick={() => { i18n.changeLanguage(lang.code); setLangOpen(false); }}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-sm transition-colors ${isActive ? 'bg-oe-blue/10 text-oe-blue font-medium' : 'text-content-primary hover:bg-surface-secondary'}`}
                >
                  <CountryFlag code={lang.country} size={16} />
                  <span className="truncate">{lang.name}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="relative z-10 grid min-h-screen grid-cols-1 lg:grid-cols-2">
        {/* ── LEFT: hero + module tiles grid ──────────────────────────── */}
        <div
          ref={heroRef}
          onMouseMove={onHeroMouseMove}
          className="oe-hero relative hidden lg:flex flex-col justify-center overflow-hidden px-12 xl:px-20 py-14"
        >
          {/* Aurora + spotlight stack — left side only. */}
          <div className="oe-aurora" aria-hidden>
            <div className="oe-aurora-c" />
          </div>
          <div className="oe-spot" aria-hidden />

          {/* Eyebrow */}
          <div className="oe-font-display relative mb-5 inline-flex w-fit items-center gap-2 rounded-full border border-white/60 bg-white/70 px-3 py-1 text-[11px] font-semibold tracking-[0.08em] uppercase text-content-secondary backdrop-blur-md dark:border-white/10 dark:bg-white/10 dark:text-white/80">
            <span className="oe-pulse relative flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
            <span>{t('login.welcome_eyebrow', 'First-time setup')}</span>
          </div>

          {/* Headline */}
          <h1 className="oe-font-display relative max-w-[640px] text-[46px] xl:text-[60px] leading-[0.95] font-extrabold tracking-[-0.04em] text-content-primary dark:text-white">
            {t('login.welcome_h_a', 'A clean slate,')}{' '}
            <span className="relative inline-block">
              <span className="oe-font-serif italic font-normal bg-gradient-to-r from-[#0284c7] via-[#0ea5e9] to-[#38bdf8] bg-clip-text text-transparent">
                {t('login.welcome_h_b', 'ready to build.')}
              </span>
              <span className="absolute -inset-x-2 -bottom-1 -z-10 h-[14px] rounded-full bg-gradient-to-r from-[#0284c7]/25 via-[#0ea5e9]/25 to-[#38bdf8]/25 blur-xl" />
            </span>
          </h1>

          <p className="oe-font-display relative mt-5 max-w-[480px] text-[15px] leading-[1.6] text-content-secondary dark:text-white/65">
            {t('login.welcome_sub_modules', 'Sign in to unlock every module - your workspace is empty until you import or create.')}
          </p>

          {/* Module tiles grid — same icon language as the dashboard
              and sidebar. Five columns at xl, four at lg. */}
          <div className="relative mt-9 grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-5 gap-3 max-w-[680px]">
            {modules.map((m, i) => {
              const tone = TONE_STYLES[m.tone];
              const Icon = m.icon;
              const floatClass = i % 3 === 0 ? 'oe-tile-float-a' : i % 3 === 1 ? 'oe-tile-float-b' : '';
              return (
                <div
                  key={m.label}
                  className={`oe-tile oe-font-display ${floatClass} rounded-2xl p-3.5 animate-stagger-in`}
                  style={{ animationDelay: `${80 + i * 40}ms` }}
                >
                  <div className={`flex h-9 w-9 items-center justify-center rounded-xl ring-1 ${tone.bg} ${tone.fg} ${tone.ring}`}>
                    <Icon size={16} strokeWidth={1.8} />
                  </div>
                  <div className="mt-2.5 text-[12px] font-semibold leading-tight text-content-primary dark:text-white">
                    {m.label}
                  </div>
                  <div className="mt-1 flex items-baseline gap-1.5">
                    <span className={`text-[18px] font-extrabold tracking-tight leading-none ${m.stat === '—' ? 'text-content-quaternary/60' : 'text-content-primary dark:text-white'}`}>
                      {m.stat}
                    </span>
                    <span className="text-[10px] uppercase tracking-[0.08em] font-medium text-content-tertiary">
                      {m.hint}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="oe-font-display relative mt-7 flex items-center gap-3 text-[11px] font-medium text-content-tertiary">
            <div className="oe-spec-bar h-[2px] w-12 rounded-full" />
            <span>{t('login.workspace_status_first', 'Empty workspace - sign in to set up your first project')}</span>
          </div>

          {/* Copyright — left-bottom, sits below the hero content. */}
          <div className="relative mt-auto pt-10 text-[11px] text-content-tertiary/80 dark:text-white/40">
            © 2026{' '}
            <a
              href="https://www.linkedin.com/in/boikoartem/"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-content-secondary hover:text-oe-blue transition-colors dark:text-white/70 dark:hover:text-oe-blue"
            >
              Artem Boiko
            </a>{' '}
            · OpenConstructionERP
            · <a href="mailto:info@datadrivenconstruction.io" className="hover:text-content-secondary transition-colors">info@datadrivenconstruction.io</a>
          </div>
        </div>

        {/* ── RIGHT: clean white form pane ─────────────────────────────── */}
        <div className="flex items-center justify-center px-5 py-10 sm:px-10 relative z-10">
          <div className="oe-form-pane w-full max-w-[420px] rounded-[24px]">
            <div className="rounded-[24px] p-7 sm:p-9">
              {/* Mobile-only logo */}
              <div className="lg:hidden mb-6 flex flex-col items-center">
                <Logo size="md" animate />
                <span
                  className="mt-2.5 text-xl font-medium tracking-[-0.02em] text-content-primary dark:text-white"
                  style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif" }}
                >
                  Open<span className="text-oe-blue">Construction</span><span className="text-content-quaternary">ERP</span>
                </span>
              </div>

              {/* Brand row (desktop) */}
              <div className="hidden lg:flex items-center gap-2.5 mb-7">
                <Logo size="sm" animate />
                <span
                  className="text-[15px] font-medium tracking-[-0.02em] text-content-primary dark:text-white"
                  style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif" }}
                >
                  Open<span className="text-oe-blue">Construction</span><span className="text-content-quaternary dark:text-white/50">ERP</span>
                </span>
              </div>

              {/* Headline */}
              <div className="animate-stagger-in" style={{ animationDelay: '60ms' }}>
                <h2 className="oe-font-display text-[28px] font-bold tracking-[-0.025em] text-content-primary dark:text-white">
                  {t('auth.welcome_back', 'Welcome back')}
                </h2>
                <p className="oe-font-display mt-1.5 text-sm text-content-secondary dark:text-white/60">
                  {t('auth.login_subtitle', 'Sign in to your workspace')}
                </p>
              </div>

              <form
                onSubmit={handleSubmit}
                className="mt-7 space-y-3.5 animate-stagger-in"
                style={{ animationDelay: '160ms' }}
                aria-label={t('auth.login', 'Sign in')}
              >
                <Input
                  id="login-email-next"
                  name="email"
                  label={t('auth.email', 'Email')}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  autoComplete="email"
                  required aria-required="true"
                  autoFocus
                  icon={<Mail size={15} />}
                />

                <div className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <label htmlFor="login-password-next" className="text-sm font-medium text-content-primary dark:text-white">
                      {t('auth.password', 'Password')}
                    </label>
                    <Link
                      to="/forgot-password"
                      className="text-2xs font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
                    >
                      {t('auth.forgot_password', 'Forgot password?')}
                    </Link>
                  </div>
                  <div className="relative">
                    <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
                      <Lock size={15} />
                    </div>
                    <input
                      id="login-password-next"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={t('auth.password_placeholder', 'Enter your password')}
                      autoComplete="current-password"
                      required aria-required="true"
                      minLength={8}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-9 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      aria-label={showPassword ? t('auth.hide_password', 'Hide password') : t('auth.show_password', 'Show password')}
                      className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary hover:text-content-secondary transition-colors"
                      tabIndex={-1}
                    >
                      {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                  </div>
                </div>

                <label className="flex items-center gap-2 cursor-pointer select-none pt-1">
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    className="h-3.5 w-3.5 rounded border-border text-oe-blue focus:ring-oe-blue accent-oe-blue"
                  />
                  <span className="text-xs text-content-secondary dark:text-white/60">
                    {t('auth.remember_me', 'Remember me for 30 days')}
                  </span>
                </label>

                {error && (
                  <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error animate-stagger-in">
                    <span className="shrink-0 mt-0.5">!</span>
                    <span>{error}</span>
                  </div>
                )}

                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  loading={loading}
                  className="w-full btn-shimmer"
                >
                  {t('auth.login', 'Sign in')}
                </Button>
              </form>

              {/* Footer */}
              <div className="mt-7 animate-stagger-in" style={{ animationDelay: '340ms' }}>
                <p className="text-center text-xs text-content-secondary dark:text-white/60">
                  {t('auth.no_account', "Don't have an account?")}{' '}
                  <Link
                    to="/register"
                    className="font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
                  >
                    {t('auth.create_account', 'Create account')}
                  </Link>
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
