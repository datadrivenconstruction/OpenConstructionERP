// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Compliance status pill — green active / amber expiring / red expired / grey other.

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import type { ComplianceStatus } from './types';

const STATUS_TO_VARIANT: Record<
  ComplianceStatus,
  'success' | 'warning' | 'error' | 'neutral'
> = {
  active: 'success',
  // Not an error and not cover: neutral, so it never reads as live green.
  not_yet_effective: 'neutral',
  expiring_soon: 'warning',
  expired: 'error',
  cancelled: 'neutral',
  void: 'neutral',
};

const STATUS_LABEL_FALLBACK: Record<ComplianceStatus, string> = {
  active: 'Active',
  not_yet_effective: 'Not yet in effect',
  expiring_soon: 'Expiring soon',
  expired: 'Expired',
  cancelled: 'Cancelled',
  void: 'Void',
};

export interface ComplianceStatusBadgeProps {
  status: ComplianceStatus;
  className?: string;
}

export function ComplianceStatusBadge({
  status,
  className,
}: ComplianceStatusBadgeProps) {
  const { t } = useTranslation();
  const variant = STATUS_TO_VARIANT[status] ?? 'neutral';
  const label = t(`compliance.status.${status}`, {
    defaultValue: STATUS_LABEL_FALLBACK[status] ?? status,
  });
  return (
    <Badge variant={variant} size="sm" dot className={className}>
      {label}
    </Badge>
  );
}
