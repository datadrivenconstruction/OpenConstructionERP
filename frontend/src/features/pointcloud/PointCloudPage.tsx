/**
 * Point Cloud / Reality Capture - Phase 0 read surface.
 *
 * Lists the reality-capture scans (laser scan / photogrammetry / LiDAR) for the
 * active project from GET /api/v1/pointcloud/scans. Phase 0 ships the scan
 * registry and the presigned direct-to-storage ingest; the cloud viewer, model
 * registration and deviation analysis land in later phases. Until a deployment
 * wires object storage, the page still renders the project's scans and a guided
 * empty state so the module is never a dead end.
 */
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ScanLine,
  FolderOpen,
  Layers,
  Ruler,
  ShieldCheck,
  Boxes,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { Badge, Breadcrumb, Card, DismissibleInfo, EmptyState } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/* The accepted upload containers, mirrored from the backend allow-list
   (backend/app/modules/pointcloud/models.py ACCEPTED_SCAN_FORMATS). Proprietary
   ReCap RCP/RCS is deliberately absent - export E57 or LAS instead. */
const SUPPORTED_FORMATS = ['E57', 'LAS', 'LAZ', 'COPC', 'PLY', 'PCD', 'PTS', 'XYZ'];

interface ScanDataset {
  id: string;
  project_id: string;
  source_type: string;
  original_format: string;
  accuracy_tier: string;
  status: string;
  point_count: number;
  created_at: string;
}

interface ScanDatasetList {
  items: ScanDataset[];
  total: number;
  offset: number;
  limit: number;
}

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

export function PointCloudPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['pointcloud-scans', activeProjectId],
    queryFn: () =>
      apiGet<ScanDatasetList>(`/v1/pointcloud/scans?project_id=${activeProjectId}`),
    enabled: Boolean(activeProjectId),
  });

  const scans = data?.items ?? [];

  return (
    <div className="space-y-5">
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
      >
        {t(
          'pointcloud.intro_body',
          'Bring survey-grade clouds into the project to verify built quantities against the model, feed cut and fill into the estimate, and document site conditions. Phase 0 ships the scan registry and the direct-to-storage ingest; the cloud viewer, model registration and deviation analysis arrive in the next releases.',
        )}
      </DismissibleInfo>

      {!activeProjectId ? (
        <Card>
          <EmptyState
            icon={<FolderOpen size={28} />}
            title={t('pointcloud.no_project_title', 'Open a project first')}
            description={t(
              'pointcloud.no_project_desc',
              'Reality-capture scans belong to a project. Pick a project from the selector above, then come back to see and manage its scans.',
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
              'Reality-capture clouds are uploaded straight to object storage and registered here. Supported containers:',
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
            {scans.map((scan) => (
              <li key={scan.id} className="flex items-center gap-3 px-4 py-3">
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
              </li>
            ))}
          </ul>
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
