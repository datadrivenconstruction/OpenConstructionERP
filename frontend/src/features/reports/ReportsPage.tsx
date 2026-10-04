// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { getIntlLocale, fmtFixed, fmtPercent } from '@/shared/lib/formatters';
import { toDisplayQuantity, displayUnitFor } from '@/shared/lib/unitConversion';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import {
  FileText,
  BarChart3,
  FileCode2,
  ShieldCheck,
  CalendarDays,
  TrendingUp,
  Download,
  Loader2,
  Settings2,
  CheckSquare2,
  Square,
  Leaf,
  DollarSign,
  ShieldAlert,
  FileEdit,
  Table2,
  PieChart,
  ClipboardCheck,
  LineChart,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Breadcrumb, EmptyState, SkeletonGrid, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { reportsGuide } from './reportsGuide';
import { bidTotalCsvRow, csvCell, csvRow, tenderStatusLabel, type BidTotal } from './tenderCsv';
import { DismissibleInfo, IntroRichText } from '@/shared/ui/DismissibleInfo';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, apiPost, extractErrorMessageFromBody, triggerDownload, type Page } from '@/shared/lib/api';
import { fetchAllPages } from '@/shared/lib/apiHelpers';
import { projectsApi, type Project } from '@/features/projects/api';
import { boqApi } from '@/features/boq/api';
import { scheduleApi } from '@/features/schedule/api';
import { costModelApi } from '@/features/costmodel/api';
import { GeneratedReportsHistory } from './GeneratedReportsHistory';

// HTML-escape user-controlled strings before they land in the HTML-report
// generators below. Pre-fix (Wave V_REPORTING audit) values like
// projectName / risk title / BOQ description were interpolated raw -
// a malicious "<img src=x onerror=...>" project name would execute in
// the recipient's browser when they opened the downloaded .html.
function esc(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ── Types ─────────────────────────────────────────────────────────────────── */

/**
 * Narrow translator signature reused by the report generators. The full i18next
 * `TFunction` type is more permissive than we need; a key + options call always
 * returns a string in our usage, and modelling it this way lets the module-level
 * download functions accept the translator without importing i18next's types.
 */
type TFunc = (key: string, opts?: Record<string, unknown>) => string;

/** Max number of BOQ positions rendered inline in a custom HTML report. */
const BOQ_DETAIL_POSITION_LIMIT = 500;

interface ReportCard {
  id: string;
  titleKey: string;
  descriptionKey: string;
  icon: LucideIcon;
  formats: ReportFormat[];
  comingSoon?: boolean;
  /** Custom download handler for reports that don't use standard BOQ export. */
  customHandler?: (projectId: string, projectName: string, t: TFunc) => Promise<void>;
}

interface ReportFormat {
  label: string;
  extension: string;
  endpoint: string;
  mediaType: string;
}

/* ── Report card definitions ───────────────────────────────────────────────── */

const REPORT_CARDS: ReportCard[] = [
  {
    id: 'boq_report',
    titleKey: 'reports.boq_report',
    descriptionKey: 'reports.boq_report_desc',
    icon: FileText,
    formats: [
      {
        label: 'PDF',
        extension: 'pdf',
        endpoint: 'export/pdf',
        mediaType: 'application/pdf',
      },
      {
        label: 'Excel',
        extension: 'xlsx',
        endpoint: 'export/excel',
        mediaType:
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      },
    ],
  },
  {
    id: 'cost_report',
    titleKey: 'reports.cost_report',
    descriptionKey: 'reports.cost_report_desc',
    icon: PieChart,
    formats: [
      {
        label: 'CSV',
        extension: 'csv',
        endpoint: '',
        mediaType: 'text/csv',
      },
    ],
    customHandler: downloadCostReport,
  },
  {
    id: 'gaeb_xml',
    titleKey: 'reports.gaeb_xml',
    descriptionKey: 'reports.gaeb_xml_desc',
    icon: FileCode2,
    formats: [
      {
        label: 'XML',
        extension: 'xml',
        endpoint: 'export/gaeb',
        mediaType: 'application/xml',
      },
    ],
  },
  {
    id: 'validation_report',
    titleKey: 'reports.validation_report',
    descriptionKey: 'reports.validation_report_desc',
    icon: ClipboardCheck,
    formats: [
      {
        label: 'CSV',
        extension: 'csv',
        endpoint: '',
        mediaType: 'text/csv',
      },
    ],
    customHandler: downloadValidationReport,
  },
  {
    id: 'schedule_report',
    titleKey: 'reports.schedule_report',
    descriptionKey: 'reports.schedule_report_desc',
    icon: CalendarDays,
    formats: [
      {
        label: 'TXT',
        extension: 'txt',
        endpoint: '',
        mediaType: 'text/plain',
      },
    ],
    customHandler: downloadScheduleReport,
  },
  {
    id: '5d_report',
    titleKey: 'reports.5d_report',
    descriptionKey: 'reports.5d_report_desc',
    icon: TrendingUp,
    formats: [
      {
        label: 'CSV',
        extension: 'csv',
        endpoint: '',
        mediaType: 'text/csv',
      },
    ],
    customHandler: download5DReport,
  },
  {
    id: 'tender_comparison',
    titleKey: 'reports.tender_comparison',
    descriptionKey: 'reports.tender_comparison_desc',
    icon: Table2,
    formats: [{ label: 'CSV', extension: 'csv', endpoint: '', mediaType: 'text/csv' }],
    customHandler: downloadTenderComparisonReport,
  },
  {
    id: 'change_order_register',
    titleKey: 'reports.change_order_register',
    descriptionKey: 'reports.change_order_register_desc',
    icon: FileEdit,
    formats: [{ label: 'CSV', extension: 'csv', endpoint: '', mediaType: 'text/csv' }],
    customHandler: downloadChangeOrderReport,
  },
  {
    id: 'risk_register',
    titleKey: 'reports.risk_register',
    descriptionKey: 'reports.risk_register_desc',
    icon: ShieldAlert,
    formats: [{ label: 'CSV', extension: 'csv', endpoint: '', mediaType: 'text/csv' }],
    customHandler: downloadRiskRegisterReport,
  },
  {
    id: 'cash_flow',
    titleKey: 'reports.cash_flow',
    descriptionKey: 'reports.cash_flow_desc',
    icon: DollarSign,
    formats: [{ label: 'CSV', extension: 'csv', endpoint: '', mediaType: 'text/csv' }],
    customHandler: downloadCashFlowReport,
  },
  {
    id: 'progress_report',
    titleKey: 'reports.progress_report',
    descriptionKey: 'reports.progress_report_desc',
    icon: LineChart,
    formats: [{ label: 'HTML', extension: 'html', endpoint: '', mediaType: 'text/html' }],
    customHandler: downloadProgressReport,
  },
];

/* ── Helpers ───────────────────────────────────────────────────────────────── */

/** Trigger a browser file download from an in-memory string. */
function downloadBlob(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  triggerDownload(blob, filename);
}

/** Format a date string for display, falling back to "-" for nulls. */
function fmtDate(d: string | null | undefined): string {
  if (!d) return '-';
  try {
    const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(d);
    return new Date(d).toLocaleDateString(getIntlLocale(), isDateOnly ? { timeZone: 'UTC' } : undefined);
  } catch {
    return d;
  }
}

/**
 * Cost Report - fetch cost model dashboard data and generate a CSV with budget,
 * committed, actual, forecast, and variance breakdown.
 */
async function downloadCostReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  let dashboard: Awaited<ReturnType<typeof costModelApi.getDashboard>>;
  try {
    dashboard = await costModelApi.getDashboard(projectId);
  } catch {
    throw new Error(
      t('reports.err_no_cost_model', {
        defaultValue:
          'No cost model data available for this project. Create a cost model with budget items first.',
      }),
    );
  }

  const csvLines: string[] = [];
  csvLines.push(t('reports.csv_cost_report', { defaultValue: 'Cost Report' }));
  csvLines.push(`${t('reports.csv_project', { defaultValue: 'Project' })},${projectName}`);
  csvLines.push(`${t('reports.csv_generated', { defaultValue: 'Generated' })},${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push(t('reports.csv_summary', { defaultValue: 'Summary' }));
  csvLines.push(`${t('reports.csv_total_budget', { defaultValue: 'Total Budget' })},${dashboard.total_budget}`);
  csvLines.push(`${t('reports.csv_total_committed', { defaultValue: 'Total Committed' })},${dashboard.total_committed}`);
  csvLines.push(`${t('reports.csv_total_actual', { defaultValue: 'Total Actual' })},${dashboard.total_actual}`);
  csvLines.push(`${t('reports.csv_total_forecast', { defaultValue: 'Total Forecast' })},${dashboard.total_forecast}`);
  csvLines.push(`${t('reports.csv_variance', { defaultValue: 'Variance' })},${dashboard.variance}`);
  csvLines.push(`${t('reports.csv_variance_pct', { defaultValue: 'Variance %' })},${dashboard.variance_pct}`);
  csvLines.push(`${t('reports.csv_spi', { defaultValue: 'SPI' })},${dashboard.spi}`);
  csvLines.push(`${t('reports.csv_cpi', { defaultValue: 'CPI' })},${dashboard.cpi}`);
  csvLines.push(`${t('reports.csv_status', { defaultValue: 'Status' })},${dashboard.status}`);
  csvLines.push(`${t('reports.csv_currency', { defaultValue: 'Currency' })},${dashboard.currency}`);

  // Include category breakdown if available
  const categories = (dashboard as unknown as Record<string, unknown>).categories as
    | Array<Record<string, unknown>>
    | undefined;
  if (categories && categories.length > 0) {
    csvLines.push('');
    csvLines.push(t('reports.csv_cost_breakdown', { defaultValue: 'Cost Breakdown by Category' }));
    csvLines.push(
      [
        t('reports.csv_col_category', { defaultValue: 'Category' }),
        t('reports.csv_col_planned', { defaultValue: 'Planned' }),
        t('reports.csv_col_actual', { defaultValue: 'Actual' }),
        t('reports.csv_col_variance', { defaultValue: 'Variance' }),
      ].join(','),
    );
    const unknownLabel = t('reports.csv_unknown', { defaultValue: 'Unknown' });
    for (const cat of categories) {
      const planned = Number(cat.planned || 0);
      const actual = Number(cat.actual || 0);
      csvLines.push(
        `${cat.category || cat.name || unknownLabel},${planned.toFixed(2)},${actual.toFixed(2)},${(planned - actual).toFixed(2)}`,
      );
    }
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_cost_report.csv`, 'text/csv');
}

