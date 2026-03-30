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
  X,
  Info,
  Printer,
} from 'lucide-react';
import { Button, Badge } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { parseExcelFile } from '../_shared/excelImport';
import { exportToCSV, downloadBlob } from '../_shared/excelExport';
import { printBOQReport } from '../_shared/pdfBOQExport';
import type { ExchangePosition, ImportParseResult } from '../_shared/templateTypes';
import { IT_TEMPLATE, IT_TRADE_SECTIONS } from './itTemplate';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
  classification?: Record<string, string>;
}

type ITExportFormat = 'computo-detailed' | 'computo-summary';

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
          {t('it_cm.preview', { defaultValue: 'Preview' })}: {positions.length}{' '}
          {t('it_cm.positions', { defaultValue: 'positions' })}
        </span>
        {positions.length > 20 && (
          <button
            onClick={() => setShowAll((v) => !v)}
            className="text-2xs text-oe-blue hover:underline"
          >
            {showAll
              ? t('it_cm.show_less', { defaultValue: 'Show less' })
              : t('it_cm.show_all', { defaultValue: `Show all ${positions.length}` })}
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
                {t('it_cm.classification', { defaultValue: 'Capitolo' })}
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
                  title={pos.classification ? Object.values(pos.classification)[0] : ''}
                >
                  {pos.classification ? Object.values(pos.classification)[0] : '-'}
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
// Main Module Component
// ---------------------------------------------------------------------------

export default function ITExchangeModule() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // --- Import state ---
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [parsedResult, setParsedResult] = useState<ImportParseResult | null>(null);
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
  const [exportFormat, setExportFormat] = useState<ITExportFormat>('computo-detailed');
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

  // Export: positions for selected BOQ (via BOQ detail endpoint)
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
      setParsedResult(null);
      setParseError(null);
      setImportResult(null);

      try {
        const result = await parseExcelFile(file, IT_TEMPLATE.defaultColumns);

        if (result.errors.length > 0) {
          setParseError(result.errors.join('; '));
        } else if (result.positions.length === 0) {
          setParseError(
            t('it_cm.parse_error', {
              defaultValue:
                'No positions found in the file. Ensure the file is a valid Computo Metrico / Prezzario DEI-formatted BOQ (CSV, TSV, or XLSX).',
            }),
          );
        } else {
          setParsedResult(result);
          addToast({
            type: 'success',
            title: t('it_cm.parsed_ok', { defaultValue: 'File parsed successfully' }),
            message: `${result.positions.length} positions found`,
          });
        }
      } catch {
        setParseError(
          t('it_cm.parse_error_generic', {
            defaultValue: 'Failed to parse the Italian Computo Metrico BOQ file.',
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
    if (!parsedResult || !importTargetBoqId) return;
    setIsImporting(true);
    try {
      const positions = parsedResult.positions.map((pos) => ({
        ordinal: pos.ordinal,
        description: pos.description,
        unit: pos.unit,
        quantity: pos.quantity,
        unit_rate: pos.unitRate,
        total: pos.total,
        classification: pos.classification,
      }));

      await apiGet<{ imported: number }>(
        `/v1/boq/boqs/${importTargetBoqId}/import`,
        { method: 'POST', body: JSON.stringify({ positions, source: 'it_computo_import' }) } as never,
      );

      const result = { imported: positions.length, errors: [] as string[] };
      setImportResult(result);
      queryClient.invalidateQueries({ queryKey: ['boq-positions'] });
      addToast({
        type: result.imported > 0 ? 'success' : 'warning',
        title: t('it_cm.import_complete', {
          defaultValue: 'Italian Computo Metrico import complete',
        }),
        message: `${result.imported} positions imported`,
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('it_cm.import_failed', {
          defaultValue: 'Italian Computo Metrico import failed',
        }),
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setIsImporting(false);
    }
  }, [parsedResult, importTargetBoqId, queryClient, addToast, t]);

  const handleClearImport = useCallback(() => {
    setImportFile(null);
    setParsedResult(null);
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
        classification: p.classification,
      })),
    [exportPositions],
  );

  const selectedExportBoq = exportBoqs.find((b) => b.id === exportBoqId);
  const selectedExportProject = projects.find((p) => p.id === exportProjectId);
  const includePrices = exportFormat === 'computo-detailed';

  const handleExport = useCallback(() => {
    if (exportablePositions.length === 0) {
      addToast({
        type: 'warning',
        title: t('it_cm.no_positions', { defaultValue: 'No positions to export' }),
      });
      return;
    }
    setIsExporting(true);
    try {
      const projectName = selectedExportProject?.name ?? 'Project';
      const boqName = selectedExportBoq?.name ?? 'BOQ';
      const filename = `${projectName}_${boqName}_IT_${exportFormat === 'computo-detailed' ? 'Computo_Detailed' : 'Computo_Summary'}.csv`;

      const result = exportToCSV(exportablePositions, IT_TEMPLATE, filename, {
        includePrices,
      });

      downloadBlob(result.blob, result.filename);
      addToast({
        type: 'success',
        title: t('it_cm.export_complete', {
          defaultValue: 'Italian Computo Metrico export complete',
        }),
        message: `${result.positionCount} positions exported to ${result.filename}`,
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('it_cm.export_failed', {
          defaultValue: 'Italian Computo Metrico export failed',
        }),
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setIsExporting(false);
    }
  }, [
    exportablePositions,
    exportFormat,
    selectedExportProject,
    selectedExportBoq,
    includePrices,
    addToast,
    t,
  ]);

  const handlePrint = useCallback(() => {
    if (exportablePositions.length === 0) return;
    printBOQReport(exportablePositions, IT_TEMPLATE, {
      projectName: selectedExportProject?.name,
      boqName: selectedExportBoq?.name,
      includePrices,
    });
  }, [exportablePositions, selectedExportProject, selectedExportBoq, includePrices]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const parsedPositions = parsedResult?.positions ?? null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-100 dark:bg-emerald-900/30">
          <Euro className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            {t('it_cm.title', { defaultValue: 'Italy Computo Metrico Import / Export' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('it_cm.subtitle', {
              defaultValue:
                'Exchange Bills of Quantities in Computo Metrico / Prezzario DEI format (Excel / CSV)',
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
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Upload size={15} />
          {t('it_cm.tab_import', { defaultValue: 'Import' })}
        </button>
        <button
          onClick={() => setActiveTab('export')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'export'
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Download size={15} />
          {t('it_cm.tab_export', { defaultValue: 'Export' })}
        </button>
      </div>

      {/* -- Import Tab ---------------------------------------------------- */}
      {activeTab === 'import' && (
        <div className="space-y-5">
          {/* File upload area */}
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
              importFile
                ? 'border-oe-blue/50 bg-oe-blue/5'
                : 'border-border hover:border-oe-blue/30 hover:bg-surface-secondary/30'
            }`}
          >
            {importFile ? (
              <div className="space-y-3">
                <div className="flex items-center justify-center gap-2 text-sm text-content-primary">
                  <FileUp size={18} className="text-oe-blue" />
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
                    {t('it_cm.positions_found', { defaultValue: 'positions found' })}
                    {parsedPositions.some((p) => p.unitRate > 0) && (
                      <Badge variant="blue" className="ml-2">
                        {t('it_cm.detailed', { defaultValue: 'Computo Detailed' })}
                      </Badge>
                    )}
                    {parsedPositions.every((p) => p.unitRate === 0) && (
                      <Badge variant="neutral" className="ml-2">
                        {t('it_cm.summary', { defaultValue: 'Computo Summary' })}
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
                  {t('it_cm.drop_file', {
                    defaultValue: 'Drop an Italian Computo Metrico file here (Excel or CSV), or',
                  })}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {t('it_cm.browse', { defaultValue: 'Browse files' })}
                </Button>
                <p className="text-2xs text-content-quaternary">
                  {t('it_cm.formats_hint', {
                    defaultValue:
                      'Supported: .csv, .tsv, .xlsx (Computo Metrico / Prezzario DEI-formatted BOQ)',
                  })}
                </p>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.xlsx"
              className="hidden"
              onChange={handleFileInputChange}
            />
          </div>

          {/* Computo Metrico Trade Sections reference */}
          {parsedPositions && parsedPositions.length > 0 && (
            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-3">
              <div className="flex items-center gap-1.5 text-xs font-medium text-content-secondary mb-2">
                <Info size={13} />
                {t('it_cm.trades_ref', {
                  defaultValue: 'Computo Metrico Capitoli Reference',
                })}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {IT_TRADE_SECTIONS.map((sec) => (
                  <span
                    key={sec.code}
                    className="inline-flex items-center gap-1 rounded bg-surface-tertiary/50 px-2 py-0.5 text-2xs text-content-tertiary"
                  >
                    <span className="font-mono font-medium">{sec.code}</span>
                    <span>{sec.label}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Preview */}
          {parsedPositions && parsedPositions.length > 0 && (
            <ImportPreview positions={parsedPositions} t={t} />
          )}

          {/* Target BOQ selection + Import button */}
          {parsedPositions && parsedPositions.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-5">
              <h3 className="text-sm font-semibold text-content-primary mb-3">
                {t('it_cm.target_boq', { defaultValue: 'Import Target' })}
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
                      — {t('it_cm.select_boq', { defaultValue: 'Select BOQ' })} —
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
                      ? t('it_cm.importing', { defaultValue: 'Importing...' })
                      : t('it_cm.import_btn', {
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
                  {t('it_cm.positions_imported', { defaultValue: 'positions imported' })}
                </span>
              </div>
              {importResult.errors.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-content-secondary">
                  {importResult.errors.map((err, idx) => (
                    <li key={idx}>&#x2022; {err}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* -- Export Tab ---------------------------------------------------- */}
      {activeTab === 'export' && (
        <div className="space-y-5">
          {/* BOQ selection */}
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('it_cm.source_boq', { defaultValue: '1. Select BOQ to Export' })}
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
                    — {t('it_cm.select_boq', { defaultValue: 'Select BOQ' })} —
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
                  {t('it_cm.export_format', { defaultValue: 'Format' })}
                </label>
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value as ITExportFormat)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value="computo-detailed">
                    {t('it_cm.detailed', { defaultValue: 'Computo Detailed' })} —{' '}
                    {t('it_cm.with_prices', { defaultValue: 'with prices' })}
                  </option>
                  <option value="computo-summary">
                    {t('it_cm.summary', { defaultValue: 'Computo Summary' })} —{' '}
                    {t('it_cm.no_prices', { defaultValue: 'quantities only' })}
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
                  {t('it_cm.export_summary', { defaultValue: '2. Export Summary' })}
                </h3>
                <button
                  onClick={() => setShowExportPreview((v) => !v)}
                  className="flex items-center gap-1 text-xs text-oe-blue hover:underline"
                >
                  <Eye size={13} />
                  {showExportPreview
                    ? t('it_cm.hide_preview', { defaultValue: 'Hide preview' })
                    : t('it_cm.show_preview', { defaultValue: 'Show preview' })}
                </button>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('it_cm.positions', { defaultValue: 'Positions' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportablePositions.filter((p) => !p.isSection).length}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('it_cm.sections', { defaultValue: 'Sections' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportablePositions.filter((p) => p.isSection).length}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('it_cm.format_label', { defaultValue: 'Format' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportFormat === 'computo-detailed' ? 'Detailed' : 'Summary'}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('it_cm.prices_label', { defaultValue: 'Prices' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {includePrices
                      ? t('common.yes', { defaultValue: 'Yes' })
                      : t('common.no', { defaultValue: 'No' })}
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
                  {t('it_cm.export_btn', {
                    defaultValue: `Export as ${exportFormat === 'computo-detailed' ? 'Computo Detailed' : 'Computo Summary'} CSV`,
                  })}
                </Button>
                <Button variant="secondary" icon={<Printer size={15} />} onClick={handlePrint}>
                  {t('it_cm.print_btn', { defaultValue: 'Print / PDF' })}
                </Button>
              </div>
            </div>
          )}

          {exportBoqId && exportablePositions.length === 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-8 text-center">
              <Euro size={32} className="mx-auto text-content-quaternary mb-2" />
              <p className="text-sm text-content-tertiary">
                {t('it_cm.no_positions', {
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
          {t('it_cm.info', {
            defaultValue:
              'Computo Metrico Estimativo is the standard Italian construction cost estimation document. Combined with Prezzario DEI (published by DEI - Tipografia del Genio Civile), it provides official regional unit prices used for public and private construction projects across Italy.',
          })}
        </p>
      </div>
    </div>
  );
}
