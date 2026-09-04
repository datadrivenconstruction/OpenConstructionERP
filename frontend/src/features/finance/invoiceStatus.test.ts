// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

// Vitest runs from the frontend root, and under the Vite transform
// import.meta.url is not a file URL, so the source is reached from there.
const PAGE_SOURCE = 'src/features/finance/FinancePage.tsx';
import {
  canMarkPaid,
  invoiceStatusOptions,
  isReceivable,
  INVOICE_SELF_SERVICE_TRANSITIONS,
  INVOICE_STATUS_COLORS,
  INVOICE_STATUS_ORDER,
} from './FinancePage';

/**
 * #284: a freshly created invoice lands in 'draft' and previously had no
 * control to advance its status (the row Approve / Mark Paid buttons only show
 * from 'pending' / 'approved'). The edit-modal status dropdown fills that gap,
 * but it must NEVER offer the privileged 'approved' / 'paid' transitions -
 * those go through the manager-gated /approve and /pay endpoints (and /pay
 * writes a binding ledger entry). These tests lock that invariant in.
 */
/** Every line that opens the e-invoice dialog, and which of them run unguarded. */
function unguardedEInvoiceOpeners(source: string): { total: number; unguarded: number[] } {
  const lines = source.split('\n');
  const unguarded: number[] = [];
  let total = 0;
  lines.forEach((line, i) => {
    if (!/setEinvoiceFor\(inv\)/.test(line)) return;
    total += 1;
    const preceding = lines.slice(Math.max(0, i - 10), i).join('\n');
    if (!/isReceivable\(inv\)\s*&&/.test(preceding)) unguarded.push(i + 1);
  });
  return { total, unguarded };
}

