// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A portal user whose link expired asks for a new one here instead of
// phoning the builder. The answer never says whether the address has access,
// because the server does not tell either.

import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Mail, MailCheck } from 'lucide-react';
import { requestPortalMagicLink } from './api';

export function RequestSignInLink() {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');

  const valid = email.trim().length > 3 && email.includes('@');

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || state === 'sending') return;
    setState('sending');
    try {
      await requestPortalMagicLink(email.trim());
      setState('sent');
    } catch {
      setState('error');
    }
  };

  if (state === 'sent') {
    return (
      <div role="status" className="flex items-start gap-2 rounded-lg bg-surface-secondary p-3 text-sm text-content-secondary">
        <MailCheck size={16} className="mt-0.5 shrink-0 text-oe-blue" />
        <span>
          {t('portal.signin_link_sent', {
            defaultValue:
              'If this address has portal access, a new sign-in link is on its way. Check your inbox and spam folder.',
          })}
        </span>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor="portal-signin-email" className="text-xs font-medium text-content-secondary">
        {t('portal.signin_link_label', { defaultValue: 'Link expired? Get a new one by email' })}
      </label>
      <div className="flex gap-2">
        <input
          id="portal-signin-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('portal.signin_link_placeholder', { defaultValue: 'you@example.com' })}
          className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
        />
        <button
          type="submit"
          disabled={!valid || state === 'sending'}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-oe-blue px-3 py-2 text-sm font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
        >
          {state === 'sending' ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />}
          {t('portal.signin_link_send', { defaultValue: 'Send link' })}
        </button>
      </div>
      {state === 'error' && (
        <p role="alert" className="text-xs text-semantic-error">
          {t('portal.signin_link_failed', {
            defaultValue: 'Could not request a link right now. Please try again in a few minutes.',
          })}
        </p>
      )}
    </form>
  );
}
