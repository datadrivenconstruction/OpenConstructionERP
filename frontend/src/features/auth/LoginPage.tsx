import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import {
  Eye, EyeOff, Mail, Lock, Globe, ChevronDown, Info, X,
  ShieldCheck, Zap, Brain,
  FileSpreadsheet, CalendarClock, TrendingUp, Boxes, Database,
  BarChart3, Upload, FileCheck,
  Box, Ruler, Layers,
  PenTool, FolderOpen, ClipboardList,
} from 'lucide-react';
import { Button, Input, Logo, LogoWithText, CountryFlag } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { extractErrorMessageFromBody } from '@/shared/lib/api';
import { AuthBackground } from './AuthBackground';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';

export function LoginPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const setTokens = useAuthStore((s) => s.setTokens);
  // `?next=/path` lets guarded routes send the user back to where they wanted
  // to go after login. Falls back to `/` for direct visits.
  const nextPath = (() => {
    try {
      const params = new URLSearchParams(location.search);
      const next = params.get('next');
      if (next && next.startsWith('/') && !next.startsWith('//')) return next;
    } catch { /* ignore */ }
    return '/';
  })();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [rememberMe, setRememberMe] = useState(
    () => localStorage.getItem('oe_remember') === '1',
  );
  const [langOpen, setLangOpen] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [demoOpen, setDemoOpen] = useState(true);
  const [demoLoading, setDemoLoading] = useState<string | null>(null);
  const langRef = useRef<HTMLDivElement>(null);

  const currentLang =
    SUPPORTED_LANGUAGES.find((l) => l.code === i18n.language) ?? SUPPORTED_LANGUAGES[0]!;

  // Clear form on mount (prevents pre-fill after logout)
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
        const data = await res.json().catch(() => null);
        const parsed = extractErrorMessageFromBody(data);
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

  const demoAccounts = [
    { email: 'demo@openestimator.io', name: 'Admin', role: t('auth.demo_role_admin', 'Administrator'), color: 'bg-blue-500', letter: 'A' },
    { email: 'estimator@openestimator.io', name: 'Сарнай Бат', role: t('auth.demo_role_estimator', 'Estimator'), color: 'bg-emerald-500', letter: 'S' },
    { email: 'manager@openestimator.io', name: 'Thomas Müller', role: t('auth.demo_role_manager', 'Manager'), color: 'bg-amber-500', letter: 'M' },
  ];

  const handleDemoLogin = async (demoEmail: string) => {
    setDemoLoading(demoEmail);
    setError('');
    setEmail('');
    setPassword('');
    try {
      // Use the dedicated demo-login endpoint (v2.6.22) which mints tokens
      // for seeded demo accounts without a password — necessary because the
      // backend seeder generates a fresh `secrets.token_urlsafe(16)` per
      // install (BUG-D01) and the frontend has no way to read it.
      let res = await fetch('/api/v1/users/auth/demo-login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: demoEmail }),
      });

      // Fallback path: if the server is older than v2.6.22 it returns 404
      // for /demo-login/. Try the legacy login + auto-register pair so
      // existing deployments don't break the moment we ship the new client.
      if (res.status === 404) {
        res = await fetch('/api/v1/users/auth/login/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: demoEmail, password: 'DemoPass1234!' }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => null);
          const parsedMsg = extractErrorMessageFromBody(errData) ?? '';
          if (
            parsedMsg.includes('Invalid') ||
            parsedMsg.includes('not found') ||
            res.status === 401
          ) {
            const regRes = await fetch('/api/v1/users/auth/register/', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                email: demoEmail,
                password: 'DemoPass1234!',
                full_name: (demoEmail.split('@')[0] ?? 'Demo User')
                  .replace(/[._]/g, ' ')
                  .replace(/\b\w/g, (c) => c.toUpperCase()),
              }),
            });
            if (regRes.ok) {
              res = await fetch('/api/v1/users/auth/login/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: demoEmail, password: 'DemoPass1234!' }),
              });
            }
          }
        }
      }

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const parsed = extractErrorMessageFromBody(data);
        setError(parsed || t('auth.demo_login_failed', 'Demo login failed. Please try again.'));
        return;
      }
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token, false, demoEmail);
      navigate(nextPath, { replace: true });
    } catch {
      setError(t('auth.connection_error', 'Unable to connect to server. Please try again.'));
    } finally {
      setDemoLoading(null);
    }
  };

  /* Benefits list — reserved for future hero section layout
  const benefits = [
    { icon: HardDrive, color: 'text-emerald-500 bg-emerald-500/10', title: t('login.benefit.local', 'Your data stays on your computer'), desc: t('login.benefit.local_desc', 'No cloud. No third-party servers. Full control.') },
    { icon: ShieldCheck, color: 'text-blue-500 bg-blue-500/10', title: t('login.benefit.open_source', '100% open source'), desc: t('login.benefit.open_source_desc', 'Transparent code. No vendor lock-in.') },
    { icon: Globe2, color: 'text-violet-500 bg-violet-500/10', title: t('login.benefit.standards', 'International standards'), desc: t('login.benefit.standards_desc', '55,000+ cost items across 11 regional databases worldwide.') },
    { icon: Brain, color: 'text-amber-500 bg-amber-500/10', title: t('login.benefit.ai', 'AI-assisted estimation'), desc: t('login.benefit.ai_desc', 'Smart suggestions. You decide, AI assists.') },
    { icon: Zap, color: 'text-rose-500 bg-rose-500/10', title: t('login.benefit.allinone', 'BOQ + 4D + 5D + Tendering'), desc: t('login.benefit.allinone_desc', 'Full workflow in one tool.') },
    { icon: Users, color: 'text-cyan-500 bg-cyan-500/10', title: t('login.benefit.free', 'Free for everyone'), desc: t('login.benefit.free_desc', 'No fees. No limits. By estimators.') },
  ]; */

  return (
    <div className="relative grid h-screen grid-cols-1 lg:grid-cols-2 bg-surface-secondary overflow-hidden">
      <AuthBackground />

      {/* Local style block — premium glass variant + drifting orb keyframes
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
          border-color: rgba(255, 255, 255, 0.08);
          box-shadow:
            0 30px 80px -24px rgba(14, 165, 233, 0.35),
            0 12px 40px -12px rgba(0, 0, 0, 0.55),
            0 2px 6px -2px rgba(0, 0, 0, 0.4),
            inset 0 1px 0 rgba(255, 255, 255, 0.12),
            inset 0 0 0 1px rgba(255, 255, 255, 0.04);
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
          Restrained palette — single faint sky blob behind the marketing
          column so the headline / stats sit on a near-white field.
          Dark mode keeps the original richer blob set for depth. */}
      <div className="absolute inset-y-0 left-0 right-1/2 z-0 pointer-events-none overflow-hidden hidden lg:block">
        <div className="absolute top-[-12%] left-[-6%] w-[520px] h-[520px] rounded-full bg-sky-300/10 dark:bg-oe-blue/35 blur-[120px] animate-blob-slow-1 mix-blend-screen" />
        <div className="absolute bottom-[-18%] right-[2%] w-[400px] h-[400px] rounded-full bg-cyan-200/8 dark:bg-violet-500/35 blur-[110px] animate-blob-slow-4 mix-blend-screen hidden dark:block" />
      </div>

      {/* Mobile-only ambient blobs (single column layout) */}
      <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden lg:hidden">
        <div className="absolute top-[-12%] left-[-6%] w-[520px] h-[520px] rounded-full bg-sky-300/12 dark:bg-oe-blue/35 blur-[110px] animate-blob-slow-1 mix-blend-screen" />
      </div>

      {/* Language — top right (enlarged for /login so it's discoverable). */}
      <div className="absolute top-4 right-4 z-30" ref={langRef}>
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
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-sm transition-colors ${isActive ? 'bg-oe-blue/8 text-oe-blue font-medium' : 'text-content-primary hover:bg-surface-secondary'}`}
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

      {/* ── Right column on lg+: marketing & benefits.
          Order swap (lg:order-2) puts the form on the left so it's the
          first thing the eye lands on — primary action priority. */}
      <div className="hidden lg:flex relative z-10 lg:order-2 flex-col justify-center pl-14 xl:pl-20 pr-12 xl:pr-16 py-6 overflow-hidden">
        {/* Marketing column showcase — color lives here. Sky/cyan mesh +
            slow-drifting orbs + faint noise grain. The form column on the
            left stays a clean white field; this column carries the visual
            weight. */}
        <div className="absolute inset-0 pointer-events-none -z-10" aria-hidden>
          <div
            className="absolute inset-0"
            style={{
              background:
                'radial-gradient(ellipse 90% 70% at 70% 25%, rgba(14,165,233,0.16), transparent 65%),' +
                'radial-gradient(ellipse 80% 60% at 25% 85%, rgba(56,189,248,0.12), transparent 65%),' +
                'radial-gradient(ellipse 60% 50% at 90% 75%, rgba(125,211,252,0.10), transparent 65%)',
            }}
          />
          <div
            className="absolute inset-0 hidden dark:block"
            style={{
              background:
                'radial-gradient(ellipse 80% 60% at 70% 20%, rgba(14,165,233,0.22), transparent 60%),' +
                'radial-gradient(ellipse 70% 60% at 30% 90%, rgba(139,92,246,0.18), transparent 60%)',
            }}
          />
          <div className="absolute top-[8%] right-[8%] w-[420px] h-[420px] rounded-full bg-sky-300/45 dark:bg-sky-500/35 blur-[100px] login-orb-a" />
          <div className="absolute bottom-[6%] left-[10%] w-[360px] h-[360px] rounded-full bg-cyan-200/40 dark:bg-violet-500/30 blur-[100px] login-orb-b" />
          <div className="absolute top-[42%] right-[34%] w-[280px] h-[280px] rounded-full bg-white/55 dark:bg-white/0 blur-[80px] login-orb-c" />
          <div
            className="absolute inset-0 opacity-[0.04] dark:opacity-[0.07] mix-blend-overlay"
            style={{
              backgroundImage:
                "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.5 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")",
            }}
          />
        </div>

        {/* Eyebrow pill */}
        <div className="mb-5 animate-stagger-in" style={{ animationDelay: '0ms' }}>
          <span className="inline-flex items-center gap-2 rounded-full bg-emerald-500/[0.08] dark:bg-emerald-400/[0.1] px-3.5 py-1.5">
            <span className="relative flex h-[6px] w-[6px]">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex rounded-full h-[6px] w-[6px] bg-emerald-500" />
            </span>
            <span className="text-[11px] font-medium tracking-[0.04em] text-emerald-700 dark:text-emerald-300">{t('login.open_source_label', { defaultValue: 'Open Source' })}</span>
          </span>
        </div>

        {/* Marketing headline — kept as h2 because the form panel below has the
            authoritative h1 (visually hidden, always present in DOM). */}
        <h2 className="text-[32px] xl:text-[36px] font-semibold text-content-primary leading-[1.08] tracking-[-0.025em] animate-stagger-in" style={{ animationDelay: '60ms' }}>
          {t('login.hero_h_a', { defaultValue: 'The' })}{' '}
          <span className="bg-gradient-to-r from-oe-blue to-sky-500 bg-clip-text text-transparent">#1</span>{' '}
          {t('login.hero_h_b', { defaultValue: 'open-source workspace for' })}{' '}
          <span className="bg-gradient-to-r from-oe-blue to-sky-500 bg-clip-text text-transparent">
            {t('login.hero_h_c', { defaultValue: 'construction project management' })}
          </span>
        </h2>

        {/* Subhead */}
        <p className="mt-5 text-[17px] text-content-secondary/70 leading-[1.65] tracking-[-0.008em] max-w-[420px] animate-stagger-in" style={{ animationDelay: '120ms' }}>
          {t('login.hero_desc', { defaultValue: 'Plan, estimate, schedule, tender — every step of a project on one professional platform.' })}
        </p>

        {/* Stats row */}
        <div className="mt-5 flex items-center gap-5 animate-stagger-in" style={{ animationDelay: '180ms' }}>
          {[
            { value: '55K+', label: t('login.stat_costs', { defaultValue: 'cost items‌⁠‍' }) },
            { value: '20', label: t('login.stat_langs', { defaultValue: 'languages‌⁠‍' }) },
            { value: '30', label: t('login.stat_regions', { defaultValue: 'regions‌⁠‍' }) },
            { value: '4', label: t('login.stat_cad', { defaultValue: 'CAD formats‌⁠‍' }) },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <div className="text-[22px] font-semibold text-content-primary tracking-tight">{s.value}</div>
              <div className="text-[11px] text-content-tertiary mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Divider */}
        <div className="mt-5 mb-4 h-px bg-gradient-to-r from-content-primary/[0.06] via-content-primary/[0.1] to-transparent animate-stagger-in" style={{ animationDelay: '220ms' }} />

        {/* Module honeycomb — proper pointy-top hex grid where every cell
            shares an edge with its neighbours. Layout is intentionally
            wider on the top/bottom rows (6 cells) than on the middle
            row (5 cells) so it reads as a real, naturally-extending
            honeycomb. Every cell is a real module — no decorative
            placeholders. Math:
              hex width   = 88px (left vertex to right vertex)
              hex height  = 100px (top vertex to bottom vertex)
              row stride  = 75px (3/4 of height — pointy-top step)
              column step = 88px (one hex width on the same row)
              alternating rows are offset by 44px (half a hex) — that's
              what makes the slanted edges meet exactly. */}
        <div className="relative mt-1 mr-auto h-[280px] w-[560px] max-w-full overflow-hidden animate-stagger-in" style={{ animationDelay: '260ms' }}>
          {([
            // Top row (y = -75) — 6 cells, offset by 44.
            { x: -220, y: -75, icon: ShieldCheck,     label: t('login.mod.local',     { defaultValue: 'Local' }) },
            { x: -132, y: -75, icon: Brain,           label: t('login.mod.ai',       { defaultValue: 'AI' }) },
            { x:  -44, y: -75, icon: Ruler,           label: t('login.mod.takeoff',  { defaultValue: 'Takeoff' }) },
            { x:   44, y: -75, icon: PenTool,         label: t('login.mod.cad',      { defaultValue: 'CAD' }) },
            { x:  132, y: -75, icon: Box,             label: t('login.mod.bim',      { defaultValue: 'BIM' }) },
            { x:  220, y: -75, icon: TrendingUp,      label: t('login.mod.cost5d',   { defaultValue: '5D' }) },
            // Mid row (y = 0) — 5 cells aligned on the same axis.
            { x: -176, y:  0,  icon: Database,        label: t('login.mod.costs',    { defaultValue: 'Costs' }) },
            { x:  -88, y:  0,  icon: FileSpreadsheet, label: t('login.mod.boq',      { defaultValue: 'BOQ' }) },
            { x:    0, y:  0,  icon: Layers,          label: t('login.mod.core',     { defaultValue: 'Workspace' }), accent: true },
            { x:   88, y:  0,  icon: CalendarClock,   label: t('login.mod.schedule', { defaultValue: 'Schedule' }) },
            { x:  176, y:  0,  icon: BarChart3,       label: t('login.mod.tender',   { defaultValue: 'Tendering' }) },
            // Bottom row (y = 75) — 6 cells, offset by 44.
            { x: -220, y:  75, icon: Zap,             label: t('login.mod.realtime', { defaultValue: 'Realtime' }) },
            { x: -132, y:  75, icon: Boxes,           label: t('login.mod.resources',{ defaultValue: 'Resources' }) },
            { x:  -44, y:  75, icon: ClipboardList,   label: t('login.mod.tasks',    { defaultValue: 'Tasks' }) },
            { x:   44, y:  75, icon: FileCheck,       label: t('login.mod.validate', { defaultValue: 'Validate' }) },
            { x:  132, y:  75, icon: FolderOpen,      label: t('login.mod.files',    { defaultValue: 'Files' }) },
            { x:  220, y:  75, icon: Upload,          label: t('login.mod.exports',  { defaultValue: 'Exports' }) },
          ] as const).map((cell, idx) => {
            const isAccent = 'accent' in cell && cell.accent === true;
            const Icon = cell.icon;
            return (
              // Outer wrapper handles ABSOLUTE POSITIONING only — its
              // transform is the hex-grid offset and must never be
              // overridden by an animation. Animations live on the inner
              // cell so they don't fight with our positioning maths.
              <div
                key={idx}
                className="absolute top-1/2 left-1/2"
                style={{
                  transform: `translate(calc(-50% + ${cell.x}px), calc(-50% + ${cell.y}px))`,
                }}
              >
                <div
                  className={`relative flex flex-col items-center justify-center w-[88px] h-[100px] animate-fade-in transition-transform duration-300 hover:scale-[1.05] ${
                    isAccent ? 'text-white' : 'text-content-primary'
                  }`}
                  style={{
                    animationDelay: `${280 + idx * 35}ms`,
                    animationFillMode: 'both',
                    clipPath: 'polygon(50% 2%, 100% 26%, 100% 74%, 50% 98%, 0% 74%, 0% 26%)',
                    background: isAccent
                      ? 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 65%, #0369a1 100%)'
                      : 'linear-gradient(180deg, rgba(255,255,255,0.97), rgba(244,250,255,0.82))',
                    boxShadow: isAccent
                      ? '0 18px 32px -12px rgba(14,165,233,0.55), inset 0 1px 0 rgba(255,255,255,0.35)'
                      : '0 8px 18px -8px rgba(15,23,42,0.10), inset 0 1px 0 rgba(255,255,255,0.9), inset 0 0 0 1px rgba(14,165,233,0.06)',
                  }}
                >
                  <Icon
                    size={isAccent ? 22 : 18}
                    strokeWidth={isAccent ? 2 : 1.65}
                    className={isAccent ? '' : 'text-oe-blue/90'}
                  />
                  <span
                    className={`mt-[5px] text-[10px] font-semibold tracking-[-0.01em] ${
                      isAccent ? 'text-white/95' : 'text-content-primary/85'
                    }`}
                  >
                    {cell.label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Value props — restored as a clean two-up grid with refined
            typography (no boxed icon backgrounds, accent rule above each
            title) so the marketing column lands on something concrete
            after the honeycomb. */}
        <div className="mt-2 grid grid-cols-2 gap-x-7 gap-y-1 animate-stagger-in" style={{ animationDelay: '320ms' }}>
          {[
            { icon: ShieldCheck, title: t('login.feat_local_title', { defaultValue: 'Your data, your machine' }), desc: t('login.feat_local', { defaultValue: 'Nothing leaves your computer. Full ownership, zero cloud dependency.' }) },
            { icon: Brain,       title: t('login.feat_ai_title',    { defaultValue: 'AI-assisted, human-confirmed' }), desc: t('login.feat_ai',    { defaultValue: 'Smart suggestions with confidence scores. You always have the final say.' }) },
          ].map((feat) => {
            const Icon = feat.icon;
            return (
              <div key={feat.title} className="relative pl-4">
                <span aria-hidden className="absolute left-0 top-1 h-[14px] w-[2px] rounded-full bg-gradient-to-b from-oe-blue to-sky-500/60" />
                <div className="flex items-center gap-1.5">
                  <Icon size={13} strokeWidth={1.8} className="text-oe-blue/85" />
                  <span className="text-[12.5px] font-semibold tracking-[-0.01em] text-content-primary leading-tight">
                    {feat.title}
                  </span>
                </div>
                <p className="mt-1 text-[11.5px] leading-[1.55] text-content-tertiary tracking-[-0.005em]">
                  {feat.desc}
                </p>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="mt-4 space-y-1 animate-stagger-in" style={{ animationDelay: '380ms' }}>
          <div className="flex items-center gap-2 text-[11px] text-content-quaternary/60">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" className="opacity-40"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
            <a href="/api/source" target="_blank" rel="noopener noreferrer" className="hover:text-content-tertiary transition-colors">AGPL-3.0</a>
            <span className="opacity-30">&middot;</span>
            <a href="https://OpenConstructionERP.com" target="_blank" rel="noopener noreferrer" className="hover:text-content-tertiary transition-colors">OpenConstructionERP.com</a>
          </div>
          <p className="text-[10px] text-content-quaternary/40">
            Created by{' '}
            <a
              href="https://www.linkedin.com/in/artem-boiko/"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-content-tertiary underline-offset-2 hover:underline"
            >
              Artem Boiko
            </a>
            &middot; <a href="mailto:info@datadrivenconstruction.io" className="hover:text-content-tertiary">info@datadrivenconstruction.io</a>
          </p>
        </div>
      </div>

      {/* Center column removed — tags moved to left panel footer */}

      {/* ── Left column on lg+: logo + form (primary action). ── */}
      <div className="relative flex items-center justify-center p-4 sm:p-6 z-10 lg:order-1 overflow-hidden">
        {/* Form column backdrop — clean near-white field on lg+ so the
            glass card reads against a calm canvas. The decorative show
            (orbs / mesh) lives on the marketing column on the right. */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden hidden lg:block" aria-hidden>
          <div className="absolute inset-0 bg-white dark:bg-[#0b0d12]" />
          <div className="absolute inset-0 bg-gradient-to-l from-white/0 via-white/60 to-white dark:from-[#0b0d12]/0 dark:via-[#0b0d12]/60 dark:to-[#0b0d12]" />
          {/* Tiny far-corner sky tint just to soften the edge — the glass
              still has something to lift off, but the field reads white. */}
          <div className="absolute -top-24 -left-24 w-[420px] h-[420px] rounded-full bg-sky-100/55 dark:bg-sky-500/12 blur-[110px]" />
        </div>
        <div className="w-full max-w-[380px] relative z-10">
          {/* Logo */}
          <div className="mb-5 flex flex-col items-center animate-stagger-in" style={{ animationDelay: '0ms' }}>
            <div className="flex items-center gap-2.5">
              <Logo size="md" animate />
              <span
                className="text-2xl font-extrabold text-content-primary whitespace-nowrap"
                style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif", letterSpacing: '-0.02em' }}
              >
                Open<span className="text-oe-blue">Construction</span><span className="text-content-quaternary font-semibold">ERP</span>
              </span>
            </div>
            <p className="mt-2 text-sm text-content-tertiary">
              {t('login.workspace_tagline', { defaultValue: 'Professional construction project workspace' })}
            </p>
          </div>

          {/* Open-source banner (mobile) */}
          <div className="lg:hidden mb-4 animate-stagger-in" style={{ animationDelay: '100ms' }}>
            <div className="rounded-xl bg-gradient-to-r from-oe-blue/10 via-violet-500/10 to-emerald-500/10 border border-oe-blue/20 px-4 py-3 text-center">
              <div className="flex items-center justify-center gap-1.5 mb-1">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600">{t('login.open_source_label', { defaultValue: 'Open Source' })}</span>
              </div>
              <p className="text-sm font-bold bg-gradient-to-r from-oe-blue via-violet-600 to-emerald-600 bg-clip-text text-transparent">
                {t('login.open_source_badge', { defaultValue: 'The #1 Open-Source Construction ERP' })}
              </p>
            </div>
          </div>

          {/* Form — premium multi-layer glass.
              login-glass-pro adds layered borders, a coloured ambient drop
              shadow, an inset highlight, and a soft-light overlay tint via
              ::after. The DOM-level top sheen below adds the rim-light line. */}
          <div
            className="login-glass-pro relative rounded-2xl px-6 py-5 animate-form-scale-in"
            style={{ animationDelay: '150ms' }}
          >
            {/* Top-edge sheen — bright highlight along the rim */}
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
            {/* Visually hidden h1 for screen readers + a11y tools — visible text uses h2 below */}
            <h1 className="sr-only">{t('auth.login', 'Sign in')}</h1>
            <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
              <h2 className="text-base font-semibold text-content-primary mb-0.5">{t('auth.login', 'Sign in')}</h2>
              <p className="text-xs text-content-secondary mb-4">{t('auth.login_subtitle', 'Enter your credentials to access your workspace')}</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3" aria-label={t('auth.login', 'Sign in')}>
              <div className="animate-stagger-in" style={{ animationDelay: '280ms' }}>
                <Input id="login-email" name="email" label={t('auth.email', 'Email')} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="email" required autoFocus icon={<Mail size={15} />} />
              </div>

              <div className="flex flex-col gap-1 animate-stagger-in" style={{ animationDelay: '340ms' }}>
                <div className="flex items-center justify-between">
                  <label htmlFor="login-password" className="text-sm font-medium text-content-primary">{t('auth.password', 'Password')}</label>
                  <Link to="/forgot-password" className="text-2xs font-medium text-oe-blue hover:text-oe-blue-hover transition-colors">{t('auth.forgot_password', 'Forgot password?')}</Link>
                </div>
                <div className="relative">
                  <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary"><Lock size={15} /></div>
                  <input id="login-password" name="password" type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={t('auth.password_placeholder', 'Enter your password')} autoComplete="current-password" required minLength={8} className="h-9 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-9 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary" />
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
                <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error animate-stagger-in">
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

          {/* Demo Access */}
          <div className="mt-3 animate-stagger-in" style={{ animationDelay: '500ms' }}>
            <div className="login-glass-pro relative rounded-2xl overflow-hidden">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-x-6 top-0 h-px"
                style={{
                  background:
                    'linear-gradient(90deg, transparent, rgba(255,255,255,0.95), transparent)',
                }}
              />
              <button
                type="button"
                onClick={() => setDemoOpen(!demoOpen)}
                aria-expanded={demoOpen}
                className="flex w-full items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold text-oe-blue hover:bg-oe-blue/[0.04] transition-all"
              >
                <Zap size={14} className="text-oe-blue" />
                <span>{t('auth.try_demo', { defaultValue: 'Try demo (no signup)' })}</span>
                <ChevronDown size={14} className={`text-oe-blue/70 transition-transform duration-200 ${demoOpen ? 'rotate-180' : ''}`} />
              </button>

              {demoOpen && (
                <div className="border-t border-border-light/60 px-3 py-2.5 space-y-1.5 animate-stagger-in">
                  {demoAccounts.map((acct) => (
                    <button
                      key={acct.email}
                      type="button"
                      onClick={() => handleDemoLogin(acct.email)}
                      disabled={demoLoading !== null}
                      className="flex w-full items-center gap-3 rounded-xl border border-border-light/50 bg-surface-secondary/50 px-3.5 py-2.5 text-left transition-all hover:border-oe-blue/40 hover:bg-oe-blue/[0.05] hover:shadow-sm disabled:opacity-50 group"
                    >
                      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${acct.color} text-white text-sm font-bold shadow-sm`}>
                        {demoLoading === acct.email ? (
                          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>
                        ) : (
                          acct.letter
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-semibold text-content-primary">{acct.name}</div>
                        <div className="text-[11px] text-content-tertiary truncate">{acct.email} · {acct.role}</div>
                      </div>
                      <ChevronDown size={15} className="text-content-quaternary -rotate-90 group-hover:text-oe-blue transition-colors shrink-0" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Learn more — direct link to the marketing site (was a popup). */}
          <div className="mt-4 flex items-center justify-center gap-3 animate-stagger-in" style={{ animationDelay: '520ms' }}>
            <a
              href="https://OpenConstructionERP.com"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg border border-border-light/60 px-3 py-1.5 text-2xs text-content-tertiary hover:text-oe-blue hover:border-oe-blue/30 transition-colors"
            >
              <Info size={12} />
              {t('login.learn_more', 'Learn more about the platform')}
            </a>
          </div>
          <div className="lg:hidden mt-2 text-center text-2xs text-content-quaternary">
            <div className="flex items-center justify-center gap-3">
              <a href="https://OpenConstructionERP.com" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">OpenConstructionERP.com</a>
              <span>·</span>
              <a href="https://github.com/datadrivenconstruction/OpenConstructionERP" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">GitHub</a>
            </div>
          </div>
        </div>
      </div>

      {/* ── About modal ── */}
      {showInfo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-lg" onClick={() => setShowInfo(false)} />

          <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-border-light bg-surface-elevated shadow-2xl">
            <button
              onClick={() => setShowInfo(false)}
              className="sticky top-0 float-right m-3 p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors z-10 bg-surface-elevated/80 backdrop-blur-sm"
            >
              <X size={18} />
            </button>

            {/* Header */}
            <div className="px-6 pt-5 pb-4 border-b border-border-light clear-both">
              <LogoWithText size="sm" className="mb-3" />
              <h3 className="text-base font-bold text-content-primary mb-2">
                {t('about.title', 'Professional construction cost estimation — free and open source')}
              </h3>
              <p className="text-[13px] text-content-secondary leading-relaxed">
                {t('about.intro', 'OpenConstructionERP is a modern platform for construction cost management. It covers the full estimation workflow — from creating a bill of quantities to tendering and bid comparison. Designed for professionals worldwide, it supports international standards and works in 20 languages.')}
              </p>
              <p className="mt-2 text-[13px] text-content-secondary leading-relaxed">
                {t('about.intro2', 'Unlike traditional commercial solutions, OpenConstructionERP runs entirely on your computer. Your project data never leaves your machine — you have full ownership and control. The source code is open and auditable, so you always know exactly what the software does.')}
              </p>
            </div>

            {/* What you can do */}
            <div className="px-6 py-4">
              <h3 className="text-sm font-semibold text-content-primary mb-3">
                {t('about.capabilities_title', 'What you can do')}
              </h3>
              <div className="grid grid-cols-2 gap-2.5">
                {[
                  { icon: FileSpreadsheet, color: 'text-emerald-500 bg-emerald-500/10', title: t('about.cap.boq', 'Bill of Quantities'), desc: t('about.cap.boq_desc', 'Create detailed BOQ with hierarchical sections, positions, assemblies, markups (overhead, profit, VAT), and automatic totals. Works with regional classification systems or your own custom schema.') },
                  { icon: Database, color: 'text-blue-500 bg-blue-500/10', title: t('about.cap.costs', 'Cost Databases'), desc: t('about.cap.costs_desc', '55,000+ cost items across 30 regional databases worldwide. Add your own rates, import from Excel, or build a custom database from scratch.') },
                  { icon: CalendarClock, color: 'text-amber-500 bg-amber-500/10', title: t('about.cap.schedule', '4D Scheduling'), desc: t('about.cap.schedule_desc', 'Create project schedules with CPM critical path calculation, interactive Gantt charts, Monte Carlo risk analysis, resource assignment, and auto-generation of activities from your BOQ.') },
                  { icon: TrendingUp, color: 'text-violet-500 bg-violet-500/10', title: t('about.cap.costmodel', '5D Cost Model'), desc: t('about.cap.costmodel_desc', 'Track budgets over time with Earned Value Management (SPI, CPI), S-curve visualization, cash flow projections, cost snapshots, and what-if scenario modeling for informed decision-making.') },
                  { icon: Boxes, color: 'text-rose-500 bg-rose-500/10', title: t('about.cap.catalog', 'Resource Catalog'), desc: t('about.cap.catalog_desc', '7,000+ resources — materials, equipment, labor, operators, and utilities. Build reusable assemblies (composite rates) from catalog items and apply them directly to BOQ positions.') },
                  { icon: BarChart3, color: 'text-cyan-500 bg-cyan-500/10', title: t('about.cap.tendering', 'Tendering & Bids'), desc: t('about.cap.tendering_desc', 'Create tender packages with scope and positions, distribute to subcontractors, collect and compare bids side-by-side in a price mirror, and make award decisions based on data.') },
                  { icon: Upload, color: 'text-orange-500 bg-orange-500/10', title: t('about.cap.import', 'Import & Export'), desc: t('about.cap.import_desc', 'Full support for GAEB XML (X83), Excel, and CSV import/export. Generate professional PDF reports. Seamlessly integrate with your existing tools and workflows.') },
                  { icon: FileCheck, color: 'text-teal-500 bg-teal-500/10', title: t('about.cap.validation', 'Quality Validation'), desc: t('about.cap.validation_desc', 'Built-in quality engine automatically checks for missing quantities, zero prices, duplicate positions, classification compliance, and rate anomalies — with a traffic-light dashboard.') },
                ].map((cap, idx) => {
                  const Icon = cap.icon;
                  return (
                    <div key={idx} className="rounded-lg border border-border-light/60 bg-surface-secondary/50 px-3 py-2.5">
                      <div className="flex items-center gap-2 mb-1">
                        <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${cap.color}`}>
                          <Icon size={13} />
                        </div>
                        <span className="text-xs font-semibold text-content-primary">{cap.title}</span>
                      </div>
                      <p className="text-2xs text-content-tertiary leading-relaxed pl-8">{cap.desc}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Why open source */}
            <div className="px-6 py-4 border-t border-border-light">
              <h3 className="text-sm font-semibold text-content-primary mb-2">
                {t('about.why_title', 'Why open source matters')}
              </h3>
              <div className="space-y-2 text-[13px] text-content-secondary leading-relaxed">
                <p>{t('about.why_1', 'Construction cost data is one of the most valuable assets a company owns. With proprietary software, your data is often locked inside formats you cannot control. If the vendor raises prices, changes terms, or discontinues the product — you may lose access to years of work.')}</p>
                <p>{t('about.why_2', 'OpenConstructionERP takes a different approach. Your data is stored in open formats (SQLite, JSON, CSV) on your own hardware. You can export everything at any time. The source code is publicly auditable under AGPL-3.0, so there are no hidden data transfers, no telemetry, and no surprises.')}</p>
                <p>{t('about.why_3', 'The platform is modular — install only what you need. Community modules extend functionality without bloating the core. And because it runs locally, it works offline and performs fast even with large projects.')}</p>
              </div>
            </div>

            {/* Who is it for */}
            <div className="px-6 py-4 border-t border-border-light">
              <h3 className="text-sm font-semibold text-content-primary mb-2">
                {t('about.who_title', 'Who is it for')}
              </h3>
              <p className="text-[13px] text-content-secondary leading-relaxed mb-3">
                {t('about.who_desc', 'OpenConstructionERP is designed for anyone involved in construction cost management — whether you work on residential projects or large-scale infrastructure, in-house or as a consultant.')}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {[
                  t('about.who.estimators', 'Cost estimators'),
                  t('about.who.qsurveyor', 'Quantity surveyors'),
                  t('about.who.pm', 'Project managers'),
                  t('about.who.contractors', 'General contractors'),
                  t('about.who.subs', 'Subcontractors'),
                  t('about.who.architects', 'Architects & engineers'),
                  t('about.who.developers', 'Real estate developers'),
                  t('about.who.public', 'Public sector & municipalities'),
                  t('about.who.students', 'Students & educators'),
                  t('about.who.freelancers', 'Freelance consultants'),
                ].map((role) => (
                  <span key={role} className="inline-flex items-center rounded-full bg-oe-blue/8 px-2.5 py-1 text-2xs font-medium text-oe-blue">
                    {role}
                  </span>
                ))}
              </div>
            </div>

            {/* Key facts */}
            <div className="px-6 py-4 border-t border-border-light">
              <h3 className="text-sm font-semibold text-content-primary mb-3">
                {t('about.numbers_title', 'Platform in numbers')}
              </h3>
              <div className="grid grid-cols-4 gap-3 text-center">
                {[
                  { value: '55,719', label: t('about.stat.costs', 'Cost items') },
                  { value: '30', label: t('about.stat.regions', 'Regional databases') },
                  { value: '20', label: t('about.stat.languages', 'Languages') },
                  { value: '100%', label: t('about.stat.free', 'Free & open source') },
                ].map((stat) => (
                  <div key={stat.label} className="rounded-lg bg-surface-secondary/50 py-2.5">
                    <div className="text-lg font-bold text-oe-blue">{stat.value}</div>
                    <div className="text-2xs text-content-tertiary">{stat.label}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* AI note */}
            <div className="px-6 py-4 border-t border-border-light">
              <h3 className="text-sm font-semibold text-content-primary mb-2">
                {t('about.ai_title', 'About AI features')}
              </h3>
              <p className="text-[13px] text-content-secondary leading-relaxed">
                {t('about.ai_desc', 'OpenConstructionERP includes optional AI-powered tools — quick estimation from text descriptions, smart cost suggestions, and BOQ chat assistant. These features require an API key from a provider of your choice (Anthropic, OpenAI, Google). AI is always opt-in: it only activates when you configure it, and you decide what data to send. Without an API key, all other features work fully offline.')}
              </p>
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-border-light flex items-center justify-between">
              <div className="flex items-center gap-3 text-2xs text-content-quaternary">
                <a href="/api/source" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">AGPL-3.0</a>
                <a href="https://OpenConstructionERP.com" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">OpenConstructionERP.com</a>
                <a href="https://github.com/datadrivenconstruction/OpenConstructionERP" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">GitHub</a>
              </div>
              <Button variant="primary" size="sm" onClick={() => setShowInfo(false)}>
                {t('about.close', 'Got it')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
