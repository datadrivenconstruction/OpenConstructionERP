// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Transmittals' contribution to the Module Insights panel.
 *
 * The page already counts transmittals by status in its stats row, so none of
 * that is repeated here. What the register cannot show is the thing a document
 * controller actually chases: a transmittal goes out to several recipients at
 * once, and each of them owes a receipt separately. One outstanding recipient
 * on a ten-recipient transmittal looks identical to nine outstanding ones in
 * any transmittal-level count.
 *
 * So the dataset is one row per DISTRIBUTION LINE, meaning one recipient on one
 * transmittal. That grain is what makes "waiting on which recipient" answerable
 * at all. It also means row counts here are recipient lines, never transmittals,
 * which is why the dataset label says so out loud.
 *
 * This deliberately shares no code with the approvals register's panel. That
 * one walks a sequential queue and asks which single approver holds the next
 * decision; recipients here are a parallel fan-out with no ordering and no
 * per-step decision, so the only thing the two have in common is the shape of
 * the file.
 *
 * Three rules keep the numbers honest:
 *
 * 1. Drafts are excluded entirely. Nothing has been sent, so no recipient owes
 *    a receipt, and counting them would invent a chase list out of work still
 *    being written.
 * 2. Waiting time runs from `issued_date`, never from `created_at`, so a
 *    transmittal that sat in draft for a month does not bill that month to the
 *    recipient. A record with no issue date is skipped rather than guessed at.
 * 3. Only some purposes expect a reply. `PURPOSE_DESCRIPTIONS` on the page says
 *    for_information needs none and for_record is archival, and for_tender is
 *    "issued for tender", which is not a promise to answer. So a response is
 *    owed when the purpose is for_approval or for_review, or when someone set a
 *    response due date on the record itself. The second half of that is the
 *    important half: an explicit due date is a decision about this transmittal
 *    and outranks the category.
 *
 * Receipt acknowledgement is not gated by purpose. Proving who received a
 * document is the reason the module exists, and that holds even for a
 * for_information issue.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { Transmittal, TransmittalPurpose } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

const DAY_MS = 24 * 60 * 60 * 1000;

/** Purposes that ask the recipient for something back. See rule 3 above. */
const RESPONSE_EXPECTED: readonly TransmittalPurpose[] = ['for_approval', 'for_review'];

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

