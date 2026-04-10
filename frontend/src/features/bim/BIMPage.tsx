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
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
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
} from 'lucide-react';
import { Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';
import BIMFilterPanel from './BIMFilterPanel';
import { BIMProcessingProgress, type BIMProcessingStage } from './BIMProcessingProgress';
import { Filter } from 'lucide-react';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchBIMModels,
  fetchBIMModel,
  fetchBIMElements,
  uploadBIMData,
  uploadCADFile,
  getGeometryUrl,
  deleteBIMModel,
} from './api';

/* ── Helpers ─────────────────────────────────────────────────────────── */

const CAD_EXTENSIONS = new Set(['.rvt', '.ifc']);
const DATA_EXTENSIONS = new Set(['.csv', '.xlsx', '.xls']);

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
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-secondary border border-border-light">
      <Icon size={12} className="text-content-quaternary" />
      <span className="text-[10px] font-medium text-content-tertiary">{label}</span>
      <span className="text-[10px] font-bold text-content-primary tabular-nums">{value}</span>
    </div>
  );
}

/* ── Model Card ──────────────────────────────────────────────────────── */

function ModelCard({ model, isActive, onClick, onDelete }: {
  model: BIMModelData; isActive: boolean; onClick: () => void; onDelete?: () => void;
}) {
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
    ? 'Ready'
    : model.status === 'needs_converter'
      ? 'Needs Converter'
      : model.status === 'processing'
        ? 'Processing'
        : model.status === 'error'
          ? 'Error'
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
        <div
          role="button"
          tabIndex={0}
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onDelete?.(); } }}
          className="absolute top-2.5 end-2 p-1 rounded-md text-content-quaternary hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 opacity-0 group-hover:opacity-100 transition-all z-10"
        >
          <Trash2 size={11} />
        </div>
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
          <span className="text-content-quaternary tabular-nums">{model.element_count ?? 0} elements</span>
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

interface ProcessingUpdate {
  stage: BIMProcessingStage;
  fileName?: string;
  fileSize?: string;
  elementCount?: number;
  errorMessage?: string;
}

