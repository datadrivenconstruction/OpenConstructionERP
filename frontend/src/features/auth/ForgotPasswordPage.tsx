// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertCircle, ArrowLeft, Mail, CheckCircle2, Globe, ChevronDown } from 'lucide-react';
import { Button, Input, BrandLockup, CountryFlag } from '@/shared/ui';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '@/app/i18n';
import { sortLanguagesByName } from '@/shared/lib/languageOrder';
import { AuthBackground } from './AuthBackground';
import { ClassicAuthFooter } from './ClassicAuth';

export function ForgotPasswordPage() {
  const { t, i18n } = useTranslation();
  const currentLang = getLanguageByCode(i18n.language);
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
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

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await fetch('/api/v1/users/auth/forgot-password/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(
          data?.detail ||
            t('auth.reset_error', 'Unable to process reset request. Please try again.'),
        );
        return;
      }

      setSubmitted(true);
    } catch {
      setError(t('auth.server_error', 'Unable to connect to server. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="oe-auth relative flex min-h-screen items-center justify-center bg-surface-secondary p-4 overflow-hidden">
      {/* Animated gradient blobs */}
      <AuthBackground />
      <ClassicAuthFooter />

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

      <div className="relative z-10 w-full max-w-[380px]">
        {/* Same brand block as sign-in, so the four auth screens read as one flow. */}
        <div className="mb-5 flex flex-col items-center animate-stagger-in" style={{ animationDelay: '0ms' }}>
          <BrandLockup size="lg" animate />
          <p className="mt-2 text-sm text-content-tertiary">
            {t('login.workspace_tagline', { defaultValue: 'Professional construction project workspace' })}
          </p>
        </div>

        {/* Form card — glass morphism + scale-in entrance */}
        <div
          className="glass-strong rounded-2xl px-6 py-5 shadow-lg animate-form-scale-in"
          style={{ animationDelay: '150ms' }}
        >
          {submitted ? (
            /* Success state — generic copy avoids leaking whether the email exists */
            <div className="text-center py-2 animate-stagger-in" role="status" aria-live="polite" style={{ animationDelay: '200ms' }}>
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-semantic-success-bg text-semantic-success">
                <CheckCircle2 size={24} />
              </div>
              <h2 className="oe-section-title mb-2">
                {t('auth.check_email', 'Check your email')}
              </h2>
              <p className="text-sm text-content-secondary mb-2">
                {t('auth.reset_sent_generic', {
                  defaultValue: "If an account exists for {{email}}, we've sent password reset instructions.",
                  email,
                })}
              </p>
              <p className="text-xs text-content-tertiary mb-6">
                {t('auth.reset_check_spam', {
                  defaultValue: "Didn't receive it? Check your spam folder or try again in a few minutes.",
                })}
              </p>
              <Link
                to="/login"
                className="inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
              >
                <ArrowLeft size={14} className="rtl:rotate-180" />
                {t('auth.back_to_login', 'Back to sign in')}
              </Link>
            </div>
          ) : (
            /* Form */
            <>
              <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
                <Link
                  to="/login"
                  className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
                >
                  <ArrowLeft size={14} className="rtl:rotate-180" />
                  {t('auth.back_to_login', 'Back to sign in')}
                </Link>

                <h2 className="oe-section-title mb-0.5">
                  {t('auth.forgot_password', 'Forgot password?')}
                </h2>
                <p className="text-xs text-content-secondary mb-4">
                  {t('auth.forgot_subtitle', "Enter your email and we'll send you a reset link.")}
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-3">
                <div className="animate-stagger-in" style={{ animationDelay: '300ms' }}>
                  <Input
                    label={t('auth.email', 'Email')}
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    required aria-required="true"
                    autoFocus
                    icon={<Mail size={16} />}
                  />
                </div>

                {/* Error */}
                {error && (
                  <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3.5 py-2.5 text-sm text-semantic-error animate-stagger-in">
                    <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
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
                    {t('auth.send_reset_link', 'Send reset link')}
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
