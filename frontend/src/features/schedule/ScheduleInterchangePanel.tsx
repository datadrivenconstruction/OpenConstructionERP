// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Schedule interchange panel (T1.1). Three independent sections:
//   - EXPORT: download the live schedule as the canonical interchange JSON
//     ({format, format_version, schedule, activities, relationships}) — a
//     lossless, brand-neutral round-trip format.
//   - HEALTH CHECK: a read-only DCMA-style hygiene dry-run (clean-preview)
//     that lists the repairs that *would* apply and the key tallies (leads,
//     hard constraints, missing predecessors/successors, total repairs).
//     It changes nothing.
//   - IMPORT: load an interchange .json document, optionally normalise it on
//     import, override the name, and create a new schedule in this project.
//
// All three call ``scheduleApi`` (GET …/export, GET …/clean-preview,
// POST …/import). Money/quantity values never appear here; everything is
// counts and structure.

import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Download,
  Upload,
  Stethoscope,
  Loader2,
  FileJson,
  FileCode2,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
} from 'lucide-react';

import { Button, Card, Badge, Input, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  scheduleApi,
  type CleanAction,
  type ScheduleCleanPreview,
  type ScheduleExport,
  type ScheduleImportResult,
  type InterchangeDocument,
  type VendorImportResult,
} from './api';

interface ScheduleInterchangePanelProps {
  scheduleId: string;
  projectId: string;
}

/**
 * Stat keys we surface in the highlighted hygiene roll-up (in this order). The
 * remaining ``stats`` keys render in a secondary grid. ``__repairs__`` is a
 * synthetic key for the summed would-fix repairs and is handled separately.
 */
const HIGHLIGHT_STATS = [
  'lead_count',
  'hard_constraint_count',
  'activities_missing_predecessor',
  'activities_missing_successor',
] as const;

/** Stat keys that count an actual (or would-be) repair, summed into the total. */
const REPAIR_STAT_KEYS = [
  'duplicate_refs_fixed',
  'duration_clamped',
  'progress_clamped',
  'parents_cleared',
  'parent_cycles_broken',
  'relationship_types_coerced',
  'relationships_dropped_self',
  'relationships_dropped_dangling',
  'relationships_deduped',
] as const;

/** Human label for a stat key (falls back to a humanised key). */
function statLabel(
  t: (k: string, o?: Record<string, unknown>) => string,
  key: string,
): string {
  const defaults: Record<string, string> = {
    activities: 'Activities',
    relationships: 'Relationships',
    lead_count: 'Leads (negative lag)',
    hard_constraint_count: 'Hard constraints',
    activities_missing_predecessor: 'Missing predecessor',
    activities_missing_successor: 'Missing successor',
    duplicate_refs_fixed: 'Duplicate refs fixed',
    duration_clamped: 'Durations clamped',
    progress_clamped: 'Progress clamped',
    parents_cleared: 'Parents cleared',
    parent_cycles_broken: 'Parent cycles broken',
    relationship_types_coerced: 'Link types coerced',
    relationships_dropped_self: 'Self-links dropped',
    relationships_dropped_dangling: 'Dangling links dropped',
    relationships_deduped: 'Duplicate links removed',
  };
  const fallback =
    defaults[key] ??
    key
      .replace(/_/g, ' ')
      .replace(/^\w/, (c) => c.toUpperCase());
  return t(`schedule.interchange.stat_${key}`, { defaultValue: fallback });
}

/** Sum the repair-class stats into the "total repairs that would apply" figure. */
function totalRepairs(stats: Record<string, number>): number {
  return REPAIR_STAT_KEYS.reduce((sum, k) => sum + (Number(stats[k]) || 0), 0);
}

