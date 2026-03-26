import { useState, useRef, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import JSZip from 'jszip';
import clsx from 'clsx';
import {
  Upload,
  X,
  FileArchive,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Package,
  User,
  Tag,
  FileText,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { useModuleStore } from '@/stores/useModuleStore';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** The shape we expect inside manifest.json in the uploaded zip. */
export interface UploadedManifest {
  name: string;
  version: string;
  displayName: string;
  description?: string;
  author?: string;
  category?: string;
}

type UploadStep = 'idle' | 'reading' | 'valid' | 'error';

interface ParseResult {
  manifest: UploadedManifest | null;
  error: string | null;
}

/* ── Props ─────────────────────────────────────────────────────────────── */

export interface ModuleUploadDialogProps {
  open: boolean;
  onClose: () => void;
}

/* ── Validation helpers ────────────────────────────────────────────────── */

const REQUIRED_MANIFEST_FIELDS: (keyof UploadedManifest)[] = [
  'name',
  'version',
  'displayName',
];

function validateManifest(data: unknown): ParseResult {
  if (!data || typeof data !== 'object') {
    return { manifest: null, error: 'manifest.json is not a valid JSON object.' };
  }

  const obj = data as Record<string, unknown>;

  for (const field of REQUIRED_MANIFEST_FIELDS) {
    if (!obj[field] || typeof obj[field] !== 'string') {
      return {
        manifest: null,
        error: `manifest.json is missing required field "${field}" (must be a non-empty string).`,
      };
    }
  }

  return {
    manifest: {
      name: obj['name'] as string,
      version: obj['version'] as string,
      displayName: obj['displayName'] as string,
      description: typeof obj['description'] === 'string' ? obj['description'] : undefined,
      author: typeof obj['author'] === 'string' ? obj['author'] : undefined,
      category: typeof obj['category'] === 'string' ? obj['category'] : undefined,
    },
    error: null,
  };
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function ModuleUploadDialog({ open, onClose }: ModuleUploadDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const installCustomModule = useModuleStore((s) => s.installCustomModule);
  const customModules = useModuleStore((s) => s.customModules);

  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<UploadStep>('idle');
  const [fileName, setFileName] = useState<string>('');
  const [manifest, setManifest] = useState<UploadedManifest | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [isDragOver, setIsDragOver] = useState(false);

  /** Reset state when dialog closes. */
  const reset = useCallback(() => {
    setStep('idle');
    setFileName('');
    setManifest(null);
    setErrorMessage('');
    setIsDragOver(false);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  /** Close handler that also resets. */
  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        handleClose();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [open, handleClose]);

  // Close on backdrop click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) {
        handleClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, handleClose]);

  /** Process a selected file. */
  const processFile = useCallback(
    async (file: File) => {
      // Validate extension
      if (!file.name.toLowerCase().endsWith('.zip')) {
        setStep('error');
        setFileName(file.name);
        setErrorMessage(
          t('module_upload.invalid_file_type', {
            defaultValue: 'Only .zip files are accepted. Please select a valid module package.',
          }),
        );
        return;
      }

      setStep('reading');
      setFileName(file.name);
      setManifest(null);
      setErrorMessage('');

      try {
        const zip = await JSZip.loadAsync(file);

        // Look for manifest.json (at root or one level deep)
        let manifestFile = zip.file('manifest.json');
        if (!manifestFile) {
          // Try one directory level deep (e.g. module-name/manifest.json)
          const entries = Object.keys(zip.files);
          const deepManifest = entries.find(
            (name) => name.match(/^[^/]+\/manifest\.json$/) && !zip.files[name]!.dir,
          );
          if (deepManifest) {
            manifestFile = zip.file(deepManifest);
          }
        }

        if (!manifestFile) {
          setStep('error');
          setErrorMessage(
            t('module_upload.no_manifest', {
              defaultValue:
                'No manifest.json found in the zip archive. A valid module package must contain a manifest.json at the root.',
            }),
          );
          return;
        }

        const content = await manifestFile.async('text');

        let parsed: unknown;
        try {
          parsed = JSON.parse(content);
        } catch {
          setStep('error');
          setErrorMessage(
            t('module_upload.invalid_manifest_json', {
              defaultValue: 'manifest.json contains invalid JSON.',
            }),
          );
          return;
        }

        const result = validateManifest(parsed);

        if (result.error) {
          setStep('error');
          setErrorMessage(result.error);
          return;
        }

        // Check if already installed
        const alreadyInstalled = customModules.some(
          (m) => m.name === result.manifest!.name,
        );
        if (alreadyInstalled) {
          setStep('error');
          setErrorMessage(
            t('module_upload.already_installed', {
              defaultValue:
                'A module with the name "{{name}}" is already installed. Remove it first to reinstall.',
              name: result.manifest!.name,
            }),
          );
          return;
        }

        setManifest(result.manifest);
        setStep('valid');
      } catch {
        setStep('error');
        setErrorMessage(
          t('module_upload.read_error', {
            defaultValue: 'Failed to read the zip file. It may be corrupted.',
          }),
        );
      }
    },
    [t, customModules],
  );

  /** Handle file input change. */
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) void processFile(file);
    },
    [processFile],
  );

  /** Handle drag & drop. */
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) void processFile(file);
    },
    [processFile],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  /** Install the module. */
  const handleInstall = useCallback(() => {
    if (!manifest) return;
    installCustomModule(manifest);
    addToast({
      type: 'success',
      title: t('module_upload.installed_title', { defaultValue: 'Module installed' }),
      message: t('module_upload.installed_message', {
        defaultValue: '"{{name}}" v{{version}} has been installed successfully.',
        name: manifest.displayName,
        version: manifest.version,
      }),
    });
    handleClose();
  }, [manifest, installCustomModule, addToast, t, handleClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('module_upload.title', { defaultValue: 'Upload Module' })}
        tabIndex={-1}
        className={clsx(
          'relative z-10 w-full max-w-md mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-xl',
          'animate-scale-in',
          'focus:outline-none',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-0">
          <h2 className="text-base font-semibold text-content-primary">
            {t('module_upload.title', { defaultValue: 'Upload Module' })}
          </h2>
          <button
            type="button"
            onClick={handleClose}
            data-testid="upload-dialog-close"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 pt-4 pb-6">
          {/* Drop zone */}
          {step === 'idle' || step === 'error' ? (
            <>
              <div
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onClick={() => fileInputRef.current?.click()}
                data-testid="upload-drop-zone"
                className={clsx(
                  'flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 cursor-pointer transition-all',
                  isDragOver
                    ? 'border-oe-blue bg-oe-blue-subtle/50'
                    : step === 'error'
                      ? 'border-semantic-error/30 bg-semantic-error/5 hover:border-semantic-error/50'
                      : 'border-border hover:border-oe-blue/50 hover:bg-surface-secondary',
                )}
              >
                <div
                  className={clsx(
                    'flex h-12 w-12 items-center justify-center rounded-full',
                    isDragOver
                      ? 'bg-oe-blue/10 text-oe-blue'
                      : step === 'error'
                        ? 'bg-semantic-error/10 text-semantic-error'
                        : 'bg-surface-tertiary text-content-tertiary',
                  )}
                >
                  {step === 'error' ? (
                    <AlertCircle size={24} />
                  ) : (
                    <Upload size={24} />
                  )}
                </div>

                <div className="text-center">
                  <p className="text-sm font-medium text-content-primary">
                    {isDragOver
                      ? t('module_upload.drop_here', { defaultValue: 'Drop file here' })
                      : t('module_upload.drag_or_click', {
                          defaultValue: 'Drag & drop a .zip file or click to browse',
                        })}
                  </p>
                  <p className="mt-1 text-xs text-content-tertiary">
                    {t('module_upload.zip_only', {
                      defaultValue: 'Only .zip module packages are accepted',
                    })}
                  </p>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip"
                  onChange={handleFileChange}
                  className="hidden"
                  data-testid="upload-file-input"
                />
              </div>

              {/* Error message */}
              {step === 'error' && errorMessage && (
                <div
                  className="mt-3 flex items-start gap-2 rounded-lg bg-semantic-error/5 border border-semantic-error/20 px-3 py-2.5"
                  data-testid="upload-error"
                >
                  <AlertCircle
                    size={14}
                    className="mt-0.5 shrink-0 text-semantic-error"
                  />
                  <div>
                    {fileName && (
                      <p className="text-xs font-medium text-content-primary mb-0.5">
                        {fileName}
                      </p>
                    )}
                    <p className="text-xs text-semantic-error">{errorMessage}</p>
                  </div>
                </div>
              )}
            </>
          ) : step === 'reading' ? (
            /* Reading state */
            <div className="flex flex-col items-center gap-3 py-8" data-testid="upload-reading">
              <Loader2 size={28} className="animate-spin text-oe-blue" />
              <p className="text-sm text-content-secondary">
                {t('module_upload.reading', {
                  defaultValue: 'Reading module package...',
                })}
              </p>
              {fileName && (
                <p className="text-xs text-content-tertiary font-mono">{fileName}</p>
              )}
            </div>
          ) : step === 'valid' && manifest ? (
            /* Valid manifest preview */
            <div data-testid="upload-preview">
              {/* Success header */}
              <div className="flex items-center gap-2 mb-4">
                <CheckCircle2 size={16} className="text-semantic-success" />
                <span className="text-sm font-medium text-semantic-success">
                  {t('module_upload.valid_package', {
                    defaultValue: 'Valid module package',
                  })}
                </span>
              </div>

              {/* Module info card */}
              <div className="rounded-xl border border-border-light bg-surface-primary p-4 space-y-3">
                {/* Name & version */}
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
                    <Package size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-content-primary">
                      {manifest.displayName}
                    </h3>
                    <p className="text-xs text-content-tertiary font-mono">
                      {manifest.name} v{manifest.version}
                    </p>
                  </div>
                </div>

                {/* Description */}
                {manifest.description && (
                  <div className="flex items-start gap-2 text-xs text-content-secondary">
                    <FileText size={12} className="mt-0.5 shrink-0 text-content-tertiary" />
                    <span>{manifest.description}</span>
                  </div>
                )}

                {/* Author */}
                {manifest.author && (
                  <div className="flex items-center gap-2 text-xs text-content-secondary">
                    <User size={12} className="shrink-0 text-content-tertiary" />
                    <span>{manifest.author}</span>
                  </div>
                )}

                {/* Category */}
                {manifest.category && (
                  <div className="flex items-center gap-2 text-xs text-content-secondary">
                    <Tag size={12} className="shrink-0 text-content-tertiary" />
                    <span>{manifest.category}</span>
                  </div>
                )}

                {/* File */}
                <div className="flex items-center gap-2 text-xs text-content-tertiary">
                  <FileArchive size={12} className="shrink-0" />
                  <span className="font-mono">{fileName}</span>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex gap-3 mt-5">
                <Button
                  variant="secondary"
                  size="md"
                  onClick={() => {
                    reset();
                  }}
                  className="flex-1"
                >
                  {t('module_upload.choose_different', {
                    defaultValue: 'Choose Different File',
                  })}
                </Button>
                <Button
                  variant="primary"
                  size="md"
                  icon={<Package size={14} />}
                  onClick={handleInstall}
                  data-testid="upload-install-btn"
                  className="flex-1"
                >
                  {t('module_upload.install', { defaultValue: 'Install Module' })}
                </Button>
              </div>
            </div>
          ) : null}

          {/* Cancel button for idle/error states */}
          {(step === 'idle' || step === 'error') && (
            <div className="mt-4 flex justify-end">
              <Button variant="ghost" size="sm" onClick={handleClose}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
