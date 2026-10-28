// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Supplier / subcontractor prequalification status badge (TOP-30 #20).
 *
 * A small, self-contained badge that shows whether a vendor is prequalified,
 * so procurement and tendering surfaces can warn before raising a PO against a
 * non-prequalified vendor. Reusable on purpose: it takes only a subcontractor
 * id, fetches the award-eligibility verdict, and renders a compact pill.
 *
 * Kept in the subcontractors feature (the domain owner of prequalification) so
 * other features can import it without duplicating the gate logic. Renders
 * nothing while loading or when the id is empty, so it is safe to drop next to
 * a vendor name in a table cell.
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { getAwardEligibility } from './api';

interface SupplierStatusBadgeProps {
  /** Subcontractor id to resolve prequalification status for. */
  subcontractorId?: string | null;
  /** Hide the badge entirely when the vendor is fully eligible (default false). */
  hideWhenEligible?: boolean;
}

export function SupplierStatusBadge({
  subcontractorId,
  hideWhenEligible = false,
}: SupplierStatusBadgeProps) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['subcontractors', 'awardEligibility', subcontractorId],
    queryFn: () => getAwardEligibility(subcontractorId as string),
    enabled: !!subcontractorId,
    retry: false,
    staleTime: 60_000,
  });

  if (!subcontractorId || q.isLoading || q.isError || !q.data) return null;

  const { awardable, reasons } = q.data;

  if (awardable) {
    if (hideWhenEligible) return null;
    return (
      <Badge variant="success" size="sm" dot>
        {t('procurement.vendor_prequalification', {
          defaultValue: 'Prequalified',
        })}
      </Badge>
    );
  }

  const blocked = reasons.includes('subcontractor_blocked');
  return (
    <Badge variant={blocked ? 'error' : 'warning'} size="sm" dot>
      {t('procurement.vendor_not_prequalified', {
        defaultValue: 'Not prequalified',
      })}
    </Badge>
  );
}
