// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Subcontractor-portal payments page — the public, magic-link-authed surface
 * where a subcontractor lists and submits payment applications.
 *
 * Auth model (NOT the internal JWT):
 *   - A magic-link lands here as /portal/payments?token=<magic-link>. On mount
 *     we consume it via POST /portal/auth/consume, store the returned session
 *     token in sessionStorage, then strip ?token from the URL.
 *   - On a return visit the stored session token is reused.
 *   - A 401 anywhere clears the token and drops back to the sign-in prompt so
 *     the user re-opens their invitation link.
 *
 * This deliberately renders WITHOUT the internal app shell (it is reachable by
 * external subcontractors), mirroring features/buyer-portal.
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import { Loader2, AlertCircle, KeyRound, Receipt, FileText, ArrowLeft } from 'lucide-react';
import { Card, EmptyState } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { PaymentApplicationList } from './PaymentApplicationList';
import { PaymentApplicationForm } from './PaymentApplicationForm';
import { PaymentApplicationDetailModal } from './PaymentApplicationDetailModal';
import { PortalProgressReportsTab } from './PortalProgressReportsTab';
import { consumePortalMagicLink, getPortalSessionToken } from './api';
import { PortalBrandHeader } from './PortalBrandHeader';
import { RequestSignInLink } from './RequestSignInLink';

type View = 'list' | 'form';
type Tab = 'payments' | 'progress';

export function PortalPaymentsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const magicToken = params.get('token');
  // An internal staff member can land here without a magic link (e.g. via a
  // bookmark or a stale link). When they do, the sign-in wall below offers an
  // escape back into the app: to the dashboard if a session is known, else to
  // /login (which itself bounces an already-signed-in cookie session straight
  // to the dashboard, so /login is always a safe destination).
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const escapeTo = isAuthenticated ? '/' : '/login';

  const [authed, setAuthed] = useState<boolean>(() => !!getPortalSessionToken());
  const [authError, setAuthError] = useState<string | null>(null);
  const [consuming, setConsuming] = useState<boolean>(!!magicToken);
  const [tab, setTab] = useState<Tab>('payments');
  const [view, setView] = useState<View>('list');
  const [openId, setOpenId] = useState<string | null>(null);

  // Guards the magic-link consume against React StrictMode's double-invoke
  // (and any other remount). Without this the effect fires twice: the first
  // call consumes the one-time link and opens a session, the second races in
  // and gets "Magic link already consumed", flipping the UI to a false
  // "Sign-in failed" even though a valid session token was just stored. We
  // remember the token we already started consuming and short-circuit a
  // repeat for the same token.
  const consumedTokenRef = useRef<string | null>(null);

  // Consume a magic-link token if present in the URL, then clean the URL.
  // The ref dedupe guarantees the one-time link is consumed exactly once even
  // under StrictMode's double-invoke, so the state updates here run
  // unconditionally (no per-invocation "cancelled" guard — that previously
  // left the page stuck on "Signing you in…" when the duplicate effect was
  // short-circuited and never reached the finally).
  useEffect(() => {
    if (!magicToken) return;
    if (consumedTokenRef.current === magicToken) return;
    consumedTokenRef.current = magicToken;
    setConsuming(true);
    setAuthError(null);
    consumePortalMagicLink(magicToken)
      .then((res) => {
        setAuthed(true);
        // An explicit, inviter-chosen redirect wins: forward the now-signed-in
        // user to it. Guard against an open redirect by only honouring a
        // same-origin app path ("/..." but not "//host" or a full URL); the
        // token is stripped from the URL in the finally below.
        const target = res.redirect_path?.trim();
        if (target && target.startsWith('/') && !target.startsWith('//')) {
          navigate(target, { replace: true });
        }
      })
      .catch((err: unknown) => {
        // If a valid session token already landed (e.g. a duplicated consume
        // where the first call succeeded), trust it rather than showing an
        // error for the losing duplicate request.
        if (getPortalSessionToken()) {
          setAuthed(true);
          return;
        }
        setAuthError(err instanceof Error ? err.message : 'Sign-in failed');
      })
      .finally(() => {
        setConsuming(false);
        // Strip the one-time token from the address bar.
        const next = new URLSearchParams(params);
        next.delete('token');
        setParams(next, { replace: true });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [magicToken]);

  if (consuming) {
    return (
      <CenteredShell>
        <Card padding="lg" className="flex flex-col items-center gap-3 text-center">
          <Loader2 className="animate-spin text-oe-blue" size={28} />
          <p className="text-sm text-content-secondary">
            {t('payportal.signing_in', { defaultValue: 'Signing you in…' })}
          </p>
        </Card>
      </CenteredShell>
    );
  }

  if (!authed) {
    return (
      <CenteredShell>
        <Card padding="none" className="w-full max-w-md">
          <EmptyState
            icon={authError ? <AlertCircle size={22} /> : <KeyRound size={22} />}
            title={
              authError
                ? t('payportal.signin_failed', { defaultValue: 'Sign-in failed' })
                : t('payportal.signin_title', {
                    defaultValue: 'Sign in to the subcontractor portal',
                  })
            }
            description={
              authError ??
              t('payportal.signin_prompt', {
                defaultValue: 'Open the secure link from your invitation email to continue.',
              })
            }
          />
          <div className="border-t border-border-light px-6 pb-6 pt-4">
            <RequestSignInLink />
          </div>
        </Card>
        {/* Escape hatch — a stranded internal user (no magic link, no app
            shell) can get back into OpenConstructionERP instead of being
            trapped on the sign-in wall. */}
        <Link
          to={escapeTo}
          className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-oe-blue transition-colors hover:underline"
        >
          <ArrowLeft size={14} />
          {t('payportal.back_to_app', { defaultValue: 'Back to OpenConstructionERP' })}
        </Link>
      </CenteredShell>
    );
  }

  // Authenticated surface.
  return (
    <CenteredShell>
      <div className="w-full max-w-2xl space-y-4">
        {/* Tabs — only shown on the list view so the submit form is full-bleed. */}
        {view === 'list' ? (
          <nav className="flex gap-1 border-b border-border-light">
            {(
              [
                {
                  id: 'payments',
                  label: t('payportal.tab_payments', { defaultValue: 'Payments' }),
                  icon: Receipt,
                },
                {
                  id: 'progress',
                  label: t('payportal.tab_progress', { defaultValue: 'Progress Reports' }),
                  icon: FileText,
                },
              ] as { id: Tab; label: string; icon: React.ElementType }[]
            ).map((it) => {
              const Icon = it.icon;
              return (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => setTab(it.id)}
                  className={clsx(
                    '-mb-px flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                    tab === it.id
                      ? 'border-oe-blue text-oe-blue'
                      : 'border-transparent text-content-secondary hover:text-content-primary',
                  )}
                >
                  <Icon size={14} />
                  {it.label}
                </button>
              );
            })}
          </nav>
        ) : null}

        {tab === 'progress' ? (
          <PortalProgressReportsTab />
        ) : view === 'form' ? (
          <PaymentApplicationForm
            onCancel={() => setView('list')}
            onDone={() => setView('list')}
          />
        ) : (
          <PaymentApplicationList onNew={() => setView('form')} onOpen={setOpenId} />
        )}
      </div>
      {openId ? (
        <PaymentApplicationDetailModal id={openId} onClose={() => setOpenId(null)} />
      ) : null}
    </CenteredShell>
  );
}

function CenteredShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-surface-secondary px-4 py-6">
      <div className="mx-auto flex w-full max-w-2xl flex-col items-center">
        <PortalBrandHeader />
        {children}
      </div>
    </div>
  );
}
