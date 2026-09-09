// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RegionalExchangePage - polymorphic BOQ exchange page (Wave 5 Epic I).
 *
 * Replaces 20 near-identical country modules with one component driven
 * by a `RegionalTemplate` from `regionalRegistry.ts`. The country pack
 * provides the flag, label, format hint, column mapping, trade-section
 * reference, and import endpoint; everything else (file drop, parse,
 * preview, target-BOQ selector, export, print) is shared logic.
 *
 * All UI strings flow through i18next so locales drop into ONE keyspace
 * (`regional.*`) rather than 20 (`au.*`, `br.*`, `ca.*`, ...).
 */

import { useState, useCallback, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
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
import { Button, Badge, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { apiGet } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { parseExcelFile } from '../_shared/excelImport';
import { exportToCSV, downloadBlob } from '../_shared/excelExport';
import { printBOQReport } from '../_shared/pdfBOQExport';
import { SampleTemplateButton } from '../_shared/SampleTemplateButton';
import type { ExchangePosition, ImportParseResult } from '../_shared/templateTypes';
import type { RegionalTemplate } from './regionalRegistry';
import { importDispatcher } from './regionalRegistry';
import { fmtList, fmtFixed } from '@/shared/lib/formatters';

/* ── Types from the BOQ module ──────────────────────────────────────── */

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

type ExportFormatChoice = 'detailed' | 'summary';

/**
 * What `POST /v1/boq/boqs/{id}/import/auto/` answers.
 *
 * `imported` is optional on purpose: the count belongs to the server, and a
 * response that does not carry one must be reported as unknown rather than
 * filled in from the client-side preview.
 */
interface AutoImportResponse {
  imported?: number;
  skipped?: number;
  errors?: unknown[];
  warnings?: unknown[];
  source_format?: string;
  format_id?: string;
  currency?: string;
  method?: string;
}

/**
 * Render one entry of the response's `errors` list.
 *
 * Every producer on the backend appends a dict, not a string: the native
 * importers use `{ordinal, error}`, the persistence step `{row, position_id,
 * error}`, the smart-import fallback `{row, error, data}`. Joining those into
 * a template literal yields "[object Object]", so pull the message out and
 * prefix it with whichever row identifier the entry happens to carry.
 */
function describeImportError(entry: unknown): string {
  if (typeof entry === 'string') return entry;
  if (entry === null || typeof entry !== 'object') return String(entry);

  const row = entry as Record<string, unknown>;
  const message = row.error ?? row.message ?? row.detail;
  const label = row.ordinal ?? row.row ?? row.index ?? row.position_id;
  const text = typeof message === 'string' ? message : JSON.stringify(entry);
  return label === undefined || label === null ? text : `${label}: ${text}`;
}

/**
 * Extensions the browser-side preview can actually read.
 *
 * `parseExcelFile` is a delimited-text reader: it splits on commas, semicolons
 * and tabs and maps columns. Handed a native container it does not refuse, it
 * splits it anyway and produces rows that mean nothing. A BC3 came back as two
 * rows cut out of its long-text records while the server's own reader made nine
 * positions out of the same file, so the preview said one number and the result
 * said another. Worse, the accepted extensions are what a screen offers, not
 * what arrives: an HTML error page saved under a .bc3 name parsed into three
 * confident-looking positions.
 *
 * So the preview is offered only for what it can read. Everything else still
 * imports, by the same route it always did, because the file goes to the server
 * whole and the server picks the reader.
 */
const PREVIEWABLE_EXTENSIONS = ['.csv', '.tsv', '.xls', '.xlsx'] as const;

function previewCanRead(filename: string): boolean {
  const lower = filename.toLowerCase();
  return PREVIEWABLE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/* ── Import preview table ───────────────────────────────────────────── */

function ImportPreview({
  positions,
  template,
  t,
}: {
  positions: ExchangePosition[];
  template: RegionalTemplate;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const [showAll, setShowAll] = useState(false);
  const displayed = showAll ? positions : positions.slice(0, 20);

  return (
    <div className="border border-border-light rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-surface-tertiary/50 flex items-center justify-between">
        <span className="text-xs font-medium text-content-secondary">
          {t('regional.preview', { defaultValue: 'Preview' })}: {positions.length}{' '}
          {t('regional.positions', { defaultValue: 'positions' })}
        </span>
        {positions.length > 20 && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="text-2xs text-oe-blue hover:underline"
          >
            {showAll
              ? t('regional.show_less', { defaultValue: 'Show less' })
              : t('regional.show_all', { defaultValue: 'Show all', count: positions.length })}
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
                {template.excelTemplate.classification ||
                  t('regional.classification', { defaultValue: 'Classification' })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {displayed.map((pos, idx) => {
              const code = pos.classification ? Object.values(pos.classification)[0] : '';
              const info = code
                ? template.tradeSections.find((s) => code.startsWith(s.code))
                : undefined;
              return (
                <tr
                  key={pos.ordinal || `pos-${idx}`}
                  className={`hover:bg-surface-secondary/30 ${
                    idx % 2 === 0 ? 'bg-surface-primary/50' : ''
                  }`}
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
                    {pos.quantity > 0 ? fmtFixed(pos.quantity, 3) : '-'}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {pos.unitRate > 0 ? fmtFixed(pos.unitRate, 2) : '-'}
                  </td>
                  <td
                    className="px-3 py-1.5 text-content-tertiary text-2xs truncate"
                    title={info ? `${info.code} - ${info.label}` : code}
                  >
                    {code || '-'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Main polymorphic component ─────────────────────────────────────── */

export interface RegionalExchangePageProps {
  /** The country pack driving this page. */
  template: RegionalTemplate;
}

export default function RegionalExchangePage({ template }: RegionalExchangePageProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  /* Import state */
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [parsedResult, setParsedResult] = useState<ImportParseResult | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  /** The dropped file is a native container, so there is no browser preview of it. */
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const [importTargetBoqId, setImportTargetBoqId] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<{
    // `null` means the request came back without a count. The server owns
    // this number; when it does not send one we say so instead of guessing.
    imported: number | null;
    errors: string[];
    // Which reader claimed the file, e.g. "gaeb" / "bc3" / "xlsx".
    sourceFormat?: string;
  } | null>(null);

  /* Export state */
  const [exportProjectId, setExportProjectId] = useState('');
  const [exportBoqId, setExportBoqId] = useState('');
  const [exportFormat, setExportFormat] = useState<ExportFormatChoice>('detailed');
  const [isExporting, setIsExporting] = useState(false);
  const [showExportPreview, setShowExportPreview] = useState(false);

  /* Tab state */
  const [activeTab, setActiveTab] = useState<'import' | 'export'>('import');

  /* Project + BOQ queries */
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects-list'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const [importProjectId, setImportProjectId] = useState('');
  const { data: importBoqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-import', importProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${importProjectId}`),
    enabled: !!importProjectId,
  });

  const { data: exportBoqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-export', exportProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${exportProjectId}`),
    enabled: !!exportProjectId,
  });

  const { data: exportPositions = [] } = useQuery<BOQPosition[]>({
    queryKey: ['boq-positions-export', exportBoqId],
    queryFn: async () => {
      const boq = await apiGet<{ positions?: BOQPosition[] }>(
        `/v1/boq/boqs/${exportBoqId}`,
      );
      return boq.positions ?? [];
    },
    enabled: !!exportBoqId,
  });

  /* ── Import handlers ────────────────────────────────────────────── */

  const handleFileSelect = useCallback(
    async (file: File) => {
      setImportFile(file);
      setParsedResult(null);
      setParseError(null);
      setImportResult(null);
      setPreviewUnavailable(!previewCanRead(file.name));

      if (!previewCanRead(file.name)) {
        // Nothing to preview and nothing wrong: the server reads this one.
        return;
      }

      try {
        const result = await parseExcelFile(file, template.excelTemplate.defaultColumns);

        if (result.errors.length > 0) {
          setParseError(result.errors.join('; '));
        } else if (result.positions.length === 0) {
          setParseError(
            t('regional.parse_error', {
              defaultValue:
                'No positions found in the file. Ensure the file matches the expected layout.',
            }),
          );
        } else {
          setParsedResult(result);
          addToast({
            type: 'success',
            title: t('regional.parsed_ok', { defaultValue: 'File parsed successfully' }),
            message: `${result.positions.length} positions found`,
          });
        }
      } catch {
        setParseError(
          t('regional.parse_error_generic', {
            defaultValue: 'Failed to parse the file.',
          }),
        );
      }
    },
    [template, addToast, t],
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
    // A parsed preview is not a precondition. It never was one for the request,
    // which posts the file, and a native container has no preview to wait for.
    if (!importFile || !importTargetBoqId) return;
    setIsImporting(true);

    // The dispatcher takes the FILE, not the preview. It sniffs magic bytes
    // and extension to pick the native reader (GAEB, BC3, Excel/CSV) and
    // applies that reader's validator packs; a JSON body of already-parsed
    // rows never satisfied its `file` field and could only ever come back
    // 422. The client-side parse above stays exactly as it is - it is what
    // shows the column mapping before anything is committed.
    const form = new FormData();
    form.append('file', importFile);
    const token = useAuthStore.getState().accessToken;

    // `importDispatcher` returns the path without the "/api" prefix because
    // its usual caller goes through the api helper, which prepends it. Raw
    // fetch has to add it or the request 404s.
    const url = `/api${importDispatcher(importTargetBoqId)}`;

    // Imports of large sheets and AI fallbacks run for tens of seconds, so
    // give this the same 90s ceiling the BOQ import screens use rather than
    // leaving the request without one.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90_000);

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
        throw new Error(
          typeof body.detail === 'string'
            ? body.detail
            : t('regional.import_failed', { defaultValue: 'Import failed' }),
        );
      }

      const response = (await res.json()) as AutoImportResponse;
      const imported = typeof response.imported === 'number' ? response.imported : null;
      const errors = (response.errors ?? []).map(describeImportError);
      const sourceFormat = response.source_format || response.format_id || undefined;

      setImportResult({ imported, errors, sourceFormat });
      queryClient.invalidateQueries({ queryKey: ['boq-positions'] });

      const summary =
        imported === null
          ? t('regional.import_count_unknown', {
              defaultValue: 'The server did not report how many positions were imported',
            })
          : t('regional.import_summary', {
              defaultValue: '{{n}} positions imported',
              n: imported,
            });
      const parts = [summary];
      if (sourceFormat) {
        parts.push(t('regional.read_by', { defaultValue: 'read by {{format}}', format: sourceFormat }));
      }
      if (errors.length > 0) {
        parts.push(
          t('regional.import_errors', {
            defaultValue: '{{n}} rows could not be imported',
            n: errors.length,
          }),
        );
      }
      addToast({
        type: imported !== null && imported > 0 ? 'success' : 'warning',
        title: t('regional.import_complete', { defaultValue: 'Import complete' }),
        message: fmtList(parts),
      });
    } catch (err) {
      clearTimeout(timeoutId);
      const isTimeout = err instanceof DOMException && err.name === 'AbortError';
      const msg = isTimeout
        ? t('regional.import_timeout', {
            defaultValue: 'The server did not respond within 90 seconds. Try a smaller file.',
          })
        : err instanceof Error
          ? err.message
          : String(err);
      setImportResult({ imported: 0, errors: [msg] });
      addToast({
        type: 'error',
        title: t('regional.import_failed', { defaultValue: 'Import failed' }),
        message: msg,
      });
    } finally {
      setIsImporting(false);
    }
  }, [importFile, importTargetBoqId, queryClient, addToast, t]);

  const handleClearImport = useCallback(() => {
    setImportFile(null);
    setParsedResult(null);
    setParseError(null);
    setPreviewUnavailable(false);
    setImportResult(null);
  }, []);

  /* ── Export handlers ────────────────────────────────────────────── */

  // NOTE: quantities/units here stay metric-canonical on purpose. The CSV
  // export (exportToCSV) and the import parser share one column layout, so
  // this is a round-trippable interchange format - converting to imperial
  // would corrupt the data on re-import. Left canonical like GAEB. (#270)
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
  const includePrices = exportFormat === 'detailed';

  const handleExport = useCallback(() => {
    if (exportablePositions.length === 0) {
      addToast({
        type: 'warning',
        title: t('regional.no_positions', { defaultValue: 'No positions to export' }),
      });
      return;
    }
    setIsExporting(true);
    try {
      const projectName = selectedExportProject?.name ?? 'Project';
      const boqName = selectedExportBoq?.name ?? 'BOQ';
      const suffix = exportFormat === 'detailed' ? 'Detailed' : 'Summary';
      const filename = `${projectName}_${boqName}_${template.countryCode}_${suffix}.csv`;

      const result = exportToCSV(exportablePositions, template.excelTemplate, filename, {
        includePrices,
      });
      downloadBlob(result.blob, result.filename);

      addToast({
        type: 'success',
        title: t('regional.export_complete', { defaultValue: 'Export complete' }),
        message: `${result.positionCount} positions exported to ${result.filename}`,
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('regional.export_failed', { defaultValue: 'Export failed' }),
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
    template,
    addToast,
    t,
  ]);

  const handlePrint = useCallback(() => {
    if (exportablePositions.length === 0) return;
    printBOQReport(exportablePositions, template.excelTemplate, {
      projectName: selectedExportProject?.name,
      boqName: selectedExportBoq?.name,
      includePrices,
    });
  }, [exportablePositions, selectedExportProject, selectedExportBoq, includePrices, template]);

  /* ── Render ────────────────────────────────────────────────────── */

  const parsedPositions = parsedResult?.positions ?? null;
  /**
   * A file is ready to send once it is chosen and either previewed or known to
   * be a format only the server reads. Before this the whole target block hung
   * off the preview, so a BC3 could only be imported because the preview had
   * invented rows out of it.
   */
  const readyToImport = Boolean(importFile) && (previewUnavailable || (parsedPositions?.length ?? 0) > 0);

  return (
    <div
      className="space-y-5 animate-fade-in"
      data-testid="regional-exchange-page"
      data-template-id={template.id}
    >
      <PageHeader
        srTitle={template.label}
        subtitle={
          <span data-testid="regional-format-hint">
            <span aria-hidden="true" className="mr-1.5" data-testid="regional-flag">
              {template.flag}
            </span>
            <span data-testid="regional-label">{template.label}</span>
            {template.formatHint ? <> · {template.formatHint}</> : null}
          </span>
        }
      />

      <DismissibleInfo
        storageKey={`regional-exchange-${template.id}`}
        title={t('regional.intro_title', {
          defaultValue: "Speak your country's tender format",
        })}
        more={
          t('regional.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('regional.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.boq', { defaultValue: 'Bill of Quantities' }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('nav.validation', { defaultValue: 'Validation' }),
            onClick: () => navigate('/validation'),
          },
        ]}
      >
        {t('regional.intro_body', {
          defaultValue:
            "Import and export BOQ data in your region's native structure (NRM in the UK, MasterFormat in the US, DPGF in France and others), with the right trade-section breakdown applied. The data lands in or comes from a normal BOQ, so the same estimate moves across markets without re-keying.",
        })}
      </DismissibleInfo>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab('import')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'import'
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Upload size={15} />
          {t('regional.tab_import', { defaultValue: 'Import' })}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('export')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'export'
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Download size={15} />
          {t('regional.tab_export', { defaultValue: 'Export' })}
        </button>
      </div>

      {/* Import tab */}
      {activeTab === 'import' && (
        <div className="space-y-5">
          {/* File upload */}
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
                    ({fmtFixed(importFile.size / 1024, 1)} KB)
                  </span>
                  <button
                    type="button"
                    onClick={handleClearImport}
                    className="ml-2 p-1 rounded hover:bg-surface-secondary"
                    aria-label={t('regional.clear_file', { defaultValue: 'Clear file' })}
                  >
                    <X size={14} className="text-content-tertiary" />
                  </button>
                </div>
                {parsedPositions && (
                  <div className="flex items-center justify-center gap-1.5 text-xs text-emerald-600">
                    <CheckCircle2 size={14} />
                    {parsedPositions.length}{' '}
                    {t('regional.positions_found', { defaultValue: 'positions found' })}
                    <Badge variant="blue" className="ml-2">
                      {template.excelTemplate.classification}
                    </Badge>
                  </div>
                )}
                {previewUnavailable && (
                  <div
                    data-testid="regional-no-browser-preview"
                    className="flex items-center justify-center gap-1.5 text-xs text-content-tertiary"
                  >
                    <Info size={14} />
                    {t('regional.no_browser_preview', {
                      defaultValue:
                        'No preview for this format in the browser. The file is read by the {{standard}} reader on import.',
                      standard: template.excelTemplate.classification,
                    })}
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
                  {t('regional.drop_file', { defaultValue: 'Drop a file here, or' })}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {t('regional.browse', { defaultValue: 'Browse files' })}
                </Button>
                <p className="text-2xs text-content-quaternary">
                  {t('regional.formats_hint', {
                    defaultValue: 'Supported: {{exts}}',
                    exts: fmtList(template.excelTemplate.acceptedExtensions),
                  })}
                </p>
                {template.sampleFile && (
                  <a
                    href={template.sampleFile}
                    download
                    data-testid="regional-sample-link"
                    className="mt-1 inline-flex items-center gap-1.5 text-2xs font-medium text-oe-blue hover:underline"
                  >
                    <Download size={12} />
                    {t('regional.download_sample', {
                      defaultValue: 'Download a sample file to try it',
                    })}
                  </a>
                )}
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={template.excelTemplate.acceptedExtensions.join(',')}
              className="hidden"
              onChange={handleFileInputChange}
            />
          </div>

          {/* Expected layout + ready-to-fill sample CSV */}
          {!importFile && <SampleTemplateButton template={template.excelTemplate} />}

          {/* Trade sections reference */}
          {parsedPositions && parsedPositions.length > 0 && template.tradeSections.length > 0 && (
            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-3">
              <div className="flex items-center gap-1.5 text-xs font-medium text-content-secondary mb-2">
                <Info size={13} />
                {t('regional.trades_ref', {
                  defaultValue: '{{standard}} Reference',
                  standard: template.excelTemplate.classification,
                })}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {template.tradeSections.map((sec) => (
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
            <ImportPreview positions={parsedPositions} template={template} t={t} />
          )}

          {/* Target BOQ selection + Import button */}
          {readyToImport && (
            <div className="rounded-xl border border-border bg-surface-primary p-5">
              <h3 className="text-sm font-semibold text-content-primary mb-3">
                {t('regional.target_boq', { defaultValue: 'Import Target' })}
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
                      — {t('regional.select_project', { defaultValue: 'Select project' })} —
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
                      — {t('regional.select_boq', { defaultValue: 'Select BOQ' })} —
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
                    {/*
                      Label by the file when there is no preview. Naming a count
                      the browser never counted is how the old screen came to
                      offer "Import 2 positions" for a file the server read as
                      nine.
                    */}
                    {isImporting
                      ? t('regional.importing', { defaultValue: 'Importing…' })
                      : parsedPositions && parsedPositions.length > 0
                        ? t('regional.import_btn', {
                            defaultValue: 'Import {{count}} positions',
                            count: parsedPositions.length,
                          })
                        : t('regional.import_file_btn', {
                            defaultValue: 'Import {{name}}',
                            name: importFile?.name ?? '',
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
                  {importResult.imported === null ? (
                    t('regional.import_count_unknown', {
                      defaultValue: 'The server did not report how many positions were imported',
                    })
                  ) : (
                    <>
                      {importResult.imported}{' '}
                      {t('regional.positions_imported', { defaultValue: 'positions imported' })}
                    </>
                  )}
                </span>
                {importResult.sourceFormat && (
                  <Badge variant="neutral" size="sm">
                    {t('regional.read_by', {
                      defaultValue: 'read by {{format}}',
                      format: importResult.sourceFormat,
                    })}
                  </Badge>
                )}
              </div>
              {importResult.errors.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-content-secondary">
                  {importResult.errors.map((err, idx) => (
                    <li key={`err-${err.slice(0, 40)}-${idx}`}>• {err}</li>
                  ))}
                </ul>
              )}
              {/* Offered whenever the request succeeded. A missing count is
                  not evidence that nothing landed, so an unknown count still
                  gets the link into the BOQ where the truth can be read. */}
              {(importResult.imported === null || importResult.imported > 0) && (
                <Link
                  data-testid="regional-open-boq"
                  // The editor is a path param (/boq/:boqId). `?boq=` was read by
                  // nothing, so this link promised the editor and delivered the list.
                  to={importTargetBoqId ? `/boq/${importTargetBoqId}` : '/boq'}
                  className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-oe-blue hover:underline"
                >
                  {t('regional.open_boq', {
                    defaultValue: 'Open in BOQ editor to review & validate →',
                  })}
                </Link>
              )}
            </div>
          )}
        </div>
      )}

      {/* Export tab */}
      {activeTab === 'export' && (
        <div className="space-y-5">
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('regional.source_boq', { defaultValue: '1. Select BOQ to Export' })}
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
                    — {t('regional.select_project', { defaultValue: 'Select project' })} —
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
                    — {t('regional.select_boq', { defaultValue: 'Select BOQ' })} —
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
                  {t('regional.export_format', { defaultValue: 'Format' })}
                </label>
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value as ExportFormatChoice)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value="detailed">
                    {t('regional.format_detailed', { defaultValue: 'Detailed (with prices)' })}
                  </option>
                  <option value="summary">
                    {t('regional.format_summary', { defaultValue: 'Summary (quantities only)' })}
                  </option>
                </select>
              </div>
            </div>
          </div>

          {exportBoqId && exportablePositions.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('regional.export_summary', { defaultValue: '2. Export Summary' })}
                </h3>
                <button
                  type="button"
                  onClick={() => setShowExportPreview((v) => !v)}
                  className="flex items-center gap-1 text-xs text-oe-blue hover:underline"
                >
                  <Eye size={13} />
                  {showExportPreview
                    ? t('regional.hide_preview', { defaultValue: 'Hide preview' })
                    : t('regional.show_preview', { defaultValue: 'Show preview' })}
                </button>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('regional.positions', { defaultValue: 'Positions' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportablePositions.filter((p) => !p.isSection).length}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('regional.sections', { defaultValue: 'Sections' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportablePositions.filter((p) => p.isSection).length}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('regional.format_label', { defaultValue: 'Format' })}
                  </div>
                  <div className="text-lg font-bold text-content-primary">
                    {exportFormat === 'detailed'
                      ? t('regional.detailed_short', { defaultValue: 'Detailed' })
                      : t('regional.summary_short', { defaultValue: 'Summary' })}
                  </div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">
                    {t('regional.prices_label', { defaultValue: 'Prices' })}
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
                          <tr
                            key={pos.ordinal || `export-${idx}`}
                            className="hover:bg-surface-secondary/30"
                          >
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
                              {fmtFixed(pos.quantity, 3)}
                            </td>
                            {includePrices && (
                              <td className="px-3 py-1.5 text-right tabular-nums">
                                {fmtFixed(pos.unitRate, 2)}
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
                  {t('regional.export_btn', { defaultValue: 'Export as CSV' })}
                </Button>
                <Button variant="secondary" icon={<Printer size={15} />} onClick={handlePrint}>
                  {t('regional.print_btn', { defaultValue: 'Print / PDF' })}
                </Button>
              </div>
            </div>
          )}

          {exportBoqId && exportablePositions.length === 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-8 text-center">
              <FileText32 />
              <p className="text-sm text-content-tertiary">
                {t('regional.no_positions_msg', {
                  defaultValue: 'This BOQ has no positions to export.',
                })}
              </p>
            </div>
          )}
        </div>
      )}

    </div>
  );
}

/* Tiny inline icon - keeps lucide imports tight and saves a re-export. */
function FileText32() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="32"
      height="32"
      className="mx-auto mb-2 text-content-quaternary"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}
