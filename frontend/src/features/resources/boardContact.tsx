import { useTranslation } from 'react-i18next';
import { MessageSquare, Phone, Printer } from 'lucide-react';
import { Button } from '@/shared/ui';

/** Print rules for the dispatch board: only the board, landscape, no chrome. */
export const BOARD_PRINT_ID = 'resources-board-print';
export const BOARD_PRINT_CSS = `
@media print {
  @page { size: landscape; margin: 10mm; }
  body * { visibility: hidden !important; }
  #${BOARD_PRINT_ID}, #${BOARD_PRINT_ID} * { visibility: visible !important; }
  #${BOARD_PRINT_ID} { position: absolute; left: 0; top: 0; width: 100%; }
  #${BOARD_PRINT_ID} .overflow-x-auto { overflow: visible !important; }
  #${BOARD_PRINT_ID} table { width: 100%; font-size: 11px; border-collapse: collapse; }
  #${BOARD_PRINT_ID} th, #${BOARD_PRINT_ID} td { border: 1px solid #999; padding: 3px 6px; }
  #${BOARD_PRINT_ID} tr { break-inside: avoid; }
}
`;

/** Keep digits and a leading plus so the dialler gets a clean number. */
export function dialNumber(phone: string): string {
  const trimmed = phone.trim();
  const digits = trimmed.replace(/[^\d]/g, '');
  return trimmed.startsWith('+') ? `+${digits}` : digits;
}

export function telHref(phone: string): string {
  return `tel:${dialNumber(phone)}`;
}

export function smsHref(phone: string, body: string): string {
  return `sms:${dialNumber(phone)}?body=${encodeURIComponent(body)}`;
}

/** Phone number with tel: and sms: links; the SMS body is prefilled by the caller. */
export function BoardPhoneCell({ phone, smsBody }: { phone?: string | null; smsBody: string }) {
  const { t } = useTranslation();
  if (!phone) {
    return <span className="text-content-tertiary">—</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <a
        href={telHref(phone)}
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1 text-oe-blue hover:underline"
        title={t('resources.call_phone', { defaultValue: 'Call' })}
        data-testid="board-phone-tel"
      >
        <Phone size={11} className="shrink-0 print:hidden" />
        {phone}
      </a>
      <a
        href={smsHref(phone, smsBody)}
        onClick={(e) => e.stopPropagation()}
        className="rounded p-0.5 text-content-secondary hover:text-oe-blue print:hidden"
        aria-label={t('resources.send_sms', { defaultValue: 'Send SMS' })}
        title={t('resources.send_sms', { defaultValue: 'Send SMS' })}
        data-testid="board-phone-sms"
      >
        <MessageSquare size={12} />
      </a>
    </span>
  );
}

/** Opens the browser print dialog; the print rules above leave only the board. */
export function BoardPrintButton() {
  const { t } = useTranslation();
  return (
    <Button
      variant="secondary"
      size="sm"
      icon={<Printer size={14} />}
      onClick={() => window.print()}
      data-testid="board-print"
    >
      {t('resources.print_board', { defaultValue: 'Print / PDF' })}
    </Button>
  );
}
