// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Photo archive: every site photo of the project, whichever module took it, in one place.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarDays, Columns2, FolderPlus, Grid3x3, Images, Loader2, Map as MapIcon, Download, X } from 'lucide-react';
import { AuthImage, EmptyState, ErrorState, ModuleGuideButton, Badge } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { FieldItemsMap } from '@/shared/ui/FieldItemsMap';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import type { MapPin } from '@/shared/lib/photoEvidence';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  addToAlbum,
  createCompare,
  downloadExport,
  fetchAlbums,
  fetchCompares,
  fetchExport,
  fetchMap,
  fetchPhoto,
  fetchTimeline,
  fetchValidation,
  listPhotos,
  photosKeys,
  startExport,
  type Album,
  type ArchivePhoto,
} from './api';
import {
  activeFilterCount,
  categorySuggestion,
  PHOTO_CATEGORIES,
  filtersFromParams,
  filtersToParams,
  parseView,
  SOURCE_MODULES,
  type PhotoFilters,
  type PhotoView,
} from './model';
import { AlbumManager } from './components/AlbumManager';
import { BulkBar } from './components/BulkBar';
import { updatePhoto, type PhotoCategory as DocPhotoCategory } from '@/features/documents/api';
import { BeforeAfterSlider } from './components/BeforeAfterSlider';
import { PhotoLightbox } from './components/PhotoLightbox';
import { PhotoUploadDropzone } from './components/PhotoUploadDropzone';
import { photosGuide } from './photosGuide';

const VIEW_ICONS: Record<PhotoView, typeof Grid3x3> = {
  grid: Grid3x3,
  timeline: CalendarDays,
  map: MapIcon,
  albums: Images,
  compare: Columns2,
};

