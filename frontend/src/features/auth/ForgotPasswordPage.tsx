import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft, Mail, CheckCircle2, Globe, ChevronDown } from 'lucide-react';
import { Button, Input, Logo, CountryFlag } from '@/shared/ui';
import { SUPPORTED_LANGUAGES, getLanguageByCode } from '@/app/i18n';
import { AuthBackground } from './AuthBackground';

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
          {submitted ? (
            /* Success state */
            <div className="text-center py-4 animate-stagger-in" style={{ animationDelay: '200ms' }}>
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-semantic-success-bg text-semantic-success">
                <CheckCircle2 size={28} />
              </div>
              <h2 className="text-lg font-semibold text-content-primary mb-2">
                {t('auth.check_email', 'Check your email')}
              </h2>
              <p className="text-sm text-content-secondary mb-6">
                {t('auth.reset_sent', { defaultValue: "If an account exists for {{email}}, you'll receive a password reset link shortly.", email })}
              </p>
              <Link
                to="/login"
                className="inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
              >
                <ArrowLeft size={14} />
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
                  <ArrowLeft size={14} />
                  {t('auth.back_to_login', 'Back to sign in')}
                </Link>

                <h2 className="text-lg font-semibold text-content-primary mb-1">
                  {t('auth.forgot_password', 'Forgot password?')}
                </h2>
                <p className="text-sm text-content-secondary mb-6">
                  {t('auth.forgot_subtitle', "Enter your email and we'll send you a reset link.")}
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="animate-stagger-in" style={{ animationDelay: '300ms' }}>
                  <Input
                    label={t('auth.email', 'Email')}
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    required
                    autoFocus
                    icon={<Mail size={16} />}
                  />
                </div>

                {/* Error */}
                {error && (
                  <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3.5 py-2.5 text-sm text-semantic-error animate-stagger-in">
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
