/**
 * BIMPage — redesigned split-view BIM Hub page.
 *
 * Left panel: model list + element tree (grouped by storey > discipline > type).
 * Right panel: Three.js BIM Viewer.
 *
 * Upload: single unified drop zone that accepts ALL file types (CAD + data).
 * Auto-detects format from extension and routes to the correct endpoint.
 * "Advanced mode" reveals separate data + geometry upload (collapsed by default).
 *
 * Route: /projects/:projectId/bim  or  /bim  (uses project context store)
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
  Info,
  CalendarDays,
  Trash2,
} from 'lucide-react';
import { Button, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import {
  fetchBIMModels,
  fetchBIMModel,
  fetchBIMElements,
  uploadBIMData,
  uploadCADFile,
  getGeometryUrl,
  deleteBIMModel,
} from './api';

/* ── Constants ────────────────────────────────────────────────────────── */

const CAD_EXTENSIONS = new Set(['.rvt', '.ifc']);
const DATA_EXTENSIONS = new Set(['.csv', '.xlsx', '.xls']);

function getFileExtension(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot).toLowerCase() : '';
}

function isCADFile(filename: string): boolean {
  return CAD_EXTENSIONS.has(getFileExtension(filename));
}

function isDataFile(filename: string): boolean {
  return DATA_EXTENSIONS.has(getFileExtension(filename));
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

/* ── Model Card ───────────────────────────────────────────────────────── */

function ModelCard({
  model,
  isActive,
  onClick,
  onDelete,
}: {
  model: BIMModelData;
  isActive: boolean;
  onClick: () => void;
  onDelete?: () => void;
}) {
  const { t } = useTranslation();
  const formatLabel = (model.model_format || model.format || '').toUpperCase();
  const isProcessing = model.status === 'processing';

  return (
    <div
      className={`shrink-0 w-52 text-start rounded-lg border transition-colors relative group ${
        isActive
          ? 'border-oe-blue bg-oe-blue-subtle'
          : 'border-border-light hover:border-border-medium hover:bg-surface-secondary'
      } ${isProcessing ? 'border-t-2 border-t-amber-400' : ''}`}
    >
      {/* Delete button */}
      {onDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="absolute top-1.5 end-1.5 p-1 rounded text-content-quaternary hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 opacity-0 group-hover:opacity-100 transition-opacity z-10"
          title={t('bim.delete_model', { defaultValue: 'Delete model' })}
        >
          <Trash2 size={12} />
        </button>
      )}

      <button onClick={onClick} className="w-full text-start p-2.5">
        <div className="flex items-center gap-1.5">
          <Box size={14} className={isActive ? 'text-oe-blue' : 'text-content-tertiary'} />
          <span className="text-xs font-medium text-content-primary truncate">{model.name}</span>
        </div>
        <div className="flex items-center gap-1.5 mt-1">
          <Badge
            variant={
              model.status === 'ready'
                ? 'success'
                : model.status === 'processing'
                  ? 'warning'
                  : model.status === 'error'
                    ? 'error'
                    : 'neutral'
            }
            size="sm"
          >
            {isProcessing ? (
              <span className="flex items-center gap-1">
                <Loader2 size={10} className="animate-spin" />
                {t('bim.status_processing', { defaultValue: 'Processing' })}
              </span>
            ) : (
              model.status
            )}
          </Badge>
          {formatLabel && (
            <span className="text-2xs text-content-tertiary">{formatLabel}</span>
          )}
          <span className="text-2xs text-content-quaternary tabular-nums ms-auto">
            {model.element_count ?? 0} el.
          </span>
        </div>
      </button>
    </div>
  );
}

/* ── Unified Upload Section ───────────────────────────────────────────── */

