// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { BadgeVariant } from '@/shared/ui';

export function statusVariant(status: string): BadgeVariant {
  switch (status) {
    case 'published':
      return 'blue';
    case 'awarded':
      return 'success';
    case 'cancelled':
      return 'error';
    default:
      return 'neutral';
  }
}

export const STATUS_DEFAULTS: Record<string, string> = {
  draft: 'Draft',
  published: 'Published',
  awarded: 'Awarded',
  cancelled: 'Cancelled',
};

export const MODE_DEFAULTS: Record<string, string> = {
  per_project_contracts: 'One contract per project',
  framework_call_off: 'Framework agreement and call-offs',
};

export const KIND_DEFAULTS: Record<string, string> = {
  subcontract: 'Subcontract',
  supply: 'Supply',
};
