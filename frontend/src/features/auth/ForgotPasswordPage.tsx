import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft, Mail, CheckCircle2 } from 'lucide-react';
import { Button, Input, Logo } from '@/shared/ui';
import { AuthBackground } from './AuthBackground';

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    // In a real app, this would call a password reset API
    setSubmitted(true);
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-surface-secondary p-4 overflow-hidden">
      {/* Animated gradient blobs */}
      <AuthBackground />

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
                {t('auth.reset_sent', "If an account exists for {email}, you'll receive a password reset link shortly.").replace('{email}', email)}
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

                <div className="animate-stagger-in" style={{ animationDelay: '380ms' }}>
                  <Button
                    type="submit"
                    variant="primary"
                    size="lg"
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
