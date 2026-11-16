import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import { Logo } from '@/shared/ui';
import { AuthBackground } from './AuthBackground';
import { ClassicAuthFooter } from './ClassicAuth';

/** The route the sign-up confirmation email links to (backend users/service.py builds it). */
export const VERIFY_EMAIL_ROUTE = '/auth/verify-email';

type View = 'working' | 'success' | 'invalid';

/**
 * Landing page of the sign-up confirmation link, emailed or copied by an
 * administrator: posts the token once and tells the user whether the account
 * is now active. The token leaves the address bar as soon as it is read.
 */
export function VerifyEmailPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [token] = useState(() => (searchParams.get('token') ?? '').trim());
  const [view, setView] = useState<View>(() => (token ? 'working' : 'invalid'));
  const sent = useRef(false);

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
    if (!token || sent.current) return;
    sent.current = true;
    fetch('/api/v1/users/auth/verify-email/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then((res) => setView(res.ok ? 'success' : 'invalid'))
      .catch(() => setView('invalid'));
  }, [token]);

  return (
    <div className="oe-auth relative flex min-h-screen items-center justify-center bg-surface-secondary p-4 overflow-hidden">
      <AuthBackground />
      <ClassicAuthFooter />
      <div className="relative z-10 w-full max-w-[400px]">
        <div className="mb-8 text-center">
          <Logo size="xl" className="mx-auto shadow-xl" />
        </div>
        <div className="glass-strong rounded-2xl p-7 shadow-lg text-center" role="status" aria-live="polite">
          {view === 'working' && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-content-secondary">
              <Loader2 size={18} className="animate-spin" />
              {t('auth.verify_working', { defaultValue: 'Confirming your account...' })}
            </div>
          )}
          {view === 'success' && (
            <div className="py-4">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-semantic-success-bg text-semantic-success">
                <CheckCircle2 size={28} />
              </div>
              <h2 className="oe-section-title mb-2">
                {t('auth.verify_success_title', { defaultValue: 'Account confirmed' })}
              </h2>
              <p className="text-sm text-content-secondary mb-6">
                {t('auth.verify_success_body', { defaultValue: 'Your account is active. You can sign in now.' })}
              </p>
            </div>
          )}
          {view === 'invalid' && (
            <div className="py-4">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-semantic-error-bg text-semantic-error">
                <AlertTriangle size={28} />
              </div>
              <h2 className="oe-section-title mb-2">
                {t('auth.verify_invalid_title', { defaultValue: 'Link not valid' })}
              </h2>
              <p className="text-sm text-content-secondary mb-6">
                {t('auth.verify_invalid_body', {
                  defaultValue:
                    'This confirmation link has expired or is not valid. Ask your administrator for a new one.',
                })}
              </p>
            </div>
          )}
          {view !== 'working' && (
            <Link
              to="/login"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
            >
              <ArrowLeft size={14} />
              {t('auth.back_to_login', { defaultValue: 'Back to sign in' })}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