/**
 * Validation Report - run BOQ validation via the backend validate endpoint and
 * generate a CSV report with all rule results.
 *
 * Requires a BOQ to be selected. When called from the report card (which only
 * passes projectId), we fetch the first BOQ for the project and validate that.
 */
async function downloadValidationReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  // Find the first BOQ for this project
  let boqs: Array<{ id: string; name: string }>;
  try {
    boqs = await boqApi.list(projectId);
  } catch {
    throw new Error(
      t('reports.err_boqs_load', { defaultValue: 'Could not load BOQs for this project.' }),
    );
  }

  if (boqs.length === 0) {
    throw new Error(
      t('reports.err_no_boq', {
        defaultValue: 'No BOQs found for this project. Create a BOQ first to run validation.',
      }),
    );
  }

  const boq = boqs[0]!;

  // Call the validate endpoint (POST /boqs/{boq_id}/validate)
  type ValidationReport = {
    boq_id: string;
    boq_name: string;
    total_positions: number;
    score: number;
    status: string;
    summary: { total: number; passed: number; warnings: number; errors: number; info: number };
    results: Array<{
      rule_id: string;
      rule_name: string;
      severity: string;
      status: string;
      message: string;
      element_ref?: string;
    }>;
  };
  let report: ValidationReport;
  try {
    report = await apiPost<ValidationReport>(`/v1/boq/boqs/${boq.id}/validate/`, {});
  } catch (err) {
    // The validate endpoint commonly fails when no validation rules are
    // enabled for the project - surface that as the actionable cause rather
    // than echoing a generic "Validation failed". A 404/501 means the
    // rule set isn't configured; point the user at Governance to set it up.
    const raw = err instanceof Error ? err.message : '';
    const looksLikeMissingRules =
      /404|not found|no rules|no validation|501|not implemented|disabled/i.test(raw);
    if (looksLikeMissingRules) {
      throw new Error(
        t('reports.err_no_validation_rules', {
          defaultValue:
            'No validation rules configured for this project. Set up validation rules in Governance first.',
        }),
      );
    }
    throw new Error(
      t('reports.err_validation_failed', {
        defaultValue: 'Validation failed: {{detail}}',
        detail: raw || t('common.unknown_error', { defaultValue: 'Unknown error' }),
      }),
    );
  }

  const csvLines: string[] = [];
  csvLines.push(t('reports.csv_validation_report', { defaultValue: 'Validation Report' }));
  csvLines.push(`${t('reports.csv_project', { defaultValue: 'Project' })},${projectName}`);
  csvLines.push(`${t('reports.csv_boq', { defaultValue: 'BOQ' })},${report.boq_name || boq.name}`);
  csvLines.push(`${t('reports.csv_generated', { defaultValue: 'Generated' })},${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push(t('reports.csv_summary', { defaultValue: 'Summary' }));
  csvLines.push(`${t('reports.csv_total_positions', { defaultValue: 'Total Positions' })},${report.total_positions}`);
  csvLines.push(`${t('reports.csv_score', { defaultValue: 'Score' })},${typeof report.score === 'number' ? (report.score * 100).toFixed(1) + '%' : t('reports.csv_na', { defaultValue: 'N/A' })}`);
  csvLines.push(`${t('reports.csv_status', { defaultValue: 'Status' })},${report.status}`);
  csvLines.push(`${t('reports.csv_rules_checked', { defaultValue: 'Rules Checked' })},${report.summary?.total ?? 0}`);
  csvLines.push(`${t('reports.csv_passed', { defaultValue: 'Passed' })},${report.summary?.passed ?? 0}`);
  csvLines.push(`${t('reports.csv_warnings', { defaultValue: 'Warnings' })},${report.summary?.warnings ?? 0}`);
  csvLines.push(`${t('reports.csv_errors', { defaultValue: 'Errors' })},${report.summary?.errors ?? 0}`);
  csvLines.push('');

  if (report.results && report.results.length > 0) {
    csvLines.push(t('reports.csv_detailed_results', { defaultValue: 'Detailed Results' }));
    csvLines.push(
      [
        t('reports.csv_col_rule_id', { defaultValue: 'Rule ID' }),
        t('reports.csv_col_rule_name', { defaultValue: 'Rule Name' }),
        t('reports.csv_col_severity', { defaultValue: 'Severity' }),
        t('reports.csv_col_status', { defaultValue: 'Status' }),
        t('reports.csv_col_message', { defaultValue: 'Message' }),
        t('reports.csv_col_element', { defaultValue: 'Element' }),
      ].join(','),
    );
    for (const r of report.results) {
      csvLines.push(
        [
          r.rule_id,
          `"${(r.rule_name || '').replace(/"/g, '""')}"`,
          r.severity,
          r.status,
          `"${(r.message || '').replace(/"/g, '""')}"`,
          r.element_ref || '',
        ].join(','),
      );
    }
  } else {
    csvLines.push(t('reports.csv_no_issues', { defaultValue: 'No validation issues found.' }));
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_validation_report.csv`, 'text/csv');
}

/**
 * Schedule Report - fetch schedules and activities, then generate a plain-text
 * summary and trigger a download.
 */
async function downloadScheduleReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  let schedules: Awaited<ReturnType<typeof scheduleApi.listSchedules>>['items'];
  try {
    schedules = (await scheduleApi.listSchedules(projectId)).items;
  } catch {
    throw new Error(
      t('reports.err_no_schedule', {
        defaultValue: 'Could not load schedule data for this project. Create a schedule first.',
      }),
    );
  }

  const lines: string[] = [
    `${t('reports.txt_schedule_report', { defaultValue: 'Schedule Report' })} - ${projectName}`,
    `${t('reports.txt_generated', { defaultValue: 'Generated' })}: ${new Date().toISOString()}`,
    '='.repeat(60),
    '',
  ];

  if (schedules.length === 0) {
    lines.push(t('reports.txt_no_schedules', { defaultValue: 'No schedules found for this project.' }));
  }

  for (const schedule of schedules) {
    lines.push(`${t('reports.txt_schedule', { defaultValue: 'Schedule' })}: ${schedule.name}`);
    lines.push(`  ${t('reports.txt_status', { defaultValue: 'Status' })}:     ${schedule.status}`);
    lines.push(`  ${t('reports.txt_start_date', { defaultValue: 'Start date' })}: ${fmtDate(schedule.start_date)}`);
    lines.push(`  ${t('reports.txt_end_date', { defaultValue: 'End date' })}:   ${fmtDate(schedule.end_date)}`);
    lines.push('');

    try {
      const gantt = await scheduleApi.getGantt(schedule.id);
      lines.push(`  ${t('reports.txt_activities_count', { defaultValue: 'Activities ({{count}} total):', count: gantt.summary.total_activities })}`);
      lines.push(
        `    ${t('reports.txt_completed', { defaultValue: 'Completed' })}: ${gantt.summary.completed}  |  ${t('reports.txt_in_progress', { defaultValue: 'In-progress' })}: ${gantt.summary.in_progress}  |  ${t('reports.txt_delayed', { defaultValue: 'Delayed' })}: ${gantt.summary.delayed}`,
      );
      lines.push('');
      lines.push(
        '  ' +
          t('reports.txt_col_wbs', { defaultValue: 'WBS' }).padEnd(14) +
          t('reports.txt_col_name', { defaultValue: 'Name' }).padEnd(32) +
          t('reports.txt_col_start', { defaultValue: 'Start' }).padEnd(14) +
          t('reports.txt_col_end', { defaultValue: 'End' }).padEnd(14) +
          t('reports.txt_col_days', { defaultValue: 'Days' }).padEnd(8) +
          t('reports.txt_col_progress', { defaultValue: 'Progress' }).padEnd(10) +
          t('reports.txt_col_status', { defaultValue: 'Status' }),
      );
      lines.push('  ' + '-'.repeat(100));

      for (const act of gantt.activities) {
        lines.push(
          '  ' +
            (act.wbs_code || '').padEnd(14) +
            act.name.substring(0, 30).padEnd(32) +
            fmtDate(act.start_date).padEnd(14) +
            fmtDate(act.end_date).padEnd(14) +
            String(act.duration_days).padEnd(8) +
            `${act.progress_pct}%`.padEnd(10) +
            act.status,
        );
      }
    } catch {
      lines.push('  ' + t('reports.txt_activities_load_fail', { defaultValue: '(Could not load activities for this schedule)' }));
    }

    lines.push('');
    lines.push('-'.repeat(60));
    lines.push('');
  }

  downloadBlob(lines.join('\n'), `${projectName}_schedule_report.txt`, 'text/plain');
}

/**
 * 5D Report - fetch dashboard data and S-curve, then generate a CSV download.
 */
async function download5DReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  let dashboard: Awaited<ReturnType<typeof costModelApi.getDashboard>>;
  let sCurveData: Awaited<ReturnType<typeof costModelApi.getSCurve>>;

  try {
    [dashboard, sCurveData] = await Promise.all([
      costModelApi.getDashboard(projectId),
      costModelApi.getSCurve(projectId),
    ]);
  } catch {
    throw new Error(
      t('reports.err_no_5d', {
        defaultValue:
          'No 5D cost model data available for this project. Create a cost model with budget and schedule data first.',
      }),
    );
  }

  const csvLines: string[] = [];

  // Dashboard summary section
  csvLines.push(t('reports.csv_5d_report', { defaultValue: '5D Cost Report' }));
  csvLines.push(`${t('reports.csv_project', { defaultValue: 'Project' })},${projectName}`);
  csvLines.push(`${t('reports.csv_generated', { defaultValue: 'Generated' })},${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push(t('reports.csv_dashboard_summary', { defaultValue: 'Dashboard Summary' }));
  csvLines.push(`${t('reports.csv_total_budget', { defaultValue: 'Total Budget' })},${dashboard.total_budget}`);
  csvLines.push(`${t('reports.csv_total_committed', { defaultValue: 'Total Committed' })},${dashboard.total_committed}`);
  csvLines.push(`${t('reports.csv_total_actual', { defaultValue: 'Total Actual' })},${dashboard.total_actual}`);
  csvLines.push(`${t('reports.csv_total_forecast', { defaultValue: 'Total Forecast' })},${dashboard.total_forecast}`);
  csvLines.push(`${t('reports.csv_variance', { defaultValue: 'Variance' })},${dashboard.variance}`);
  csvLines.push(`${t('reports.csv_variance_pct', { defaultValue: 'Variance %' })},${dashboard.variance_pct}`);
  csvLines.push(`${t('reports.csv_spi', { defaultValue: 'SPI' })},${dashboard.spi}`);
  csvLines.push(`${t('reports.csv_cpi', { defaultValue: 'CPI' })},${dashboard.cpi}`);
  csvLines.push(`${t('reports.csv_status', { defaultValue: 'Status' })},${dashboard.status}`);
  csvLines.push(`${t('reports.csv_currency', { defaultValue: 'Currency' })},${dashboard.currency}`);
  csvLines.push('');

  // S-Curve data section
  csvLines.push(t('reports.csv_scurve_data', { defaultValue: 'S-Curve Data' }));
  if (sCurveData.periods && sCurveData.periods.length > 0) {
    csvLines.push(
      [
        t('reports.csv_col_period', { defaultValue: 'Period' }),
        t('reports.csv_col_planned', { defaultValue: 'Planned' }),
        t('reports.csv_col_earned', { defaultValue: 'Earned' }),
        t('reports.csv_col_actual', { defaultValue: 'Actual' }),
      ].join(','),
    );
    for (const point of sCurveData.periods) {
      csvLines.push(`${point.period},${point.planned},${point.earned},${point.actual}`);
    }
  } else {
    csvLines.push(t('reports.csv_no_scurve', { defaultValue: 'No S-curve period data available yet.' }));
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_5d_report.csv`, 'text/csv');
}

/**
 * Tender Comparison Report - fetch tender packages and bid comparison data,
 * then generate a CSV download.
 */
async function downloadTenderComparisonReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  let packages: Array<{
    id: string; name: string; status: string; bid_count: number; deadline: string | null;
  }>;
  try {
    packages = await apiGet<Array<{
      id: string; name: string; status: string; bid_count: number; deadline: string | null;
    }>>(`/v1/tendering/packages/?project_id=${projectId}`);
  } catch {
    throw new Error(
      t('reports.err_no_tender', {
        defaultValue: 'No tender packages available for this project. Create tender packages first.',
      }),
    );
  }

  const naLabel = t('reports.csv_na', { defaultValue: 'N/A' });
  const csvLines: string[] = [];
  csvLines.push(csvCell(t('reports.csv_tender_comparison', { defaultValue: 'Tender Comparison Report' })));
  csvLines.push(csvRow([t('reports.csv_project', { defaultValue: 'Project' }), projectName]));
  csvLines.push(csvRow([t('reports.csv_generated', { defaultValue: 'Generated' }), new Date().toISOString()]));
  csvLines.push(csvRow([t('reports.csv_total_packages', { defaultValue: 'Total Packages' }), packages.length]));
  csvLines.push('');

  for (const pkg of packages) {
    csvLines.push(csvCell(`${t('reports.csv_package', { defaultValue: 'Package' })}: ${pkg.name}`));
    csvLines.push(csvRow([t('reports.csv_status', { defaultValue: 'Status' }), tenderStatusLabel(pkg.status, t)]));
    csvLines.push(csvRow([t('reports.csv_deadline', { defaultValue: 'Deadline' }), pkg.deadline || naLabel]));
    csvLines.push(csvRow([t('reports.csv_bids', { defaultValue: 'Bids' }), pkg.bid_count]));

    try {
      const comparison = await apiGet<{
        bid_count: number;
        budget_total: number;
        bid_totals: BidTotal[];
        rows: Array<{ description: string; unit: string; budget_rate: number; bids: Array<{ company_name: string; unit_rate: number; total: number }> }>;
      }>(`/v1/tendering/packages/${pkg.id}/comparison/`);

      if (comparison.bid_totals.length > 0) {
        csvLines.push('');
        csvLines.push(
          csvRow([
            t('reports.csv_col_company', { defaultValue: 'Company' }),
            t('reports.csv_col_total', { defaultValue: 'Total' }),
            t('reports.csv_col_currency', { defaultValue: 'Currency' }),
            t('reports.csv_col_deviation_pct', { defaultValue: 'Deviation %' }),
            t('reports.csv_col_status', { defaultValue: 'Status' }),
          ]),
        );
        for (const bt of comparison.bid_totals) {
          csvLines.push(bidTotalCsvRow(bt, comparison.budget_total, t, naLabel));
        }
        csvLines.push(
          csvRow([t('reports.csv_budget_total', { defaultValue: 'Budget Total' }), Number(comparison.budget_total).toFixed(2)]),
        );
      }
    } catch { /* skip comparison if unavailable */ }

    csvLines.push('');
    csvLines.push('---');
    csvLines.push('');
  }

  if (packages.length === 0) {
    csvLines.push(csvCell(t('reports.csv_no_packages', { defaultValue: 'No tender packages found for this project.' })));
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_tender_comparison.csv`, 'text/csv');
}

/**
 * Change Order Register - fetch change orders and summary, then generate a CSV
 * download with cumulative cost and schedule impact.
 */
async function downloadChangeOrderReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  let orders: Array<{
    id: string; code: string; title: string; description: string;
    reason_category: string; status: string; cost_impact: number;
    schedule_impact_days: number; currency: string; item_count: number;
    created_at: string; submitted_at: string | null; approved_at: string | null;
  }>;
  let summary: {
    total_orders: number; approved_count: number; rejected_count: number;
    total_cost_impact: number; total_schedule_impact_days: number; currency: string;
  };

  try {
    [orders, summary] = await Promise.all([
      apiGet<typeof orders>(`/v1/changeorders/?project_id=${projectId}`),
      apiGet<typeof summary>(`/v1/changeorders/summary/?project_id=${projectId}`),
    ]);
  } catch {
    throw new Error(
      t('reports.err_no_change_orders', {
        defaultValue: 'No change order data available for this project. Create change orders first.',
      }),
    );
  }

  const daysLabel = t('reports.csv_days', { defaultValue: 'days' });
  const csvLines: string[] = [];
  csvLines.push(t('reports.csv_change_order_register', { defaultValue: 'Change Order Register' }));
  csvLines.push(`${t('reports.csv_project', { defaultValue: 'Project' })},${projectName}`);
  csvLines.push(`${t('reports.csv_generated', { defaultValue: 'Generated' })},${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push(t('reports.csv_summary', { defaultValue: 'Summary' }));
  csvLines.push(`${t('reports.csv_total_orders', { defaultValue: 'Total Orders' })},${summary.total_orders}`);
  csvLines.push(`${t('reports.csv_approved', { defaultValue: 'Approved' })},${summary.approved_count}`);
  csvLines.push(`${t('reports.csv_rejected', { defaultValue: 'Rejected' })},${summary.rejected_count}`);
  csvLines.push(`${t('reports.csv_total_cost_impact', { defaultValue: 'Total Cost Impact' })},${summary.total_cost_impact} ${summary.currency}`);
  csvLines.push(`${t('reports.csv_total_schedule_impact', { defaultValue: 'Total Schedule Impact' })},${summary.total_schedule_impact_days} ${daysLabel}`);
  csvLines.push('');
  csvLines.push(
    [
      t('reports.csv_col_code', { defaultValue: 'Code' }),
      t('reports.csv_col_title', { defaultValue: 'Title' }),
      t('reports.csv_col_reason', { defaultValue: 'Reason' }),
      t('reports.csv_col_status', { defaultValue: 'Status' }),
      t('reports.csv_col_cost_impact', { defaultValue: 'Cost Impact' }),
      t('reports.csv_col_schedule_days', { defaultValue: 'Schedule Days' }),
      t('reports.csv_col_items', { defaultValue: 'Items' }),
      t('reports.csv_col_created', { defaultValue: 'Created' }),
      t('reports.csv_col_submitted', { defaultValue: 'Submitted' }),
      t('reports.csv_col_approved', { defaultValue: 'Approved' }),
    ].join(','),
  );

  for (const o of orders) {
    csvLines.push([
      o.code,
      `"${o.title.replace(/"/g, '""')}"`,
      o.reason_category,
      o.status,
      Number(o.cost_impact).toFixed(2),
      String(o.schedule_impact_days),
      String(o.item_count),
      o.created_at?.slice(0, 10) || '',
      o.submitted_at?.slice(0, 10) || '',
      o.approved_at?.slice(0, 10) || '',
    ].join(','));
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_change_orders.csv`, 'text/csv');
}

/**
 * Risk Register Report - fetch risks with probability, impact, scores, and
 * mitigation plans, then generate a CSV download.
 */
async function downloadRiskRegisterReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  type RiskRow = {
    id: string; code: string; title: string; description: string;
    probability: number; impact_cost: number; impact_severity: string;
    risk_score: number; status: string; owner_name: string | null;
    mitigation_plan: string | null; created_at: string;
  };

  // Read every page, and let a failure reach the caller.
  //
  // The route caps `limit` at 100, so one request is a page rather than the
  // register. The header rows below state Total Risks and Total Exposure, and a
  // short read turned both into confident wrong numbers inside a file the
  // reader treats as the official record. Swallowing the error was worse again:
  // it produced a clean-looking report asserting zero risks and zero exposure.
  // The caller already converts a throw into a "failed to generate" toast.
  const { items: risks, truncated, ceiling } = await fetchAllPages<RiskRow>((offset, limit) =>
    apiGet<Page<RiskRow>>(`/v1/risk/?project_id=${projectId}&limit=${limit}&offset=${offset}`),
  );

  // Refuse rather than ship a register that is quietly missing rows. The
  // ceiling is a memory guard set far above any real register, so reaching it
  // means something is wrong; either way, a partial export of a document people
  // treat as the record is the failure this whole change exists to prevent.
  // Throwing surfaces it as a toast carrying this message.
  if (truncated) {
    throw new Error(
      `The risk register exceeds the ${ceiling} row export ceiling, so this report would be incomplete.`,
    );
  }

  const csvLines: string[] = [];
  csvLines.push(t('reports.csv_risk_register', { defaultValue: 'Risk Register Report' }));
  csvLines.push(`${t('reports.csv_project', { defaultValue: 'Project' })},${projectName}`);
  csvLines.push(`${t('reports.csv_generated', { defaultValue: 'Generated' })},${new Date().toISOString()}`);
  csvLines.push(`${t('reports.csv_total_risks', { defaultValue: 'Total Risks' })},${risks.length}`);
  const totalExposure = risks.reduce((s, r) => s + r.probability * r.impact_cost, 0);
  csvLines.push(`${t('reports.csv_total_exposure', { defaultValue: 'Total Exposure' })},${totalExposure.toFixed(0)}`);
  csvLines.push('');
  csvLines.push(
    [
      t('reports.csv_col_code', { defaultValue: 'Code' }),
      t('reports.csv_col_title', { defaultValue: 'Title' }),
      t('reports.csv_col_probability', { defaultValue: 'Probability' }),
      t('reports.csv_col_impact_cost', { defaultValue: 'Impact Cost' }),
      t('reports.csv_col_severity', { defaultValue: 'Severity' }),
      t('reports.csv_col_score', { defaultValue: 'Score' }),
      t('reports.csv_col_status', { defaultValue: 'Status' }),
      t('reports.csv_col_owner', { defaultValue: 'Owner' }),
      t('reports.csv_col_mitigation', { defaultValue: 'Mitigation' }),
    ].join(','),
  );

  for (const r of risks) {
    csvLines.push([
      r.code,
      `"${r.title.replace(/"/g, '""')}"`,
      `${(r.probability * 100).toFixed(0)}%`,
      Number(r.impact_cost).toFixed(0),
      r.impact_severity,
      r.risk_score.toFixed(1),
      r.status,
      r.owner_name || '',
      `"${(r.mitigation_plan || '').replace(/"/g, '""')}"`,
    ].join(','));
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_risk_register.csv`, 'text/csv');
}

/**
 * Cash Flow Report - fetch S-curve data and generate a CSV with planned vs
 * actual cumulative and per-period spending.
 */
async function downloadCashFlowReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  let sCurve: Awaited<ReturnType<typeof costModelApi.getSCurve>>;
  try {
    sCurve = await costModelApi.getSCurve(projectId);
  } catch {
    throw new Error(
      t('reports.err_no_cash_flow', {
        defaultValue:
          'No cash flow data available for this project. Create a cost model with S-curve data first.',
      }),
    );
  }

  if (!sCurve.periods || sCurve.periods.length === 0) {
    throw new Error(
      t('reports.err_no_periods', {
        defaultValue: 'No S-curve period data found. Add budget periods to generate a cash flow report.',
      }),
    );
  }

  const csvLines: string[] = [];
  csvLines.push(t('reports.csv_cash_flow_forecast', { defaultValue: 'Cash Flow Forecast' }));
  csvLines.push(`${t('reports.csv_project', { defaultValue: 'Project' })},${projectName}`);
  csvLines.push(`${t('reports.csv_generated', { defaultValue: 'Generated' })},${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push(
    [
      t('reports.csv_col_period', { defaultValue: 'Period' }),
      t('reports.csv_col_planned_cumulative', { defaultValue: 'Planned Cumulative' }),
      t('reports.csv_col_earned_cumulative', { defaultValue: 'Earned Cumulative' }),
      t('reports.csv_col_actual_cumulative', { defaultValue: 'Actual Cumulative' }),
      t('reports.csv_col_planned_period', { defaultValue: 'Planned Period' }),
      t('reports.csv_col_actual_period', { defaultValue: 'Actual Period' }),
    ].join(','),
  );

  let prevPlanned = 0;
  let prevActual = 0;
  for (const p of sCurve.periods) {
    // S-curve money fields arrive as Decimal strings; coerce once so both
    // the per-period subtraction and .toFixed below stay numeric.
    const planned = Number(p.planned) || 0;
    const earned = Number(p.earned) || 0;
    const actual = Number(p.actual) || 0;
    const plannedPeriod = planned - prevPlanned;
    const actualPeriod = actual - prevActual;
    csvLines.push([
      p.period,
      planned.toFixed(0),
      earned.toFixed(0),
      actual.toFixed(0),
      plannedPeriod.toFixed(0),
      actualPeriod.toFixed(0),
    ].join(','));
    prevPlanned = planned;
    prevActual = actual;
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_cash_flow.csv`, 'text/csv');
}

/**
 * Progress Report - generates an HTML report combining EVM performance, schedule
 * status, and top risks into a single downloadable page.
 */
async function downloadProgressReport(
  projectId: string,
  projectName: string,
  t: TFunc,
): Promise<void> {
  const lang = getIntlLocale();
  const titleProgress = t('reports.html_progress_report', { defaultValue: 'Progress Report' });
  const htmlParts: string[] = [];
  htmlParts.push(`<!DOCTYPE html><html lang="${esc(lang)}"><head><meta charset="UTF-8"><title>${esc(projectName)} - ${esc(titleProgress)}</title>`);
  htmlParts.push('<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:900px;margin:0 auto;padding:40px 24px;color:#1a1a1a;line-height:1.6}h1{font-size:28px;border-bottom:3px solid #2563eb;padding-bottom:12px}h2{font-size:20px;color:#2563eb;margin-top:32px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb;font-size:14px}th{background:#f9fafb;font-weight:600}.metric{display:inline-block;margin:8px 16px 8px 0;padding:12px 20px;border:1px solid #e5e7eb;border-radius:8px;text-align:center}.metric-label{font-size:11px;text-transform:uppercase;color:#6b7280;letter-spacing:0.05em}.metric-value{font-size:22px;font-weight:700}p.footer{color:#9ca3af;font-size:12px;margin-top:40px;border-top:1px solid #e5e7eb;padding-top:12px}@media print{body{padding:0}}</style>');
  htmlParts.push('</head><body>');
  htmlParts.push(`<h1>${esc(projectName)} - ${esc(titleProgress)}</h1>`);
  htmlParts.push(`<p style="color:#6b7280">${esc(t('reports.html_generated', { defaultValue: 'Generated' }))}: ${esc(new Date().toLocaleString(lang))}</p>`);

  // EVM section
  try {
    const dashboard = await costModelApi.getDashboard(projectId);
    htmlParts.push(`<h2>${esc(t('reports.html_evm_performance', { defaultValue: 'Earned Value Performance' }))}</h2>`);
    htmlParts.push('<div>');
    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_spi', { defaultValue: 'SPI' }))}</div><div class="metric-value" style="color:${Number(dashboard.spi||0)>=1?'#166534':'#991b1b'}">${fmtFixed(Number(dashboard.spi||0), 2)}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_cpi', { defaultValue: 'CPI' }))}</div><div class="metric-value" style="color:${Number(dashboard.cpi||0)>=1?'#166534':'#991b1b'}">${fmtFixed(Number(dashboard.cpi||0), 2)}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_budget', { defaultValue: 'Budget' }))}</div><div class="metric-value">${Number(dashboard.total_budget||0).toLocaleString(lang)}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_actual', { defaultValue: 'Actual' }))}</div><div class="metric-value">${Number(dashboard.total_actual||0).toLocaleString(lang)}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_forecast_eac', { defaultValue: 'Forecast (EAC)' }))}</div><div class="metric-value">${Number(dashboard.total_forecast||0).toLocaleString(lang)}</div></div>`);
    htmlParts.push('</div>');
  } catch { htmlParts.push(`<p>${esc(t('reports.html_no_budget', { defaultValue: 'No budget data available.' }))}</p>`); }

  // Schedule section
  try {
    const { items: schedules } = await scheduleApi.listSchedules(projectId);
    htmlParts.push(`<h2>${esc(t('reports.html_schedule_status', { defaultValue: 'Schedule Status' }))}</h2>`);
    for (const sched of schedules) {
      try {
        const gantt = await scheduleApi.getGantt(sched.id);
        const pct = gantt.summary.total_activities > 0
          ? Math.round((gantt.summary.completed / gantt.summary.total_activities) * 100)
          : 0;
        htmlParts.push(`<h3>${esc(sched.name)}</h3>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_progress', { defaultValue: 'Progress' }))}</div><div class="metric-value">${pct}%</div></div>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_activities', { defaultValue: 'Activities' }))}</div><div class="metric-value">${gantt.summary.total_activities}</div></div>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_completed', { defaultValue: 'Completed' }))}</div><div class="metric-value">${gantt.summary.completed}</div></div>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_delayed', { defaultValue: 'Delayed' }))}</div><div class="metric-value" style="color:${gantt.summary.delayed>0?'#991b1b':'#166534'}">${gantt.summary.delayed}</div></div>`);
      } catch { /* skip */ }
    }
  } catch { htmlParts.push(`<p>${esc(t('reports.html_no_schedule', { defaultValue: 'No schedule data.' }))}</p>`); }

  // Risk highlights
  try {
    // A five-row sample under a "Top Risks" heading, with no count and no
    // aggregate printed off it, so the page envelope is read for its rows
    // only. (The route is asked for five without a sort, so these are five
    // risks rather than the five highest - a separate defect, noted not
    // fixed here.)
    const risks = (await apiGet<Page<{ code: string; title: string; risk_score: number; impact_severity: string }>>(`/v1/risk/?project_id=${projectId}&limit=5`)).items;
    if (risks.length > 0) {
      htmlParts.push(`<h2>${esc(t('reports.html_top_risks', { defaultValue: 'Top Risks' }))}</h2>`);
      htmlParts.push(`<table><thead><tr><th>${esc(t('reports.html_col_code', { defaultValue: 'Code' }))}</th><th>${esc(t('reports.html_col_risk', { defaultValue: 'Risk' }))}</th><th>${esc(t('reports.html_col_severity', { defaultValue: 'Severity' }))}</th><th>${esc(t('reports.html_col_score', { defaultValue: 'Score' }))}</th></tr></thead><tbody>`);
      const sorted = [...risks].sort((a, b) => b.risk_score - a.risk_score);
      for (const r of sorted) {
        htmlParts.push(`<tr><td>${esc(r.code)}</td><td>${esc(r.title)}</td><td>${esc(r.impact_severity)}</td><td>${fmtFixed(r.risk_score, 1)}</td></tr>`);
      }
      htmlParts.push('</tbody></table>');
    }
  } catch { /* skip */ }

  htmlParts.push(`<p class="footer">${esc(t('reports.html_footer', { defaultValue: 'Report generated by OpenConstructionERP on {{date}}', date: new Date().toLocaleString(lang) }))}</p>`);
  htmlParts.push('</body></html>');

  const blob = new Blob([htmlParts.join('\n')], { type: 'text/html' });
  triggerDownload(blob, `${projectName}_progress_report.html`);
}

