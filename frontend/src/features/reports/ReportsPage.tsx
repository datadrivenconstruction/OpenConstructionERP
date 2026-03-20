import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FileText,
  BarChart3,
  FileCode2,
  ShieldCheck,
  CalendarDays,
  TrendingUp,
  Download,
  Loader2,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi, type Project } from '@/features/projects/api';
import { boqApi, type BOQ } from '@/features/boq/api';

/* ── Types ─────────────────────────────────────────────────────────────────── */

interface ReportCard {
  id: string;
  titleKey: string;
  descriptionKey: string;
  icon: LucideIcon;
  formats: ReportFormat[];
  comingSoon?: boolean;
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
    formats: [],
    comingSoon: true,
  },
  {
    id: '5d_report',
    titleKey: 'reports.5d_report',
    descriptionKey: 'reports.5d_report_desc',
    icon: TrendingUp,
    formats: [],
    comingSoon: true,
  },
];

/* ── Helpers ───────────────────────────────────────────────────────────────── */

async function downloadBoqExport(
  boqId: string,
  boqName: string,
  format: ReportFormat,
): Promise<void> {
  const token = localStorage.getItem('oe_access_token');
  const response = await fetch(`/api/v1/boq/boqs/${boqId}/${format.endpoint}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'Unknown error');
    throw new Error(`Export failed (${response.status}): ${errorText}`);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${boqName}.${format.extension}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export function ReportsPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // Project & BOQ selectors
  const [projects, setProjects] = useState<Project[]>([]);
  const [boqs, setBoqs] = useState<BOQ[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [selectedBoqId, setSelectedBoqId] = useState('');
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingBoqs, setLoadingBoqs] = useState(false);

  // Per-format loading state: "cardId:extension"
  const [downloading, setDownloading] = useState<string | null>(null);

  // Load projects on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await projectsApi.list();
        if (cancelled) return;
        setProjects(data);
        const first = data[0];
        if (first) {
          setSelectedProjectId(first.id);
        }
      } catch {
        // Silently handle — user will see empty dropdown
      } finally {
        if (!cancelled) setLoadingProjects(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  const handleDownload = useCallback(
    async (card: ReportCard, format: ReportFormat) => {
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
    [selectedBoqId, selectedBoq, addToast, t],
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
            onChange={(e) => setSelectedProjectId(e.target.value)}
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
            disabled={!selectedBoqId}
            onDownload={handleDownload}
          />
        ))}
      </div>
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
