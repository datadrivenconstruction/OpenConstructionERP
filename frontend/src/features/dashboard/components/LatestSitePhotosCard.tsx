/**
 * "Latest site photos" dashboard widget.
 *
 * Shows the most recent photos across every project the user can access
 * (newest first) as a responsive strip of thumbnails. Each tile carries a
 * subtle bottom gradient with the project name and a relative date, and
 * clicks through to that project's photo gallery (/photos) after setting
 * the global active project so the gallery opens scoped to the clicked
 * project.
 *
 * Data comes from `GET /api/v1/documents/photos/recent/` which already
 * enforces access control server-side. Images load through `AuthImage`
 * (bearer-token fetch -> object URL) since the thumb route is auth-gated.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Camera, ArrowRight, Image as ImageIcon } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { Card, Button, AuthImage } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

interface RecentPhoto {
  id: string;
  project_id: string;
  project_name: string;
  caption: string | null;
  category: string;
  taken_at: string | null;
  created_at: string;
  /** Relative API path of the thumbnail, served via the authenticated
   *  thumb route (full-file fallback on a missing thumbnail). */
  file_url: string;
}

const RECENT_LIMIT = 12;

export function LatestSitePhotosCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);

  const { data: photos, isLoading } = useQuery({
    queryKey: ['dashboard-recent-photos', RECENT_LIMIT],
    queryFn: () =>
      apiGet<RecentPhoto[]>(`/v1/documents/photos/recent/?limit=${RECENT_LIMIT}`).catch(() => []),
    retry: false,
    staleTime: 60_000,
  });

  const items = useMemo(() => photos ?? [], [photos]);

  // Open the clicked project's photo gallery. The /photos page reads the
  // active project from the global project-context store, so we set it
  // first, then navigate - mirroring how other dashboard cards deep-link.
  const openProjectPhotos = (photo: RecentPhoto) => {
    setActiveProject(photo.project_id, photo.project_name);
    navigate('/photos');
  };

  // While the first fetch is in flight, render a quiet skeleton strip so
  // the card never flashes the empty state before data arrives.
  if (isLoading) {
    return (
      <div className="animate-card-in" style={{ animationDelay: '160ms' }}>
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Camera size={16} className="text-content-tertiary" strokeWidth={1.75} />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('dashboard.latest_photos_title', { defaultValue: 'Latest site photos' })}
            </h3>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {Array.from({ length: 6 }).map((_unused, i) => (
              <div
                key={i}
                className="aspect-square w-full animate-pulse rounded-xl bg-surface-secondary"
              />
            ))}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-card-in" style={{ animationDelay: '160ms' }}>
      <Card>
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Camera size={16} className="text-content-tertiary" strokeWidth={1.75} />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('dashboard.latest_photos_title', { defaultValue: 'Latest site photos' })}
            </h3>
          </div>
          {items.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              icon={<ArrowRight size={14} />}
              iconPosition="right"
              onClick={() => navigate('/photos')}
            >
              {t('dashboard.latest_photos_view_all', { defaultValue: 'View all' })}
            </Button>
          )}
        </div>

        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-surface-secondary text-content-quaternary">
              <ImageIcon size={22} strokeWidth={1.5} />
            </div>
            <p className="text-sm font-medium text-content-secondary">
              {t('dashboard.latest_photos_empty', { defaultValue: 'No site photos yet' })}
            </p>
            <p className="max-w-xs text-xs text-content-tertiary">
              {t('dashboard.latest_photos_empty_hint', {
                defaultValue: 'Upload progress photos from a project to see them here.',
              })}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {items.map((photo, index) => (
              <button
                key={photo.id}
                type="button"
                onClick={() => openProjectPhotos(photo)}
                title={t('dashboard.latest_photos_open', {
                  defaultValue: 'Open photos for {{project}}',
                  project: photo.project_name,
                })}
                className="group relative block aspect-square w-full overflow-hidden rounded-xl border border-border-light bg-surface-secondary text-left shadow-xs transition-all duration-normal ease-oe hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/40 animate-stagger-in"
                style={{ animationDelay: `${180 + index * 40}ms` }}
              >
                <AuthImage
                  src={photo.file_url}
                  alt={photo.caption || photo.project_name}
                  className="h-full w-full object-cover transition-transform duration-slow ease-oe group-hover:scale-[1.04]"
                  placeholder={
                    <div className="h-full w-full animate-pulse bg-surface-secondary" />
                  }
                  fallback={
                    <div className="flex h-full w-full items-center justify-center bg-surface-secondary text-content-quaternary">
                      <ImageIcon size={22} strokeWidth={1.5} />
                    </div>
                  }
                />
                {/* Bottom gradient carrying the project name + relative date. */}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 via-black/35 to-transparent px-2.5 pb-2 pt-6">
                  <div className="truncate text-xs font-semibold text-white">
                    {photo.project_name}
                  </div>
                  <DateDisplay
                    value={photo.taken_at || photo.created_at}
                    format="relative"
                    className="text-2xs text-white/80"
                  />
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
