// Cells and rows of the tender comparison CSV.
//
// The rows carry text typed by others (package names, bidder names), so every
// field is quoted and a leading = + - @ is defused: a bidder called
// "=HYPERLINK(...)" must not run as a formula in the spreadsheet that opens the
// export.

type TFunc = (key: string, opts?: Record<string, unknown>) => string;

/** One CSV field: quoted, inner quotes doubled, formula lead-ins neutralised. */
export function csvCell(value: string | number | null | undefined): string {
  let s = value === null || value === undefined ? '' : String(value);
  // A plain negative number such as "-4.5%" is data, not a formula.
  if (/^[=+\-@\t\r]/.test(s) && !/^-\d+(\.\d+)?%?$/.test(s)) s = `'${s}`;
  return `"${s.replace(/"/g, '""')}"`;
}

export function csvRow(values: Array<string | number | null | undefined>): string {
  return values.map(csvCell).join(',');
}

/** Package and bid statuses, in the words the tendering screen uses. */
export function tenderStatusLabel(status: string, t: TFunc): string {
  const labels: Record<string, string> = {
    draft: t('tendering.status_draft', { defaultValue: 'Draft' }),
    issued: t('tendering.status_issued', { defaultValue: 'Issued' }),
    collecting: t('tendering.status_collecting', { defaultValue: 'Collecting' }),
    evaluating: t('tendering.status_evaluating', { defaultValue: 'Evaluating' }),
    awarded: t('tendering.status_awarded', { defaultValue: 'Awarded' }),
    closed: t('tendering.status_closed', { defaultValue: 'Closed' }),
    pending: t('tendering.status_pending', { defaultValue: 'Pending' }),
    submitted: t('tendering.status_submitted', { defaultValue: 'Submitted' }),
    accepted: t('tendering.status_accepted', { defaultValue: 'Accepted' }),
    rejected: t('tendering.status_rejected', { defaultValue: 'Rejected' }),
  };
  return labels[status] ?? status;
}

export interface BidTotal {
  company_name: string;
  total: number | string;
  currency: string;
  deviation_pct: number;
  /** False when the server could not compare the bid with the budget. */
  deviation_known?: boolean;
  status: string;
}

/**
 * One bidder row. The server reports a deviation of 0 when the budget is zero
 * or the bid is in another currency; printing "0.0%" there reads as an exact
 * match, so the cell says N/A instead.
 */
export function bidTotalRow(bt: BidTotal, budgetTotal: number | string, t: TFunc, naLabel: string): string {
  const known = bt.deviation_known ?? Number(budgetTotal) > 0;
  const deviation = known && Number(budgetTotal) > 0 ? `${Number(bt.deviation_pct).toFixed(1)}%` : naLabel;
  return csvRow([bt.company_name, Number(bt.total).toFixed(2), bt.currency, deviation, tenderStatusLabel(bt.status, t)]);
}
