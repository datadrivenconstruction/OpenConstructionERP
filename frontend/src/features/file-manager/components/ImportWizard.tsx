// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Modal wizard for importing a project bundle (.ocep). */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { X, Loader2, Upload, ChevronLeft, AlertTriangle, CheckCircle2 } from 'lucide-react';
import clsx from 'clsx';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { validateImport, commitImport } from '../api';
import type { ImportMode, ImportPreview, ImportResult } from '../types';
import { fmtFixed } from '@/shared/lib/formatters';

interface ImportWizardProps {
  open: boolean;
  onClose: () => void;
}

interface ProjectListItem {
  id: string;
  name: string;
}

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

type Step = 'pick' | 'validate' | 'mode' | 'result';

export function ImportWizard({ open, onClose }: ImportWizardProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>('pick');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mode, setMode] = useState<ImportMode>('new_project');
  const [targetProjectId, setTargetProjectId] = useState<string>('');
  const [newProjectName, setNewProjectName] = useState<string>('');
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Project list — only fetched while the modal is open and the user is on
  // a step where they need to pick a target project.
  const { data: projects } = useQuery({
    queryKey: ['file-manager-projects-list'],
    queryFn: () => fetchProjectList<ProjectListItem[]>(),
    enabled: open && step === 'mode' && (mode === 'merge_into_existing' || mode === 'replace_existing'),
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!open) {
      setStep('pick');
      setFile(null);
      setPreview(null);
      setMode('new_project');
      setTargetProjectId('');
      setNewProjectName('');
      setCommitting(false);
      setResult(null);
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  async function handleFile(f: File) {
    setFile(f);
    setError(null);
    setStep('validate');
    try {
      const p = await validateImport(f);
      setPreview(p);
      setNewProjectName(`${p.manifest.project_name} (imported)`);
      setStep('mode');
    } catch (e) {
      setError((e as Error).message);
      setStep('pick');
    }
  }

  async function handleCommit() {
    if (!file) return;
    setCommitting(true);
    setError(null);
    try {
      const r = await commitImport({
        file,
        mode,
        targetProjectId: mode === 'new_project' ? undefined : targetProjectId || undefined,
        newProjectName: mode === 'new_project' && newProjectName ? newProjectName : undefined,
      });
      setResult(r);
      setStep('result');
      addToast({
        type: 'success',
        title: t('files.import.success_title', { defaultValue: 'Bundle imported' }),
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCommitting(false);
    }
  }

  const modeLabels: Record<ImportMode, string> = {
    new_project: t('files.import.mode_new', { defaultValue: 'Create a new project' }),
    merge_into_existing: t('files.import.mode_merge', { defaultValue: 'Merge into existing project' }),
    replace_existing: t('files.import.mode_replace', { defaultValue: 'Replace existing project' }),
  };

  const modeHints: Record<ImportMode, string> = {
    new_project: t('files.import.mode_new_hint', {
      defaultValue: 'Safest. New IDs everywhere; nothing in your workspace changes.',
    }),
    merge_into_existing: t('files.import.mode_merge_hint', {
      defaultValue: 'Adds rows to a chosen project. Existing IDs are skipped.',
    }),
    replace_existing: t('files.import.mode_replace_hint', {
      defaultValue: 'Wipes the chosen project\'s bundle-managed rows, then imports. Destructive.',
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
            {t('files.import.title', { defaultValue: 'Import project bundle' })}
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
          {step === 'pick' && (
            <>
              <p className="text-xs text-content-secondary">
                {t('files.import.intro', {
                  defaultValue: 'Select a .ocep bundle exported from this or any other workspace.',
                })}
              </p>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="w-full rounded-xl border-2 border-dashed border-border-light hover:border-oe-blue hover:bg-oe-blue/5 transition-colors py-10 flex flex-col items-center gap-2 text-content-secondary"
              >
                <Upload size={20} className="text-content-tertiary" />
                <span className="text-sm font-medium">
                  {t('files.import.select_file', { defaultValue: 'Choose .ocep file' })}
                </span>
                <span className="text-2xs text-content-tertiary">
                  {t('files.import.drop_hint', { defaultValue: 'Click to browse' })}
                </span>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".ocep,application/zip"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
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

          {step === 'validate' && (
            <div className="py-10 flex flex-col items-center gap-3 text-content-tertiary">
              <Loader2 size={20} className="animate-spin" />
              <p className="text-xs">
                {t('files.import.validating', { defaultValue: 'Validating bundle…' })}
              </p>
            </div>
          )}

          {step === 'mode' && preview && file && (
            <>
              <div className="rounded-lg border border-border-light p-3 space-y-1.5">
                <Stat
                  label={t('files.import.stat_project', { defaultValue: 'Source project' })}
                  value={preview.manifest.project_name}
                />
                <Stat
                  label={t('files.import.stat_scope', { defaultValue: 'Scope' })}
                  value={preview.manifest.scope}
                />
                <Stat
                  label={t('files.import.stat_size', { defaultValue: 'Bundle size' })}
                  value={fmtBytes(preview.bundle_size_bytes)}
                />
                <Stat
                  label={t('files.import.stat_attachments', { defaultValue: 'Attachments' })}
                  value={
                    preview.has_attachments
                      ? `${preview.manifest.attachment_count} (${fmtBytes(preview.manifest.attachment_total_bytes)})`
                      : t('files.import.no_attachments', { defaultValue: 'None' })
                  }
                />
                <Stat
                  label={t('files.import.stat_format', { defaultValue: 'Format' })}
                  value={`${preview.manifest.format} ${preview.manifest.format_version}`}
                />
              </div>

              {preview.warnings.length > 0 && (
                <div className="rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-950/20 p-2.5 text-xs text-amber-800 dark:text-amber-300 space-y-1">
                  {preview.warnings.map((w, i) => (
                    <p key={i} className="flex items-start gap-1.5">
                      <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                      {w}
                    </p>
                  ))}
                </div>
              )}

              <div>
                <h3 className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1.5">
                  {t('files.import.choose_mode', { defaultValue: 'Import mode' })}
                </h3>
                <div className="space-y-2">
                  {(['new_project', 'merge_into_existing', 'replace_existing'] as ImportMode[]).map((m) => (
                    <label
                      key={m}
                      className={clsx(
                        'flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                        mode === m
                          ? m === 'replace_existing'
                            ? 'border-semantic-error bg-semantic-error/5'
                            : 'border-oe-blue bg-oe-blue/5'
                          : 'border-border-light hover:bg-surface-secondary',
                      )}
                    >
                      <input
                        type="radio"
                        name="mode"
                        value={m}
                        checked={mode === m}
                        onChange={() => setMode(m)}
                        className="mt-0.5 accent-oe-blue"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-content-primary">
                          {modeLabels[m]}
                        </div>
                        <p className="text-xs text-content-tertiary mt-0.5">{modeHints[m]}</p>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {mode === 'new_project' && (
                <div>
                  <label className="block text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                    {t('files.import.rename', { defaultValue: 'New project name (optional)' })}
                  </label>
                  <input
                    type="text"
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    className="w-full h-9 px-3 text-sm rounded-lg border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20"
                  />
                </div>
              )}

              {(mode === 'merge_into_existing' || mode === 'replace_existing') && (
                <div>
                  <label className="block text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                    {t('files.import.target_project', { defaultValue: 'Target project' })}
                  </label>
                  <select
                    value={targetProjectId}
                    onChange={(e) => setTargetProjectId(e.target.value)}
                    className="w-full h-9 px-2 text-sm rounded-lg border border-border-light bg-surface-primary text-content-primary focus:outline-none focus:border-oe-blue focus:ring-2 focus:ring-oe-blue/20"
                  >
                    <option value="">
                      {t('files.import.pick_project', { defaultValue: '- pick a project -' })}
                    </option>
                    {(projects ?? []).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {mode === 'replace_existing' && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-semantic-error/10 border border-semantic-error/30 text-semantic-error text-xs">
                  <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                  <p>
                    {t('files.import.destructive_warn', {
                      defaultValue:
                        'This will permanently delete the bundle-managed rows in the target project before importing. Cannot be undone.',
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
            </>
          )}

          {step === 'result' && result && (
            <>
              <div className="flex items-center gap-2.5 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={18} />
                <span className="text-sm font-semibold">
                  {t('files.import.result_done', { defaultValue: 'Import complete' })}
                </span>
              </div>
              <div className="rounded-lg border border-border-light overflow-hidden">
                <div className="grid grid-cols-2">
                  <div className="px-3 py-2 border-r border-border-light">
                    <div className="text-2xs uppercase tracking-wide text-content-tertiary">
                      {t('files.import.imported', { defaultValue: 'Imported' })}
                    </div>
                    <div className="text-lg font-semibold text-content-primary tabular-nums">
                      {Object.values(result.imported_counts).reduce((a, b) => a + b, 0)}
                    </div>
                  </div>
                  <div className="px-3 py-2">
                    <div className="text-2xs uppercase tracking-wide text-content-tertiary">
                      {t('files.import.skipped', { defaultValue: 'Skipped' })}
                    </div>
                    <div className="text-lg font-semibold text-content-primary tabular-nums">
                      {Object.values(result.skipped_counts).reduce((a, b) => a + b, 0)}
                    </div>
                  </div>
                </div>
                <div className="border-t border-border-light px-3 py-2 text-xs text-content-tertiary">
                  {t('files.import.stat_attachments', { defaultValue: 'Attachments' })}:{' '}
                  <span className="text-content-primary font-medium tabular-nums">
                    {result.attachment_count}
                  </span>
                </div>
              </div>

              {result.warnings.length > 0 && (
                <div className="rounded-lg border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-950/20 p-2.5 text-xs text-amber-800 dark:text-amber-300 space-y-1">
                  {result.warnings.map((w, i) => (
                    <p key={i}>{w}</p>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-border-light flex items-center gap-2">
          {step === 'mode' && (
            <button
              type="button"
              onClick={() => {
                setStep('pick');
                setFile(null);
                setPreview(null);
              }}
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
              {step === 'result'
                ? t('common.close', { defaultValue: 'Close' })
                : t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            {step === 'mode' && (
              <button
                type="button"
                onClick={handleCommit}
                disabled={
                  committing ||
                  ((mode === 'merge_into_existing' || mode === 'replace_existing') && !targetProjectId)
                }
                className={clsx(
                  'inline-flex items-center gap-2 h-9 px-4 text-xs font-medium rounded-lg text-white disabled:opacity-50',
                  mode === 'replace_existing'
                    ? 'bg-semantic-error hover:opacity-90'
                    : 'bg-oe-blue hover:bg-oe-blue-hover',
                )}
              >
                {committing && <Loader2 size={12} className="animate-spin" />}
                {t('files.import.confirm', { defaultValue: 'Import' })}
              </button>
            )}
            {step === 'result' && result && (
              <button
                type="button"
                onClick={() => {
                  navigate(`/projects/${result.project_id}`);
                  onClose();
                }}
                className="inline-flex items-center gap-2 h-9 px-4 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover"
              >
                {t('files.import.open_imported', { defaultValue: 'Open imported project' })}
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