function FilterBar({
  filters,
  albums,
  onChange,
}: {
  filters: PhotoFilters;
  albums: Album[];
  onChange: (next: PhotoFilters) => void;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState(filters.q ?? '');
  useEffect(() => setQ(filters.q ?? ''), [filters.q]);
  const input = 'rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm';
  return (
    <div className="flex flex-wrap items-end gap-2" data-testid="photo-filter-bar">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onChange({ ...filters, q: q.trim() || undefined });
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onBlur={() => onChange({ ...filters, q: q.trim() || undefined })}
          placeholder={t('photoArchive.filters.search')}
          aria-label={t('photoArchive.filters.search')}
          className={`${input} w-48`}
        />
      </form>
      <label className="flex flex-col text-2xs text-content-tertiary">
        {t('photoArchive.filters.from')}
        <input
          type="date"
          value={filters.from ?? ''}
          onChange={(e) => onChange({ ...filters, from: e.target.value || undefined })}
          className={input}
        />
      </label>
      <label className="flex flex-col text-2xs text-content-tertiary">
        {t('photoArchive.filters.to')}
        <input
          type="date"
          value={filters.to ?? ''}
          onChange={(e) => onChange({ ...filters, to: e.target.value || undefined })}
          className={input}
        />
      </label>
      <select
        value={filters.source ?? ''}
        onChange={(e) => onChange({ ...filters, source: e.target.value || undefined })}
        aria-label={t('photoArchive.filters.source')}
        className={input}
      >
        <option value="">{t('photoArchive.filters.any_source')}</option>
        {SOURCE_MODULES.map((s) => (
          <option key={s} value={s}>
            {t(`photoArchive.source.${s}`)}
          </option>
        ))}
      </select>
      <select
        value={filters.category ?? ''}
        onChange={(e) => onChange({ ...filters, category: e.target.value || undefined })}
        aria-label={t('photoArchive.filters.category')}
        className={input}
      >
        <option value="">{t('photos.all_categories')}</option>
        {PHOTO_CATEGORIES.map((c) => (
          <option key={c} value={c}>
            {t(`photos.cat_${c}`)}
          </option>
        ))}
      </select>
      <select
        value={filters.album ?? ''}
        onChange={(e) => onChange({ ...filters, album: e.target.value || undefined })}
        aria-label={t('photoArchive.filters.album')}
        className={input}
      >
        <option value="">{t('photoArchive.filters.any_album')}</option>
        {albums.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>
      <label className="inline-flex items-center gap-1 pb-1.5 text-sm">
        <input
          type="checkbox"
          checked={Boolean(filters.hasGps)}
          onChange={(e) => onChange({ ...filters, hasGps: e.target.checked || undefined })}
        />
        {t('photoArchive.filters.has_gps')}
      </label>
      {filters.tag && (
        <button
          type="button"
          onClick={() => onChange({ ...filters, tag: undefined })}
          className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-1 text-xs"
        >
          #{filters.tag}
          <X className="h-3 w-3" aria-label={t('photoArchive.filters.clear')} />
        </button>
      )}
      {filters.targetKind && (
        <button
          type="button"
          onClick={() => onChange({ ...filters, targetKind: undefined, targetId: undefined })}
          className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-1 text-xs"
        >
          {t(`photoArchive.target.${filters.targetKind}`)}
          <X className="h-3 w-3" aria-label={t('photoArchive.filters.clear')} />
        </button>
      )}
      {activeFilterCount(filters) > 0 && (
        <button type="button" onClick={() => onChange({})} className="pb-1.5 text-xs text-oe-blue hover:underline">
          {t('photoArchive.filters.clear_all')}
        </button>
      )}
    </div>
  );
}

function Thumb({
  photo,
  selected,
  selectMode,
  onOpen,
  onToggle,
  onApplySuggestion,
}: {
  photo: ArchivePhoto;
  selected: boolean;
  selectMode: boolean;
  onOpen: () => void;
  onToggle: () => void;
  onApplySuggestion: (photo: ArchivePhoto) => void;
}) {
  const { t } = useTranslation();
  const suggestion = selectMode ? null : categorySuggestion(photo);
  const field = photo.tags.some((tag) => tag.toLowerCase() === 'field');
  return (
    <li className={`group relative overflow-hidden rounded-lg border ${selected ? 'border-oe-blue ring-2 ring-oe-blue' : 'border-border-light'}`}>
      <button
        type="button"
        onClick={selectMode ? onToggle : onOpen}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (selectMode) onToggle();
            else onOpen();
          }
        }}
        aria-pressed={selectMode ? selected : undefined}
        className="block aspect-square w-full bg-surface-secondary"
      >
        {photo.thumb_status === 'failed' ? (
          <span className="flex h-full items-center justify-center p-2 text-center text-xs text-content-tertiary">
            {t('photoArchive.thumb_failed')}
          </span>
        ) : (
          <AuthImage src={photo.thumb_url} alt={photo.caption || photo.filename} className="h-full w-full object-cover" />
        )}
      </button>
      <label className="absolute left-1.5 top-1.5 rounded bg-white/80 p-0.5">
        <input type="checkbox" checked={selected} onChange={onToggle} aria-label={t('photoArchive.select')} />
      </label>
      {photo.source_module !== 'documents' && (
        <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-2xs text-white">
          {t(`photoArchive.source.${photo.source_module}`)}
        </span>
      )}
      <div className="flex items-center gap-1 px-2 py-1 text-xs">
        <span className="min-w-0 flex-1 truncate">
          {photo.caption || (photo.taken_at ? <DateDisplay value={photo.taken_at} /> : photo.filename)}
        </span>
        <span className="shrink-0 text-2xs text-content-tertiary">
          {t(`photos.cat_${photo.category}`, { defaultValue: photo.category })}
        </span>
        {field && (
          <span className="shrink-0 rounded bg-emerald-100 px-1 text-2xs text-emerald-800">{t('photoArchive.field_badge')}</span>
        )}
      </div>
      {suggestion && (
        <button
          type="button"
          onClick={() => onApplySuggestion(photo)}
          title={t('photoArchive.suggestion.apply_hint')}
          className="mx-2 mb-1.5 rounded bg-purple-50 px-1.5 py-0.5 text-left text-2xs text-purple-800 hover:bg-purple-100"
        >
          {suggestion.confidence !== null
            ? t('photoArchive.suggestion.with_conf', {
                cat: t(`photos.cat_${suggestion.category}`),
                pct: Math.round(suggestion.confidence * 100),
              })
            : t('photoArchive.suggestion.plain', { cat: t(`photos.cat_${suggestion.category}`) })}
        </button>
      )}
    </li>
  );
}

