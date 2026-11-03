// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shown on /field while queued work is held because the session or PIN was
 * refused. Nothing is lost or retried meanwhile: entering the PIN again lifts
 * the hold and the backlog goes out in its original order.
 */

import { useState, useSyncExternalStore } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyRound } from 'lucide-react';
import { isAuthHeld, releaseAuthHold, subscribeAuthHold } from '@/shared/lib/offline';
import { readFieldSession, persistFieldSession } from './fieldApi';

export function FieldReauthBanner({ onReleased }: { onReleased: () => void }) {
  const { t } = useTranslation();
  const held = useSyncExternalStore(
    subscribeAuthHold,
    () => isAuthHeld('field'),
    () => false,
  );
  const [pin, setPin] = useState('');
  if (!held) return null;

  const submit = () => {
    const session = readFieldSession();
    if (!session || !/^\d{6}$/.test(pin)) return;
    persistFieldSession({ ...session, pin });
    setPin('');
    releaseAuthHold('field');
    onReleased();
  };

  return (
    <div role="alert" data-testid="field-reauth" className="border-b border-amber-200 bg-amber-50 px-4 py-3">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-amber-900">
        <KeyRound size={16} aria-hidden="true" />
        {t('field.reauth_title', { defaultValue: 'Your work is saved. Enter your PIN to send it.' })}
      </p>
      <div className="mt-2 flex gap-2">
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit();
          }}
          aria-label={t('field.auth_pin', { defaultValue: 'PIN' })}
          className="h-12 w-40 rounded-xl border border-slate-300 px-3 text-center text-xl tracking-[0.4em]"
        />
        <button
          type="button"
          onClick={submit}
          disabled={pin.length !== 6}
          className="h-12 flex-1 rounded-xl bg-sky-600 text-sm font-semibold text-white disabled:opacity-50"
        >
          {t('field.reauth_submit', { defaultValue: 'Send now' })}
        </button>
      </div>
    </div>
  );
}

export default FieldReauthBanner;
