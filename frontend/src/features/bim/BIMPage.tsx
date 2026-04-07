/**
 * BIMPage — split-view BIM Hub page.
 *
 * Left panel: model list + element tree (grouped by storey > discipline > type).
 * Right panel: Three.js BIM Viewer.
 *
 * Route: /projects/:projectId/bim  or  /bim  (uses project context store)
 */

import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  ChevronRight,
  ChevronDown,
  Layers,
  Building2,
  Loader2,
  FolderOpen,
  Link2,
  Search,
  Upload,
  Database,
  FileBox,
  FileUp,
  X,
  CheckCircle2,
  AlertCircle,
  Clock,
} from 'lucide-react';
import { Button, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { BIMViewer, DisciplineToggle } from '@/shared/ui/BIMViewer';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { fetchBIMModels, fetchBIMElements, uploadBIMData, uploadCADFile, getGeometryUrl } from './api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface TreeNode {
  key: string;
  label: string;
  type: 'storey' | 'discipline' | 'element_type' | 'element';
  children: TreeNode[];
  elementId?: string;
  count?: number;
}

/* ── Tree Builder ──────────────────────────────────────────────────────── */

function buildElementTree(elements: BIMElementData[]): TreeNode[] {
  // Group: storey > discipline > element_type > elements
  const storeyMap = new Map<string, Map<string, Map<string, BIMElementData[]>>>();

  for (const el of elements) {
    const storey = el.storey || 'Unassigned';
    const discipline = el.discipline || 'Other';
    const elType = el.element_type || 'Unknown';

    if (!storeyMap.has(storey)) storeyMap.set(storey, new Map());
    const discMap = storeyMap.get(storey)!;
    if (!discMap.has(discipline)) discMap.set(discipline, new Map());
    const typeMap = discMap.get(discipline)!;
    if (!typeMap.has(elType)) typeMap.set(elType, []);
    typeMap.get(elType)!.push(el);
  }

  const tree: TreeNode[] = [];
  for (const [storey, discMap] of storeyMap) {
    const storeyChildren: TreeNode[] = [];
    let storeyCount = 0;

    for (const [discipline, typeMap] of discMap) {
      const discChildren: TreeNode[] = [];
      let discCount = 0;

      for (const [elType, els] of typeMap) {
        const typeChildren: TreeNode[] = els.map((el) => ({
          key: `el-${el.id}`,
          label: el.name || el.id,
          type: 'element' as const,
          children: [],
          elementId: el.id,
        }));
        discCount += els.length;
        discChildren.push({
          key: `type-${storey}-${discipline}-${elType}`,
          label: elType,
          type: 'element_type',
          children: typeChildren,
          count: els.length,
        });
      }

      storeyCount += discCount;
      storeyChildren.push({
        key: `disc-${storey}-${discipline}`,
        label: discipline,
        type: 'discipline',
        children: discChildren,
        count: discCount,
      });
    }

    tree.push({
      key: `storey-${storey}`,
      label: storey,
      type: 'storey',
      children: storeyChildren,
      count: storeyCount,
    });
  }

  return tree;
}

/* ── Tree Node Component ───────────────────────────────────────────────── */

