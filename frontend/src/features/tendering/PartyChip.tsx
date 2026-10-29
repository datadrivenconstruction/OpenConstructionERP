// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Party chip on the tender invitation list.
 *
 * Shows which directory contact an invited firm is, and lets a person link,
 * unlink, or confirm the matcher's suggestion. The matcher never links on a
 * weak signal; a suggestion stays a suggestion until confirmed.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, Link2Off, UserPlus, X } from 'lucide-react';

import { Badge } from '@/shared/ui';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { useToastStore } from '@/stores/useToastStore';

import {
  decidePartySuggestion,
  linkInvitationParty,
  unlinkInvitationParty,
  type BidInvitation,
} from './bidInvitations';

export function PartyChip({ invitation }: { invitation: BidInvitation }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [picking, setPicking] = useState(false);
  const { id, package_id: packageId } = invitation;

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['tendering-bid-invitations', packageId] });
  const onError = (error: Error) =>
    addToast({
      type: 'error',
      title: t('tendering.party.failed', { defaultValue: 'Could not change the party link' }),
      message: error.message,
    });

  const link = useMutation({
    mutationFn: (contactId: string) => linkInvitationParty(packageId, id, contactId),
    onSuccess: () => {
      setPicking(false);
      return refresh();
    },
    onError,
  });
  const unlink = useMutation({
    mutationFn: () => unlinkInvitationParty(packageId, id),
    onSuccess: refresh,
    onError,
  });
  const decide = useMutation({
    mutationFn: (v: { reviewId: string; confirm: boolean }) => decidePartySuggestion(v.reviewId, v.confirm),
    onSuccess: refresh,
    onError,
  });
  const busy = link.isPending || unlink.isPending || decide.isPending;
  const btn =
    'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-medium text-oe-blue transition-colors hover:bg-oe-blue-subtle disabled:opacity-50';

  if (invitation.contact_id) {
    return (
      <div className="flex items-center gap-1" data-testid={`party-chip-${id}`}>
        <Badge variant="success" size="sm">
          {t('tendering.party.linked', { defaultValue: 'Party: {{name}}', name: invitation.contact_name || '-' })}
        </Badge>
        <button type="button" className={btn} disabled={busy} onClick={() => unlink.mutate()} data-testid={`party-unlink-${id}`}>
          <Link2Off size={12} aria-hidden />
          {t('tendering.party.unlink', { defaultValue: 'Unlink' })}
        </button>
      </div>
    );
  }

  const suggestion = invitation.suggestion;
  return (
    <div className="flex flex-col items-end gap-1" data-testid={`party-chip-${id}`}>
      <div className="flex flex-wrap items-center justify-end gap-1">
        <Badge variant="warning" size="sm">
          {t('tendering.party.none', { defaultValue: 'No party' })}
        </Badge>
        {suggestion && (
          <>
            <span className="text-2xs text-content-secondary">
              {t('tendering.party.suggested', {
                defaultValue: 'Suggested: {{name}} ({{percent}}%)',
                name: suggestion.contact_name,
                percent: Math.round(suggestion.confidence * 100),
              })}
            </span>
            <button
              type="button"
              className={btn}
              disabled={busy}
              onClick={() => decide.mutate({ reviewId: suggestion.review_id, confirm: true })}
              data-testid={`party-confirm-${id}`}
            >
              <Check size={12} aria-hidden />
              {t('tendering.party.confirm', { defaultValue: 'Confirm' })}
            </button>
            <button
              type="button"
              className={btn}
              disabled={busy}
              onClick={() => decide.mutate({ reviewId: suggestion.review_id, confirm: false })}
              data-testid={`party-reject-${id}`}
            >
              <X size={12} aria-hidden />
              {t('tendering.party.reject', { defaultValue: 'Not this one' })}
            </button>
          </>
        )}
        <button type="button" className={btn} disabled={busy} onClick={() => setPicking((v) => !v)} data-testid={`party-link-${id}`}>
          <UserPlus size={12} aria-hidden />
          {t('tendering.party.link', { defaultValue: 'Link to contact' })}
        </button>
      </div>
      {picking && (
        <div className="w-64">
          <ContactSearchInput
            value=""
            onChange={(contactId) => {
              if (contactId) link.mutate(contactId);
            }}
            placeholder={t('tendering.party.search', { defaultValue: 'Search contacts' })}
          />
        </div>
      )}
    </div>
  );
}
