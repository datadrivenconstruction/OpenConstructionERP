/**
 * BIMPage — Premium BIM Hub with immersive 3D viewport and polished light UI.
 *
 * Layout:
 *  - Clean light header with stats + actions
 *  - Full-height 3D viewport
 *  - Glass-morphism model filmstrip at the bottom
 *  - Slide-in upload panel from right
 *  - Professional landing page when no models exist
 *
 * Route: /projects/:projectId/bim  or  /bim
 */

import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  ChevronRight,
  Loader2,
  FolderOpen,
  Link2,
  Upload,
  Database,
  FileBox,
  FileUp,
  X,
  CheckCircle2,
  AlertCircle,
  ChevronUp,
  CalendarDays,
  Trash2,
  Eye,
  Layers,
  AlertTriangle,
  UploadCloud,
  Sparkles,
  Building2,
  Ruler,
  Globe2,
  ArrowRight,
  Plus,
  Cuboid,
  SlidersHorizontal,
  ClipboardList,
  ShieldCheck,
  LayoutGrid,
  Maximize2,
  Package,
} from 'lucide-react';
import { Badge, EmptyState, Breadcrumb, ConfirmDialog } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';
import {
  parseBIMUrlState,
  serializeBIMUrlState,
  BIM_URL_STATE_KEYS,
} from '@/shared/ui/BIMViewer/urlState';
import BIMFilterGroupsPanel from './BIMFilterGroupsPanel';
import BIMRightPanelTabs from './BIMRightPanelTabs';
import ElementAssetCard from './ElementAssetCard';
import BIMSnapshotsPopover from './BIMSnapshotsPopover';
import { useBIMViewerStore } from '@/stores/useBIMViewerStore';
import { BIMConverterStatusBanner } from './BIMConverterStatusBanner';
import { InstallConverterPrompt } from './InstallConverterPrompt';
import AddToBOQModal from './AddToBOQModal';
import SaveGroupModal from './SaveGroupModal';
import CreateTaskFromBIMModal from './CreateTaskFromBIMModal';
import LinkDocumentToBIMModal from './LinkDocumentToBIMModal';
import LinkActivityToBIMModal from './LinkActivityToBIMModal';
import LinkRequirementToBIMModal from './LinkRequirementToBIMModal';
import type { BIMGroupFilterCriteria } from './api';
import { Filter } from 'lucide-react';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBIMLinkSelectionStore } from '@/stores/useBIMLinkSelectionStore';
import { useBIMUploadStore, type BIMUploadJob } from '@/stores/useBIMUploadStore';
import { apiGet } from '@/shared/lib/api';
import {
  fetchBIMModels,
  fetchBIMModel,
  fetchBIMElements,
  fetchBIMConverters,
  deleteBIMModel,
  deleteLink,
  listElementGroups,
  deleteElementGroup,
  type BIMElementGroup,
} from './api';

/* ── Helpers ─────────────────────────────────────────────────────────── */

const CAD_EXTENSIONS = new Set(['.rvt', '.ifc']);
const DATA_EXTENSIONS = new Set(['.csv', '.xlsx', '.xls']);
/** Extensions handled by the DWG Takeoff module — not accepted in BIM Hub. */
const DWG_EXTENSIONS = new Set(['.dwg', '.dxf']);

function getFileExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot).toLowerCase() : '';
}
function isCADFile(fn: string): boolean {
  return CAD_EXTENSIONS.has(getFileExtension(fn));
}
function isDataFile(fn: string): boolean {
  return DATA_EXTENSIONS.has(getFileExtension(fn));
}
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

/* ── Stat Pill ───────────────────────────────────────────────────────── */

function StatPill({ label, value, icon: Icon }: { label: string; value: string | number; icon: React.ElementType }) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-secondary border border-border-light">
      <Icon size={13} className="text-content-tertiary" />
      <span className="text-[11px] font-medium text-content-tertiary">{label}</span>
      <span className="text-[11px] font-bold text-content-primary tabular-nums">{value}</span>
    </div>
  );
}

/* ── Model Card ──────────────────────────────────────────────────────── */

/** Collapsible model filmstrip — shows for 5s on mount, then slides away.
 *  Click the tab handle to re-expand. */