describe('invoice status dropdown options', () => {
  it('offers draft -> pending so a new invoice can move forward', () => {
    const opts = invoiceStatusOptions('draft');
    expect(opts).toContain('draft'); // current is always present
    expect(opts).toContain('pending');
    expect(opts).toContain('cancelled');
  });

  it('lets a pending invoice go back to draft or be cancelled', () => {
    const opts = invoiceStatusOptions('pending');
    expect(opts).toEqual(expect.arrayContaining(['pending', 'draft', 'cancelled']));
  });

  it('lets a cancelled invoice be re-opened to draft', () => {
    expect(invoiceStatusOptions('cancelled')).toEqual(
      expect.arrayContaining(['cancelled', 'draft']),
    );
  });

  it('NEVER offers approve or pay from the dropdown (manager-gated only)', () => {
    for (const status of INVOICE_STATUS_ORDER) {
      const opts = invoiceStatusOptions(status);
      const reachable = opts.filter((o) => o !== status);
      expect(reachable).not.toContain('approved');
      expect(reachable).not.toContain('paid');
    }
  });

  it('returns only the current status when there is no editor-safe next step', () => {
    // approved / paid are terminal from the dropdown's perspective: the only
    // option is the current status, which the UI renders read-only.
    expect(invoiceStatusOptions('approved')).toEqual(['approved']);
    expect(invoiceStatusOptions('paid')).toEqual(['paid']);
  });

  it('keeps the self-service map a strict subset of the lifecycle vocabulary', () => {
    for (const [from, tos] of Object.entries(INVOICE_SELF_SERVICE_TRANSITIONS)) {
      expect(INVOICE_STATUS_ORDER).toContain(from);
      for (const to of tos) {
        expect(INVOICE_STATUS_ORDER).toContain(to);
      }
    }
  });

  it('reads the invoice direction from either field shape the table is fed with', () => {
    // The e-invoice action hangs off this: offered on a payable, the dialog
    // reports our own missing seller details on a document the supplier
    // issued. The rows arrive with the wire name from the API and with the
    // display alias from the legacy shape, so both have to answer.
    expect(isReceivable({ invoice_direction: 'receivable' } as never)).toBe(true);
    expect(isReceivable({ direction: 'receivable' } as never)).toBe(true);
    expect(isReceivable({ invoice_direction: 'payable', direction: 'receivable' } as never)).toBe(true);
    expect(isReceivable({ direction: 'payable' } as never)).toBe(false);
    expect(isReceivable({} as never)).toBe(false);
  });

  it('guards every place the e-invoice dialog can be opened from', () => {
    // isReceivable being correct proves nothing about where it is called, and
    // the defect this closes was a call site, not a predicate: the button was
    // offered on payables, where the dialog reports our own missing seller
    // details on a document the supplier wrote. The page renders the action
    // twice, once in the table row and once in the phone card, so the guard has
    // to be at both. Read off the source because both sites are inline in a
    // 2700 line page with no component to mount on its own, and because the
    // regression to catch is a third site shipping unguarded rather than the
    // conditional failing to work.
    const source = readFileSync(resolve(process.cwd(), PAGE_SOURCE), 'utf-8');
    const openers = unguardedEInvoiceOpeners(source);
    expect(openers.unguarded).toEqual([]);
    expect(openers.total).toBe(2);
  });

  it('would notice an unguarded site (the check above is falsifiable)', () => {
    // A scan that has never come back dirty is not evidence. Run the same
    // function over a page that opens the dialog with no guard in front of it,
    // and it has to name the line.
    const planted = [
      'const x = 1;',
      '<button onClick={() => setEinvoiceFor(inv)}>',
      '{isReceivable(inv) && (',
      '  <button onClick={() => setEinvoiceFor(inv)}>',
    ].join('\n');
    const openers = unguardedEInvoiceOpeners(planted);
    expect(openers.total).toBe(2);
    expect(openers.unguarded).toEqual([2]); // 1-based line of the bare button
  });

  it('keeps approved and sent on different badge colours', () => {
    // These two sit one row apart in the same status column, and an invoice
    // that has gone out to the client is not an invoice that has only been
    // approved internally. They shared one blue until the palette grew a
    // variant for it. Statuses that mean "nothing is in flight" are still free
    // to share neutral, so this pins the one pair that has to stay apart
    // rather than demanding a unique colour per status.
    expect(INVOICE_STATUS_COLORS.sent).not.toBe(INVOICE_STATUS_COLORS.approved);
    // ...and neither may borrow the colour that means the money arrived.
    expect(INVOICE_STATUS_COLORS.sent).not.toBe(INVOICE_STATUS_COLORS.paid);
    expect(INVOICE_STATUS_COLORS.approved).not.toBe(INVOICE_STATUS_COLORS.paid);
  });

  it('offers Mark Paid in the state approving an invoice actually produces', () => {
    // Approving writes 'sent', not 'approved': finance.service.approve_invoice
    // does `self.invoices.update(invoice_id, status="sent")`, and the v3033
    // data migration rewrote every stored 'approved' row to 'sent'. A test
    // written against the word 'approved' passes either way and proves
    // nothing, so this drives from the value the backend really stores. An
    // invoice a manager has just approved must still offer the one action a
    // person needs next.
    expect(canMarkPaid('sent')).toBe(true);
  });

  it('matches the exact status set the pay endpoint accepts', () => {
    // The cross-layer invariant. finance.service.pay_invoice guards with
    // `if prior not in ("approved", "sent")`, so the button has to be offered
    // for both and for nothing else. Offering it more widely produces a 400
    // the person cannot act on; offering it more narrowly strands the invoice.
    // 'approved' stays in the set deliberately and must not be pruned as dead:
    // posting a capture from the invoice inbox still creates its payable with
    // that status, so it is a state the product reaches today.
    const offered = INVOICE_STATUS_ORDER.filter((s) => canMarkPaid(s));
    expect(offered.sort()).toEqual(['approved', 'sent']);
  });

  it('never offers Mark Paid from a state that has not been approved', () => {
    for (const status of ['draft', 'pending', 'paid', 'cancelled', 'credit_note_issued']) {
      expect(canMarkPaid(status)).toBe(false);
    }
    // A row that arrives without a status must not get a payment button.
    expect(canMarkPaid(undefined)).toBe(false);
    expect(canMarkPaid(null)).toBe(false);
    expect(canMarkPaid('')).toBe(false);
  });

  it('keeps offering Mark Paid on the status the invoice inbox still writes', () => {
    // Guards against a future cleanup pruning 'approved' as a dead legacy
    // value. It is not dead: finance/invoice_capture_service.py posts a
    // capture by calling create_invoice(status="approved"), so a payable born
    // in the inbox arrives in that status on a fully migrated database, and
    // pay_invoice accepts it. Dropping it would leave every inbox-posted
    // invoice with no way to be marked paid.
    expect(canMarkPaid('approved')).toBe(true);
  });

  it('routes every Mark Paid site through the shared predicate', () => {
    // The page renders the invoice actions twice, once in the table row and
    // once in the phone card, and the card also gates its whole action strip
    // on a repeat of the same condition. The defect was that all of them
    // tested a status literal the application had stopped writing, so a
    // correct predicate used at two of three sites would still strand the
    // invoice on one of them. Read off the source because the sites are inline
    // in a 3600 line page with no component to mount on its own.
    const source = readFileSync(resolve(process.cwd(), PAGE_SOURCE), 'utf-8');
    const strayLiteral = source.match(/inv\.status === 'approved'/g) ?? [];
    expect(strayLiteral).toEqual([]);
    expect((source.match(/canMarkPaid\(inv\.status\)/g) ?? []).length).toBe(3);
  });

  it('preserves the canonical display order in the option list', () => {
    // draft has options draft, pending, cancelled - they must come back in
    // INVOICE_STATUS_ORDER order, not transition-map order.
    expect(invoiceStatusOptions('draft')).toEqual(['draft', 'pending', 'cancelled']);
  });
});
