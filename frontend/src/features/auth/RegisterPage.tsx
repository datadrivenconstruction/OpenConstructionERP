// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useRef, useEffect, type FormEvent } from 'react';
import { APP_NAME } from '@/shared/lib/brandName';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';
import {
  Eye, EyeOff, Mail, Lock, User, Globe, ChevronDown,
  HardDrive, Zap, Globe2, Brain, Building2, Briefcase,
} from 'lucide-react';
import { Button, Input, LogoWithText, CountryFlag } from '@/shared/ui';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '@/app/i18n';
import { sortLanguagesByName } from '@/shared/lib/languageOrder';
import { readRememberChoice, useAuthStore } from '@/stores/useAuthStore';
import { LegalFooter } from '@/features/legal/LegalFooter';
import { AuthBackground } from './AuthBackground';
import { meetsPasswordPolicy, passwordStrength } from './passwordPolicy';

export function RegisterPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const currentLang = getLanguageByCode(i18n.language);
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [jobTitle, setJobTitle] = useState('');
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
  // The server's rules (length, a letter in any script, a digit), shared with
  // the reset page so the two forms cannot drift from each other.
  const passwordStrong = meetsPasswordPolicy(password);
  // The word beside the bars answers the same question the submit button asks,
  // so the form can never read "Medium" next to a button that stays disabled.
  const strength = passwordStrength(password);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (!passwordsMatch) {
      setError(t('auth.passwords_no_match', { defaultValue: 'Passwords do not match' }));
      return;
    }
    if (passwordStrong === false) {
      setError(
        t('auth.password_requirements', {
          defaultValue:
            'Password must be at least 8 characters with at least one letter and one digit',
        }),
      );
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
        }),
      });

      if (!regRes.ok) {
        // FastAPI returns either a plain string detail or a list of
        // validation-error objects; flatten the list into one message,
        // otherwise fall back to the generic failure text.
        const body = await regRes.json().catch(() => null);
        const detail = body?.detail;
        const fallback = t('auth.registration_failed', 'Registration failed');
        const message = Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item.msg).join('; ')
          : detail || fallback;
        setError(message);
        return;
      }

      // The registration endpoint returns the user record. In gated modes
      // (admin-approve / email-verify) the new account comes back with
      // is_active=false and the immediate login attempt 401s with the
      // same generic "Invalid email or password" used for bad creds, so
      // without this branch users get a confusing dead-end. Surface a
      // clear pending-activation message instead.
      const regBody = await regRes.json().catch(() => null);
      if (regBody && regBody.is_active === false) {
        setError(
          t(
            'auth.registration_pending_activation',
            'Account created. An administrator needs to activate it before you can log in. ' +
              'For local installs, set OE_REGISTRATION_MODE=open in your .env to skip this step.',
          ),
        );
        return;
      }

      const loginRes = await fetch('/api/v1/users/auth/login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (loginRes.ok) {
        const data = await loginRes.json();
        setTokens(data.access_token, data.refresh_token, readRememberChoice(), email);
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
    { icon: HardDrive, color: 'text-emerald-500 bg-emerald-500/10', title: t('login.benefit.local', 'Self-hosted: your data stays where you run this.'), desc: t('login.benefit.local_desc', 'Self-hosted: your machines, your network, your rules.') },
    { icon: Globe2, color: 'text-violet-500 bg-violet-500/10', title: t('login.benefit.standards', 'Global cost databases'), desc: t('login.benefit.standards_desc', '55,000+ cost items, 48 databases.') },
    { icon: Brain, color: 'text-amber-500 bg-amber-500/10', title: t('login.benefit.ai', 'AI-assisted estimation'), desc: t('login.benefit.ai_desc', 'Smart suggestions. You decide, AI assists.') },
    { icon: Zap, color: 'text-rose-500 bg-rose-500/10', title: t('login.benefit.allinone', 'BOQ + 4D + 5D + Tendering'), desc: t('login.benefit.allinone_desc', 'Full workflow in one tool.') },
  ];

  return (
    <div className="relative flex h-screen bg-surface-secondary overflow-hidden">
      <AuthBackground />

      {/* Language — top right */}
      <div className="absolute top-3 end-3 z-30" ref={langRef}>
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
          <div className="absolute end-0 mt-1 w-44 max-h-72 overflow-y-auto rounded-xl border border-border-light bg-surface-elevated shadow-xl py-0.5 animate-stagger-in">
            {sortLanguagesByName(SUPPORTED_LANGUAGES).map((lang) => {
              const isActive = i18n.language === lang.code;
              return (
                <button
                  key={lang.code}
                  onClick={() => { i18n.changeLanguage(lang.code); setLangOpen(false); }}
                  className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-xs transition-colors ${isActive ? 'bg-oe-blue/10 text-oe-blue font-medium' : 'text-content-primary hover:bg-surface-secondary'}`}
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
      <div className="hidden lg:flex lg:w-[460px] xl:w-[500px] shrink-0 relative z-10 flex-col justify-center ps-14 xl:ps-20 pe-8 xl:pe-10 py-6">
        <div className="mb-4 animate-stagger-in" style={{ animationDelay: '0ms' }}>
          <h2 className="text-xl font-bold text-content-primary leading-snug">
            {t('login.hero_title', 'Construction cost estimation,')}{' '}
            <span className="gradient-text">{t('login.hero_highlight', 'reimagined')}</span>
          </h2>
          <p className="mt-1.5 text-[13px] text-content-secondary leading-relaxed">
            {/* This used to reuse login.hero_desc, whose text ended "all in one
                open-source platform" - a marketing claim about the project's
                licence, on a page whose job is to register a workspace. It now
                uses the same neutral product tagline the sign-in page carries,
                which is already translated in every locale. */}
            {t('login.workspace_tagline', 'Estimating, scheduling, cost control and site records in one place.')}
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
              {t('login.privacy', 'Your projects, documents and estimates stay inside the deployment you sign in to - your own machine, or the servers your organisation runs. Nothing is uploaded to the vendor of this product.')}
            </p>
            <p className="mt-0.5 text-[10px] text-content-quaternary leading-snug">
              * {t('login.privacy_ai', 'The built-in AI tools are the exception, and they stay off until an operator connects them. A connected tool sends what its prompt needs to the provider that operator chose (OpenAI, Anthropic and others), under that provider\'s own retention terms. A few features also load content from the third-party services they name, such as map tiles.')}
            </p>
          </div>
        </div>

        {/* One footer, shared with every other screen that has no app shell.
            This row used to carry an inline mark of the upstream repository and
            a badge naming the licence next to the Legal link. Neither belongs
            here: /legal, one click away, is the surface that states the licence,
            the NOTICE attribution and the source offer, and one shared component
            is what stops the screens that have no shell drifting apart again. */}
        <LegalFooter
          className="mt-3 flex items-center gap-3 text-2xs text-content-quaternary animate-stagger-in"
          style={{ animationDelay: '360ms' }}
        />
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
                {t('auth.register_subtitle', `Get started with ${APP_NAME}`)}
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
                  required aria-required="true"
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
                  required aria-required="true"
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
              </div>

              <div className="flex flex-col gap-1 animate-stagger-in" style={{ animationDelay: '340ms' }}>
                <label htmlFor="register-password" className="text-sm font-medium text-content-primary">
                  {t('auth.password', 'Password')}
                </label>
                <div className="relative">
                  <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-content-tertiary">
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
                    required aria-required="true"
                    minLength={8}
                    className="h-9 w-full rounded-lg border border-border bg-surface-primary pl-9 pr-9 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? t('auth.hide_password', 'Hide password') : t('auth.show_password', 'Show password')}
                    className="absolute inset-y-0 end-0 flex items-center pe-3 text-content-tertiary hover:text-content-secondary transition-colors"
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
                {password && (
                  <div className="mt-0.5">
                    <div className="flex items-center gap-2">
                      <div className={`h-1 flex-1 rounded-full transition-colors duration-normal ${password.length >= 8 ? 'bg-semantic-success' : 'bg-border'}`} />
                      <div className={`h-1 flex-1 rounded-full transition-colors duration-normal ${password.length >= 12 ? 'bg-semantic-success' : 'bg-border'}`} />
                      <div className={`h-1 flex-1 rounded-full transition-colors duration-normal ${/[A-Z]/.test(password) && /[0-9]/.test(password) ? 'bg-semantic-success' : 'bg-border'}`} />
                      <span className="text-2xs text-content-tertiary ml-1">
                        {strength === 'weak' ? t('auth.password_strength_weak', 'Weak') : strength === 'medium' ? t('auth.password_strength_medium', 'Medium') : t('auth.password_strength_strong', 'Strong')}
                      </span>
                    </div>
                    {/* The rule the server enforces, stated while the button is
                        still disabled. handleSubmit sets the same sentence, but
                        a disabled button never reaches it, so a reader who typed
                        a password with no letter in it was told nothing: the
                        label read "Medium" and the form simply would not send. */}
                    {!passwordStrong && (
                      <p className="text-2xs text-semantic-error mt-1" data-testid="register-password-reason">
                        {t('auth.password_requirements', {
                          defaultValue: 'Password must be at least 8 characters with at least one letter and one digit',
                        })}
                      </p>
                    )}
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
                  required aria-required="true"
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
                  disabled={
                    !(
                      fullName &&
                      email &&
                      password &&
                      confirmPassword &&
                      passwordsMatch &&
                      passwordStrong &&
                      privacyAccepted
                    )
                  }
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

          {/* Mobile footer: the same component, so the narrow layout carries the
              build version too and follows the same visibility setting. */}
          <div className="lg:hidden mt-3 text-center text-2xs text-content-quaternary">
            <LegalFooter className="flex items-center justify-center gap-1.5" />
          </div>
        </div>
      </div>
    </div>
  );
}
