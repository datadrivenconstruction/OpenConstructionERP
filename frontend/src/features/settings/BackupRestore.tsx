/**
 * BackupRestore — Export and import user data backups.
 *
 * Provides a UI for creating database backups (export as ZIP)
 * and restoring from previously exported backups.
 */

import { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Download,
  Upload,
  Loader2,
  FileArchive,
  CheckCircle2,
  AlertTriangle,
  Shield,
  HardDrive,
  X,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, ConfirmDialog } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';

// ── Types ────────────────────────────────────────────────────────────────────

interface ValidateResult {
  valid: boolean;
  version: string;
  compatible: boolean;
  record_counts: Record<string, number>;
  warnings: string[];
  errors: string[];
}

interface RestoreResult {
  success: boolean;
  records_imported: Record<string, number>;
  warnings: string[];
}

// ── API helpers ──────────────────────────────────────────────────────────────

async function exportBackup(): Promise<Blob> {
  const token = useAuthStore.getState().accessToken;
  const resp = await fetch('/api/v1/backup/export/', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) throw new Error('Export failed');
  return resp.blob();
}

async function validateBackup(file: File): Promise<ValidateResult> {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch('/api/v1/backup/validate/', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) throw new Error('Validation failed');
  return resp.json();
}

async function restoreBackup(
  file: File,
  mode: 'replace' | 'merge',
): Promise<RestoreResult> {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append('file', file);
  form.append('mode', mode);
  const resp = await fetch('/api/v1/backup/restore/', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) throw new Error('Restore failed');
  return resp.json();
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

// ── Component ────────────────────────────────────────────────────────────────

export function BackupRestore() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // Export state
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<{ size: number } | null>(null);

  // Import state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [restoreMode, setRestoreMode] = useState<'replace' | 'merge'>('merge');
  const [restoring, setRestoring] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Export ───────────────────────────────────────────────────────────────

  const handleExport = useCallback(async () => {
    setExporting(true);
    setExportResult(null);
    try {
      const blob = await exportBackup();
      const now = new Date();
      const dateStr = now.toISOString().slice(0, 10);
      const filename = `openconstructionerp-backup-${dateStr}.zip`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.style.display = 'none';
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 200);

      setExportResult({ size: blob.size });
      addToast({
        type: 'success',
        title: t('backup.export_success', { defaultValue: 'Backup created' }),
        message: t('backup.export_success_detail', {
          defaultValue: 'Downloaded {{size}} backup file',
          size: formatBytes(blob.size),
        }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('backup.export_error', { defaultValue: 'Export failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setExporting(false);
    }
  }, [addToast, t]);

  // ── File selection ───────────────────────────────────────────────────────

  const handleFileSelect = useCallback(
    async (file: File) => {
      if (!file.name.endsWith('.zip')) {
        addToast({
          type: 'warning',
          title: t('backup.invalid_file', { defaultValue: 'Invalid file' }),
          message: t('backup.zip_only', { defaultValue: 'Please select a .zip backup file' }),
        });
        return;
      }

      setSelectedFile(file);
      setValidation(null);
      setValidating(true);

      try {
        const result = await validateBackup(file);
        setValidation(result);

        if (!result.valid) {
          addToast({
            type: 'error',
            title: t('backup.validation_failed', { defaultValue: 'Invalid backup' }),
            message: result.errors?.[0] || t('backup.validation_failed_detail', { defaultValue: 'The backup file is not valid' }),
          });
        }
      } catch (err) {
        addToast({
          type: 'error',
          title: t('backup.validation_error', { defaultValue: 'Validation error' }),
          message: err instanceof Error ? err.message : String(err),
        });
        setSelectedFile(null);
      } finally {
        setValidating(false);
      }
    },
    [addToast, t],
  );

  const onFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileSelect(file);
      e.target.value = '';
    },
    [handleFileSelect],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files?.[0];
      if (file) handleFileSelect(file);
    },
    [handleFileSelect],
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  // ── Restore ──────────────────────────────────────────────────────────────

  const handleRestore = useCallback(async () => {
    if (!selectedFile) return;

    setShowConfirm(false);
    setRestoring(true);

    try {
      const result = await restoreBackup(selectedFile, restoreMode);

      if (result.success) {
        const totalRecords = Object.values(result.records_imported).reduce(
          (a, b) => a + b,
          0,
        );
        addToast({
          type: 'success',
          title: t('backup.restore_success', { defaultValue: 'Backup restored' }),
          message: t('backup.restore_success_detail', {
            defaultValue: '{{count}} records imported successfully',
            count: totalRecords,
          }),
        });
        setSelectedFile(null);
        setValidation(null);
      } else {
        addToast({
          type: 'error',
          title: t('backup.restore_failed', { defaultValue: 'Restore failed' }),
          message: result.warnings?.[0] || t('backup.restore_failed_detail', { defaultValue: 'Could not restore from backup' }),
        });
      }
    } catch (err) {
      addToast({
        type: 'error',
        title: t('backup.restore_error', { defaultValue: 'Restore error' }),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRestoring(false);
    }
  }, [selectedFile, restoreMode, addToast, t]);

  const handleRestoreClick = useCallback(() => {
    if (restoreMode === 'replace') {
      setShowConfirm(true);
    } else {
      handleRestore();
    }
  }, [restoreMode, handleRestore]);

  const clearFile = useCallback(() => {
    setSelectedFile(null);
    setValidation(null);
  }, []);

  // ── Record counts grid ───────────────────────────────────────────────────

  const totalRecords = validation
    ? Object.values(validation.record_counts).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <>
      <Card>
        <CardHeader
          title={t('backup.title', { defaultValue: 'Backup & Restore' })}
          subtitle={t('backup.subtitle', {
            defaultValue: 'Export your data or restore from a previous backup',
          })}
        />
        <CardContent>
          <div className="space-y-6">
            {/* ── Export Section ──────────────────────────────────────────── */}
            <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-5">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
                  <HardDrive size={20} />
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="text-sm font-semibold text-content-primary">
                    {t('backup.export_title', { defaultValue: 'Create Backup' })}
                  </h4>
                  <p className="mt-0.5 text-xs text-content-secondary leading-relaxed">
                    {t('backup.export_desc', {
                      defaultValue:
                        'Export all your projects, BOQ data, cost databases, and settings as a ZIP file.',
                    })}
                  </p>
                  <div className="mt-3 flex items-center gap-3">
                    <Button
                      variant="primary"
                      size="md"
                      onClick={handleExport}
                      disabled={exporting}
                      loading={exporting}
                      icon={!exporting ? <Download size={14} /> : undefined}
                    >
                      {exporting
                        ? t('backup.exporting', { defaultValue: 'Creating backup...' })
                        : t('backup.export_btn', { defaultValue: 'Create Backup' })}
                    </Button>
                    {exportResult && (
                      <span className="flex items-center gap-1.5 text-xs text-semantic-success">
                        <CheckCircle2 size={14} />
                        {formatBytes(exportResult.size)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* ── Import Section ──────────────────────────────────────────── */}
            <div className="rounded-xl border border-border-light bg-surface-secondary/30 p-5">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
                  <Shield size={20} />
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="text-sm font-semibold text-content-primary">
                    {t('backup.import_title', { defaultValue: 'Restore from Backup' })}
                  </h4>
                  <p className="mt-0.5 text-xs text-content-secondary leading-relaxed">
                    {t('backup.import_desc', {
                      defaultValue:
                        'Upload a previously exported .zip backup file to restore your data.',
                    })}
                  </p>

                  {/* Drop zone */}
                  {!selectedFile && (
                    <div
                      onDrop={onDrop}
                      onDragOver={onDragOver}
                      onDragLeave={onDragLeave}
                      onClick={() => fileInputRef.current?.click()}
                      className={`mt-3 flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-5 transition-all ${
                        dragOver
                          ? 'border-oe-blue bg-oe-blue-subtle/50'
                          : 'border-border hover:border-oe-blue/50 hover:bg-surface-secondary/50'
                      }`}
                    >
                      <Upload
                        size={24}
                        className={
                          dragOver ? 'text-oe-blue' : 'text-content-tertiary'
                        }
                      />
                      <div className="text-center">
                        <p className="text-sm font-medium text-content-secondary">
                          {t('backup.drop_zone_label', {
                            defaultValue: 'Drop a .zip backup file here',
                          })}
                        </p>
                        <p className="mt-0.5 text-xs text-content-tertiary">
                          {t('backup.drop_zone_hint', {
                            defaultValue: 'or click to browse',
                          })}
                        </p>
                      </div>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".zip"
                        className="hidden"
                        onChange={onFileInputChange}
                      />
                    </div>
                  )}

                  {/* Validating spinner */}
                  {validating && (
                    <div className="mt-3 flex items-center gap-2 text-sm text-content-secondary">
                      <Loader2 size={16} className="animate-spin text-oe-blue" />
                      {t('backup.validating', { defaultValue: 'Validating backup file...' })}
                    </div>
                  )}

                  {/* Selected file + validation result */}
                  {selectedFile && !validating && (
                    <div className="mt-3 space-y-3">
                      {/* File info */}
                      <div className="flex items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5">
                        <FileArchive size={18} className="shrink-0 text-oe-blue" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-content-primary truncate">
                            {selectedFile.name}
                          </p>
                          <p className="text-xs text-content-tertiary">
                            {formatBytes(selectedFile.size)}
                            {validation?.version &&
                              ` \u2014 v${validation.version}`}
                          </p>
                        </div>
                        <button
                          onClick={clearFile}
                          className="shrink-0 rounded p-1 text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary transition-colors"
                          aria-label={t('common.remove', { defaultValue: 'Remove' })}
                        >
                          <X size={14} />
                        </button>
                      </div>

                      {/* Validation result */}
                      {validation && (
                        <>
                          {/* Record counts */}
                          {Object.keys(validation.record_counts).length > 0 && (
                            <div className="rounded-lg border border-border-light bg-surface-primary p-3">
                              <p className="text-xs font-medium text-content-secondary mb-2">
                                {t('backup.record_counts', {
                                  defaultValue: 'Records in backup ({{total}} total)',
                                  total: totalRecords,
                                })}
                              </p>
                              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1.5">
                                {Object.entries(validation.record_counts).map(
                                  ([key, count]) => (
                                    <div
                                      key={key}
                                      className="flex items-center justify-between text-xs"
                                    >
                                      <span className="text-content-secondary capitalize">
                                        {key.replace(/_/g, ' ')}
                                      </span>
                                      <span className="font-mono text-content-primary">
                                        {count}
                                      </span>
                                    </div>
                                  ),
                                )}
                              </div>
                            </div>
                          )}

                          {/* Warnings */}
                          {validation.warnings.length > 0 && (
                            <div className="rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg px-3 py-2.5">
                              {validation.warnings.map((w, i) => (
                                <div
                                  key={`warn-${w.slice(0, 30)}-${i}`}
                                  className="flex items-start gap-2 text-xs text-content-secondary"
                                >
                                  <AlertTriangle
                                    size={13}
                                    className="shrink-0 mt-0.5 text-semantic-warning"
                                  />
                                  <span>{w}</span>
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Compatibility check */}
                          {!validation.compatible && (
                            <div className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-3 py-2.5">
                              <div className="flex items-start gap-2 text-xs text-semantic-error">
                                <AlertTriangle size={13} className="shrink-0 mt-0.5" />
                                <span>
                                  {t('backup.incompatible', {
                                    defaultValue:
                                      'This backup was created with an incompatible version and may not restore correctly.',
                                  })}
                                </span>
                              </div>
                            </div>
                          )}

                          {/* Mode selector + Restore button */}
                          {validation.valid && (
                            <div className="space-y-3">
                              {/* Mode selector */}
                              <div>
                                <label className="text-xs font-medium text-content-secondary block mb-2">
                                  {t('backup.restore_mode', {
                                    defaultValue: 'Restore mode',
                                  })}
                                </label>
                                <div className="flex gap-2">
                                  <button
                                    onClick={() => setRestoreMode('merge')}
                                    aria-pressed={restoreMode === 'merge'}
                                    className={`flex-1 rounded-lg px-3 py-2.5 text-xs font-medium border-2 transition-all ${
                                      restoreMode === 'merge'
                                        ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                                        : 'border-border-light hover:bg-surface-secondary text-content-secondary'
                                    }`}
                                  >
                                    {t('backup.mode_merge', {
                                      defaultValue: 'Merge (keep existing)',
                                    })}
                                  </button>
                                  <button
                                    onClick={() => setRestoreMode('replace')}
                                    aria-pressed={restoreMode === 'replace'}
                                    className={`flex-1 rounded-lg px-3 py-2.5 text-xs font-medium border-2 transition-all ${
                                      restoreMode === 'replace'
                                        ? 'border-semantic-error bg-semantic-error-bg text-semantic-error'
                                        : 'border-border-light hover:bg-surface-secondary text-content-secondary'
                                    }`}
                                  >
                                    {t('backup.mode_replace', {
                                      defaultValue: 'Replace all data',
                                    })}
                                  </button>
                                </div>
                                {restoreMode === 'replace' && (
                                  <p className="mt-1.5 text-[11px] text-semantic-error leading-relaxed">
                                    {t('backup.replace_warning', {
                                      defaultValue:
                                        'This will permanently delete all existing data before restoring. This action cannot be undone.',
                                    })}
                                  </p>
                                )}
                              </div>

                              {/* Restore button */}
                              <Button
                                variant={restoreMode === 'replace' ? 'danger' : 'primary'}
                                size="md"
                                onClick={handleRestoreClick}
                                disabled={restoring}
                                loading={restoring}
                                icon={!restoring ? <Upload size={14} /> : undefined}
                              >
                                {restoring
                                  ? t('backup.restoring', {
                                      defaultValue: 'Restoring...',
                                    })
                                  : t('backup.restore_btn', {
                                      defaultValue: 'Restore Backup',
                                    })}
                              </Button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Confirm dialog for replace mode */}
      <ConfirmDialog
        open={showConfirm}
        onConfirm={handleRestore}
        onCancel={() => setShowConfirm(false)}
        title={t('backup.confirm_replace_title', {
          defaultValue: 'Replace all data?',
        })}
        message={t('backup.confirm_replace_message', {
          defaultValue:
            'All existing projects, BOQ data, cost databases, and settings will be permanently deleted and replaced with the backup contents. This action cannot be undone.',
        })}
        confirmLabel={t('backup.confirm_replace_btn', {
          defaultValue: 'Replace all data',
        })}
        variant="danger"
        loading={restoring}
      />
    </>
  );
}
