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
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { InfoHint } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { triggerDownload } from '@/shared/lib/api';
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
    icon: BarChart3,
    formats: [
      {
        label: 'PDF',
        extension: 'pdf',
        endpoint: 'export/pdf',
        mediaType: 'application/pdf',
      },
    ],
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
    icon: ShieldCheck,
    formats: [
      {
        label: 'PDF',
        extension: 'pdf',
        endpoint: 'export/pdf',
        mediaType: 'application/pdf',
      },
    ],
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
 * Schedule Report — fetch schedules and activities, then generate a plain-text
 * summary and trigger a download.
 */
async function downloadScheduleReport(projectId: string, projectName: string): Promise<void> {
  const schedules = await scheduleApi.listSchedules(projectId);

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
  const [dashboard, sCurveData] = await Promise.all([
    costModelApi.getDashboard(projectId),
    costModelApi.getSCurve(projectId),
  ]);

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
  csvLines.push('Period,Planned,Earned,Actual');
  for (const point of sCurveData.periods) {
    csvLines.push(`${point.period},${point.planned},${point.earned},${point.actual}`);
  }

  downloadBlob(csvLines.join('\n'), `${projectName}_5d_report.csv`, 'text/csv');
}

async function downloadBoqExport(
  boqId: string,
  boqName: string,
  format: ReportFormat,
): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const response = await fetch(`/api/v1/boq/boqs/${boqId}/${format.endpoint}`, {
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
    new Set(['summary', 'boq_detail', 'cost_breakdown']),
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
    <div className="mx-auto max-w-6xl space-y-6 p-6">
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
          onToggle={(id) => {
            setBuilderSections((prev) => {
              const next = new Set(prev);
              if (next.has(id)) next.delete(id);
              else next.add(id);
              return next;
            });
          }}
          onGenerate={async () => {
            if (!selectedBoqId || !selectedBoq) {
              addToast({
                type: 'warning',
                title: t('reports.select_boq_first', { defaultValue: 'Please select a project and BOQ first' }),
              });
              return;
            }
            setBuilderGenerating(true);
            try {
              const token = useAuthStore.getState().accessToken;
              const sectionsParam = Array.from(builderSections).join(',');
              const r = await fetch(
                `/api/v1/boq/boqs/${selectedBoqId}/export/pdf?sections=${sectionsParam}`,
                { headers: token ? { Authorization: `Bearer ${token}` } : {} },
              );
              if (r.ok) {
                const blob = await r.blob();
                triggerDownload(blob, `${selectedBoq.name}_custom_report.pdf`);
                addToast({ type: 'success', title: t('reports.download_success', { defaultValue: 'Report downloaded successfully' }) });
              } else {
                throw new Error('Export failed');
              }
            } catch {
              addToast({ type: 'error', title: t('reports.download_error', { defaultValue: 'Failed to generate report' }) });
            } finally {
              setBuilderGenerating(false);
            }
          }}
          generating={builderGenerating}
          disabled={!selectedBoqId}
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

const REPORT_SECTIONS = [
  { id: 'summary', label: 'Executive Summary', icon: FileText, description: 'Project overview, key metrics, grand total' },
  { id: 'boq_detail', label: 'BOQ Detail', icon: FileText, description: 'Full bill of quantities with sections and positions' },
  { id: 'cost_breakdown', label: 'Cost Breakdown', icon: BarChart3, description: 'Cost distribution by category (KG/NRM/Division)' },
  { id: 'validation', label: 'Validation Report', icon: ShieldCheck, description: 'Compliance check results and quality score' },
  { id: 'schedule', label: 'Schedule Summary', icon: CalendarDays, description: 'Gantt chart activities and milestones' },
  { id: 'sustainability', label: 'Sustainability / CO2', icon: Leaf, description: 'Embodied carbon estimates and EPD references' },
] as const;

function CustomReportBuilder({
  sections,
  onToggle,
  onGenerate,
  generating,
  disabled,
  t,
}: {
  sections: Set<string>;
  onToggle: (id: string) => void;
  onGenerate: () => void;
  generating: boolean;
  disabled: boolean;
  t: (key: string, opts?: Record<string, string>) => string;
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
          {t('reports.generate_pdf', { defaultValue: 'Generate PDF' })}
          {sections.size > 0 && (
            <span className="ml-1 text-xs opacity-70">({sections.size})</span>
          )}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {REPORT_SECTIONS.map((sec) => {
          const isActive = sections.has(sec.id);
          const Icon = sec.icon;
          return (
            <button
              key={sec.id}
              onClick={() => onToggle(sec.id)}
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
                    {sec.label}
                  </span>
                </div>
                <p className="text-2xs text-content-tertiary mt-0.5">{sec.description}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