function TreeItem({
  node,
  selectedId,
  expandedKeys,
  onToggle,
  onSelect,
  depth = 0,
}: {
  node: TreeNode;
  selectedId: string | null;
  expandedKeys: Set<string>;
  onToggle: (key: string) => void;
  onSelect: (elementId: string) => void;
  depth?: number;
}) {
  const isExpanded = expandedKeys.has(node.key);
  const hasChildren = node.children.length > 0;
  const isElement = node.type === 'element';
  const isSelected = isElement && node.elementId === selectedId;

  return (
    <div>
      <button
        onClick={() => {
          if (isElement && node.elementId) {
            onSelect(node.elementId);
          } else if (hasChildren) {
            onToggle(node.key);
          }
        }}
        className={`flex items-center gap-1.5 w-full text-start text-xs py-1 px-1.5 rounded transition-colors ${
          isSelected
            ? 'bg-oe-blue-subtle text-oe-blue font-medium'
            : 'text-content-secondary hover:bg-surface-secondary'
        }`}
        style={{ paddingInlineStart: `${depth * 16 + 6}px` }}
      >
        {hasChildren && (
          isExpanded
            ? <ChevronDown size={12} className="shrink-0 text-content-tertiary" />
            : <ChevronRight size={12} className="shrink-0 text-content-tertiary" />
        )}
        {!hasChildren && <span className="w-3 shrink-0" />}

        {node.type === 'storey' && <Building2 size={13} className="shrink-0 text-content-tertiary" />}
        {node.type === 'discipline' && <Layers size={13} className="shrink-0 text-content-tertiary" />}
        {node.type === 'element_type' && <FolderOpen size={12} className="shrink-0 text-content-tertiary" />}
        {node.type === 'element' && <Box size={12} className="shrink-0 text-content-tertiary" />}

        <span className="truncate">{node.label}</span>

        {node.count != null && (
          <span className="ms-auto text-2xs text-content-quaternary tabular-nums shrink-0">
            {node.count}
          </span>
        )}
      </button>

      {isExpanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeItem
              key={child.key}
              node={child}
              selectedId={selectedId}
              expandedKeys={expandedKeys}
              onToggle={onToggle}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Model Card ────────────────────────────────────────────────────────── */

function ModelCard({
  model,
  isActive,
  onClick,
}: {
  model: BIMModelData;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-start p-3 rounded-lg border transition-colors ${
        isActive
          ? 'border-oe-blue bg-oe-blue-subtle'
          : 'border-border-light hover:border-border-medium hover:bg-surface-secondary'
      }`}
    >
      <div className="flex items-center gap-2">
        <Box size={16} className={isActive ? 'text-oe-blue' : 'text-content-tertiary'} />
        <span className="text-sm font-medium text-content-primary truncate">{model.name}</span>
      </div>
      <div className="flex items-center gap-2 mt-1">
        <Badge
          variant={
            model.status === 'ready'
              ? 'success'
              : model.status === 'processing'
                ? 'warning'
                : 'neutral'
          }
          size="sm"
        >
          {model.status === 'processing' ? (
            <span className="flex items-center gap-1">
              <Loader2 size={10} className="animate-spin" />
              Processing...
            </span>
          ) : (
            model.status
          )}
        </Badge>
        <span className="text-2xs text-content-tertiary">{model.format?.toUpperCase()}</span>
        <span className="text-2xs text-content-quaternary truncate">{model.filename}</span>
      </div>
    </button>
  );
}

/* ── Upload Card ──────────────────────────────────────────────────────── */

type UploadMode = 'cad' | 'data';

function UploadCard({
  projectId,
  onUploadComplete,
}: {
  projectId: string;
  onUploadComplete: (modelId: string) => void;
}) {
  const { t } = useTranslation();
  const [uploadMode, setUploadMode] = useState<UploadMode>('cad');
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [cadFile, setCadFile] = useState<File | null>(null);
  const [geometryFile, setGeometryFile] = useState<File | null>(null);
  const [modelName, setModelName] = useState('');
  const [discipline, setDiscipline] = useState('architecture');
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{
    elementCount?: number;
    storeys?: string[];
    disciplines?: string[];
    hasGeometry?: boolean;
    cadFormat?: string;
    cadStatus?: string;
  } | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const dataInputRef = useRef<HTMLInputElement>(null);
  const cadInputRef = useRef<HTMLInputElement>(null);
  const geoInputRef = useRef<HTMLInputElement>(null);
  const addToast = useToastStore((s) => s.addToast);

  const handleDataFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setDataFile(file);
    setUploadResult(null);
    setUploadError(null);
    // Auto-fill model name from file name (without extension)
    if (file && !modelName) {
      const baseName = file.name.replace(/\.(csv|xlsx|xls)$/i, '');
      setModelName(baseName);
    }
  }, [modelName]);

  const handleCadFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setCadFile(file);
    setUploadResult(null);
    setUploadError(null);
    if (file && !modelName) {
      const baseName = file.name.replace(/\.(rvt|ifc|dwg|dgn|fbx|obj|3ds)$/i, '');
      setModelName(baseName);
    }
  }, [modelName]);

  const handleGeoFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setGeometryFile(e.target.files?.[0] ?? null);
    setUploadResult(null);
    setUploadError(null);
  }, []);

  const resetForm = useCallback(() => {
    setDataFile(null);
    setCadFile(null);
    setGeometryFile(null);
    setModelName('');
    if (dataInputRef.current) dataInputRef.current.value = '';
    if (cadInputRef.current) cadInputRef.current.value = '';
    if (geoInputRef.current) geoInputRef.current.value = '';
  }, []);

  const handleUploadData = useCallback(async () => {
    if (!dataFile) return;

    setUploading(true);
    setUploadError(null);
    setUploadResult(null);

    try {
      const result = await uploadBIMData(
        projectId,
        modelName || 'Imported Model',
        discipline,
        dataFile,
        geometryFile,
      );
      setUploadResult({
        elementCount: result.element_count,
        storeys: result.storeys,
        disciplines: result.disciplines,
        hasGeometry: result.has_geometry,
      });
      addToast({
        type: 'success',
        title: t('bim.upload_success', { defaultValue: 'BIM data uploaded' }),
        message: t('bim.upload_success_desc', {
          defaultValue: '{{count}} elements imported successfully.',
          count: result.element_count,
        }),
      });
      onUploadComplete(result.model_id);
      resetForm();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setUploadError(msg);
      addToast({
        type: 'error',
        title: t('bim.upload_failed', { defaultValue: 'Upload failed' }),
        message: msg,
      });
    } finally {
      setUploading(false);
    }
  }, [projectId, modelName, discipline, dataFile, geometryFile, onUploadComplete, addToast, t, resetForm]);

  const handleUploadCad = useCallback(async () => {
    if (!cadFile) return;

    setUploading(true);
    setUploadError(null);
    setUploadResult(null);

    try {
      const result = await uploadCADFile(
        projectId,
        modelName || cadFile.name.replace(/\.[^.]+$/, ''),
        discipline,
        cadFile,
      );
      setUploadResult({
        cadFormat: result.format.toUpperCase(),
        cadStatus: result.status,
      });
      addToast({
        type: 'success',
        title: t('bim.cad_upload_success', { defaultValue: 'CAD file uploaded' }),
        message: t('bim.cad_upload_success_desc', {
          defaultValue: '{{format}} file uploaded. Processing will start shortly.',
          format: result.format.toUpperCase(),
        }),
      });
      onUploadComplete(result.model_id);
      resetForm();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setUploadError(msg);
      addToast({
        type: 'error',
        title: t('bim.upload_failed', { defaultValue: 'Upload failed' }),
        message: msg,
      });
    } finally {
      setUploading(false);
    }
  }, [projectId, modelName, discipline, cadFile, onUploadComplete, addToast, t, resetForm]);

  const disciplineOptions = [
    { value: 'architecture', label: t('bim.disc_architecture', { defaultValue: 'Architecture' }) },
    { value: 'structural', label: t('bim.disc_structural', { defaultValue: 'Structural' }) },
    { value: 'mechanical', label: t('bim.disc_mechanical', { defaultValue: 'Mechanical' }) },
    { value: 'electrical', label: t('bim.disc_electrical', { defaultValue: 'Electrical' }) },
    { value: 'plumbing', label: t('bim.disc_plumbing', { defaultValue: 'Plumbing' }) },
    { value: 'fire_protection', label: t('bim.disc_fire', { defaultValue: 'Fire Protection' }) },
    { value: 'civil', label: t('bim.disc_civil', { defaultValue: 'Civil' }) },
    { value: 'landscape', label: t('bim.disc_landscape', { defaultValue: 'Landscape' }) },
    { value: 'mixed', label: t('bim.disc_mixed', { defaultValue: 'Mixed / Multi-discipline' }) },
  ];

  return (
    <div className="border border-border-light rounded-lg bg-surface-primary">
      <div className="p-4 border-b border-border-light">
        <div className="flex items-center gap-2">
          <Upload size={18} className="text-oe-blue" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('bim.upload_title', { defaultValue: 'Upload BIM Data' })}
          </h2>
        </div>
        <p className="text-xs text-content-tertiary mt-1">
          {t('bim.upload_desc_full', {
            defaultValue:
              'Upload a raw CAD file directly, or pre-processed element data (CSV/Excel) with optional 3D geometry.',
          })}
        </p>
      </div>

      <div className="p-4 space-y-4">
        {/* Mode toggle */}
        <div className="flex gap-2 p-1 bg-surface-secondary rounded-lg">
          <button
            onClick={() => setUploadMode('cad')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-md text-xs font-medium transition-colors ${
              uploadMode === 'cad'
                ? 'bg-surface-primary text-oe-blue shadow-sm'
                : 'text-content-secondary hover:text-content-primary'
            }`}
          >
            <FileUp size={14} />
            {t('bim.mode_cad', { defaultValue: 'Direct CAD Upload' })}
          </button>
          <button
            onClick={() => setUploadMode('data')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-md text-xs font-medium transition-colors ${
              uploadMode === 'data'
                ? 'bg-surface-primary text-oe-blue shadow-sm'
                : 'text-content-secondary hover:text-content-primary'
            }`}
          >
            <Database size={14} />
            {t('bim.mode_data', { defaultValue: 'Pre-processed Data' })}
          </button>
        </div>

        {uploadMode === 'cad' ? (
          /* ── CAD file upload mode ────────────────────────────────────── */
          <>
            <label className="flex flex-col items-center gap-2 border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors hover:border-oe-blue hover:bg-oe-blue-subtle/30">
              <FileUp size={28} className="text-content-tertiary" />
              <span className="text-xs font-medium text-content-primary">
                {t('bim.upload_cad_label', { defaultValue: 'CAD / BIM File' })}
              </span>
              <span className="text-2xs text-content-tertiary">
                {t('bim.upload_cad_hint', {
                  defaultValue: 'RVT, IFC, DWG, DGN, FBX, OBJ, 3DS (max 500 MB)',
                })}
              </span>
              <span className="text-2xs text-content-quaternary">
                {t('bim.upload_cad_note', {
                  defaultValue: 'File will be queued for background processing by the CAD converter',
                })}
              </span>
              {cadFile && (
                <Badge variant="blue" size="sm">
                  {cadFile.name} ({(cadFile.size / (1024 * 1024)).toFixed(1)} MB)
                </Badge>
              )}
              <input
                ref={cadInputRef}
                type="file"
                accept=".rvt,.ifc,.dwg,.dgn,.fbx,.obj,.3ds"
                className="hidden"
                onChange={handleCadFileChange}
              />
            </label>
          </>
        ) : (
          /* ── Pre-processed data upload mode ──────────────────────────── */
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
                  defaultValue: 'Columns: element_id, type, name, storey, area, volume, length',
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
        )}

        {/* Options row */}
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex-1 min-w-[180px]">
            <label className="block text-xs text-content-tertiary mb-1">
              {t('bim.model_name', { defaultValue: 'Model name' })}
            </label>
            <input
              type="text"
              className="w-full text-sm py-1.5 px-3 rounded-lg border border-border-light bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
              placeholder={t('bim.model_name_placeholder', { defaultValue: 'e.g. Building A — Architecture' })}
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

          <Button
            variant="primary"
            size="sm"
            onClick={uploadMode === 'cad' ? handleUploadCad : handleUploadData}
            disabled={uploadMode === 'cad' ? !cadFile || uploading : !dataFile || uploading}
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

        {/* Upload result — data mode */}
        {uploadResult && uploadResult.elementCount != null && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-green-50 border border-green-200 dark:bg-green-950/30 dark:border-green-800">
            <CheckCircle2 size={16} className="text-green-600 dark:text-green-400 mt-0.5 shrink-0" />
            <div className="text-xs text-green-800 dark:text-green-300">
              <p className="font-medium">
                {t('bim.upload_result', {
                  defaultValue: '{{count}} elements imported',
                  count: uploadResult.elementCount,
                })}
                {uploadResult.hasGeometry && (
                  <span className="ms-1 text-green-600 dark:text-green-400">
                    {t('bim.upload_with_geometry', { defaultValue: '(with 3D geometry)' })}
                  </span>
                )}
              </p>
              {uploadResult.storeys && uploadResult.storeys.length > 0 && (
                <p className="mt-0.5">
                  {t('bim.upload_storeys', { defaultValue: 'Storeys:' })}{' '}
                  {uploadResult.storeys.join(', ')}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Upload result — CAD mode */}
        {uploadResult && uploadResult.cadFormat && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-blue-50 border border-blue-200 dark:bg-blue-950/30 dark:border-blue-800">
            <Clock size={16} className="text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
            <div className="text-xs text-blue-800 dark:text-blue-300">
              <p className="font-medium">
                {t('bim.cad_upload_queued', {
                  defaultValue: '{{format}} file uploaded successfully',
                  format: uploadResult.cadFormat,
                })}
              </p>
              <p className="mt-0.5">
                {t('bim.cad_processing_note', {
                  defaultValue: 'The model is queued for processing. Elements will appear once the CAD converter finishes.',
                })}
              </p>
            </div>
          </div>
        )}

        {/* Upload error */}
        {uploadError && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 dark:bg-red-950/30 dark:border-red-800">
            <AlertCircle size={16} className="text-red-600 dark:text-red-400 mt-0.5 shrink-0" />
            <p className="text-xs text-red-800 dark:text-red-300">{uploadError}</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── BIM Page ──────────────────────────────────────────────────────────── */

export function BIMPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { projectId: urlProjectId } = useParams<{ projectId: string }>();
  const contextProjectId = useProjectContextStore((s) => s.activeProjectId);
  const contextProjectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = urlProjectId || contextProjectId || '';

  const [activeModelId, setActiveModelId] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [disciplineVisibility, setDisciplineVisibility] = useState<Record<string, boolean>>({});

  // Fetch models
  const modelsQuery = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: !!projectId,
  });

  // Auto-select first model
  useEffect(() => {
    if (modelsQuery.data?.models?.length && !activeModelId) {
      const first = modelsQuery.data.models[0];
      if (first) setActiveModelId(first.id);
    }
  }, [modelsQuery.data, activeModelId]);

  // Fetch elements for active model
  const elementsQuery = useQuery({
    queryKey: ['bim-elements', activeModelId],
    queryFn: () => fetchBIMElements(activeModelId!),
    enabled: !!activeModelId,
  });

  const elements: BIMElementData[] = elementsQuery.data?.elements ?? [];

  // Compute geometry URL if any elements have mesh_ref
  const geometryUrl = useMemo(() => {
    if (!activeModelId) return null;
    const hasMeshRef = elements.some((el) => !!el.mesh_ref);
    return hasMeshRef ? getGeometryUrl(activeModelId) : null;
  }, [activeModelId, elements]);

  // Build tree
  const tree = useMemo(() => buildElementTree(elements), [elements]);

  // Get disciplines
  const disciplines = useMemo(() => {
    const set = new Set<string>();
    for (const el of elements) {
      if (el.discipline) set.add(el.discipline);
    }
    return Array.from(set).sort();
  }, [elements]);

  // Search filter for tree
  const filteredTree = useMemo(() => {
    if (!searchQuery.trim()) return tree;
    const q = searchQuery.toLowerCase();

    function filterNode(node: TreeNode): TreeNode | null {
      if (node.type === 'element') {
        const matches = node.label.toLowerCase().includes(q);
        return matches ? node : null;
      }
      const filteredChildren = node.children
        .map(filterNode)
        .filter((n): n is TreeNode => n !== null);
      if (filteredChildren.length === 0) return null;
      return { ...node, children: filteredChildren, count: filteredChildren.length };
    }

    return tree.map(filterNode).filter((n): n is TreeNode => n !== null);
  }, [tree, searchQuery]);

  // Handlers
  const handleToggleNode = useCallback((key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const handleElementSelect = useCallback((elementId: string | null) => {
    setSelectedElementId(elementId);
  }, []);

  const handleTreeSelect = useCallback((elementId: string) => {
    setSelectedElementId(elementId);
  }, []);

  const handleDisciplineToggle = useCallback((discipline: string) => {
    setDisciplineVisibility((prev) => ({
      ...prev,
      [discipline]: prev[discipline] === false ? true : false,
    }));
  }, []);

  const handleUploadComplete = useCallback(
    (modelId: string) => {
      // Invalidate models query to reload the list
      queryClient.invalidateQueries({ queryKey: ['bim-models', projectId] });
      // Activate the newly uploaded model
      setActiveModelId(modelId);
      setSelectedElementId(null);
      setShowUpload(false);
    },
    [queryClient, projectId],
  );

  // Breadcrumb
  const breadcrumbItems = useMemo(() => {
    const items = [
      { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
    ];
    if (projectId && contextProjectName) {
      items.push({
        label: contextProjectName,
        to: `/projects/${projectId}`,
      });
    }
    items.push({ label: t('bim.title', { defaultValue: 'BIM Viewer' }), to: '' });
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

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 pt-4 pb-3 border-b border-border-light">
        <Breadcrumb items={breadcrumbItems} />
        <div className="flex items-center justify-between mt-2">
          <h1 className="text-xl font-bold text-content-primary">
            {t('bim.title', { defaultValue: 'BIM Viewer' })}
          </h1>
          <div className="flex items-center gap-2">
            {selectedElementId && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  /* Link to BOQ — future implementation */
                }}
              >
                <Link2 size={14} className="me-1.5" />
                {t('bim.link_to_boq', { defaultValue: 'Link to BOQ' })}
              </Button>
            )}
            <Button
              variant={showUpload ? 'secondary' : 'primary'}
              size="sm"
              onClick={() => setShowUpload((prev) => !prev)}
            >
              {showUpload ? (
                <>
                  <X size={14} className="me-1.5" />
                  {t('bim.hide_upload', { defaultValue: 'Close' })}
                </>
              ) : (
                <>
                  <Upload size={14} className="me-1.5" />
                  {t('bim.show_upload', { defaultValue: 'Upload BIM Data' })}
                </>
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Upload card (collapsible) */}
      {showUpload && (
        <div className="px-6 py-3 border-b border-border-light">
          <UploadCard projectId={projectId} onUploadComplete={handleUploadComplete} />
        </div>
      )}

      {/* Split layout */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel — model list + element tree */}
        <div className="w-80 shrink-0 border-e border-border-light bg-surface-primary overflow-y-auto">
          {/* Models section */}
          <div className="p-3 border-b border-border-light">
            <h2 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider mb-2">
              {t('bim.models', { defaultValue: 'Models' })}
            </h2>
            {modelsQuery.isLoading ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 size={20} className="animate-spin text-content-tertiary" />
              </div>
            ) : modelsQuery.data?.models?.length ? (
              <div className="space-y-2">
                {modelsQuery.data.models.map((model) => (
                  <ModelCard
                    key={model.id}
                    model={model}
                    isActive={model.id === activeModelId}
                    onClick={() => {
                      setActiveModelId(model.id);
                      setSelectedElementId(null);
                    }}
                  />
                ))}
              </div>
            ) : (
              <div className="py-6 px-4 text-center space-y-2">
                <Box size={24} className="mx-auto text-content-quaternary" />
                <p className="text-xs font-medium text-content-tertiary">
                  {t('bim.no_models', { defaultValue: 'No models uploaded yet' })}
                </p>
                <p className="text-2xs text-content-quaternary">
                  {t('bim.no_models_hint_upload', {
                    defaultValue: 'Click "Upload BIM Data" above to import element data and 3D geometry from your CAD converter.',
                  })}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowUpload(true)}
                  className="mt-1"
                >
                  <Upload size={12} className="me-1" />
                  {t('bim.show_upload', { defaultValue: 'Upload BIM Data' })}
                </Button>
              </div>
            )}
          </div>

          {/* Search */}
          {elements.length > 0 && (
            <div className="p-3 border-b border-border-light">
              <div className="relative">
                <Search size={14} className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t('bim.search_elements', { defaultValue: 'Search elements...' })}
                  className="w-full text-xs py-1.5 ps-8 pe-3 rounded-lg border border-border-light bg-surface-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </div>
            </div>
          )}

          {/* Discipline toggles */}
          {disciplines.length > 0 && (
            <div className="p-3 border-b border-border-light">
              <DisciplineToggle
                disciplines={disciplines}
                visible={disciplineVisibility}
                onToggle={handleDisciplineToggle}
              />
            </div>
          )}

          {/* Element tree */}
          <div className="p-2">
            <h2 className="text-xs font-semibold text-content-tertiary uppercase tracking-wider px-1.5 mb-1">
              {t('bim.element_tree', { defaultValue: 'Element Tree' })}
            </h2>
            {elementsQuery.isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 size={20} className="animate-spin text-content-tertiary" />
              </div>
            ) : filteredTree.length > 0 ? (
              <div className="space-y-0.5">
                {filteredTree.map((node) => (
                  <TreeItem
                    key={node.key}
                    node={node}
                    selectedId={selectedElementId}
                    expandedKeys={expandedKeys}
                    onToggle={handleToggleNode}
                    onSelect={handleTreeSelect}
                  />
                ))}
              </div>
            ) : elements.length === 0 && activeModelId ? (
              <p className="text-xs text-content-tertiary py-4 text-center">
                {t('bim.no_elements', { defaultValue: 'No elements to display' })}
              </p>
            ) : searchQuery ? (
              <p className="text-xs text-content-tertiary py-4 text-center">
                {t('bim.no_search_results', { defaultValue: 'No matching elements' })}
              </p>
            ) : null}
          </div>
        </div>

        {/* Right panel — 3D Viewer */}
        <div className="flex-1 min-w-0">
          {activeModelId ? (
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
                title={
                  modelsQuery.data?.models?.length
                    ? t('bim.select_model', { defaultValue: 'Select a model' })
                    : t('bim.getting_started', { defaultValue: 'BIM Viewer' })
                }
                description={
                  modelsQuery.data?.models?.length
                    ? t('bim.select_model_desc', { defaultValue: 'Choose a BIM model from the list to visualize it in 3D.' })
                    : t('bim.getting_started_desc', { defaultValue: 'Upload element data (CSV/Excel) and optional 3D geometry (DAE) from your CAD converter to visualize building models in 3D. Elements can be linked to BOQ positions for quantity verification.' })
                }
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
