// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useCallback, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  Download,
  FileUp,
  Loader2,
  Package,
  Ruler,
  Shapes,
  Trash2,
  Upload,
  Weight,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { getIntlLocale, fmtFixed } from '@/shared/lib/formatters';
import { CollapsibleSection, EmptyState, StatCard } from '@/shared/ui';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { PageHeader } from '@/shared/ui/PageHeader';
import { downloadWithAuth } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  deleteImport,
  fetchCutting,
  fetchImports,
  fetchShapes,
  importAbsFile,
  previewAbsFile,
  type RebarCuttingEntry,
  type RebarImport,
  type RebarPreviewResponse,
  type RebarShape,
} from './api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string | null): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleDateString(getIntlLocale(), {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatWeight(kg: number | null): string {
  if (kg === null) return '-';
  if (kg >= 1000) return `${fmtFixed(kg / 1000, 2)} t`;
  return `${fmtFixed(kg, 1)} kg`;
}

// ---------------------------------------------------------------------------
// Sub-views
// ---------------------------------------------------------------------------

function fmtOptional(v: number | null, decimals: number): string {
  return v === null ? '-' : fmtFixed(v, decimals);
}

function ShapesTable({ shapes }: { shapes: Omit<RebarShape, 'id'>[] }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-left text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            <th className="px-3 py-2">{t('rebar_schedule.bar_mark', { defaultValue: 'Bar Mark' })}</th>
            <th className="px-3 py-2">{t('rebar_schedule.shape_code', { defaultValue: 'Shape' })}</th>
            <th className="px-3 py-2">{t('rebar_schedule.drawing', { defaultValue: 'Drawing' })}</th>
            <th className="px-3 py-2">{t('rebar_schedule.steel_grade', { defaultValue: 'Grade' })}</th>
            <th className="px-3 py-2 text-right">{t('rebar_schedule.diameter', { defaultValue: 'Dia (mm)' })}</th>
            <th className="px-3 py-2 text-right">{t('rebar_schedule.length', { defaultValue: 'Length (mm)' })}</th>
            <th className="px-3 py-2 text-right">{t('rebar_schedule.quantity', { defaultValue: 'Qty' })}</th>
            <th className="px-3 py-2 text-right">{t('rebar_schedule.weight_col', { defaultValue: 'Weight (kg)' })}</th>
          </tr>
        </thead>
        <tbody>
          {shapes.map((s) => (
            <tr
              key={s.line_no}
              className="border-b border-border-light last:border-0 hover:bg-surface-secondary/50 transition-colors"
            >
              <td className="px-3 py-2 font-medium text-content-primary">{s.position ?? '-'}</td>
              <td className="px-3 py-2 text-content-secondary">{s.super_group}</td>
              <td className="px-3 py-2 text-content-secondary">{s.drawing_ref ?? '-'}</td>
              <td className="px-3 py-2 text-content-secondary">{s.steel_grade ?? '-'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{s.diameter_mm ?? '-'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{s.length_mm ?? '-'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{s.quantity ?? '-'}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmtOptional(s.weight_kg, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CuttingTable({ cutting }: { cutting: RebarCuttingEntry[] }) {
  const { t } = useTranslation();
  const totalBars = cutting.reduce((s, c) => s + c.bars, 0);
  const totalWeight = cutting.reduce((s, c) => s + c.weight_kg, 0);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-left text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            <th className="px-3 py-2">{t('rebar_schedule.diameter', { defaultValue: 'Dia (mm)' })}</th>
            <th className="px-3 py-2 text-right">{t('rebar_schedule.bar_count', { defaultValue: 'Bars' })}</th>
            <th className="px-3 py-2 text-right">{t('rebar_schedule.total_weight', { defaultValue: 'Weight (kg)' })}</th>
          </tr>
        </thead>
        <tbody>
          {cutting.map((c) => (
            <tr
              key={c.diameter_mm}
              className="border-b border-border-light last:border-0 hover:bg-surface-secondary/50 transition-colors"
            >
              <td className="px-3 py-2 font-medium text-content-primary">{c.diameter_mm}</td>
              <td className="px-3 py-2 text-right tabular-nums">{c.bars}</td>
              <td className="px-3 py-2 text-right tabular-nums">{fmtFixed(c.weight_kg, 1)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border font-semibold text-content-primary">
            <td className="px-3 py-2">{t('rebar_schedule.total', { defaultValue: 'Total' })}</td>
            <td className="px-3 py-2 text-right tabular-nums">{totalBars}</td>
            <td className="px-3 py-2 text-right tabular-nums">{fmtFixed(totalWeight, 1)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Explainer
// ---------------------------------------------------------------------------

function RebarScheduleExplainer() {
  const { t } = useTranslation();

  const steps = [
    {
      num: 1,
      title: t('rebar_schedule.flow_step_1', { defaultValue: 'Upload an ABS file' }),
      desc: t('rebar_schedule.flow_step_1_desc', {
        defaultValue:
          'Drag and drop or browse for a .abs bar-bending schedule file. The parser reads bar marks, shape codes, dimensions and quantities.',
      }),
    },
    {
      num: 2,
      title: t('rebar_schedule.flow_step_2', { defaultValue: 'Review the preview' }),
      desc: t('rebar_schedule.flow_step_2_desc', {
        defaultValue:
          'Before committing, check the parsed shapes and any warnings. Fix problems in the source file and re-upload if needed.',
      }),
    },
    {
      num: 3,
      title: t('rebar_schedule.flow_step_3', { defaultValue: 'Inspect shapes and weights' }),
      desc: t('rebar_schedule.flow_step_3_desc', {
        defaultValue:
          'Open an import to see every bar mark with its shape, diameter, length, quantity and unit weight. Stat cards show totals at a glance.',
      }),
    },
    {
      num: 4,
      title: t('rebar_schedule.flow_step_4', { defaultValue: 'Generate cutting lists' }),
      desc: t('rebar_schedule.flow_step_4_desc', {
        defaultValue:
          'The cutting list groups bars by diameter and totals the count and weight, ready for ordering or export back to .abs.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="rebar_schedule.how"
      icon={<Ruler size={15} className="text-oe-blue" />}
      title={t('rebar_schedule.flow_title', { defaultValue: 'How rebar schedules work' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('rebar_schedule.flow_intro', {
          defaultValue:
            'Import bar-bending schedules from ABS files, review parsed shapes and weights, and produce cutting lists grouped by diameter for procurement.',
        })}
      </p>
      <ol className="mt-3 space-y-2">
        {steps.map((s) => (
          <li key={s.num} className="flex gap-3 text-xs">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-bold text-oe-blue-text">
              {s.num}
            </span>
            <div>
              <span className="font-medium text-content-primary">{s.title}</span>
              <span className="text-content-tertiary"> - {s.desc}</span>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('rebar_schedule.flow_related', { defaultValue: 'Related:' })}
        </span>{' '}
        <Link to="/boq" className="font-medium text-oe-blue-text hover:underline">
          {t('rebar_schedule.mod_boq', { defaultValue: 'BOQ' })}
        </Link>
        {' · '}
        <Link to="/quantities" className="font-medium text-oe-blue-text hover:underline">
          {t('rebar_schedule.mod_quantities', { defaultValue: 'Quantities' })}
        </Link>
        {' · '}
        <Link to="/formwork" className="font-medium text-oe-blue-text hover:underline">
          {t('rebar_schedule.mod_formwork', { defaultValue: 'Formwork' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type View = 'list' | 'preview' | 'detail';

export function RebarSchedulePage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const activeProjectId = useProjectContextStore(
    (s: { activeProjectId: string | null }) => s.activeProjectId,
  );
  const projectId = activeProjectId;

  // -- State ---------------------------------------------------------------
  const [view, setView] = useState<View>('list');
  const [selectedImportId, setSelectedImportId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RebarImport | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Upload / preview state
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<RebarPreviewResponse | null>(null);
  const [previewFile, setPreviewFile] = useState<File | null>(null);

  // -- Queries (all hooks ABOVE any early return) --------------------------
  const importsQuery = useQuery({
    queryKey: ['rebar-imports', projectId],
    queryFn: () => fetchImports(projectId!),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const shapesQuery = useQuery({
    queryKey: ['rebar-shapes', selectedImportId],
    queryFn: () => fetchShapes(selectedImportId!),
    enabled: !!selectedImportId && view === 'detail',
    staleTime: 60_000,
  });

  const cuttingQuery = useQuery({
    queryKey: ['rebar-cutting', selectedImportId],
    queryFn: () => fetchCutting(selectedImportId!),
    enabled: !!selectedImportId && view === 'detail',
    staleTime: 60_000,
  });

  // -- Derived data --------------------------------------------------------
  const imports = importsQuery.data ?? [];
  const shapes = shapesQuery.data ?? [];
  const cutting = cuttingQuery.data ?? [];
  const selectedImport = imports.find((i) => i.id === selectedImportId) ?? null;

  const stats = useMemo(() => {
    const totalImports = imports.length;
    const totalShapes = imports.reduce((s, i) => s + i.record_count, 0);
    const totalWeight = imports.reduce((s, i) => s + (i.total_weight_kg ?? 0), 0);
    return { totalImports, totalShapes, totalWeight };
  }, [imports]);

  // -- Handlers ------------------------------------------------------------

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith('.abs')) {
        setUploadError(
          t('rebar_schedule.invalid_file', {
            defaultValue: 'Only .abs files are supported.',
          }),
        );
        return;
      }
      setUploadError(null);
      setUploading(true);
      try {
        const data = await previewAbsFile(file, i18n.language);
        setPreviewData(data);
        setPreviewFile(file);
        setView('preview');
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : 'Preview failed');
      } finally {
        setUploading(false);
      }
    },
    [t, i18n.language],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
      e.target.value = '';
    },
    [handleFile],
  );

  const handleConfirmImport = useCallback(async () => {
    if (!previewFile || !projectId) return;
    setImporting(true);
    setUploadError(null);
    try {
      const created = await importAbsFile(previewFile, projectId, i18n.language);
      await queryClient.invalidateQueries({ queryKey: ['rebar-imports', projectId] });
      setPreviewData(null);
      setPreviewFile(null);
      setSelectedImportId(created.import_record.id);
      setView('detail');
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setImporting(false);
    }
  }, [previewFile, projectId, queryClient, i18n.language]);

  const handleCancelPreview = useCallback(() => {
    setPreviewData(null);
    setPreviewFile(null);
    setUploadError(null);
    setView('list');
  }, []);

  const handleOpenDetail = useCallback((imp: RebarImport) => {
    setSelectedImportId(imp.id);
    setView('detail');
  }, []);

  const handleBackToList = useCallback(() => {
    setSelectedImportId(null);
    setView('list');
  }, []);

  const handleExport = useCallback(async () => {
    if (!selectedImportId || !selectedImport) return;
    try {
      await downloadWithAuth(
        `/api/v1/rebar-schedule/imports/${selectedImportId}/export`,
        `${selectedImport.filename}`,
      );
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Export failed');
    }
  }, [selectedImportId, selectedImport]);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteImport(deleteTarget.id);
      await queryClient.invalidateQueries({ queryKey: ['rebar-imports', projectId] });
      if (selectedImportId === deleteTarget.id) {
        setSelectedImportId(null);
        setView('list');
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  }, [deleteTarget, projectId, queryClient, selectedImportId]);

  // -- No project selected -------------------------------------------------
  if (!projectId) {
    return (
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6">
        <PageHeader
          srTitle={t('rebar_schedule.title', { defaultValue: 'Rebar Schedule' })}
          subtitle={t('rebar_schedule.subtitle', {
            defaultValue: 'Import, validate and manage reinforcement bar schedules from ABS files.',
          })}
        />
        <RebarScheduleExplainer />
        <EmptyState
          icon={<Ruler className="h-6 w-6" />}
          title={t('rebar_schedule.no_project', { defaultValue: 'Select a project' })}
          description={t('rebar_schedule.no_project_desc', {
            defaultValue: 'Choose a project from the header to manage its rebar schedules.',
          })}
        />
      </div>
    );
  }

  // -- Preview view --------------------------------------------------------
  if (view === 'preview' && previewData) {
    return (
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6">
        <PageHeader
          srTitle={t('rebar_schedule.title', { defaultValue: 'Rebar Schedule' })}
          subtitle={t('rebar_schedule.preview_subtitle', {
            defaultValue: 'Review the parsed file before importing.',
          })}
          actions={
            <>
              <button
                onClick={handleCancelPreview}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <X className="h-4 w-4" aria-hidden />
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                onClick={handleConfirmImport}
                disabled={importing}
                className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-2 text-sm font-medium text-content-inverse hover:opacity-90 disabled:opacity-40 transition-colors"
              >
                {importing ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Upload className="h-4 w-4" aria-hidden />
                )}
                {t('rebar_schedule.confirm_import', { defaultValue: 'Import' })}
              </button>
            </>
          }
        />

        {uploadError && (
          <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm text-semantic-error">
            {uploadError}
          </div>
        )}

        {previewData.validation.findings.length > 0 && (
          <div className="rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg p-3 text-sm text-semantic-warning">
            <p className="font-medium mb-1">
              {t('rebar_schedule.warnings', { defaultValue: 'Warnings' })}
            </p>
            <ul className="list-disc list-inside space-y-0.5">
              {previewData.validation.findings.map((f, i) => (
                <li key={`${f.rule_id}-${f.element_ref ?? ''}-${i}`}>
                  {f.element_ref ? `${f.element_ref}: ` : ''}
                  {f.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatCard
            label={t('rebar_schedule.stat_filename', { defaultValue: 'File' })}
            value={previewFile?.name ?? ''}
            icon={FileUp}
            tone="blue"
          />
          <StatCard
            label={t('rebar_schedule.stat_shapes', { defaultValue: 'Shapes' })}
            value={previewData.record_count}
            icon={Shapes}
          />
          <StatCard
            label={t('rebar_schedule.stat_weight', { defaultValue: 'Total Weight' })}
            value={formatWeight(previewData.total_weight_kg)}
            icon={Weight}
          />
        </div>

        <div className="rounded-xl border border-border-light bg-surface-elevated/90 shadow-xs">
          <div className="border-b border-border-light px-4 py-3">
            <h2 className="text-sm font-semibold text-content-primary">
              {t('rebar_schedule.shapes', { defaultValue: 'Shapes' })}
            </h2>
          </div>
          <ShapesTable shapes={previewData.shapes} />
        </div>
      </div>
    );
  }

  // -- Detail view ---------------------------------------------------------
  if (view === 'detail' && selectedImport) {
    const detailLoading = shapesQuery.isLoading || cuttingQuery.isLoading;
    return (
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6">
        <PageHeader
          srTitle={t('rebar_schedule.title', { defaultValue: 'Rebar Schedule' })}
          subtitle={selectedImport.filename}
          actions={
            <>
              <button
                onClick={handleBackToList}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden />
                {t('rebar_schedule.back_to_list', { defaultValue: 'All Imports' })}
              </button>
              <button
                onClick={handleExport}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm font-medium text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <Download className="h-4 w-4" aria-hidden />
                {t('rebar_schedule.export', { defaultValue: 'Export .abs' })}
              </button>
              <button
                onClick={() => setDeleteTarget(selectedImport)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-3 py-2 text-sm font-medium text-semantic-error hover:opacity-80 transition-colors"
              >
                <Trash2 className="h-4 w-4" aria-hidden />
                {t('common.delete', { defaultValue: 'Delete' })}
              </button>
            </>
          }
        />

        {uploadError && (
          <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm text-semantic-error">
            {uploadError}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard
            label={t('rebar_schedule.stat_imported', { defaultValue: 'Imported' })}
            value={formatDate(selectedImport.created_at)}
            icon={FileUp}
            tone="blue"
          />
          <StatCard
            label={t('rebar_schedule.stat_shapes', { defaultValue: 'Shapes' })}
            value={selectedImport.record_count}
            icon={Shapes}
          />
          <StatCard
            label={t('rebar_schedule.stat_weight', { defaultValue: 'Total Weight' })}
            value={formatWeight(selectedImport.total_weight_kg)}
            icon={Weight}
          />
          <StatCard
            label={t('rebar_schedule.stat_diameters', { defaultValue: 'Diameters' })}
            value={cutting.length}
            icon={Ruler}
          />
        </div>

        {detailLoading && (
          <div className="flex items-center justify-center py-16 text-content-tertiary">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            {t('common.loading', { defaultValue: 'Loading...' })}
          </div>
        )}

        {!detailLoading && shapes.length > 0 && (
          <div className="rounded-xl border border-border-light bg-surface-elevated/90 shadow-xs">
            <div className="border-b border-border-light px-4 py-3">
              <h2 className="text-sm font-semibold text-content-primary">
                {t('rebar_schedule.shapes', { defaultValue: 'Shapes' })}
                <span className="ml-2 text-xs font-normal text-content-tertiary">
                  ({shapes.length})
                </span>
              </h2>
            </div>
            <ShapesTable shapes={shapes} />
          </div>
        )}

        {!detailLoading && cutting.length > 0 && (
          <div className="rounded-xl border border-border-light bg-surface-elevated/90 shadow-xs">
            <div className="border-b border-border-light px-4 py-3">
              <h2 className="text-sm font-semibold text-content-primary">
                {t('rebar_schedule.cutting_list', { defaultValue: 'Cutting List' })}
              </h2>
            </div>
            <CuttingTable cutting={cutting} />
          </div>
        )}
      </div>
    );
  }

  // -- List view (default) -------------------------------------------------
  return (
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-6">
      <PageHeader
        srTitle={t('rebar_schedule.title', { defaultValue: 'Rebar Schedule' })}
        subtitle={t('rebar_schedule.subtitle', {
          defaultValue: 'Import, validate and manage reinforcement bar schedules from ABS files.',
        })}
      />

      <RebarScheduleExplainer />

      {/* Stats */}
      {imports.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatCard
            label={t('rebar_schedule.stat_imports', { defaultValue: 'Imports' })}
            value={stats.totalImports}
            icon={Package}
            tone="blue"
          />
          <StatCard
            label={t('rebar_schedule.stat_shapes', { defaultValue: 'Shapes' })}
            value={stats.totalShapes}
            icon={Shapes}
          />
          <StatCard
            label={t('rebar_schedule.stat_weight', { defaultValue: 'Total Weight' })}
            value={formatWeight(stats.totalWeight)}
            icon={Weight}
          />
        </div>
      )}

      {/* Upload area */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragOver
            ? 'border-oe-blue bg-oe-blue/5'
            : 'border-border-light bg-surface-elevated/90 hover:border-border'
        }`}
      >
        {uploading ? (
          <Loader2 className="h-8 w-8 animate-spin text-oe-blue" />
        ) : (
          <>
            <FileUp className="mb-3 h-8 w-8 text-content-tertiary" />
            <p className="text-sm font-medium text-content-primary">
              {t('rebar_schedule.drop_abs', {
                defaultValue: 'Drag and drop an .abs file here',
              })}
            </p>
            <p className="mt-1 text-xs text-content-tertiary">
              {t('rebar_schedule.or_browse', {
                defaultValue: 'or click to browse',
              })}
            </p>
            <input
              type="file"
              accept=".abs"
              onChange={handleFileInput}
              className="absolute inset-0 cursor-pointer opacity-0"
              aria-label={t('rebar_schedule.upload_label', { defaultValue: 'Upload ABS file' })}
            />
          </>
        )}
      </div>

      {uploadError && (
        <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm text-semantic-error">
          {uploadError}
        </div>
      )}

      {/* Import list */}
      {importsQuery.isLoading && (
        <div className="flex items-center justify-center py-16 text-content-tertiary">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {!importsQuery.isLoading && imports.length === 0 && (
        <EmptyState
          icon={<Ruler className="h-6 w-6" />}
          title={t('rebar_schedule.empty', { defaultValue: 'No rebar imports yet' })}
          description={t('rebar_schedule.empty_desc', {
            defaultValue: 'Upload an ABS file above to get started.',
          })}
        />
      )}

      {!importsQuery.isLoading && imports.length > 0 && (
        <div className="space-y-2">
          {imports.map((imp) => (
            <div
              key={imp.id}
              onClick={() => handleOpenDetail(imp)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleOpenDetail(imp);
                }
              }}
              role="button"
              tabIndex={0}
              className="flex items-center gap-4 rounded-xl border border-border-light bg-surface-elevated/90 px-4 py-3 shadow-xs transition-shadow hover:shadow-sm cursor-pointer"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue-text">
                <FileUp className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-content-primary">{imp.filename}</p>
                <p className="mt-0.5 text-xs text-content-tertiary">{formatDate(imp.created_at)}</p>
              </div>
              <div className="hidden items-center gap-4 text-xs text-content-secondary sm:flex">
                <span className="tabular-nums">
                  {imp.record_count} {t('rebar_schedule.shapes_short', { defaultValue: 'shapes' })}
                </span>
                <span className="tabular-nums">{formatWeight(imp.total_weight_kg)}</span>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setDeleteTarget(imp);
                }}
                className="shrink-0 rounded-lg p-2 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error transition-colors"
                aria-label={t('common.delete', { defaultValue: 'Delete' })}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={!!deleteTarget}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
        title={t('rebar_schedule.delete_title', { defaultValue: 'Delete import' })}
        message={t('rebar_schedule.delete_message', {
          defaultValue: 'This will permanently remove the import and all its shapes. This cannot be undone.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={deleting}
      />
    </div>
  );
}
