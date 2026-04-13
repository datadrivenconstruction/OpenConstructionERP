import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { getIntlLocale } from '@/shared/lib/formatters';
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
import { Breadcrumb, InfoHint } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
import { projectsApi, type Project } from '@/features/projects/api';
import { boqApi, type BOQ } from '@/features/boq/api';
import { scheduleApi } from '@/features/schedule/api';
import { costModelApi } from '@/features/costmodel/api';

/* ── Types ─────────────────────────────────────────────────────────────────── */

interface ReportCard {
  id: string;
  titleKey: string;
  descriptionKey: string;
  icon: LucideIcon;
  formats: ReportFormat[];
  comingSoon?: boolean;
  /** Custom download handler for reports that don't use standard BOQ export. */
  customHandler?: (projectId: string, projectName: string) => Promise<void>;
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

/** Format a date string for display, falling back to "N/A" for nulls. */
function fmtDate(d: string | null | undefined): string {
  if (!d) return 'N/A';
  try {
    return new Date(d).toLocaleDateString(getIntlLocale());
  } catch {
    return d;
  }
}

/**
 * Cost Report — fetch cost model dashboard data and generate a CSV with budget,
 * committed, actual, forecast, and variance breakdown.
 */
async function downloadCostReport(projectId: string, projectName: string): Promise<void> {
  let dashboard: Awaited<ReturnType<typeof costModelApi.getDashboard>>;
  try {
    dashboard = await costModelApi.getDashboard(projectId);
  } catch {
    throw new Error(
      'No cost model data available for this project. ' +
        'Create a cost model with budget items first.',
    );
  }

  const csvLines: string[] = [];
  csvLines.push('Cost Report');
  csvLines.push(`Project,${projectName}`);
  csvLines.push(`Generated,${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push('Summary');
  csvLines.push(`Total Budget,${dashboard.total_budget}`);
  csvLines.push(`Total Committed,${dashboard.total_committed}`);
  csvLines.push(`Total Actual,${dashboard.total_actual}`);
  csvLines.push(`Total Forecast,${dashboard.total_forecast}`);
  csvLines.push(`Variance,${dashboard.variance}`);
  csvLines.push(`Variance %,${dashboard.variance_pct}`);
  csvLines.push(`SPI,${dashboard.spi}`);
  csvLines.push(`CPI,${dashboard.cpi}`);
  csvLines.push(`Status,${dashboard.status}`);
  csvLines.push(`Currency,${dashboard.currency}`);

  // Include category breakdown if available
  const categories = (dashboard as unknown as Record<string, unknown>).categories as
    | Array<Record<string, unknown>>
    | undefined;
  if (categories && categories.length > 0) {
    csvLines.push('');
    csvLines.push('Cost Breakdown by Category');
    csvLines.push('Category,Planned,Actual,Variance');
    for (const cat of categories) {
      const planned = Number(cat.planned || 0);
      const actual = Number(cat.actual || 0);
      csvLines.push(
        `${cat.category || cat.name || 'Unknown'},${planned.toFixed(2)},${actual.toFixed(2)},${(planned - actual).toFixed(2)}`,
      );
    }
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_cost_report.csv`, 'text/csv');
}

/**
 * Validation Report — run BOQ validation via the backend validate endpoint and
 * generate a CSV report with all rule results.
 *
 * Requires a BOQ to be selected. When called from the report card (which only
 * passes projectId), we fetch the first BOQ for the project and validate that.
 */
async function downloadValidationReport(projectId: string, projectName: string): Promise<void> {
  // Find the first BOQ for this project
  let boqs: Array<{ id: string; name: string }>;
  try {
    boqs = await boqApi.list(projectId);
  } catch {
    throw new Error('Could not load BOQs for this project.');
  }

  if (boqs.length === 0) {
    throw new Error(
      'No BOQs found for this project. Create a BOQ first to run validation.',
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
    throw new Error(
      `Validation failed: ${err instanceof Error ? err.message : 'Unknown error'}`,
    );
  }

  const csvLines: string[] = [];
  csvLines.push('Validation Report');
  csvLines.push(`Project,${projectName}`);
  csvLines.push(`BOQ,${report.boq_name || boq.name}`);
  csvLines.push(`Generated,${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push('Summary');
  csvLines.push(`Total Positions,${report.total_positions}`);
  csvLines.push(`Score,${typeof report.score === 'number' ? (report.score * 100).toFixed(1) + '%' : 'N/A'}`);
  csvLines.push(`Status,${report.status}`);
  csvLines.push(`Rules Checked,${report.summary?.total ?? 0}`);
  csvLines.push(`Passed,${report.summary?.passed ?? 0}`);
  csvLines.push(`Warnings,${report.summary?.warnings ?? 0}`);
  csvLines.push(`Errors,${report.summary?.errors ?? 0}`);
  csvLines.push('');

  if (report.results && report.results.length > 0) {
    csvLines.push('Detailed Results');
    csvLines.push('Rule ID,Rule Name,Severity,Status,Message,Element');
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
    csvLines.push('No validation issues found.');
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_validation_report.csv`, 'text/csv');
}

/**
 * Schedule Report — fetch schedules and activities, then generate a plain-text
 * summary and trigger a download.
 */
async function downloadScheduleReport(projectId: string, projectName: string): Promise<void> {
  let schedules: Awaited<ReturnType<typeof scheduleApi.listSchedules>>;
  try {
    schedules = await scheduleApi.listSchedules(projectId);
  } catch {
    throw new Error(
      'Could not load schedule data for this project. Create a schedule first.',
    );
  }

  const lines: string[] = [
    `Schedule Report — ${projectName}`,
    `Generated: ${new Date().toISOString()}`,
    '='.repeat(60),
    '',
  ];

  if (schedules.length === 0) {
    lines.push('No schedules found for this project.');
  }

  for (const schedule of schedules) {
    lines.push(`Schedule: ${schedule.name}`);
    lines.push(`  Status:     ${schedule.status}`);
    lines.push(`  Start date: ${fmtDate(schedule.start_date)}`);
    lines.push(`  End date:   ${fmtDate(schedule.end_date)}`);
    lines.push('');

    try {
      const gantt = await scheduleApi.getGantt(schedule.id);
      lines.push(`  Activities (${gantt.summary.total_activities} total):`);
      lines.push(
        `    Completed: ${gantt.summary.completed}  |  In-progress: ${gantt.summary.in_progress}  |  Delayed: ${gantt.summary.delayed}`,
      );
      lines.push('');
      lines.push(
        '  ' +
          'WBS'.padEnd(14) +
          'Name'.padEnd(32) +
          'Start'.padEnd(14) +
          'End'.padEnd(14) +
          'Days'.padEnd(8) +
          'Progress'.padEnd(10) +
          'Status',
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
      lines.push('  (Could not load activities for this schedule)');
    }

    lines.push('');
    lines.push('-'.repeat(60));
    lines.push('');
  }

  downloadBlob(lines.join('\n'), `${projectName}_schedule_report.txt`, 'text/plain');
}

/**
 * 5D Report — fetch dashboard data and S-curve, then generate a CSV download.
 */
async function download5DReport(projectId: string, projectName: string): Promise<void> {
  let dashboard: Awaited<ReturnType<typeof costModelApi.getDashboard>>;
  let sCurveData: Awaited<ReturnType<typeof costModelApi.getSCurve>>;

  try {
    [dashboard, sCurveData] = await Promise.all([
      costModelApi.getDashboard(projectId),
      costModelApi.getSCurve(projectId),
    ]);
  } catch {
    throw new Error(
      'No 5D cost model data available for this project. ' +
        'Create a cost model with budget and schedule data first.',
    );
  }

  const csvLines: string[] = [];

  // Dashboard summary section
  csvLines.push('5D Cost Report');
  csvLines.push(`Project,${projectName}`);
  csvLines.push(`Generated,${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push('Dashboard Summary');
  csvLines.push(`Total Budget,${dashboard.total_budget}`);
  csvLines.push(`Total Committed,${dashboard.total_committed}`);
  csvLines.push(`Total Actual,${dashboard.total_actual}`);
  csvLines.push(`Total Forecast,${dashboard.total_forecast}`);
  csvLines.push(`Variance,${dashboard.variance}`);
  csvLines.push(`Variance %,${dashboard.variance_pct}`);
  csvLines.push(`SPI,${dashboard.spi}`);
  csvLines.push(`CPI,${dashboard.cpi}`);
  csvLines.push(`Status,${dashboard.status}`);
  csvLines.push(`Currency,${dashboard.currency}`);
  csvLines.push('');

  // S-Curve data section
  csvLines.push('S-Curve Data');
  if (sCurveData.periods && sCurveData.periods.length > 0) {
    csvLines.push('Period,Planned,Earned,Actual');
    for (const point of sCurveData.periods) {
      csvLines.push(`${point.period},${point.planned},${point.earned},${point.actual}`);
    }
  } else {
    csvLines.push('No S-curve period data available yet.');
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_5d_report.csv`, 'text/csv');
}

/**
 * Tender Comparison Report — fetch tender packages and bid comparison data,
 * then generate a CSV download.
 */
async function downloadTenderComparisonReport(projectId: string, projectName: string): Promise<void> {
  let packages: Array<{
    id: string; name: string; status: string; bid_count: number; deadline: string | null;
  }>;
  try {
    packages = await apiGet<Array<{
      id: string; name: string; status: string; bid_count: number; deadline: string | null;
    }>>(`/v1/tendering/packages/?project_id=${projectId}`);
  } catch {
    throw new Error(
      'No tender packages available for this project. Create tender packages first.',
    );
  }

  const csvLines: string[] = [];
  csvLines.push('Tender Comparison Report');
  csvLines.push(`Project,${projectName}`);
  csvLines.push(`Generated,${new Date().toISOString()}`);
  csvLines.push(`Total Packages,${packages.length}`);
  csvLines.push('');

  for (const pkg of packages) {
    csvLines.push(`Package: ${pkg.name}`);
    csvLines.push(`Status,${pkg.status}`);
    csvLines.push(`Deadline,${pkg.deadline || 'N/A'}`);
    csvLines.push(`Bids,${pkg.bid_count}`);

    try {
      const comparison = await apiGet<{
        bid_count: number;
        budget_total: number;
        bid_totals: Array<{ company_name: string; total: number; currency: string; deviation_pct: number; status: string }>;
        rows: Array<{ description: string; unit: string; budget_rate: number; bids: Array<{ company_name: string; unit_rate: number; total: number }> }>;
      }>(`/v1/tendering/packages/${pkg.id}/comparison`);

      if (comparison.bid_totals.length > 0) {
        csvLines.push('');
        csvLines.push(['Company', 'Total', 'Currency', 'Deviation %', 'Status'].join(','));
        for (const bt of comparison.bid_totals) {
          csvLines.push([bt.company_name, bt.total.toFixed(2), bt.currency, `${bt.deviation_pct.toFixed(1)}%`, bt.status].join(','));
        }
        csvLines.push(`Budget Total,${comparison.budget_total.toFixed(2)}`);
      }
    } catch { /* skip comparison if unavailable */ }

    csvLines.push('');
    csvLines.push('---');
    csvLines.push('');
  }

  if (packages.length === 0) {
    csvLines.push('No tender packages found for this project.');
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_tender_comparison.csv`, 'text/csv');
}

/**
 * Change Order Register — fetch change orders and summary, then generate a CSV
 * download with cumulative cost and schedule impact.
 */
async function downloadChangeOrderReport(projectId: string, projectName: string): Promise<void> {
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
      'No change order data available for this project. Create change orders first.',
    );
  }

  const csvLines: string[] = [];
  csvLines.push('Change Order Register');
  csvLines.push(`Project,${projectName}`);
  csvLines.push(`Generated,${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push('Summary');
  csvLines.push(`Total Orders,${summary.total_orders}`);
  csvLines.push(`Approved,${summary.approved_count}`);
  csvLines.push(`Rejected,${summary.rejected_count}`);
  csvLines.push(`Total Cost Impact,${summary.total_cost_impact} ${summary.currency}`);
  csvLines.push(`Total Schedule Impact,${summary.total_schedule_impact_days} days`);
  csvLines.push('');
  csvLines.push(['Code', 'Title', 'Reason', 'Status', 'Cost Impact', 'Schedule Days', 'Items', 'Created', 'Submitted', 'Approved'].join(','));

  for (const o of orders) {
    csvLines.push([
      o.code,
      `"${o.title.replace(/"/g, '""')}"`,
      o.reason_category,
      o.status,
      o.cost_impact.toFixed(2),
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
 * Risk Register Report — fetch risks with probability, impact, scores, and
 * mitigation plans, then generate a CSV download.
 */
async function downloadRiskRegisterReport(projectId: string, projectName: string): Promise<void> {
  let risks: Array<{
    id: string; code: string; title: string; description: string;
    probability: number; impact_cost: number; impact_severity: string;
    risk_score: number; status: string; owner_name: string | null;
    mitigation_plan: string | null; created_at: string;
  }>;
  try {
    risks = await apiGet(`/v1/risk/?project_id=${projectId}&limit=100`);
  } catch {
    risks = [];
  }

  const csvLines: string[] = [];
  csvLines.push('Risk Register Report');
  csvLines.push(`Project,${projectName}`);
  csvLines.push(`Generated,${new Date().toISOString()}`);
  csvLines.push(`Total Risks,${risks.length}`);
  const totalExposure = risks.reduce((s, r) => s + r.probability * r.impact_cost, 0);
  csvLines.push(`Total Exposure,${totalExposure.toFixed(0)}`);
  csvLines.push('');
  csvLines.push(['Code', 'Title', 'Probability', 'Impact Cost', 'Severity', 'Score', 'Status', 'Owner', 'Mitigation'].join(','));

  for (const r of risks) {
    csvLines.push([
      r.code,
      `"${r.title.replace(/"/g, '""')}"`,
      `${(r.probability * 100).toFixed(0)}%`,
      r.impact_cost.toFixed(0),
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
 * Cash Flow Report — fetch S-curve data and generate a CSV with planned vs
 * actual cumulative and per-period spending.
 */
async function downloadCashFlowReport(projectId: string, projectName: string): Promise<void> {
  let sCurve: Awaited<ReturnType<typeof costModelApi.getSCurve>>;
  try {
    sCurve = await costModelApi.getSCurve(projectId);
  } catch {
    throw new Error(
      'No cash flow data available for this project. ' +
        'Create a cost model with S-curve data first.',
    );
  }

  if (!sCurve.periods || sCurve.periods.length === 0) {
    throw new Error(
      'No S-curve period data found. Add budget periods to generate a cash flow report.',
    );
  }

  const csvLines: string[] = [];
  csvLines.push('Cash Flow Forecast');
  csvLines.push(`Project,${projectName}`);
  csvLines.push(`Generated,${new Date().toISOString()}`);
  csvLines.push('');
  csvLines.push(['Period', 'Planned Cumulative', 'Earned Cumulative', 'Actual Cumulative', 'Planned Period', 'Actual Period'].join(','));

  let prevPlanned = 0;
  let prevActual = 0;
  for (const p of sCurve.periods) {
    const plannedPeriod = p.planned - prevPlanned;
    const actualPeriod = p.actual - prevActual;
    csvLines.push([
      p.period,
      p.planned.toFixed(0),
      p.earned.toFixed(0),
      p.actual.toFixed(0),
      plannedPeriod.toFixed(0),
      actualPeriod.toFixed(0),
    ].join(','));
    prevPlanned = p.planned;
    prevActual = p.actual;
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_cash_flow.csv`, 'text/csv');
}

/**
 * Progress Report — generates an HTML report combining EVM performance, schedule
 * status, and top risks into a single downloadable page.
 */
async function downloadProgressReport(projectId: string, projectName: string): Promise<void> {
  const htmlParts: string[] = [];
  htmlParts.push(`<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>${projectName} — Progress Report</title>`);
  htmlParts.push('<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:900px;margin:0 auto;padding:40px 24px;color:#1a1a1a;line-height:1.6}h1{font-size:28px;border-bottom:3px solid #2563eb;padding-bottom:12px}h2{font-size:20px;color:#2563eb;margin-top:32px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb;font-size:14px}th{background:#f9fafb;font-weight:600}.metric{display:inline-block;margin:8px 16px 8px 0;padding:12px 20px;border:1px solid #e5e7eb;border-radius:8px;text-align:center}.metric-label{font-size:11px;text-transform:uppercase;color:#6b7280;letter-spacing:0.05em}.metric-value{font-size:22px;font-weight:700}p.footer{color:#9ca3af;font-size:12px;margin-top:40px;border-top:1px solid #e5e7eb;padding-top:12px}@media print{body{padding:0}}</style>');
  htmlParts.push('</head><body>');
  htmlParts.push(`<h1>${projectName} — Progress Report</h1>`);
  htmlParts.push(`<p style="color:#6b7280">Generated: ${new Date().toLocaleString()}</p>`);

  // EVM section
  try {
    const dashboard = await costModelApi.getDashboard(projectId);
    htmlParts.push('<h2>Earned Value Performance</h2>');
    htmlParts.push('<div>');
    htmlParts.push(`<div class="metric"><div class="metric-label">SPI</div><div class="metric-value" style="color:${Number(dashboard.spi||0)>=1?'#166534':'#991b1b'}">${Number(dashboard.spi||0).toFixed(2)}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">CPI</div><div class="metric-value" style="color:${Number(dashboard.cpi||0)>=1?'#166534':'#991b1b'}">${Number(dashboard.cpi||0).toFixed(2)}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">Budget</div><div class="metric-value">${Number(dashboard.total_budget||0).toLocaleString()}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">Actual</div><div class="metric-value">${Number(dashboard.total_actual||0).toLocaleString()}</div></div>`);
    htmlParts.push(`<div class="metric"><div class="metric-label">Forecast (EAC)</div><div class="metric-value">${Number(dashboard.total_forecast||0).toLocaleString()}</div></div>`);
    htmlParts.push('</div>');
  } catch { htmlParts.push('<p>No budget data available.</p>'); }

  // Schedule section
  try {
    const schedules = await scheduleApi.listSchedules(projectId);
    htmlParts.push('<h2>Schedule Status</h2>');
    for (const sched of schedules) {
      try {
        const gantt = await scheduleApi.getGantt(sched.id);
        const pct = gantt.summary.total_activities > 0
          ? Math.round((gantt.summary.completed / gantt.summary.total_activities) * 100)
          : 0;
        htmlParts.push(`<h3>${sched.name}</h3>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">Progress</div><div class="metric-value">${pct}%</div></div>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">Activities</div><div class="metric-value">${gantt.summary.total_activities}</div></div>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">Completed</div><div class="metric-value">${gantt.summary.completed}</div></div>`);
        htmlParts.push(`<div class="metric"><div class="metric-label">Delayed</div><div class="metric-value" style="color:${gantt.summary.delayed>0?'#991b1b':'#166534'}">${gantt.summary.delayed}</div></div>`);
      } catch { /* skip */ }
    }
  } catch { htmlParts.push('<p>No schedule data.</p>'); }

  // Risk highlights
  try {
    const risks = await apiGet<Array<{ code: string; title: string; risk_score: number; impact_severity: string }>>(`/v1/risk/?project_id=${projectId}&limit=5`);
    if (risks.length > 0) {
      htmlParts.push('<h2>Top Risks</h2>');
      htmlParts.push('<table><thead><tr><th>Code</th><th>Risk</th><th>Severity</th><th>Score</th></tr></thead><tbody>');
      const sorted = [...risks].sort((a, b) => b.risk_score - a.risk_score);
      for (const r of sorted) {
        htmlParts.push(`<tr><td>${r.code}</td><td>${r.title}</td><td>${r.impact_severity}</td><td>${r.risk_score.toFixed(1)}</td></tr>`);
      }
      htmlParts.push('</tbody></table>');
    }
  } catch { /* skip */ }

  htmlParts.push(`<p class="footer">Report generated by OpenConstructionERP on ${new Date().toLocaleString()}</p>`);
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
    const errorText = await response.text().catch(() => 'Unknown error');
    throw new Error(`Export failed (${response.status}): ${errorText}`);
  }

  const blob = await response.blob();
  triggerDownload(blob, `${boqName}.${format.extension}`);
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export function ReportsPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { activeProjectId, setActiveProject } = useProjectContextStore();

  // Project & BOQ selectors
  const [projects, setProjects] = useState<Project[]>([]);
  const [boqs, setBoqs] = useState<BOQ[]>([]);
  const selectedProjectId = activeProjectId ?? '';
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingBoqs, setLoadingBoqs] = useState(false);

  // Per-format loading state: "cardId:extension"
  const [downloading, setDownloading] = useState<string | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [builderSections, setBuilderSections] = useState<Set<string>>(
    new Set(['summary', 'budget', 'cost_breakdown', 'boq_detail']),
  );
  const [builderGenerating, setBuilderGenerating] = useState(false);

  // Load projects on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await projectsApi.list();
        if (cancelled) return;
        setProjects(data);
        // If no project is selected in the global store yet, pick the first one
        if (!activeProjectId && data.length > 0) {
          const first = data[0]!;
          setActiveProject(first.id, first.name);
        }
      } catch (err) {
        if (import.meta.env.DEV) console.warn('Failed to load projects for reports:', err);
        if (!cancelled) setProjects([]);
      } finally {
        if (!cancelled) setLoadingProjects(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load BOQs when project changes
  useEffect(() => {
    if (!selectedProjectId) {
      setBoqs([]);
      setSelectedBoqId('');
      return;
    }

    let cancelled = false;
    setLoadingBoqs(true);

    (async () => {
      try {
        const data = await boqApi.list(selectedProjectId);
        if (cancelled) return;
        setBoqs(data);
        const firstBoq = data[0];
        setSelectedBoqId(firstBoq ? firstBoq.id : '');
      } catch {
        if (!cancelled) {
          setBoqs([]);
          setSelectedBoqId('');
        }
      } finally {
        if (!cancelled) setLoadingBoqs(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [selectedProjectId]);

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
          await card.customHandler(selectedProjectId, selectedProject.name);
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

  return (
    <div className="mx-auto max-w-content space-y-6 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('reports.title', { defaultValue: 'Reports' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-content-primary">
          {t('reports.title', { defaultValue: 'Reports' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('reports.subtitle', {
            defaultValue: 'Generate professional reports for your projects',
          })}
        </p>
      </div>

      {/* Report guide */}
      <InfoHint text={t('reports.guide_desc', { defaultValue: 'BOQ Report = detailed bill of quantities with totals. Cost Report = cost breakdown by category. GAEB XML = German tendering format (.x83) for subcontractor exchange. Validation = compliance check results. Schedule = Gantt activities summary. 5D = budget vs. actual cost curves.' })} />

      {/* Project + BOQ selectors */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-col gap-1">
          <label
            htmlFor="report-project"
            className="text-xs font-medium text-content-secondary"
          >
            {t('projects.title', { defaultValue: 'Project' })}
          </label>
          <select
            id="report-project"
            value={selectedProjectId}
            onChange={(e) => {
              const id = e.target.value;
              const name = projects.find((p) => p.id === id)?.name ?? '';
              if (id) {
                setActiveProject(id, name);
              } else {
                useProjectContextStore.getState().clearProject();
              }
            }}
            disabled={loadingProjects}
            className="h-9 min-w-[220px] rounded-lg border border-border-light bg-surface-primary px-3 text-sm text-content-primary outline-none transition-colors focus:border-oe-blue focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
          >
            {loadingProjects && (
              <option value="">
                {t('common.loading', { defaultValue: 'Loading...' })}
              </option>
            )}
            {!loadingProjects && projects.length === 0 && (
              <option value="">
                {t('reports.no_projects', { defaultValue: 'No projects available' })}
              </option>
            )}
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

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
            setBuilderGenerating(true);
            try {
              const sections = Array.from(builderSections);
              const projectName = selectedProject.name;

              let cachedDashboard: Awaited<ReturnType<typeof costModelApi.getDashboard>> | null = null;
              async function getDashboard() {
                if (!cachedDashboard) {
                  cachedDashboard = await costModelApi.getDashboard(selectedProjectId);
                }
                return cachedDashboard;
              }

              const htmlParts: string[] = [];

              htmlParts.push(`<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>${projectName} — Project Report</title>`);
              htmlParts.push('<style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:900px;margin:0 auto;padding:40px 24px;color:#1a1a1a;line-height:1.6}h1{font-size:28px;border-bottom:3px solid #2563eb;padding-bottom:12px;margin-bottom:8px}h2{font-size:20px;color:#2563eb;margin-top:32px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}h3{font-size:16px;margin-top:20px;color:#374151}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb;font-size:14px}th{background:#f9fafb;font-weight:600;color:#374151}tr:hover{background:#f9fafb}.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600}.badge-success{background:#dcfce7;color:#166534}.badge-warning{background:#fef3c7;color:#92400e}.badge-error{background:#fee2e2;color:#991b1b}.badge-blue{background:#dbeafe;color:#1e40af}.badge-neutral{background:#f3f4f6;color:#4b5563}.metric{display:inline-block;margin:8px 16px 8px 0;padding:12px 20px;border:1px solid #e5e7eb;border-radius:8px;text-align:center}.metric-label{font-size:11px;text-transform:uppercase;color:#6b7280;letter-spacing:0.05em}.metric-value{font-size:22px;font-weight:700;color:#1a1a1a}p.generated{color:#9ca3af;font-size:12px;margin-top:40px;border-top:1px solid #e5e7eb;padding-top:12px}@media print{body{padding:0}}</style>');
              htmlParts.push('</head><body>');
              htmlParts.push(`<h1>${projectName}</h1>`);
              htmlParts.push(`<p style="color:#6b7280;margin-bottom:24px">Generated: ${new Date().toLocaleString()}</p>`);

              // Executive Summary
              if (sections.includes('summary')) {
                htmlParts.push('<h2>Executive Summary</h2>');
                try {
                  const dashboard = await getDashboard();
                  htmlParts.push('<div>');
                  htmlParts.push(`<div class="metric"><div class="metric-label">Total Budget</div><div class="metric-value">${Number(dashboard.total_budget || 0).toLocaleString()} ${dashboard.currency || 'EUR'}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Total Actual</div><div class="metric-value">${Number(dashboard.total_actual || 0).toLocaleString()} ${dashboard.currency || 'EUR'}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Variance</div><div class="metric-value">${Number(dashboard.variance || 0).toLocaleString()} ${dashboard.currency || 'EUR'}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Status</div><div class="metric-value">${dashboard.status || 'N/A'}</div></div>`);
                  htmlParts.push('</div>');
                } catch {
                  htmlParts.push('<p>No budget data available for this project.</p>');
                }
              }

              // Budget vs Actual
              if (sections.includes('budget')) {
                htmlParts.push('<h2>Budget vs Actual</h2>');
                try {
                  const dashboard = await getDashboard();
                  htmlParts.push('<table><thead><tr><th>Metric</th><th style="text-align:right">Value</th></tr></thead><tbody>');
                  htmlParts.push(`<tr><td>Total Budget (Planned)</td><td style="text-align:right">${Number(dashboard.total_budget || 0).toLocaleString()}</td></tr>`);
                  htmlParts.push(`<tr><td>Total Committed</td><td style="text-align:right">${Number(dashboard.total_committed || 0).toLocaleString()}</td></tr>`);
                  htmlParts.push(`<tr><td>Total Actual</td><td style="text-align:right">${Number(dashboard.total_actual || 0).toLocaleString()}</td></tr>`);
                  htmlParts.push(`<tr><td>Total Forecast</td><td style="text-align:right">${Number(dashboard.total_forecast || 0).toLocaleString()}</td></tr>`);
                  const variance = Number(dashboard.variance || 0);
                  htmlParts.push(`<tr><td><strong>Variance</strong></td><td style="text-align:right;color:${variance >= 0 ? '#166534' : '#991b1b'}"><strong>${variance >= 0 ? '+' : ''}${variance.toLocaleString()}</strong></td></tr>`);
                  htmlParts.push(`<tr><td>Variance %</td><td style="text-align:right">${dashboard.variance_pct || 0}%</td></tr>`);
                  htmlParts.push('</tbody></table>');
                } catch {
                  htmlParts.push('<p>No budget data available.</p>');
                }
              }

              // Cost Breakdown by Category
              if (sections.includes('cost_breakdown')) {
                htmlParts.push('<h2>Cost Breakdown by Category</h2>');
                try {
                  const dashboard = await getDashboard();
                  const categories = (dashboard as unknown as Record<string, unknown>).categories as Array<Record<string, unknown>> | undefined;
                  if (categories && categories.length > 0) {
                    htmlParts.push('<table><thead><tr><th>Category</th><th style="text-align:right">Planned</th><th style="text-align:right">Actual</th><th style="text-align:right">Variance</th></tr></thead><tbody>');
                    for (const cat of categories) {
                      const v = Number(cat.planned || 0) - Number(cat.actual || 0);
                      htmlParts.push(`<tr><td>${cat.category || cat.name || 'Unknown'}</td><td style="text-align:right">${Number(cat.planned || 0).toLocaleString()}</td><td style="text-align:right">${Number(cat.actual || 0).toLocaleString()}</td><td style="text-align:right;color:${v >= 0 ? '#166534' : '#991b1b'}">${v >= 0 ? '+' : ''}${v.toLocaleString()}</td></tr>`);
                    }
                    htmlParts.push('</tbody></table>');
                  } else {
                    htmlParts.push('<p>No category breakdown available.</p>');
                  }
                } catch {
                  htmlParts.push('<p>No cost breakdown data available.</p>');
                }
              }

              // EVM Performance
              if (sections.includes('evm')) {
                htmlParts.push('<h2>Earned Value Management (EVM)</h2>');
                try {
                  const dashboard = await getDashboard();
                  htmlParts.push('<div>');
                  htmlParts.push(`<div class="metric"><div class="metric-label">SPI</div><div class="metric-value">${Number(dashboard.spi || 0).toFixed(2)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">CPI</div><div class="metric-value">${Number(dashboard.cpi || 0).toFixed(2)}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">EAC</div><div class="metric-value">${Number(dashboard.total_forecast || 0).toLocaleString()}</div></div>`);
                  htmlParts.push('</div>');
                  htmlParts.push('<p style="color:#6b7280;font-size:13px">SPI &gt; 1.0 = ahead of schedule. CPI &gt; 1.0 = under budget. EAC = Estimate at Completion.</p>');
                } catch {
                  htmlParts.push('<p>No EVM data available.</p>');
                }
              }

              // Schedule Summary
              if (sections.includes('schedule')) {
                htmlParts.push('<h2>Schedule Summary</h2>');
                try {
                  const schedules = await scheduleApi.listSchedules(selectedProjectId);
                  if (schedules.length === 0) {
                    htmlParts.push('<p>No schedules found.</p>');
                  }
                  for (const sched of schedules) {
                    htmlParts.push(`<h3>${sched.name} <span class="badge badge-blue">${sched.status}</span></h3>`);
                    try {
                      const gantt = await scheduleApi.getGantt(sched.id);
                      htmlParts.push(`<div class="metric"><div class="metric-label">Total Activities</div><div class="metric-value">${gantt.summary.total_activities}</div></div>`);
                      htmlParts.push(`<div class="metric"><div class="metric-label">Completed</div><div class="metric-value">${gantt.summary.completed}</div></div>`);
                      htmlParts.push(`<div class="metric"><div class="metric-label">In Progress</div><div class="metric-value">${gantt.summary.in_progress}</div></div>`);
                      htmlParts.push(`<div class="metric"><div class="metric-label">Delayed</div><div class="metric-value">${gantt.summary.delayed}</div></div>`);
                    } catch {
                      htmlParts.push('<p>Could not load activities.</p>');
                    }
                  }
                } catch {
                  htmlParts.push('<p>No schedule data available.</p>');
                }
              }

              // Risk Summary
              if (sections.includes('risk')) {
                htmlParts.push('<h2>Risk Summary</h2>');
                try {
                  const risks = await apiGet<Array<{ id: string; code: string; title: string; probability: number; impact_cost: number; impact_severity: string; risk_score: number; status: string }>>(`/v1/risk/?project_id=${selectedProjectId}&limit=50`);
                  if (risks.length === 0) {
                    htmlParts.push('<p>No risks registered.</p>');
                  } else {
                    const totalExposure = risks.reduce((sum, r) => sum + r.probability * r.impact_cost, 0);
                    const highCritical = risks.filter(r => r.impact_severity === 'high' || r.impact_severity === 'critical').length;
                    htmlParts.push(`<div class="metric"><div class="metric-label">Total Risks</div><div class="metric-value">${risks.length}</div></div>`);
                    htmlParts.push(`<div class="metric"><div class="metric-label">High/Critical</div><div class="metric-value">${highCritical}</div></div>`);
                    htmlParts.push(`<div class="metric"><div class="metric-label">Total Exposure</div><div class="metric-value">${totalExposure.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div></div>`);
                    htmlParts.push('<h3>Top 5 Risks</h3>');
                    htmlParts.push('<table><thead><tr><th>Code</th><th>Title</th><th>Probability</th><th>Severity</th><th style="text-align:right">Score</th></tr></thead><tbody>');
                    const top5 = [...risks].sort((a, b) => b.risk_score - a.risk_score).slice(0, 5);
                    for (const r of top5) {
                      const cls = r.impact_severity === 'critical' ? 'error' : r.impact_severity === 'high' ? 'warning' : 'neutral';
                      htmlParts.push(`<tr><td>${r.code}</td><td>${r.title}</td><td>${(r.probability * 100).toFixed(0)}%</td><td><span class="badge badge-${cls}">${r.impact_severity}</span></td><td style="text-align:right">${r.risk_score.toFixed(1)}</td></tr>`);
                    }
                    htmlParts.push('</tbody></table>');
                  }
                } catch {
                  htmlParts.push('<p>No risk data available.</p>');
                }
              }

              // Change Orders Summary
              if (sections.includes('changeorders')) {
                htmlParts.push('<h2>Change Orders Summary</h2>');
                try {
                  const summary = await apiGet<{ total_orders: number; draft_count: number; submitted_count: number; approved_count: number; rejected_count: number; total_cost_impact: number; total_schedule_impact_days: number; currency: string }>(`/v1/changeorders/summary/?project_id=${selectedProjectId}`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Total Orders</div><div class="metric-value">${summary.total_orders}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Approved</div><div class="metric-value">${summary.approved_count}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Pending</div><div class="metric-value">${summary.draft_count + summary.submitted_count}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Cost Impact</div><div class="metric-value">${Number(summary.total_cost_impact).toLocaleString()} ${summary.currency}</div></div>`);
                  htmlParts.push(`<div class="metric"><div class="metric-label">Schedule Impact</div><div class="metric-value">${summary.total_schedule_impact_days} days</div></div>`);
                } catch {
                  htmlParts.push('<p>No change order data available.</p>');
                }
              }

              // BOQ Detail
              if (sections.includes('boq_detail') && selectedBoqId && selectedBoq) {
                htmlParts.push('<h2>BOQ Detail</h2>');
                try {
                  const boqDetail = await apiGet<{ positions?: Array<{ ordinal: string; description: string; unit: string; quantity: number; unit_rate: number; total: number }> }>(`/v1/boq/boqs/${selectedBoqId}`);
                  const positions = boqDetail.positions ?? [];
                  htmlParts.push(`<p>BOQ: <strong>${selectedBoq.name}</strong> (${positions.length} positions)</p>`);
                  htmlParts.push('<table><thead><tr><th>#</th><th>Description</th><th>Unit</th><th style="text-align:right">Qty</th><th style="text-align:right">Rate</th><th style="text-align:right">Total</th></tr></thead><tbody>');
                  let grandTotal = 0;
                  for (const pos of positions) {
                    grandTotal += Number(pos.total || 0);
                    htmlParts.push(`<tr><td>${pos.ordinal || ''}</td><td>${pos.description || ''}</td><td>${pos.unit || ''}</td><td style="text-align:right">${Number(pos.quantity || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td><td style="text-align:right">${Number(pos.unit_rate || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td><td style="text-align:right">${Number(pos.total || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td></tr>`);
                  }
                  htmlParts.push(`<tr style="font-weight:700;border-top:2px solid #1a1a1a"><td colspan="5">Grand Total</td><td style="text-align:right">${grandTotal.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td></tr>`);
                  htmlParts.push('</tbody></table>');
                } catch {
                  htmlParts.push('<p>Could not load BOQ positions.</p>');
                }
              } else if (sections.includes('boq_detail')) {
                htmlParts.push('<h2>BOQ Detail</h2><p>No BOQ selected. Select a BOQ to include position details.</p>');
              }

              // Validation
              if (sections.includes('validation')) {
                htmlParts.push('<h2>Validation Report</h2>');
                htmlParts.push('<p>Run validation from the Validation Dashboard for detailed compliance results.</p>');
              }

              // Sustainability
              if (sections.includes('sustainability')) {
                htmlParts.push('<h2>Sustainability / CO2</h2>');
                htmlParts.push('<p>Enable the Sustainability module for embodied carbon analysis.</p>');
              }

              htmlParts.push(`<p class="generated">Report generated by OpenEstimate on ${new Date().toLocaleString()}</p>`);
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
          t={t}
        />
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
  t,
}: {
  sections: Set<string>;
  onToggle: (id: string) => void;
  onSetSections: (ids: string[]) => void;
  onGenerate: () => void;
  generating: boolean;
  disabled: boolean;
  t: (key: string, opts?: Record<string, unknown>) => string;
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
            className="rounded-full border border-border-light bg-surface-secondary/50 px-3 py-1 text-2xs font-medium text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            {t(preset.labelKey, { defaultValue: preset.labelDefault })}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {REPORT_SECTIONS.map((sec) => {
          const isActive = sections.has(sec.id);
          const Icon = sec.icon;
          return (
            <button
              key={sec.id}
              onClick={() => onToggle(sec.id)}
              role="checkbox"
              aria-checked={isActive}
              className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                isActive
                  ? 'border-oe-blue/40 bg-oe-blue-subtle/20'
                  : 'border-border-light bg-surface-secondary/30 hover:bg-surface-secondary'
              }`}
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
                <p className="text-2xs text-content-tertiary mt-0.5">{t(sec.descKey, { defaultValue: sec.descDefault })}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
