// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Per-recipient bidder link on the distribution list.
 *
 * A firm prices the bill through a personal web link instead of an account.
 * The link's token is shown once, when it is made, so "Copy bidder link"
 * always makes a fresh link and copies it; the link sent earlier stops working
 * and the firm keeps whatever it already typed. For a firm that already
 * submitted, copying is an explicit reopen of its bid, confirmed first. The
 * badge says how far the firm got: not opened, opened, submitted, expired or
 * revoked.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link2 } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { ConfirmDialog } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import { createBidLink, listBidInvitations, type BidInvitation, type BidInvitationStatus } from './bidInvitations';

const STATUS_VARIANT: Record<BidInvitationStatus, BadgeVariant> = {
  not_opened: 'neutral',
  opened: 'blue',
  submitted: 'success',
  expired: 'warning',
  revoked: 'neutral',
};

export function bidInvitationsQueryKey(packageId: string) {
  return ['tendering-bid-invitations', packageId] as const;
}

/** The newest link of one recipient, or undefined when it never had one. */
export function latestInvitation(items: BidInvitation[], recipientId: string): BidInvitation | undefined {
  return items.find((i) => i.recipient_id === recipientId);
}

export function BidLinkCell({ packageId, recipientId }: { packageId: string; recipientId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [shownUrl, setShownUrl] = useState<string | null>(null);

  // One request per package; every row reads the same cached list.
  const invitationsQ = useQuery({
    queryKey: bidInvitationsQueryKey(packageId),
    queryFn: () => listBidInvitations(packageId),
    staleTime: 15_000,
  });
  const latest = latestInvitation(invitationsQ.data?.items ?? [], recipientId);

  const statusLabel = (status: BidInvitationStatus): string => {
    switch (status) {
      case 'opened':
        return t('tendering.bid_link.status_opened', { defaultValue: 'Link opened' });
      case 'submitted':
        return t('tendering.bid_link.status_submitted', { defaultValue: 'Prices submitted' });
      case 'expired':
        return t('tendering.bid_link.status_expired', { defaultValue: 'Link expired' });
      case 'revoked':
        return t('tendering.bid_link.status_revoked', { defaultValue: 'Link revoked' });
      default:
        return t('tendering.bid_link.status_not_opened', { defaultValue: 'Link not opened' });
    }
  };

  const mutation = useMutation({
    mutationFn: (reopen: boolean) => createBidLink(packageId, recipientId, { reopen }),
    onSuccess: async (created) => {
      queryClient.invalidateQueries({ queryKey: bidInvitationsQueryKey(packageId) });
      // The API may answer with a path only; the bidder needs the full address.
      const url = created.url.startsWith('/') ? `${window.location.origin}${created.url}` : created.url;
      try {
        await navigator.clipboard.writeText(url);
        setShownUrl(null);
        addToast({
          type: 'success',
          title: t('tendering.bid_link.copied', { defaultValue: 'Bidder link copied' }),
          message: t('tendering.bid_link.copied_hint', {
            defaultValue: 'Paste it into your email to the firm. It opens the bill without an account.',
          }),
        });
      } catch {
        // No clipboard (insecure context, permission): show it to copy by hand.
        setShownUrl(url);
      }
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('tendering.bid_link.failed', { defaultValue: 'Could not make the bidder link' }),
        message: error.message,
      });
    },
  });

  const onCopy = async () => {
    // A submitted bid stays closed unless the buyer reopens it here, on purpose.
    const reopen = latest?.status === 'submitted';
    const live = latest && (latest.status === 'not_opened' || latest.status === 'opened' || reopen);
    if (live) {
      const ok = await confirm({
        title: reopen
          ? t('tendering.bid_link.reopen_title', { defaultValue: 'Reopen this bid?' })
          : t('tendering.bid_link.replace_title', { defaultValue: 'Make a new bidder link?' }),
        message: reopen
          ? t('tendering.bid_link.replace_submitted', {
              defaultValue:
                'This firm has already submitted. A new link lets it change its prices and submit again; its bid is updated, not duplicated. The previous link stops working.',
            })
          : t('tendering.bid_link.replace_message', {
              defaultValue:
                'Links are shown only once, so copying makes a new one. The link sent earlier stops working; the firm keeps the prices it already entered.',
            }),
        confirmLabel: reopen
          ? t('tendering.bid_link.reopen_confirm', { defaultValue: 'Reopen and copy link' })
          : t('tendering.bid_link.replace_confirm', { defaultValue: 'Make new link' }),
        variant: 'warning',
      });
      if (!ok) return;
    }
    mutation.mutate(reopen);
  };

  return (
    <div className="flex shrink-0 flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        {latest && (
          <Badge variant={STATUS_VARIANT[latest.status] ?? 'neutral'} size="sm">
            {statusLabel(latest.status)}
          </Badge>
        )}
        <button
          type="button"
          onClick={onCopy}
          disabled={mutation.isPending}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-oe-blue transition-colors hover:bg-oe-blue-subtle disabled:opacity-50"
          title={t('tendering.bid_link.copy_hint', {
            defaultValue: 'A personal link where this firm enters its unit prices online',
          })}
          data-testid={`bid-link-copy-${recipientId}`}
        >
          <Link2 size={12} aria-hidden />
          {t('tendering.bid_link.copy', { defaultValue: 'Copy bidder link' })}
        </button>
      </div>
      {shownUrl && (
        <input
          readOnly
          value={shownUrl}
          onFocus={(e) => e.currentTarget.select()}
          aria-label={t('tendering.bid_link.manual_copy', { defaultValue: 'Bidder link, copy it by hand' })}
          className="w-64 rounded border border-border-light bg-surface-secondary px-2 py-1 text-2xs text-content-secondary"
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
