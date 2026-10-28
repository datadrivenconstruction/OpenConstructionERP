// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sales-manager UI panel for buyer self-service portal magic links.
 *
 * Dropped inside the BuyerDetailDrawer (and the Reservation / SPA
 * drawers via the same component) — lists active tokens for the
 * buyer, lets a manager mint a fresh one, copy the URL, and revoke.
 *
 * Visibility: MANAGER+ (mirrors the backend ``RequireRole("manager")``
 * gate on ``POST /portal/issue/``).
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Link as LinkIcon, Loader2, Plus, ShieldOff } from 'lucide-react';
import { copyToClipboard } from '@/shared/lib/browser';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  issuePortalToken,
  listBuyerPortalTokens,
  revokePortalToken,
  type PortalIssueResponse,
} from './api';
import { getIntlLocale } from '@/shared/lib/formatters';

interface Props {
  buyerId: string;
  reservationId?: string | null;
  salesContractId?: string | null;
}

export function BuyerAccessLinkPanel({
  buyerId,
  reservationId,
  salesContractId,
}: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  // Manager+ gate — mirror the backend RequireRole("manager") on issue/.
  const userRole = useAuthStore((s) => s.userRole);
  const canManage = (() => {
    if (!userRole) return false;
    const r = userRole.toLowerCase();
    return ['admin', 'superuser', 'owner', 'manager'].includes(r);
  })();

  const tokensQ = useQuery({
    queryKey: ['propdev', 'portal-links', buyerId],
    queryFn: () => listBuyerPortalTokens(buyerId),
    enabled: canManage,
  });

  const [freshIssued, setFreshIssued] = useState<PortalIssueResponse | null>(
    null,
  );
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle');

  const issueMut = useMutation({
    mutationFn: () =>
      issuePortalToken({
        buyer_id: buyerId,
        reservation_id: reservationId ?? undefined,
        sales_contract_id: salesContractId ?? undefined,
      }),
    onSuccess: (res) => {
      setFreshIssued(res);
      qc.invalidateQueries({
        queryKey: ['propdev', 'portal-links', buyerId],
      });
    },
  });

  const revokeMut = useMutation({
    mutationFn: (tokenId: string) => revokePortalToken(tokenId),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ['propdev', 'portal-links', buyerId],
      });
    },
  });

  async function copy(url: string) {
    try {
      await copyToClipboard(url);
      setCopyState('copied');
      setTimeout(() => setCopyState('idle'), 1500);
    } catch {
      // Clipboard API can fail under HTTP / cross-origin; fall back to
      // a transient selection box.
      const ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        setCopyState('copied');
        setTimeout(() => setCopyState('idle'), 1500);
      } finally {
        document.body.removeChild(ta);
      }
    }
  }

  if (!canManage) return null;

  const rows = tokensQ.data ?? [];
  const issuing = issueMut.isPending;

  return (
    <section
      data-testid="buyer-access-link-panel"
      className="rounded-xl border border-border-light bg-surface-secondary/40 p-3 space-y-3"
    >
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary flex items-center gap-1.5">
          <LinkIcon size={12} aria-hidden />
          {t('buyer_portal_panel.title', {
            defaultValue: 'Buyer access link',
          })}
        </h3>
        <button
          type="button"
          onClick={() => issueMut.mutate()}
          disabled={issuing}
          className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-oe-blue text-white text-2xs font-medium hover:bg-oe-blue-hover disabled:opacity-50"
          data-testid="issue-portal-link"
        >
          {issuing ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            <Plus size={11} />
          )}
          {t('buyer_portal_panel.issue', { defaultValue: 'Issue new link' })}
        </button>
      </header>

      {/* Just-issued banner — plaintext URL only shown once. */}
      {freshIssued && (
        <div
          data-testid="fresh-link-banner"
          className="rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 px-2.5 py-2 text-2xs space-y-1.5"
        >
          <p className="font-medium text-amber-900 dark:text-amber-200">
            {t('buyer_portal_panel.copy_now', {
              defaultValue:
                'Copy this URL now - it will not be shown again.',
            })}
          </p>
          <div className="flex items-center gap-1.5">
            <input
              readOnly
              value={freshIssued.portal_url}
              onFocus={(e) => e.currentTarget.select()}
              className="flex-1 h-7 px-2 rounded border border-border-light bg-surface-primary text-2xs font-mono text-content-primary"
              aria-label={t('buyer_portal_panel.url', {
                defaultValue: 'Portal URL',
              })}
            />
            <button
              type="button"
              onClick={() => copy(freshIssued.portal_url)}
              className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-surface-elevated border border-border-light text-2xs font-medium text-content-primary hover:bg-surface-secondary"
              data-testid="copy-fresh-link"
            >
              <Copy size={10} />
              {copyState === 'copied'
                ? t('buyer_portal_panel.copied', { defaultValue: 'Copied!' })
                : t('buyer_portal_panel.copy', { defaultValue: 'Copy' })}
            </button>
          </div>
        </div>
      )}

      {/* Active token list */}
      {tokensQ.isLoading ? (
        <p className="text-2xs text-content-tertiary">
          {t('buyer_portal_panel.loading', { defaultValue: 'Loading…' })}
        </p>
      ) : rows.length === 0 ? (
        <p className="text-2xs text-content-tertiary">
          {t('buyer_portal_panel.empty', {
            defaultValue: 'No active links. Issue one to share with the buyer.',
          })}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
              data-testid={`portal-link-row-${row.id}`}
            >
              <div className="min-w-0 text-2xs">
                <p className="text-content-primary font-medium truncate">
                  {row.jwt_id.slice(0, 12)}…
                </p>
                <p className="text-content-tertiary">
                  {t('buyer_portal_panel.expires', {
                    defaultValue: 'Expires {{date}}',
                    date: new Date(row.expires_at).toLocaleDateString(getIntlLocale()),
                  })}
                  {row.last_used_at && (
                    <>
                      {' · '}
                      {t('buyer_portal_panel.last_used', {
                        defaultValue: 'last used {{date}}',
                        date: new Date(row.last_used_at).toLocaleDateString(getIntlLocale()),
                      })}
                    </>
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={() => revokeMut.mutate(row.id)}
                disabled={revokeMut.isPending}
                className="inline-flex items-center gap-1 h-6 px-2 rounded text-2xs font-medium text-semantic-error hover:bg-semantic-error/10 disabled:opacity-50"
                data-testid={`revoke-${row.id}`}
              >
                <ShieldOff size={10} />
                {t('buyer_portal_panel.revoke', { defaultValue: 'Revoke' })}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
