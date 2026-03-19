import { useState, useCallback, useRef, type DragEvent, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Upload,
  FileSpreadsheet,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Database,
} from 'lucide-react';
import { Button, Card, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

// ── Types ────────────────────────────────────────────────────────────────────

interface ImportResult {
  imported: number;
  skipped: number;
  errors: Array<{
    row: number;
    error: string;
    data: Record<string, string>;
  }>;
  total_rows: number;
}

// ── API helper for file upload ───────────────────────────────────────────────

const TOKEN_KEY = 'oe_access_token';

async function uploadCostFile(file: File): Promise<ImportResult> {
  const formData = new FormData();
  formData.append('file', file);

  const token = localStorage.getItem(TOKEN_KEY);
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/v1/costs/import/file', {
    method: 'POST',
    headers,
    body: formData,
  });

  if (!response.ok) {
    let detail = 'Upload failed';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }

  return response.json() as Promise<ImportResult>;
}

// ── File Preview Info ────────────────────────────────────────────────────────

interface FilePreview {
  name: string;
  size: string;
  type: 'excel' | 'csv';
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileType(name: string): 'excel' | 'csv' | null {
  const lower = name.toLowerCase();
  if (lower.endsWith('.xlsx') || lower.endsWith('.xls')) return 'excel';
  if (lower.endsWith('.csv')) return 'csv';
  return null;
}

// ── Component ────────────────────────────────────────────────────────────────

export function ImportDatabasePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const handleFile = useCallback(
    (file: File) => {
      const type = getFileType(file.name);
      if (!type) {
        addToast({
          type: 'error',
          title: t('costs.import_unsupported_format', {
            defaultValue: 'Unsupported file format',
          }),
          message: t('costs.import_supported_hint', {
            defaultValue: 'Please upload an Excel (.xlsx) or CSV (.csv) file.',
          }),
        });
        return;
      }

      // 10MB limit
      if (file.size > 10 * 1024 * 1024) {
        addToast({
          type: 'error',
          title: t('costs.import_file_too_large', { defaultValue: 'File too large' }),
          message: t('costs.import_max_size', { defaultValue: 'Maximum file size is 10 MB.' }),
        });
        return;
      }

      setSelectedFile(file);
      setPreview({
        name: file.name,
        size: formatFileSize(file.size),
        type,
      });
      setResult(null);
    },
    [addToast, t],
  );

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleFileInput = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const importMutation = useMutation({
    mutationFn: () => {
      if (!selectedFile) throw new Error('No file selected');
      return uploadCostFile(selectedFile);
    },
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ['costs'] });
      if (data.imported > 0) {
        addToast({
          type: 'success',
          title: t('costs.import_success', {
            defaultValue: 'Import complete',
          }),
          message: `${data.imported} items imported successfully.`,
        });
      }
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costs.import_failed', { defaultValue: 'Import failed' }),
        message: err.message,
      });
    },
  });

  const handleReset = useCallback(() => {
    setSelectedFile(null);
    setPreview(null);
    setResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <div className="max-w-2xl mx-auto animate-fade-in">
      {/* Back navigation */}
      <button
        onClick={() => navigate('/costs')}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        {t('costs.title', { defaultValue: 'Cost Database' })}
      </button>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('costs.import_title', { defaultValue: 'Import Cost Database' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('costs.import_subtitle', {
            defaultValue:
              'Load a pricing database or upload your own file.',
          })}
        </p>
      </div>

      {/* DDC Community Database — download from GitHub */}
      <Card className="mb-6 border-oe-blue/20 bg-gradient-to-r from-oe-blue-subtle/50 to-surface-elevated">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-oe-blue text-white">
            <Database size={22} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-content-primary">
              CWICR Cost Database — 55,000+ items
            </h3>
            <p className="mt-1 text-xs text-content-secondary leading-relaxed">
              Professional construction cost database by Data Driven Construction.
              9 languages, 85 fields per item. Includes labor, materials, equipment rates.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <a
                href="https://github.com/datadrivenconstructionIO/cwicr-database/releases"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg bg-oe-blue px-4 py-2 text-sm font-medium text-white shadow-sm transition-all hover:bg-oe-blue-hover hover:shadow-md active:scale-[0.98]"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
                Download from GitHub
              </a>
              <Badge variant="blue" size="sm">55,719 items</Badge>
              <Badge variant="neutral" size="sm">9 languages</Badge>
              <Badge variant="neutral" size="sm">Excel / CSV</Badge>
            </div>
            <p className="mt-2 text-2xs text-content-tertiary">
              Download the .xlsx or .csv file, then upload it below.
            </p>
          </div>
        </div>
      </Card>

      {/* Divider */}
      <div className="flex items-center gap-3 mb-6">
        <div className="h-px flex-1 bg-border-light" />
        <span className="text-xs font-medium text-content-tertiary uppercase tracking-wider">or upload your own file</span>
        <div className="h-px flex-1 bg-border-light" />
      </div>

      {/* Import result summary */}
      {result && (
        <Card className="mb-6 animate-card-in">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              {result.errors.length === 0 && result.imported > 0 ? (
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-success-bg">
                  <CheckCircle2 size={20} className="text-semantic-success" />
                </div>
              ) : result.imported === 0 ? (
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-error-bg">
                  <XCircle size={20} className="text-semantic-error" />
                </div>
              ) : (
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-warning-bg">
                  <AlertTriangle size={20} className="text-semantic-warning" />
                </div>
              )}
              <div>
                <h3 className="text-base font-semibold text-content-primary">
                  {t('costs.import_complete', { defaultValue: 'Import Complete' })}
                </h3>
                <p className="text-sm text-content-secondary">
                  {result.total_rows}{' '}
                  {t('costs.import_rows_processed', { defaultValue: 'rows processed' })}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl bg-semantic-success-bg/50 px-4 py-3 text-center">
                <div className="text-2xl font-bold text-[#15803d]">{result.imported}</div>
                <div className="text-xs text-content-secondary mt-0.5">
                  {t('costs.import_imported', { defaultValue: 'Imported' })}
                </div>
              </div>
              <div className="rounded-xl bg-surface-secondary px-4 py-3 text-center">
                <div className="text-2xl font-bold text-content-secondary">{result.skipped}</div>
                <div className="text-xs text-content-secondary mt-0.5">
                  {t('costs.import_skipped', { defaultValue: 'Skipped' })}
                </div>
              </div>
              <div className="rounded-xl bg-semantic-error-bg/50 px-4 py-3 text-center">
                <div className="text-2xl font-bold text-semantic-error">{result.errors.length}</div>
                <div className="text-xs text-content-secondary mt-0.5">
                  {t('costs.import_errors', { defaultValue: 'Errors' })}
                </div>
              </div>
            </div>

            {/* Error details (first 5) */}
            {result.errors.length > 0 && (
              <div className="rounded-lg border border-semantic-error/20 bg-semantic-error-bg/30 p-3">
                <p className="text-xs font-medium text-semantic-error mb-2">
                  {t('costs.import_error_details', { defaultValue: 'Error details' })}
                </p>
                <div className="space-y-1.5">
                  {result.errors.slice(0, 5).map((err, i) => (
                    <p key={i} className="text-xs text-content-secondary">
                      <span className="font-mono text-semantic-error">
                        {t('costs.import_row', { defaultValue: 'Row' })} {err.row}
                      </span>
                      : {err.error}
                    </p>
                  ))}
                  {result.errors.length > 5 && (
                    <p className="text-xs text-content-tertiary">
                      ...{t('costs.import_and_more', {
                        defaultValue: 'and {{count}} more errors',
                        count: result.errors.length - 5,
                      })}
                    </p>
                  )}
                </div>
              </div>
            )}

            <div className="flex items-center gap-3 pt-1">
              <Button variant="secondary" onClick={handleReset}>
                {t('costs.import_another', { defaultValue: 'Import Another' })}
              </Button>
              <Button variant="primary" onClick={() => navigate('/costs')}>
                {t('costs.import_go_to_database', { defaultValue: 'Go to Cost Database' })}
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Upload area */}
      {!result && (
        <>
          {/* Supported formats */}
          <Card className="mb-6">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle">
                <Database size={20} className="text-oe-blue" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('costs.import_formats_title', { defaultValue: 'Supported formats' })}
                </h3>
                <ul className="mt-2 space-y-1.5 text-sm text-content-secondary">
                  <li className="flex items-center gap-2">
                    <FileSpreadsheet size={14} className="text-[#15803d] shrink-0" />
                    {t('costs.import_format_excel', {
                      defaultValue:
                        'Excel (.xlsx) with columns: Code, Description, Unit, Rate',
                    })}
                  </li>
                  <li className="flex items-center gap-2">
                    <FileSpreadsheet size={14} className="text-oe-blue shrink-0" />
                    {t('costs.import_format_csv', {
                      defaultValue: 'CSV (.csv) with the same columns',
                    })}
                  </li>
                </ul>
                <p className="mt-2 text-xs text-content-tertiary">
                  {t('costs.import_columns_hint', {
                    defaultValue:
                      'Columns are auto-detected. Accepted headers: Code, Description, Unit, Rate/Price/Cost, Currency, DIN 276/Classification.',
                  })}
                </p>
              </div>
            </div>
          </Card>

          {/* Drag & drop zone */}
          <Card padding="none" className="overflow-hidden">
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center px-8 py-16 cursor-pointer transition-all duration-normal ease-oe ${
                isDragging
                  ? 'bg-oe-blue-subtle border-2 border-dashed border-oe-blue'
                  : selectedFile
                    ? 'bg-surface-secondary'
                    : 'bg-surface-elevated hover:bg-surface-secondary border-2 border-dashed border-border-light hover:border-border'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.csv,.xls"
                onChange={handleFileInput}
                className="hidden"
              />

              {selectedFile && preview ? (
                <div className="flex flex-col items-center gap-3 animate-fade-in">
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-oe-blue-subtle">
                    <FileSpreadsheet size={28} className="text-oe-blue" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-semibold text-content-primary">{preview.name}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="blue" size="sm">
                        {preview.type === 'excel' ? 'Excel' : 'CSV'}
                      </Badge>
                      <span className="text-xs text-content-tertiary">{preview.size}</span>
                    </div>
                  </div>
                  <p className="text-xs text-content-tertiary mt-1">
                    {t('costs.import_click_to_change', {
                      defaultValue: 'Click to choose a different file',
                    })}
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <div
                    className={`flex h-14 w-14 items-center justify-center rounded-2xl transition-colors duration-normal ${
                      isDragging
                        ? 'bg-oe-blue text-white'
                        : 'bg-surface-secondary text-content-tertiary'
                    }`}
                  >
                    <Upload size={28} />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-semibold text-content-primary">
                      {isDragging
                        ? t('costs.import_drop_here', { defaultValue: 'Drop your file here' })
                        : t('costs.import_drop_or_click', {
                            defaultValue: 'Drop your file here or click to browse',
                          })}
                    </p>
                    <p className="mt-1 text-xs text-content-tertiary">
                      {t('costs.import_accepted', {
                        defaultValue: 'Excel (.xlsx) or CSV (.csv) - max 10 MB',
                      })}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* Actions */}
          {selectedFile && (
            <div className="mt-6 flex items-center justify-end gap-3 animate-fade-in">
              <Button variant="secondary" onClick={handleReset}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                onClick={() => importMutation.mutate()}
                loading={importMutation.isPending}
                icon={
                  importMutation.isPending ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Upload size={16} />
                  )
                }
              >
                {importMutation.isPending
                  ? t('costs.import_importing', { defaultValue: 'Importing...' })
                  : t('costs.import_all', { defaultValue: 'Import All' })}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