function UnifiedUploadSection({
  projectId,
  onUploadComplete,
  compact,
  initialAdvancedMode,
  initialModelName,
}: {
  projectId: string;
  onUploadComplete: (modelId: string) => void;
  compact?: boolean;
  initialAdvancedMode?: boolean;
  initialModelName?: string;
}) {
  const { t } = useTranslation();

  const [file, setFile] = useState<File | null>(null);
  const [modelName, setModelName] = useState(initialModelName || '');
  const [discipline, setDiscipline] = useState('architecture');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStage, setUploadStage] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const [advancedMode, setAdvancedMode] = useState(initialAdvancedMode || false);

  useEffect(() => {
    if (initialModelName) setModelName(initialModelName);
  }, [initialModelName]);

  useEffect(() => {
    if (initialAdvancedMode) setAdvancedMode(true);
  }, [initialAdvancedMode]);
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [geometryFile, setGeometryFile] = useState<File | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const dataInputRef = useRef<HTMLInputElement>(null);
  const geoInputRef = useRef<HTMLInputElement>(null);
  const addToast = useToastStore((s) => s.addToast);

  const cadAcceptedExtensions = '.rvt,.ifc';
  const addQueueTask = useUploadQueueStore((s) => s.addTask);
  const updateQueueTask = useUploadQueueStore((s) => s.updateTask);

  const handleFileSelect = useCallback(
    (selectedFile: File) => {
      const ext = getFileExtension(selectedFile.name);
      if (!CAD_EXTENSIONS.has(ext) && !DATA_EXTENSIONS.has(ext)) {
        setUploadError(
          t('bim.unsupported_format', {
            defaultValue:
              'Unsupported file format. Use IFC, RVT, CSV, or Excel files.',
          }),
        );
        return;
      }
      setFile(selectedFile);
      setUploadError(null);
      // Auto-fill model name from filename (strip extension)
      if (!modelName) {
        const baseName = selectedFile.name.replace(/\.[^.]+$/, '');
        setModelName(baseName);
      }
    },
    [modelName, t],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selectedFile = e.target.files?.[0] ?? null;
      if (selectedFile) handleFileSelect(selectedFile);
    },
    [handleFileSelect],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const droppedFile = e.dataTransfer.files?.[0] ?? null;
      if (droppedFile) handleFileSelect(droppedFile);
    },
    [handleFileSelect],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleDataFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0] ?? null;
      setDataFile(f);
      setUploadError(null);
      if (f && !modelName) {
        const baseName = f.name.replace(/\.(csv|xlsx|xls)$/i, '');
        setModelName(baseName);
      }
    },
    [modelName],
  );

  const handleGeoFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setGeometryFile(e.target.files?.[0] ?? null);
    setUploadError(null);
  }, []);

  const resetForm = useCallback(() => {
    setFile(null);
    setDataFile(null);
    setGeometryFile(null);
    setModelName('');
    setUploadError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (dataInputRef.current) dataInputRef.current.value = '';
    if (geoInputRef.current) geoInputRef.current.value = '';
  }, []);

  const handleRemoveFile = useCallback(() => {
    setFile(null);
    setUploadError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const handleUpload = useCallback(async () => {
    if (!projectId) {
      setUploadError(t('bim.select_project_first', { defaultValue: 'Please select a project first' }));
      return;
    }

    setUploading(true);
    setUploadError(null);
    setUploadProgress(0);

    try {
      if (advancedMode) {
        if (!dataFile) return;
        setUploadStage(t('bim.stage_uploading', { defaultValue: 'Uploading data...' }));
        setUploadProgress(30);
        const result = await uploadBIMData(projectId, modelName || 'Imported Model', discipline, dataFile, geometryFile);
        setUploadProgress(100);
        setUploadStage(t('bim.stage_done', { defaultValue: 'Done!' }));
        addToast({
          type: 'success',
          title: t('bim.upload_success', { defaultValue: 'BIM data uploaded' }),
          message: `${result.element_count} elements imported`,
        });
        onUploadComplete(result.model_id);
        resetForm();
      } else if (file) {
        const name = modelName || file.name.replace(/\.[^.]+$/, '');
        if (isCADFile(file.name)) {
          setUploadStage(t('bim.stage_uploading_cad', { defaultValue: 'Uploading CAD file...' }));
          setUploadProgress(20);

          // Simulate progress during upload
          const progressInterval = setInterval(() => {
            setUploadProgress((p) => Math.min(p + 5, 85));
          }, 500);

          const result = await uploadCADFile(projectId, name, discipline, file);
          clearInterval(progressInterval);

          setUploadProgress(90);
          setUploadStage(t('bim.stage_processing', { defaultValue: 'Server processing...' }));

          // Brief pause to show 90%
          await new Promise((r) => setTimeout(r, 500));
          setUploadProgress(100);
          setUploadStage(
            t('bim.stage_queued', {
              defaultValue: '{{format}} uploaded — server is parsing elements',
              format: result.format.toUpperCase(),
            }).replace('{{format}}', result.format.toUpperCase()),
          );

          const elemCount = (result as any).element_count || 0;
          const isReady = (result as any).status === 'ready';

          addToast({
            type: 'success',
            title: isReady
              ? t('bim.processing_complete', { defaultValue: 'IFC processed successfully' })
              : t('bim.cad_upload_success', { defaultValue: 'CAD file uploaded' }),
            message: isReady
              ? `${elemCount} elements extracted from ${result.format.toUpperCase()} file`
              : `${result.format.toUpperCase()} file uploaded. Processing queued.`,
          });

          if (isReady) {
            setUploadStage(`${elemCount} elements extracted — model ready`);
          }

          onUploadComplete(result.model_id);
          await new Promise((r) => setTimeout(r, 2000));
          resetForm();
        } else if (isDataFile(file.name)) {
          setUploadStage(t('bim.stage_importing', { defaultValue: 'Importing elements...' }));
          setUploadProgress(40);
          const result = await uploadBIMData(projectId, name, discipline, file);
          setUploadProgress(100);
          setUploadStage(`${result.element_count} elements imported`);
          addToast({
            type: 'success',
            title: t('bim.upload_success', { defaultValue: 'BIM data uploaded' }),
            message: `${result.element_count} elements imported`,
          });
          onUploadComplete(result.model_id);
          await new Promise((r) => setTimeout(r, 1500));
          resetForm();
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setUploadError(msg);
      setUploadProgress(0);
      setUploadStage('');
      addToast({ type: 'error', title: t('bim.upload_failed', { defaultValue: 'Upload failed' }), message: msg });
    } finally {
      setUploading(false);
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
    addToast,
    addQueueTask,
    updateQueueTask,
    t,
    resetForm,
  ]);

  const canUpload = advancedMode ? !!dataFile && !uploading : !!file && !uploading;

  const disciplineOptions = [
    { value: 'architecture', label: t('bim.disc_architecture', { defaultValue: 'Architecture' }) },
    { value: 'structural', label: t('bim.disc_structural', { defaultValue: 'Structural' }) },
    { value: 'mechanical', label: t('bim.disc_mechanical', { defaultValue: 'Mechanical' }) },
    { value: 'electrical', label: t('bim.disc_electrical', { defaultValue: 'Electrical' }) },
    { value: 'plumbing', label: t('bim.disc_plumbing', { defaultValue: 'Plumbing' }) },
    {
      value: 'fire_protection',
      label: t('bim.disc_fire', { defaultValue: 'Fire Protection' }),
    },
    { value: 'civil', label: t('bim.disc_civil', { defaultValue: 'Civil' }) },
    { value: 'landscape', label: t('bim.disc_landscape', { defaultValue: 'Landscape' }) },
    {
      value: 'mixed',
      label: t('bim.disc_mixed', { defaultValue: 'Mixed / Multi-discipline' }),
    },
  ];

  const fileTypeHint = file
    ? isCADFile(file.name)
      ? t('bim.file_type_cad', {
          defaultValue: 'CAD file — will be queued for background processing',
        })
      : t('bim.file_type_data', {
          defaultValue: 'Data file — elements will be imported immediately',
        })
    : null;

  return (
    <div
      className={`border border-border-light rounded-lg bg-surface-primary ${compact ? '' : ''}`}
    >
      {/* Header */}
      <div className="p-4 border-b border-border-light">
        <div className="flex items-center gap-2">
          <Upload size={18} className="text-oe-blue" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('bim.upload_model', { defaultValue: 'Upload Building Model' })}
          </h2>
        </div>
        <p className="text-xs text-content-tertiary mt-1">
          {t('bim.upload_unified_desc', {
            defaultValue: 'Drag and drop your file here, or click to browse.',
          })}
        </p>
      </div>

      <div className="p-4 space-y-4">
        {!advancedMode && (
          <>
            {/* Unified drop zone */}
            <label
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              className={`flex flex-col items-center gap-3 border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                dragOver
                  ? 'border-oe-blue bg-oe-blue-subtle/30'
                  : file
                    ? 'border-oe-blue/40 bg-oe-blue-subtle/10'
                    : 'border-border-medium hover:border-oe-blue hover:bg-oe-blue-subtle/30'
              }`}
            >
              {file ? (
                <>
                  <CheckCircle2 size={28} className="text-oe-blue" />
                  <div>
                    <p className="text-sm font-medium text-content-primary">{file.name}</p>
                    <p className="text-2xs text-content-tertiary mt-0.5">
                      {(file.size / (1024 * 1024)).toFixed(1)} MB
                    </p>
                    {fileTypeHint && (
                      <p className="text-2xs text-oe-blue mt-1">{fileTypeHint}</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault();
                      handleRemoveFile();
                    }}
                    className="text-2xs text-content-tertiary hover:text-red-500 underline"
                  >
                    {t('bim.remove_file', { defaultValue: 'Remove file' })}
                  </button>
                </>
              ) : (
                <>
                  <FileUp size={28} className="text-content-tertiary" />
                  <div>
                    <p className="text-sm font-medium text-content-primary">
                      {t('bim.drop_file_here', { defaultValue: 'Drop file here' })}
                    </p>
                    <p className="text-2xs text-content-tertiary mt-1">
                      {t('bim.supported_formats', {
                        defaultValue: 'Supported: Revit (.rvt), IFC (.ifc)',
                      })}
                    </p>
                    <p className="text-2xs text-content-quaternary mt-0.5">
                      {t('bim.max_file_size', {
                        defaultValue: 'Max file size: 500 MB',
                      })}
                    </p>
                  </div>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept={cadAcceptedExtensions}
                className="hidden"
                onChange={handleInputChange}
              />
            </label>
          </>
        )}

        {advancedMode && (
          <>
            {/* Hint when opened from "Upload Converted Data" */}
            {initialAdvancedMode && (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-blue-50 border border-blue-200 dark:bg-blue-950/30 dark:border-blue-800">
                <Info size={16} className="text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
                <p className="text-xs text-blue-800 dark:text-blue-300">
                  {t('bim.upload_converted_hint', {
                    defaultValue:
                      'Already converted your CAD file? Upload the element data (CSV/Excel) and optional geometry (DAE/COLLADA) here.',
                  })}
                </p>
              </div>
            )}

            {/* Advanced mode: separate data + geometry uploads */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Data file (required) */}
              <label className="flex flex-col items-center gap-2 border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors hover:border-oe-blue hover:bg-oe-blue-subtle/30">
                <Database size={24} className="text-content-tertiary" />
                <span className="text-xs font-medium text-content-primary">
                  {t('bim.upload_data_label', { defaultValue: 'Element Data (required)' })}
                </span>
                <span className="text-2xs text-content-tertiary">
                  {t('bim.upload_data_hint', { defaultValue: 'CSV or Excel from CAD converter' })}
                </span>
                <span className="text-2xs text-content-quaternary">
                  {t('bim.upload_data_columns', {
                    defaultValue:
                      'Columns: element_id, type, name, storey, area, volume, length',
                  })}
                </span>
                {dataFile && (
                  <Badge variant="blue" size="sm">
                    {dataFile.name}
                  </Badge>
                )}
                <input
                  ref={dataInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden"
                  onChange={handleDataFileChange}
                />
              </label>

              {/* Geometry file (optional) */}
              <label className="flex flex-col items-center gap-2 border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors hover:border-oe-blue hover:bg-oe-blue-subtle/30">
                <FileBox size={24} className="text-content-tertiary" />
                <span className="text-xs font-medium text-content-primary">
                  {t('bim.upload_geo_label', { defaultValue: '3D Geometry (optional)' })}
                </span>
                <span className="text-2xs text-content-tertiary">
                  {t('bim.upload_geo_hint', {
                    defaultValue: 'DAE/COLLADA file with matching element IDs',
                  })}
                </span>
                {geometryFile && (
                  <Badge variant="blue" size="sm">
                    {geometryFile.name}
                  </Badge>
                )}
                <input
                  ref={geoInputRef}
                  type="file"
                  accept=".dae,.glb,.gltf"
                  className="hidden"
                  onChange={handleGeoFileChange}
                />
              </label>
            </div>
          </>
        )}

        {/* Model name + discipline + upload button */}
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex-1 min-w-[180px]">
            <label className="block text-xs text-content-tertiary mb-1">
              {t('bim.model_name', { defaultValue: 'Model name' })}
            </label>
            <input
              type="text"
              className="w-full text-sm py-1.5 px-3 rounded-lg border border-border-light bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              placeholder={t('bim.model_name_placeholder', {
                defaultValue: 'e.g. Building A \u2014 Architecture',
              })}
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
            />
          </div>

          <div className="w-44">
            <label className="block text-xs text-content-tertiary mb-1">
              {t('bim.discipline_label', { defaultValue: 'Discipline' })}
            </label>
            <select
              className="w-full text-sm py-1.5 px-3 rounded-lg border border-border-light bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              value={discipline}
              onChange={(e) => setDiscipline(e.target.value)}
            >
              {disciplineOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Inline progress bar */}
          {uploading && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-content-secondary font-medium">{uploadStage}</span>
                <span className="text-content-tertiary tabular-nums">{uploadProgress}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-surface-tertiary overflow-hidden">
                <div
                  className="h-full rounded-full bg-oe-blue transition-all duration-300 ease-out"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}

          <Button
            variant="primary"
            size="sm"
            onClick={handleUpload}
            disabled={!projectId || !canUpload || uploading}
            title={!projectId ? t('bim.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
          >
            {uploading ? (
              <>
                <Loader2 size={14} className="me-1.5 animate-spin" />
                {t('bim.uploading', { defaultValue: 'Uploading...' })}
              </>
            ) : (
              <>
                <Upload size={14} className="me-1.5" />
                {t('bim.upload_btn', { defaultValue: 'Upload' })}
              </>
            )}
          </Button>
        </div>

        {/* Upload error */}
        {uploadError && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 dark:bg-red-950/30 dark:border-red-800">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 mt-0.5 shrink-0" />
            <p className="text-xs text-red-800 dark:text-red-300">{uploadError}</p>
          </div>
        )}

        {/* Advanced mode toggle */}
        <div className="border-t border-border-light pt-3">
          <button
            type="button"
            onClick={() => {
              setAdvancedMode((prev) => !prev);
              // Clear unified file when switching to advanced
              if (!advancedMode) {
                setFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
              } else {
                setDataFile(null);
                setGeometryFile(null);
                if (dataInputRef.current) dataInputRef.current.value = '';
                if (geoInputRef.current) geoInputRef.current.value = '';
              }
            }}
            className="flex items-center gap-1.5 text-xs text-content-tertiary hover:text-content-secondary transition-colors"
          >
            {advancedMode ? (
              <>
                <ChevronUp size={14} />
                {t('bim.switch_simple', { defaultValue: 'Switch to simple mode' })}
              </>
            ) : (
              <>
                <ChevronRight size={14} />
                {t('bim.switch_advanced', {
                  defaultValue:
                    'Already converted? Upload data + geometry separately.',
                })}
              </>
            )}
          </button>
          {!advancedMode && (
            <p className="text-2xs text-content-quaternary mt-1 ps-5">
              {t('bim.advanced_hint', {
                defaultValue:
                  'Use advanced mode to upload CSV/Excel element data with a separate DAE geometry file.',
              })}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── BIM Page ─────────────────────────────────────────────────────────── */

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
  const [leftPanelUploadOpen, setLeftPanelUploadOpen] = useState(false);
  /** When set, opens the upload panel in advanced mode with this name pre-filled. */
  const [uploadConvertedName, setUploadConvertedName] = useState<string | null>(null);
  /** Override to force-hide the full-page upload after a successful upload. */
  const [showUploadOverride, setShowUploadOverride] = useState<boolean | null>(null);
  const addToast = useToastStore((s) => s.addToast);

  // Fetch models
  const modelsQuery = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: !!projectId,
  });

  const hasModels = (modelsQuery.data?.items?.length ?? 0) > 0;
  // Show full-page upload only when truly no models AND no override.
  // After upload, showUploadOverride is set to false to immediately hide the upload view.
  const showFullPageUpload = showUploadOverride !== null ? showUploadOverride : !hasModels;

  // Reset the override once query data catches up (models are present)
  useEffect(() => {
    if (hasModels && showUploadOverride === false) {
      setShowUploadOverride(null);
    }
  }, [hasModels, showUploadOverride]);

  // Resolve active model from the list
  const activeModel = useMemo(
    () => modelsQuery.data?.items?.find((m) => m.id === activeModelId) ?? null,
    [modelsQuery.data, activeModelId],
  );

  // Poll status when active model is "processing"
  const statusPollQuery = useQuery({
    queryKey: ['bim-model-status', activeModelId],
    queryFn: () => fetchBIMModel(activeModelId!),
    enabled: !!activeModelId && activeModel?.status === 'processing',
    refetchInterval: 10_000, // poll every 10 seconds
  });

  // When status changes from "processing" to something else, refresh models list
  useEffect(() => {
    if (
      statusPollQuery.data &&
      statusPollQuery.data.status !== 'processing' &&
      activeModel?.status === 'processing'
    ) {
      queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
      queryClient.invalidateQueries({ queryKey: ['bim-elements', activeModelId] });
      addToast({
        type: statusPollQuery.data.status === 'ready' ? 'success' : 'info',
        title:
          statusPollQuery.data.status === 'ready'
            ? t('bim.model_ready', { defaultValue: 'Model ready' })
            : t('bim.model_status_changed', { defaultValue: 'Model status changed' }),
        message: t('bim.model_status_changed_desc', {
          defaultValue: '{{name}} is now {{status}}.',
          name: activeModel?.name ?? '',
          status: statusPollQuery.data.status,
        }),
      });
    }
  }, [statusPollQuery.data, activeModel, queryClient, projectId, activeModelId, addToast, t]);

  // Auto-select first model
  useEffect(() => {
    if (modelsQuery.data?.items?.length && !activeModelId) {
      const first = modelsQuery.data.items[0];
      if (first) setActiveModelId(first.id);
    }
  }, [modelsQuery.data, activeModelId]);

  // Fetch elements for active model
  const elementsQuery = useQuery({
    queryKey: ['bim-elements', activeModelId],
    queryFn: () => fetchBIMElements(activeModelId!),
    enabled: !!activeModelId,
  });

  const elements: BIMElementData[] = elementsQuery.data?.items ?? [];

  // Compute geometry URL if any elements have mesh_ref
  const geometryUrl = useMemo(() => {
    if (!activeModelId) return null;
    const hasMeshRef = elements.some((el) => !!el.mesh_ref);
    return hasMeshRef ? getGeometryUrl(activeModelId) : null;
  }, [activeModelId, elements]);

  const handleElementSelect = useCallback((elementId: string | null) => {
    setSelectedElementId(elementId);
  }, []);

  const handleUploadComplete = useCallback(
    (modelId: string) => {
      setActiveModelId(modelId);
      setShowUploadOverride(false); // Immediately hide full-page upload
      setSelectedElementId(null);
      setLeftPanelUploadOpen(false);
      setUploadConvertedName(null);
      queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
    },
    [queryClient, projectId],
  );

  /** Delete a BIM model after confirmation. */
  const handleDeleteModel = useCallback(
    async (modelId: string, modelName: string) => {
      const confirmed = window.confirm(
        t('bim.confirm_delete_model', {
          defaultValue: 'Delete model "{{name}}"? This will remove all its elements.',
          name: modelName,
        }),
      );
      if (!confirmed) return;

      try {
        await deleteBIMModel(modelId);
        addToast({
          type: 'success',
          title: t('bim.model_deleted', { defaultValue: 'Model deleted' }),
          message: modelName,
        });
        if (activeModelId === modelId) {
          setActiveModelId(null);
          setSelectedElementId(null);
        }
        queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        addToast({
          type: 'error',
          title: t('bim.delete_failed', { defaultValue: 'Delete failed' }),
          message: msg,
        });
      }
    },
    [activeModelId, addToast, queryClient, projectId, t],
  );

  // Breadcrumb
  const breadcrumbItems = useMemo(() => {
    const items: { label: string; to?: string }[] = [
      { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
    ];
    if (projectId && contextProjectName) {
      items.push({
        label: contextProjectName,
        to: `/projects/${projectId}`,
      });
    }
    items.push({ label: t('bim.title', { defaultValue: 'BIM Viewer' }) });
    return items;
  }, [t, projectId, contextProjectName]);

  // Selected element IDs for the viewer
  const selectedElementIds = useMemo(
    () => (selectedElementId ? [selectedElementId] : []),
    [selectedElementId],
  );

  // No project selected
  if (!projectId) {
    return (
      <div className="p-6">
        <Breadcrumb items={breadcrumbItems} />
        <EmptyState
          icon={<FolderOpen size={28} />}
          title={t('bim.no_project', { defaultValue: 'No project selected' })}
          description={t('bim.no_project_desc', {
            defaultValue: 'Select a project to view BIM models.',
          })}
        />
      </div>
    );
  }

  // Project selected but no models and not loading — show full-page upload
  // (unless override says to hide it, e.g. right after a successful upload)
  if (showFullPageUpload && !modelsQuery.isLoading) {
    return (
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="px-6 pt-4 pb-3 border-b border-border-light">
          <Breadcrumb items={breadcrumbItems} />
          <div className="flex items-center justify-between mt-2">
            <h1 className="text-xl font-bold text-content-primary">
              {t('bim.title', { defaultValue: 'BIM Viewer' })}
            </h1>
          </div>
        </div>

        {/* Centered upload section, with model list above if any models exist */}
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="w-full max-w-xl space-y-4">
            {/* Show existing models above upload when available */}
            {hasModels && modelsQuery.data?.items && (
              <div className="border border-border-light rounded-lg bg-surface-primary p-4">
                <h2 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider mb-2">
                  {t('bim.models', { defaultValue: 'Models' })}
                </h2>
                <div className="flex gap-2 overflow-x-auto">
                  {modelsQuery.data.items.map((model) => (
                    <ModelCard
                      key={model.id}
                      model={model}
                      isActive={model.id === activeModelId}
                      onClick={() => {
                        setActiveModelId(model.id);
                        setSelectedElementId(null);
                        setShowUploadOverride(false);
                      }}
                      onDelete={() => handleDeleteModel(model.id, model.name)}

                    />
                  ))}
                </div>
              </div>
            )}
            <UnifiedUploadSection
              projectId={projectId}
              onUploadComplete={handleUploadComplete}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 pt-4 pb-3 border-b border-border-light">
        <Breadcrumb items={breadcrumbItems} />
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-content-primary">
              {t('bim.title', { defaultValue: 'BIM Viewer' })}
            </h1>
            {elements.length > 0 && (
              <Badge variant="blue" size="sm">
                {t('bim.element_count', {
                  defaultValue: '{{count}} elements',
                  count: elements.length,
                })}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {elements.length > 0 && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    /* Link to BOQ — future implementation */
                  }}
                  title={t('bim.link_to_boq_hint', {
                    defaultValue:
                      'Select elements in the 3D viewer and link them to BOQ positions for quantity verification.',
                  })}
                >
                  <Link2 size={14} className="me-1.5" />
                  {t('bim.link_to_boq', { defaultValue: 'Link to BOQ' })}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => navigate('/schedule')}
                  title={t('bim.schedule_link_hint', {
                    defaultValue:
                      'Link BIM elements to schedule activities for 4D construction simulation.',
                  })}
                >
                  <CalendarDays size={14} className="me-1.5" />
                  {t('bim.four_d_schedule', { defaultValue: '4D Schedule' })}
                </Button>
              </>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setLeftPanelUploadOpen((prev) => !prev)}
            >
              {leftPanelUploadOpen ? (
                <>
                  <X size={14} className="me-1.5" />
                  {t('common.close', { defaultValue: 'Close' })}
                </>
              ) : (
                <>
                  <Upload size={14} className="me-1.5" />
                  {t('bim.add_model', { defaultValue: 'Add model' })}
                </>
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Collapsible upload panel below header */}
      {leftPanelUploadOpen && (
        <div className="px-6 py-4 border-b border-border-light bg-surface-primary">
          <div className="max-w-xl">
            <UnifiedUploadSection
              projectId={projectId}
              onUploadComplete={handleUploadComplete}
              compact
              initialAdvancedMode={!!uploadConvertedName}
              initialModelName={uploadConvertedName || undefined}
            />
          </div>
        </div>
      )}

      {/* Full-width 3D Viewer */}
      <div className="flex-1 min-h-0">
        {activeModelId && activeModel?.status === 'processing' ? (
          <div className="flex flex-col items-center justify-center h-full bg-surface-secondary">
            <div className="text-center max-w-sm">
              <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-amber-100 to-orange-100 flex items-center justify-center mb-4">
                <Box size={32} className="text-amber-600" />
              </div>
              <h2 className="text-lg font-semibold text-content-primary mb-2">
                {t('bim.model_processing_title', { defaultValue: 'Model Processing' })}
              </h2>
              <p className="text-sm text-content-secondary mb-4">
                {t('bim.model_processing_viewer_desc', {
                  defaultValue:
                    'Your {{format}} file is being processed. The 3D viewer will load automatically when elements are ready.',
                  format: (activeModel.model_format || activeModel.format || '').toUpperCase(),
                })}
              </p>
              <div className="text-xs text-content-tertiary">
                {t('bim.model_processing_file_info', {
                  defaultValue: 'File: {{name}} ({{size}})',
                  name: activeModel.name,
                  size: activeModel.file_size ? formatFileSize(activeModel.file_size) : '—',
                })}
              </div>
            </div>
          </div>
        ) : activeModelId ? (
          <BIMViewer
            modelId={activeModelId}
            projectId={projectId}
            selectedElementIds={selectedElementIds}
            onElementSelect={handleElementSelect}
            elements={elements}
            isLoading={elementsQuery.isLoading}
            error={
              elementsQuery.error
                ? t('bim.load_error', { defaultValue: 'Failed to load model elements' })
                : null
            }
            geometryUrl={geometryUrl}
            className="h-full"
          />
        ) : (
          <div className="flex items-center justify-center h-full bg-surface-secondary">
            <EmptyState
              icon={<Box size={28} />}
              title={t('bim.select_model', { defaultValue: 'Select a model' })}
              description={t('bim.select_model_desc', {
                defaultValue:
                  'Choose a BIM model from the list to visualize it in 3D.',
              })}
            />
          </div>
        )}
      </div>

      {/* Bottom model bar (filmstrip) */}
      <div className="shrink-0 border-t border-border-light bg-surface-primary">
        <div className="flex items-center gap-3 px-4 py-3 overflow-x-auto">
          <h2 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider shrink-0">
            {t('bim.models', { defaultValue: 'Models' })}
          </h2>

          {modelsQuery.isLoading ? (
            <Loader2 size={16} className="animate-spin text-content-tertiary" />
          ) : modelsQuery.data?.items?.length ? (
            modelsQuery.data.items.map((model) => (
              <ModelCard
                key={model.id}
                model={model}
                isActive={model.id === activeModelId}
                onClick={() => {
                  setActiveModelId(model.id);
                  setSelectedElementId(null);
                }}
                onDelete={() => handleDeleteModel(model.id, model.name)}
              />
            ))
          ) : (
            <span className="text-xs text-content-quaternary">
              {t('bim.no_models', { defaultValue: 'No models uploaded yet' })}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
