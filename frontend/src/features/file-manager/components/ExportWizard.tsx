// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Modal wizard for exporting a project bundle (.ocep). */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Loader2, Download, ChevronLeft, AlertTriangle } from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { previewExport, downloadBundle } from '../api';
import type { BundleScope, ExportOptions, ExportPreview } from '../types';
import { fmtFixed } from '@/shared/lib/formatters';

interface ExportWizardProps {
  open: boolean;
  projectId: string;
  projectName?: string;
  onClose: () => void;
}

const SCOPES: BundleScope[] = ['metadata_only', 'documents', 'bim', 'dwg', 'full'];

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

export function ExportWizard({ open, projectId, projectName, onClose }: ExportWizardProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [step, setStep] = useState<'scope' | 'preview'>('scope');
  const [scope, setScope] = useState<BundleScope>('metadata_only');
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset whenever the modal closes so reopening starts fresh.
  useEffect(() => {
    if (!open) {
      setStep('scope');
      setPreview(null);
      setError(null);
      setDownloading(false);
      setPreviewLoading(false);
    }
  }, [open]);

  // Escape closes the modal.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const options: ExportOptions = { scope };

  async function handlePreview() {
    setPreviewLoading(true);
    setError(null);
    try {
      const result = await previewExport(projectId, options);
      setPreview(result);
      setStep('preview');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      const fallback = `${(projectName ?? 'project').replace(/[^a-zA-Z0-9_-]+/g, '_')}.ocep`;
      const result = await downloadBundle(projectId, options, fallback);
      addToast({
        type: 'success',
        title: t('files.export.success_title', { defaultValue: 'Bundle downloaded' }),
        message: `${result.filename} (${fmtBytes(result.sizeBytes)})`,
      });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDownloading(false);
    }
  }

  const scopeLabels: Record<BundleScope, string> = {
    metadata_only: t('files.export.scope_metadata', { defaultValue: 'Metadata only' }),
    documents: t('files.export.scope_documents', { defaultValue: 'Documents' }),
    bim: t('files.export.scope_bim', { defaultValue: 'BIM models' }),
    dwg: t('files.export.scope_dwg', { defaultValue: 'DWG drawings' }),
    full: t('files.export.scope_full', { defaultValue: 'Full project' }),
  };

  const scopeHints: Record<BundleScope, string> = {
    metadata_only: t('files.export.scope_metadata_hint', {
      defaultValue: 'Email-friendly. BOQs, tables, and links - no attachments. Fits in any inbox.',
    }),
    documents: t('files.export.scope_documents_hint', {
      defaultValue: 'Adds uploaded documents and photos with their thumbnails.',
    }),
    bim: t('files.export.scope_bim_hint', {
      defaultValue: 'Adds BIM models, elements, and canonical geometry.',
    }),
    dwg: t('files.export.scope_dwg_hint', {
      defaultValue: 'Adds DWG drawings, versions, and related sheets.',
    }),
    full: t('files.export.scope_full_hint', {
      defaultValue: 'Everything - full migration package, including all attachments.',
    }),
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="relative w-full max-w-lg mx-4 rounded-xl border border-border-light bg-surface-elevated shadow-xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('files.export.title', { defaultValue: 'Export project bundle' })}
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

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {step === 'scope' && (
            <>
              <p className="text-xs text-content-secondary">
                {t('files.export.intro', {
                  defaultValue:
                    'Choose what to include. Smaller bundles transfer faster; bigger bundles preserve more.',
                })}
              </p>
              <div className="space-y-2">
                {SCOPES.map((s) => (
                  <label
                    key={s}
                    className={clsx(
                      'flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                      scope === s
                        ? 'border-oe-blue bg-oe-blue/5'
                        : 'border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <input
                      type="radio"
                      name="scope"
                      value={s}
                      checked={scope === s}
                      onChange={() => setScope(s)}
                      className="mt-0.5 accent-oe-blue"
                    />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-content-primary">
                        {scopeLabels[s]}
                      </div>
                      <p className="text-xs text-content-tertiary mt-0.5">{scopeHints[s]}</p>
                    </div>
                  </label>
                ))}
              </div>
            </>
          )}

          {step === 'preview' && preview && (
            <>
              <div className="rounded-lg border border-border-light p-3 space-y-2">
                <Stat
                  label={t('files.export.stat_scope', { defaultValue: 'Scope' })}
                  value={scopeLabels[preview.scope]}
                />
                <Stat
                  label={t('files.export.stat_attachments', { defaultValue: 'Attachments' })}
                  value={String(preview.attachment_count)}
                />
                <Stat
                  label={t('files.export.stat_size', { defaultValue: 'Estimated size' })}
                  value={fmtBytes(preview.estimated_size_bytes)}
                />
                <Stat
                  label={t('files.export.stat_format', { defaultValue: 'Format' })}
                  value={`${preview.bundle_format} ${preview.bundle_format_version}`}
                />
              </div>

              <div>
                <h3 className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                  {t('files.export.tables', { defaultValue: 'Tables' })}
                </h3>
                <div className="rounded-lg border border-border-light overflow-hidden text-xs">
                  <div className="max-h-48 overflow-y-auto">
                    <table className="w-full">
                      <tbody>
                        {Object.entries(preview.table_counts)
                          .sort(([, a], [, b]) => b - a)
                          .map(([tbl, count]) => (
                            <tr key={tbl} className="border-b border-border-light last:border-0">
                              <td className="px-3 py-1.5 font-mono text-[11px] text-content-secondary truncate">
                                {tbl}
                              </td>
                              <td className="px-3 py-1.5 text-right tabular-nums text-content-tertiary">
                                {count}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              {preview.estimated_size_bytes > 200 * 1024 * 1024 && (
                <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/20 text-amber-800 dark:text-amber-300 text-xs">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  <p>
                    {t('files.export.large_warn', {
                      defaultValue:
                        'Large bundle - keep this tab open while exporting.',
                    })}
                  </p>
                </div>
              )}
            </>
          )}

          {error && (
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-semantic-error/10 text-semantic-error text-xs">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <p>{error}</p>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-border-light flex items-center gap-2">
          {step === 'preview' && (
            <button
              type="button"
              onClick={() => setStep('scope')}
              className="inline-flex items-center gap-1 h-9 px-3 text-xs font-medium rounded-lg text-content-secondary hover:bg-surface-secondary"
            >
              <ChevronLeft size={12} />
              {t('common.back', { defaultValue: 'Back' })}
            </button>
          )}
          <div className="ms-auto flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-9 px-4 text-xs font-medium rounded-lg text-content-secondary hover:bg-surface-secondary"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            {step === 'scope' ? (
              <button
                type="button"
                onClick={handlePreview}
                disabled={previewLoading}
                className="inline-flex items-center gap-2 h-9 px-4 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover disabled:opacity-50"
              >
                {previewLoading && <Loader2 size={12} className="animate-spin" />}
                {t('files.export.preview_btn', { defaultValue: 'Preview' })}
              </button>
            ) : (
              <button
                type="button"
                onClick={handleDownload}
                disabled={downloading}
                className="inline-flex items-center gap-2 h-9 px-4 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover disabled:opacity-50"
              >
                {downloading ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                {t('files.export.download_btn', { defaultValue: 'Download bundle' })}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-content-tertiary">{label}</span>
      <span className="font-medium text-content-primary truncate">{value}</span>
    </div>
  );
}