async function downloadBoqExport(
  boqId: string,
  boqName: string,
  format: ReportFormat,
): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const endpoint = format.endpoint.endsWith('/') ? format.endpoint : `${format.endpoint}/`;
  const response = await fetch(`/api/v1/boq/boqs/${boqId}/${endpoint}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    // v2.9.30: parse JSON detail when available; never leak raw HTML error pages to toasts.
    let detail: string | null = null;
    const raw = await response.text().catch(() => '');
    if (raw) {
      try {
        detail = extractErrorMessageFromBody(JSON.parse(raw));
      } catch {
        detail = extractErrorMessageFromBody(raw);
      }
    }
    throw new Error(detail ? `Export failed (${response.status}): ${detail}` : `Export failed (${response.status})`);
  }

  const blob = await response.blob();
  triggerDownload(blob, `${boqName}.${format.extension}`);
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export function ReportsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const { activeProjectId } = useProjectContextStore();

  // Project & BOQ selectors
  const [projects, setProjects] = useState<Project[]>([]);
  const selectedProjectId = activeProjectId ?? '';
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [loadingProjects, setLoadingProjects] = useState(true);

  // BOQs are loaded via React Query so the request is automatically deduped
  // across StrictMode double-mounts and across any other components that ask
  // for the same project's BOQs in the same session - the previous imperative
  // useEffect issued the request twice on every fresh page mount.
  const { data: boqs = [], isLoading: loadingBoqs } = useQuery({
    queryKey: ['boqs', selectedProjectId],
    queryFn: () => boqApi.list(selectedProjectId),
    enabled: !!selectedProjectId,
    staleTime: 30_000,
  });

  // Per-format loading state: "cardId:extension"
  const [downloading, setDownloading] = useState<string | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [builderSections, setBuilderSections] = useState<Set<string>>(
    new Set(['summary', 'budget', 'cost_breakdown', 'boq_detail']),
  );
  const [builderGenerating, setBuilderGenerating] = useState(false);

  // Load projects on mount.
  //
  // We deliberately fire-and-forget here without an unmount guard: the previous
  // version had `[activeProjectId, setActiveProject]` in the dep array, so when
  // the effect itself called setActiveProject(first) the store update bumped
  // activeProjectId, the effect re-ran (no-op via useRef guard), the cleanup
  // flipped cancelled=true, and the in-flight `setLoadingProjects(false)` was
  // skipped - leaving the page wedged on the spinner forever (#172). Reading
  // store state via getState() inside the effect avoids the dep-loop entirely.
  const hasLoadedProjects = useRef(false);
  useEffect(() => {
    if (hasLoadedProjects.current) return;
    hasLoadedProjects.current = true;
    (async () => {
      try {
        const data = await projectsApi.list();
        setProjects(data);
        const { activeProjectId: currentActive, setActiveProject: setProj } =
          useProjectContextStore.getState();
        if (!currentActive && data.length > 0) {
          const first = data[0]!;
          setProj(first.id, first.name);
        }
      } catch {
        setProjects([]);
      } finally {
        setLoadingProjects(false);
      }
    })();
  }, []);

  // Default the BOQ picker to the first BOQ once the query resolves, and
  // clear the selection when the project switches or the list empties.
  useEffect(() => {
    if (!selectedProjectId) {
      setSelectedBoqId('');
      return;
    }
    if (boqs.length === 0) {
      setSelectedBoqId('');
      return;
    }
    if (!boqs.some((b) => b.id === selectedBoqId)) {
      setSelectedBoqId(boqs[0]!.id);
    }
  }, [selectedProjectId, boqs, selectedBoqId]);

  const selectedBoq = boqs.find((b) => b.id === selectedBoqId);

  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  const handleDownload = useCallback(
    async (card: ReportCard, format: ReportFormat) => {
      // Custom-handler cards only need a project selection
      if (card.customHandler) {
        if (!selectedProjectId || !selectedProject) {
          addToast({
            type: 'warning',
            title: t('reports.select_project_first', {
              defaultValue: 'Please select a project first',
            }),
          });
          return;
        }

        const key = `${card.id}:${format.extension}`;
        setDownloading(key);

        try {
          await card.customHandler(selectedProjectId, selectedProject.name, t);
          addToast({
            type: 'success',
            title: t('reports.download_success', {
              defaultValue: 'Report downloaded successfully',
            }),
          });
        } catch (err) {
          addToast({
            type: 'error',
            title: t('reports.download_error', {
              defaultValue: 'Failed to generate report',
            }),
            message: err instanceof Error ? err.message : undefined,
          });
        } finally {
          setDownloading(null);
        }
        return;
      }

      // Standard BOQ export path
      if (!selectedBoqId || !selectedBoq) {
        addToast({
          type: 'warning',
          title: t('reports.select_boq_first', { defaultValue: 'Please select a project and BOQ first' }),
        });
        return;
      }

      const key = `${card.id}:${format.extension}`;
      setDownloading(key);

      try {
        await downloadBoqExport(selectedBoqId, selectedBoq.name, format);
        addToast({
          type: 'success',
          title: t('reports.download_success', {
            defaultValue: 'Report downloaded successfully',
          }),
        });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('reports.download_error', {
            defaultValue: 'Failed to generate report',
          }),
          message: err instanceof Error ? err.message : undefined,
        });
      } finally {
        setDownloading(null);
      }
    },
    [selectedProjectId, selectedProject, selectedBoqId, selectedBoq, addToast, t],
  );

  if (loadingProjects) {
    return (
      <div className="w-full space-y-5 animate-fade-in">
        <Breadcrumb
          items={[
            { label: t('nav.reports', { defaultValue: 'Reports' }) },
          ]}
        />
        <SkeletonGrid items={6} />
      </div>
    );
  }

  return (
    <div className="w-full space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.reports', { defaultValue: 'Reports' }) },
        ]}
      />

      {/* Header - module name + icon live in the global top bar; the page
          renders only the muted subtitle here (canon §2). Project selection
          lives in the global top bar, so there is no in-page project picker;
          the BOQ picker below is a within-project picker and stays. */}
      <PageHeader
        srTitle={t('nav.reports', { defaultValue: 'Reports' })}
        subtitle={t('reports.subtitle', {
          defaultValue: 'Generate professional reports for your projects',
        })}
        actions={<ModuleGuideButton content={reportsGuide} />}
      />

      <DismissibleInfo
        storageKey="reports"
        title={t('reports.intro_title', {
          defaultValue: 'Hand over a document, not a screenshot',
        })}
        more={
          t('reports.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('reports.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.boq', { defaultValue: 'BOQ' }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('nav.reporting', { defaultValue: 'Reporting' }),
            onClick: () => navigate('/reporting'),
          },
        ]}
      >
        {t('reports.intro_body', {
          defaultValue:
            'Choose a project and BOQ, then generate the deliverable you need: detailed BOQ, cost breakdown by category, GAEB X83 for tender exchange, validation results, schedule summary or 5D budget-vs-actual. Each export downloads in the format your client or authority expects. The numbers come straight from the BOQ and cost data, so what you send matches the screen.',
        })}
      </DismissibleInfo>

      {/* No project selected - point at the global top-bar project selector
          rather than rendering a local picker (canon §4). */}
      {!selectedProjectId ? (
        <EmptyState
          icon={<FileText size={28} strokeWidth={1.5} />}
          title={t('reports.no_project_title', { defaultValue: 'Select a project' })}
          description={
            !loadingProjects && projects.length === 0
              ? t('reports.no_projects', { defaultValue: 'No projects available' })
              : t('reports.no_project_desc', {
                  defaultValue:
                    'Pick a project from the selector in the top bar to generate its reports.',
                })
          }
        />
      ) : (
      <>
      {/* BOQ selector - a within-project picker, kept per canon §4 exception. */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-col gap-1">
          <label
            htmlFor="report-boq"
            className="text-xs font-medium text-content-secondary"
          >
            {t('boq.title', { defaultValue: 'BOQ' })}
          </label>
          <select
            id="report-boq"
            value={selectedBoqId}
            onChange={(e) => setSelectedBoqId(e.target.value)}
            disabled={loadingBoqs || boqs.length === 0}
            className="h-9 min-w-[220px] rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary outline-none transition-colors focus:border-oe-blue focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
          >
            {loadingBoqs && (
              <option value="">
                {t('common.loading', { defaultValue: 'Loading...' })}
              </option>
            )}
            {!loadingBoqs && boqs.length === 0 && selectedProjectId && (
              <option value="">
                {t('reports.no_boqs', { defaultValue: 'No BOQs in this project' })}
              </option>
            )}
            {boqs.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Report cards grid */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {REPORT_CARDS.map((card) => (
          <ReportCardComponent
            key={card.id}
            card={card}
            downloading={downloading}
            disabled={card.customHandler ? !selectedProjectId : !selectedBoqId}
            onDownload={handleDownload}
          />
        ))}

        {/* Custom Report Builder card */}
        <div className="flex flex-col justify-between rounded-xl border border-dashed border-oe-blue/40 bg-oe-blue-subtle/10 p-5 shadow-sm transition-shadow hover:shadow-md">
          <div>
            <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue/10">
              <Settings2 size={20} className="text-oe-blue" strokeWidth={1.75} />
            </div>
            <h3 className="text-base font-semibold text-content-primary">
              {t('reports.custom_report', { defaultValue: 'Custom Report' })}
            </h3>
            <p className="mt-1 text-sm leading-relaxed text-content-secondary">
              {t('reports.custom_report_desc', {
                defaultValue: 'Build a combined report with the sections you choose.',
              })}
            </p>
          </div>
          <div className="mt-4">
            <button
              onClick={() => setShowBuilder((p) => !p)}
              aria-label={showBuilder
                ? t('reports.hide_builder', { defaultValue: 'Hide Builder' })
                : t('reports.configure', { defaultValue: 'Configure Sections' })}
              className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue-hover transition-colors"
            >
              <Settings2 size={14} />
              {showBuilder
                ? t('reports.hide_builder', { defaultValue: 'Hide Builder' })
                : t('reports.configure', { defaultValue: 'Configure Sections' })}
            </button>
          </div>
        </div>
      </div>

      {/* Recently generated reports - surfaces backend history that was
          previously a blind spot for users (V_REPORTING audit). */}
      {selectedProjectId && <GeneratedReportsHistory projectId={selectedProjectId} />}

      {/* Custom Report Builder panel */}
      {showBuilder && (
        <CustomReportBuilder
          sections={builderSections}
          onSetSections={(ids) => setBuilderSections(new Set(ids))}
          onToggle={(id) => {
            setBuilderSections((prev) => {
              const next = new Set(prev);
              if (next.has(id)) next.delete(id);
              else next.add(id);
              return next;
            });
          }}
          onGenerate={async () => {
            if (!selectedProjectId || !selectedProject) {
              addToast({
                type: 'warning',
                title: t('reports.select_project_first', { defaultValue: 'Please select a project first' }),
              });
              return;
            }
            // Item 2 - warn the user up front when "BOQ Detail" is selected but
            // no BOQ is available. Without this the section silently renders a
            // "No BOQ selected" placeholder and the user gets a report missing
            // the position detail they expected. Still allow generation (the
            // other sections are valid), but make the omission explicit.
            if (builderSections.has('boq_detail') && !selectedBoqId) {
              addToast({
                type: 'warning',
                title: t('reports.boq_detail_skipped_title', {
                  defaultValue: 'BOQ Detail will be skipped',
                }),
                message: t('reports.boq_detail_skipped_msg', {
                  defaultValue:
                    'No BOQ is selected, so the BOQ Detail section cannot be included. Select a BOQ to add position details.',
                }),
              });
            }
            setBuilderGenerating(true);
            try {
              const sections = Array.from(builderSections);
              const projectName = selectedProject.name;
              const lang = getIntlLocale();
              // Human-facing HTML export: render quantities in the user's
              // measurement system. Read at click time (this is a one-shot
              // export action, not reactive render). Storage is untouched.
              const measurementSystem = usePreferencesStore.getState().measurementSystem;

              let cachedDashboard: Awaited<ReturnType<typeof costModelApi.getDashboard>> | null = null;
              async function getDashboard() {
                if (!cachedDashboard) {
                  cachedDashboard = await costModelApi.getDashboard(selectedProjectId);
                }
                return cachedDashboard;
              }

              const htmlParts: string[] = [];

              htmlParts.push(`<!DOCTYPE html><html lang="${esc(lang)}"><head><meta charset="UTF-8"><title>${esc(projectName)} - ${esc(t('reports.html_project_report', { defaultValue: 'Project Report' }))}</title>`);
              htmlParts.push('<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:900px;margin:0 auto;padding:40px 24px;color:#1a1a1a;line-height:1.6}h1{font-size:28px;border-bottom:3px solid #2563eb;padding-bottom:12px;margin-bottom:8px}h2{font-size:20px;color:#2563eb;margin-top:32px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}h3{font-size:16px;margin-top:20px;color:#374151}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb;font-size:14px}th{background:#f9fafb;font-weight:600;color:#374151}tr:hover{background:#f9fafb}.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600}.badge-success{background:#dcfce7;color:#166534}.badge-warning{background:#fef3c7;color:#92400e}.badge-error{background:#fee2e2;color:#991b1b}.badge-blue{background:#dbeafe;color:#1e40af}.badge-neutral{background:#f3f4f6;color:#4b5563}.metric{display:inline-block;margin:8px 16px 8px 0;padding:12px 20px;border:1px solid #e5e7eb;border-radius:8px;text-align:center}.metric-label{font-size:11px;text-transform:uppercase;color:#6b7280;letter-spacing:0.05em}.metric-value{font-size:22px;font-weight:700;color:#1a1a1a}p.generated{color:#9ca3af;font-size:12px;margin-top:40px;border-top:1px solid #e5e7eb;padding-top:12px}@media print{body{padding:0}}</style>');
              htmlParts.push('</head><body>');
              htmlParts.push(`<h1>${esc(projectName)}</h1>`);
              htmlParts.push(`<p style="color:#6b7280;margin-bottom:24px">${esc(t('reports.html_generated', { defaultValue: 'Generated' }))}: ${esc(new Date().toLocaleString(lang))}</p>`);

              const naLabel = t('reports.csv_na', { defaultValue: 'N/A' });

              // Executive Summary
              if (sections.includes('summary')) {
                htmlParts.push(`<h2>${esc(t('reports.section_summary', { defaultValue: 'Executive Summary' }))}</h2>`);
                try {
                  const dashboard = await getDashboard();
                  const cur = dashboard.currency || 'EUR';
                  htmlParts.push('<div>');
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_total_budget', { defaultValue: 'Total Budget' }))}</div><div class="metric-value">${Number(dashboard.total_budget || 0).toLocaleString(lang)} ${esc(cur)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_total_actual', { defaultValue: 'Total Actual' }))}</div><div class="metric-value">${Number(dashboard.total_actual || 0).toLocaleString(lang)} ${esc(cur)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_variance', { defaultValue: 'Variance' }))}</div><div class="metric-value">${Number(dashboard.variance || 0).toLocaleString(lang)} ${esc(cur)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_status', { defaultValue: 'Status' }))}</div><div class="metric-value">${esc(dashboard.status || naLabel)}</div></div>`);
                  htmlParts.push('</div>');
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_no_budget_project', { defaultValue: 'No budget data available for this project.' }))}</p>`);
                }
              }

              // Budget vs Actual
              if (sections.includes('budget')) {
                htmlParts.push(`<h2>${esc(t('reports.section_budget', { defaultValue: 'Budget vs Actual' }))}</h2>`);
                try {
                  const dashboard = await getDashboard();
                  htmlParts.push(`<table><thead><tr><th>${esc(t('reports.html_col_metric', { defaultValue: 'Metric' }))}</th><th style="text-align:right">${esc(t('reports.html_col_value', { defaultValue: 'Value' }))}</th></tr></thead><tbody>`);
                  htmlParts.push(`<tr><td>${esc(t('reports.html_total_budget_planned', { defaultValue: 'Total Budget (Planned)' }))}</td><td style="text-align:right">${Number(dashboard.total_budget || 0).toLocaleString(lang)}</td></tr>`);
                  htmlParts.push(`<tr><td>${esc(t('reports.html_total_committed', { defaultValue: 'Total Committed' }))}</td><td style="text-align:right">${Number(dashboard.total_committed || 0).toLocaleString(lang)}</td></tr>`);
                  htmlParts.push(`<tr><td>${esc(t('reports.html_total_actual', { defaultValue: 'Total Actual' }))}</td><td style="text-align:right">${Number(dashboard.total_actual || 0).toLocaleString(lang)}</td></tr>`);
                  htmlParts.push(`<tr><td>${esc(t('reports.html_total_forecast', { defaultValue: 'Total Forecast' }))}</td><td style="text-align:right">${Number(dashboard.total_forecast || 0).toLocaleString(lang)}</td></tr>`);
                  const variance = Number(dashboard.variance || 0);
                  htmlParts.push(`<tr><td><strong>${esc(t('reports.html_variance', { defaultValue: 'Variance' }))}</strong></td><td style="text-align:right;color:${variance >= 0 ? '#166534' : '#991b1b'}"><strong>${variance >= 0 ? '+' : ''}${variance.toLocaleString(lang)}</strong></td></tr>`);
                  htmlParts.push(`<tr><td>${esc(t('reports.html_variance_pct', { defaultValue: 'Variance %' }))}</td><td style="text-align:right">${dashboard.variance_pct || 0}%</td></tr>`);
                  htmlParts.push('</tbody></table>');
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_no_budget', { defaultValue: 'No budget data available.' }))}</p>`);
                }
              }

              // Cost Breakdown by Category
              if (sections.includes('cost_breakdown')) {
                htmlParts.push(`<h2>${esc(t('reports.section_cost_breakdown', { defaultValue: 'Cost Breakdown by Category' }))}</h2>`);
                try {
                  const dashboard = await getDashboard();
                  const categories = (dashboard as unknown as Record<string, unknown>).categories as Array<Record<string, unknown>> | undefined;
                  if (categories && categories.length > 0) {
                    htmlParts.push(`<table><thead><tr><th>${esc(t('reports.html_col_category', { defaultValue: 'Category' }))}</th><th style="text-align:right">${esc(t('reports.html_col_planned', { defaultValue: 'Planned' }))}</th><th style="text-align:right">${esc(t('reports.html_col_actual', { defaultValue: 'Actual' }))}</th><th style="text-align:right">${esc(t('reports.html_variance', { defaultValue: 'Variance' }))}</th></tr></thead><tbody>`);
                    const unknownLabel = t('reports.csv_unknown', { defaultValue: 'Unknown' });
                    for (const cat of categories) {
                      const v = Number(cat.planned || 0) - Number(cat.actual || 0);
                      htmlParts.push(`<tr><td>${esc(String(cat.category || cat.name || unknownLabel))}</td><td style="text-align:right">${Number(cat.planned || 0).toLocaleString(lang)}</td><td style="text-align:right">${Number(cat.actual || 0).toLocaleString(lang)}</td><td style="text-align:right;color:${v >= 0 ? '#166534' : '#991b1b'}">${v >= 0 ? '+' : ''}${v.toLocaleString(lang)}</td></tr>`);
                    }
                    htmlParts.push('</tbody></table>');
                  } else {
                    htmlParts.push(`<p>${esc(t('reports.html_no_category', { defaultValue: 'No category breakdown available.' }))}</p>`);
                  }
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_no_cost_breakdown', { defaultValue: 'No cost breakdown data available.' }))}</p>`);
                }
              }

              // EVM Performance
              if (sections.includes('evm')) {
                htmlParts.push(`<h2>${esc(t('reports.html_evm_title', { defaultValue: 'Earned Value Management (EVM)' }))}</h2>`);
                try {
                  const dashboard = await getDashboard();
                  htmlParts.push('<div>');
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_spi', { defaultValue: 'SPI' }))}</div><div class="metric-value">${fmtFixed(Number(dashboard.spi || 0), 2)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_cpi', { defaultValue: 'CPI' }))}</div><div class="metric-value">${fmtFixed(Number(dashboard.cpi || 0), 2)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_eac', { defaultValue: 'EAC' }))}</div><div class="metric-value">${Number(dashboard.total_forecast || 0).toLocaleString(lang)}</div></div>`);
                  htmlParts.push('</div>');
                  htmlParts.push(`<p style="color:#6b7280;font-size:13px">${esc(t('reports.html_evm_hint', { defaultValue: 'SPI > 1.0 = ahead of schedule. CPI > 1.0 = under budget. EAC = Estimate at Completion.' }))}</p>`);
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_no_evm', { defaultValue: 'No EVM data available.' }))}</p>`);
                }
              }

              // Schedule Summary
              if (sections.includes('schedule')) {
                htmlParts.push(`<h2>${esc(t('reports.section_schedule', { defaultValue: 'Schedule Summary' }))}</h2>`);
                try {
                  const { items: schedules } =
                    await scheduleApi.listSchedules(selectedProjectId);
                  if (schedules.length === 0) {
                    htmlParts.push(`<p>${esc(t('reports.html_no_schedules', { defaultValue: 'No schedules found.' }))}</p>`);
                  }
                  for (const sched of schedules) {
                    htmlParts.push(`<h3>${esc(sched.name)} <span class="badge badge-blue">${esc(sched.status)}</span></h3>`);
                    try {
                      const gantt = await scheduleApi.getGantt(sched.id);
                      htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_total_activities', { defaultValue: 'Total Activities' }))}</div><div class="metric-value">${gantt.summary.total_activities}</div></div>`);
                      htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_completed', { defaultValue: 'Completed' }))}</div><div class="metric-value">${gantt.summary.completed}</div></div>`);
                      htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_in_progress', { defaultValue: 'In Progress' }))}</div><div class="metric-value">${gantt.summary.in_progress}</div></div>`);
                      htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_delayed', { defaultValue: 'Delayed' }))}</div><div class="metric-value">${gantt.summary.delayed}</div></div>`);
                    } catch {
                      htmlParts.push(`<p>${esc(t('reports.html_activities_load_fail', { defaultValue: 'Could not load activities.' }))}</p>`);
                    }
                  }
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_no_schedule', { defaultValue: 'No schedule data.' }))}</p>`);
                }
              }

              // Risk Summary
              if (sections.includes('risk')) {
                htmlParts.push(`<h2>${esc(t('reports.section_risk', { defaultValue: 'Risk Summary' }))}</h2>`);
                try {
                  // Read the whole register, the way the CSV export above
                  // already does. This section prints Total Risks and Total
                  // Exposure, and both were reduced over whatever the first
                  // fifty rows happened to be: a project with three hundred
                  // risks got a confident, wrong pair of figures inside a
                  // document the reader treats as the record.
                  //
                  // Past the ceiling the read is partial, and the figures that
                  // need every row - exposure, the high and critical count, the
                  // top five - are dropped rather than computed over part of
                  // the register and stated with the same confidence as the
                  // real thing. The register's own size survives being cut off,
                  // because the page envelope carries it, so the section still
                  // reports how many risks there are and how much of them it
                  // read. Failing the section instead printed "No risk data
                  // available." over a register holding thousands of rows,
                  // which a reader takes for an empty register rather than for
                  // a summary that was cut short.
                  type ReportRiskRow = { id: string; code: string; title: string; probability: number; impact_cost: number; impact_severity: string; risk_score: number; status: string };
                  const { items: risks, truncated: risksTruncated, ceiling: riskCeiling, total: riskTotal } = await fetchAllPages<ReportRiskRow>((offset, limit) =>
                    apiGet<Page<ReportRiskRow>>(`/v1/risk/?project_id=${selectedProjectId}&limit=${limit}&offset=${offset}`),
                  );
                  // A partial read can only be described as partial when there
                  // is a size to quote it against, and when that size is really
                  // larger than what was read: rows deleted while the loop ran
                  // can leave a total that no longer exceeds the rows in hand,
                  // and "Showing 10,000 of 9,998" is worse than saying nothing.
                  // Holding the number itself rather than a flag is what lets
                  // the branch below use it without a second existence check.
                  const partialRiskTotal =
                    risksTruncated && riskTotal !== undefined && riskTotal > risks.length ? riskTotal : undefined;
                  if (risksTruncated && partialRiskTotal === undefined) {
                    throw new Error(`The risk register exceeds the ${riskCeiling} row report ceiling.`);
                  }
                  if (partialRiskTotal !== undefined) {
                    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_total_risks', { defaultValue: 'Total Risks' }))}</div><div class="metric-value">${partialRiskTotal.toLocaleString(lang)}</div></div>`);
                    htmlParts.push(`<p style="color:#92400e;font-size:13px">${esc(t('cases.showing_count', { defaultValue: 'Showing {{shown}} of {{total}}', shown: risks.length, total: partialRiskTotal }))}</p>`);
                  } else if (risks.length === 0) {
                    htmlParts.push(`<p>${esc(t('reports.html_no_risks', { defaultValue: 'No risks registered.' }))}</p>`);
                  } else {
                    const totalExposure = risks.reduce((sum, r) => sum + r.probability * r.impact_cost, 0);
                    const highCritical = risks.filter(r => r.impact_severity === 'high' || r.impact_severity === 'critical').length;
                    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_total_risks', { defaultValue: 'Total Risks' }))}</div><div class="metric-value">${risks.length}</div></div>`);
                    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_high_critical', { defaultValue: 'High/Critical' }))}</div><div class="metric-value">${highCritical}</div></div>`);
                    htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_total_exposure', { defaultValue: 'Total Exposure' }))}</div><div class="metric-value">${totalExposure.toLocaleString(lang, { maximumFractionDigits: 0 })}</div></div>`);
                    htmlParts.push(`<h3>${esc(t('reports.html_top5_risks', { defaultValue: 'Top 5 Risks' }))}</h3>`);
                    htmlParts.push(`<table><thead><tr><th>${esc(t('reports.html_col_code', { defaultValue: 'Code' }))}</th><th>${esc(t('reports.html_col_title', { defaultValue: 'Title' }))}</th><th>${esc(t('reports.html_col_probability', { defaultValue: 'Probability' }))}</th><th>${esc(t('reports.html_col_severity', { defaultValue: 'Severity' }))}</th><th style="text-align:right">${esc(t('reports.html_col_score', { defaultValue: 'Score' }))}</th></tr></thead><tbody>`);
                    const top5 = [...risks].sort((a, b) => b.risk_score - a.risk_score).slice(0, 5);
                    for (const r of top5) {
                      const cls = r.impact_severity === 'critical' ? 'error' : r.impact_severity === 'high' ? 'warning' : 'neutral';
                      htmlParts.push(`<tr><td>${esc(r.code)}</td><td>${esc(r.title)}</td><td>${fmtPercent(r.probability * 100, 0)}</td><td><span class="badge badge-${cls}">${esc(r.impact_severity)}</span></td><td style="text-align:right">${fmtFixed(r.risk_score, 1)}</td></tr>`);
                    }
                    htmlParts.push('</tbody></table>');
                  }
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_no_risk', { defaultValue: 'No risk data available.' }))}</p>`);
                }
              }

              // Change Orders Summary
              if (sections.includes('changeorders')) {
                htmlParts.push(`<h2>${esc(t('reports.section_changeorders', { defaultValue: 'Change Orders Summary' }))}</h2>`);
                try {
                  const summary = await apiGet<{ total_orders: number; draft_count: number; submitted_count: number; approved_count: number; rejected_count: number; total_cost_impact: number; total_schedule_impact_days: number; currency: string }>(`/v1/changeorders/summary/?project_id=${selectedProjectId}`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_total_orders', { defaultValue: 'Total Orders' }))}</div><div class="metric-value">${summary.total_orders}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_approved', { defaultValue: 'Approved' }))}</div><div class="metric-value">${summary.approved_count}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_pending', { defaultValue: 'Pending' }))}</div><div class="metric-value">${summary.draft_count + summary.submitted_count}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_cost_impact', { defaultValue: 'Cost Impact' }))}</div><div class="metric-value">${Number(summary.total_cost_impact).toLocaleString(lang)} ${esc(summary.currency)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">${esc(t('reports.html_schedule_impact', { defaultValue: 'Schedule Impact' }))}</div><div class="metric-value">${summary.total_schedule_impact_days} ${esc(t('reports.csv_days', { defaultValue: 'days' }))}</div></div>`);
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_no_change_orders', { defaultValue: 'No change order data available.' }))}</p>`);
                }
              }

              // BOQ Detail
              if (sections.includes('boq_detail') && selectedBoqId && selectedBoq) {
                htmlParts.push(`<h2>${esc(t('reports.section_boq_detail', { defaultValue: 'BOQ Detail' }))}</h2>`);
                try {
                  const boqDetail = await apiGet<{ positions?: Array<{ ordinal: string; description: string; unit: string; quantity: number; unit_rate: number; total: number }> }>(`/v1/boq/boqs/${selectedBoqId}`);
                  const positions = boqDetail.positions ?? [];
                  // Large BOQs (1000+ positions) blow up the HTML size and
                  // make the file slow to generate/render/download. Render at
                  // most BOQ_DETAIL_POSITION_LIMIT rows, but keep the grand
                  // total accurate by summing every position regardless.
                  const truncated = positions.length > BOQ_DETAIL_POSITION_LIMIT;
                  const rows = truncated ? positions.slice(0, BOQ_DETAIL_POSITION_LIMIT) : positions;
                  htmlParts.push(`<p>${esc(t('reports.html_col_boq', { defaultValue: 'BOQ' }))}: <strong>${esc(selectedBoq.name)}</strong> (${esc(t('reports.html_positions_count', { defaultValue: '{{count}} positions', count: positions.length }))})</p>`);
                  if (truncated) {
                    htmlParts.push(`<p style="color:#92400e;font-size:13px">${esc(t('reports.html_boq_truncated', { defaultValue: '(Showing first {{limit}} positions; full BOQ available in BOQ export)', limit: BOQ_DETAIL_POSITION_LIMIT }))}</p>`);
                  }
                  htmlParts.push(`<table><thead><tr><th>#</th><th>${esc(t('reports.html_col_description', { defaultValue: 'Description' }))}</th><th>${esc(t('reports.html_col_unit', { defaultValue: 'Unit' }))}</th><th style="text-align:right">${esc(t('reports.html_col_qty', { defaultValue: 'Qty' }))}</th><th style="text-align:right">${esc(t('reports.html_col_rate', { defaultValue: 'Rate' }))}</th><th style="text-align:right">${esc(t('reports.html_col_total', { defaultValue: 'Total' }))}</th></tr></thead><tbody>`);
                  for (const pos of rows) {
                    // Quantity is absolute (scaled); unit_rate is a per-unit
                    // price (reciprocal - divide by the unit scale so rate x qty
                    // still equals the unchanged-currency total).
                    const dq = toDisplayQuantity(Number(pos.quantity || 0), pos.unit || '', measurementSystem);
                    const unitScale = toDisplayQuantity(1, pos.unit || '', measurementSystem).value || 1;
                    const dispRate = Number(pos.unit_rate || 0) / unitScale;
                    const dispUnit = displayUnitFor(pos.unit || '', measurementSystem);
                    htmlParts.push(`<tr><td>${esc(pos.ordinal)}</td><td>${esc(pos.description)}</td><td>${esc(dispUnit)}</td><td style="text-align:right">${dq.value.toLocaleString(lang, { maximumFractionDigits: 2 })}</td><td style="text-align:right">${dispRate.toLocaleString(lang, { maximumFractionDigits: 2 })}</td><td style="text-align:right">${Number(pos.total || 0).toLocaleString(lang, { maximumFractionDigits: 2 })}</td></tr>`);
                  }
                  const grandTotal = positions.reduce((sum, pos) => sum + Number(pos.total || 0), 0);
                  htmlParts.push(`<tr style="font-weight:700;border-top:2px solid #1a1a1a"><td colspan="5">${esc(t('reports.html_grand_total', { defaultValue: 'Grand Total' }))}</td><td style="text-align:right">${grandTotal.toLocaleString(lang, { maximumFractionDigits: 2 })}</td></tr>`);
                  htmlParts.push('</tbody></table>');
                } catch {
                  htmlParts.push(`<p>${esc(t('reports.html_boq_load_fail', { defaultValue: 'Could not load BOQ positions.' }))}</p>`);
                }
              } else if (sections.includes('boq_detail')) {
                htmlParts.push(`<h2>${esc(t('reports.section_boq_detail', { defaultValue: 'BOQ Detail' }))}</h2><p>${esc(t('reports.html_no_boq_selected', { defaultValue: 'No BOQ selected. Select a BOQ to include position details.' }))}</p>`);
              }

              // Validation
              if (sections.includes('validation')) {
                htmlParts.push(`<h2>${esc(t('reports.section_validation', { defaultValue: 'Validation Report' }))}</h2>`);
                htmlParts.push(`<p>${esc(t('reports.html_validation_hint', { defaultValue: 'Run validation from the Validation Dashboard for detailed compliance results.' }))}</p>`);
              }

              // Sustainability
              if (sections.includes('sustainability')) {
                htmlParts.push(`<h2>${esc(t('reports.section_sustainability', { defaultValue: 'Sustainability / CO2' }))}</h2>`);
                htmlParts.push(`<p>${esc(t('reports.html_sustainability_hint', { defaultValue: 'Enable the Sustainability module for embodied carbon analysis.' }))}</p>`);
              }

              htmlParts.push(`<p class="generated">${esc(t('reports.html_footer', { defaultValue: 'Report generated by OpenConstructionERP on {{date}}', date: new Date().toLocaleString(lang) }))}</p>`);
              htmlParts.push('</body></html>');

              const htmlContent = htmlParts.join('\n');
              const blob = new Blob([htmlContent], { type: 'text/html' });
              triggerDownload(blob, `${projectName}_report.html`);
              addToast({ type: 'success', title: t('reports.download_success', { defaultValue: 'Report downloaded successfully' }) });
            } catch {
              addToast({ type: 'error', title: t('reports.download_error', { defaultValue: 'Failed to generate report' }) });
            } finally {
              setBuilderGenerating(false);
            }
          }}
          generating={builderGenerating}
          disabled={!selectedProjectId}
          boqAvailable={!!selectedBoqId}
          t={t}
        />
      )}
      </>
      )}
    </div>
  );
}

