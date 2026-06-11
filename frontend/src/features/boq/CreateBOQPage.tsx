import { useState, useEffect, useRef, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronDown, X, FileSpreadsheet, FilePlus2, Upload, FileUp } from 'lucide-react';
import { Button, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiGet } from '@/shared/lib/api';
import { boqApi } from './api';

interface Project {
  id: string;
  name: string;
}

interface CreateBOQModalProps {
  open: boolean;
  onClose: () => void;
  defaultProjectId?: string;
}

type StartMode = 'empty' | 'import';

/**
 * Accepted import containers in the New BOQ window, grouped by the standard /
 * country they come from. Everything here is dispatched to the backend
 * `/import/auto/` endpoint, which sniffs the file and routes it to the matching
 * native parser (GAEB / FIEBDC-3 / Excel) or, for drawings and scans, to the
 * AI takeoff path. The `accept` string is derived from this list so the two can
 * never drift.
 */
const IMPORT_STANDARDS: { region: string; standard: string; exts: string[] }[] = [
  { region: 'Germany / Austria / Switzerland', standard: 'GAEB DA XML 3.3 (X81 / X83 / X84 / X86)', exts: ['.x81', '.x83', '.x84', '.x86', '.xml'] },
  { region: 'Spain / Latin America', standard: 'FIEBDC-3 (BC3)', exts: ['.bc3'] },
  { region: 'United Kingdom / United States / universal', standard: 'Excel or CSV (NRM / MasterFormat / custom columns)', exts: ['.xlsx', '.csv'] },
  { region: 'Drawings and scans (AI takeoff)', standard: 'PDF, IFC, DWG, RVT, DGN, images', exts: ['.pdf', '.ifc', '.dwg', '.rvt', '.dgn', '.jpg', '.jpeg', '.png', '.tiff'] },
];

const IMPORT_ACCEPT = Array.from(new Set(IMPORT_STANDARDS.flatMap((s) => s.exts))).join(',');

