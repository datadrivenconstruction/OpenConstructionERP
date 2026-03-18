import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';
import { Eye, EyeOff, Mail, Lock } from 'lucide-react';
import { Button, Input, Logo } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { AuthBackground } from './AuthBackground';

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await fetch('/api/v1/users/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.detail || 'Invalid email or password');
        return;
      }

      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      navigate('/');
    } catch {
      setError('Unable to connect to server. Please try again.');
    } finally {
      setLoading(false);
    }
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
          <h1 className="text-2xl font-bold text-content-primary">
            Open<span className="gradient-text">Estimator</span>
            <span className="text-content-tertiary">.io</span>
          </h1>
          <p className="mt-1.5 text-sm text-content-secondary">{t('app.tagline')}</p>
        </div>

        {/* Form card — glass morphism + scale-in entrance */}
        <div
          className="glass-strong rounded-2xl p-7 shadow-lg animate-form-scale-in"
          style={{ animationDelay: '150ms' }}
        >
          <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
            <h2 className="text-lg font-semibold text-content-primary mb-1">
              {t('auth.login', 'Sign in')}
            </h2>
            <p className="text-sm text-content-secondary mb-6">
              {t('auth.login_subtitle', 'Enter your credentials to access your workspace')}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email — staggered */}
            <div className="animate-stagger-in" style={{ animationDelay: '280ms' }}>
              <Input
                label={t('auth.email', 'Email')}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                autoComplete="email"
                required
                autoFocus
                icon={<Mail size={16} />}
              />
            </div>

            {/* Password — staggered */}
            <div
              className="flex flex-col gap-1.5 animate-stagger-in"
              style={{ animationDelay: '360ms' }}
            >
              <div className="flex items-center justify-between">
                <label htmlFor="login-password" className="text-sm font-medium text-content-primary">
                  {t('auth.password', 'Password')}
                </label>
                <Link
                  to="/forgot-password"
                  className="text-xs font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
                >
                  {t('auth.forgot_password', 'Forgot password?')}
                </Link>
              </div>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
                  <Lock size={16} />
                </div>
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  required
                  minLength={8}
                  className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-10 text-sm text-content-primary placeholder:text-content-tertiary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-content-tertiary hover:text-content-secondary transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3.5 py-2.5 text-sm text-semantic-error animate-stagger-in">
                <span className="shrink-0 mt-0.5">!</span>
                <span>{error}</span>
              </div>
            )}

            {/* Submit — shimmer on hover */}
            <div className="animate-stagger-in" style={{ animationDelay: '440ms' }}>
              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={loading}
                className="w-full btn-shimmer"
              >
                {t('auth.login', 'Sign in')}
              </Button>
            </div>
          </form>

          {/* Footer */}
          <div
            className="mt-5 border-t border-border-light pt-5 animate-stagger-in"
            style={{ animationDelay: '520ms' }}
          >
            <p className="text-center text-sm text-content-secondary">
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

        <p
          className="mt-6 text-center text-xs text-content-tertiary animate-stagger-in"
          style={{ animationDelay: '600ms' }}
        >
          OpenEstimator.io v0.1.0 — AGPL-3.0
        </p>
      </div>
    </div>
  );
}