function UploadPanel({
  projectId,
  onUploadComplete,
  onClose,
  initialAdvancedMode,
  initialModelName,
  onProcessingUpdate,
}: {
  projectId: string;
  onUploadComplete: (modelId: string) => void;
  onClose: () => void;
  initialAdvancedMode?: boolean;
  initialModelName?: string;
  /** Reports stage transitions to the parent so it can render a global
   *  progress card over the viewport. */
  onProcessingUpdate?: (update: ProcessingUpdate | null) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [modelName, setModelName] = useState(initialModelName || '');
  const [discipline, setDiscipline] = useState('architecture');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStage, setUploadStage] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [advancedMode, setAdvancedMode] = useState(initialAdvancedMode || false);
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [geometryFile, setGeometryFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dataInputRef = useRef<HTMLInputElement>(null);
  const geoInputRef = useRef<HTMLInputElement>(null);
  const addToast = useToastStore((s) => s.addToast);

  useEffect(() => { if (initialModelName) setModelName(initialModelName); }, [initialModelName]);
  useEffect(() => { if (initialAdvancedMode) setAdvancedMode(true); }, [initialAdvancedMode]);

  const handleFileSelect = useCallback((f: File) => {
    const ext = getFileExtension(f.name);
    if (!CAD_EXTENSIONS.has(ext) && !DATA_EXTENSIONS.has(ext)) { setUploadError('Unsupported format.'); return; }
    setFile(f);
    setUploadError(ext === '.rvt' ? 'Note: RVT files require DDC cad2data. Consider IFC.' : null);
    if (!modelName) setModelName(f.name.replace(/\.[^.]+$/, ''));
  }, [modelName]);

  const resetForm = useCallback(() => {
    setFile(null); setDataFile(null); setGeometryFile(null); setModelName(''); setUploadError(null);
    [fileInputRef, dataInputRef, geoInputRef].forEach((r) => { if (r.current) r.current.value = ''; });
  }, []);

  const handleUpload = useCallback(async () => {
    if (!projectId) return;
    setUploading(true);
    setUploadError(null);
    setUploadProgress(0);

    // The backend /upload-cad endpoint is synchronous — it runs the whole
    // pipeline inline and only returns when processing is finished. Since
    // there are no intermediate status events we simulate the 5 stages on
    // a timer so the user sees steady progress. If the fetch resolves
    // faster than the timer, we jump to the final stage immediately.
    const activeFile = advancedMode ? dataFile : file;
    const sizeLabel = activeFile ? formatFileSize(activeFile.size) : undefined;
    const fileName = activeFile?.name;
    onProcessingUpdate?.({ stage: 'uploading', fileName, fileSize: sizeLabel });
    setUploadStage('Uploading…');
    setUploadProgress(10);

    // Drive the stepper forward while the fetch is in flight
    const stageSchedule: BIMProcessingStage[] = [
      'uploading',
      'converting',
      'parsing',
      'indexing',
      'linking',
    ];
    let stageIdx = 0;
    const stageTimer = setInterval(() => {
      if (stageIdx < stageSchedule.length - 1) {
        stageIdx += 1;
        onProcessingUpdate?.({
          stage: stageSchedule[stageIdx]!,
          fileName,
          fileSize: sizeLabel,
        });
        setUploadStage(stageSchedule[stageIdx]!);
        setUploadProgress((p) => Math.min(p + 15, 90));
      }
    }, 1500);

    try {
      if (advancedMode && dataFile) {
        const res = await uploadBIMData(
          projectId,
          modelName || 'Imported',
          discipline,
          dataFile,
          geometryFile,
        );
        clearInterval(stageTimer);
        setUploadProgress(100);
        onProcessingUpdate?.({
          stage: 'ready',
          fileName,
          fileSize: sizeLabel,
          elementCount: res.element_count,
        });
        addToast({
          type: 'success',
          title: 'BIM data uploaded',
          message: `${res.element_count} elements`,
        });
        onUploadComplete(res.model_id);
        resetForm();
      } else if (file) {
        const name = modelName || file.name.replace(/\.[^.]+$/, '');
        if (isCADFile(file.name)) {
          const res = await uploadCADFile(projectId, name, discipline, file);
          clearInterval(stageTimer);
          setUploadProgress(100);
          const st = (res as { status?: string }).status || 'processing';
          const cnt = (res as { element_count?: number }).element_count || 0;

          if (st === 'ready') {
            onProcessingUpdate?.({
              stage: 'ready',
              fileName,
              fileSize: sizeLabel,
              elementCount: cnt,
            });
            addToast({
              type: 'success',
              title: 'Model processed',
              message: `${cnt} elements`,
            });
          } else if (st === 'needs_converter') {
            onProcessingUpdate?.({
              stage: 'needs_converter',
              fileName,
              fileSize: sizeLabel,
              errorMessage: `${res.format.toUpperCase()} requires DDC cad2data. Convert to IFC first.`,
            });
            addToast({
              type: 'warning',
              title: 'Converter required',
              message: `${res.format.toUpperCase()} needs DDC cad2data`,
            });
          } else if (st === 'error') {
            onProcessingUpdate?.({
              stage: 'error',
              fileName,
              fileSize: sizeLabel,
              errorMessage: 'Could not extract elements from this CAD file.',
            });
            addToast({
              type: 'error',
              title: 'Processing failed',
              message: 'Could not extract elements',
            });
          } else {
            onProcessingUpdate?.({
              stage: 'ready',
              fileName,
              fileSize: sizeLabel,
              elementCount: cnt,
            });
            addToast({
              type: 'success',
              title: 'File uploaded',
              message: 'Processing queued',
            });
          }
          onUploadComplete(res.model_id);
          // Give the user a moment to read the final stage before closing
          await new Promise((r) => setTimeout(r, 600));
          resetForm();
        } else if (isDataFile(file.name)) {
          const res = await uploadBIMData(projectId, name, discipline, file);
          clearInterval(stageTimer);
          setUploadProgress(100);
          onProcessingUpdate?.({
            stage: 'ready',
            fileName,
            fileSize: sizeLabel,
            elementCount: res.element_count,
          });
          addToast({
            type: 'success',
            title: 'Imported',
            message: `${res.element_count} elements`,
          });
          onUploadComplete(res.model_id);
          resetForm();
        }
      }
    } catch (err) {
      clearInterval(stageTimer);
      const msg = err instanceof Error ? err.message : String(err);
      setUploadError(msg);
      setUploadProgress(0);
      onProcessingUpdate?.({
        stage: 'error',
        fileName,
        fileSize: sizeLabel,
        errorMessage: msg,
      });
      addToast({ type: 'error', title: 'Upload failed', message: msg });
    } finally {
      clearInterval(stageTimer);
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
    onUploadComplete,
    onProcessingUpdate,
    addToast,
    resetForm,
  ]);

  const canUpload = advancedMode ? !!dataFile && !uploading : !!file && !uploading;
  const disciplines = [
    { v: 'architecture', l: 'Architecture' }, { v: 'structural', l: 'Structural' },
    { v: 'mechanical', l: 'Mechanical' }, { v: 'electrical', l: 'Electrical' },
    { v: 'plumbing', l: 'Plumbing' }, { v: 'fire_protection', l: 'Fire Protection' },
    { v: 'civil', l: 'Civil' }, { v: 'mixed', l: 'Multi-discipline' },
  ];

  return (
    <div className="absolute top-0 end-0 h-full w-[380px] bg-surface-primary/95 backdrop-blur-xl border-s border-border-light shadow-2xl z-30 flex flex-col animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-border-light">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-oe-blue/10 flex items-center justify-center">
            <Upload size={16} className="text-oe-blue" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-content-primary">Upload Model</h2>
            <p className="text-[10px] text-content-quaternary">IFC, RVT, CSV, Excel</p>
          </div>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {!advancedMode ? (
          <label
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
                <button type="button" onClick={(e) => { e.preventDefault(); setFile(null); setUploadError(null); if (fileInputRef.current) fileInputRef.current.value = ''; }} className="text-[10px] text-content-tertiary hover:text-red-500 underline">Remove</button>
              </>
            ) : (
              <>
                <div className="w-12 h-12 rounded-xl bg-surface-secondary border border-border-light flex items-center justify-center"><FileUp size={22} className="text-content-quaternary" /></div>
                <p className="text-sm font-medium text-content-primary">Drop file here</p>
                <p className="text-[10px] text-content-quaternary">Revit (.rvt), IFC (.ifc) &middot; Max 500 MB</p>
              </>
            )}
            <input ref={fileInputRef} type="file" accept=".rvt,.ifc,.csv,.xlsx,.xls" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileSelect(f); }} />
          </label>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col items-center gap-2 border-2 border-dashed border-border-medium rounded-xl p-4 text-center cursor-pointer hover:border-oe-blue/50 hover:bg-surface-secondary transition-all">
              <Database size={20} className="text-content-quaternary" />
              <span className="text-[11px] font-medium text-content-primary">Element Data</span>
              <span className="text-[9px] text-content-quaternary">CSV / Excel</span>
              {dataFile && <Badge variant="blue" size="sm">{dataFile.name}</Badge>}
              <input ref={dataInputRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => { setDataFile(e.target.files?.[0] ?? null); if (e.target.files?.[0] && !modelName) setModelName(e.target.files[0].name.replace(/\.\w+$/, '')); }} />
            </label>
            <label className="flex flex-col items-center gap-2 border-2 border-dashed border-border-medium rounded-xl p-4 text-center cursor-pointer hover:border-oe-blue/50 hover:bg-surface-secondary transition-all">
              <FileBox size={20} className="text-content-quaternary" />
              <span className="text-[11px] font-medium text-content-primary">3D Geometry</span>
              <span className="text-[9px] text-content-quaternary">DAE / COLLADA</span>
              {geometryFile && <Badge variant="blue" size="sm">{geometryFile.name}</Badge>}
              <input ref={geoInputRef} type="file" accept=".dae,.glb,.gltf" className="hidden" onChange={(e) => setGeometryFile(e.target.files?.[0] ?? null)} />
            </label>
          </div>
        )}

        <div>
          <label className="block text-[10px] font-semibold text-content-tertiary mb-1.5 uppercase tracking-wider">Model Name</label>
          <input type="text" className="w-full text-sm py-2 px-3 rounded-lg border border-border-light bg-surface-secondary text-content-primary placeholder-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue" placeholder="e.g. Building A" value={modelName} onChange={(e) => setModelName(e.target.value)} />
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-content-tertiary mb-1.5 uppercase tracking-wider">Discipline</label>
          <select className="w-full text-sm py-2 px-3 rounded-lg border border-border-light bg-surface-secondary text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue" value={discipline} onChange={(e) => setDiscipline(e.target.value)}>
            {disciplines.map((d) => <option key={d.v} value={d.v}>{d.l}</option>)}
          </select>
        </div>

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
          {advancedMode ? 'Switch to simple mode' : 'Already converted? Upload data + geometry separately'}
        </button>
      </div>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-border-light">
        <button onClick={handleUpload} disabled={!canUpload} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-30 disabled:cursor-not-allowed bg-oe-blue text-white hover:bg-oe-blue-dark active:scale-[0.98] shadow-sm hover:shadow-md">
          {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
          {uploading ? 'Uploading...' : 'Upload Model'}
        </button>
      </div>
    </div>
  );
}

