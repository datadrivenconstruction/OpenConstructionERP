// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Public funding's contribution to the Module Insights panel.
 *
 * The register shows one row per application. What a funding officer needs
 * before a review meeting is the shape of the portfolio: how much has been
 * awarded against how much has actually arrived, where the money is sitting
 * by programme, and how the deadlines fall across the next months. A table
 * sorted by code hides all three.
 *
 * Everything is derived from the applications and obligations the page has
 * already loaded, so the panel costs no extra request. With nothing loaded
 * the datasets are empty and the panel draws nothing rather than inventing a
 * portfolio.
 *
 * Money arrives from the API as exact decimal strings and is converted here,
 * once, for charting. The converted number never goes back to the screen as
 * an amount; the string does.
 */
import { useTranslation } from 'react-i18next';

import type { InsightDataset, InsightDef } from '@/features/insights';

import { toMoney } from './api';
import type { FundingApplication, FundingObligation, FundingProgramme } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

export interface FundingInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/** Sortable YYYY-MM key so a time series stays chronological. */
function monthKey(day: string): string {
  const trimmed = (day || '').slice(0, 7);
  return /^\d{4}-\d{2}$/.test(trimmed) ? trimmed : '';
}

/**
 * Build the funding datasets and the charts that ship with the module.
 *
 * `programmes` is a lookup rather than a list because the interesting
 * grouping is by programme name, and the application only carries the id.
 * A missing programme degrades to its id rather than dropping the row: an
 * application whose catalogue entry has gone is exactly the one somebody
 * needs to see.
 */
export function buildFundingInsights(
  applications: FundingApplication[],
  obligations: FundingObligation[],
  programmes: Map<string, FundingProgramme>,
  t: Translate,
): FundingInsights {
  const applicationRows = applications.map((row) => {
    const programme = programmes.get(row.programme_id);
    return {
      code: row.code,
      status: t(`funding.status.${row.status}`, { defaultValue: row.status }),
      programme: programme ? programme.name || programme.code : row.programme_id,
      authority: programme ? programme.authority_name : '',
      instrument: programme
        ? t(`funding.instrument.${programme.instrument}`, { defaultValue: programme.instrument })
        : '',
      requested: toMoney(row.requested_amount),
      approved: toMoney(row.approved_amount),
      eligible_base: toMoney(row.eligible_cost_base),
      own_share: toMoney(row.own_share_amount),
      // The difference between what was asked for and what was granted is
      // the number that tells a bidder whether their next application is
      // realistic, and no column on the register holds it.
      shortfall: Math.max(toMoney(row.requested_amount) - toMoney(row.approved_amount), 0),
    };
  });

  const obligationRows = obligations
    .filter((row) => monthKey(row.due_on))
    .map((row) => ({
      month: monthKey(row.due_on),
      // The server names the kind; the constructed key is the fallback for a
      // row that predates `title_key`. Same order as `obligationLabel`, so the
      // chart category and the list entry cannot drift apart.
      kind: t(row.title_key || `funding.obligation_kind.${row.kind}`, { defaultValue: row.kind }),
      source: t(`funding.obligation_source.${row.source}`, { defaultValue: row.source }),
      status: row.overdue
        ? t('funding.obligation_overdue', { defaultValue: 'Overdue' })
        : t(`funding.obligation_status.${row.status}`, { defaultValue: row.status }),
      count: 1,
    }));

  const currency = applications.find((row) => row.currency)?.currency ?? '';

  const datasets: InsightDataset[] = [
    {
      id: 'funding_applications',
      label: t('funding.insights.ds_applications', { defaultValue: 'Funding applications' }),
      rows: applicationRows,
      currency,
      fields: [
        { key: 'code', label: t('funding.field.code', { defaultValue: 'Reference' }), kind: 'dimension' },
        { key: 'status', label: t('funding.field.status', { defaultValue: 'Status' }), kind: 'dimension' },
        {
          key: 'programme',
          label: t('funding.field.programme', { defaultValue: 'Programme' }),
          kind: 'dimension',
        },
        {
          key: 'authority',
          label: t('funding.field.authority', { defaultValue: 'Authority' }),
          kind: 'dimension',
        },
        {
          key: 'instrument',
          label: t('funding.field.instrument', { defaultValue: 'Instrument' }),
          kind: 'dimension',
        },
        {
          key: 'requested',
          label: t('funding.field.requested', { defaultValue: 'Requested' }),
          kind: 'measure',
          format: 'currency',
        },
        {
          key: 'approved',
          label: t('funding.field.approved', { defaultValue: 'Approved' }),
          kind: 'measure',
          format: 'currency',
        },
        {
          key: 'eligible_base',
          label: t('funding.field.eligible_base', { defaultValue: 'Eligible cost base' }),
          kind: 'measure',
          format: 'currency',
        },
        {
          key: 'own_share',
          label: t('funding.field.own_share', { defaultValue: 'Own contribution' }),
          kind: 'measure',
          format: 'currency',
        },
        {
          key: 'shortfall',
          label: t('funding.field.shortfall', { defaultValue: 'Not awarded' }),
          kind: 'measure',
          format: 'currency',
        },
      ],
    },
    {
      id: 'funding_obligations',
      label: t('funding.insights.ds_obligations', { defaultValue: 'Funding deadlines' }),
      rows: obligationRows,
      // No currency: a deadline carries no money, and a currency-formatted
      // count of deadlines would read as an amount of money.
      currency: '',
      fields: [
        { key: 'month', label: t('funding.field.month', { defaultValue: 'Month due' }), kind: 'dimension' },
        { key: 'kind', label: t('funding.field.kind', { defaultValue: 'Kind' }), kind: 'dimension' },
        { key: 'source', label: t('funding.field.source', { defaultValue: 'Source' }), kind: 'dimension' },
        { key: 'status', label: t('funding.field.status', { defaultValue: 'Status' }), kind: 'dimension' },
        { key: 'count', label: t('funding.field.count', { defaultValue: 'Deadlines' }), kind: 'measure' },
      ],
    },
  ];

  const builtins: InsightDef[] = [
    {
      id: 'funding_approved_total',
      title: t('funding.insights.approved_total', { defaultValue: 'Approved funding' }),
      datasetId: 'funding_applications',
      chart: 'kpi',
      measure: 'approved',
      agg: 'sum',
      builtin: true,
      color: 0,
    },
    {
      id: 'funding_by_programme',
      title: t('funding.insights.by_programme', { defaultValue: 'Approved by programme' }),
      datasetId: 'funding_applications',
      chart: 'bar',
      dimension: 'programme',
      measure: 'approved',
      agg: 'sum',
      builtin: true,
      color: 1,
    },
    {
      id: 'funding_by_status',
      title: t('funding.insights.by_status', { defaultValue: 'Applications by status' }),
      datasetId: 'funding_applications',
      chart: 'donut',
      dimension: 'status',
      agg: 'count',
      builtin: true,
      color: 2,
    },
    {
      id: 'funding_deadlines_by_month',
      title: t('funding.insights.deadlines_by_month', { defaultValue: 'Deadlines by month' }),
      datasetId: 'funding_obligations',
      chart: 'bar',
      dimension: 'month',
      agg: 'count',
      builtin: true,
      color: 3,
    },
  ];

  return { datasets, builtins };
}
