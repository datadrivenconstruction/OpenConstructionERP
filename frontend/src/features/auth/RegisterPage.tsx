import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';
import { Eye, EyeOff, Mail, Lock, User } from 'lucide-react';
import { Button, Input } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';

export function RegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const passwordsMatch = password === confirmPassword;
  const passwordLongEnough = password.length >= 8;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (!passwordsMatch) {
      setError('Passwords do not match');
      return;
    }
    if (!passwordLongEnough) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);

    try {
      // Register
      const regRes = await fetch('/api/v1/users/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, full_name: fullName }),
      });

      if (!regRes.ok) {
        const data = await regRes.json().catch(() => null);
        setError(data?.detail || 'Registration failed');
        return;
      }

      // Auto-login after registration
      const loginRes = await fetch('/api/v1/users/auth/login', {
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
      setError('Unable to connect to server');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-secondary p-4">
      <div className="w-full max-w-[400px] animate-scale-in">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-[20px] bg-oe-blue shadow-lg">
            <span className="text-2xl font-bold text-white">OE</span>
          </div>
          <h1 className="text-2xl font-bold text-content-primary">{t('app.name')}</h1>
        </div>

        {/* Register Form */}
        <div className="rounded-2xl border border-border-light bg-surface-elevated p-7 shadow-sm">
          <h2 className="text-lg font-semibold text-content-primary mb-1">
            {t('auth.create_account', 'Create account')}
          </h2>
          <p className="text-sm text-content-secondary mb-6">
            {t('auth.register_subtitle', 'Get started with OpenEstimate')}
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label={t('auth.full_name', 'Full Name')}
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="John Smith"
              required
              autoFocus
              icon={<User size={16} />}
            />

            <Input
              label={t('auth.email', 'Email')}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              autoComplete="email"
              required
              icon={<Mail size={16} />}
            />

            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-content-primary">
                {t('auth.password', 'Password')}
              </label>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
                  <Lock size={16} />
                </div>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Minimum 8 characters"
                  autoComplete="new-password"
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
              {password && (
                <div className="flex items-center gap-2 mt-1">
                  <div className={`h-1 flex-1 rounded-full ${password.length >= 8 ? 'bg-semantic-success' : 'bg-border'}`} />
                  <div className={`h-1 flex-1 rounded-full ${password.length >= 12 ? 'bg-semantic-success' : 'bg-border'}`} />
                  <div className={`h-1 flex-1 rounded-full ${/[A-Z]/.test(password) && /[0-9]/.test(password) ? 'bg-semantic-success' : 'bg-border'}`} />
                  <span className="text-2xs text-content-tertiary ml-1">
                    {password.length < 8 ? 'Weak' : password.length < 12 ? 'Good' : 'Strong'}
                  </span>
                </div>
              )}
            </div>

            <Input
              label={t('auth.confirm_password', 'Confirm Password')}
              type={showPassword ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Repeat your password"
              autoComplete="new-password"
              required
              error={confirmPassword && !passwordsMatch ? 'Passwords do not match' : undefined}
              icon={<Lock size={16} />}
            />

            {error && (
              <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg px-3.5 py-2.5 text-sm text-semantic-error">
                <span className="shrink-0 mt-0.5">!</span>
                <span>{error}</span>
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              disabled={!passwordsMatch || !passwordLongEnough}
              className="w-full"
            >
              {t('auth.create_account', 'Create account')}
            </Button>
          </form>

          <div className="mt-5 border-t border-border-light pt-5">
            <p className="text-center text-sm text-content-secondary">
              {t('auth.have_account', 'Already have an account?')}{' '}
              <Link
                to="/login"
                className="font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
              >
                {t('auth.login', 'Sign in')}
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
