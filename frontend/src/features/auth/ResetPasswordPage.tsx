// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Lock, Eye, EyeOff, CheckCircle2, AlertTriangle, Globe, ChevronDown } from 'lucide-react';
import { Button, Input, Logo, CountryFlag } from '@/shared/ui';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '@/app/i18n';
import { sortLanguagesByName } from '@/shared/lib/languageOrder';
import { useAuthStore } from '@/stores/useAuthStore';
import { AuthBackground } from './AuthBackground';
import { meetsPasswordPolicy } from './passwordPolicy';

/** The route the password-reset email links to (backend users/service.py builds it). */
export const RESET_PASSWORD_ROUTE = '/auth/reset';

type View = 'form' | 'success' | 'invalid';

/** True when a 422 from the reset endpoint is about the token, not the password. */
function isTokenValidationError(detail: unknown): boolean {
  return (
    Array.isArray(detail) &&
    detail.some(
      (item: { loc?: unknown }) => Array.isArray(item?.loc) && item.loc.includes('token'),
    )
  );
}

/**
 * Landing page of the password-reset email: reads the one-time token from
 * `?token=` and sets a new password with it.
 *
 * The token is a credential for the account until it expires, so it is read
 * once into state and then taken out of the address bar (a router `replace`,
 * which is `history.replaceState` under the app's basename). That keeps it
 * out of the browser history, a copied URL and any report that reads the
 * current location. It is never logged.
 */