/* ── Report Card ───────────────────────────────────────────────────────────── */

function ReportCardComponent({
  card,
  downloading,
  disabled,
  onDownload,
}: {
  card: ReportCard;
  downloading: string | null;
  disabled: boolean;
  onDownload: (card: ReportCard, format: ReportFormat) => void;
}) {
  const { t } = useTranslation();
  const Icon = card.icon;

  return (
    <div className="flex flex-col justify-between rounded-xl border border-border-light bg-surface-primary p-5 shadow-sm transition-shadow hover:shadow-md">
      {/* Icon + Title */}
      <div>
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue-subtle">
          <Icon size={20} className="text-oe-blue" strokeWidth={1.75} />
        </div>
        <h3 className="text-base font-semibold text-content-primary">
          {t(card.titleKey, { defaultValue: card.id })}
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-content-secondary">
          {t(card.descriptionKey, { defaultValue: '' })}
        </p>
      </div>

      {/* Action buttons */}
      <div className="mt-4 flex flex-wrap gap-2">
        {card.comingSoon ? (
          <span className="inline-flex items-center rounded-md bg-surface-secondary px-3 py-1.5 text-xs font-medium text-content-tertiary">
            {t('reports.coming_soon', { defaultValue: 'Coming soon' })}
          </span>
        ) : (
          card.formats.map((format) => {
            const key = `${card.id}:${format.extension}`;
            const isLoading = downloading === key;

            return (
              <button
                key={format.extension}
                onClick={() => onDownload(card, format)}
                disabled={disabled || isLoading}
                aria-label={t('reports.download_format_aria', {
                  defaultValue: 'Download {{format}} for {{report}}',
                  format: format.label,
                  report: t(card.titleKey, { defaultValue: card.id }),
                })}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary transition-colors hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-40"
              >
                {isLoading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Download size={14} />
                )}
                {t('reports.download_format', {
                  defaultValue: `Download ${format.label}`,
                  format: format.label,
                })}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

/* ── Custom Report Builder ────────────────────────────────────────────────── */

const REPORT_PRESETS = [
  {
    id: 'monthly_progress',
    labelKey: 'reports.preset_monthly',
    labelDefault: 'Monthly Progress',
    sections: ['summary', 'budget', 'evm', 'schedule', 'risk', 'changeorders'],
  },
  {
    id: 'client_presentation',
    labelKey: 'reports.preset_client',
    labelDefault: 'Client Presentation',
    sections: ['summary', 'cost_breakdown', 'boq_detail'],
  },
  {
    id: 'audit_report',
    labelKey: 'reports.preset_audit',
    labelDefault: 'Audit Report',
    sections: ['summary', 'budget', 'boq_detail', 'validation', 'changeorders'],
  },
  {
    id: 'full_report',
    labelKey: 'reports.preset_full',
    labelDefault: 'Full Report',
    sections: ['summary', 'budget', 'cost_breakdown', 'evm', 'schedule', 'risk', 'changeorders', 'boq_detail', 'validation', 'sustainability'],
  },
];

const REPORT_SECTIONS = [
  { id: 'summary', labelKey: 'reports.section_summary', labelDefault: 'Executive Summary', icon: FileText, descKey: 'reports.section_summary_desc', descDefault: 'Project overview, key metrics, grand total' },
  { id: 'budget', labelKey: 'reports.section_budget', labelDefault: 'Budget vs Actual', icon: DollarSign, descKey: 'reports.section_budget_desc', descDefault: 'Planned, committed, actual, and variance analysis' },
  { id: 'cost_breakdown', labelKey: 'reports.section_cost_breakdown', labelDefault: 'Cost Breakdown by Category', icon: BarChart3, descKey: 'reports.section_cost_breakdown_desc', descDefault: 'Cost distribution by material, labor, equipment' },
  { id: 'evm', labelKey: 'reports.section_evm', labelDefault: 'EVM Performance', icon: TrendingUp, descKey: 'reports.section_evm_desc', descDefault: 'SPI, CPI, EAC earned value metrics' },
  { id: 'schedule', labelKey: 'reports.section_schedule', labelDefault: 'Schedule Summary', icon: CalendarDays, descKey: 'reports.section_schedule_desc', descDefault: 'Total activities, critical path, milestones' },
  { id: 'risk', labelKey: 'reports.section_risk', labelDefault: 'Risk Summary', icon: ShieldAlert, descKey: 'reports.section_risk_desc', descDefault: 'Top 5 risks, total exposure, mitigation status' },
  { id: 'changeorders', labelKey: 'reports.section_changeorders', labelDefault: 'Change Orders Summary', icon: FileEdit, descKey: 'reports.section_changeorders_desc', descDefault: 'Approved, pending, total cost/schedule impact' },
  { id: 'boq_detail', labelKey: 'reports.section_boq_detail', labelDefault: 'BOQ Detail', icon: Table2, descKey: 'reports.section_boq_detail_desc', descDefault: 'Full position list with quantities and rates' },
  { id: 'validation', labelKey: 'reports.section_validation', labelDefault: 'Validation Report', icon: ShieldCheck, descKey: 'reports.section_validation_desc', descDefault: 'Compliance check results and quality score' },
  { id: 'sustainability', labelKey: 'reports.section_sustainability', labelDefault: 'Sustainability / CO2', icon: Leaf, descKey: 'reports.section_sustainability_desc', descDefault: 'Embodied carbon estimates and EPD references' },
] as const;

function CustomReportBuilder({
  sections,
  onToggle,
  onSetSections,
  onGenerate,
  generating,
  disabled,
  boqAvailable,
  t,
}: {
  sections: Set<string>;
  onToggle: (id: string) => void;
  onSetSections: (ids: string[]) => void;
  onGenerate: () => void;
  generating: boolean;
  disabled: boolean;
  /** Whether a BOQ is currently selected - the "BOQ Detail" section needs
   *  one and is visually marked unavailable when this is false. */
  boqAvailable: boolean;
  t: TFunc;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-primary p-5 animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('reports.select_sections', { defaultValue: 'Select report sections' })}
          </h3>
          <p className="text-xs text-content-tertiary mt-0.5">
            {t('reports.sections_hint', {
              defaultValue: 'Choose which sections to include in your custom report',
            })}
          </p>
        </div>
        <button
          onClick={onGenerate}
          disabled={disabled || generating || sections.size === 0}
          aria-label={t('reports.generate_report', { defaultValue: 'Generate Report' })}
          className="flex items-center gap-1.5 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50 transition-colors"
        >
          {generating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Download size={14} />
          )}
          {t('reports.generate_report', { defaultValue: 'Generate Report' })}
          {sections.size > 0 && (
            <span className="ml-1 text-xs opacity-70">({sections.size})</span>
          )}
        </button>
      </div>

      {/* Presets */}
      <div className="flex flex-wrap gap-2 mb-4">
        <span className="text-xs font-medium text-content-tertiary mr-1 self-center">
          {t('reports.presets', { defaultValue: 'Quick presets:' })}
        </span>
        {REPORT_PRESETS.map((preset) => (
          <button
            key={preset.id}
            onClick={() => onSetSections(preset.sections)}
            aria-label={t('reports.apply_preset_aria', {
              defaultValue: 'Apply preset: {{preset}}',
              preset: t(preset.labelKey, { defaultValue: preset.labelDefault }),
            })}
            className="rounded-full border border-border-light bg-surface-secondary/50 px-3 py-1 text-2xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            {t(preset.labelKey, { defaultValue: preset.labelDefault })}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {REPORT_SECTIONS.map((sec) => {
          const isActive = sections.has(sec.id);
          // Item 2 - "BOQ Detail" needs a selected BOQ. When none is selected
          // mark it unavailable (muted + hint) so the user understands it will
          // be skipped before they generate, rather than discovering a
          // placeholder in the downloaded file.
          const unavailable = sec.id === 'boq_detail' && !boqAvailable;
          const Icon = sec.icon;
          const unavailableHint = t('reports.section_requires_boq', {
            defaultValue: 'Select a BOQ above to include this section',
          });
          return (
            <button
              key={sec.id}
              onClick={() => onToggle(sec.id)}
              role="checkbox"
              aria-checked={isActive}
              title={unavailable ? unavailableHint : undefined}
              className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                isActive
                  ? 'border-oe-blue/40 bg-oe-blue-subtle/20'
                  : 'border-border-light bg-surface-secondary/30 hover:bg-surface-secondary'
              } ${unavailable ? 'opacity-50' : ''}`}
            >
              <div className="mt-0.5 shrink-0">
                {isActive ? (
                  <CheckSquare2 size={16} className="text-oe-blue" />
                ) : (
                  <Square size={16} className="text-content-quaternary" />
                )}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <Icon size={13} className={isActive ? 'text-oe-blue' : 'text-content-tertiary'} />
                  <span className={`text-xs font-medium ${isActive ? 'text-content-primary' : 'text-content-secondary'}`}>
                    {t(sec.labelKey, { defaultValue: sec.labelDefault })}
                  </span>
                </div>
                <p className="text-2xs text-content-tertiary mt-0.5">
                  {unavailable ? unavailableHint : t(sec.descKey, { defaultValue: sec.descDefault })}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
