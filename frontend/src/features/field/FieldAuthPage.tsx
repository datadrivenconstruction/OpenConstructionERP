// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field-worker PIN redemption screen.
 *
 * The SMS magic link points at `/field/{token}`; this screen collects the
 * 6-digit PIN, exchanges `(token, pin)` for a long-lived field session via
 * `POST /v1/field-diary/auth/consume/`, persists it into sessionStorage (the
 * keys the field shell reads), then routes to `/field`.
 *
 * Deliberately standalone: no desktop AppLayout, no JWT. The session token +
 * PIN are the only credentials a field worker holds.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { Loader2, LogIn } from 'lucide-react';
import { persistFieldSession } from './fieldApi';

interface ConsumeResponse {
  session_token: string;
  project_id: string;
  user_id: string;
  module_key: string;
}

export function FieldAuthPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token = '' } = useParams<{ token: string }>();
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (!/^\d{6}$/.test(pin)) {
      setError(t('field.auth_pin_invalid', { defaultValue: 'Enter the 6-digit PIN from your SMS.' }));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch('/api/v1/field-diary/auth/consume/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ token, pin }),
      });
      if (!res.ok) {
        const detail =
          (await res
            .clone()
            .json()
            .then((d: { detail?: string }) => d?.detail)
            .catch(() => undefined)) ?? `HTTP ${res.status}`;
        setError(typeof detail === 'string' ? detail : t('field.auth_failed', { defaultValue: 'Sign-in failed.' }));
        return;
      }
      const data = (await res.json()) as ConsumeResponse;
      persistFieldSession({
        token: data.session_token,
        pin,
        projectId: data.project_id,
        userId: data.user_id ?? '',
      });
      navigate('/field', { replace: true });
    } catch {
      setError(t('field.auth_network', { defaultValue: 'Network error - check your connection and retry.' }));
    } finally {
      setBusy(false);
    }
  }, [pin, token, navigate, t]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-white px-6">
      <div className="flex w-full max-w-sm flex-col gap-5">
        <div className="text-center">
          <h1 className="text-xl font-semibold text-slate-900">
            {t('field.auth_title', { defaultValue: 'Field sign-in' })}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {t('field.auth_subtitle', { defaultValue: 'Enter the 6-digit PIN from your SMS to start.' })}
          </p>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-sm text-slate-600">{t('field.auth_pin', { defaultValue: 'PIN' })}</span>
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submit();
            }}
            placeholder="000000"
            className="h-14 rounded-xl border border-slate-300 px-4 text-center text-2xl tracking-[0.5em]"
            aria-label={t('field.auth_pin', { defaultValue: 'PIN' })}
          />
        </label>

        {error && <p className="text-sm text-rose-600">{error}</p>}

        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || pin.length !== 6}
          className="flex h-14 items-center justify-center gap-2 rounded-xl bg-sky-600 text-base font-semibold text-white disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" /> : <LogIn size={20} aria-hidden="true" />}
          {t('field.auth_submit', { defaultValue: 'Sign in' })}
        </button>
      </div>
    </div>
  );
}

export default FieldAuthPage;