export function ResetPasswordPage() {
  const { t, i18n } = useTranslation();
  const currentLang = getLanguageByCode(i18n.language);
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [token] = useState(() => (searchParams.get('token') ?? '').trim());
  const [view, setView] = useState<View>(() => (token ? 'form' : 'invalid'));
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);

  // Take the token out of the address bar as soon as it has been read.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (!params.has('token')) return;
    params.delete('token');
    const rest = params.toString();
    navigate(
      { pathname: location.pathname, search: rest ? `?${rest}` : '', hash: location.hash },
      { replace: true },
    );
  }, [location.pathname, location.search, location.hash, navigate]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const passwordsMatch = password === confirmPassword;
  const passwordStrong = meetsPasswordPolicy(password);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (!passwordStrong) {
      setError(
        t('auth.password_requirements', {
          defaultValue: 'Password must be at least 8 characters with at least one letter and one digit',
        }),
      );
      return;
    }
    if (!passwordsMatch) {
      setError(t('auth.passwords_no_match', { defaultValue: 'Passwords do not match' }));
      return;
    }

    setLoading(true);
    try {
      const res = await fetch('/api/v1/users/auth/reset-password/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      });

      if (res.ok) {
        // The reset ends every session this account had: the server refuses
        // any token issued before the password changed. Drop the local one
        // too, so the next screen is a sign-in with the new password and not
        // a dashboard that logs itself out on its first request.
        if (useAuthStore.getState().isAuthenticated) useAuthStore.getState().logout();
        setView('success');
        return;
      }

      const body = await res.json().catch(() => null);
      if (res.status === 400 || (res.status === 422 && isTokenValidationError(body?.detail))) {
        // Expired, already used, malformed, or the account is gone. The
        // server's wording differs per case; the way forward does not.
        setView('invalid');
        return;
      }
      if (res.status === 422) {
        // The local check passed, so what is left is the server's
        // common-password list.
        setError(
          t('auth.password_too_common', {
            defaultValue: 'This password is too common. Please choose a less predictable one.',
          }),
        );
        return;
      }
      setError(t('auth.reset_error', { defaultValue: 'Unable to process reset request. Please try again.' }));
    } catch {
      setError(t('auth.server_error', { defaultValue: 'Unable to connect to server. Please try again.' }));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-surface-secondary p-4 overflow-hidden">
      {/* Animated gradient blobs */}
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

      <div className="relative z-10 w-full max-w-[400px]">
        {/* Logo — glow entrance */}
        <div className="mb-8 text-center animate-stagger-in" style={{ animationDelay: '0ms' }}>
          <div className="mx-auto mb-4 animate-logo-glow rounded-[20px] w-fit">
            <Logo size="xl" animate className="mx-auto shadow-xl" />
          </div>
        </div>

        {/* Form card — glass morphism + scale-in entrance */}
        <div
          className="glass-strong rounded-2xl p-7 shadow-lg animate-form-scale-in"
          style={{ animationDelay: '150ms' }}
        >
          {view === 'success' && (
            <div className="text-center py-4 animate-stagger-in" role="status" aria-live="polite" style={{ animationDelay: '200ms' }}>
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-semantic-success-bg text-semantic-success">
                <CheckCircle2 size={28} />
              </div>
              <h2 className="text-lg font-semibold text-content-primary mb-2">
                {t('auth.reset_success_title', { defaultValue: 'Password changed' })}
              </h2>
              <p className="text-sm text-content-secondary mb-6">
                {t('auth.reset_success_body', {
                  defaultValue: 'Your password has been changed. Sign in with your new password.',
                })}
              </p>
              <Link
                to="/login"
                className="inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
              >
                <ArrowLeft size={14} />
                {t('auth.back_to_login', { defaultValue: 'Back to sign in' })}
              </Link>
            </div>
          )}

          {view === 'invalid' && (
            <div className="text-center py-4 animate-stagger-in" role="alert" style={{ animationDelay: '200ms' }}>
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-semantic-error-bg text-semantic-error">
                <AlertTriangle size={28} />
              </div>
              <h2 className="text-lg font-semibold text-content-primary mb-2">
                {t('auth.reset_link_invalid_title', { defaultValue: 'This link no longer works' })}
              </h2>
              <p className="text-sm text-content-secondary mb-6">
                {t('auth.reset_link_invalid_body', {
                  defaultValue:
                    'The reset link has expired, has already been used, or is incomplete. Request a new one to continue.',
                })}
              </p>
              <Link
                to="/forgot-password"
                className="inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
              >
                {t('auth.reset_request_new_link', { defaultValue: 'Request a new link' })}
              </Link>
            </div>
          )}

          {view === 'form' && (
            <>
              <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
                <Link
                  to="/login"
                  className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
                >
                  <ArrowLeft size={14} />
                  {t('auth.back_to_login', { defaultValue: 'Back to sign in' })}
                </Link>

                <h2 className="text-lg font-semibold text-content-primary mb-1">
                  {t('auth.reset_title', { defaultValue: 'Set a new password' })}
                </h2>
                <p className="text-sm text-content-secondary mb-6">
                  {t('auth.reset_subtitle', { defaultValue: 'Choose a new password for your account.' })}
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4" noValidate>
                <div className="animate-stagger-in" style={{ animationDelay: '300ms' }}>
                  <Input
                    id="reset-new-password"
                    name="new_password"
                    label={t('auth.reset_new_password', { defaultValue: 'New password' })}
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={t('auth.password_min', { defaultValue: 'Minimum 8 characters' })}
                    hint={t('auth.password_requirements', {
                      defaultValue: 'Password must be at least 8 characters with at least one letter and one digit',
                    })}
                    autoComplete="new-password"
                    required aria-required="true"
                    autoFocus
                    icon={<Lock size={15} />}
                    suffix={
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        aria-label={showPassword
                          ? t('auth.hide_password', { defaultValue: 'Hide password' })
                          : t('auth.show_password', { defaultValue: 'Show password' })}
                        className="flex items-center text-content-tertiary hover:text-content-secondary transition-colors"
                        tabIndex={-1}
                      >
                        {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    }
                  />
                </div>

                <div className="animate-stagger-in" style={{ animationDelay: '340ms' }}>
                  <Input
                    id="reset-confirm-password"
                    name="confirm_password"
                    label={t('auth.confirm_password', { defaultValue: 'Confirm Password' })}
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder={t('auth.confirm_password_placeholder', { defaultValue: 'Repeat your password' })}
                    autoComplete="new-password"
                    required aria-required="true"
                    error={confirmPassword && !passwordsMatch
                      ? t('auth.passwords_mismatch', { defaultValue: 'Passwords do not match' })
                      : undefined}
                    icon={<Lock size={15} />}
                  />
                </div>

                {/* Error */}
                {error && (
                  <div role="alert" className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3.5 py-2.5 text-sm text-semantic-error animate-stagger-in">
                    <span className="shrink-0 mt-0.5">!</span>
                    <span>{error}</span>
                  </div>
                )}

                <div className="animate-stagger-in" style={{ animationDelay: '380ms' }}>
                  <Button
                    type="submit"
                    variant="primary"
                    size="lg"
                    loading={loading}
                    className="w-full btn-shimmer"
                  >
                    {t('auth.reset_submit', { defaultValue: 'Save new password' })}
                  </Button>
                </div>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
