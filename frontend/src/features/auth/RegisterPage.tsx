import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';
import {
  Eye, EyeOff, Mail, Lock, User, Globe, ChevronDown,
  ShieldCheck, HardDrive, Zap, Globe2, Brain, Users,
  Building2, Briefcase, Search,
} from 'lucide-react';
import { Button, Input, LogoWithText, CountryFlag } from '@/shared/ui';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '@/app/i18n';
import { useAuthStore } from '@/stores/useAuthStore';
import { AuthBackground } from './AuthBackground';

export function RegisterPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const currentLang = getLanguageByCode(i18n.language);
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [howFoundUs, setHowFoundUs] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const passwordsMatch = password === confirmPassword;
  const passwordLongEnough = password.length >= 8;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (!passwordsMatch) {
      setError(t('auth.passwords_no_match', { defaultValue: 'Passwords do not match' }));
      return;
    }
    if (!passwordLongEnough) {
      setError(t('auth.password_min_length', { defaultValue: 'Password must be at least 8 characters' }));
      return;
    }

    setLoading(true);

    try {
      const regRes = await fetch('/api/v1/users/auth/register/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          password,
          full_name: fullName,
          company,
          job_title: jobTitle,
          how_found_us: howFoundUs,
        }),
      });

      if (!regRes.ok) {
        const data = await regRes.json().catch(() => null);
        setError(data?.detail || t('auth.registration_failed', 'Registration failed'));
        return;
      }

      const loginRes = await fetch('/api/v1/users/auth/login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (loginRes.ok) {
        const data = await loginRes.json();
        setTokens(data.access_token, data.refresh_token);
        navigate('/');
      } else {
        navigate('/login');
      }
    } catch {
      setError(t('auth.connection_error', 'Unable to connect to server'));
    } finally {
      setLoading(false);
    }
  };

  const benefits = [
    { icon: HardDrive, color: 'text-emerald-500 bg-emerald-500/10', title: t('login.benefit.local', 'Your data stays on your computer'), desc: t('login.benefit.local_desc', 'No cloud. No third-party servers. Full control.') },
    { icon: ShieldCheck, color: 'text-blue-500 bg-blue-500/10', title: t('login.benefit.open_source', '100% open source'), desc: t('login.benefit.open_source_desc', 'Transparent code. No vendor lock-in.') },
    { icon: Globe2, color: 'text-violet-500 bg-violet-500/10', title: t('login.benefit.standards', 'Global cost databases'), desc: t('login.benefit.standards_desc', '55,000+ cost items, 11 databases.') },
    { icon: Brain, color: 'text-amber-500 bg-amber-500/10', title: t('login.benefit.ai', 'AI-assisted estimation'), desc: t('login.benefit.ai_desc', 'Smart suggestions. You decide, AI assists.') },
    { icon: Zap, color: 'text-rose-500 bg-rose-500/10', title: t('login.benefit.allinone', 'BOQ + 4D + 5D + Tendering'), desc: t('login.benefit.allinone_desc', 'Full workflow in one tool.') },
    { icon: Users, color: 'text-cyan-500 bg-cyan-500/10', title: t('login.benefit.free', 'Free for everyone'), desc: t('login.benefit.free_desc', 'No fees. No limits. By estimators.') },
  ];

  return (
    <div className="relative flex h-screen bg-surface-secondary overflow-hidden">
      <AuthBackground />

      {/* Language — top right */}
      <div className="absolute top-3 right-3 z-30" ref={langRef}>
        <button
          onClick={() => setLangOpen(!langOpen)}
          className="flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-elevated/80 backdrop-blur-sm px-2.5 py-1 text-xs text-content-secondary hover:bg-surface-elevated transition-colors shadow-sm"
        >
          <Globe size={12} className="text-content-tertiary" />
          <CountryFlag code={currentLang.country} size={14} />
          <span className="hidden sm:inline">{currentLang.name}</span>
          <ChevronDown size={11} className={`text-content-tertiary transition-transform ${langOpen ? 'rotate-180' : ''}`} />
        </button>
        {langOpen && (
          <div className="absolute right-0 mt-1 w-44 max-h-72 overflow-y-auto rounded-xl border border-border-light bg-surface-elevated shadow-xl py-0.5 animate-stagger-in">
            {SUPPORTED_LANGUAGES.map((lang) => {
              const isActive = i18n.language === lang.code;
              return (
                <button
                  key={lang.code}
                  onClick={() => { i18n.changeLanguage(lang.code); setLangOpen(false); }}
                  className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-xs transition-colors ${isActive ? 'bg-oe-blue/8 text-oe-blue font-medium' : 'text-content-primary hover:bg-surface-secondary'}`}
                >
                  <CountryFlag code={lang.country} size={14} />
                  <span className="truncate">{lang.name}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Left: benefits (desktop) ── */}
      <div className="hidden lg:flex lg:w-[460px] xl:w-[500px] shrink-0 relative z-10 flex-col justify-center pl-14 xl:pl-20 pr-8 xl:pr-10 py-6">
        <div className="mb-4 animate-stagger-in" style={{ animationDelay: '0ms' }}>
          <h2 className="text-xl font-bold text-content-primary leading-snug">
            {t('login.hero_title', 'Construction cost estimation,')}{' '}
            <span className="gradient-text">{t('login.hero_highlight', 'reimagined')}</span>
          </h2>
          <p className="mt-1.5 text-[13px] text-content-secondary leading-relaxed">
            {t('login.hero_desc', 'Professional BOQ, 4D scheduling, 5D cost model, and tendering — all in one open-source platform.')}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {benefits.map((item, idx) => {
            const Icon = item.icon;
            return (
              <div
                key={idx}
                className="rounded-lg border border-border-light/40 bg-surface-elevated/40 backdrop-blur-sm px-2.5 py-2 animate-stagger-in"
                style={{ animationDelay: `${50 + idx * 40}ms` }}
              >
                <div className="flex items-center gap-1.5 mb-0.5">
                  <div className={`flex h-5 w-5 shrink-0 items-center justify-center rounded ${item.color}`}>
                    <Icon size={11} />
                  </div>
                  <span className="text-2xs font-semibold text-content-primary leading-tight">{item.title}</span>
                </div>
                <p className="text-2xs text-content-tertiary leading-snug pl-[26px]">{item.desc}</p>
              </div>
            );
          })}
        </div>

        <div className="mt-3 flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 animate-stagger-in" style={{ animationDelay: '320ms' }}>
          <HardDrive size={13} className="text-emerald-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-2xs text-content-secondary leading-snug">
              {t('login.privacy', 'All data is processed and stored locally on your machine. Nothing is sent to external servers. You own your data — always.')}
            </p>
            <p className="mt-0.5 text-[10px] text-content-quaternary leading-snug">
              * {t('login.privacy_ai', 'If you use built-in AI tools, some data may be sent to the AI provider you configure (OpenAI, Anthropic, etc.). You control which provider to use and what data to share.')}
            </p>
          </div>
        </div>

        <div className="mt-3 flex items-center gap-3 text-2xs text-content-quaternary animate-stagger-in" style={{ animationDelay: '360ms' }}>
          <span className="inline-flex items-center gap-1 rounded-full border border-border-light px-2 py-0.5 text-content-tertiary">
            <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" className="opacity-50"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
            Open Source · AGPL-3.0
          </span>
          <a href="https://OpenConstructionERP.com" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">OpenConstructionERP.com</a>
        </div>
      </div>

      {/* ── Right: logo + form ── */}
      <div className="flex flex-1 items-center justify-center p-4 sm:p-6 relative z-10">
        <div className="w-full max-w-[400px]">
          {/* Logo */}
          <div className="mb-5 flex flex-col items-center animate-stagger-in" style={{ animationDelay: '0ms' }}>
            <LogoWithText size="md" animate />
            <p className="mt-1 text-xs text-content-tertiary">{t('app.tagline')}</p>
          </div>

          {/* Form */}
          <div className="glass-strong rounded-2xl px-6 py-5 shadow-lg animate-form-scale-in" style={{ animationDelay: '150ms' }}>
            {/* Visually hidden h1 for screen readers + a11y tools — visible text uses h2 below */}
            <h1 className="sr-only">{t('auth.create_account', 'Create account')}</h1>
            <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
              <h2 className="text-base font-semibold text-content-primary mb-0.5">
                {t('auth.create_account', 'Create account')}
              </h2>
              <p className="text-xs text-content-secondary mb-4">
                {t('auth.register_subtitle', 'Get started with OpenEstimate')}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3" aria-label={t('auth.register', 'Create account')}>
              <div className="animate-stagger-in" style={{ animationDelay: '260ms' }}>
                <Input
                  id="register-full-name"
                  name="full_name"
                  label={t('auth.full_name', 'Full Name')}
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder={t('auth.full_name_placeholder', 'John Smith')}
                  required
                  autoFocus
                  autoComplete="name"
                  icon={<User size={15} />}
                />
              </div>

              <div className="animate-stagger-in" style={{ animationDelay: '300ms' }}>
                <Input
                  id="register-email"
                  name="email"
                  label={t('auth.email', 'Email')}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  autoComplete="email"
                  required
                  icon={<Mail size={15} />}
                />
              </div>

              <div className="animate-stagger-in" style={{ animationDelay: '320ms' }}>
                <Input
                  id="register-company"
                  name="company"
                  label={t('auth.company', 'Company')}
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder={t('auth.company_placeholder', 'Your company or organisation')}
                  autoComplete="organization"
                  icon={<Building2 size={15} />}
                />
              </div>

              <div className="grid grid-cols-2 gap-2 animate-stagger-in" style={{ animationDelay: '330ms' }}>
                <Input
                  id="register-job-title"
                  name="job_title"
                  label={t('auth.job_title', 'Role')}
                  type="text"
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  placeholder={t('auth.job_title_placeholder', 'e.g. Estimator')}
                  autoComplete="organization-title"
                  icon={<Briefcase size={15} />}
                />
                <div>
                  <label htmlFor="register-how-found" className="text-sm font-medium text-content-primary block mb-1">
                    {t('auth.how_found_us', 'How did you find us?')}
                  </label>
                  <div className="relative">
                    <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
                      <Search size={15} />
                    </div>
                    <select
                      id="register-how-found"
                      name="how_found_us"
                      value={howFoundUs}
                      onChange={(e) => setHowFoundUs(e.target.value)}
                      className="h-9 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary appearance-none cursor-pointer"
                    >
                      <option value="">{t('auth.how_found_select', '— Select —')}</option>
                      <option value="google">{t('auth.how_found_google', 'Google Search')}</option>
                      <option value="github">{t('auth.how_found_github', 'GitHub')}</option>
                      <option value="linkedin">{t('auth.how_found_linkedin', 'LinkedIn')}</option>
                      <option value="reddit">{t('auth.how_found_reddit', 'Reddit')}</option>
                      <option value="youtube">{t('auth.how_found_youtube', 'YouTube')}</option>
                      <option value="recommendation">{t('auth.how_found_recommendation', 'Recommendation')}</option>
                      <option value="conference">{t('auth.how_found_conference', 'Conference / Event')}</option>
                      <option value="other">{t('auth.how_found_other', 'Other')}</option>
                    </select>
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-1 animate-stagger-in" style={{ animationDelay: '340ms' }}>
                <label htmlFor="register-password" className="text-sm font-medium text-content-primary">
                  {t('auth.password', 'Password')}
                </label>
                <div className="relative">
                  <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
                    <Lock size={15} />
                  </div>
                  <input
                    id="register-password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t('auth.password_min', 'Minimum 8 characters')}
                    autoComplete="new-password"
                    required
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
                {password && (
                  <div className="flex items-center gap-2 mt-0.5">
                    <div className={`h-1 flex-1 rounded-full transition-colors duration-normal ${password.length >= 8 ? 'bg-semantic-success' : 'bg-border'}`} />
                    <div className={`h-1 flex-1 rounded-full transition-colors duration-normal ${password.length >= 12 ? 'bg-semantic-success' : 'bg-border'}`} />
                    <div className={`h-1 flex-1 rounded-full transition-colors duration-normal ${/[A-Z]/.test(password) && /[0-9]/.test(password) ? 'bg-semantic-success' : 'bg-border'}`} />
                    <span className="text-2xs text-content-tertiary ml-1">
                      {password.length < 8 ? t('auth.password_strength_weak', 'Weak') : password.length < 12 ? t('auth.password_strength_medium', 'Medium') : t('auth.password_strength_strong', 'Strong')}
                    </span>
                  </div>
                )}
              </div>

              <div className="animate-stagger-in" style={{ animationDelay: '380ms' }}>
                <Input
                  id="register-confirm-password"
                  name="confirm_password"
                  label={t('auth.confirm_password', 'Confirm Password')}
                  type={showPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder={t('auth.confirm_password_placeholder', 'Repeat your password')}
                  autoComplete="new-password"
                  required
                  error={confirmPassword && !passwordsMatch ? t('auth.passwords_mismatch', 'Passwords do not match') : undefined}
                  icon={<Lock size={15} />}
                />
              </div>

              {error && (
                <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error animate-stagger-in">
                  <span className="shrink-0 mt-0.5">!</span>
                  <span>{error}</span>
                </div>
              )}

              <div className="animate-stagger-in" style={{ animationDelay: '410ms' }}>
                <label className="flex items-start gap-2 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={privacyAccepted}
                    onChange={(e) => setPrivacyAccepted(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue cursor-pointer shrink-0"
                  />
                  <span className="text-[11px] text-content-secondary leading-snug">
                    {t('auth.privacy_consent', 'I agree to the')}{' '}
                    <a
                      href="/privacy-policy.html"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-oe-blue hover:underline font-medium"
                    >
                      {t('auth.privacy_policy', 'Privacy Policy')}
                    </a>
                    {' '}{t('auth.and', 'and')}{' '}
                    <a
                      href="/terms.html"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-oe-blue hover:underline font-medium"
                    >
                      {t('auth.terms_of_service', 'Terms of Service')}
                    </a>
                    {'. '}
                    {t('auth.privacy_consent_detail', 'Your data is processed in accordance with GDPR. We collect your name, email, company info, and usage data to provide the service. You can delete your account at any time.')}
                  </span>
                </label>
              </div>

              <div className="animate-stagger-in" style={{ animationDelay: '420ms' }}>
                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  loading={loading}
                  disabled={!fullName || !email || !password || !confirmPassword || !passwordsMatch || !passwordLongEnough || !privacyAccepted}
                  className="w-full btn-shimmer"
                >
                  {t('auth.create_account', 'Create account')}
                </Button>
              </div>
            </form>

            <div className="mt-4 border-t border-border-light pt-3.5 animate-stagger-in" style={{ animationDelay: '460ms' }}>
              <p className="text-center text-xs text-content-secondary">
                {t('auth.has_account', 'Already have an account?')}{' '}
                <Link to="/login" className="font-medium text-oe-blue hover:text-oe-blue-hover transition-colors">
                  {t('auth.login', 'Sign in')}
                </Link>
              </p>
              <button
                type="button"
                onClick={() => navigate('/login')}
                className="mt-2 block w-full text-center text-2xs text-oe-blue hover:text-oe-blue-hover hover:underline font-medium cursor-pointer transition-colors"
              >
                {t('auth.try_demo', 'Try demo account →')}
              </button>
            </div>
          </div>

          {/* Mobile footer */}
          <div className="lg:hidden mt-3 text-center text-2xs text-content-quaternary">
            <div className="flex items-center justify-center gap-3">
              <a href="https://OpenConstructionERP.com" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">OpenConstructionERP.com</a>
              <span>·</span>
              <a href="https://github.com/datadrivenconstruction/OpenConstructionERP" target="_blank" rel="noopener noreferrer" className="hover:text-content-secondary transition-colors">GitHub</a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
