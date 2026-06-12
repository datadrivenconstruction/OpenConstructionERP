/**
 * Point Cloud / Reality Capture module page.
 *
 * Mirrors the upload-and-explain UX of the BIM Hub and DWG Takeoff pages:
 *  - a drag-and-drop upload dropzone + file picker for laser-scan / reality-
 *    capture containers (.las/.laz/.e57/.ply/.pts/.xyz/.pcd), wired to the
 *    REAL presigned-direct ingest endpoint (see ./api.ts). No faked success -
 *    backend failures surface as a real error.
 *  - a project picker (mirrors DWG Takeoff) so the scan is registered against
 *    the right project.
 *  - an explanation / intro block describing what the module does.
 *  - the scan registry list and capability cards.
 *  - a subtle, modern, theme-aware animated point-cloud background that sits
 *    behind the content (PointCloudBackground).
 *
 * Phase 0 ships the scan registry plus the direct-to-storage ingest; the cloud
 * viewer, model registration and deviation analysis arrive in later phases.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ScanLine,
  FolderOpen,
  Layers,
  Ruler,
  ShieldCheck,
  Boxes,
  AlertCircle,
  Eye,
  Loader2,
  UploadCloud,
  CheckCircle2,
  X,
} from 'lucide-react';
import { Badge, Breadcrumb, Card, DismissibleInfo, EmptyState } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi } from '@/features/projects/api';
import {
  ACCEPTED_SCAN_FORMATS,
  VIEWABLE_SCAN_STATUSES,
  formatFromFileName,
  listScans,
  uploadScan,
  type AccuracyTier,
  type ScanSourceType,
  type UploadProgress,
} from './api';
import { PointCloudBackground } from './PointCloudBackground';
import { PointCloudViewer } from './PointCloudViewer';

/* The accepted upload containers, mirrored from the backend allow-list
   (backend/app/modules/pointcloud/models.py ACCEPTED_SCAN_FORMATS). Proprietary
   ReCap RCP/RCS is deliberately absent - export E57 or LAS instead. */
const SUPPORTED_FORMATS = ACCEPTED_SCAN_FORMATS.map((f) => f.toUpperCase());
const ACCEPT_ATTR = ACCEPTED_SCAN_FORMATS.map((f) => `.${f}`).join(',');

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  uploading: 'warning',
  uploaded: 'blue',
  converting: 'blue',
  ready: 'success',
  failed: 'error',
};

const ACCURACY_LABEL: Record<string, string> = {
  survey: 'Survey grade, +/-3-6 mm',
  standard: 'Standard, +/-15 mm',
  coarse: 'Coarse, +/-50 mm',
};

const SOURCE_LABEL: Record<string, string> = {
  laser_scan: 'Laser scan',
  photogrammetry: 'Photogrammetry',
  lidar: 'LiDAR',
  other: 'Other',
};

