import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Button, Input } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
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
        const data = await res.json();
        setError(data.detail || 'Login failed');
        return;
      }

      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      navigate('/');
    } catch {
      setError('Connection error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-secondary p-4">
      <div className="w-full max-w-sm animate-scale-in">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-oe-blue shadow-md">
            <span className="text-xl font-bold text-white">OE</span>
          </div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('app.name')}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('app.tagline')}
          </p>
        </div>

        {/* Form */}
        <div className="rounded-2xl border border-border-light bg-surface-elevated p-6 shadow-sm">
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label={t('auth.email')}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              autoComplete="email"
              required
              error={error && email ? ' ' : undefined}
            />
            <Input
              label={t('auth.password')}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
              required
              minLength={8}
            />

            {error && (
              <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
                {error}
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              className="w-full"
            >
              {t('auth.login')}
            </Button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-content-tertiary">
          OpenEstimate v0.1.0 — AGPL-3.0
        </p>
      </div>
    </div>
  );
}
