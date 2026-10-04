// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What a bid that came in through a bidder link adds to its row: a "late"
 * mark when it was submitted after the deadline, and the firm's note.
 *
 * Both live in the bid's metadata, written by the price-entry link on
 * submit; a bid typed in by staff carries neither and renders nothing here.
 */

import { useTranslation } from 'react-i18next';
import { MessageSquare } from 'lucide-react';

import { Badge } from '@/shared/ui';

export function bidPortalMarks(metadata: Record<string, unknown> | null | undefined): {
  late: boolean;
  note: string;
} {
  const meta = metadata ?? {};
  if (meta.source !== 'bid_portal') return { late: false, note: '' };
  const note = typeof meta.bidder_note === 'string' ? meta.bidder_note.trim() : '';
  return { late: meta.late === true, note };
}

export function BidPortalMarks({ metadata }: { metadata: Record<string, unknown> | null | undefined }) {
  const { t } = useTranslation();
  const { late, note } = bidPortalMarks(metadata);
  if (!late && !note) return null;
  return (
    <>
      {late && (
        <Badge variant="warning" size="sm" className="ml-2">
          {t('tendering.bid_late', { defaultValue: 'Late' })}
        </Badge>
      )}
      {note && (
        <span
          className="mt-0.5 flex items-start gap-1 text-xs text-content-secondary"
          title={t('tendering.bidder_note', { defaultValue: 'Note from the bidder' })}
          data-testid="bid-portal-note"
        >
          <MessageSquare
            size={10}
            className="mt-0.5 shrink-0"
            role="img"
            aria-label={t('tendering.bidder_note', { defaultValue: 'Note from the bidder' })}
          />
          <span className="whitespace-pre-line break-words">{note}</span>
        </span>
      )}
    </>
  );
}