function ModelFilmstrip({ models, isLoading, activeModelId, onSelectModel, onDeleteModel, onUpload }: {
  models: BIMModelData[];
  isLoading: boolean;
  activeModelId: string | null;
  onSelectModel: (id: string) => void;
  onDeleteModel: (id: string, name: string) => void;
  onUpload: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="shrink-0 bg-surface-primary border-t border-border-light">
      {/* Header — always visible with drag handle, title, and count */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={t('bim.toggle_models_filmstrip', { defaultValue: 'Toggle models filmstrip' })}
        className="flex items-center w-full px-4 py-2 cursor-pointer group hover:bg-surface-secondary/30 transition-colors"
      >
        {/* Drag handle icon */}
        <div className="flex flex-col items-center gap-[3px] mr-3 opacity-50 group-hover:opacity-80 transition-opacity">
          <div className="w-5 h-[2px] rounded-full bg-content-tertiary" />
          <div className="w-5 h-[2px] rounded-full bg-content-tertiary" />
          <div className="w-5 h-[2px] rounded-full bg-content-tertiary" />
        </div>

        {/* Model icon */}
        <Layers size={16} className="text-content-secondary mr-2 shrink-0" />

        {/* Title */}
        <span className="text-xs font-semibold text-content-primary">
          {t('bim.models_label', { defaultValue: 'Models' })}
        </span>
        <span className="text-[11px] text-content-tertiary ml-1.5">({models.length})</span>

        {/* Expand/collapse chevron */}
        <svg
          className={`ml-auto w-4 h-4 text-content-tertiary transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
        </svg>
      </button>

      {/* Collapsible model cards */}
      <div
        className="overflow-hidden transition-all duration-300 ease-in-out"
        style={{ maxHeight: expanded ? '120px' : '0px', opacity: expanded ? 1 : 0 }}
      >
        <div className="flex items-center gap-3 px-4 pb-2 overflow-x-auto">
          {isLoading ? (
            <Loader2 size={14} className="animate-spin text-content-quaternary" />
          ) : models.length ? (
            models.map((m) => (
              <ModelCard key={m.id} model={m} isActive={m.id === activeModelId}
                onClick={() => onSelectModel(m.id)}
                onDelete={() => onDeleteModel(m.id, m.name)} />
            ))
          ) : (
            <span className="text-[11px] text-content-quaternary">
              {t('bim.no_models_yet', { defaultValue: 'No models uploaded yet' })}
            </span>
          )}
          {/* Add model button */}
          <button
            onClick={onUpload}
            className="flex items-center justify-center shrink-0 w-16 h-16 rounded-xl border-2 border-dashed border-border-medium hover:border-oe-blue/50 hover:bg-oe-blue/5 transition-all group"
            title={t('bim.upload_model', { defaultValue: 'Upload model' })}
            aria-label={t('bim.upload_model', { defaultValue: 'Upload model' })}
          >
            <Plus size={20} className="text-content-quaternary group-hover:text-oe-blue transition-colors" />
          </button>
        </div>
      </div>
    </div>
  );
}

function ModelCard({ model, isActive, onClick, onDelete }: {
  model: BIMModelData; isActive: boolean; onClick: () => void; onDelete?: () => void;
}) {
  const { t } = useTranslation();
  const fmt = (model.model_format || model.format || '').toUpperCase();
  const isError = model.status === 'error' || model.status === 'needs_converter';
  const isProcessing = model.status === 'processing';

  const statusDot = model.status === 'ready'
    ? 'bg-emerald-500'
    : isProcessing
      ? 'bg-amber-400 animate-pulse'
      : isError
        ? 'bg-red-400'
        : 'bg-gray-400';

  const statusLabel = model.status === 'ready'
    ? t('bim.status_ready', { defaultValue: 'Ready' })
    : model.status === 'needs_converter'
      ? t('bim.status_needs_converter', { defaultValue: 'Needs Converter' })
      : model.status === 'processing'
        ? t('bim.status_processing', { defaultValue: 'Processing' })
        : model.status === 'error'
          ? t('bim.status_error', { defaultValue: 'Error' })
          : model.status;

  return (
    <button
      onClick={onClick}
      className={`group relative shrink-0 w-52 text-start rounded-xl border-2 transition-all duration-200 overflow-hidden ${
        isActive
          ? 'border-oe-blue bg-oe-blue/5 shadow-lg shadow-oe-blue/8 ring-1 ring-oe-blue/20'
          : 'border-transparent bg-surface-primary hover:bg-surface-secondary hover:border-border-light shadow-sm'
      }`}
    >
      {/* Top accent */}
      <div className={`h-[3px] ${isActive ? 'bg-oe-blue' : isError ? 'bg-red-400' : isProcessing ? 'bg-amber-400' : 'bg-emerald-400'}`} />

      {onDelete && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onDelete?.(); } }}
          aria-label={t('bim.delete_model', { defaultValue: 'Delete model' })}
          className="absolute top-2.5 end-2 p-1 rounded-md text-content-quaternary hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-all z-10"
        >
          <Trash2 size={11} />
        </button>
      )}

      <div className="p-3 space-y-2">
        <div className="flex items-center gap-2.5">
          <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
            isActive ? 'bg-oe-blue/10' : 'bg-surface-secondary'
          }`}>
            <Cuboid size={15} className={isActive ? 'text-oe-blue' : 'text-content-tertiary'} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-content-primary truncate">{model.name}</p>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
              <span className="text-[10px] text-content-tertiary">{statusLabel}</span>
              {fmt && (
                <>
                  <span className="text-content-quaternary">·</span>
                  <span className="text-[10px] text-content-quaternary font-mono">{fmt}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between text-[10px]">
          <div className="flex items-center gap-2 text-content-quaternary tabular-nums">
            {isProcessing && (model.element_count ?? 0) === 0 ? (
              <span className="inline-block w-16 h-3 rounded bg-surface-tertiary animate-pulse" />
            ) : (
              <>
                <span>{t('bim.element_count', { defaultValue: '{{count}} elements', count: model.element_count ?? 0 })}</span>
                {(model.storey_count ?? 0) > 0 && (
                  <>
                    <span className="text-content-quaternary">·</span>
                    <span>{t('bim.storey_count', { defaultValue: '{{count}} levels', count: model.storey_count })}</span>
                  </>
                )}
              </>
            )}
          </div>
          {model.created_at && (
            <span className="text-content-quaternary">
              {new Date(model.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

/* ── Upload Panel ────────────────────────────────────────────────────── */

/** State used by UploadPanel to remember an upload that was deferred
 *  because the matching DDC converter was missing.  Once the user
 *  confirms install via `InstallConverterPrompt`, the saved fields
 *  are replayed through `uploadCADFile` without a second file pick. */
interface InstallPromptState {
  open: boolean;
  converterId: string;
  fileName: string;
  fileSize: number;
  pendingFile: File;
  pendingProjectId: string;
  pendingName: string;
  pendingDiscipline: string;
}

function UploadPanel({
  projectId,
  onUploadComplete,
  onClose,
  initialAdvancedMode,
  initialModelName,
}: {
  projectId: string;
  onUploadComplete: (modelId: string) => void;
  onClose: () => void;
  initialAdvancedMode?: boolean;
  initialModelName?: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [modelName, setModelName] = useState(initialModelName || '');
  const [discipline, setDiscipline] = useState('architecture');
  const [conversionDepth, setConversionDepth] = useState<'standard' | 'medium' | 'complete'>('standard');
  const [generatePdfSheets, setGeneratePdfSheets] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStage, setUploadStage] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [advancedMode, setAdvancedMode] = useState(initialAdvancedMode || false);
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [geometryFile, setGeometryFile] = useState<File | null>(null);
  const [installPromptState, setInstallPromptState] =
    useState<InstallPromptState | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dataInputRef = useRef<HTMLInputElement>(null);
  const geoInputRef = useRef<HTMLInputElement>(null);
  const addToast = useToastStore((s) => s.addToast);

  useEffect(() => { if (initialModelName) setModelName(initialModelName); }, [initialModelName]);
  useEffect(() => { if (initialAdvancedMode) setAdvancedMode(true); }, [initialAdvancedMode]);

  const handleFileSelect = useCallback((f: File) => {
    const ext = getFileExtension(f.name);
    if (DWG_EXTENSIONS.has(ext)) {
      addToast({
        type: 'info',
        title: t('bim.dwg_redirect_title', { defaultValue: 'DWG files are handled in the DWG Takeoff module' }),
        message: t('bim.dwg_redirect_msg', { defaultValue: 'Redirecting to DWG Takeoff...' }),
      });
      navigate('/dwg-takeoff');
      return;
    }
    if (!CAD_EXTENSIONS.has(ext) && !DATA_EXTENSIONS.has(ext)) { setUploadError(t('bim.upload_unsupported_format', { defaultValue: 'Unsupported file format. Please upload .rvt or .ifc files.' })); return; }
    setFile(f);
    setUploadError(ext === '.rvt' ? t('bim.upload_rvt_note') : null);
    if (!modelName) setModelName(f.name.replace(/\.[^.]+$/, ''));
  }, [modelName, t, addToast, navigate]);

  const resetForm = useCallback(() => {
    setFile(null); setDataFile(null); setGeometryFile(null); setModelName(''); setUploadError(null);
    [fileInputRef, dataInputRef, geoInputRef].forEach((r) => { if (r.current) r.current.value = ''; });
  }, []);

  const startGlobalUpload = useBIMUploadStore((s) => s.startUpload);
  const globalJobs = useBIMUploadStore((s) => s.jobs);
  const activeUploads = useMemo(() => {
    const active: { id: string; fileName: string; status: string; stage: string; progress: number; elementCount: number }[] = [];
    for (const [id, job] of globalJobs) {
      if (job.projectId !== projectId) continue;
      if (job.status === 'uploading' || job.status === 'converting') {
        active.push({ id, fileName: job.fileName, status: job.status, stage: job.stage, progress: job.progress, elementCount: 0 });
      } else if (job.status === 'ready') {
        active.push({ id, fileName: job.fileName, status: 'ready', stage: '', progress: 100, elementCount: job.elementCount });
      }
    }
    return active;
  }, [globalJobs, projectId]);

  const handleUpload = useCallback(async () => {
    if (!projectId) return;
    setUploading(true);
    setUploadError(null);
    setUploadProgress(0);

    try {
      if (advancedMode && dataFile) {
        // Advanced (data) upload — delegate to global store
        const name = modelName || 'Imported';
        startGlobalUpload({
          file: dataFile,
          projectId,
          modelName: name,
          discipline,
          uploadType: 'data',
          geometryFile,
        });
        addToast({
          type: 'info',
          title: t('bim.upload_started_title', { defaultValue: 'Upload started' }),
          message: t('bim.upload_background_msg', {
            defaultValue: 'You can navigate to other pages — the upload will continue in the background.',
          }),
        });
        resetForm();
      } else if (file) {
        const name = modelName || file.name.replace(/\.[^.]+$/, '');
        if (isCADFile(file.name)) {
          // Pre-upload guard: if the dropped file is a format that needs
          // a converter and the converter isn't installed locally, surface
          // the install prompt BEFORE wasting an upload roundtrip.  The
          // query result is cached under `['bim-converters']` so the
          // banner and the prompt pick up the same data.
          const lowerName = file.name.toLowerCase();
          const needsConverterMatch = (
            ['rvt'] as const
          ).find((c) => lowerName.endsWith('.' + c));
          if (needsConverterMatch) {
            try {
              const status = await queryClient.fetchQuery({
                queryKey: ['bim-converters'],
                queryFn: fetchBIMConverters,
                staleTime: 30_000,
              });
              const conv = status.converters.find(
                (c) => c.id === needsConverterMatch,
              );
              if (conv && !conv.installed) {
                setUploading(false);
                setUploadProgress(0);
                setUploadStage('');
                setInstallPromptState({
                  open: true,
                  converterId: needsConverterMatch,
                  fileName: file.name,
                  fileSize: file.size,
                  pendingFile: file,
                  pendingProjectId: projectId,
                  pendingName: name,
                  pendingDiscipline: discipline,
                });
                // Don't proceed to upload — prompt will retry on success.
                return;
              }
            } catch (err) {
              // If the converters endpoint fails, fall through to upload —
              // the backend will preflight-reject and we'll catch it below.
              if (import.meta.env.DEV) console.warn('Converter preflight check failed:', err);
            }
          }

          // Delegate to global store — upload survives navigation.
          startGlobalUpload({
            file,
            projectId,
            modelName: name,
            discipline,
            uploadType: 'cad',
            conversionDepth,
            generatePdfSheets,
          });
          addToast({
            type: 'info',
            title: t('bim.upload_started_title', { defaultValue: 'Upload started' }),
            message: t('bim.upload_background_msg', {
              defaultValue: 'You can navigate to other pages — the upload will continue in the background.',
            }),
          });
          resetForm();
        } else if (isDataFile(file.name)) {
          // Data file upload — delegate to global store
          startGlobalUpload({
            file,
            projectId,
            modelName: name,
            discipline,
            uploadType: 'data',
          });
          addToast({
            type: 'info',
            title: t('bim.upload_started_title', { defaultValue: 'Upload started' }),
            message: t('bim.upload_background_msg', {
              defaultValue: 'You can navigate to other pages — the upload will continue in the background.',
            }),
          });
          resetForm();
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setUploadError(msg);
      setUploadProgress(0);
      addToast({ type: 'error', title: t('bim.upload_failed'), message: msg });
    } finally {
      setUploading(false);
      setUploadStage('');
    }
  }, [
    projectId,
    file,
    advancedMode,
    dataFile,
    geometryFile,
    modelName,
    discipline,
    conversionDepth,
    generatePdfSheets,
    onUploadComplete,
    addToast,
    resetForm,
    queryClient,
    startGlobalUpload,
    t,
  ]);

  /** Replay a deferred upload after the user installs a converter from
   *  the prompt.  Uses the saved `pendingFile` + metadata so the user
   *  never has to pick the file twice.  Now delegates to the global
   *  store so the retry also survives navigation. */
  const retryUploadAfterInstall = useCallback(
    (pending: InstallPromptState) => {
      startGlobalUpload({
        file: pending.pendingFile,
        projectId: pending.pendingProjectId,
        modelName: pending.pendingName,
        discipline: pending.pendingDiscipline,
        uploadType: 'cad',
      });
      addToast({
        type: 'info',
        title: t('bim.upload_started_title', { defaultValue: 'Upload started' }),
        message: t('bim.upload_background_msg', {
          defaultValue: 'You can navigate to other pages — the upload will continue in the background.',
        }),
      });
    },
    [addToast, startGlobalUpload, t],
  );

  const canUpload = advancedMode ? !!dataFile && !uploading : !!file && !uploading;
  const disciplines = [
    { v: 'architecture', l: t('bim.disc_architecture') }, { v: 'structural', l: t('bim.disc_structural') },
    { v: 'mechanical', l: t('bim.disc_mechanical') }, { v: 'electrical', l: t('bim.disc_electrical') },
    { v: 'plumbing', l: t('bim.disc_plumbing') }, { v: 'fire_protection', l: t('bim.disc_fire') },
    { v: 'civil', l: t('bim.disc_civil') }, { v: 'mixed', l: t('bim.disc_mixed') },
  ];

  return (
    <>
    <div className="absolute top-0 end-0 h-full w-[380px] bg-surface-primary/95 backdrop-blur-sm border-s border-border-light shadow-lg z-30 flex flex-col animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-oe-blue/10 flex items-center justify-center">
            <Upload size={16} className="text-oe-blue" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-content-primary">{t('bim.upload_panel_title')}</h2>
            <p className="text-[10px] text-content-quaternary">{t('bim.upload_panel_subtitle')}</p>
          </div>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors" aria-label={t('common.close', { defaultValue: 'Close' })}>
          <X size={16} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {/* Active uploads progress */}
        {activeUploads.length > 0 && (
          <div className="space-y-2">
            {activeUploads.map((job) => (
              <div key={job.id} className={`rounded-xl border p-3 ${job.status === 'ready' ? 'border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/20' : 'border-oe-blue/30 bg-oe-blue/5'}`}>
                <div className="flex items-center gap-2 mb-1.5">
                  {job.status === 'ready' ? (
                    <CheckCircle2 size={14} className="text-green-500 shrink-0" />
                  ) : (
                    <Loader2 size={14} className="text-oe-blue animate-spin shrink-0" />
                  )}
                  <span className="text-xs font-medium text-content-primary truncate">{job.fileName}</span>
                </div>
                {job.status !== 'ready' ? (
                  <>
                    <div className="h-1.5 w-full rounded-full bg-surface-tertiary overflow-hidden">
                      <div className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-500 ease-out" style={{ width: `${job.progress}%` }} />
                    </div>
                    <p className="text-[10px] text-content-tertiary mt-1">{t(job.stage, { defaultValue: 'Processing...' })}</p>
                  </>
                ) : (
                  <p className="text-[10px] text-green-600 dark:text-green-400">
                    {t('bim.upload_complete_count', { defaultValue: '{{count}} elements', count: job.elementCount })}
                  </p>
                )}
              </div>
            ))}
            {activeUploads.some((j) => j.status !== 'ready') && (
              <p className="text-[10px] text-content-tertiary text-center py-1">
                {t('bim.upload_continue_working', {
                  defaultValue: 'Processing in background — you can continue working or upload another file.',
                })}
              </p>
            )}
          </div>
        )}

        {!advancedMode ? (
          <label
            aria-label={t('bim.upload_dropzone_aria', { defaultValue: 'Drop a file here or click to browse' })}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) handleFileSelect(f); }}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
            className={`flex flex-col items-center gap-3 border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
              dragOver ? 'border-oe-blue bg-oe-blue/5' : file ? 'border-oe-blue/40 bg-oe-blue/5' : 'border-border-medium hover:border-oe-blue/50 hover:bg-surface-secondary'
            }`}
          >
            {file ? (
              <>
                <div className="w-10 h-10 rounded-xl bg-oe-blue/10 flex items-center justify-center"><CheckCircle2 size={20} className="text-oe-blue" /></div>
                <p className="text-sm font-medium text-content-primary">{file.name}</p>
                <p className="text-[10px] text-content-quaternary">{formatFileSize(file.size)}</p>
                <button type="button" onClick={(e) => { e.preventDefault(); setFile(null); setUploadError(null); if (fileInputRef.current) fileInputRef.current.value = ''; }} className="text-[10px] text-content-tertiary hover:text-red-500 underline">{t('bim.upload_remove_file')}</button>
              </>
            ) : (
              <>
                <div className="w-12 h-12 rounded-xl bg-surface-secondary border border-border-light flex items-center justify-center"><FileUp size={22} className="text-content-quaternary" /></div>
                <p className="text-sm font-medium text-content-primary">{t('bim.upload_drop_here')}</p>
                <p className="text-[10px] text-content-quaternary">{t('bim.upload_size_hint')}</p>
                <div className="flex items-center gap-1.5 mt-1">
                  <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-oe-blue/10 text-oe-blue border border-oe-blue/20">.rvt</span>
                  <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-oe-blue/10 text-oe-blue border border-oe-blue/20">.ifc</span>
                  <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-surface-tertiary text-content-quaternary">.csv</span>
                  <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-surface-tertiary text-content-quaternary">.xlsx</span>
                </div>
              </>
            )}
            <input ref={fileInputRef} type="file" accept=".rvt,.ifc,.csv,.xlsx,.xls" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileSelect(f); }} />
          </label>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col items-center gap-2 border-2 border-dashed border-border-medium rounded-xl p-4 text-center cursor-pointer hover:border-oe-blue/50 hover:bg-surface-secondary transition-all">
              <Database size={20} className="text-content-quaternary" />
              <span className="text-[11px] font-medium text-content-primary">{t('bim.upload_advanced_element_data')}</span>
              <span className="text-[9px] text-content-quaternary">{t('bim.upload_advanced_element_data_hint')}</span>
              {dataFile && <Badge variant="blue" size="sm">{dataFile.name}</Badge>}
              <input ref={dataInputRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => { setDataFile(e.target.files?.[0] ?? null); if (e.target.files?.[0] && !modelName) setModelName(e.target.files[0].name.replace(/\.\w+$/, '')); }} />
            </label>
            <label className="flex flex-col items-center gap-2 border-2 border-dashed border-border-medium rounded-xl p-4 text-center cursor-pointer hover:border-oe-blue/50 hover:bg-surface-secondary transition-all">
              <FileBox size={20} className="text-content-quaternary" />
              <span className="text-[11px] font-medium text-content-primary">{t('bim.upload_advanced_geometry')}</span>
              <span className="text-[9px] text-content-quaternary">{t('bim.upload_advanced_geometry_hint')}</span>
              {geometryFile && <Badge variant="blue" size="sm">{geometryFile.name}</Badge>}
              <input ref={geoInputRef} type="file" accept=".dae,.glb,.gltf" className="hidden" onChange={(e) => setGeometryFile(e.target.files?.[0] ?? null)} />
            </label>
          </div>
        )}

        <div>
          <label className="block text-[10px] font-semibold text-content-tertiary mb-1.5 uppercase tracking-wider">{t('bim.upload_model_name_label')}</label>
          <input type="text" className="w-full text-sm py-2 px-3 rounded-lg border border-border-light bg-surface-secondary text-content-primary placeholder-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue" placeholder={t('bim.upload_model_name_placeholder')} value={modelName} onChange={(e) => setModelName(e.target.value)} />
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-content-tertiary mb-1.5 uppercase tracking-wider">{t('bim.upload_discipline_label')}</label>
          <select className="w-full text-sm py-2 px-3 rounded-lg border border-border-light bg-surface-secondary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue" value={discipline} onChange={(e) => setDiscipline(e.target.value)}>
            {disciplines.map((d) => <option key={d.v} value={d.v}>{d.l}</option>)}
          </select>
        </div>
        {/* Conversion depth and PDF-sheet export are RVT-only — the options
            control Revit category extraction / sheet export. Hide them for
            IFC uploads where neither applies. */}
        {file && getFileExtension(file.name) === '.rvt' && (
          <>
            <div>
              <label className="block text-[10px] font-semibold text-content-tertiary mb-1.5 uppercase tracking-wider">{t('bim.upload_depth_label', { defaultValue: 'Conversion depth' })}</label>
              <select className="w-full text-sm py-2 px-3 rounded-lg border border-border-light bg-surface-secondary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue" value={conversionDepth} onChange={(e) => setConversionDepth(e.target.value as 'standard' | 'medium' | 'complete')}>
                <option value="standard">{t('bim.upload_depth_standard', { defaultValue: 'Standard · main categories (fast)' })}</option>
                <option value="medium">{t('bim.upload_depth_medium', { defaultValue: 'Medium · extended categories (balanced)' })}</option>
                <option value="complete">{t('bim.upload_depth_complete', { defaultValue: 'Complete · all categories (slow)' })}</option>
              </select>
              <p className="mt-1 text-[10px] text-content-quaternary leading-relaxed">{t('bim.upload_depth_help', { defaultValue: 'Controls how many Revit categories are extracted. Element IDs and full properties are always preserved.' })}</p>
            </div>
            <div>
              <label className="flex items-start gap-2 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={generatePdfSheets}
                  onChange={(e) => setGeneratePdfSheets(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-border-medium text-oe-blue focus:ring-1 focus:ring-oe-blue cursor-pointer"
                />
                <div className="flex-1 min-w-0">
                  <span className="block text-[11px] font-medium text-content-primary group-hover:text-oe-blue transition-colors">
                    {t('bim.upload_generate_pdf_label', { defaultValue: 'Also export existing project sheets as PDF (background)' })}
                  </span>
                  <span className="block text-[10px] text-content-quaternary leading-relaxed mt-0.5">
                    {t('bim.upload_generate_pdf_help', { defaultValue: 'Exports the sheets the designer prepared inside the model as a single PDF into Documents. Runs after the model is ready — upload is not delayed.' })}
                  </span>
                </div>
              </label>
            </div>
          </>
        )}

        {uploading && (
          <div className="space-y-2">
            <div className="flex justify-between text-[11px]"><span className="text-content-secondary">{uploadStage}</span><span className="text-content-quaternary tabular-nums">{uploadProgress}%</span></div>
            <div className="h-1.5 w-full rounded-full bg-surface-tertiary overflow-hidden"><div className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-300" style={{ width: `${uploadProgress}%` }} /></div>
          </div>
        )}
        {uploadError && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800">
            <AlertCircle size={14} className="text-red-500 mt-0.5 shrink-0" />
            <p className="text-[11px] text-red-700 dark:text-red-300">{uploadError}</p>
          </div>
        )}
        <button type="button" onClick={() => { setAdvancedMode((p) => !p); setFile(null); setDataFile(null); setGeometryFile(null); }} className="flex items-center gap-1.5 text-[11px] text-content-tertiary hover:text-content-secondary transition-colors">
          {advancedMode ? <ChevronUp size={12} /> : <ChevronRight size={12} />}
          {advancedMode ? t('bim.upload_simple_mode_toggle') : t('bim.upload_advanced_mode_toggle')}
        </button>
      </div>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border-light">
        <button onClick={handleUpload} disabled={!canUpload} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-30 disabled:cursor-not-allowed bg-oe-blue text-white hover:bg-oe-blue-dark active:scale-[0.98] shadow-sm hover:shadow-md">
          {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
          {uploading ? t('bim.uploading') : t('bim.upload_panel_title')}
        </button>
      </div>
    </div>

    {/* Install-converter prompt — shown when a native CAD upload was
        deferred by the pre-upload guard or rejected by the backend
        preflight.  On success it replays the saved upload without a
        second file-picker roundtrip. */}
    {installPromptState && (
      <InstallConverterPrompt
        open={installPromptState.open}
        converterId={installPromptState.converterId}
        fileName={installPromptState.fileName}
        fileSize={installPromptState.fileSize}
        onClose={() => setInstallPromptState(null)}
        onInstalledAndRetry={() => {
          const pending = installPromptState;
          setInstallPromptState(null);
          void retryUploadAfterInstall(pending);
        }}
      />
    )}
    </>
  );
}

/* ── Non-Ready Model Overlay ─────────────────────────────────────────── */

function NonReadyOverlay({ model, onUploadConverted, onDelete }: {
  model: BIMModelData | null; onUploadConverted: () => void; onDelete: () => void;
}) {
  const { t } = useTranslation();

  // model is null while the models query is still hydrating after a fresh
  // upload / deep link — render a lightweight "loading" overlay so we don't
  // flash the empty viewer or trip the elements query into an error state.
  if (!model) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-surface-secondary" role="status">
        <div className="text-center max-w-sm px-6">
          <div className="mx-auto w-20 h-20 rounded-2xl bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 flex items-center justify-center mb-5">
            <Loader2 size={32} className="text-blue-500 animate-spin" />
          </div>
          <h2 className="text-lg font-bold text-content-primary mb-2">
            {t('bim.overlay_loading_model_title', { defaultValue: 'Loading model…' })}
          </h2>
          <p className="text-sm text-content-secondary">
            {t('bim.overlay_loading_model_desc', { defaultValue: 'Fetching the model record. This usually takes only a moment.' })}
          </p>
        </div>
      </div>
    );
  }

  const fmt = (model.model_format || model.format || '').toUpperCase();
  const isProcessing = model.status === 'processing';

  const configs = {
    processing: { icon: <Loader2 size={32} className="text-blue-500 animate-spin" />, bg: 'bg-blue-50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-800', title: t('bim.overlay_processing_title'), desc: t('bim.overlay_processing_desc', { format: fmt }) },
    needs_converter: { icon: <AlertTriangle size={32} className="text-amber-500" />, bg: 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800', title: t('bim.overlay_needs_converter_title'), desc: t('bim.overlay_needs_converter_desc', { format: fmt }) },
    error: { icon: <AlertCircle size={32} className="text-red-500" />, bg: 'bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800', title: t('bim.overlay_error_title'), desc: t('bim.overlay_error_desc') },
  };
  const c = configs[model.status as keyof typeof configs] ?? configs.error;

  return (
    <div className="flex flex-col items-center justify-center h-full bg-surface-secondary" role={isProcessing ? 'status' : 'alert'}>
      <div className="text-center max-w-md px-6 w-full">
        <div className={`mx-auto w-20 h-20 rounded-2xl ${c.bg} border flex items-center justify-center mb-5`}>{c.icon}</div>
        <h2 className="text-lg font-bold text-content-primary mb-2">{c.title}</h2>
        <p className="text-sm text-content-secondary mb-2">{c.desc}</p>
        <p className="text-[11px] text-content-quaternary mb-6">{model.name}{model.file_size ? ` · ${formatFileSize(model.file_size)}` : ''}</p>

        {isProcessing && (
          <div className="mx-auto max-w-xs mb-6">
            <style>{`
              @keyframes oeBimIndeterminate {
                0% { transform: translateX(-100%); }
                100% { transform: translateX(400%); }
              }
            `}</style>
            <div className="h-1.5 w-full rounded-full bg-blue-100 dark:bg-blue-900/30 overflow-hidden relative">
              <div
                className="absolute top-0 left-0 h-full w-1/4 rounded-full bg-gradient-to-r from-blue-400 to-blue-600"
                style={{ animation: 'oeBimIndeterminate 1.6s ease-in-out infinite' }}
              />
            </div>
            <p className="text-[11px] text-content-tertiary mt-2.5">
              {t('bim.overlay_processing_hint', {
                defaultValue: 'Backend is converting the file. This page will update automatically when ready — feel free to navigate away.',
              })}
            </p>
          </div>
        )}

        {!isProcessing && (
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <button onClick={onUploadConverted} aria-label={t('bim.overlay_upload_converted_btn')} className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-oe-blue text-white text-sm font-semibold hover:bg-oe-blue-dark transition-colors shadow-sm">
              <UploadCloud size={15} /> {t('bim.overlay_upload_converted_btn')}
            </button>
            <button onClick={onDelete} aria-label={t('bim.overlay_delete_btn')} className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-surface-primary border border-border-light text-content-secondary text-sm font-medium hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors">
              <Trash2 size={15} /> {t('bim.overlay_delete_btn')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Landing Page ────────────────────────────────────────────────────── */

function LandingPage({ projectId, onUploadComplete: _onUploadComplete, breadcrumbItems, models: landingModels, onSelectModel, onDeleteModel }: {
  projectId: string; onUploadComplete: (modelId: string) => void; breadcrumbItems: { label: string; to?: string }[];
  models?: BIMModelData[];
  onSelectModel?: (id: string) => void;
  onDeleteModel?: (id: string, name: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [modelName, setModelName] = useState('');
  const [conversionDepth, setConversionDepth] = useState<'standard' | 'medium' | 'complete'>('standard');
  const [generatePdfSheets, setGeneratePdfSheets] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const addToast = useToastStore((s) => s.addToast);
  const startGlobalUpload = useBIMUploadStore((s) => s.startUpload);
  const globalJobs = useBIMUploadStore((s) => s.jobs);
  const activeUploads = useMemo(() => {
    const active: { id: string; fileName: string; status: string; stage: string; progress: number; elementCount: number }[] = [];
    for (const [id, job] of globalJobs) {
      if (job.projectId !== projectId) continue;
      if (job.status === 'uploading' || job.status === 'converting') {
        active.push({ id, fileName: job.fileName, status: job.status, stage: job.stage, progress: job.progress, elementCount: 0 });
      } else if (job.status === 'ready') {
        active.push({ id, fileName: job.fileName, status: 'ready', stage: '', progress: 100, elementCount: job.elementCount });
      }
    }
    return active;
  }, [globalJobs, projectId]);

  const resetForm = useCallback(() => {
    setFile(null);
    setModelName('');
    setUploadError(null);
    setUploadProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const handleUpload = useCallback(async () => {
    if (!file || !projectId) return;
    setUploading(true); setUploadError(null);
    try {
      const name = modelName || file.name.replace(/\.[^.]+$/, '');
      const uploadType = isCADFile(file.name) ? 'cad' as const : 'data' as const;
      startGlobalUpload({
        file,
        projectId,
        modelName: name,
        discipline: 'architecture',
        uploadType,
        // Both options only have an effect for native CAD uploads; the
        // store ignores them for the CSV/XLSX path.
        conversionDepth: uploadType === 'cad' ? conversionDepth : undefined,
        generatePdfSheets: uploadType === 'cad' ? generatePdfSheets : false,
      });
      addToast({
        type: 'info',
        title: t('bim.upload_started_title', { defaultValue: 'Upload started' }),
        message: t('bim.upload_background_msg', {
          defaultValue: 'You can navigate to other pages — the upload will continue in the background.',
        }),
      });
      resetForm();
    } catch (err) { setUploadError(err instanceof Error ? err.message : String(err)); }
    finally { setUploading(false); }
  }, [file, projectId, modelName, conversionDepth, generatePdfSheets, startGlobalUpload, addToast, t, resetForm]);

  const features = [
    { icon: Eye, color: 'bg-blue-50 dark:bg-blue-950/20 border-blue-100 dark:border-blue-800', ic: 'text-blue-500', title: t('bim.landing_feat_3d_title'), desc: t('bim.landing_feat_3d_desc') },
    { icon: Layers, color: 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-100 dark:border-emerald-800', ic: 'text-emerald-500', title: t('bim.landing_feat_extract_title'), desc: t('bim.landing_feat_extract_desc') },
    { icon: Link2, color: 'bg-violet-50 dark:bg-violet-950/20 border-violet-100 dark:border-violet-800', ic: 'text-violet-500', title: t('bim.landing_feat_boq_title'), desc: t('bim.landing_feat_boq_desc') },
    { icon: Ruler, color: 'bg-orange-50 dark:bg-orange-950/20 border-orange-100 dark:border-orange-800', ic: 'text-orange-500', title: t('bim.landing_feat_qty_title'), desc: t('bim.landing_feat_qty_desc') },
    { icon: Building2, color: 'bg-pink-50 dark:bg-pink-950/20 border-pink-100 dark:border-pink-800', ic: 'text-pink-500', title: t('bim.landing_feat_compare_title'), desc: t('bim.landing_feat_compare_desc') },
    { icon: Globe2, color: 'bg-cyan-50 dark:bg-cyan-950/20 border-cyan-100 dark:border-cyan-800', ic: 'text-cyan-500', title: t('bim.landing_feat_format_title'), desc: t('bim.landing_feat_format_desc') },
  ];

  return (
    <div className="flex flex-col -mx-4 sm:-mx-7 -mt-6 -mb-6 border-s border-border-light" style={{ height: 'calc(100vh - 56px)' }}>
      <div className="px-6 pt-4 pb-3 border-b border-border-light"><Breadcrumb items={breadcrumbItems} /></div>
      {/* Soft modern background — calm base gradient plus two muted
          blurred colour blobs (top-left blue, bottom-right violet) for
          subtle depth.  Restrained on purpose: enough colour to feel
          "designed" without competing with the foreground content. */}
      <div className="relative flex-1 overflow-hidden bg-gradient-to-br from-slate-50 via-white to-blue-50/30 dark:from-gray-950 dark:via-gray-900 dark:to-slate-900">
        {/* Decorative cubes — tiled SVG pattern.  Large sparse tile
            (960×720) so cubes feel airy, not cluttered.  Stroke + fill
            both near-invisible (0.015 / 0.12) so the layer is pure
            texture.  Container uses `overflow-hidden` so the scrollbar
            the user was seeing is gone — the landing content scrolls
            inside its own inner area instead. */}
        <svg
          aria-hidden
          className="pointer-events-none absolute inset-0 w-full h-full z-0 text-slate-500 dark:text-slate-300"
          preserveAspectRatio="xMidYMid slice"
        >
          <defs>
            <linearGradient id="bimCubeFadeTop" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.012" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0.003" />
            </linearGradient>
            <linearGradient id="bimCubeFadeLeft" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.009" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0.002" />
            </linearGradient>
            <linearGradient id="bimCubeFadeRight" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0.002" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0.008" />
            </linearGradient>
            <symbol id="bimIsoCube" viewBox="-100 -120 200 240">
              <polygon points="0,-100 90,-50 0,0 -90,-50" fill="url(#bimCubeFadeTop)" stroke="currentColor" strokeWidth="0.5" strokeOpacity="0.12" />
              <polygon points="-90,-50 0,0 0,100 -90,50" fill="url(#bimCubeFadeLeft)" stroke="currentColor" strokeWidth="0.5" strokeOpacity="0.12" />
              <polygon points="90,-50 0,0 0,100 90,50" fill="url(#bimCubeFadeRight)" stroke="currentColor" strokeWidth="0.5" strokeOpacity="0.12" />
              <line x1="0" y1="-100" x2="0" y2="0" stroke="currentColor" strokeWidth="0.25" strokeOpacity="0.1" />
            </symbol>
            {/* Smaller denser tile — many small cubes so the page
                reads as a subtle isometric grid rather than a few
                big, heavy shapes.  520×400, cubes at scale ≈0.28-0.36. */}
            <pattern id="bimCubeTile" x="0" y="0" width="520" height="400" patternUnits="userSpaceOnUse">
              <g transform="translate(90 120) scale(0.32)"><use href="#bimIsoCube" /></g>
              <g transform="translate(270 90) scale(0.28)"><use href="#bimIsoCube" /></g>
              <g transform="translate(430 160) scale(0.3)"><use href="#bimIsoCube" /></g>
              <g transform="translate(180 270) scale(0.36)"><use href="#bimIsoCube" /></g>
              <g transform="translate(380 330) scale(0.26)"><use href="#bimIsoCube" /></g>
              <g transform="translate(60 330)" opacity="0.1" stroke="currentColor" strokeWidth="0.4" fill="none">
                <polygon points="0,-32 27,-16 0,0 -27,-16" />
                <polygon points="-27,-16 0,0 0,32 -27,16" />
                <polygon points="27,-16 0,0 0,32 27,16" strokeDasharray="3 3" />
              </g>
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#bimCubeTile)" />
        </svg>
        {/* Content wrapper — compact layout + `overflow-y-auto` with
            hidden scrollbar means scrolling still works on short
            viewports but the scrollbar is invisible.  Tight padding
            below so the typical 1080p viewport fits everything without
            needing to scroll. */}
        <div className="absolute inset-0 overflow-y-auto overflow-x-hidden scrollbar-none z-10">
        <div aria-hidden className="pointer-events-none absolute -top-32 -left-32 w-[520px] h-[520px] rounded-full bg-blue-200/25 dark:bg-blue-500/8 blur-[140px]" />
        <div aria-hidden className="pointer-events-none absolute -bottom-32 -right-32 w-[520px] h-[520px] rounded-full bg-violet-200/20 dark:bg-violet-500/8 blur-[140px]" />
        <div className="relative max-w-7xl mx-auto px-6 pt-6 pb-4">

          {/* Row 1: Upload card (left) + Hero text (right) */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-stretch mb-8">

            {/* LEFT — Upload card */}
            <div className="flex flex-col">
              <div className="rounded-2xl bg-white dark:bg-gray-800/60 border border-border-light shadow-lg shadow-black/5 dark:shadow-black/20 p-6 flex flex-col h-full">
                <label
                  aria-label={t('bim.landing_dropzone_aria', { defaultValue: 'Drop a BIM model file here or click to browse. Supported formats: .rvt, .ifc, .csv, .xlsx' })}
                  onDrop={(e) => {
                    e.preventDefault();
                    const f = e.dataTransfer.files?.[0];
                    if (f) {
                      const ext = getFileExtension(f.name);
                      if (DWG_EXTENSIONS.has(ext)) {
                        addToast({ type: 'info', title: t('bim.dwg_redirect_title', { defaultValue: 'DWG files are handled in the DWG Takeoff module' }), message: t('bim.dwg_redirect_msg', { defaultValue: 'Redirecting to DWG Takeoff...' }) });
                        navigate('/dwg-takeoff');
                        return;
                      }
                      if (!CAD_EXTENSIONS.has(ext) && !DATA_EXTENSIONS.has(ext)) {
                        addToast({ type: 'error', title: t('bim.upload_unsupported_format', { defaultValue: 'Unsupported file format. Please upload .rvt or .ifc files.' }) });
                        return;
                      }
                      setFile(f);
                      if (!modelName) setModelName(f.name.replace(/\.[^.]+$/, ''));
                    }
                  }}
                  onDragOver={(e) => e.preventDefault()}
                  className={`group/drop flex flex-col items-center justify-center gap-4 rounded-xl p-10 text-center cursor-pointer transition-all flex-1 ${
                    file
                      ? 'border-2 border-oe-blue bg-oe-blue/5'
                      : 'border-2 border-dashed border-border-medium bg-gradient-to-br from-blue-50/60 via-white to-violet-50/40 dark:from-blue-950/20 dark:via-gray-800/40 dark:to-violet-950/20 hover:border-oe-blue/50 hover:shadow-md'
                  }`}
                >
                  {file ? (
                    <>
                      <div className="w-14 h-14 rounded-2xl bg-oe-blue/10 flex items-center justify-center"><CheckCircle2 size={26} className="text-oe-blue" /></div>
                      <p className="text-sm font-semibold text-content-primary">{file.name}</p>
                      <p className="text-xs text-content-quaternary">{formatFileSize(file.size)}</p>
                    </>
                  ) : (
                    <>
                      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-oe-blue/10 to-violet-500/10 flex items-center justify-center group-hover/drop:scale-110 transition-transform">
                        <FileUp size={26} className="text-oe-blue" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-content-primary">{t('bim.landing_drop_here')}</p>
                        <p className="text-xs text-content-tertiary mt-1">{t('bim.landing_size_hint')}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono px-2 py-1 rounded-md bg-oe-blue/8 text-oe-blue border border-oe-blue/15 font-semibold">.rvt</span>
                        <span className="text-[10px] font-mono px-2 py-1 rounded-md bg-oe-blue/8 text-oe-blue border border-oe-blue/15 font-semibold">.ifc</span>
                      </div>
                      <p className="text-[10px] text-content-quaternary leading-relaxed mt-1 text-center">
                        Revit 2015–2026 &middot; IFC 2x3, 4.0, 4.1, 4.3
                      </p>
                    </>
                  )}
                  <input ref={fileInputRef} type="file" accept=".rvt,.ifc" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); if (!modelName) setModelName(f.name.replace(/\.[^.]+$/, '')); } }} />
                </label>
                {file && (
                  <div className="mt-4 space-y-3">
                    <input type="text" className="w-full text-sm py-2.5 px-4 rounded-xl border border-border-light bg-surface-secondary text-content-primary placeholder-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/30" placeholder={t('bim.model_name')} value={modelName} onChange={(e) => setModelName(e.target.value)} />
                    {/* RVT-only options — Revit category extraction depth
                        and sheet-to-PDF export don't apply to IFC uploads. */}
                    {getFileExtension(file.name) === '.rvt' && (
                      <>
                        <div>
                          <label className="block text-[10px] font-semibold text-content-tertiary mb-1.5 uppercase tracking-wider">
                            {t('bim.upload_depth_label', { defaultValue: 'Conversion depth' })}
                          </label>
                          <select
                            className="w-full text-sm py-2.5 px-4 rounded-xl border border-border-light bg-surface-secondary text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                            value={conversionDepth}
                            onChange={(e) => setConversionDepth(e.target.value as 'standard' | 'medium' | 'complete')}
                          >
                            <option value="standard">{t('bim.upload_depth_standard', { defaultValue: 'Standard · main categories (fast)' })}</option>
                            <option value="medium">{t('bim.upload_depth_medium', { defaultValue: 'Medium · extended categories (balanced)' })}</option>
                            <option value="complete">{t('bim.upload_depth_complete', { defaultValue: 'Complete · all categories (slow)' })}</option>
                          </select>
                          <p className="mt-1 text-[10px] text-content-quaternary leading-relaxed">
                            {t('bim.upload_depth_help', { defaultValue: 'Controls how many Revit categories are extracted. Element IDs and full properties are always preserved.' })}
                          </p>
                        </div>
                        <label className="flex items-start gap-2 cursor-pointer group">
                          <input
                            type="checkbox"
                            checked={generatePdfSheets}
                            onChange={(e) => setGeneratePdfSheets(e.target.checked)}
                            className="mt-0.5 h-4 w-4 rounded border-border-medium text-oe-blue focus:ring-1 focus:ring-oe-blue cursor-pointer"
                          />
                          <div className="flex-1 min-w-0">
                            <span className="block text-[11px] font-medium text-content-primary group-hover:text-oe-blue transition-colors">
                              {t('bim.upload_generate_pdf_label', { defaultValue: 'Also export existing project sheets as PDF (background)' })}
                            </span>
                            <span className="block text-[10px] text-content-quaternary leading-relaxed mt-0.5">
                              {t('bim.upload_generate_pdf_help', { defaultValue: 'Exports the sheets the designer prepared inside the model as a single PDF into Documents. Runs after the model is ready — upload is not delayed.' })}
                            </span>
                          </div>
                        </label>
                      </>
                    )}
                    {uploading && <div className="h-1.5 rounded-full bg-surface-tertiary overflow-hidden"><div className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-300" style={{ width: `${uploadProgress}%` }} /></div>}
                    {uploadError && <p className="text-xs text-red-500">{uploadError}</p>}
                    <button onClick={handleUpload} disabled={uploading} className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-50 bg-oe-blue text-white hover:bg-oe-blue-dark active:scale-[0.98] shadow-md hover:shadow-lg">
                      {uploading ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
                      {uploading ? t('bim.landing_processing') : t('bim.landing_upload_process')}
                    </button>
                  </div>
                )}
              </div>

              {/* Active upload progress */}
              {activeUploads.length > 0 && (
                <div className="mt-3 space-y-2">
                  {activeUploads.map((job) => (
                    <div key={job.id} className={`rounded-xl border p-3.5 ${job.status === 'ready' ? 'border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/20' : 'border-oe-blue/30 bg-white dark:bg-gray-900 shadow-sm'}`}>
                      <div className="flex items-center gap-2 mb-1.5">
                        {job.status === 'ready' ? <CheckCircle2 size={14} className="text-green-500 shrink-0" /> : <Loader2 size={14} className="text-oe-blue animate-spin shrink-0" />}
                        <span className="text-xs font-medium text-content-primary truncate">{job.fileName}</span>
                      </div>
                      {job.status !== 'ready' ? (
                        <>
                          <div className="h-1.5 w-full rounded-full bg-surface-tertiary overflow-hidden"><div className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-500" style={{ width: `${job.progress}%` }} /></div>
                          <p className="text-[11px] text-content-tertiary mt-1">{t(job.stage, { defaultValue: 'Processing...' })}</p>
                        </>
                      ) : (
                        <p className="text-[11px] text-green-600 dark:text-green-400">{t('bim.upload_complete_count', { defaultValue: '{{count}} elements', count: job.elementCount })}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* RIGHT — Hero text + local-processing badge (chip styled to
                match /dwg-takeoff so the trust signal reads identically
                across CAD modules). The decorative animation was
                removed to keep the page calm and let the modern mesh
                background carry the visual weight. */}
            <div className="flex flex-col justify-center gap-4">
              <div>
                <h1 className="text-2xl font-bold text-content-primary tracking-tight leading-tight">{t('bim.landing_hero_title')}</h1>
                <p className="text-base text-content-secondary mt-3 leading-relaxed">
                  {t('bim.landing_hero_subtitle')}
                </p>
                <p className="text-xs text-content-tertiary mt-3 leading-relaxed">
                  {t('bim.landing_formats_detailed', { defaultValue: 'Revit 2015\u20132026 (.rvt) \u00B7 IFC 2x3, 4.0, 4.1, 4.3 (.ifc) \u00B7 CSV \u00B7 Excel. DWG \u2192 DWG Takeoff.' })}
                </p>
                <div className="mt-4 flex items-center justify-start">
                  <div className="inline-flex flex-wrap items-center gap-2 px-4 py-2 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                    <ShieldCheck size={14} className="text-emerald-500 dark:text-emerald-400 shrink-0" />
                    <span className="text-xs text-emerald-700 dark:text-emerald-300/90 font-medium">
                      {t('common.local_processing', { defaultValue: '100% Local Processing \u00B7 Your files never leave your computer' })}
                    </span>
                    <span className="text-[10px] text-emerald-500/40">|</span>
                    <a
                      href="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[10px] text-emerald-600/80 dark:text-emerald-400/70 hover:text-emerald-700 dark:hover:text-emerald-300 hover:underline whitespace-nowrap"
                    >
                      {t('common.powered_by_cad2data', { defaultValue: 'Powered by DDC cad2data' })}
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Row 2: Feature cards — 3x2 grid */}
          <div>
            <h2 className="text-xs font-bold text-content-tertiary uppercase tracking-widest mb-3">
              {t('bim.landing_what_you_get', { defaultValue: 'What you get' })}
            </h2>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
              {features.map((f, i) => (
                <div key={i} className="flex items-start gap-3 rounded-xl p-4 bg-white dark:bg-gray-800/40 border border-border-light/60 hover:border-border-light hover:shadow-sm transition-all">
                  <div className={`w-8 h-8 rounded-lg ${f.color} border flex items-center justify-center shrink-0`}><f.icon size={15} className={f.ic} /></div>
                  <div className="min-w-0">
                    <h3 className="text-xs font-semibold text-content-primary leading-tight">{f.title}</h3>
                    <p className="text-[11px] text-content-tertiary leading-snug mt-1">{f.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Row 3 removed — models now in fixed bottom filmstrip only */}
          {false as boolean && (
            <div className="hidden">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {(landingModels ?? []).map((m) => {
                  const fmt = (m.model_format || m.format || '').toUpperCase();
                  const isError = m.status === 'error' || m.status === 'needs_converter';
                  const isProcessing = m.status === 'processing';
                  const isReady = m.status === 'ready';

                  const statusColor = isReady
                    ? 'bg-emerald-500'
                    : isProcessing
                      ? 'bg-amber-400 animate-pulse'
                      : isError
                        ? 'bg-red-400'
                        : 'bg-gray-400';

                  const statusLabel = isReady
                    ? t('bim.status_ready', { defaultValue: 'Ready' })
                    : m.status === 'needs_converter'
                      ? t('bim.status_needs_converter', { defaultValue: 'Needs Converter' })
                      : isProcessing
                        ? t('bim.status_processing', { defaultValue: 'Processing' })
                        : isError
                          ? t('bim.status_error', { defaultValue: 'Error' })
                          : m.status;

                  const statusTextColor = isReady
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : isProcessing
                      ? 'text-amber-600 dark:text-amber-400'
                      : isError
                        ? 'text-red-600 dark:text-red-400'
                        : 'text-content-tertiary';

                  const borderAccent = isReady
                    ? 'border-l-emerald-400'
                    : isProcessing
                      ? 'border-l-amber-400'
                      : isError
                        ? 'border-l-red-400'
                        : 'border-l-gray-300 dark:border-l-gray-600';

                  const timeAgo = m.created_at ? (() => {
                    const diff = Date.now() - new Date(m.created_at!).getTime();
                    const mins = Math.floor(diff / 60000);
                    if (mins < 1) return t('bim.just_now', { defaultValue: 'just now' });
                    if (mins < 60) return t('bim.time_mins_ago', { defaultValue: '{{count}}m ago', count: mins });
                    const hrs = Math.floor(mins / 60);
                    if (hrs < 24) return t('bim.time_hours_ago', { defaultValue: '{{count}}h ago', count: hrs });
                    const days = Math.floor(hrs / 24);
                    return t('bim.time_days_ago', { defaultValue: '{{count}}d ago', count: days });
                  })() : '';

                  return (
                    <button
                      key={m.id}
                      onClick={() => onSelectModel?.(m.id)}
                      className={`group relative w-full text-left rounded-xl border border-border-light border-l-[3px] ${borderAccent} bg-white dark:bg-gray-800/50 p-4 hover:shadow-lg hover:border-oe-blue/30 hover:-translate-y-0.5 transition-all duration-200 cursor-pointer`}
                    >
                      {/* Delete button — visible on hover */}
                      {onDeleteModel && (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); onDeleteModel(m.id, m.name); }}
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onDeleteModel(m.id, m.name); } }}
                          aria-label={t('bim.delete_model', { defaultValue: 'Delete model' })}
                          className="absolute top-3 end-3 p-1.5 rounded-lg text-content-quaternary hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-all z-10"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}

                      {/* Card content */}
                      <div className="flex items-start gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-oe-blue/10 to-blue-50 dark:to-blue-950/20 border border-oe-blue/15 flex items-center justify-center shrink-0">
                          <Cuboid size={18} className="text-oe-blue" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold text-content-primary truncate pe-6" title={m.name}>{m.name}</p>
                          <div className="flex items-center gap-2 mt-1">
                            {fmt && (
                              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-md bg-oe-blue/8 text-oe-blue border border-oe-blue/15 font-semibold leading-none">
                                .{fmt.toLowerCase()}
                              </span>
                            )}
                            <div className="flex items-center gap-1">
                              <span className={`w-1.5 h-1.5 rounded-full ${statusColor}`} />
                              <span className={`text-[10px] font-medium ${statusTextColor}`}>{statusLabel}</span>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Footer stats */}
                      <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-border-light/60">
                        <div className="flex items-center gap-3 text-[11px] text-content-quaternary tabular-nums">
                          {isProcessing && (m.element_count ?? 0) === 0 ? (
                            <span className="inline-block w-20 h-3 rounded bg-surface-tertiary animate-pulse" />
                          ) : (
                            <>
                              <span className="flex items-center gap-1">
                                <Layers size={11} className="text-content-quaternary" />
                                {t('bim.element_count', { defaultValue: '{{count}} elements', count: m.element_count ?? 0 })}
                              </span>
                              {(m.storey_count ?? 0) > 0 && (
                                <span className="flex items-center gap-1">
                                  <Building2 size={11} className="text-content-quaternary" />
                                  {t('bim.storey_count', { defaultValue: '{{count}} levels', count: m.storey_count })}
                                </span>
                              )}
                            </>
                          )}
                        </div>
                        {timeAgo && (
                          <span className="flex items-center gap-1 text-[10px] text-content-quaternary">
                            <CalendarDays size={10} />
                            {timeAgo}
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

        </div>
        </div>
      </div>

      {/* ── Bottom Filmstrip: Your Models — always visible so the user
           keeps a consistent anchor to switch or upload models.
           Previously guarded by `landingModels.length > 0` which made the
           panel appear on first render then vanish when the LandingPage
           unmounted into the main view.  Keeping it always-rendered with
           an empty-state string removes that flicker. ── */}
      <div className="shrink-0 border-t border-border-light bg-surface-primary">
          <div className="flex items-center px-4 py-1.5">
            <Database size={14} className="text-content-tertiary mr-2 shrink-0" />
            <span className="text-xs font-semibold text-content-primary">
              {t('bim.your_models', { defaultValue: 'Your Models' })}
            </span>
            <span className="text-[11px] text-content-quaternary ml-1.5">({(landingModels ?? []).length})</span>
          </div>
          <div className="flex items-center gap-2.5 px-4 pb-2.5 overflow-x-auto">
            {(!landingModels || landingModels.length === 0) && (
              <span className="text-[11px] text-content-quaternary italic py-1">
                {t('bim.no_models_yet', { defaultValue: 'No models uploaded yet' })}
              </span>
            )}
            {(landingModels ?? []).map((m) => {
              const fmt = (m.model_format || m.format || '').toUpperCase();
              const isReady = m.status === 'ready';
              const isProcessing = m.status === 'processing';
              const isError = m.status === 'error' || m.status === 'needs_converter';
              const statusDot = isReady ? 'bg-emerald-500' : isProcessing ? 'bg-amber-400 animate-pulse' : isError ? 'bg-red-400' : 'bg-gray-400';

              return (
                <button
                  key={m.id}
                  onClick={() => onSelectModel?.(m.id)}
                  className="group relative shrink-0 w-52 text-start rounded-lg border border-border-light bg-surface-secondary hover:bg-surface-tertiary hover:border-oe-blue/30 hover:shadow-md transition-all duration-200 overflow-hidden"
                >
                  {onDeleteModel && (
                    <span
                      role="button"
                      tabIndex={0}
                      onClick={(e) => { e.stopPropagation(); onDeleteModel(m.id, m.name); }}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onDeleteModel(m.id, m.name); } }}
                      className="absolute top-1.5 right-1.5 p-1 rounded text-content-quaternary hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 opacity-0 group-hover:opacity-100 transition-all z-10"
                    >
                      <Trash2 size={11} />
                    </span>
                  )}
                  <div className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5 mb-1">
                      <Cuboid size={12} className="shrink-0 text-content-tertiary" />
                      <span className="text-[11px] font-semibold text-content-primary truncate">{m.name}</span>
                      {fmt && (
                        <span className="text-[9px] font-mono font-bold px-1 py-0.5 rounded bg-oe-blue/8 text-oe-blue border border-oe-blue/15 shrink-0">.{fmt.toLowerCase()}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-content-quaternary">
                      <span className="flex items-center gap-1">
                        <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
                        {isReady ? t('bim.status_ready', { defaultValue: 'Ready' }) : isProcessing ? t('bim.status_processing', { defaultValue: 'Processing' }) : m.status}
                      </span>
                      {(m.element_count ?? 0) > 0 && (
                        <>
                          <span>&middot;</span>
                          <span>{m.element_count} {t('bim.elements', { defaultValue: 'elements' })}</span>
                        </>
                      )}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
    </div>
  );
}

/* ── Main BIM Page ───────────────────────────────────────────────────── */

export function BIMPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { projectId: urlProjectId, modelId: urlModelId } = useParams<{ projectId?: string; modelId?: string }>();
  const contextProjectId = useProjectContextStore((s) => s.activeProjectId);
  const contextProjectName = useProjectContextStore((s) => s.activeProjectName);
  // Server-side fallback: same rationale as /dwg-takeoff. If the user
  // lands on /bim without a URL project param and localStorage was
  // purged (stale-project cleanup), every BIM query fires with an empty
  // projectId and models appear "lost" on reload. Fetch the projects
  // list and use the first as a last resort.
  const { data: projectsList = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Array<{ id: string; name: string }>>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });
  const projectId = urlProjectId || contextProjectId || projectsList[0]?.id || '';
  const { confirm, ...confirmProps } = useConfirm();

  const [activeModelId, setActiveModelId] = useState<string | null>(urlModelId || null);
  const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
  // Full Ctrl+click / Shift+click multi-selection set, fed by the viewer's
  // onSelectionChange. Echoed back to BIMViewer so every selected mesh stays
  // highlighted across renders (parent's `[selectedElementId]` would collapse
  // the highlight to the most recent click only).
  const [multiSelectedIds, setMultiSelectedIds] = useState<string[]>([]);

  // Deep-link auto-select: Cmd+Shift+K global semantic search and the
  // similar-items panel land here with `?element=<element_id>` — pick
  // the matching element as soon as the elements list resolves.  Cleared
  // from the URL after one shot so a refresh doesn't reapply it.
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkElementId = searchParams.get('element');
  const deepLinkDocName = searchParams.get('docName');
  const deepLinkDocId = searchParams.get('docId');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadConvertedName, setUploadConvertedName] = useState<string | null>(null);
  const [showUploadOverride, setShowUploadOverride] = useState<boolean | null>(null);
  const [filterPanelOpen, setFilterPanelOpen] = useState(true);
  // Right-panel visibility lives in the shared BIM viewer store so the
  // keyboard shortcut `S` (RFC 19) can open the Tools tab from anywhere.
  const boqPanelOpen = useBIMViewerStore((s) => s.rightPanelOpen);
  const setBoqPanelOpen = useBIMViewerStore((s) => s.setRightPanelOpen);
  const summaryPanelOpen = useBIMViewerStore((s) => s.summaryPanelOpen);
  const setSummaryPanelOpen = useBIMViewerStore((s) => s.setSummaryPanelOpen);
  const dimensionsVisible = useBIMViewerStore((s) => s.dimensionsVisible);
  const setDimensionsVisible = useBIMViewerStore((s) => s.setDimensionsVisible);
  const assetCardEnabled = useBIMViewerStore((s) => s.assetCardEnabled);
  const setAssetCardEnabled = useBIMViewerStore((s) => s.setAssetCardEnabled);
  const [snapshotsOpen, setSnapshotsOpen] = useState(false);
  const [filterPredicate, setFilterPredicate] = useState<
    ((el: BIMElementData) => boolean) | null
  >(null);
  const [visibleElementCount, setVisibleElementCount] = useState<number | null>(null);
  const [colorByMode, setColorByMode] = useState<
    | 'default'
    | 'storey'
    | 'type'
    | 'validation'
    | 'boq_coverage'
    | 'document_coverage'
    | '5d_cost'
    | '4d_schedule'
  >('default');
  const showBoundingBoxes = false;
  const [isolatedIds, setIsolatedIds] = useState<string[] | null>(null);
  const [meshMatchRatio, setMeshMatchRatio] = useState<number | null>(null);
  /** Elements queued for linking via the AddToBOQ modal. Single element
   *  when the user clicks an element; multiple elements when "quick
   *  takeoff" on a filtered category. */
  const [linkCandidates, setLinkCandidates] = useState<BIMElementData[] | null>(null);
  /** Save-as-group modal state — captures the current filter snapshot. */
  const [saveGroupState, setSaveGroupState] = useState<{
    filterCriteria: BIMGroupFilterCriteria;
    elementIds: string[];
  } | null>(null);
  /** Inline create-from-element modal targets.  Each one stores the
   *  elements the user wants to link from — typically [singleClickedElement]. */
  const [createTaskFor, setCreateTaskFor] = useState<BIMElementData[] | null>(null);
  const [linkDocumentFor, setLinkDocumentFor] = useState<BIMElementData[] | null>(null);
  const [linkActivityFor, setLinkActivityFor] = useState<BIMElementData[] | null>(null);
  const [linkRequirementFor, setLinkRequirementFor] = useState<
    BIMElementData[] | null
  >(null);
  const addToast = useToastStore((s) => s.addToast);

  /* ── Cross-highlight bridge to BOQ editor ───────────────────────── */
  const highlightedBIMElementIds = useBIMLinkSelectionStore((s) => s.highlightedBIMElementIds);
  const setBIMSelection = useBIMLinkSelectionStore((s) => s.setBIMSelection);
  const clearBIMLinkSelection = useBIMLinkSelectionStore((s) => s.clear);

  const modelsQuery = useQuery({ queryKey: ['bim-models', projectId], queryFn: () => fetchBIMModels(projectId), enabled: !!projectId, staleTime: 5 * 60_000 });
  const models = modelsQuery.data?.items ?? [];
  const hasModels = models.length > 0;
  const showFullPageUpload = showUploadOverride !== null ? showUploadOverride : !hasModels;

  useEffect(() => { if (hasModels && showUploadOverride === false) setShowUploadOverride(null); }, [hasModels, showUploadOverride]);

  /* ── Deep-link from Documents page ──────────────────────────────────────
   * When navigating from /documents with ?docName= or ?docId=, try to
   * match an existing BIM model by filename (strip extension too).  If
   * found, auto-select it.  If not, open the upload panel so the user
   * can upload + convert right away.  URL params are cleaned up after
   * one shot so a refresh doesn't keep re-triggering. */
  useEffect(() => {
    if (!deepLinkDocName && !deepLinkDocId) return;
    if (!models.length) return;
    const targetName = deepLinkDocName ? decodeURIComponent(deepLinkDocName).toLowerCase() : '';
    const nameNoExt = targetName.replace(/\.[^.]+$/, '');
    const match = models.find((m) => {
      const mLower = (m.name || '').toLowerCase();
      return mLower === targetName || mLower === nameNoExt || mLower.startsWith(nameNoExt);
    });
    if (match) {
      setActiveModelId(match.id);
      setShowUploadOverride(false);
    } else {
      // No matching model — open the upload panel so the user can convert.
      setUploadOpen(true);
      if (deepLinkDocName) setUploadConvertedName(decodeURIComponent(deepLinkDocName));
    }
    const next = new URLSearchParams(searchParams);
    next.delete('docName');
    next.delete('docId');
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkDocName, deepLinkDocId, models.length]);

  const activeModel = useMemo(() => models.find((m) => m.id === activeModelId) ?? null, [models, activeModelId]);

  const statusPollQuery = useQuery({
    queryKey: ['bim-model-status', activeModelId],
    queryFn: () => fetchBIMModel(activeModelId!),
    enabled: !!activeModelId && activeModel?.status === 'processing',
    refetchInterval: 8_000,
  });
  useEffect(() => {
    if (statusPollQuery.data && statusPollQuery.data.status !== 'processing' && activeModel?.status === 'processing') {
      queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
      queryClient.invalidateQueries({ queryKey: ['bim-elements', activeModelId] });
    }
  }, [statusPollQuery.data, activeModel, queryClient, projectId, activeModelId]);

  // Auto-detect project when navigating to /bim/:modelId without correct project context.
  // Runs at most once per urlModelId — never overrides an explicit project switch
  // from the top selector (which would otherwise snap the user back to this model's project).
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const autoDetectedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!urlModelId) return;
    if (autoDetectedRef.current === urlModelId) return;
    if (modelsQuery.isLoading) return;
    const modelInList = models.find((m) => m.id === urlModelId);
    if (modelInList) {
      autoDetectedRef.current = urlModelId;
      return;
    }
    fetchBIMModel(urlModelId).then((model) => {
      autoDetectedRef.current = urlModelId;
      if (model?.project_id && model.project_id !== projectId) {
        setActiveProject(model.project_id, '');
      }
    }).catch(() => { autoDetectedRef.current = urlModelId; });
  }, [urlModelId, models, projectId, setActiveProject, modelsQuery.isLoading]);

  // Pick a valid active model: handles initial mount, deep links (after auto-detect),
  // and project switches (when current activeModelId no longer belongs to the project).
  useEffect(() => {
    if (!models.length) return;
    // For deep links, wait until auto-detect has had a chance to run.
    if (urlModelId && autoDetectedRef.current !== urlModelId) return;
    const currentInList = activeModelId && models.some((m) => m.id === activeModelId);
    if (currentInList) return;
    const target = urlModelId && models.find((m) => m.id === urlModelId) ? urlModelId : models[0]!.id;
    setActiveModelId(target);
  }, [models, activeModelId, urlModelId]);

  // Sync URL when active model changes
  useEffect(() => {
    if (!activeModelId) return;
    const basePath = urlProjectId ? `/projects/${urlProjectId}/bim` : '/bim';
    const targetPath = `${basePath}/${activeModelId}`;
    if (!window.location.pathname.endsWith(activeModelId)) {
      navigate(targetPath, { replace: true });
    }
  }, [activeModelId, urlProjectId, navigate]);

  // Reset transient viewer state when switching between models
  useEffect(() => {
    setMeshMatchRatio(null);
    setFilterPredicate(null);
    setVisibleElementCount(null);
    setIsolatedIds(null);
    setColorByMode('default');
    setFullModelRequested(false);
    setActiveGroupId(null);
  }, [activeModelId]);

  // When ?group= is present, load only that group's elements from the
  // backend (lazy loading).  This makes cross-module navigation instant
  // for large models (7k+ elements).
  const groupParam = searchParams.get('group');
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [fullModelRequested, setFullModelRequested] = useState(false);

  // Sync the URL group param into local state on mount / URL change.
  useEffect(() => {
    if (groupParam && !fullModelRequested) {
      setActiveGroupId(groupParam);
    }
  }, [groupParam, fullModelRequested]);

  const effectiveGroupId = fullModelRequested ? null : activeGroupId;

  const elementsQuery = useQuery({
    // Skeleton mode: ~10× faster list (no boq_links / tasks / docs / activities
    // / requirements / validation joins). The 3D viewer only needs identity
    // + bbox for mesh matching; relations are fetched on demand when the user
    // opens the BOQ-link panel or a validation drawer.
    queryKey: ['bim-elements', activeModelId, effectiveGroupId ?? 'all', 'skeleton'],
    queryFn: () =>
      fetchBIMElements(activeModelId!, {
        groupId: effectiveGroupId,
        skeleton: true,
      }),
    // Only load elements once we know the model is actually ready.  Firing
    // earlier (e.g. while the model is still in 'processing' state right after
    // an upload) used to surface a misleading "Failed to load model elements"
    // toast — the inline NonReadyOverlay now drives the UI for non-ready
    // states and the elements query waits its turn.
    enabled: !!activeModelId && activeModel?.status === 'ready',
  });
  const elements: BIMElementData[] = elementsQuery.data?.items ?? [];
  const elementsTotal: number = elementsQuery.data?.total ?? 0;

  // Apply the deep-link element selection as soon as the elements list
  // resolves.  Strips the query param afterwards so a refresh doesn't
  // keep re-selecting the same element.
  useEffect(() => {
    if (!deepLinkElementId || elements.length === 0) return;
    const target = elements.find((e) => e.id === deepLinkElementId);
    if (target) {
      setSelectedElementId(deepLinkElementId);
      setBIMSelection([deepLinkElementId]);
      const next = new URLSearchParams(searchParams);
      next.delete('element');
      setSearchParams(next, { replace: true });
    }
  }, [deepLinkElementId, elements, searchParams, setSearchParams, setBIMSelection]);

  // Deep-link: ?isolate=id1,id2,... — isolate the listed BIM elements in
  // the 3D viewer.  Used by the BOQ editor's "View in BIM" button when a
  // position is linked to one or more BIM elements.  Stripped after first
  // application so a page refresh resets to the full model view.
  const isolateParam = searchParams.get('isolate');
  useEffect(() => {
    if (!isolateParam || elements.length === 0) return;
    const ids = isolateParam.split(',').filter((id) => id.length > 0);
    if (ids.length === 0) return;
    // Verify at least one ID actually exists in the current model
    const elementIdSet = new Set(elements.map((e) => e.id));
    const validIds = ids.filter((id) => elementIdSet.has(id));
    if (validIds.length === 0) return;
    setIsolatedIds(validIds);
    // If a single element is isolated, also select it to show its detail
    if (validIds.length === 1) {
      setSelectedElementId(validIds[0]!);
      setBIMSelection(validIds);
    }
    const next = new URLSearchParams(searchParams);
    next.delete('isolate');
    setSearchParams(next, { replace: true });
  }, [isolateParam, elements, searchParams, setSearchParams, setBIMSelection]);

  // Saved element groups for the current model — populated by the
  // /api/v1/bim_hub/element-groups/ endpoint and rendered at the top
  // of BIMFilterPanel for one-click apply.  Refetch is triggered by
  // the SaveGroupModal's success path via React Query invalidation.
  const groupsQuery = useQuery({
    queryKey: ['bim-element-groups', projectId, activeModelId],
    queryFn: () => listElementGroups(projectId, activeModelId),
    enabled: !!projectId && !!activeModelId,
  });
  const savedGroups: BIMElementGroup[] = groupsQuery.data ?? [];

  // Resolve the active group name for the lazy-load info bar.
  const activeGroupMeta = useMemo(() => {
    if (!activeGroupId) return null;
    return savedGroups.find((g) => g.id === activeGroupId) ?? null;
  }, [activeGroupId, savedGroups]);

  // Direct URL for Three.js loaders — no blob intermediary, no race conditions.
  // The ?token= param authenticates the request (Three.js can't set headers).
  // Cache-bust with model updated_at to ensure fresh geometry after re-upload.
  const geometryUrl = useMemo(() => {
    if (
      !activeModelId ||
      activeModel?.status !== 'ready' ||
      ((activeModel?.element_count ?? 0) === 0 && !elements.some((el) => !!el.mesh_ref))
    ) {
      return null;
    }
    const token = useAuthStore.getState().accessToken;
    const base = `/api/v1/bim_hub/models/${encodeURIComponent(activeModelId)}/geometry/`;
    const params = new URLSearchParams();
    if (token) params.set('token', token);
    params.set('_t', activeModel?.updated_at || String(Date.now()));
    return `${base}?${params.toString()}`;
  }, [activeModelId, activeModel?.status, activeModel?.element_count, activeModel?.updated_at, elements]);

  const handleElementSelect = useCallback(
    (id: string | null) => {
      setSelectedElementId(id);
      // Publish the click to the cross-highlight store so the BOQ editor
      // can scroll to any linked row.
      setBIMSelection(id ? [id] : []);
    },
    [setBIMSelection],
  );

  // Clear the cross-highlight store when leaving the BIM page so the BOQ
  // editor doesn't keep a stale highlight from a previous session.
  useEffect(() => {
    return () => clearBIMLinkSelection();
  }, [clearBIMLinkSelection]);

  /* ── URL deep-link: camera + selection ──────────────────────────────
   * Writes the current camera position/target and the multi-selection
   * ID list to the URL so users can copy-paste a link that reopens
   * /bim with the exact same view.  On mount, once the model has
   * loaded and the viewer's camera bridge is available, we hydrate
   * the camera + selection from the URL.
   *
   * The write is debounced to 500ms — an OrbitControls drag fires
   * dozens of change events per second, which would flood the
   * history stack and create noticeable stutter on 100k-element
   * models. */
  const urlStateAppliedRef = useRef(false);

  // Hydrate camera + selection from URL when the model and viewer
  // bridge are both ready. Runs once per activeModelId — subsequent
  // camera moves or selection changes are driven by user input.
  useEffect(() => {
    if (!activeModelId) return;
    if (urlStateAppliedRef.current) return;
    if (elements.length === 0) return; // wait for elements to load
    const state = parseBIMUrlState(searchParams);
    if (!state.camera && state.selection.length === 0) {
      urlStateAppliedRef.current = true;
      return;
    }
    // Try applying via the viewer's camera bridge; back off one frame
    // if it isn't ready yet (the bridge publishes after the <canvas />
    // ref populates, which can be 1–2 frames behind the parent render).
    let cancelled = false;
    let attempts = 0;
    const apply = () => {
      if (cancelled) return;
      const bridge = (
        window as unknown as {
          __oeBim?: {
            setViewpoint: (
              pos: { x: number; y: number; z: number },
              target: { x: number; y: number; z: number },
            ) => void;
          };
        }
      ).__oeBim;
      if (!bridge && attempts < 60) {
        attempts++;
        requestAnimationFrame(apply);
        return;
      }
      if (state.camera && bridge) {
        bridge.setViewpoint(state.camera.position, state.camera.target);
      }
      if (state.selection.length > 0) {
        setMultiSelectedIds(state.selection);
        setSelectedElementId(state.selection[state.selection.length - 1] ?? null);
      }
      urlStateAppliedRef.current = true;
    };
    apply();
    return () => {
      cancelled = true;
    };
  }, [activeModelId, elements.length, searchParams]);

  // Reset hydration flag when switching models so each /bim/:modelId
  // can carry its own ?cx=...&sel=... combination.
  useEffect(() => {
    urlStateAppliedRef.current = false;
  }, [activeModelId]);

  // Debounced writer: camera + selection -> URL. We read the camera on
  // an interval rather than listening to OrbitControls directly to keep
  // this scoped to the parent page (the bridge is the public contract
  // BIMViewer exposes; wiring into SceneManager here would cross that
  // boundary and force every consumer to learn three.js internals).
  //
  // selectionSignature tracks whatever the current multi/single selection
  // resolves to — we derive it inside the effect so this hook doesn't
  // depend on a value declared lower in the component.
  const selectionSignature = multiSelectedIds.length > 0
    ? multiSelectedIds.join(',')
    : (selectedElementId ?? '');
  useEffect(() => {
    if (!activeModelId) return;
    if (!urlStateAppliedRef.current) return;
    let lastSerialized = '';
    const interval = window.setInterval(() => {
      const bridge = (
        window as unknown as {
          __oeBim?: {
            getViewpoint: () => {
              position: { x: number; y: number; z: number };
              target: { x: number; y: number; z: number };
            } | null;
          };
        }
      ).__oeBim;
      const camera = bridge?.getViewpoint?.() ?? null;
      const selection: string[] = multiSelectedIds.length > 0
        ? multiSelectedIds
        : (selectedElementId ? [selectedElementId] : []);
      const payload = serializeBIMUrlState({
        camera,
        selection,
      });
      const serialized = JSON.stringify(payload);
      if (serialized === lastSerialized) return;
      lastSerialized = serialized;
      // Merge into current params so we never clobber unrelated keys
      // (group, docName, etc.).  Only add sel when non-empty so the URL
      // stays short when nothing's selected.
      const next = new URLSearchParams(window.location.search);
      for (const k of BIM_URL_STATE_KEYS) next.delete(k);
      for (const [k, v] of Object.entries(payload)) next.set(k, v);
      setSearchParams(next, { replace: true });
    }, 500);
    return () => window.clearInterval(interval);
    // selectionSignature is intentional — we want to re-evaluate when the
    // selection changes but keep the interval running across many URL
    // writes, so the dep list stays minimal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeModelId, selectionSignature]);

  // Stable callback for BIMFilterPanel — uses functional setState so it
  // doesn't need to track filterPredicate in its dependency list.
  const handleFilterChange = useCallback(
    (predicate: (el: BIMElementData) => boolean, visibleCount: number) => {
      setFilterPredicate(() => predicate);
      setVisibleElementCount(visibleCount);
    },
    [],
  );

  // Smart-filter chips emitted by BIMViewer's health stats banner.
  // Each chip applies a one-shot predicate that narrows the viewport
  // to elements matching a specific cross-module health bucket.
  const handleSmartFilter = useCallback(
    (filterId: 'errors' | 'warnings' | 'unlinked_boq' | 'has_tasks' | 'has_docs') => {
      const predicates: Record<typeof filterId, (el: BIMElementData) => boolean> = {
        errors: (el) => el.validation_status === 'error',
        warnings: (el) => el.validation_status === 'warning',
        unlinked_boq: (el) => (el.boq_links?.length ?? 0) === 0,
        has_tasks: (el) => (el.linked_tasks?.length ?? 0) > 0,
        has_docs: (el) => (el.linked_documents?.length ?? 0) > 0,
      };
      const predicate = predicates[filterId];
      const subset = elements.filter(predicate);
      setFilterPredicate(() => predicate);
      setVisibleElementCount(subset.length);
      const labels: Record<typeof filterId, string> = {
        errors: t('bim.smart_filter_errors', { defaultValue: 'Validation errors' }),
        warnings: t('bim.smart_filter_warnings', { defaultValue: 'Validation warnings' }),
        unlinked_boq: t('bim.smart_filter_unlinked_boq', { defaultValue: 'Unlinked to BOQ' }),
        has_tasks: t('bim.smart_filter_has_tasks', { defaultValue: 'With tasks' }),
        has_docs: t('bim.smart_filter_has_docs', { defaultValue: 'With documents' }),
      };
      addToast({
        type: subset.length === 0 ? 'info' : 'success',
        title: labels[filterId],
        message: t('bim.smart_filter_applied', {
          count: subset.length,
          defaultValue: '{{count}} elements match',
        }),
      });
    },
    [elements, t, addToast],
  );

  const handleFilterElementClick = useCallback((elementId: string) => {
    setSelectedElementId(elementId);
  }, []);

  // Open the AddToBOQ modal for one or more selected elements (bulk link).
  const handleAddToBOQ = useCallback((elements: BIMElementData[]) => {
    if (elements.length > 0) setLinkCandidates(elements);
  }, []);

  // Cross-module navigation handlers — fired when the user clicks a row
  // in the Linked Documents / Tasks / Activities sections of the
  // selected-element panel.  Each one takes them to the relevant module
  // and pre-selects the target.
  const handleOpenDocument = useCallback(
    (documentId: string) => {
      navigate(`/documents?id=${encodeURIComponent(documentId)}`);
    },
    [navigate],
  );
  const handleOpenTask = useCallback(
    (taskId: string) => {
      navigate(`/tasks?id=${encodeURIComponent(taskId)}`);
    },
    [navigate],
  );
  const handleOpenActivity = useCallback(
    (activityId: string) => {
      navigate(`/schedule?activity=${encodeURIComponent(activityId)}`);
    },
    [navigate],
  );

  // Inline-create handlers — fired when the user clicks "+ New" / "+ Link"
  // in the cross-module sections of the selected-element panel.  These
  // open the inline modals so the user never has to leave the BIM viewer
  // to create a task, link a drawing, or attach a schedule activity.
  const handleCreateTask = useCallback((element: BIMElementData) => {
    setCreateTaskFor([element]);
  }, []);
  const handleLinkDocument = useCallback((element: BIMElementData) => {
    setLinkDocumentFor([element]);
  }, []);
  const handleLinkActivity = useCallback((element: BIMElementData) => {
    setLinkActivityFor([element]);
  }, []);
  const handleLinkRequirement = useCallback((element: BIMElementData) => {
    setLinkRequirementFor([element]);
  }, []);
  const handleOpenRequirement = useCallback(
    (requirementId: string) => {
      navigate(`/bim/rules?id=${encodeURIComponent(requirementId)}`);
    },
    [navigate],
  );

  // Link a saved group to a BOQ position — looks up every member element
  // by id from the current `elements` list and opens AddToBOQModal with
  // the resolved subset.  If some member ids aren't in the loaded element
  // list (e.g. the group references elements from a different model that
  // happen to share an id), they're silently dropped.
  const handleLinkGroupToBOQ = useCallback(
    (group: BIMElementGroup) => {
      const memberIds = new Set(
        Array.isArray(group.member_element_ids) ? group.member_element_ids : [],
      );
      const subset = elements.filter((el) => memberIds.has(el.id));
      if (subset.length === 0) {
        addToast({
          type: 'info',
          title: t('bim.group_empty_title', { defaultValue: 'Empty group' }),
          message: t('bim.group_empty_msg', {
            defaultValue: 'This group has no members in the current model.',
          }),
        });
        return;
      }
      setLinkCandidates(subset);
    },
    [elements, addToast, t],
  );

  // Delete a saved group via the backend, refresh the list.
  const handleDeleteGroup = useCallback(
    async (group: BIMElementGroup) => {
      const ok = await confirm({
        title: t('bim.group_delete_confirm_title', { defaultValue: 'Delete group?' }),
        message: t('bim.group_delete_confirm', {
          defaultValue: 'Delete the saved group "{{name}}"?',
          name: group.name,
        }),
      });
      if (!ok) return;
      try {
        await deleteElementGroup(group.id);
        addToast({
          type: 'success',
          title: t('bim.group_deleted_title', { defaultValue: 'Group deleted' }),
          message: group.name,
        });
        queryClient.invalidateQueries({
          queryKey: ['bim-element-groups', projectId, activeModelId],
        });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [addToast, queryClient, projectId, activeModelId, t],
  );

  // Convert the filter panel's local state into the backend's
  // BIMGroupFilterCriteria shape so the SaveGroupModal can persist it.
  // The filter panel stores set-based selections; the backend takes
  // arrays.  We deliberately drop the `groupBy` axis (which is purely
  // a UI grouping choice and not part of the predicate) and the
  // `buildingsOnly` toggle (which is a viewport-level setting, not a
  // group definition — saved groups always include their full member
  // set even if they're noise/annotations).
  type FilterStateShape = {
    search: string;
    storeys: Set<string>;
    types: Set<string>;
  };
  const handleSaveAsGroup = useCallback(
    (filter: FilterStateShape, visibleElementIds: string[]) => {
      const criteria: BIMGroupFilterCriteria = {};
      if (filter.storeys.size > 0) {
        criteria.storey = Array.from(filter.storeys);
      }
      if (filter.types.size > 0) {
        criteria.element_type = Array.from(filter.types);
      }
      const search = filter.search.trim();
      if (search) criteria.name_contains = search;
      // Prefer the explicit multi-selection when the user has Ctrl+clicked
      // a subset — that gesture means "this is what I want", not "every
      // element matching the current filter".  Falls back to the visible
      // (filtered + isolated) subset otherwise.
      const targetIds =
        multiSelectedIds.length > 0 ? multiSelectedIds : visibleElementIds;
      setSaveGroupState({
        filterCriteria: criteria,
        elementIds: targetIds,
      });
    },
    [multiSelectedIds],
  );

  // Isolate a saved group's member elements in the 3D viewport.
  const handleIsolateGroup = useCallback(
    (group: BIMElementGroup) => {
      const ids = Array.isArray(group.member_element_ids) ? group.member_element_ids : [];
      setIsolatedIds(ids.length > 0 ? ids : null);
    },
    [],
  );

  // Highlight a group's members on hover — set isolatedIds to a temporary
  // preview without committing.  We use the BIM viewer's highlightedIds
  // prop instead to avoid flickering the isolation state.
  const handleHighlightGroup = useCallback(
    (group: BIMElementGroup | null) => {
      if (group) {
        setBIMSelection(
          Array.isArray(group.member_element_ids) ? group.member_element_ids : [],
        );
      } else {
        setBIMSelection([]);
      }
    },
    [setBIMSelection],
  );

  // Navigate to the BOQ editor, optionally focusing a specific position.
  const handleNavigateToBOQ = useCallback(
    (positionId: string) => {
      navigate(`/boq?position=${encodeURIComponent(positionId)}`);
    },
    [navigate],
  );

  // Invalidate groups query after a rename or color change.
  const handleGroupUpdated = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ['bim-element-groups', projectId, activeModelId],
    });
  }, [queryClient, projectId, activeModelId]);

  // Remove a BIM↔BOQ link — fires from the properties panel's unlink button.
  const handleUnlinkBOQ = useCallback(
    async (linkId: string) => {
      try {
        await deleteLink(linkId);
        addToast({
          type: 'success',
          title: t('bim.link_removed_title', { defaultValue: 'Unlinked' }),
          message: t('bim.link_removed', { defaultValue: 'BIM ↔ BOQ link removed' }),
        });
        queryClient.invalidateQueries({ queryKey: ['bim-elements', activeModelId] });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [activeModelId, addToast, queryClient, t],
  );

  // Kick a "quick takeoff" from the currently-applied filter — aggregate all
  // elements that match the active filter predicate and open AddToBOQ with
  // the full subset so the user can generate one BOQ position from e.g.
  // "all walls on level 1".
  const handleQuickTakeoff = useCallback(() => {
    if (!elementsQuery.data || elementsQuery.data.items.length === 0) return;
    const subset = filterPredicate
      ? elementsQuery.data.items.filter(filterPredicate)
      : elementsQuery.data.items;
    if (subset.length === 0) {
      addToast({
        type: 'info',
        title: t('bim.quick_takeoff_empty_title', { defaultValue: 'Nothing to link' }),
        message: t('bim.quick_takeoff_empty', {
          defaultValue: 'Current filter has no elements to link',
        }),
      });
      return;
    }
    setLinkCandidates(subset);
  }, [elementsQuery.data, filterPredicate, addToast, t]);

  const handleUploadComplete = useCallback((modelId: string) => {
    setActiveModelId(modelId); setShowUploadOverride(false); setSelectedElementId(null); setMultiSelectedIds([]);
    setUploadOpen(false); setUploadConvertedName(null);
    // Invalidate both model list and elements — the model is ready on the
    // backend but the list cache may still show 'processing' for a moment.
    queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
    queryClient.invalidateQueries({ queryKey: ['bim-elements', modelId] });
    // Retry after a short delay to catch race conditions where the first
    // refetch arrives before the backend has fully committed the status.
    setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
      queryClient.invalidateQueries({ queryKey: ['bim-elements', modelId] });
    }, 2000);
  }, [queryClient, projectId]);

  // Watch global BIM upload store — when a job for this project finishes
  // successfully, auto-select the new model and refresh the model list.
  // Completion / error toasts are user-facing here (not the pill in
  // GlobalUploadIndicator — that's only a progress indicator).
  const globalUploadJobs = useBIMUploadStore((s) => s.jobs);
  const completedJobRef = useRef(new Set<string>());
  useEffect(() => {
    for (const [jobId, job] of globalUploadJobs) {
      if (job.projectId !== projectId) continue;
      if (job.status === 'ready' && !completedJobRef.current.has(jobId)) {
        completedJobRef.current.add(jobId);
        if (job.modelId) handleUploadComplete(job.modelId);
        addToast({
          type: 'success',
          title: t('bim.toast_model_processed_title', { defaultValue: 'Model ready' }),
          message: t('bim.upload_complete_count', { defaultValue: '{{count}} elements', count: job.elementCount }),
        });
      } else if (
        job.status === 'error' &&
        !completedJobRef.current.has(jobId)
      ) {
        completedJobRef.current.add(jobId);
        addToast({
          type: 'error',
          title: t('bim.toast_processing_failed_title', { defaultValue: 'Processing failed' }),
          message: job.errorMessage || undefined,
        });
      } else if (
        job.status === 'converter_required' &&
        !completedJobRef.current.has(jobId)
      ) {
        completedJobRef.current.add(jobId);
      }
    }
  }, [globalUploadJobs, projectId, handleUploadComplete, addToast, t]);

  const handleDeleteModel = useCallback(async (modelId: string, name: string) => {
    const ok = await confirm({
      title: t('bim.confirm_delete_model_title', { defaultValue: 'Delete model?' }),
      message: t('bim.confirm_delete_model', { name }),
    });
    if (!ok) return;
    try {
      await deleteBIMModel(modelId);
      addToast({ type: 'success', title: t('bim.toast_model_deleted_title'), message: name });
      if (activeModelId === modelId) { setActiveModelId(null); setSelectedElementId(null); setMultiSelectedIds([]); }
      queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
    } catch (err) { addToast({ type: 'error', title: t('bim.toast_delete_failed_title'), message: err instanceof Error ? err.message : String(err) }); }
  }, [activeModelId, addToast, queryClient, projectId, t]);

  const breadcrumbItems = useMemo(() => {
    const items: { label: string; to?: string }[] = [{ label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' }];
    if (projectId && contextProjectName) items.push({ label: contextProjectName, to: `/projects/${projectId}` });
    items.push({ label: t('bim.title') });
    return items;
  }, [t, projectId, contextProjectName]);

  // For multi-select: keep the FULL list of selected IDs in parent state so
  // re-renders never collapse a Ctrl+click multi-selection back to a single
  // element. The viewer's onSelectionChange callback feeds it; the array is
  // then echoed back via selectedElementIds so highlights stay in sync.
  // selectedElementId still tracks the LAST clicked id (for properties panel
  // and deep-link navigation).
  const selectedElementIds = multiSelectedIds.length > 0
    ? multiSelectedIds
    : (selectedElementId ? [selectedElementId] : []);

  // Bounding-box dimensions of the current single selection. Union bbox
  // across the whole multi-selection would be possible, but estimators
  // reported the "what is this one piece?" view as most useful — keep
  // the card single-selection-only to avoid confusing aggregates.
  const selectedDimensions = useMemo(() => {
    if (!selectedElementId || selectedElementIds.length > 1) return null;
    const el = elements.find((e) => e.id === selectedElementId);
    const bb = el?.bounding_box;
    if (!el || !bb) return null;
    const L = Math.abs(bb.max_x - bb.min_x);
    const W = Math.abs(bb.max_y - bb.min_y);
    const H = Math.abs(bb.max_z - bb.min_z);
    return {
      name: el.name || el.element_type || 'Element',
      type: el.element_type,
      L,
      W,
      H,
      volume: L * W * H,
    };
  }, [selectedElementId, selectedElementIds, elements]);

  if (!projectId) {
    return (
      <div className="flex items-center justify-center -mx-4 sm:-mx-7 -mt-6 -mb-6 border-s border-border-light" style={{ height: 'calc(100vh - 56px)' }}>
        <EmptyState icon={<FolderOpen size={32} />} title={t('bim.no_project')} description={t('bim.no_project_desc')} />
      </div>
    );
  }

  if (showFullPageUpload && !modelsQuery.isLoading) {
    return (
      <>
        <LandingPage projectId={projectId} onUploadComplete={handleUploadComplete} breadcrumbItems={breadcrumbItems} models={models} onSelectModel={(id) => { setActiveModelId(id); setShowUploadOverride(false); setSelectedElementId(null); setMultiSelectedIds([]); }} onDeleteModel={handleDeleteModel} />
        <ConfirmDialog {...confirmProps} />
      </>
    );
  }

  const storeys = new Set(elements.map((e) => e.storey).filter(Boolean));
  const discips = new Set(elements.map((e) => e.discipline).filter(Boolean));
  // "Loading by URL": user just uploaded or deep-linked, models query is still
  // refetching, so activeModel hasn't materialised yet.  We treat this as a
  // non-ready state so the inline overlay renders instead of the BIMViewer
  // (which would otherwise fire the elements query and surface an error).
  const isModelLoadingByUrl =
    !!urlModelId && !activeModel && (modelsQuery.isLoading || modelsQuery.isFetching);
  const isModelNonReady =
    !!isModelLoadingByUrl ||
    !!(activeModel && ['processing', 'needs_converter', 'error'].includes(activeModel.status));

  return (
    <div className="flex flex-col -mx-4 sm:-mx-7 -mt-6 -mb-6 border-s border-border-light" style={{ height: 'calc(100vh - 56px)' }}>
      {/* ── Header ── */}
      <div className="relative z-20 px-3 py-2.5 flex items-center justify-between border-b border-border-light bg-surface-primary">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-oe-blue/10 to-blue-50 dark:to-blue-950/20 border border-oe-blue/15 flex items-center justify-center">
              <Cuboid size={18} className="text-oe-blue" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-content-primary">{t('bim.viewer_title', { defaultValue: 'BIM Viewer' })}</h1>
              {activeModel && <p className="text-[10px] text-content-tertiary truncate max-w-[160px] lg:max-w-[280px]">{activeModel.name}</p>}
            </div>
          </div>
          {elements.length > 0 && (
            <div className="hidden md:flex items-center gap-2 ms-2">
              <StatPill icon={Box} label={t('bim.stat_elements', { defaultValue: 'Elements' })} value={elements.length} />
              {storeys.size > 0 && <StatPill icon={Layers} label={t('bim.stat_storeys', { defaultValue: 'Levels' })} value={storeys.size} />}
              {discips.size > 0 && <StatPill icon={Sparkles} label={t('bim.stat_disciplines', { defaultValue: 'Disciplines' })} value={discips.size} />}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {elements.length > 0 && (
            <>
              <button
                onClick={() => setFilterPanelOpen((p) => !p)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border ${
                  filterPanelOpen
                    ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/30'
                    : 'text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary'
                }`}
                title={t('bim.filter_toggle', { defaultValue: 'Toggle filter panel' })}
                aria-label={t('bim.filter_toggle', { defaultValue: 'Toggle filter panel' })}
                aria-pressed={filterPanelOpen}
              >
                <Filter size={13} />
                {t('bim.filter_button', { defaultValue: 'Filter' })}
                {visibleElementCount !== null && visibleElementCount < elements.length && (
                  <span className="text-[10px] bg-oe-blue text-white rounded-full px-1.5 py-0 tabular-nums">
                    {visibleElementCount}
                  </span>
                )}
              </button>

              <button
                onClick={() => setSummaryPanelOpen(!summaryPanelOpen)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border ${
                  summaryPanelOpen
                    ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/30'
                    : 'text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary'
                }`}
                title={
                  summaryPanelOpen
                    ? t('bim.summary_hide', { defaultValue: 'Hide summary panel' })
                    : t('bim.summary_show', { defaultValue: 'Show summary panel' })
                }
                aria-label={t('bim.summary_toggle', { defaultValue: 'Toggle summary panel' })}
                aria-pressed={summaryPanelOpen}
              >
                <LayoutGrid size={13} />
                {t('bim.summary_button', { defaultValue: 'Summary' })}
              </button>

              <button
                onClick={() => setDimensionsVisible(!dimensionsVisible)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border ${
                  dimensionsVisible
                    ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/30'
                    : 'text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary'
                }`}
                title={
                  dimensionsVisible
                    ? t('bim.dimensions_hide', {
                        defaultValue: 'Hide bounding-box dimensions on selection',
                      })
                    : t('bim.dimensions_show', {
                        defaultValue: 'Show bounding-box dimensions on selection',
                      })
                }
                aria-label={t('bim.dimensions_toggle', {
                  defaultValue: 'Toggle bounding-box dimensions',
                })}
                aria-pressed={dimensionsVisible}
              >
                <Maximize2 size={13} />
                {t('bim.dimensions_button', { defaultValue: 'BBox Dimensions' })}
              </button>

              {projectId && (
                <button
                  onClick={() => setSnapshotsOpen((p) => !p)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border ${
                    snapshotsOpen
                      ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/30'
                      : 'text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary'
                  }`}
                  title={t('bim.snapshots_button_title', {
                    defaultValue: 'Data snapshots for this project',
                  })}
                  aria-label={t('bim.snapshots_toggle', {
                    defaultValue: 'Toggle snapshots popover',
                  })}
                  aria-pressed={snapshotsOpen}
                  data-testid="bim-snapshots-toggle"
                >
                  <Layers size={13} />
                  {t('bim.snapshots_button', { defaultValue: 'Snapshots' })}
                </button>
              )}

              <button
                onClick={() => setAssetCardEnabled(!assetCardEnabled)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border ${
                  assetCardEnabled
                    ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/30'
                    : 'text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary'
                }`}
                title={
                  assetCardEnabled
                    ? t('bim.asset_card_hide', {
                        defaultValue: 'Hide asset-info card on selection',
                      })
                    : t('bim.asset_card_show', {
                        defaultValue: 'Show asset-info card on selection',
                      })
                }
                aria-label={t('bim.asset_card_toggle', {
                  defaultValue: 'Toggle asset register card',
                })}
                aria-pressed={assetCardEnabled}
                data-testid="bim-asset-card-toggle"
              >
                <Package size={13} />
                {t('bim.asset_card_button', { defaultValue: 'Asset Card' })}
              </button>

              <button
                onClick={() => setBoqPanelOpen(!boqPanelOpen)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border ${
                  boqPanelOpen
                    ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/30'
                    : 'text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary'
                }`}
                title={t('bim.linked_boq_toggle', { defaultValue: 'Toggle linked BOQ panel' })}
                aria-label={t('bim.linked_boq_toggle', { defaultValue: 'Toggle linked BOQ panel' })}
                aria-pressed={boqPanelOpen}
              >
                <ClipboardList size={13} />
                {t('bim.linked_boq_button', { defaultValue: 'Linked BOQ' })}
              </button>

              {/* Color-by selector — three families:
                  · Field-based (Storey / Type) use the hash-to-hue palette
                  · Compliance-based (Validation / BOQ / Documents) use a
                    fixed red/amber/green palette and turn the 3D viewer
                    into a live compliance dashboard. */}
              <select
                value={colorByMode}
                onChange={(e) =>
                  setColorByMode(
                    e.target.value as
                      | 'default'
                      | 'storey'
                      | 'type'
                      | 'validation'
                      | 'boq_coverage'
                      | 'document_coverage'
                      | '5d_cost'
                      | '4d_schedule',
                  )
                }
                title={t('bim.color_by', { defaultValue: 'Color by' })}
                aria-label={t('bim.color_by', { defaultValue: 'Color by' })}
                data-testid="bim-color-mode-select"
                className="text-[11px] py-1.5 px-2 rounded-lg border border-border-light bg-surface-secondary text-content-secondary hover:bg-surface-tertiary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              >
                <optgroup label={t('bim.color_group_field', { defaultValue: 'By field' })}>
                  <option value="default">{t('bim.color_default', { defaultValue: 'Default' })}</option>
                  <option value="storey">{t('bim.color_storey', { defaultValue: 'Storey' })}</option>
                  <option value="type">{t('bim.color_type', { defaultValue: 'Category' })}</option>
                </optgroup>
                <optgroup label={t('bim.color_group_status', { defaultValue: 'By compliance' })}>
                  <option value="validation">
                    {t('bim.color_validation', { defaultValue: 'Validation status' })}
                  </option>
                  <option value="boq_coverage">
                    {t('bim.color_boq_coverage', { defaultValue: 'BOQ link coverage' })}
                  </option>
                  <option value="document_coverage">
                    {t('bim.color_doc_coverage', { defaultValue: 'Document coverage' })}
                  </option>
                </optgroup>
                <optgroup label={t('bim.color_group_cost', { defaultValue: 'By cost' })}>
                  <option value="5d_cost">
                    {t('bim.color_5d_cost', { defaultValue: '5D unit rate' })}
                  </option>
                </optgroup>
                <optgroup label={t('bim.color_group_schedule', { defaultValue: 'By schedule' })}>
                  <option value="4d_schedule">
                    {t('bim.color_4d_schedule', { defaultValue: '4D timeline' })}
                  </option>
                </optgroup>
              </select>

              {/* Isolate toggle (when an element is selected) */}
              {selectedElementId && (
                <button
                  onClick={() =>
                    setIsolatedIds((cur) => (cur ? null : [selectedElementId]))
                  }
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-colors border ${
                    isolatedIds
                      ? 'bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-950/30 dark:text-amber-400 dark:border-amber-800'
                      : 'text-content-secondary bg-surface-secondary border-border-light hover:bg-surface-tertiary'
                  }`}
                  title={t('bim.isolate_selection', { defaultValue: 'Isolate selection' })}
                >
                  {isolatedIds
                    ? t('bim.show_all', { defaultValue: 'Show all' })
                    : t('bim.isolate', { defaultValue: 'Isolate' })}
                </button>
              )}
              <button onClick={() => navigate('/bim/rules?mode=requirements')} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-content-secondary bg-surface-secondary border border-border-light hover:bg-surface-tertiary transition-colors">
                <SlidersHorizontal size={13} /> {t('bim.rules_button', { defaultValue: 'Rules' })}
              </button>
              <button
                disabled
                aria-disabled="true"
                title={t('bim.schedule_4d_coming_soon', { defaultValue: '4D Schedule — coming soon' })}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-content-tertiary bg-surface-secondary border border-border-light opacity-60 cursor-not-allowed"
              >
                <CalendarDays size={13} /> {t('bim.schedule_4d', { defaultValue: '4D Schedule' })}
              </button>
            </>
          )}
          <button onClick={() => setUploadOpen((p) => !p)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-oe-blue text-white hover:bg-oe-blue-dark transition-colors shadow-sm">
            <Plus size={13} /> {t('bim.add_model', { defaultValue: 'Add Model' })}
          </button>
        </div>
      </div>

      {/* ── Converter status banner — surfaces any missing DDC
            converters so the user can one-click install them before
            dragging a native CAD file onto the upload zone. ── */}
      <BIMConverterStatusBanner className="mx-3 mt-2" />

      {/* ── 3D Viewport with filter sidebar ── */}
      <div className="flex-1 min-h-0 relative bg-surface-secondary flex">
        {/* Filter sidebar — only when model has loaded elements */}
        {activeModelId && !isModelNonReady && elements.length > 0 && filterPanelOpen && (
          <div className="absolute top-0 start-0 h-full z-20 overflow-y-auto flex flex-col">
            <BIMFilterGroupsPanel
              elements={elements}
              savedGroups={savedGroups}
              projectId={projectId}
              modelId={activeModelId ?? undefined}
              modelFormat={activeModel?.model_format || activeModel?.format}
              onFilterChange={handleFilterChange}
              onClose={() => setFilterPanelOpen(false)}
              onElementClick={handleFilterElementClick}
              onQuickTakeoff={handleQuickTakeoff}
              visibleElementCount={visibleElementCount}
              onSaveAsGroup={handleSaveAsGroup}
              onLinkGroupToBOQ={handleLinkGroupToBOQ}
              onDeleteGroup={handleDeleteGroup}
              onSmartFilter={handleSmartFilter}
              isolatedIds={isolatedIds}
              onClearIsolation={() => setIsolatedIds(null)}
              onIsolateGroup={handleIsolateGroup}
              onHighlightGroup={handleHighlightGroup}
              onNavigateToBOQ={handleNavigateToBOQ}
              onGroupUpdated={handleGroupUpdated}
            />

          </div>
        )}

        <div className="flex-1 min-w-0 relative">
        {/* Selected-element bounding-box dimensions. Top-right, non-
            blocking, auto-hides when the toggle is off or nothing is
            selected. Numbers come from the element's canonical
            bounding_box in metres. */}
        {dimensionsVisible && selectedDimensions && (
          <div
            className="absolute top-[60px] z-30 pointer-events-none select-none
                       rounded-lg border border-oe-blue/30 bg-surface-primary/95
                       backdrop-blur-sm shadow-md px-3 py-2 min-w-[180px]
                       transition-[inset-inline-start] duration-200"
            style={{ insetInlineStart: filterPanelOpen && elements.length > 0 ? 332 : 12 }}
            data-testid="bim-dimensions-card"
          >
            <div className="flex items-center gap-1.5 mb-1.5">
              <Maximize2 size={12} className="text-oe-blue shrink-0" />
              <span className="text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
                {t('bim.dimensions_title', { defaultValue: 'BBox dimensions' })}
              </span>
            </div>
            <div className="text-[11px] font-medium text-content-primary truncate mb-1.5" title={selectedDimensions.name}>
              {selectedDimensions.name}
              {selectedDimensions.type && (
                <span className="ml-1 text-content-tertiary text-[10px]">
                  · {selectedDimensions.type}
                </span>
              )}
            </div>
            <div className="grid grid-cols-3 gap-2 text-[11px] tabular-nums">
              <div>
                <div className="text-[9px] uppercase text-content-tertiary">L</div>
                <div className="font-semibold text-content-primary">
                  {selectedDimensions.L.toFixed(2)}<span className="text-[9px] text-content-tertiary ml-0.5">m</span>
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-content-tertiary">W</div>
                <div className="font-semibold text-content-primary">
                  {selectedDimensions.W.toFixed(2)}<span className="text-[9px] text-content-tertiary ml-0.5">m</span>
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-content-tertiary">H</div>
                <div className="font-semibold text-content-primary">
                  {selectedDimensions.H.toFixed(2)}<span className="text-[9px] text-content-tertiary ml-0.5">m</span>
                </div>
              </div>
            </div>
            <div className="mt-1.5 pt-1.5 border-t border-border-light text-[10px] text-content-tertiary flex items-center justify-between">
              <span>{t('bim.bbox_volume', { defaultValue: 'BBox volume' })}</span>
              <span className="tabular-nums font-medium text-content-secondary">
                {selectedDimensions.volume.toFixed(2)} m³
              </span>
            </div>
          </div>
        )}

        {/* Snapshot registry popover — toolbar button → projects-level list
            of frozen parquet datasets (replaces the /dashboards page). */}
        {snapshotsOpen && projectId && (
          <BIMSnapshotsPopover
            projectId={projectId}
            onClose={() => setSnapshotsOpen(false)}
          />
        )}

        {/* Asset-info card — anchored bottom-right of the viewport. Hidden
            when the user toggles the "Asset Card" button off in the top
            toolbar or dismisses the card directly. */}
        {(() => {
          if (!assetCardEnabled) return null;
          if (!projectId || !selectedElementId || selectedElementIds.length > 1) return null;
          const el = elements.find((e) => e.id === selectedElementId);
          if (!el) return null;
          const activeModel = models.find((m) => m.id === activeModelId);
          const sidebarOpen = Boolean(activeModelId && !isModelNonReady && elements.length > 0 && boqPanelOpen);
          return (
            <ElementAssetCard
              projectId={projectId}
              elementId={selectedElementId}
              element={{
                id: el.id,
                stable_id: el.stable_id ?? el.id,
                name: el.name ?? null,
                element_type: el.element_type ?? null,
                model_id: activeModelId ?? '',
                model_name: activeModel?.name ?? '',
              }}
              rightPx={sidebarOpen ? 352 : 12}
              bottomPx={24}
              visible
              onDismiss={() => setAssetCardEnabled(false)}
            />
          );
        })()}

        {/* PDF generation indicator — shown when the upload job for the
            active model has a deferred PDF export running on the backend.
            Pure status bar, never blocks interaction with the viewer. */}
        {(() => {
          if (!activeModelId) return null;
          let pdfJob: BIMUploadJob | null = null;
          for (const j of globalUploadJobs.values()) {
            if (j.modelId === activeModelId && (j.pdfStatus === 'generating' || j.pdfStatus === 'failed')) {
              pdfJob = j;
              break;
            }
          }
          if (!pdfJob) return null;
          const failed = pdfJob.pdfStatus === 'failed';
          return (
            <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 pointer-events-none">
              <div className={clsx(
                'flex items-center gap-2.5 px-3.5 py-2 rounded-full border shadow-md backdrop-blur-sm',
                failed
                  ? 'bg-red-50/95 dark:bg-red-950/40 border-red-200 dark:border-red-800 text-red-700 dark:text-red-200'
                  : 'bg-blue-50/95 dark:bg-blue-950/40 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-200',
              )}>
                {failed ? (
                  <AlertCircle size={14} className="shrink-0" />
                ) : (
                  <Loader2 size={14} className="shrink-0 animate-spin" />
                )}
                <span className="text-xs font-medium whitespace-nowrap">
                  {failed
                    ? t('bim.pdf_status_failed', { defaultValue: 'PDF sheet export failed' })
                    : t('bim.pdf_status_generating', { defaultValue: 'Generating PDF sheets in background…' })}
                </span>
                {failed && pdfJob.pdfError && (
                  <span className="text-[10px] text-red-500/80 max-w-xs truncate">
                    {pdfJob.pdfError}
                  </span>
                )}
              </div>
            </div>
          );
        })()}

        {isModelNonReady ? (
          <NonReadyOverlay
            model={activeModel ?? null}
            onUploadConverted={() => {
              if (activeModel) {
                setUploadConvertedName(activeModel.name);
                setUploadOpen(true);
              }
            }}
            onDelete={() => {
              if (activeModel) handleDeleteModel(activeModel.id, activeModel.name);
            }}
          />
        ) : activeModelId ? (
          <>
          <BIMViewer
            modelId={activeModelId}
            projectId={projectId}
            modelName={activeModel?.name}
            selectedElementIds={selectedElementIds}
            onElementSelect={handleElementSelect}
            onSelectionChange={setMultiSelectedIds}
            highlightedIds={highlightedBIMElementIds.length > 0 ? highlightedBIMElementIds : null}
            elements={elements}
            isLoading={elementsQuery.isLoading}
            error={elementsQuery.error ? t('bim.error_load_elements', { defaultValue: 'Failed to load model elements. Check the server connection.' }) : null}
            geometryUrl={geometryUrl}
            showBoundingBoxes={showBoundingBoxes}
            filterPredicate={filterPredicate}
            colorByMode={colorByMode}
            isolatedIds={isolatedIds}
            onIsolationChange={setIsolatedIds}
            onGeometryLoaded={setMeshMatchRatio}
            onAddToBOQ={handleAddToBOQ}
            onUnlinkBOQ={handleUnlinkBOQ}
            onOpenDocument={handleOpenDocument}
            onOpenTask={handleOpenTask}
            onOpenActivity={handleOpenActivity}
            onOpenRequirement={handleOpenRequirement}
            onCreateTask={handleCreateTask}
            onLinkDocument={handleLinkDocument}
            onLinkActivity={handleLinkActivity}
            onLinkRequirement={handleLinkRequirement}
            onSmartFilter={handleSmartFilter}
            leftPanelOpen={filterPanelOpen && elements.length > 0}
            className="h-full"
          />

          {/* Lazy-load info bar — shown when viewing a group subset */}
          {activeGroupId && !fullModelRequested && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-3 px-4 py-2.5 rounded-xl bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm border border-border-light shadow-lg text-sm">
              <Layers size={16} className="text-oe-blue shrink-0" />
              <span className="text-content-secondary">
                {t('bim.group_subset_info', {
                  defaultValue: 'Showing {{count}} elements from group "{{name}}"',
                  count: elementsTotal,
                  name: activeGroupMeta?.name ?? groupParam ?? '...',
                })}
              </span>
              <button
                onClick={() => {
                  setFullModelRequested(true);
                  setActiveGroupId(null);
                  // Strip group param from URL
                  const next = new URLSearchParams(searchParams);
                  next.delete('group');
                  setSearchParams(next, { replace: true });
                }}
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-oe-blue/10 hover:bg-oe-blue/20 text-oe-blue font-medium transition-colors"
              >
                <Globe2 size={14} />
                {t('bim.load_full_model', {
                  defaultValue: 'Load full model ({{total}} elements)',
                  total: activeModel?.element_count?.toLocaleString() ?? '...',
                })}
              </button>
            </div>
          )}
          </>
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Cuboid size={40} className="text-content-quaternary mx-auto mb-3" />
              <p className="text-sm text-content-tertiary">{t('bim.select_model_prompt', { defaultValue: 'Select a model to view' })}</p>
            </div>
          </div>
        )}

        {uploadOpen && (
          <UploadPanel
            projectId={projectId}
            onUploadComplete={handleUploadComplete}
            onClose={() => { setUploadOpen(false); setUploadConvertedName(null); }}
            initialAdvancedMode={!!uploadConvertedName}
            initialModelName={uploadConvertedName || undefined}
          />
        )}

        {/* In-page progress/completion toasts removed: GlobalUploadIndicator
            (mounted in AppLayout) is the single source of truth for upload
            state and survives navigation. Having a second local tracker here
            caused a zombie "Converting CAD model…" toast when UploadPanel set
            stage='converting' and no code path later flipped it to 'ready'. */}

        {/* Low mesh-match warning — shown when the loaded DAE has no per-element
            mapping (e.g. DDC RVT exports with numeric node names), which means
            element filters can't hide individual objects in the viewport. */}
        {/* Low mesh-match warning removed — positional fallback always provides
            workable filtering even when direct name-matching is sparse. */}
        {false && meshMatchRatio !== null && (
          <div className="hidden">
          </div>
        )}
        </div>

        {/* Right-panel tab container (RFC 19 §4.5): Properties / Layers /
            Tools / Groups.
            z-index 15 keeps it below the upload panel (z-30) when both are open. */}
        {activeModelId && !isModelNonReady && elements.length > 0 && boqPanelOpen && (
          <div className="absolute top-0 end-0 h-full z-[15] w-[340px] bg-surface-primary border-s border-border-light flex flex-col">
            <BIMRightPanelTabs
              modelId={activeModelId}
              elements={elements}
              savedGroups={savedGroups}
              projectId={projectId}
              onClose={() => setBoqPanelOpen(false)}
              onIsolateGroup={handleIsolateGroup}
              onHighlightGroup={handleHighlightGroup}
              onLinkGroupToBOQ={handleLinkGroupToBOQ}
              onNavigateToBOQ={handleNavigateToBOQ}
              onDeleteGroup={handleDeleteGroup}
              onGroupUpdated={handleGroupUpdated}
              onHighlightBOQElements={(ids) => {
                if (ids.length > 0) {
                  setIsolatedIds(ids);
                } else {
                  setIsolatedIds(null);
                }
              }}
            />
          </div>
        )}
      </div>

      {/* ── Model Filmstrip (collapsible, auto-hides after 5s) ── */}
      <ModelFilmstrip
        models={models}
        isLoading={modelsQuery.isLoading}
        activeModelId={activeModelId}
        onSelectModel={(id) => { setActiveModelId(id); setSelectedElementId(null); setMultiSelectedIds([]); }}
        onDeleteModel={handleDeleteModel}
        onUpload={() => setUploadOpen(true)}
      />

      {/* BIM ↔ BOQ linking modal — opened from the properties panel
          ("Add to BOQ" button) or the filter panel's quick-takeoff
          action.  Renders a single-element or bulk-element linker. */}
      {linkCandidates && linkCandidates.length > 0 && projectId && (
        <AddToBOQModal
          projectId={projectId}
          modelId={activeModelId ?? ''}
          elements={linkCandidates}
          onClose={() => setLinkCandidates(null)}
          onLinked={() => {
            queryClient.invalidateQueries({ queryKey: ['bim-elements', activeModelId] });
          }}
        />
      )}

      {/* Save-as-group modal — opened from the filter panel "Save as group"
          button.  Captures the current filter criteria + visible element ids
          and persists them as a BIMElementGroup row. */}
      {saveGroupState && projectId && (
        <SaveGroupModal
          projectId={projectId}
          modelId={activeModelId}
          filterCriteria={saveGroupState.filterCriteria}
          elementIds={saveGroupState.elementIds}
          visibleCount={saveGroupState.elementIds.length}
          onClose={() => setSaveGroupState(null)}
          onSaved={() => {
            // SavedGroupModal already invalidates the query; nothing extra here
          }}
        />
      )}

      {/* Inline create-from-element modals — opened from the "+ New" /
          "+ Link" buttons in the cross-module sections of the selected-
          element panel.  Each one POSTs to the relevant module + invalidates
          the bim-elements query so the new link badge appears instantly. */}
      {createTaskFor && projectId && (
        <CreateTaskFromBIMModal
          projectId={projectId}
          elements={createTaskFor}
          onClose={() => setCreateTaskFor(null)}
        />
      )}
      {linkDocumentFor && projectId && (
        <LinkDocumentToBIMModal
          projectId={projectId}
          elements={linkDocumentFor}
          onClose={() => setLinkDocumentFor(null)}
        />
      )}
      {linkActivityFor && projectId && (
        <LinkActivityToBIMModal
          projectId={projectId}
          elements={linkActivityFor}
          onClose={() => setLinkActivityFor(null)}
        />
      )}
      {linkRequirementFor && projectId && (
        <LinkRequirementToBIMModal
          projectId={projectId}
          elements={linkRequirementFor}
          onClose={() => setLinkRequirementFor(null)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