function formatPointCount(n: number): string {
  if (!n) return '-';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B pts`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M pts`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K pts`;
  return `${n} pts`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

/* The three things reality capture unlocks once a scan is registered against the
   model - shown as guidance cards so the BETA surface explains its own value. */
const CAPABILITY_CARDS: { icon: typeof Ruler; title: string; body: string }[] = [
  {
    icon: Ruler,
    title: 'Verify built quantities',
    body: 'Compare the as-built cloud against the model to confirm the quantities you are pricing.',
  },
  {
    icon: Layers,
    title: 'Cut and fill into the estimate',
    body: 'Survey-grade earthwork volumes feed straight into the BOQ with the accuracy tier attached.',
  },
  {
    icon: ShieldCheck,
    title: 'Document site conditions',
    body: 'A dated, georeferenced record of what was actually on site, kept with the project.',
  },
];

const SOURCE_OPTIONS: { value: ScanSourceType; labelKey: string; fallback: string }[] = [
  { value: 'laser_scan', labelKey: 'pointcloud.source_laser_scan', fallback: 'Laser scan' },
  { value: 'photogrammetry', labelKey: 'pointcloud.source_photogrammetry', fallback: 'Photogrammetry' },
  { value: 'lidar', labelKey: 'pointcloud.source_lidar', fallback: 'LiDAR' },
  { value: 'other', labelKey: 'pointcloud.source_other', fallback: 'Other' },
];

const ACCURACY_OPTIONS: { value: AccuracyTier; labelKey: string; fallback: string }[] = [
  { value: 'survey', labelKey: 'pointcloud.tier_survey', fallback: 'Survey grade, +/-3-6 mm' },
  { value: 'standard', labelKey: 'pointcloud.tier_standard', fallback: 'Standard, +/-15 mm' },
  { value: 'coarse', labelKey: 'pointcloud.tier_coarse', fallback: 'Coarse, +/-50 mm' },
];

export function PointCloudPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  // Mirror DWG Takeoff: fall back to the first server project when no project
  // is active so the page is never a dead end after a context reset.
  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 5 * 60_000,
  });
  const projectId = activeProjectId || projects[0]?.id || '';
  const noProjects = !projectsLoading && projects.length === 0;

  const { data, isLoading, isError } = useQuery({
    queryKey: ['pointcloud-scans', projectId],
    queryFn: () => listScans(projectId),
    enabled: Boolean(projectId),
  });
  const scans = data?.items ?? [];

  // ── Viewer selection ──────────────────────────────────────────────────
  // The explicitly picked scan wins; otherwise auto-open the first scan the
  // points endpoint can serve so the page lands straight in the viewer.
  const [selectedScanId, setSelectedScanId] = useState<string | null>(null);
  const activeScan = useMemo(() => {
    const picked = selectedScanId ? scans.find((s) => s.id === selectedScanId) : undefined;
    if (picked && VIEWABLE_SCAN_STATUSES.includes(picked.status)) return picked;
    return scans.find((s) => VIEWABLE_SCAN_STATUSES.includes(s.status)) ?? null;
  }, [scans, selectedScanId]);

  // ── Upload state ──────────────────────────────────────────────────────
  const [file, setFile] = useState<File | null>(null);
  const [scanName, setScanName] = useState('');
  const [sourceType, setSourceType] = useState<ScanSourceType>('laser_scan');
  const [accuracyTier, setAccuracyTier] = useState<AccuracyTier>('standard');
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handlePickProject = useCallback(
    (id: string) => {
      const picked = projects.find((p) => p.id === id);
      if (picked) setActiveProject(picked.id, picked.name);
    },
    [projects, setActiveProject],
  );

  const handleFileSelect = useCallback(
    (f: File) => {
      const fmt = formatFromFileName(f.name);
      if (!fmt) {
        setUploadError(
          t('pointcloud.upload_unsupported_format', {
            defaultValue:
              'Unsupported format. Upload a point-cloud container: E57, LAS, LAZ, COPC, PLY, PCD, PTS or XYZ.',
          }),
        );
        return;
      }
      setUploadError(null);
      setFile(f);
      if (!scanName) setScanName(f.name.replace(/\.[^.]+$/, ''));
    },
    [scanName, t],
  );

  const clearFile = useCallback(() => {
    setFile(null);
    setUploadError(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const handleUpload = useCallback(async () => {
    if (!file) return;
    if (!projectId) {
      setUploadError(
        t('pointcloud.upload_no_project', {
          defaultValue: 'No active project yet. Open a project, then upload again.',
        }),
      );
      return;
    }
    const fmt = formatFromFileName(file.name);
    if (!fmt) return;

    setUploading(true);
    setUploadError(null);
    setProgress({ percent: 0, stage: 'preparing' });
    try {
      await uploadScan(
        {
          project_id: projectId,
          name: scanName || file.name.replace(/\.[^.]+$/, ''),
          source_type: sourceType,
          accuracy_tier: accuracyTier,
          original_format: fmt,
          total_size_bytes: file.size,
        },
        file,
        (p) => setProgress(p),
      );
      addToast({
        type: 'success',
        title: t('pointcloud.upload_done_title', { defaultValue: 'Scan uploaded' }),
        message: t('pointcloud.upload_done_msg', {
          defaultValue: 'The scan is registered and queued for processing.',
        }),
      });
      clearFile();
      setScanName('');
      void queryClient.invalidateQueries({ queryKey: ['pointcloud-scans', projectId] });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setUploadError(msg);
      addToast({
        type: 'error',
        title: t('pointcloud.upload_failed_title', { defaultValue: 'Upload failed' }),
        message: msg,
      });
    } finally {
      setUploading(false);
      setProgress(null);
    }
  }, [
    file,
    projectId,
    scanName,
    sourceType,
    accuracyTier,
    addToast,
    clearFile,
    queryClient,
    t,
  ]);

  const stageLabel = useMemo(() => {
    if (!progress) return '';
    switch (progress.stage) {
      case 'preparing':
        return t('pointcloud.stage_preparing', { defaultValue: 'Preparing upload...' });
      case 'uploading':
        return t('pointcloud.stage_uploading', { defaultValue: 'Uploading to storage...' });
      case 'finalizing':
        return t('pointcloud.stage_finalizing', { defaultValue: 'Finalizing...' });
      default:
        return t('pointcloud.stage_done', { defaultValue: 'Done' });
    }
  }, [progress, t]);

  return (
    <div className="relative space-y-5">
      <PointCloudBackground />

      <Breadcrumb items={[{ label: t('nav.point_cloud', 'Point Cloud') }]} />

      <header className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
          <ScanLine size={22} />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-content-primary">
              {t('nav.point_cloud', 'Point Cloud')}
            </h1>
            <Badge variant="blue" size="sm">
              {t('common.beta', 'BETA')}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-content-secondary">
            {t(
              'pointcloud.subtitle',
              'Reality capture for the project: laser scans, photogrammetry and LiDAR, registered against the model.',
            )}
          </p>
        </div>
      </header>

      <DismissibleInfo
        storageKey="pointcloud-intro"
        title={t('pointcloud.intro_title', 'What reality capture adds')}
        links={[
          { label: t('pointcloud.intro_link_bim', { defaultValue: 'BIM viewer' }), onClick: () => navigate('/bim') },
          { label: t('pointcloud.intro_link_boq', { defaultValue: 'Open BOQ' }), onClick: () => navigate('/boq') },
        ]}
      >
        {t(
          'pointcloud.intro_body',
          'Import survey-grade laser scans, photogrammetry and LiDAR clouds, view them, and use them to verify built quantities against the model, feed cut and fill into the estimate, and document site conditions. Upload a scan and open it in the cloud viewer below; model registration and deviation analysis arrive in the next releases.',
        )}
      </DismissibleInfo>

      {/* ── Upload window ──────────────────────────────────────────────── */}
      {!noProjects && (
        <Card>
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-content-primary">
                  {t('pointcloud.upload_title', { defaultValue: 'Upload a scan' })}
                </h2>
                <p className="mt-0.5 text-xs text-content-tertiary">
                  {t('pointcloud.upload_subtitle', {
                    defaultValue:
                      'Reality-capture clouds upload straight to object storage and register here.',
                  })}
                </p>
              </div>
              {/* Project picker - mirrors the DWG Takeoff selector so the scan
                  registers against the right project. */}
              <label className="flex items-center gap-2 text-xs text-content-tertiary">
                <span className="font-medium">{t('pointcloud.project_label', { defaultValue: 'Project' })}</span>
                <select
                  className="max-w-[220px] truncate rounded-lg border border-border-light bg-surface-secondary px-2.5 py-1.5 text-sm text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  value={projectId}
                  onChange={(e) => handlePickProject(e.target.value)}
                  disabled={uploading || projectsLoading}
                  data-testid="pointcloud-project-select"
                >
                  {projectsLoading && <option value="">{t('common.loading', 'Loading...')}</option>}
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label
              htmlFor="pointcloud-upload-input"
              role="button"
              tabIndex={0}
              aria-label={t('pointcloud.upload_dropzone_aria', {
                defaultValue: 'Upload a point-cloud file',
              })}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const f = e.dataTransfer.files?.[0];
                if (f) handleFileSelect(f);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                setDragOver(false);
              }}
              className={`flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-8 text-center transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2 ${
                uploading
                  ? 'cursor-default border-border-medium bg-surface-secondary/60'
                  : 'cursor-pointer'
              } ${
                dragOver
                  ? 'border-oe-blue bg-oe-blue/5'
                  : file
                    ? 'border-oe-blue/40 bg-oe-blue/5'
                    : 'border-border-medium hover:border-oe-blue/50 hover:bg-surface-secondary'
              }`}
            >
              {file ? (
                <>
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-oe-blue/10">
                    <CheckCircle2 size={24} className="text-oe-blue" />
                  </div>
                  <p className="text-sm font-medium text-content-primary">{file.name}</p>
                  <p className="text-2xs text-content-quaternary">{formatFileSize(file.size)}</p>
                  {!uploading && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        clearFile();
                      }}
                      className="inline-flex items-center gap-1 text-2xs text-content-tertiary underline hover:text-danger"
                    >
                      <X size={11} />
                      {t('pointcloud.upload_remove_file', { defaultValue: 'Remove file' })}
                    </button>
                  )}
                </>
              ) : (
                <>
                  <div className="flex h-14 w-14 items-center justify-center rounded-xl border border-border-light bg-surface-secondary">
                    <UploadCloud size={26} className="text-content-quaternary" />
                  </div>
                  <p className="text-sm font-medium text-content-primary">
                    {t('pointcloud.upload_drop_here', { defaultValue: 'Drop your scan here' })}
                  </p>
                  <p className="text-xs text-content-tertiary">
                    {t('pointcloud.upload_drop_hint', { defaultValue: 'or click to browse files' })}
                  </p>
                  <div className="mt-1 flex flex-wrap justify-center gap-1.5">
                    {SUPPORTED_FORMATS.map((fmt) => (
                      <span
                        key={fmt}
                        className="rounded-md border border-border-light bg-surface-secondary/60 px-2 py-0.5 text-2xs font-medium text-content-tertiary"
                      >
                        {fmt}
                      </span>
                    ))}
                  </div>
                </>
              )}
              <input
                id="pointcloud-upload-input"
                ref={fileInputRef}
                type="file"
                accept={ACCEPT_ATTR}
                className="hidden"
                disabled={uploading}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFileSelect(f);
                }}
              />
            </label>

            {/* Capture metadata - the tier gates what the scan may drive. */}
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('pointcloud.name_label', { defaultValue: 'Scan name' })}
                </label>
                <input
                  type="text"
                  className="w-full rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-primary placeholder-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  placeholder={t('pointcloud.name_placeholder', { defaultValue: 'e.g. Ground floor scan' })}
                  value={scanName}
                  onChange={(e) => setScanName(e.target.value)}
                  disabled={uploading}
                />
              </div>
              <div>
                <label className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('pointcloud.source_label', { defaultValue: 'Source' })}
                </label>
                <select
                  className="w-full rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  value={sourceType}
                  onChange={(e) => setSourceType(e.target.value as ScanSourceType)}
                  disabled={uploading}
                >
                  {SOURCE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(o.labelKey, { defaultValue: o.fallback })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('pointcloud.tier_label', { defaultValue: 'Accuracy tier' })}
                </label>
                <select
                  className="w-full rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  value={accuracyTier}
                  onChange={(e) => setAccuracyTier(e.target.value as AccuracyTier)}
                  disabled={uploading}
                >
                  {ACCURACY_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {t(o.labelKey, { defaultValue: o.fallback })}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {uploading && progress && (
              <div className="space-y-1.5">
                <div className="flex justify-between text-2xs">
                  <span className="text-content-secondary">{stageLabel}</span>
                  <span className="tabular-nums text-content-quaternary">{progress.percent}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-300"
                    style={{ width: `${progress.percent}%` }}
                  />
                </div>
              </div>
            )}

            {uploadError && (
              <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950/20">
                <AlertCircle size={14} className="mt-0.5 shrink-0 text-red-500" />
                <p className="text-2xs text-red-700 dark:text-red-300">{uploadError}</p>
              </div>
            )}

            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleUpload}
                disabled={!file || uploading || !projectId}
                data-testid="pointcloud-upload-submit"
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-oe-blue px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-oe-blue-dark hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-30"
              >
                {uploading ? <Loader2 size={16} className="animate-spin" /> : <UploadCloud size={16} />}
                {uploading
                  ? t('pointcloud.uploading', { defaultValue: 'Uploading...' })
                  : t('pointcloud.upload_cta', { defaultValue: 'Upload scan' })}
              </button>
            </div>
          </div>
        </Card>
      )}

      {/* ── Scan registry ──────────────────────────────────────────────── */}
      {noProjects ? (
        <Card>
          <EmptyState
            icon={<FolderOpen size={28} />}
            title={t('pointcloud.no_project_title', 'Open a project first')}
            description={t(
              'pointcloud.no_project_desc',
              'Reality-capture scans belong to a project. Create or open a project, then come back to upload and manage its scans.',
            )}
            action={{
              label: t('nav.projects', 'Go to projects'),
              onClick: () => navigate('/projects'),
            }}
          />
        </Card>
      ) : isLoading ? (
        <Card>
          <div className="flex items-center justify-center gap-2 py-10 text-content-tertiary">
            <Loader2 size={18} className="animate-spin" />
            <span className="text-sm">{t('common.loading', 'Loading...')}</span>
          </div>
        </Card>
      ) : isError ? (
        <Card>
          <div className="flex items-start gap-3 py-6 text-content-secondary">
            <AlertCircle size={20} className="mt-0.5 shrink-0 text-danger" />
            <div>
              <p className="text-sm font-medium text-content-primary">
                {t('pointcloud.error_title', 'Could not load scans')}
              </p>
              <p className="mt-1 text-sm">
                {t(
                  'pointcloud.error_desc',
                  'The reality-capture service did not respond. It may not be enabled on this deployment yet.',
                )}
              </p>
            </div>
          </div>
        </Card>
      ) : scans.length === 0 ? (
        <Card>
          <EmptyState
            icon={<ScanLine size={28} />}
            title={t('pointcloud.empty_title', 'No scans in this project yet')}
            description={t(
              'pointcloud.empty_desc',
              'Upload a reality-capture cloud above to register your first scan. Supported containers:',
            )}
          />
          <div className="mt-1 flex flex-wrap justify-center gap-1.5 pb-2">
            {SUPPORTED_FORMATS.map((fmt) => (
              <span
                key={fmt}
                className="rounded-md border border-border-light bg-surface-secondary/60 px-2 py-0.5 text-2xs font-medium text-content-tertiary"
              >
                {fmt}
              </span>
            ))}
          </div>
        </Card>
      ) : (
        <Card padding="none">
          <div className="border-b border-border-light px-4 py-2.5">
            <span className="text-sm font-semibold text-content-primary">
              {t('pointcloud.scans_title', 'Scans')}
            </span>
            <span className="ml-2 text-xs text-content-tertiary">{scans.length}</span>
          </div>
          <ul className="divide-y divide-border-light">
            {scans.map((scan) => {
              const viewable = VIEWABLE_SCAN_STATUSES.includes(scan.status);
              const isActive = activeScan?.id === scan.id;
              return (
                <li
                  key={scan.id}
                  className={`flex items-center gap-3 px-4 py-3 transition-colors ${
                    isActive ? 'bg-oe-blue/5' : ''
                  }`}
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                    <Boxes size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-content-primary">
                        {SOURCE_LABEL[scan.source_type] ?? scan.source_type}
                      </span>
                      <span className="rounded border border-border-light px-1.5 py-px text-2xs font-medium uppercase text-content-tertiary">
                        {scan.original_format}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-content-tertiary">
                      {ACCURACY_LABEL[scan.accuracy_tier] ?? scan.accuracy_tier}
                      {' · '}
                      {formatPointCount(scan.point_count)}
                    </p>
                  </div>
                  <Badge variant={STATUS_VARIANT[scan.status] ?? 'neutral'} size="sm">
                    {scan.status}
                  </Badge>
                  {viewable && (
                    <button
                      type="button"
                      onClick={() => setSelectedScanId(scan.id)}
                      data-testid={`pointcloud-view-${scan.id}`}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                        isActive
                          ? 'border-oe-blue/40 bg-oe-blue/10 text-oe-blue'
                          : 'border-border-light bg-surface-secondary text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
                      }`}
                    >
                      <Eye size={13} />
                      {isActive
                        ? t('pointcloud.viewing', { defaultValue: 'Viewing' })
                        : t('pointcloud.view_scan', { defaultValue: 'View' })}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {/* ── Viewer ─────────────────────────────────────────────────────── */}
      {activeScan && (
        <Card>
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-content-primary">
                  {t('pointcloud.viewer_title', { defaultValue: 'Cloud viewer' })}
                </h2>
                <p className="mt-0.5 text-xs text-content-tertiary">
                  {(SOURCE_LABEL[activeScan.source_type] ?? activeScan.source_type) +
                    ' · ' +
                    activeScan.original_format.toUpperCase()}
                </p>
              </div>
              <Badge variant={STATUS_VARIANT[activeScan.status] ?? 'neutral'} size="sm">
                {activeScan.status}
              </Badge>
            </div>
            <PointCloudViewer
              key={activeScan.id}
              scanId={activeScan.id}
              scanLabel={SOURCE_LABEL[activeScan.source_type] ?? activeScan.source_type}
            />
          </div>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        {CAPABILITY_CARDS.map((cap, i) => {
          const Icon = cap.icon;
          return (
            <Card key={i} className="space-y-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary text-content-secondary">
                <Icon size={16} />
              </div>
              <h3 className="text-sm font-semibold text-content-primary">
                {t(`pointcloud.cap_${i}_title`, cap.title)}
              </h3>
              <p className="text-xs leading-relaxed text-content-tertiary">
                {t(`pointcloud.cap_${i}_body`, cap.body)}
              </p>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

export default PointCloudPage;