/** Same keys the page's badges use, so a bar label reads like the badge. */
function purposeLabel(code: string, t: Translate): string {
  return t(`transmittals.purpose_${code}`, { defaultValue: titleCase(code) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`transmittals.status_${code}`, { defaultValue: titleCase(code) });
}

/** Sortable YYYY-MM key so a time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function expectsResponse(tr: Transmittal): boolean {
  return RESPONSE_EXPECTED.includes(tr.purpose) || tr.response_due != null;
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  transmittal: string;
  recipient: string;
  company: string;
  purpose: string;
  status: string;
  month: string;
  outstanding: number;
  awaiting_response: number;
  overdue: number;
  days_waiting: number;
}

/**
 * One distribution line. Returns null for anything that cannot honestly be
 * measured: a draft, or an issued record with no issue date on it.
 */
function toRows(tr: Transmittal, noCompany: string, t: Translate): Row[] {
  if (tr.status === 'draft' || !tr.issued_date) return [];
  const issued = new Date(tr.issued_date).getTime();
  if (Number.isNaN(issued)) return [];

  const owesResponse = expectsResponse(tr);
  const due = tr.response_due ? new Date(tr.response_due).getTime() : NaN;
  const now = Date.now();

  return tr.recipients.map((r) => {
    // Waiting stops at the receipt for an acknowledged line and keeps running
    // for one still outstanding, so a stale line looks worse every week.
    const ackAt = r.acknowledged_at ? new Date(r.acknowledged_at).getTime() : NaN;
    const end = r.acknowledged && !Number.isNaN(ackAt) ? ackAt : now;
    const hasResponse = Boolean(r.response?.trim());

    return {
      transmittal: tr.transmittal_number,
      recipient: r.name,
      company: r.company?.trim() || noCompany,
      purpose: purposeLabel(tr.purpose, t),
      status: statusLabel(tr.status, t),
      month: monthKey(tr.issued_date as string),
      outstanding: r.acknowledged ? 0 : 1,
      awaiting_response: owesResponse && !hasResponse ? 1 : 0,
      // Overdue needs a real due date to be past, so it is always a subset of
      // awaiting_response: setting a due date makes a response expected.
      overdue: !Number.isNaN(due) && now > due && !hasResponse ? 1 : 0,
      days_waiting: Math.max(0, Math.floor((end - issued) / DAY_MS)),
    };
  });
}

export interface TransmittalsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the distribution-line dataset and its built-in charts. A transmittal
 * carries documents, not money, so there is no currency-formatted measure.
 */
export function buildTransmittalsInsights(
  transmittals: Transmittal[],
  t: Translate,
): TransmittalsInsights {
  const noCompany = t('transmittals.insights.no_company', { defaultValue: 'No company recorded' });

  // Drafts and undated records drop out, so a register holding only drafts has
  // nothing to measure and the dataset is legitimately empty.
  const rows: Row[] = [...transmittals]
    .sort((a, b) => new Date(a.issued_date ?? 0).getTime() - new Date(b.issued_date ?? 0).getTime())
    .flatMap((tr) => toRows(tr, noCompany, t));

  const dataset: InsightDataset = {
    id: 'lines',
    // Names the grain on purpose: every count below is recipient lines, not
    // transmittals, and the stats row above the panel counts transmittals.
    label: t('transmittals.insights.ds_lines', {
      defaultValue: 'Distribution lines, one per recipient',
    }),
    currency: '',
    fields: [
      { key: 'transmittal', label: t('transmittals.insights.f_transmittal', { defaultValue: 'Transmittal' }), kind: 'dimension' },
      { key: 'recipient', label: t('transmittals.insights.f_recipient', { defaultValue: 'Recipient' }), kind: 'dimension' },
      { key: 'company', label: t('transmittals.insights.f_company', { defaultValue: 'Company' }), kind: 'dimension' },
      { key: 'purpose', label: t('transmittals.insights.f_purpose', { defaultValue: 'Purpose' }), kind: 'dimension' },
      { key: 'status', label: t('transmittals.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('transmittals.insights.f_month', { defaultValue: 'Month issued' }), kind: 'dimension' },
      { key: 'outstanding', label: t('transmittals.insights.f_outstanding', { defaultValue: 'Receipt not acknowledged' }), kind: 'measure', format: 'number' },
      { key: 'awaiting_response', label: t('transmittals.insights.f_awaiting_response', { defaultValue: 'Response owed' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('transmittals.insights.f_overdue', { defaultValue: 'Response past its due date' }), kind: 'measure', format: 'number' },
      { key: 'days_waiting', label: t('transmittals.insights.f_days_waiting', { defaultValue: 'Days to acknowledge' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'lines', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-outstanding', title: t('transmittals.insights.k_outstanding', { defaultValue: 'Receipts not acknowledged' }), chart: 'kpi', measure: 'outstanding', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-awaiting-response', title: t('transmittals.insights.k_awaiting_response', { defaultValue: 'Responses owed' }), chart: 'kpi', measure: 'awaiting_response', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-overdue', title: t('transmittals.insights.k_overdue', { defaultValue: 'Responses past due' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-days', title: t('transmittals.insights.k_days', { defaultValue: 'Avg days to acknowledge' }), chart: 'kpi', measure: 'days_waiting', agg: 'avg', color: 5 },
    { ...base, id: 'bar-outstanding-by-recipient', title: t('transmittals.insights.c_outstanding_by_recipient', { defaultValue: 'Waiting on which recipient' }), chart: 'bar', dimension: 'recipient', measure: 'outstanding', agg: 'sum', color: 4 },
    { ...base, id: 'bar-days-by-company', title: t('transmittals.insights.c_days_by_company', { defaultValue: 'Average days to acknowledge by company' }), chart: 'bar', dimension: 'company', measure: 'days_waiting', agg: 'avg', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