function useExport(projectId: string) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [jobId, setJobId] = useState<string | null>(null);
  const status = useQuery({
    queryKey: ['photo-archive', 'export', jobId],
    queryFn: () => fetchExport(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: (q) => (q.state.data?.ready || q.state.data?.status === 'failed' ? false : 2000),
  });
  useEffect(() => {
    if (!jobId || !status.data) return;
    if (status.data.ready) {
      void downloadExport(jobId);
      addToast({ type: 'success', title: t('photoArchive.export.ready', { count: status.data.photo_count ?? 0 }) });
      setJobId(null);
    } else if (status.data.status === 'failed') {
      addToast({ type: 'error', title: t('photoArchive.export.failed') });
      setJobId(null);
    }
  }, [jobId, status.data, addToast, t]);
  const start = useMutation({
    mutationFn: (opts: { photo_ids?: string[]; album_id?: string }) => startExport(projectId, opts),
    onSuccess: (job) => {
      setJobId(job.job_id);
      addToast({ type: 'info', title: t('photoArchive.export.started') });
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.export.failed'), message: getErrorMessage(err) }),
  });
  return { start: start.mutate, busy: start.isPending || Boolean(jobId), progress: status.data?.progress_percent ?? 0 };
}

function PhotosArchive({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [params, setParams] = useSearchParams();
  const view = parseView(params.get('view'));
  const filters = useMemo(() => filtersFromParams(params), [params]);
  const [open, setOpen] = useState<ArchivePhoto | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [selectModeOn, setSelectMode] = useState(false);
  // Ticking a checkbox outside select mode enters it, as the old gallery did.
  const selectMode = selectModeOn || selected.length > 0;
  const exitSelect = () => {
    setSelectMode(false);
    setSelected([]);
  };
  useEffect(() => {
    if (!selectMode) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !open) exitSelect();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
  const deepLinkPhoto = params.get('photo');
  useEffect(() => {
    if (!deepLinkPhoto) return;
    fetchPhoto(deepLinkPhoto)
      .then(setOpen)
      .catch(() => addToast({ type: 'error', title: t('photoArchive.load_failed') }));
    const next = new URLSearchParams(params);
    next.delete('photo');
    setParams(next, { replace: true });
    // Runs once per deep link; params change on every filter edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkPhoto]);
  const applySuggestion = useMutation({
    mutationFn: (photo: ArchivePhoto) => {
      const sug = categorySuggestion(photo)!;
      const lower = new Set(photo.tags.map((x) => x.toLowerCase()));
      const tags = [...photo.tags, ...sug.tags.filter((x) => !lower.has(x.toLowerCase()))];
      return updatePhoto(photo.id, { category: sug.category as DocPhotoCategory, tags });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: photosKeys.all });
      addToast({ type: 'success', title: t('photoArchive.suggestion.applied') });
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.save_failed'), message: getErrorMessage(err) }),
  });
  const exporter = useExport(projectId);

  const setFilters = (next: PhotoFilters) => setParams(filtersToParams(next, params), { replace: true });
  const setView = (v: PhotoView) => {
    const next = new URLSearchParams(params);
    next.set('view', v);
    setParams(next, { replace: true });
  };

  const albums = useQuery({ queryKey: photosKeys.albums(projectId), queryFn: () => fetchAlbums(projectId) });
  const validation = useQuery({
    queryKey: photosKeys.validation(projectId),
    queryFn: () => fetchValidation(projectId),
    staleTime: 60_000,
  });
  const grid = useInfiniteQuery({
    queryKey: photosKeys.list(projectId, filters),
    queryFn: ({ pageParam }) => listPhotos(projectId, filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: view === 'grid',
  });
  const timeline = useQuery({
    queryKey: photosKeys.timeline(projectId, filters),
    queryFn: () => fetchTimeline(projectId, filters),
    enabled: view === 'timeline',
  });
  const geo = useQuery({
    queryKey: photosKeys.map(projectId, filters),
    queryFn: () => fetchMap(projectId, filters),
    enabled: view === 'map',
  });
  const compares = useQuery({
    queryKey: photosKeys.compares(projectId),
    queryFn: () => fetchCompares(projectId),
    enabled: view === 'compare',
  });

  const gridPhotos = useMemo(() => grid.data?.pages.flatMap((p) => p.items) ?? [], [grid.data]);
  const total = grid.data?.pages[0]?.total ?? 0;
  const pins: MapPin[] = useMemo(
    () =>
      (geo.data?.features ?? []).map((f) => ({
        id: f.id,
        lon: f.geometry.coordinates[0],
        lat: f.geometry.coordinates[1],
        label: String(f.properties.caption || f.properties.filename || ''),
      })),
    [geo.data],
  );

  const toggle = (id: string) => setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  const addSelectedToAlbum = useMutation({
    mutationFn: (albumId: string) => addToAlbum(albumId, selected),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: photosKeys.all });
      addToast({ type: 'success', title: t('photoArchive.albums.added', { count: res.added }) });
      setSelected([]);
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.albums.add_failed'), message: getErrorMessage(err) }),
  });
  const compareSelected = useMutation({
    mutationFn: () => {
      const picked = selected.map((id) => gridPhotos.find((p) => p.id === id)).filter(Boolean) as ArchivePhoto[];
      const key = (p: ArchivePhoto) => p.taken_at ?? p.created_at ?? '';
      const [before, after] = [...picked].sort((a, b) => key(a).localeCompare(key(b)));
      return createCompare(projectId, before!.id, after!.id, '');
    },
    onSuccess: (cmp) => {
      qc.invalidateQueries({ queryKey: photosKeys.compares(projectId) });
      setSelected([]);
      navigate(`/photos/compare/${cmp.id}`);
    },
    onError: (err) => addToast({ type: 'error', title: t('photoArchive.compare.create_failed'), message: getErrorMessage(err) }),
  });

  const findings = validation.data?.findings ?? [];
  const problems = findings.filter((f) => f.severity === 'error' || f.severity === 'warning').length;

  return (
    <div className="space-y-4">
      <PageHeader
        srTitle={t('photos.title')}
        subtitle={t('photoArchive.subtitle')}
        actions={
          <div className="flex items-center gap-2">
            {validation.data && (
              <Badge variant={problems === 0 ? 'success' : validation.data.status === 'errors' ? 'error' : 'warning'}>
                {problems === 0 ? t('photoArchive.validation.clean') : t('photoArchive.validation.issues', { count: problems })}
              </Badge>
            )}
            <button
              type="button"
              disabled={exporter.busy}
              onClick={() => exporter.start(filters.album ? { album_id: filters.album } : {})}
              className="inline-flex items-center gap-1 rounded-md border border-border-light px-3 py-1.5 text-sm disabled:opacity-50"
            >
              {exporter.busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Download className="h-4 w-4" aria-hidden />}
              {exporter.busy ? t('photoArchive.export.progress', { value: exporter.progress }) : t('photoArchive.export.all')}
            </button>
            {view === 'grid' && (
              <button
                type="button"
                onClick={() => (selectMode ? exitSelect() : setSelectMode(true))}
                aria-pressed={selectMode}
                className="rounded-md border border-border-light px-3 py-1.5 text-sm"
              >
                {selectMode ? t('photoArchive.bulk.done') : t('photoArchive.bulk.select')}
              </button>
            )}
            <ModuleGuideButton content={photosGuide} />
          </div>
        }
      />

      <PhotoUploadDropzone projectId={projectId} />

      <nav className="flex gap-1 border-b border-border-light" role="tablist" aria-label={t('photoArchive.views')}>
        {(Object.keys(VIEW_ICONS) as PhotoView[]).map((v) => {
          const Icon = VIEW_ICONS[v];
          return (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm ${
                view === v ? 'border-oe-blue text-oe-blue' : 'border-transparent text-content-secondary hover:text-content-primary'
              }`}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {t(`photoArchive.view.${v}`)}
            </button>
          );
        })}
      </nav>

      {view !== 'albums' && view !== 'compare' && (
        <FilterBar filters={filters} albums={albums.data ?? []} onChange={setFilters} />
      )}

      {selectMode && view === 'grid' && (
        <BulkBar photos={gridPhotos} selected={selected} allIds={gridPhotos.map((p) => p.id)} onSelect={setSelected}>
          {(albums.data ?? []).length > 0 && (
            <select
              defaultValue=""
              onChange={(e) => e.target.value && addSelectedToAlbum.mutate(e.target.value)}
              aria-label={t('photoArchive.albums.add_to')}
              className="rounded border border-border-light bg-surface-primary px-2 py-1 text-xs"
            >
              <option value="">{t('photoArchive.albums.add_to')}</option>
              {(albums.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            disabled={selected.length !== 2 || compareSelected.isPending}
            onClick={() => compareSelected.mutate()}
            title={t('photoArchive.compare.pick_two')}
            className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-1 text-xs disabled:opacity-50"
          >
            <Columns2 className="h-3 w-3" aria-hidden />
            {t('photoArchive.compare.make')}
          </button>
          <button
            type="button"
            disabled={exporter.busy}
            onClick={() => exporter.start({ photo_ids: selected })}
            className="inline-flex items-center gap-1 rounded border border-border-light px-2 py-1 text-xs disabled:opacity-50"
          >
            <Download className="h-3 w-3" aria-hidden />
            {t('photoArchive.export.selected')}
          </button>
        </BulkBar>
      )}

      {view === 'grid' &&
        (grid.isError ? (
          <ErrorState title={t('photoArchive.load_failed')} hint={getErrorMessage(grid.error)} onRetry={() => grid.refetch()} />
        ) : grid.isLoading ? (
          <Loader2 className="mx-auto h-6 w-6 animate-spin text-content-tertiary" aria-hidden />
        ) : gridPhotos.length === 0 ? (
          <EmptyState
            icon={<Images className="h-8 w-8" />}
            title={activeFilterCount(filters) ? t('photoArchive.empty_filtered') : t('photoArchive.empty_title')}
            description={activeFilterCount(filters) ? undefined : t('photoArchive.empty_body')}
          />
        ) : (
          <>
            <p className="text-xs text-content-tertiary">{t('photoArchive.count', { count: total })}</p>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6" data-testid="photo-grid">
              {gridPhotos.map((p) => (
                <Thumb
                  key={p.id}
                  photo={p}
                  selected={selected.includes(p.id)}
                  selectMode={selectMode}
                  onOpen={() => setOpen(p)}
                  onToggle={() => toggle(p.id)}
                  onApplySuggestion={(photo) => applySuggestion.mutate(photo)}
                />
              ))}
            </ul>
            {grid.hasNextPage && (
              <div className="text-center">
                <button
                  type="button"
                  disabled={grid.isFetchingNextPage}
                  onClick={() => grid.fetchNextPage()}
                  className="rounded-md border border-border-light px-4 py-1.5 text-sm disabled:opacity-50"
                >
                  {grid.isFetchingNextPage ? t('photoArchive.loading') : t('photoArchive.load_more')}
                </button>
              </div>
            )}
          </>
        ))}

      {view === 'timeline' &&
        (timeline.isError ? (
          <ErrorState title={t('photoArchive.load_failed')} onRetry={() => timeline.refetch()} />
        ) : (timeline.data ?? []).length === 0 && !timeline.isLoading ? (
          <EmptyState icon={<CalendarDays className="h-8 w-8" />} title={t('photoArchive.empty_title')} />
        ) : (
          <ol className="space-y-6">
            {(timeline.data ?? []).map((day) => (
              <li key={day.date}>
                <h3 className="mb-2 text-sm font-semibold">
                  <DateDisplay value={`${day.date}T12:00:00`} />
                  <span className="ml-2 text-xs font-normal text-content-tertiary">
                    {t('photoArchive.count', { count: day.count })}
                    {day.undated > 0 && ` · ${t('photoArchive.timeline.undated', { count: day.undated })}`}
                  </span>
                </h3>
                <ul className="flex gap-2 overflow-x-auto pb-1">
                  {day.photos.map((p) => (
                    <li key={p.id} className="shrink-0">
                      <button type="button" aria-label={p.caption || p.filename} onClick={() => setOpen(p)} className="block h-24 w-24 overflow-hidden rounded border border-border-light">
                        <AuthImage src={p.thumb_url} alt={p.caption || p.filename} className="h-full w-full object-cover" />
                      </button>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        ))}

      {view === 'map' &&
        (geo.isError ? (
          <ErrorState title={t('photoArchive.load_failed')} onRetry={() => geo.refetch()} />
        ) : pins.length === 0 && !geo.isLoading ? (
          <EmptyState icon={<MapIcon className="h-8 w-8" />} title={t('photoArchive.map.empty_title')} description={t('photoArchive.map.empty_body')} />
        ) : (
          <FieldItemsMap
            pins={pins}
            total={pins.length}
            className="h-[60vh]"
            onSelect={(id) => {
              fetchPhoto(id)
                .then(setOpen)
                .catch((err) => addToast({ type: 'error', title: t('photoArchive.load_failed'), message: getErrorMessage(err) }));
            }}
          />
        ))}

      {view === 'albums' && (
        <AlbumManager
          projectId={projectId}
          onOpen={(a) => setParams(filtersToParams({ album: a.id }, new URLSearchParams({ view: 'grid' })), { replace: true })}
          onExport={(a) => exporter.start({ album_id: a.id })}
        />
      )}

      {view === 'compare' &&
        (compares.isError ? (
          <ErrorState title={t('photoArchive.load_failed')} onRetry={() => compares.refetch()} />
        ) : (compares.data ?? []).length === 0 && !compares.isLoading ? (
          <EmptyState
            icon={<Columns2 className="h-8 w-8" />}
            title={t('photoArchive.compare.empty_title')}
            description={t('photoArchive.compare.empty_body')}
            action={{ label: t('photoArchive.compare.go_pick'), onClick: () => setView('grid') }}
          />
        ) : (
          <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {(compares.data ?? []).map((c) => (
              <li key={c.id} className="space-y-1">
                <BeforeAfterSlider before={c.before} after={c.after} />
                <button type="button" onClick={() => navigate(`/photos/compare/${c.id}`)} className="text-sm text-oe-blue hover:underline">
                  {c.title || t('photoArchive.compare.untitled')}
                </button>
              </li>
            ))}
          </ul>
        ))}

      {open && (
        <PhotoLightbox
          photo={open}
          photos={view === 'grid' ? gridPhotos : []}
          onClose={() => setOpen(null)}
          onNavigate={setOpen}
        />
      )}
      {selected.length === 0 && view === 'grid' && (albums.data ?? []).length === 0 && gridPhotos.length > 0 && (
        <p className="flex items-center gap-1 text-xs text-content-tertiary">
          <FolderPlus className="h-3 w-3" aria-hidden />
          {t('photoArchive.albums.tip')}
        </p>
      )}
    </div>
  );
}

export function PhotosPage() {
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  return <RequiresProject>{projectId ? <PhotosArchive projectId={projectId} /> : null}</RequiresProject>;
}

export default PhotosPage;
