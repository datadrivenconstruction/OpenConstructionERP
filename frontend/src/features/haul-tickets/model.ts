// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { BadgeVariant } from '@/shared/ui/Badge';
import type { Ticket, TicketStatus } from './api';

export const STATUS_VARIANT: Record<TicketStatus, BadgeVariant> = {
  issued: 'neutral',
  loaded: 'blue',
  delivered: 'purple',
  verified: 'success',
  invoiced: 'success',
  rejected: 'error',
};

/** Buttons offered per status; the server holds the full transition table and refuses the rest. */
export const NEXT_STATUS: Record<TicketStatus, TicketStatus[]> = {
  issued: ['delivered', 'rejected'],
  loaded: ['delivered', 'rejected'],
  delivered: ['verified', 'rejected'],
  verified: ['invoiced'],
  invoiced: [],
  rejected: ['issued'],
};

/** Net tonnes from gross minus tare, or null when a weight is missing or tare exceeds gross. */
export function netTonnes(gross: string, tare: string): string | null {
  const g = Number(gross);
  const t = Number(tare);
  if (!gross || !tare || !Number.isFinite(g) || !Number.isFinite(t) || t > g) return null;
  return (Math.round((g - t) * 1000) / 1000).toString();
}

export function totalsOf(rows: Pick<Ticket, 'quantity' | 'amount' | 'status'>[]) {
  let quantity = 0;
  let amount = 0;
  for (const r of rows) {
    if (r.status === 'rejected') continue;
    quantity += Number(r.quantity) || 0;
    amount += Number(r.amount) || 0;
  }
  return { quantity, amount };
}
