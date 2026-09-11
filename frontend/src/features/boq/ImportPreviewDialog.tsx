// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Modal wizard for previewing a BOQ file import before committing it. */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  X,
  Loader2,
  Upload,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
} from 'lucide-react';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { extractErrorMessageFromBody } from '@/shared/lib/api';

/* ── Types ──────────────────────────────────────────────────────────── */

interface PreviewPosition {
  ordinal: string;
  code: string;
  description: string;
  unit: string;
  quantity: number | null;
  unit_rate: number | null;
  total: number | null;
  is_section: boolean;
}

interface PreviewWarning {
  row?: number;
  message: string;
}

interface PreviewError {
  row?: number;
  message: string;
}

interface PreviewResponse {
  positions: PreviewPosition[];
  total_positions: number;
  total_sections: number;
  currency: string;
  source_format: string;
  warnings: PreviewWarning[];
  errors: PreviewError[];
  skipped: number;
  truncated: boolean;
}

interface ImportPreviewDialogProps {
  open: boolean;
  onClose: () => void;
  boqId: string;
  onImported: () => void;
}

type Step = 'upload' | 'preview' | 'confirm';

/* ── Helpers ────────────────────────────────────────────────────────── */

const FORMAT_EXTS: Record<string, string[]> = {
  GAEB: ['x81', 'x83', 'x84'],
  Excel: ['xlsx', 'xls'],
  CSV: ['csv'],
  PDF: ['pdf'],
};

function detectFormat(filename: string): string {
  const ext = (filename.split('.').pop() ?? '').toLowerCase();
  // GAEB files that end in .xml but have .x8* in the name
  if (ext === 'xml' && /\.(x8[134]|gaeb)\.xml$/i.test(filename)) return 'GAEB';
  for (const [fmt, exts] of Object.entries(FORMAT_EXTS)) {
    if (exts.includes(ext)) return fmt;
  }
  if (ext === 'xml') return 'XML';
  return ext.toUpperCase() || 'Unknown';
}

const SUPPORTED_FORMATS = ['GAEB', 'Excel', 'PDF', 'CSV'] as const;

const MAX_PREVIEW_ROWS = 500;

