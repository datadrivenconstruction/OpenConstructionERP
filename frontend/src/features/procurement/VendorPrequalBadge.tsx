// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Vendor prequalification badge for procurement PO rows (TOP-30 #20).
 *
 * Resolves a PO vendor's prequalification / block / rating status from its
 * CRM ``vendor_contact_id`` and renders a compact pill so the buyer sees, at
 * a glance, whether the vendor behind a purchase order is a blocked, a
 * non-prequalified, or a low-rated subcontractor.
 *
 * Renders nothing while loading, on error, or when the contact is not a
 * registered subcontractor (an ad-hoc supplier carries no prequal record), so
 * it is safe to drop next to a vendor name in a table cell.
 *
 * The hard-block / non-prequalified gate is enforced server-side on PO
 * create + issue; this badge is the read-side surfacing of the same verdict.
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { getVendorEligibility } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

interface VendorPrequalBadgeProps {
  /** CRM contact id the PO references via ``vendor_contact_id``. */
  contactId?: string | null;
  /** Hide the badge when the vendor is fully prequalified (default false). */
  hideWhenEligible?: boolean;
}

// Below this score (0..100) a prequalified vendor still earns a "low rating"
// amber pill so buyers notice a slipping but not-yet-blocked supplier. Mirrors
// the ScorecardTile amber threshold (>= 60 amber, < 60 red) used in the
// subcontractors scorecard.
const LOW_RATING_THRESHOLD = 60;

export function VendorPrequalBadge({
  contactId,
  hideWhenEligible = false,
}: VendorPrequalBadgeProps) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['procurement', 'vendorEligibility', contactId],
    queryFn: () => getVendorEligibility(contactId as string),
    enabled: !!contactId,
    retry: false,
    staleTime: 60_000,
  });

  if (!contactId || q.isLoading || q.isError || !q.data) return null;

  const { known, awardable, is_blocked, rating_score } = q.data;

  // Ad-hoc supplier (not a registered subcontractor) - no prequal record,
  // nothing to surface.
  if (!known) return null;

  if (is_blocked) {
    return (
      <Badge variant="error" size="sm" dot>
        {t('procurement.vendor_blocked', { defaultValue: 'Blocked' })}
      </Badge>
    );
  }

  if (!awardable) {
    return (
      <Badge variant="warning" size="sm" dot>
        {t('procurement.vendor_not_prequalified', {
          defaultValue: 'Not prequalified',
        })}
      </Badge>
    );
  }

  const score = rating_score == null ? null : Number(rating_score);
  if (score != null && Number.isFinite(score) && score > 0 && score < LOW_RATING_THRESHOLD) {
    return (
      <Badge variant="warning" size="sm" dot>
        {t('procurement.vendor_low_rating', {
          defaultValue: 'Low rating ({{score}})',
          score: fmtFixed(score, 0),
        })}
      </Badge>
    );
  }

  if (hideWhenEligible) return null;
  return (
    <Badge variant="success" size="sm" dot>
      {t('procurement.vendor_prequalification', { defaultValue: 'Prequalified' })}
    </Badge>
  );
}
