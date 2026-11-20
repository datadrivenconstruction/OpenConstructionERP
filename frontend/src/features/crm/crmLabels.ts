import type { TFunction } from 'i18next';

const SOURCE_EN: Record<string, string> = {
  web: 'Web',
  referral: 'Referral',
  event: 'Event',
  trade_show: 'Trade show / exhibition',
  cold_outreach: 'Cold outreach',
  inbound: 'Inbound',
};

/** Translated name of a lead / deal source; unknown codes show humanised. */
export function sourceLabel(t: TFunction, code: string): string {
  return t(`crm.src_${code}`, { defaultValue: SOURCE_EN[code] ?? code.replace(/_/g, ' ') });
}