function fmtNumber(v: number | null | undefined): string {
  if (v == null) return '';
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ── Component ──────────────────────────────────────────────────────── */

export function ImportPreviewDialog({ open, onClose, boqId, onImported }: ImportPreviewDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [fileFormat, setFileFormat] = useState<string>('');
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [parsing, setParsing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warningsExpanded, setWarningsExpanded] = useState(false);
  const [errorsExpanded, setErrorsExpanded] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  // Reset state when the dialog closes
  useEffect(() => {
    if (!open) {
      setStep('upload');
      setFile(null);
      setFileFormat('');
      setPreview(null);
      setParsing(false);
      setImporting(false);
      setError(null);
      setWarningsExpanded(false);
      setErrorsExpanded(false);
      setDragOver(false);
    }
  }, [open]);

  // Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  /* ── Step 1: Upload & parse ─────────────────────────────────────── */

  const handleFile = useCallback(
    async (f: File) => {
      setFile(f);
      setFileFormat(detectFormat(f.name));
      setError(null);
      setParsing(true);
      setStep('upload'); // Stay on upload step while parsing

      const token = useAuthStore.getState().accessToken;
      const form = new FormData();
      form.append('file', f);

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 90_000);

      try {
        const res = await fetch('/api/v1/boq/import/preview/', {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(extractErrorMessageFromBody(body) ?? 'Preview failed');
        }

        const data: PreviewResponse = await res.json();
        setPreview(data);
        setStep('preview');
      } catch (err) {
        clearTimeout(timeoutId);
        const isTimeout = err instanceof DOMException && err.name === 'AbortError';
        setError(
          isTimeout
            ? t('boq.import_preview.parse_timeout', {
                defaultValue: 'Server did not respond within 90 seconds. The file may be too large.',
              })
            : err instanceof Error
              ? err.message
              : 'Unknown error',
        );
        setStep('upload');
      } finally {
        setParsing(false);
      }
    },
    [boqId, t],
  );

  /* ── Step 3: Confirm import ─────────────────────────────────────── */

  const handleImport = useCallback(async () => {
    if (!file) return;
    setImporting(true);
    setError(null);

    const token = useAuthStore.getState().accessToken;
    const form = new FormData();
    form.append('file', file);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90_000);

    try {
      const res = await fetch(`/api/v1/boq/boqs/${boqId}/import/auto/`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(extractErrorMessageFromBody(body) ?? 'Import failed');
      }

      const result: {
        imported?: number;
        created?: number;
        updated?: number;
        errors?: { item?: string; error: string }[];
        skipped?: number;
        source_format?: string;
        currency?: string;
      } = await res.json();

      const imported = result.imported ?? ((result.created ?? 0) + (result.updated ?? 0));
      addToast({
        type: imported > 0 ? 'success' : 'warning',
        title: t('boq.import_preview.import_success', {
          defaultValue: 'Imported {{count}} positions',
          count: imported,
        }),
      });

      onImported();
      onClose();
    } catch (err) {
      clearTimeout(timeoutId);
      const isTimeout = err instanceof DOMException && err.name === 'AbortError';
      setError(
        isTimeout
          ? t('boq.import_preview.import_timeout', {
              defaultValue: 'Server did not respond within 90 seconds.',
            })
          : err instanceof Error
            ? err.message
            : 'Unknown error',
      );
    } finally {
      setImporting(false);
    }
  }, [file, boqId, addToast, t, onImported, onClose]);

  /* ── Drag & drop handlers ───────────────────────────────────────── */

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile],
  );

  /* ── Render ─────────────────────────────────────────────────────── */

  if (!open) return null;

  const positions = preview?.positions ?? [];
  const visibleRows = positions.slice(0, MAX_PREVIEW_ROWS);
  const remaining = positions.length > MAX_PREVIEW_ROWS ? positions.length - MAX_PREVIEW_ROWS : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="relative w-full max-w-3xl mx-4 rounded-xl border border-border-light bg-surface-elevated shadow-xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('boq.import_preview.title', { defaultValue: 'Import preview' })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={15} />
          </button>
        </div>

        {/* ── Body ──────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">

          {/* Step 1: Upload */}
          {step === 'upload' && !parsing && (
            <>
              <p className="text-xs text-content-secondary">
                {t('boq.import_preview.upload_hint', {
                  defaultValue: 'Choose a file to preview before importing into this BOQ.',
                })}
              </p>

              {/* Drop zone */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                className={`w-full rounded-xl border-2 border-dashed transition-colors py-10 flex flex-col items-center gap-3 text-content-secondary ${
                  dragOver
                    ? 'border-oe-blue bg-oe-blue/10'
                    : 'border-border-light hover:border-oe-blue hover:bg-oe-blue/5'
                }`}
              >
                <Upload size={24} className="text-content-tertiary" />
                <span className="text-sm font-medium">
                  {t('boq.import_preview.drop_zone', { defaultValue: 'Drop file here or click to browse' })}
                </span>
                <span className="text-2xs text-content-tertiary">
                  {t('boq.import_preview.drop_hint', {
                    defaultValue: 'GAEB XML, Excel, PDF or CSV',
                  })}
                </span>
              </button>

              {/* Format badges */}
              <div className="flex items-center gap-2 flex-wrap">
                {SUPPORTED_FORMATS.map((fmt) => (
                  <span
                    key={fmt}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-secondary text-2xs font-medium text-content-tertiary"
                  >
                    <FileSpreadsheet size={10} />
                    {fmt}
                  </span>
                ))}
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls,.csv,.pdf,.x81,.x83,.x84,.xml"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                  e.target.value = '';
                }}
              />

              {error && (
                <div className="flex items-start gap-2 p-2.5 rounded-lg bg-semantic-error/10 text-semantic-error text-xs">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  <p>{error}</p>
                </div>
              )}
            </>
          )}

          {/* Parsing spinner */}
          {parsing && (
            <div className="py-10 flex flex-col items-center gap-3 text-content-tertiary">
              <Loader2 size={24} className="animate-spin" />
              <p className="text-xs">
                {t('boq.import_preview.parsing', { defaultValue: 'Parsing file...' })}
              </p>
              {file && fileFormat && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-oe-blue/10 text-oe-blue text-2xs font-medium">
                  {fileFormat}
                </span>
              )}
            </div>
          )}

          {/* Step 2: Preview */}
          {step === 'preview' && preview && (
            <>
              {/* File & format badge */}
              {file && (
                <div className="flex items-center gap-2 text-xs text-content-secondary">
                  <FileSpreadsheet size={14} className="text-content-tertiary" />
                  <span className="truncate">{file.name}</span>
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-oe-blue/10 text-oe-blue text-2xs font-medium">
                    {preview.source_format || fileFormat}
                  </span>
                </div>
              )}

              {/* Stats bar */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <StatCard
                  label={t('boq.import_preview.stats_positions', { defaultValue: 'Positions' })}
                  value={String(preview.total_positions)}
                />
                <StatCard
                  label={t('boq.import_preview.stats_sections', { defaultValue: 'Sections' })}
                  value={String(preview.total_sections)}
                />
                <StatCard
                  label={t('boq.import_preview.stats_currency', { defaultValue: 'Currency' })}
                  value={preview.currency || '-'}
                />
                <StatCard
                  label={t('boq.import_preview.stats_format', { defaultValue: 'Format' })}
                  value={preview.source_format || fileFormat}
                />
              </div>

              {/* Warnings */}
              {preview.warnings.length > 0 && (
                <div className="rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-950/20 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setWarningsExpanded((v) => !v)}
                    className="flex items-center gap-2 w-full px-3 py-2 text-xs text-amber-800 dark:text-amber-300 font-medium"
                  >
                    {warningsExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <AlertTriangle size={12} />
                    {t('boq.import_preview.warnings_title', {
                      defaultValue: '{{count}} warning(s)',
                      count: preview.warnings.length,
                    })}
                  </button>
                  {warningsExpanded && (
                    <div className="px-3 pb-2 space-y-1">
                      {preview.warnings.map((w, i) => (
                        <p key={i} className="text-2xs text-amber-700 dark:text-amber-400">
                          {w.row != null ? `Row ${w.row}: ` : ''}{w.message}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Errors */}
              {preview.errors.length > 0 && (
                <div className="rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setErrorsExpanded((v) => !v)}
                    className="flex items-center gap-2 w-full px-3 py-2 text-xs text-red-800 dark:text-red-300 font-medium"
                  >
                    {errorsExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <AlertTriangle size={12} />
                    {t('boq.import_preview.errors_title', {
                      defaultValue: '{{count}} error(s)',
                      count: preview.errors.length,
                    })}
                  </button>
                  {errorsExpanded && (
                    <div className="px-3 pb-2 space-y-1">
                      {preview.errors.map((e, i) => (
                        <p key={i} className="text-2xs text-red-700 dark:text-red-400">
                          {e.row != null ? `Row ${e.row}: ` : ''}{e.message}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Skipped */}
              {preview.skipped > 0 && (
                <p className="text-2xs text-content-tertiary">
                  {t('boq.import_preview.skipped_count', {
                    defaultValue: '{{count}} row(s) skipped (empty or unreadable)',
                    count: preview.skipped,
                  })}
                </p>
              )}

              {/* Preview table */}
              <div className="rounded-lg border border-border-light overflow-hidden">
                <div className="overflow-x-auto max-h-[40vh]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-surface-secondary border-b border-border-light">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium text-content-tertiary whitespace-nowrap">
                          {t('boq.import_preview.col_ordinal', { defaultValue: 'Pos. / Code' })}
                        </th>
                        <th className="px-3 py-2 text-left font-medium text-content-tertiary">
                          {t('boq.import_preview.col_description', { defaultValue: 'Description' })}
                        </th>
                        <th className="px-3 py-2 text-left font-medium text-content-tertiary whitespace-nowrap">
                          {t('boq.import_preview.col_unit', { defaultValue: 'Unit' })}
                        </th>
                        <th className="px-3 py-2 text-right font-medium text-content-tertiary whitespace-nowrap">
                          {t('boq.import_preview.col_quantity', { defaultValue: 'Qty' })}
                        </th>
                        <th className="px-3 py-2 text-right font-medium text-content-tertiary whitespace-nowrap">
                          {t('boq.import_preview.col_unit_rate', { defaultValue: 'Unit Rate' })}
                        </th>
                        <th className="px-3 py-2 text-right font-medium text-content-tertiary whitespace-nowrap">
                          {t('boq.import_preview.col_total', { defaultValue: 'Total' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {visibleRows.map((pos, i) => (
                        <tr
                          key={i}
                          className={
                            pos.is_section
                              ? 'bg-surface-secondary/60'
                              : 'hover:bg-surface-secondary/30'
                          }
                        >
                          <td className={`px-3 py-1.5 whitespace-nowrap ${pos.is_section ? 'font-semibold text-content-primary' : 'text-content-secondary'}`}>
                            {pos.ordinal || pos.code || ''}
                          </td>
                          <td className={`px-3 py-1.5 max-w-xs truncate ${pos.is_section ? 'font-semibold text-content-primary' : 'text-content-primary'}`}>
                            {pos.description}
                          </td>
                          <td className="px-3 py-1.5 text-content-secondary whitespace-nowrap">
                            {pos.is_section ? '' : pos.unit}
                          </td>
                          <td className="px-3 py-1.5 text-right text-content-secondary tabular-nums whitespace-nowrap">
                            {pos.is_section ? '' : fmtNumber(pos.quantity)}
                          </td>
                          <td className="px-3 py-1.5 text-right text-content-secondary tabular-nums whitespace-nowrap">
                            {pos.is_section ? '' : fmtNumber(pos.unit_rate)}
                          </td>
                          <td className="px-3 py-1.5 text-right text-content-primary tabular-nums whitespace-nowrap font-medium">
                            {pos.is_section ? '' : fmtNumber(pos.total)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {remaining > 0 && (
                  <div className="px-3 py-2 border-t border-border-light text-2xs text-content-tertiary text-center">
                    {t('boq.import_preview.truncated', {
                      defaultValue: '... and {{count}} more position(s)',
                      count: remaining,
                    })}
                  </div>
                )}
              </div>
            </>
          )}

          {/* Step 3: Confirm */}
          {step === 'confirm' && preview && (
            <div className="space-y-4">
              <p className="text-sm text-content-primary">
                {t('boq.import_preview.confirm_summary', {
                  defaultValue:
                    'Import {{positions}} positions ({{sections}} sections) in {{currency}} from {{format}}?',
                  positions: preview.total_positions,
                  sections: preview.total_sections,
                  currency: preview.currency || '-',
                  format: preview.source_format || fileFormat,
                })}
              </p>

              {preview.warnings.length > 0 && (
                <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40 text-xs text-amber-800 dark:text-amber-300">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  <p>
                    {t('boq.import_preview.confirm_warnings', {
                      defaultValue: '{{count}} warning(s) were detected during parsing. The import will proceed.',
                      count: preview.warnings.length,
                    })}
                  </p>
                </div>
              )}

              {error && (
                <div className="flex items-start gap-2 p-2.5 rounded-lg bg-semantic-error/10 text-semantic-error text-xs">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  <p>{error}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Footer ────────────────────────────────────────────────── */}
        <div className="px-5 py-3 border-t border-border-light flex items-center gap-2">
          {step === 'preview' && (
            <button
              type="button"
              onClick={() => { setStep('upload'); setPreview(null); setFile(null); setError(null); }}
              className="px-3 py-1.5 text-xs rounded-lg text-content-secondary hover:bg-surface-secondary transition-colors"
            >
              {t('boq.import_preview.back', { defaultValue: 'Back' })}
            </button>
          )}
          {step === 'confirm' && (
            <button
              type="button"
              onClick={() => setStep('preview')}
              className="px-3 py-1.5 text-xs rounded-lg text-content-secondary hover:bg-surface-secondary transition-colors"
            >
              {t('boq.import_preview.back', { defaultValue: 'Back' })}
            </button>
          )}
          <div className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-lg text-content-secondary hover:bg-surface-secondary transition-colors"
          >
            {t('boq.import_preview.cancel', { defaultValue: 'Cancel' })}
          </button>
          {step === 'preview' && preview && (
            <button
              type="button"
              onClick={() => setStep('confirm')}
              disabled={preview.total_positions === 0}
              className="px-4 py-1.5 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {t('boq.import_preview.continue', { defaultValue: 'Continue' })}
            </button>
          )}
          {step === 'confirm' && (
            <button
              type="button"
              onClick={handleImport}
              disabled={importing}
              className="px-4 py-1.5 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
            >
              {importing && <Loader2 size={12} className="animate-spin" />}
              {t('boq.import_preview.confirm_button', { defaultValue: 'Import' })}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Internal components ────────────────────────────────────────────── */

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-light px-3 py-2">
      <div className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className="text-sm font-semibold text-content-primary tabular-nums">{value}</div>
    </div>
  );
}