export function ScheduleInterchangePanel({
  scheduleId,
  projectId,
}: ScheduleInterchangePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // ── Import form state ──────────────────────────────────────────────────
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importDoc, setImportDoc] = useState<InterchangeDocument | null>(null);
  const [importFileName, setImportFileName] = useState<string>('');
  const [clean, setClean] = useState(true);
  const [nameOverride, setNameOverride] = useState('');

  // ── Results ────────────────────────────────────────────────────────────
  const [preview, setPreview] = useState<ScheduleCleanPreview | null>(null);
  const [importResult, setImportResult] = useState<ScheduleImportResult | null>(null);

  // ── Vendor file import (#205): MS Project XML / XER ──────────────────────
  const vendorInputRef = useRef<HTMLInputElement>(null);
  const [vendorFile, setVendorFile] = useState<File | null>(null);
  const [vendorResult, setVendorResult] = useState<VendorImportResult | null>(null);

  /* ── Export ──────────────────────────────────────────────────────────── */
  const exportMut = useMutation({
    mutationFn: () => scheduleApi.exportSchedule(scheduleId),
    onSuccess: (data: ScheduleExport) => {
      // Build a client-side download of the interchange JSON.
      try {
        const blob = new Blob([JSON.stringify(data.document, null, 2)], {
          type: 'application/json',
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `schedule-${data.schedule_id}.json`;
        link.click();
        URL.revokeObjectURL(url);
        addToast({
          type: 'success',
          title: t('schedule.interchange.export_done', { defaultValue: 'Schedule exported' }),
          message: t('schedule.interchange.export_done_msg', {
            defaultValue: 'The interchange document downloaded to your device.',
          }),
        });
      } catch (e) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: getErrorMessage(e),
        });
      }
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  /* ── Health check (clean-preview) ────────────────────────────────────── */
  const previewMut = useMutation({
    mutationFn: () => scheduleApi.cleanPreviewSchedule(scheduleId),
    onSuccess: (data) => {
      setPreview(data);
      addToast({
        type: 'success',
        title: t('schedule.interchange.health_done', { defaultValue: 'Health check ready' }),
        message: t('schedule.interchange.health_done_msg', {
          defaultValue: 'This is a read-only dry-run. Nothing in the schedule changed.',
        }),
      });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  /* ── Import ──────────────────────────────────────────────────────────── */
  const importMut = useMutation({
    mutationFn: () => {
      if (!importDoc) {
        // Guarded by the disabled button; defensive only.
        return Promise.reject(new Error('No document loaded'));
      }
      return scheduleApi.importSchedule({
        project_id: projectId,
        document: importDoc,
        clean,
        name_override: nameOverride.trim() ? nameOverride.trim() : null,
      });
    },
    onSuccess: (data) => {
      setImportResult(data);
      // The new schedule should appear in the project's schedule list.
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      addToast({
        type: 'success',
        title: t('schedule.interchange.import_done', { defaultValue: 'Schedule imported' }),
        message: t('schedule.interchange.import_done_msg', {
          defaultValue: 'Created {{activities}} activities and {{relationships}} links.',
          activities: data.activity_count,
          relationships: data.relationship_count,
        }),
      });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  /* ── Export to vendor formats (#205) ─────────────────────────────────── */
  const exportMspMut = useMutation({
    mutationFn: () =>
      scheduleApi.exportMspXml(scheduleId, `schedule-${scheduleId}.xml`),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('schedule.interchange.msp_export_done', {
          defaultValue: 'Microsoft Project XML downloaded',
        }),
      });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  const exportCsvMut = useMutation({
    mutationFn: () =>
      scheduleApi.exportCsv(scheduleId, `schedule-${scheduleId}.csv`),
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  /* ── Import a vendor file (MS Project XML / XER) (#205) ───────────────── */
  const vendorImportMut = useMutation({
    mutationFn: () => {
      if (!vendorFile) return Promise.reject(new Error('No file selected'));
      const isXer = vendorFile.name.toLowerCase().endsWith('.xer');
      return isXer
        ? scheduleApi.importXer(scheduleId, vendorFile)
        : scheduleApi.importMspXml(scheduleId, vendorFile);
    },
    onSuccess: (data) => {
      setVendorResult(data);
      // The file imports into THIS schedule, so refresh its activities/gantt.
      queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
      queryClient.invalidateQueries({ queryKey: ['schedule-activities', scheduleId] });
      queryClient.invalidateQueries({ queryKey: ['cpm', scheduleId] });
      addToast({
        type: 'success',
        title: t('schedule.interchange.vendor_import_done', {
          defaultValue: 'Schedule file imported',
        }),
        message: t('schedule.interchange.vendor_import_done_msg', {
          defaultValue: 'Added {{activities}} activities and {{relationships}} links.',
          activities: data.activities_imported,
          relationships: data.relationships_imported,
        }),
      });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  // Parse a chosen .json file into the interchange document, client-side.
  const handleFile = (file: File | undefined) => {
    if (!file) return;
    setImportResult(null);
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('Document must be a JSON object');
        }
        setImportDoc(parsed as InterchangeDocument);
        setImportFileName(file.name);
      } catch (e) {
        setImportDoc(null);
        setImportFileName('');
        addToast({
          type: 'error',
          title: t('schedule.interchange.parse_error', { defaultValue: 'Could not read file' }),
          message:
            e instanceof Error
              ? e.message
              : t('schedule.interchange.parse_error_msg', {
                  defaultValue: 'The selected file is not valid interchange JSON.',
                }),
        });
      }
    };
    reader.onerror = () => {
      addToast({
        type: 'error',
        title: t('schedule.interchange.parse_error', { defaultValue: 'Could not read file' }),
        message: t('schedule.interchange.parse_error_msg', {
          defaultValue: 'The selected file is not valid interchange JSON.',
        }),
      });
    };
    reader.readAsText(file);
  };

  return (
    <div className="space-y-4" data-testid="schedule-interchange-panel">
      {/* ── Export ──────────────────────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-1 flex items-center gap-2">
          <Download size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.interchange.export_title', { defaultValue: 'Export schedule' })}
          </h3>
        </div>
        <p className="mb-3 text-xs text-content-secondary">
          {t('schedule.interchange.export_desc', {
            defaultValue:
              'Download this schedule as an open, lossless interchange document (JSON) - the full activity set, logic and calendars. Use it to archive a snapshot or move the plan between projects.',
          })}
        </p>
        <Button
          variant="primary"
          onClick={() => exportMut.mutate()}
          disabled={exportMut.isPending}
          icon={
            exportMut.isPending ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Download size={16} />
            )
          }
        >
          {exportMut.isPending
            ? t('schedule.interchange.exporting', { defaultValue: 'Exporting...' })
            : t('schedule.interchange.export', { defaultValue: 'Export' })}
        </Button>

        {/* Vendor exports (#205): hand the plan to other tools. */}
        <div className="mt-3 border-t border-border-light pt-3">
          <p className="mb-2 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('schedule.interchange.other_formats', {
              defaultValue: 'Or export to another tool',
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => exportMspMut.mutate()}
              disabled={exportMspMut.isPending}
              data-testid="schedule-export-msp-xml"
              icon={
                exportMspMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <FileCode2 size={14} />
                )
              }
            >
              {t('schedule.interchange.export_msp', {
                defaultValue: 'Microsoft Project XML',
              })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => exportCsvMut.mutate()}
              disabled={exportCsvMut.isPending}
              data-testid="schedule-export-csv"
              icon={
                exportCsvMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <FileSpreadsheet size={14} />
                )
              }
            >
              {t('schedule.interchange.export_csv', { defaultValue: 'CSV' })}
            </Button>
          </div>
        </div>
      </Card>

      {/* ── Health check (clean-preview) ────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <Stethoscope size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.interchange.health_title', { defaultValue: 'Schedule health check' })}
          </h3>
          <Badge variant="neutral">
            {t('schedule.interchange.read_only', { defaultValue: 'Read-only' })}
          </Badge>
        </div>
        <p className="mb-3 text-xs text-content-secondary">
          {t('schedule.interchange.health_desc', {
            defaultValue:
              'Run a logic-hygiene dry-run on this schedule. It reports the repairs a normalise-on-import would apply (dropping dangling or self links, clamping durations and progress, breaking parent cycles, and more) plus key quality tallies. Nothing is changed.',
          })}
        </p>
        <Button
          variant="secondary"
          onClick={() => previewMut.mutate()}
          disabled={previewMut.isPending}
          icon={
            previewMut.isPending ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Stethoscope size={16} />
            )
          }
        >
          {previewMut.isPending
            ? t('schedule.interchange.checking', { defaultValue: 'Checking...' })
            : t('schedule.interchange.check_health', { defaultValue: 'Check health' })}
        </Button>

        {preview && (
          <div className="mt-4 space-y-4 border-t border-border-light pt-4">
            <HealthStats stats={preview.stats} />
            <ActionsList
              actions={preview.actions}
              emptyLabel={t('schedule.interchange.health_clean', {
                defaultValue: 'No repairs needed - this schedule is already clean.',
              })}
              title={t('schedule.interchange.would_apply', {
                defaultValue: 'Repairs that would apply',
              })}
            />
          </div>
        )}
      </Card>

      {/* ── Import ──────────────────────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-1 flex items-center gap-2">
          <Upload size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.interchange.import_title', { defaultValue: 'Import schedule' })}
          </h3>
        </div>
        <p className="mb-3 text-xs text-content-secondary">
          {t('schedule.interchange.import_desc', {
            defaultValue:
              'Load an interchange document (JSON) to create a new schedule in this project. Optionally normalise it on import to repair logic issues automatically.',
          })}
        </p>

        <div className="space-y-3">
          {/* File picker */}
          <div>
            <label htmlFor="interchange-file" className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-secondary">
              {t('schedule.interchange.file_label', { defaultValue: 'Interchange document (.json)' })}
            </label>
            <input
              ref={fileInputRef}
              id="interchange-file"
              type="file"
              accept="application/json,.json"
              onChange={(e) => handleFile(e.target.files?.[0])}
              className="block w-full text-sm text-content-secondary file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-surface-secondary file:px-3 file:py-2 file:text-sm file:font-medium file:text-content-primary hover:file:bg-surface-secondary/70"
            />
            {importFileName && (
              <span className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-content-secondary">
                <FileJson size={13} className="text-oe-blue" />
                {importFileName}
              </span>
            )}
          </div>

          {/* Normalise-on-import toggle */}
          <label className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={clean}
              onChange={(e) => setClean(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-border text-oe-blue accent-oe-blue focus:ring-oe-blue/30"
            />
            <span>
              <span className="font-medium text-content-primary">
                {t('schedule.interchange.normalise', { defaultValue: 'Normalise on import' })}
              </span>
              <span className="block text-xs text-content-tertiary">
                {t('schedule.interchange.normalise_hint', {
                  defaultValue: 'Run the logic-hygiene cleaner while importing (recommended).',
                })}
              </span>
            </span>
          </label>

          {/* Optional name override */}
          <Input
            label={t('schedule.interchange.name_override', { defaultValue: 'Name override (optional)' })}
            placeholder={t('schedule.interchange.name_override_ph', {
              defaultValue: 'Keep the document name, or type a new one',
            })}
            value={nameOverride}
            onChange={(e) => setNameOverride(e.target.value)}
          />

          <Button
            variant="primary"
            onClick={() => importMut.mutate()}
            disabled={!importDoc || importMut.isPending}
            icon={
              importMut.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Upload size={16} />
              )
            }
          >
            {importMut.isPending
              ? t('schedule.interchange.importing', { defaultValue: 'Importing...' })
              : t('schedule.interchange.import', { defaultValue: 'Import' })}
          </Button>
        </div>

        {/* Import result summary */}
        {importResult && (
          <div className="mt-4 space-y-4 border-t border-border-light pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <CheckCircle2 size={16} className="text-semantic-success" />
              <span className="text-sm font-semibold text-content-primary">
                {t('schedule.interchange.import_summary', { defaultValue: 'Imported' })}
              </span>
              <Badge variant="success">
                {t('schedule.interchange.created_activities', {
                  defaultValue: '{{count}} activities',
                  count: importResult.activity_count,
                })}
              </Badge>
              <Badge variant="blue">
                {t('schedule.interchange.created_relationships', {
                  defaultValue: '{{count}} links',
                  count: importResult.relationship_count,
                })}
              </Badge>
            </div>
            <HealthStats stats={importResult.stats} />
            <ActionsList
              actions={importResult.clean_actions}
              emptyLabel={t('schedule.interchange.import_no_repairs', {
                defaultValue: 'No repairs were applied during import.',
              })}
              title={t('schedule.interchange.applied', { defaultValue: 'Repairs applied' })}
            />
          </div>
        )}
      </Card>

      {/* ── Import from MS Project / XER (#205) ───────────────────────────── */}
      <Card padding="md">
        <div className="mb-1 flex items-center gap-2">
          <FileCode2 size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.interchange.vendor_import_title', {
              defaultValue: 'Import a Microsoft Project XML or XER file',
            })}
          </h3>
        </div>
        <p className="mb-3 text-xs text-content-secondary">
          {t('schedule.interchange.vendor_import_desc', {
            defaultValue:
              'Load a Microsoft Project XML (.xml) or XER (.xer) file. Its tasks and logic links are added to this schedule, ready for the CPM engine.',
          })}
        </p>

        <div className="space-y-3">
          <div>
            <label
              htmlFor="vendor-file"
              className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-secondary"
            >
              {t('schedule.interchange.vendor_file_label', {
                defaultValue: 'Project file (.xml or .xer)',
              })}
            </label>
            <input
              ref={vendorInputRef}
              id="vendor-file"
              type="file"
              accept=".xml,.xer,application/xml,text/xml"
              data-testid="schedule-vendor-file-input"
              onChange={(e) => {
                setVendorResult(null);
                setVendorFile(e.target.files?.[0] ?? null);
              }}
              className="block w-full text-sm text-content-secondary file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-surface-secondary file:px-3 file:py-2 file:text-sm file:font-medium file:text-content-primary hover:file:bg-surface-secondary/70"
            />
            {vendorFile && (
              <span className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-content-secondary">
                <FileCode2 size={13} className="text-oe-blue" />
                {vendorFile.name}
              </span>
            )}
          </div>

          <Button
            variant="primary"
            onClick={() => vendorImportMut.mutate()}
            disabled={!vendorFile || vendorImportMut.isPending}
            data-testid="schedule-vendor-import"
            icon={
              vendorImportMut.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Upload size={16} />
              )
            }
          >
            {vendorImportMut.isPending
              ? t('schedule.interchange.importing', { defaultValue: 'Importing...' })
              : t('schedule.interchange.vendor_import', {
                  defaultValue: 'Import into this schedule',
                })}
          </Button>
        </div>

        {vendorResult && (
          <div className="mt-4 space-y-3 border-t border-border-light pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <CheckCircle2 size={16} className="text-semantic-success" />
              <Badge variant="success">
                {t('schedule.interchange.created_activities', {
                  defaultValue: '{{count}} activities',
                  count: vendorResult.activities_imported,
                })}
              </Badge>
              <Badge variant="blue">
                {t('schedule.interchange.created_relationships', {
                  defaultValue: '{{count}} links',
                  count: vendorResult.relationships_imported,
                })}
              </Badge>
            </div>
            {vendorResult.warnings.length > 0 && (
              <ul className="space-y-1 rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg/40 p-2 text-xs text-content-secondary">
                {vendorResult.warnings.slice(0, 20).map((w, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <AlertTriangle
                      size={12}
                      className="mt-0.5 shrink-0 text-semantic-warning"
                    />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ── Hygiene stats grid ──────────────────────────────────────────────────── */

function HealthStats({ stats }: { stats: Record<string, number> }) {
  const { t } = useTranslation();
  const repairs = totalRepairs(stats);

  // Secondary keys: everything not highlighted, not a repair key, and not the
  // plain activities/relationships totals (shown separately, neutral).
  const skip = new Set<string>([
    ...HIGHLIGHT_STATS,
    ...REPAIR_STAT_KEYS,
  ]);
  const others = Object.keys(stats)
    .filter((k) => !skip.has(k))
    .sort();

  return (
    <div className="space-y-3">
      {/* Highlighted quality figures + total repairs */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {HIGHLIGHT_STATS.map((key) => {
          const value = Number(stats[key]) || 0;
          return (
            <StatTile
              key={key}
              label={statLabel(t, key)}
              value={value}
              tone={value > 0 ? 'warning' : 'neutral'}
            />
          );
        })}
        <StatTile
          label={t('schedule.interchange.total_repairs', {
            defaultValue: 'Total repairs that would apply',
          })}
          value={repairs}
          tone={repairs > 0 ? 'error' : 'success'}
        />
      </div>

      {/* Remaining counts (activities / relationships / per-repair breakdown) */}
      {others.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {others.map((key) => (
            <span
              key={key}
              className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-secondary/40 px-2.5 py-1 text-xs"
            >
              <span className="text-content-secondary">{statLabel(t, key)}</span>
              <span className="font-mono font-semibold tabular-nums text-content-primary">
                {Number(stats[key]) || 0}
              </span>
            </span>
          ))}
        </div>
      )}

      {/* Per-repair breakdown — only the non-zero ones, to keep it focused. */}
      {repairs > 0 && (
        <div className="flex flex-wrap gap-2">
          {REPAIR_STAT_KEYS.filter((k) => (Number(stats[k]) || 0) > 0).map((key) => (
            <span
              key={key}
              className="inline-flex items-center gap-1.5 rounded-full border border-semantic-error/30 bg-semantic-error-bg px-2.5 py-1 text-xs"
            >
              <span className="text-content-secondary">{statLabel(t, key)}</span>
              <span className="font-mono font-semibold tabular-nums text-semantic-error">
                {Number(stats[key]) || 0}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Actions list ────────────────────────────────────────────────────────── */

function ActionsList({
  actions,
  emptyLabel,
  title,
}: {
  actions: CleanAction[];
  emptyLabel: string;
  title: string;
}) {
  if (actions.length === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck size={24} strokeWidth={1.5} />}
        title={emptyLabel}
      />
    );
  }
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <AlertTriangle size={14} className="text-semantic-warning" />
        <h4 className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
          {title}
        </h4>
        <Badge variant="neutral">{actions.length}</Badge>
      </div>
      <ul className="divide-y divide-border-light overflow-hidden rounded-lg border border-border-light">
        {actions.map((a, i) => (
          <li key={`${a.code}-${a.target}-${i}`} className="flex items-start gap-2 px-3 py-2 text-sm">
            <Badge variant="neutral">{a.code}</Badge>
            <span className="min-w-0 flex-1">
              <span className="block text-content-primary">{a.detail}</span>
              {a.target && (
                <span className="block text-2xs text-content-tertiary">{a.target}</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── Stat tile ───────────────────────────────────────────────────────────── */

type StatTone = 'neutral' | 'success' | 'warning' | 'error';

function StatTile({ label, value, tone }: { label: string; value: number; tone: StatTone }) {
  const toneCls: Record<StatTone, string> = {
    neutral: 'text-content-primary',
    success: 'text-semantic-success',
    warning: 'text-semantic-warning',
    error: 'text-semantic-error',
  };
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <div className="text-2xs uppercase tracking-wide text-content-tertiary" title={label}>
        {label}
      </div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${toneCls[tone]}`}>{value}</div>
    </div>
  );
}

export default ScheduleInterchangePanel;