/* ── Non-Ready Model Overlay ─────────────────────────────────────────── */

function NonReadyOverlay({ model, onUploadConverted, onDelete }: {
  model: BIMModelData; onUploadConverted: () => void; onDelete: () => void;
}) {
  const fmt = (model.model_format || model.format || '').toUpperCase();
  const configs = {
    processing: { icon: <Loader2 size={32} className="text-blue-500 animate-spin" />, bg: 'bg-blue-50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-800', title: 'Processing Model...', desc: `Extracting elements from your ${fmt} file. This may take a moment.` },
    needs_converter: { icon: <AlertTriangle size={32} className="text-amber-500" />, bg: 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800', title: 'Converter Required', desc: `${fmt} files require DDC cad2data for extraction. Convert to IFC first, or upload pre-converted data.` },
    error: { icon: <AlertCircle size={32} className="text-red-500" />, bg: 'bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800', title: 'Processing Failed', desc: 'Could not extract elements. Try converting to IFC first or upload data manually.' },
  };
  const c = configs[model.status as keyof typeof configs] ?? configs.error;

  return (
    <div className="flex flex-col items-center justify-center h-full bg-surface-secondary">
      <div className="text-center max-w-sm px-6">
        <div className={`mx-auto w-20 h-20 rounded-2xl ${c.bg} border flex items-center justify-center mb-5`}>{c.icon}</div>
        <h2 className="text-lg font-bold text-content-primary mb-2">{c.title}</h2>
        <p className="text-sm text-content-secondary mb-2">{c.desc}</p>
        <p className="text-[11px] text-content-quaternary mb-6">{model.name}{model.file_size ? ` · ${formatFileSize(model.file_size)}` : ''}</p>
        <div className="flex items-center justify-center gap-3">
          <button onClick={onUploadConverted} className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-oe-blue text-white text-sm font-semibold hover:bg-oe-blue-dark transition-colors shadow-sm">
            <UploadCloud size={15} /> Upload Converted Data
          </button>
          <button onClick={onDelete} className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-surface-primary border border-border-light text-content-secondary text-sm font-medium hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-colors">
            <Trash2 size={15} /> Delete
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Landing Page ────────────────────────────────────────────────────── */

function LandingPage({ projectId, onUploadComplete, breadcrumbItems }: {
  projectId: string; onUploadComplete: (modelId: string) => void; breadcrumbItems: { label: string; to?: string }[];
}) {
  const [file, setFile] = useState<File | null>(null);
  const [modelName, setModelName] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const addToast = useToastStore((s) => s.addToast);

  const handleUpload = useCallback(async () => {
    if (!file || !projectId) return;
    setUploading(true); setUploadError(null);
    try {
      const name = modelName || file.name.replace(/\.[^.]+$/, '');
      if (isCADFile(file.name)) {
        setUploadProgress(20);
        const iv = setInterval(() => setUploadProgress((p) => Math.min(p + 5, 85)), 500);
        const res = await uploadCADFile(projectId, name, 'architecture', file);
        clearInterval(iv); setUploadProgress(100);
        const st = (res as any).status || 'processing';
        const cnt = (res as any).element_count || 0;
        if (st === 'ready') addToast({ type: 'success', title: 'Model ready', message: `${cnt} elements` });
        else addToast({ type: 'success', title: 'Uploaded', message: res.format.toUpperCase() });
        onUploadComplete(res.model_id);
      } else if (isDataFile(file.name)) {
        setUploadProgress(40);
        const res = await uploadBIMData(projectId, name, 'architecture', file);
        setUploadProgress(100);
        addToast({ type: 'success', title: 'Imported', message: `${res.element_count} elements` });
        onUploadComplete(res.model_id);
      }
    } catch (err) { setUploadError(err instanceof Error ? err.message : String(err)); }
    finally { setUploading(false); }
  }, [file, projectId, modelName, onUploadComplete, addToast]);

  const features = [
    { icon: Eye, color: 'bg-blue-50 dark:bg-blue-950/20 border-blue-100 dark:border-blue-800', ic: 'text-blue-500', title: '3D Visualization', desc: 'Interactive Three.js viewer with storey filtering, discipline coloring, and element selection.' },
    { icon: Layers, color: 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-100 dark:border-emerald-800', ic: 'text-emerald-500', title: 'Element Extraction', desc: 'Walls, slabs, columns, beams, MEP — with properties, areas, volumes, and classification.' },
    { icon: Link2, color: 'bg-violet-50 dark:bg-violet-950/20 border-violet-100 dark:border-violet-800', ic: 'text-violet-500', title: 'BOQ Linking', desc: 'Connect BIM elements to cost items for automated quantity verification and 5D take-off.' },
    { icon: Ruler, color: 'bg-orange-50 dark:bg-orange-950/20 border-orange-100 dark:border-orange-800', ic: 'text-orange-500', title: 'Quantity Maps', desc: 'Define rules to extract area, volume, and length — apply to your entire model at once.' },
    { icon: Building2, color: 'bg-pink-50 dark:bg-pink-950/20 border-pink-100 dark:border-pink-800', ic: 'text-pink-500', title: 'Model Comparison', desc: 'Compare versions to detect added, removed, and modified elements automatically.' },
    { icon: Globe2, color: 'bg-cyan-50 dark:bg-cyan-950/20 border-cyan-100 dark:border-cyan-800', ic: 'text-cyan-500', title: 'Format Agnostic', desc: 'IFC processed instantly. RVT via DDC cad2data. CSV/Excel for pre-converted data.' },
  ];

  return (
    <div className="flex flex-col -mx-3 sm:-mx-4 lg:-mx-6 -mt-4 -mb-4 border-s border-border-light" style={{ height: 'calc(100vh - 56px)' }}>
      <div className="px-6 pt-4 pb-3 border-b border-border-light"><Breadcrumb items={breadcrumbItems} /></div>
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-12">
          {/* Hero */}
          <div className="text-center mb-12">
            <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-oe-blue/10 to-blue-100 dark:to-blue-950/30 border border-oe-blue/20 flex items-center justify-center mb-5 shadow-lg shadow-oe-blue/5">
              <Cuboid size={36} className="text-oe-blue" />
            </div>
            <h1 className="text-3xl font-bold text-content-primary tracking-tight">BIM 3D Viewer</h1>
            <p className="text-base text-content-secondary mt-3 max-w-lg mx-auto leading-relaxed">
              Upload IFC or Revit files to visualize building elements, extract quantities, and link to your Bill of Quantities.
            </p>
          </div>

          {/* Upload */}
          <div className="max-w-lg mx-auto mb-12">
            <label
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) { setFile(f); if (!modelName) setModelName(f.name.replace(/\.[^.]+$/, '')); } }}
              onDragOver={(e) => e.preventDefault()}
              className={`flex flex-col items-center gap-4 border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all ${
                file ? 'border-oe-blue/40 bg-oe-blue/5' : 'border-border-medium hover:border-oe-blue/50 hover:bg-surface-secondary'
              }`}
            >
              {file ? (
                <>
                  <div className="w-14 h-14 rounded-xl bg-oe-blue/10 border border-oe-blue/20 flex items-center justify-center"><CheckCircle2 size={24} className="text-oe-blue" /></div>
                  <p className="text-base font-semibold text-content-primary">{file.name}</p>
                  <p className="text-xs text-content-quaternary">{formatFileSize(file.size)}</p>
                </>
              ) : (
                <>
                  <div className="w-14 h-14 rounded-xl bg-surface-secondary border border-border-light flex items-center justify-center"><FileUp size={24} className="text-content-quaternary" /></div>
                  <p className="text-base font-semibold text-content-primary">Drop your file here</p>
                  <p className="text-xs text-content-quaternary">IFC, Revit, CSV, or Excel &middot; Max 500 MB</p>
                </>
              )}
              <input ref={fileInputRef} type="file" accept=".rvt,.ifc,.csv,.xlsx,.xls" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); if (!modelName) setModelName(f.name.replace(/\.[^.]+$/, '')); } }} />
            </label>
            {file && (
              <div className="mt-4 space-y-3">
                <input type="text" className="w-full text-sm py-2.5 px-4 rounded-xl border border-border-light bg-surface-secondary text-content-primary placeholder-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue" placeholder="Model name" value={modelName} onChange={(e) => setModelName(e.target.value)} />
                {uploading && <div className="h-1.5 rounded-full bg-surface-tertiary overflow-hidden"><div className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-300" style={{ width: `${uploadProgress}%` }} /></div>}
                {uploadError && <p className="text-xs text-red-500">{uploadError}</p>}
                <button onClick={handleUpload} disabled={uploading} className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-50 bg-oe-blue text-white hover:bg-oe-blue-dark active:scale-[0.98] shadow-sm hover:shadow-md">
                  {uploading ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
                  {uploading ? 'Processing...' : 'Upload & Process'}
                </button>
              </div>
            )}
          </div>

          {/* Features */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {features.map((f, i) => (
              <div key={i} className="rounded-xl border border-border-light bg-surface-primary p-5 hover:shadow-md transition-shadow">
                <div className={`w-10 h-10 rounded-lg ${f.color} border flex items-center justify-center mb-3`}><f.icon size={18} className={f.ic} /></div>
                <h3 className="text-sm font-semibold text-content-primary mb-1">{f.title}</h3>
                <p className="text-xs text-content-tertiary leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
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
  const { projectId: urlProjectId } = useParams<{ projectId: string }>();
  const contextProjectId = useProjectContextStore((s) => s.activeProjectId);
  const contextProjectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = urlProjectId || contextProjectId || '';

  const [activeModelId, setActiveModelId] = useState<string | null>(null);
  const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadConvertedName, setUploadConvertedName] = useState<string | null>(null);
  const [showUploadOverride, setShowUploadOverride] = useState<boolean | null>(null);
  const [filterPanelOpen, setFilterPanelOpen] = useState(true);
  const [filterPredicate, setFilterPredicate] = useState<
    ((el: BIMElementData) => boolean) | null
  >(null);
  const [visibleElementCount, setVisibleElementCount] = useState<number | null>(null);
  const [colorByMode, setColorByMode] = useState<'default' | 'storey' | 'type'>('default');
  const [isolatedIds, setIsolatedIds] = useState<string[] | null>(null);
  const [processing, setProcessing] = useState<ProcessingUpdate | null>(null);
  const [meshMatchRatio, setMeshMatchRatio] = useState<number | null>(null);
  const addToast = useToastStore((s) => s.addToast);

  const modelsQuery = useQuery({ queryKey: ['bim-models', projectId], queryFn: () => fetchBIMModels(projectId), enabled: !!projectId });
  const models = modelsQuery.data?.items ?? [];
  const hasModels = models.length > 0;
  const showFullPageUpload = showUploadOverride !== null ? showUploadOverride : !hasModels;

  useEffect(() => { if (hasModels && showUploadOverride === false) setShowUploadOverride(null); }, [hasModels, showUploadOverride]);

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

  useEffect(() => { if (models.length && !activeModelId) setActiveModelId(models[0]!.id); }, [models, activeModelId]);

  // Reset transient viewer state when switching between models
  useEffect(() => {
    setMeshMatchRatio(null);
    setFilterPredicate(null);
    setVisibleElementCount(null);
    setIsolatedIds(null);
    setColorByMode('default');
  }, [activeModelId]);

  // Auto-dismiss the processing progress card 4 seconds after the model is
  // ready (errors stay until the user clicks close).
  useEffect(() => {
    if (processing?.stage !== 'ready') return;
    const timer = setTimeout(() => setProcessing(null), 4000);
    return () => clearTimeout(timer);
  }, [processing?.stage]);

  const elementsQuery = useQuery({
    queryKey: ['bim-elements', activeModelId],
    queryFn: () => fetchBIMElements(activeModelId!),
    enabled: !!activeModelId && activeModel?.status === 'ready',
  });
  const elements: BIMElementData[] = elementsQuery.data?.items ?? [];

  const geometryUrl = useMemo(() => {
    if (!activeModelId || activeModel?.status !== 'ready') return null;
    if ((activeModel?.element_count ?? 0) > 0 || elements.some((el) => !!el.mesh_ref)) return getGeometryUrl(activeModelId);
    return null;
  }, [activeModelId, activeModel, elements]);

  const handleElementSelect = useCallback((id: string | null) => setSelectedElementId(id), []);

  // Stable callback for BIMFilterPanel — uses functional setState so it
  // doesn't need to track filterPredicate in its dependency list.
  const handleFilterChange = useCallback(
    (predicate: (el: BIMElementData) => boolean, visibleCount: number) => {
      setFilterPredicate(() => predicate);
      setVisibleElementCount(visibleCount);
    },
    [],
  );

  const handleFilterElementClick = useCallback((elementId: string) => {
    setSelectedElementId(elementId);
  }, []);

  const handleUploadComplete = useCallback((modelId: string) => {
    setActiveModelId(modelId); setShowUploadOverride(false); setSelectedElementId(null);
    setUploadOpen(false); setUploadConvertedName(null);
    queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
  }, [queryClient, projectId]);

  const handleDeleteModel = useCallback(async (modelId: string, name: string) => {
    if (!window.confirm(`Delete "${name}"? All elements will be removed.`)) return;
    try {
      await deleteBIMModel(modelId);
      addToast({ type: 'success', title: 'Model deleted', message: name });
      if (activeModelId === modelId) { setActiveModelId(null); setSelectedElementId(null); }
      queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
    } catch (err) { addToast({ type: 'error', title: 'Delete failed', message: err instanceof Error ? err.message : String(err) }); }
  }, [activeModelId, addToast, queryClient, projectId]);

  const breadcrumbItems = useMemo(() => {
    const items: { label: string; to?: string }[] = [{ label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' }];
    if (projectId && contextProjectName) items.push({ label: contextProjectName, to: `/projects/${projectId}` });
    items.push({ label: 'BIM Viewer' });
    return items;
  }, [t, projectId, contextProjectName]);

  const selectedElementIds = useMemo(() => (selectedElementId ? [selectedElementId] : []), [selectedElementId]);

  if (!projectId) {
    return (
      <div className="flex items-center justify-center -mx-3 sm:-mx-4 lg:-mx-6 -mt-4 -mb-4 border-s border-border-light" style={{ height: 'calc(100vh - 56px)' }}>
        <EmptyState icon={<FolderOpen size={32} />} title="No project selected" description="Select a project to view BIM models." />
      </div>
    );
  }

  if (showFullPageUpload && !modelsQuery.isLoading) {
    return <LandingPage projectId={projectId} onUploadComplete={handleUploadComplete} breadcrumbItems={breadcrumbItems} />;
  }

  const storeys = new Set(elements.map((e) => e.storey).filter(Boolean));
  const discips = new Set(elements.map((e) => e.discipline).filter(Boolean));
  const isModelNonReady = activeModel && ['processing', 'needs_converter', 'error'].includes(activeModel.status);

  return (
    <div className="flex flex-col -mx-3 sm:-mx-4 lg:-mx-6 -mt-4 -mb-4 border-s border-border-light" style={{ height: 'calc(100vh - 56px)' }}>
      {/* ── Header ── */}
      <div className="relative z-20 px-5 py-3 flex items-center justify-between border-b border-border-light bg-surface-primary">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-oe-blue/10 to-blue-50 dark:to-blue-950/20 border border-oe-blue/15 flex items-center justify-center">
              <Cuboid size={18} className="text-oe-blue" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-content-primary">BIM Viewer</h1>
              {activeModel && <p className="text-[10px] text-content-tertiary truncate max-w-[160px]">{activeModel.name}</p>}
            </div>
          </div>
          {elements.length > 0 && (
            <div className="flex items-center gap-2 ms-2">
              <StatPill icon={Box} label="Elements" value={elements.length} />
              {storeys.size > 0 && <StatPill icon={Layers} label="Storeys" value={storeys.size} />}
              {discips.size > 0 && <StatPill icon={Sparkles} label="Disciplines" value={discips.size} />}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
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
              >
                <Filter size={13} />
                {t('bim.filter_button', { defaultValue: 'Filter' })}
                {visibleElementCount !== null && visibleElementCount < elements.length && (
                  <span className="text-[10px] bg-oe-blue text-white rounded-full px-1.5 py-0 tabular-nums">
                    {visibleElementCount}
                  </span>
                )}
              </button>

              {/* Color-by selector */}
              <select
                value={colorByMode}
                onChange={(e) => setColorByMode(e.target.value as 'default' | 'storey' | 'type')}
                title={t('bim.color_by', { defaultValue: 'Color by' })}
                className="text-[11px] py-1.5 px-2 rounded-lg border border-border-light bg-surface-secondary text-content-secondary hover:bg-surface-tertiary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              >
                <option value="default">{t('bim.color_default', { defaultValue: 'Color: Category' })}</option>
                <option value="storey">{t('bim.color_storey', { defaultValue: 'Color: Storey' })}</option>
                <option value="type">{t('bim.color_type', { defaultValue: 'Color: Type' })}</option>
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
              <button onClick={() => navigate('/boq')} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-content-secondary bg-surface-secondary border border-border-light hover:bg-surface-tertiary transition-colors">
                <Link2 size={13} /> Link to BOQ
              </button>
              <button onClick={() => navigate('/schedule')} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-content-secondary bg-surface-secondary border border-border-light hover:bg-surface-tertiary transition-colors">
                <CalendarDays size={13} /> 4D Schedule
              </button>
            </>
          )}
          <button onClick={() => setUploadOpen((p) => !p)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-oe-blue text-white hover:bg-oe-blue-dark transition-colors shadow-sm">
            <Plus size={13} /> Add Model
          </button>
        </div>
      </div>

      {/* ── 3D Viewport with filter sidebar ── */}
      <div className="flex-1 min-h-0 relative bg-surface-secondary flex">
        {/* Filter sidebar — only when model has loaded elements */}
        {activeModelId && !isModelNonReady && elements.length > 0 && filterPanelOpen && (
          <div className="shrink-0 h-full">
            <BIMFilterPanel
              elements={elements}
              modelFormat={activeModel?.model_format || activeModel?.format}
              onFilterChange={handleFilterChange}
              onClose={() => setFilterPanelOpen(false)}
              onElementClick={handleFilterElementClick}
            />
          </div>
        )}

        <div className="flex-1 min-w-0 relative">
        {isModelNonReady ? (
          <NonReadyOverlay
            model={activeModel!}
            onUploadConverted={() => { setUploadConvertedName(activeModel!.name); setUploadOpen(true); }}
            onDelete={() => handleDeleteModel(activeModel!.id, activeModel!.name)}
          />
        ) : activeModelId ? (
          <BIMViewer
            modelId={activeModelId}
            projectId={projectId}
            selectedElementIds={selectedElementIds}
            onElementSelect={handleElementSelect}
            elements={elements}
            isLoading={elementsQuery.isLoading}
            error={elementsQuery.error ? 'Failed to load model elements. Check the server connection.' : null}
            geometryUrl={geometryUrl}
            filterPredicate={filterPredicate}
            colorByMode={colorByMode}
            isolatedIds={isolatedIds}
            onGeometryLoaded={setMeshMatchRatio}
            className="h-full"
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <Cuboid size={40} className="text-content-quaternary mx-auto mb-3" />
              <p className="text-sm text-content-tertiary">Select a model to view</p>
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
            onProcessingUpdate={setProcessing}
          />
        )}

        {/* Processing progress card (bottom-right of viewport) */}
        {processing && (
          <div className="absolute bottom-6 end-6 z-40 pointer-events-none">
            <BIMProcessingProgress
              stage={processing.stage}
              fileName={processing.fileName}
              fileSize={processing.fileSize}
              elementCount={processing.elementCount}
              errorMessage={processing.errorMessage}
              onClose={() => setProcessing(null)}
            />
          </div>
        )}

        {/* Low mesh-match warning — shown when the loaded DAE has no per-element
            mapping (e.g. DDC RVT exports with numeric node names), which means
            element filters can't hide individual objects in the viewport. */}
        {meshMatchRatio !== null && meshMatchRatio < 0.02 && elements.length > 0 && !isModelNonReady && (
          <div className="absolute bottom-3 start-1/2 -translate-x-1/2 z-30 pointer-events-auto">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 shadow-sm">
              <AlertTriangle size={12} className="text-amber-600 dark:text-amber-400 shrink-0" />
              <span className="text-[11px] text-amber-800 dark:text-amber-300">
                {t('bim.no_mesh_mapping', {
                  defaultValue:
                    'Per-element filtering unavailable for this model (no stable_id → mesh mapping). Explorer still works.',
                })}
              </span>
              <button
                onClick={() => setMeshMatchRatio(null)}
                className="text-amber-700 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-200"
                aria-label="Dismiss"
              >
                <X size={11} />
              </button>
            </div>
          </div>
        )}
        </div>
      </div>

      {/* ── Model Filmstrip ── */}
      <div className="shrink-0 border-t border-border-light bg-surface-primary">
        <div className="flex items-center gap-3 px-5 py-3 overflow-x-auto">
          <span className="text-[10px] font-bold text-content-quaternary uppercase tracking-wider shrink-0">Models</span>
          {modelsQuery.isLoading ? (
            <Loader2 size={14} className="animate-spin text-content-quaternary" />
          ) : models.length ? (
            models.map((m) => (
              <ModelCard key={m.id} model={m} isActive={m.id === activeModelId}
                onClick={() => { setActiveModelId(m.id); setSelectedElementId(null); }}
                onDelete={() => handleDeleteModel(m.id, m.name)} />
            ))
          ) : (
            <span className="text-[11px] text-content-quaternary">No models uploaded yet</span>
          )}
        </div>
      </div>
    </div>
  );
}
