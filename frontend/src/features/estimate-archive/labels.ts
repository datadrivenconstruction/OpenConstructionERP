// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import type { BadgeVariant } from '@/shared/ui';
import type { SealStatus, SealSummary } from './api';

export function statusVariant(status: SealStatus): BadgeVariant {
  if (status === 'open') return 'blue';
  if (status === 'opening_requested') return 'warning';
  if (status === 'superseded') return 'neutral';
  return 'success';
}

export function receiptVariant(status: SealSummary['receipt_status']): BadgeVariant {
  if (status === 'signed' || status === 'external') return 'success';
  if (status === 'requested') return 'warning';
  return 'neutral';
}

/** The market's own word for a sealed estimate; neutral words when no profile applies. */
export function useArchiveTerm(profile: string | undefined): string {
  const { t } = useTranslation();
  const neutral = t('estimate_archive.term.neutral', { defaultValue: 'Sealed estimate' });
  switch (profile) {
    case 'de':
      return t('estimate_archive.term.de', { defaultValue: 'Urkalkulation' });
    case 'uk':
      return t('estimate_archive.term.uk', { defaultValue: 'Priced tender documents' });
    case 'fidic':
      return t('estimate_archive.term.fidic', { defaultValue: 'Rate build-up' });
    case 'us':
      return t('estimate_archive.term.us', { defaultValue: 'Escrow bid documents' });
    default:
      return neutral;
  }
}