export function CreateBOQModal({ open, onClose, defaultProjectId }: CreateBOQModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedProjectId, setSelectedProjectId] = useState(defaultProjectId ?? '');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [startMode, setStartMode] = useState<StartMode>('empty');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  // Sync default project when modal opens or defaultProjectId changes
  useEffect(() => {
    if (open) {
      setSelectedProjectId(defaultProjectId ?? '');
      setName('');
      setDescription('');
      setStartMode('empty');
      setFile(null);
      setBusy(false);
      setError(null);
    }
  }, [open, defaultProjectId]);

  const stripExt = (filename: string): string => filename.replace(/\.[^./\\]+$/, '');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);

    // When importing, a missing name defaults to the file name so the user
    // does not have to type one just to get going.
    const effectiveName =
      name.trim() || (startMode === 'import' && file ? stripExt(file.name) : '');

    if (!selectedProjectId || !effectiveName) {
      setError(t('boq.create_needs_name', { defaultValue: 'Pick a project and give the BOQ a name.' }));
      return;
    }
    if (startMode === 'import' && !file) {
      setError(t('boq.import_needs_file', { defaultValue: 'Choose a file to import, or switch to an empty BOQ.' }));
      return;
    }

    setBusy(true);
    try {
      const boq = await boqApi.create({
        project_id: selectedProjectId,
        name: effectiveName,
        description,
      });

      if (startMode === 'import' && file) {
        addToast({
          type: 'info',
          title: t('boq.import_started', { defaultValue: 'Importing {{name}}…', name: file.name }),
          message: t('boq.import_started_hint', {
            defaultValue: 'Large files (PDF / CAD / 1000+ rows) may take up to 60 seconds.',
          }),
        });

        const token = useAuthStore.getState().accessToken;
        const form = new FormData();
        form.append('file', file);

        // The auto dispatcher sniffs the file and routes it to the native
        // GAEB / FIEBDC-3 / Excel parser, or to the AI path for drawings, so
        // every supported country standard lands on a real parser rather than
        // a generic guess. 90s ceiling so a hung upload cannot freeze the UI.
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 90_000);
        try {
          const res = await fetch(`/api/v1/boq/boqs/${boq.id}/import/auto/`, {
            method: 'POST',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            body: form,
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          if (!res.ok) {
            const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
            throw new Error(typeof body.detail === 'string' ? body.detail : t('boq.import_failed', { defaultValue: 'Import failed' }));
          }
          const result = (await res.json()) as {
            imported: number;
            skipped?: number;
            total_items?: number;
            errors?: unknown[];
            source_format?: string;
            format_id?: string;
            currency?: string;
          };
          const denominator = result.total_items ?? result.imported + (result.skipped ?? 0);
          const fmtLabel = result.source_format ? ` (${result.source_format}${result.currency ? `, ${result.currency}` : ''})` : '';
          const errCount = Array.isArray(result.errors) ? result.errors.length : 0;
          addToast({
            type: result.imported > 0 ? 'success' : 'warning',
            title: t('boq.import_done', {
              defaultValue: 'Imported {{n}} of {{total}} positions{{label}}',
              n: result.imported,
              total: denominator,
              label: fmtLabel,
            }),
            message: errCount > 0 ? t('boq.import_errors', { defaultValue: '{{n}} row(s) could not be read', n: errCount }) : undefined,
          });
        } catch (importErr) {
          clearTimeout(timeoutId);
          const isTimeout = importErr instanceof DOMException && importErr.name === 'AbortError';
          // The BOQ was created; only the import failed. Surface that clearly
          // and still navigate into the (empty) BOQ so the user can retry.
          addToast({
            type: 'error',
            title: t('boq.import_failed', { defaultValue: 'Import failed' }),
            message: isTimeout
              ? t('boq.import_timeout', { defaultValue: 'Server did not respond within 90 seconds. Try a smaller file.' })
              : importErr instanceof Error ? importErr.message : String(importErr),
          });
        }
      } else {
        addToast({ type: 'success', title: t('toasts.boq_created', { defaultValue: 'Bill of Quantities created successfully' }) });
      }

      queryClient.invalidateQueries({ queryKey: ['boqs', selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      onClose();
      navigate(`/boq/${boq.id}`);
    } catch (createErr) {
      setError(createErr instanceof Error ? createErr.message : t('toasts.boq_create_failed', { defaultValue: 'Failed to create Bill of Quantities' }));
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  const submitLabel =
    startMode === 'import'
      ? t('boq.create_and_import', { defaultValue: 'Create and import' })
      : t('boq.create_boq', { defaultValue: 'Create BOQ' });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in" onClick={busy ? undefined : onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-lg mx-4 rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-primary/10">
              <FileSpreadsheet size={20} className="text-accent-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('projects.new_boq', { defaultValue: 'New BOQ' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('boq.create_subtitle', { defaultValue: 'Create a new bill of quantities' })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={busy}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors disabled:opacity-50"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="px-6 pb-6 space-y-4">
          {/* Project selector */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('common.project')}
            </label>
            <div className="relative">
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                className="w-full h-10 appearance-none rounded-lg border border-border px-3 pr-9 text-sm text-content-primary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary"
                required aria-required="true"
              >
                <option value="" disabled>
                  {t('boq.select_project', { defaultValue: 'Select Project' })}
                </option>
                {projects?.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <ChevronDown size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
            </div>
          </div>

          {/* Start mode: empty vs import */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('boq.start_from', { defaultValue: 'Start from' })}
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setStartMode('empty')}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
                  startMode === 'empty'
                    ? 'border-oe-blue bg-oe-blue/5 text-content-primary'
                    : 'border-border text-content-secondary hover:border-content-tertiary'
                }`}
                aria-pressed={startMode === 'empty'}
              >
                <FilePlus2 size={16} className={startMode === 'empty' ? 'text-oe-blue' : 'text-content-tertiary'} />
                {t('boq.start_empty', { defaultValue: 'Empty BOQ' })}
              </button>
              <button
                type="button"
                onClick={() => setStartMode('import')}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
                  startMode === 'import'
                    ? 'border-oe-blue bg-oe-blue/5 text-content-primary'
                    : 'border-border text-content-secondary hover:border-content-tertiary'
                }`}
                aria-pressed={startMode === 'import'}
                data-testid="create-boq-import-mode"
              >
                <Upload size={16} className={startMode === 'import' ? 'text-oe-blue' : 'text-content-tertiary'} />
                {t('boq.start_import', { defaultValue: 'Import a file' })}
              </button>
            </div>
          </div>

          {/* Import file picker + supported standards */}
          {startMode === 'import' && (
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex w-full items-center gap-3 rounded-lg border border-dashed border-border px-3 py-3 text-left text-sm hover:border-oe-blue hover:bg-oe-blue/5 transition-colors"
                data-testid="create-boq-file-picker"
              >
                <FileUp size={18} className="shrink-0 text-content-tertiary" />
                {file ? (
                  <span className="truncate text-content-primary">{file.name}</span>
                ) : (
                  <span className="text-content-tertiary">
                    {t('boq.import_choose_file', { defaultValue: 'Choose a file to import' })}
                  </span>
                )}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept={IMPORT_ACCEPT}
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  setFile(f);
                  if (f && !name.trim()) setName(stripExt(f.name));
                  e.target.value = '';
                }}
                aria-label={t('boq.import_choose_file', { defaultValue: 'Choose a file to import' })}
              />

              <div className="rounded-lg bg-surface-secondary/60 px-3 py-2.5">
                <p className="text-xs font-medium text-content-secondary mb-1.5">
                  {t('boq.import_supported', { defaultValue: 'Supported standards' })}
                </p>
                <ul className="space-y-1">
                  {IMPORT_STANDARDS.map((s) => (
                    <li key={s.standard} className="flex flex-col text-xs leading-tight">
                      <span className="text-content-primary">{s.standard}</span>
                      <span className="text-content-tertiary">{s.region}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Name */}
          <Input
            label={t('boq.name_label', { defaultValue: 'BOQ Name' })}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('boq.name_placeholder', {
              defaultValue: 'e.g. Main Building - Structural Works',
            })}
            required={startMode === 'empty'}
            aria-required={startMode === 'empty'}
            autoFocus
          />

          {/* Description */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('common.description')}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('boq.scope_placeholder', { defaultValue: 'Scope of this BOQ...' })}
              rows={2}
              className="w-full rounded-lg border border-border px-3 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary resize-none"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="secondary" type="button" onClick={onClose} disabled={busy}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={busy}>
              {submitLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Route compat — redirects to /boq and opens modal
export function CreateBOQPage() {
  const navigate = useNavigate();
  const { projectId } = useParams<{ projectId: string }>();

  useEffect(() => {
    navigate('/boq', { state: { openCreateModal: true, projectId }, replace: true });
  }, [navigate, projectId]);

  return null;
}
