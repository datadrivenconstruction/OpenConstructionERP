import { useState, useCallback, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Euro,
  Upload,
  Download,
  FileUp,
  FileDown,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Eye,
  Info,
  X,
  Printer,
} from 'lucide-react';
import { Button, Badge } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { parseExcelFile } from '../_shared/excelImport';
import { exportToCSV, downloadBlob } from '../_shared/excelExport';
import { printBOQReport } from '../_shared/pdfBOQExport';
import type { ExchangePosition, ImportParseResult } from '../_shared/templateTypes';
import { DPGF_TEMPLATE, LOTS_TECHNIQUES } from './dpgfTemplate';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DPGFExportFormat = 'DPGF' | 'DQE';

interface Project {
  id: string;
  name: string;
}

interface BOQ {
  id: string;
  name: string;
  project_id: string;
}

interface BOQPosition {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total?: number;
  parent_id?: string | null;
  is_section?: boolean;
  section?: string;
}

// ---------------------------------------------------------------------------
// Import Preview Table
// ---------------------------------------------------------------------------

function ImportPreview({
  positions,
  t,
}: {
  positions: ExchangePosition[];
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const [showAll, setShowAll] = useState(false);
  const displayed = showAll ? positions : positions.slice(0, 20);

  return (
    <div className="border border-border-light rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-surface-tertiary/50 flex items-center justify-between">
        <span className="text-xs font-medium text-content-secondary">
          {t('dpgf.preview', { defaultValue: 'Preview' })}: {positions.length}{' '}
          {t('dpgf.positions', { defaultValue: 'positions' })}
        </span>
        {positions.length > 20 && (
          <button
            onClick={() => setShowAll((v) => !v)}
            className="text-2xs text-oe-blue hover:underline"
          >
            {showAll
              ? t('dpgf.show_less', { defaultValue: 'Show less' })
              : t('dpgf.show_all', { defaultValue: `Show all ${positions.length}` })}
          </button>
        )}
      </div>
      <div className="overflow-x-auto max-h-80">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-surface-secondary/50 sticky top-0">
              <th className="px-3 py-1.5 text-left font-medium text-content-secondary w-24">
                {t('boq.ordinal', { defaultValue: 'Ordinal' })}
              </th>
              <th className="px-3 py-1.5 text-left font-medium text-content-secondary">
                {t('boq.description', { defaultValue: 'Description' })}
              </th>
              <th className="px-3 py-1.5 text-center font-medium text-content-secondary w-16">
                {t('boq.unit', { defaultValue: 'Unit' })}
              </th>
              <th className="px-3 py-1.5 text-right font-medium text-content-secondary w-20">
                {t('boq.quantity', { defaultValue: 'Qty' })}
              </th>
              <th className="px-3 py-1.5 text-right font-medium text-content-secondary w-20">
                {t('boq.unit_rate', { defaultValue: 'Rate' })}
              </th>
              <th className="px-3 py-1.5 text-left font-medium text-content-secondary w-32">
                {t('dpgf.lot', { defaultValue: 'Lot' })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {displayed.map((pos, idx) => (
              <tr
                key={idx}
                className={`hover:bg-surface-secondary/30 ${idx % 2 === 0 ? 'bg-surface-primary/50' : ''}`}
              >
                <td className="px-3 py-1.5 font-mono text-content-tertiary">{pos.ordinal}</td>
                <td
                  className="px-3 py-1.5 text-content-primary max-w-[300px] truncate"
                  title={pos.description}
                >
                  {pos.description || '-'}
                </td>
                <td className="px-3 py-1.5 text-center text-content-secondary">
                  {pos.unit || '-'}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {pos.quantity > 0 ? pos.quantity.toFixed(3) : '-'}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {pos.unitRate > 0 ? pos.unitRate.toFixed(2) : '-'}
                </td>
                <td
                  className="px-3 py-1.5 text-content-tertiary text-2xs truncate"
                  title={pos.section}
                >
                  {pos.section || '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lots Techniques Reference
// ---------------------------------------------------------------------------

function LotsReference({
  t,
  locale,
}: {
  t: (key: string, opts?: Record<string, unknown>) => string;
  locale: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const isFr = locale.startsWith('fr');

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 text-xs font-medium text-content-secondary hover:text-content-primary w-full text-left"
      >
        <Info size={13} className="text-emerald-600 shrink-0" />
        {t('dpgf.lot', { defaultValue: 'Lot' })} techniques ({LOTS_TECHNIQUES.length})
        <span className="ml-auto text-2xs text-content-quaternary">
          {expanded ? '-' : '+'}
        </span>
      </button>
      {expanded && (
        <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1">
          {LOTS_TECHNIQUES.map((lot) => (
            <div key={lot.code} className="flex items-center gap-2 text-2xs py-0.5">
              <Badge variant="neutral" className="font-mono text-2xs w-6 text-center shrink-0">
                {lot.code}
              </Badge>
              <span className="text-content-secondary truncate">
                {isFr ? lot.labelFr : lot.label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Module Component
// ---------------------------------------------------------------------------

export default function DPGFExchangeModule() {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // --- Import state ---
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [parseResult, setParseResult] = useState<ImportParseResult | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [importTargetBoqId, setImportTargetBoqId] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    imported: number;
    errors: string[];
  } | null>(null);

  // --- Export state ---
  const [exportProjectId, setExportProjectId] = useState('');
  const [exportBoqId, setExportBoqId] = useState('');
  const [exportFormat, setExportFormat] = useState<DPGFExportFormat>('DPGF');
  const [isExporting, setIsExporting] = useState(false);
  const [showExportPreview, setShowExportPreview] = useState(false);

  // Tab state
  const [activeTab, setActiveTab] = useState<'import' | 'export'>('import');

  // --- Shared queries ---
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects-list'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  // Import: project selection for target BOQ
  const [importProjectId, setImportProjectId] = useState('');
  const { data: importBoqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-import', importProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${importProjectId}`),
    enabled: !!importProjectId,
  });

  // Export: BOQs for selected project
  const { data: exportBoqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-export', exportProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${exportProjectId}`),
    enabled: !!exportProjectId,
  });

  // Export: positions for selected BOQ
  const { data: exportPositions = [] } = useQuery<BOQPosition[]>({
    queryKey: ['boq-positions-export', exportBoqId],
    queryFn: async () => {
      const boq = await apiGet<{ positions?: BOQPosition[] }>(`/v1/boq/boqs/${exportBoqId}`);
      return boq.positions ?? [];
    },
    enabled: !!exportBoqId,
  });

  // ---------------------------------------------------------------------------
  // Import handlers
  // ---------------------------------------------------------------------------

  const handleFileSelect = useCallback(
    async (file: File) => {
      setImportFile(file);
      setParseResult(null);
      setParseError(null);
      setImportResult(null);

      try {
        const result = await parseExcelFile(file, DPGF_TEMPLATE.defaultColumns);

        if (result.positions.length === 0) {
          setParseError(
            t('dpgf.parse_error', {
              defaultValue:
                'No positions found in the file. Ensure the file is a valid DPGF/DQE spreadsheet (CSV or Excel).',
            }),
          );
        } else {
          setParseResult(result);
          addToast({
            type: 'success',
            title: t('dpgf.parsed_ok', { defaultValue: 'File parsed successfully' }),
            message: `${result.positions.length} positions found`,
          });
        }
      } catch {
        setParseError(
          t('dpgf.parse_error_generic', {
            defaultValue: 'Failed to parse the DPGF/DQE file.',
          }),
        );
      }
    },
    [addToast, t],
  );

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileSelect(file);
      e.target.value = '';
    },
    [handleFileSelect],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) handleFileSelect(file);
    },
    [handleFileSelect],
  );

  const handleImport = useCallback(async () => {
    if (!parseResult || !importTargetBoqId) return;
    setIsImporting(true);
    try {
      const payload = parseResult.positions.map((pos) => ({
        ordinal: pos.ordinal,
        description: pos.description,
        unit: pos.unit,
        quantity: pos.quantity,
        unit_rate: pos.unitRate,
        section: pos.section || undefined,
        source: 'dpgf_import',
      }));

      await apiPost(`/v1/boq/boqs/${importTargetBoqId}/import/`, { positions: payload });

      const imported = payload.length;
      setImportResult({ imported, errors: [] });
      queryClient.invalidateQueries({ queryKey: ['boq-positions'] });
      addToast({
        type: 'success',
        title: t('dpgf.import_complete', { defaultValue: 'DPGF import complete' }),
        message: `${imported} positions imported`,
      });
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setImportResult({ imported: 0, errors: [errorMsg] });
      addToast({
        type: 'error',
        title: t('dpgf.import_failed', { defaultValue: 'DPGF import failed' }),
        message: errorMsg,
      });
    } finally {
      setIsImporting(false);
    }
  }, [parseResult, importTargetBoqId, queryClient, addToast, t]);

  const handleClearImport = useCallback(() => {
    setImportFile(null);
    setParseResult(null);
    setParseError(null);
    setImportResult(null);
  }, []);

  // ---------------------------------------------------------------------------
  // Export handlers
  // ---------------------------------------------------------------------------

  const exportablePositions: ExchangePosition[] = useMemo(
    () =>
      exportPositions.map((p) => ({
        ordinal: p.ordinal,
        description: p.description,
        unit: p.unit,
        quantity: p.quantity,
        unitRate: p.unit_rate,
        total: p.total ?? p.quantity * p.unit_rate,
        section: p.section,
        parentId: p.parent_id,
        isSection: p.is_section,
      })),
    [exportPositions],
  );

  const selectedExportBoq = exportBoqs.find((b) => b.id === exportBoqId);
  const selectedExportProject = projects.find((p) => p.id === exportProjectId);

  const includePrices = exportFormat === 'DQE';

  const handleExport = useCallback(() => {
    if (exportablePositions.length === 0) {
      addToast({
        type: 'warning',
        title: t('dpgf.no_positions', { defaultValue: 'No positions to export' }),
      });
      return;
    }
    setIsExporting(true);
    try {
      const boqName = selectedExportBoq?.name ?? 'BOQ';
      const safeName = boqName.replace(/[^a-zA-Z0-9_-]/g, '_');
      const suffix = exportFormat === 'DPGF' ? 'DPGF' : 'DQE';
      const filename = `${safeName}_${suffix}.csv`;

      const result = exportToCSV(exportablePositions, DPGF_TEMPLATE, filename, {
        includePrices: exportFormat === 'DQE',
        separator: ';', // French convention: semicolon separator
      });

      downloadBlob(result.blob, result.filename);
      addToast({
        type: 'success',
        title: t('dpgf.export_complete', { defaultValue: 'DPGF export complete' }),
        message: `${result.positionCount} positions exported to ${result.filename}`,
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('dpgf.export_failed', { defaultValue: 'DPGF export failed' }),
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setIsExporting(false);
    }
  }, [exportablePositions, exportFormat, selectedExportBoq, addToast, t]);

  const handlePrint = useCallback(() => {
    if (exportablePositions.length === 0) return;
    printBOQReport(exportablePositions, DPGF_TEMPLATE, {
      projectName: selectedExportProject?.name,
      boqName: selectedExportBoq?.name,
      includePrices: exportFormat === 'DQE',
    });
  }, [exportablePositions, exportFormat, selectedExportProject, selectedExportBoq]);

  // ---------------------------------------------------------------------------
  // Derived data
  // ---------------------------------------------------------------------------

  const parsedPositions = parseResult?.positions ?? null;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-100 dark:bg-emerald-900/30">
          <Euro className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            {t('dpgf.title', { defaultValue: 'France DPGF / DQE Import / Export' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('dpgf.subtitle', {
              defaultValue: 'Exchange BOQ data in French DPGF/DQE format with Lots techniques',
            })}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <button
          onClick={() => setActiveTab('import')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'import'
              ? 'border-emerald-600 text-emerald-600'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Upload size={15} />
          {t('dpgf.tab_import', { defaultValue: 'Import' })}
        </button>
        <button
          onClick={() => setActiveTab('export')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'export'
              ? 'border-emerald-600 text-emerald-600'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Download size={15} />
          {t('dpgf.tab_export', { defaultValue: 'Export' })}
        </button>
      </div>

      {/* ── Import Tab ───────────────────────────────────────────────── */}
      {activeTab === 'import' && (
        <div className="space-y-5">
          {/* File upload area */}
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
              importFile
                ? 'border-emerald-500/50 bg-emerald-50/30 dark:bg-emerald-950/10'
                : 'border-border hover:border-emerald-400/30 hover:bg-surface-secondary/30'
            }`}
          >
            {importFile ? (
              <div className="space-y-3">
                <div className="flex items-center justify-center gap-2 text-sm text-content-primary">
                  <FileUp size={18} className="text-emerald-600" />
                  <span className="font-medium">{importFile.name}</span>
                  <span className="text-content-tertiary">
                    ({(importFile.size / 1024).toFixed(1)} KB)
                  </span>
                  <button
                    onClick={handleClearImport}
                    className="ml-2 p-1 rounded hover:bg-surface-secondary"
                  >
                    <X size={14} className="text-content-tertiary" />
                  </button>
                </div>
                {parsedPositions && (
                  <div className="flex items-center justify-center gap-1.5 text-xs text-emerald-600">
                    <CheckCircle2 size={14} />
                    {parsedPositions.length}{' '}
                    {t('dpgf.positions_found', { defaultValue: 'positions found' })}
                    {parsedPositions.some((p) => p.unitRate > 0) && (
                      <Badge variant="blue" className="ml-2">
                        DQE
                      </Badge>
                    )}
                    {parsedPositions.every((p) => p.unitRate === 0) && (
                      <Badge variant="neutral" className="ml-2">
                        DPGF
                      </Badge>
                    )}
                  </div>
                )}
                {parseError && (
                  <div className="flex items-center justify-center gap-1.5 text-xs text-rose-600">
                    <AlertTriangle size={14} />
                    {parseError}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-2">
                <FileUp size={32} className="mx-auto text-content-quaternary" />
                <p className="text-sm text-content-secondary">
                  {t('dpgf.drop_file', {
                    defaultValue: 'Drop a DPGF/DQE file here (Excel or CSV), or',
                  })}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {t('dpgf.browse', { defaultValue: 'Browse files' })}
                </Button>
                <p className="text-2xs text-content-quaternary">
                  {t('dpgf.formats_hint', {
                    defaultValue: 'Supported: .csv, .tsv, .xlsx (DPGF/DQE formatted BOQ)',
                  })}
                </p>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={DPGF_TEMPLATE.acceptedExtensions.join(',')}
              className="hidden"
              onChange={handleFileInputChange}
            />
          </div>

          {/* Lots reference */}
          <LotsReference t={t} locale={i18n.language} />

          {/* Preview */}
          {parsedPositions && parsedPositions.length > 0 && (
            <ImportPreview positions={parsedPositions} t={t} />
          )}

          {/* Target BOQ selection + Import button */}
          {parsedPositions && parsedPositions.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-5">
              <h3 className="text-sm font-semibold text-content-primary mb-3">
                {t('dpgf.target_boq', { defaultValue: 'Import Target' })}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1">
                    {t('common.project', { defaultValue: 'Project' })}
                  </label>
                  <select
                    value={importProjectId}
                    onChange={(e) => {
                      setImportProjectId(e.target.value);
                      setImportTargetBoqId('');
                    }}
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                  >
                    <option value="">
                      — {t('risk.select_project', { defaultValue: 'Select project' })} —
                    </option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1">
                    {t('boq.title', { defaultValue: 'BOQ' })}
                  </label>
                  <select
                    value={importTargetBoqId}
                    onChange={(e) => setImportTargetBoqId(e.target.value)}
                    disabled={!importProjectId}
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm disabled:opacity-50"
                  >
                    <option value="">
                      — {t('dpgf.select_boq', { defaultValue: 'Select BOQ' })} —
                    </option>
                    {importBoqs.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end">
                  <Button
                    variant="primary"
                    className="w-full"
                    icon={
                      isImporting ? (
                        <Loader2 size={15} className="animate-spin" />
                      ) : (
                        <Upload size={15} />
                      )
                    }
                    onClick={handleImport}
                    disabled={!importTargetBoqId || isImporting}
                  >
                    {isImporting
                      ? t('dpgf.importing', { defaultValue: 'Importing...' })
                      : t('dpgf.import_btn', {
                          defaultValue: `Import ${parsedPositions.length} positions`,
                        })}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Import result */}
          {importResult && (
            <div
              className={`rounded-xl border p-4 ${
                importResult.errors.length > 0
                  ? 'border-amber-300 bg-amber-50/50 dark:bg-amber-950/20'
                  : 'border-emerald-300 bg-emerald-50/50 dark:bg-emerald-950/20'
              }`}
            >
              <div className="flex items-center gap-2 text-sm font-medium">
                {importResult.errors.length > 0 ? (
                  <AlertTriangle size={16} className="text-amber-600" />
                ) : (
                  <CheckCircle2 size={16} className="text-emerald-600" />
                )}
                <span className="text-content-primary">
                  {importResult.imported}{' '}
                  {t('dpgf.positions_imported', { defaultValue: 'positions imported' })}
                </span>
              </div>
              {importResult.errors.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-content-secondary">
                  {importResult.errors.map((err, idx) => (
                    <li key={idx}>&#8226; {err}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Export Tab ───────────────────────────────────────────────── */}
      {activeTab === 'export' && (
        <div className="space-y-5">
          {/* BOQ selection */}
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('dpgf.source_boq', { defaultValue: '1. Select BOQ to Export' })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('common.project', { defaultValue: 'Project' })}
                </label>
                <select
                  value={exportProjectId}
                  onChange={(e) => {
                    setExportProjectId(e.target.value);
                    setExportBoqId('');
                  }}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value="">
                    — {t('risk.select_project', { defaultValue: 'Select project' })} —
                  </option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('boq.title', { defaultValue: 'BOQ' })}
                </label>
                <select
                  value={exportBoqId}
                  onChange={(e) => setExportBoqId(e.target.value)}
                  disabled={!exportProjectId}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm disabled:opacity-50"
                >
                  <option value="">
                    — {t('dpgf.select_boq', { defaultValue: 'Select BOQ' })} —
                  </option>
                  {exportBoqs.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('dpgf.export_format', { defaultValue: 'Format' })}
                </label>
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value as DPGFExportFormat)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value="DPGF">
                    {t('dpgf.dpgf_format', { defaultValue: 'DPGF (Lump Sum)' })}
                  </option>
                  <option value="DQE">
                    {t('dpgf.dqe_format', { defaultValue: 'DQE (Measured)' })}
                  </option>
                </select>
              </div>
            </div>
          </div>

          {/* Export summary */}
          {exportBoqId && exportablePositions.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('dpgf.export_summary', { defaultValue: '2. Export Summary' })}
                </h3>
                <button
                  onClick={() => setShowExportPreview((v) => !v)}
                  className="flex items-center gap-1 text-xs text-emerald-600 hover:underline"
                >
                  <Eye size={13} />
                  {showExportPreview
                    ? t('dpgf.hide_preview', { defaultValue: 'Hide preview' })
                    : t('dpgf.show_preview', { defaultValue: 'Show preview' })}
                </button>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('dpgf.positions', { defaultValue: 'Positions' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportablePositions.filter((p) => !p.isSection).length}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('dpgf.sections', { defaultValue: 'Sections' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportablePositions.filter((p) => p.isSection).length}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('dpgf.format_label', { defaultValue: 'Format' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">{exportFormat}</div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('dpgf.prices', { defaultValue: 'Prices' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {includePrices ? 'Oui' : 'Non'}
                  </div>
                </div>
              </div>

              {showExportPreview && (
                <div className="border border-border-light rounded-lg overflow-x-auto max-h-60">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-surface-tertiary/50 sticky top-0">
                        <th className="px-3 py-1.5 text-left font-medium text-content-secondary">
                          {t('boq.ordinal', { defaultValue: 'Ordinal' })}
                        </th>
                        <th className="px-3 py-1.5 text-left font-medium text-content-secondary">
                          {t('boq.description', { defaultValue: 'Description' })}
                        </th>
                        <th className="px-3 py-1.5 text-center font-medium text-content-secondary">
                          {t('boq.unit', { defaultValue: 'Unit' })}
                        </th>
                        <th className="px-3 py-1.5 text-right font-medium text-content-secondary">
                          {t('boq.quantity', { defaultValue: 'Qty' })}
                        </th>
                        {includePrices && (
                          <th className="px-3 py-1.5 text-right font-medium text-content-secondary">
                            {t('boq.unit_rate', { defaultValue: 'Rate' })}
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {exportablePositions
                        .filter((p) => !p.isSection)
                        .slice(0, 30)
                        .map((pos, idx) => (
                          <tr key={idx} className="hover:bg-surface-secondary/30">
                            <td className="px-3 py-1.5 font-mono text-content-tertiary">
                              {pos.ordinal}
                            </td>
                            <td className="px-3 py-1.5 text-content-primary max-w-[280px] truncate">
                              {pos.description}
                            </td>
                            <td className="px-3 py-1.5 text-center text-content-secondary">
                              {pos.unit}
                            </td>
                            <td className="px-3 py-1.5 text-right tabular-nums">
                              {pos.quantity.toFixed(3)}
                            </td>
                            {includePrices && (
                              <td className="px-3 py-1.5 text-right tabular-nums">
                                {pos.unitRate.toFixed(2)}
                              </td>
                            )}
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="flex gap-3">
                <Button
                  variant="primary"
                  icon={
                    isExporting ? (
                      <Loader2 size={15} className="animate-spin" />
                    ) : (
                      <FileDown size={15} />
                    )
                  }
                  onClick={handleExport}
                  disabled={isExporting}
                >
                  {t('dpgf.export_btn', { defaultValue: 'Export as DPGF CSV' })}
                </Button>
                <Button
                  variant="secondary"
                  icon={<Printer size={15} />}
                  onClick={handlePrint}
                >
                  {t('dpgf.print_btn', { defaultValue: 'Print PDF' })}
                </Button>
              </div>
            </div>
          )}

          {exportBoqId && exportablePositions.length === 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-8 text-center">
              <Euro size={32} className="mx-auto text-content-quaternary mb-2" />
              <p className="text-sm text-content-tertiary">
                {t('dpgf.no_positions', {
                  defaultValue: 'This BOQ has no positions to export.',
                })}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Info box */}
      <div className="flex items-start gap-2 text-xs text-content-quaternary">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>
          {t('dpgf.info', {
            defaultValue:
              'DPGF (Decomposition du Prix Global et Forfaitaire) and DQE (Detail Quantitatif Estimatif) are standard French BOQ formats. Work is organized by Lots techniques (technical trade packages) following NF DTU standards. Compatible with Batiprix, Artisans du Batiment, and French public procurement.',
          })}
        </p>
      </div>
    </div>
  );
}
