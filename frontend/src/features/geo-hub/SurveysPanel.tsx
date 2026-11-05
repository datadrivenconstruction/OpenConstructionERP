// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Surveys panel: add a dated drone orthophoto (or link a scan), show it on the
// globe through the existing raster overlay layer, and record the observed
// progress per schedule activity next to the planned one.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Eye, EyeOff, Loader2, ScanLine, Trash2, UploadCloud, X } from 'lucide-react';

import { getErrorMessage } from '@/shared/lib/api';
import { Badge } from '@/shared/ui';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { listScans } from '@/features/pointcloud/api';

import {
  deleteSurvey,
  getSurveyProgress,
  listRasterOverlays,
  listSurveys,
  putSurveyObservation,
  surveyFromScan,
  updateRasterOverlay,
  uploadOrthophoto,
} from './api';
import {
  KIND_DEFAULT,
  PLATFORM_DEFAULT,
  SURVEY_PLATFORMS,
  UPLOAD_ERROR_DEFAULT,
  WARNING_DEFAULT,
  compareOpacities,
  formatGsd,
  formatSize,
  formatVariance,
  parseObservedPct,
  sortSurveys,
  todayIso,
  validateUploadForm,
  varianceBadge,
} from './surveyProgress';
import type { SurveyCapture, SurveyPlatform, SurveyProgressRow } from './types';
import { fmtFixed } from '@/shared/lib/formatters';

interface SurveysPanelProps {
  projectId: string;
  onClose: () => void;
}

export function SurveysPanel({ projectId, onClose }: SurveysPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { confirm, ...confirmProps } = useConfirm();
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [scanId, setScanId] = useState<string>('');
  const [capturedOn, setCapturedOn] = useState<string>(() => todayIso());
  const [platform, setPlatform] = useState<SurveyPlatform>('drone');
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [lastAdded, setLastAdded] = useState<SurveyCapture | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [earlierId, setEarlierId] = useState<string>('');
  const [laterId, setLaterId] = useState<string>('');
  const [blend, setBlend] = useState<number>(50);

  const surveysQuery = useQuery({
    queryKey: ['geo-hub', 'surveys', projectId],
    queryFn: () => listSurveys(projectId),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });
  // Same key as OverlayPanel / OverlayLayer, so a visibility change repaints the globe.
  const overlaysQuery = useQuery({
    queryKey: ['geo-hub', 'raster-overlays', projectId],
    queryFn: () => listRasterOverlays(projectId, { includeHidden: true }),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });
  const scansQuery = useQuery({
    queryKey: ['pointcloud', 'scans', projectId],
    queryFn: () => listScans(projectId),
    enabled: Boolean(projectId),
    staleTime: 60_000,
    retry: false,
  });

  const surveys = useMemo(() => sortSurveys(surveysQuery.data ?? []), [surveysQuery.data]);
  const selected = surveys.find((s) => s.id === selectedId) ?? null;
  const withImage = surveys.filter((s) => s.overlay_id);
  const overlayById = useMemo(() => {
    const m = new Map<string, { visible: boolean }>();
    for (const o of overlaysQuery.data ?? []) m.set(o.id, { visible: o.visible });
    return m;
  }, [overlaysQuery.data]);

  const progressQuery = useQuery({
    queryKey: ['geo-hub', 'survey-progress', selectedId],
    queryFn: () => getSurveyProgress(selectedId as string),
    enabled: Boolean(selectedId),
  });

  const refreshOverlays = () => queryClient.invalidateQueries({ queryKey: ['geo-hub', 'raster-overlays', projectId] });
  const fail = (titleKey: string, titleDefault: string, err: unknown) =>
    useToastStore.getState().addToast({
      type: 'error',
      title: t(titleKey, { defaultValue: titleDefault }),
      message: getErrorMessage(err),
    });

  const addMutation = useMutation({
    mutationFn: async () => {
      if (file) return uploadOrthophoto(projectId, file, { capturedOn, platform });
      return surveyFromScan({ scan_id: scanId, captured_on: capturedOn, platform });
    },
    onSuccess: (created) => {
      setLastAdded(created);
      setSelectedId(created.id);
      setFile(null);
      setScanId('');
      if (fileInput.current) fileInput.current.value = '';
      queryClient.invalidateQueries({ queryKey: ['geo-hub', 'surveys', projectId] });
      refreshOverlays();
    },
    onError: (err) => fail('geo_hub.surveys.upload.failed', 'The survey could not be added.', err),
  });

  const visibilityMutation = useMutation({
    mutationFn: ({ overlayId, visible }: { overlayId: string; visible: boolean }) =>
      updateRasterOverlay(overlayId, { visible }),
    onSuccess: refreshOverlays,
    onError: (err) => fail('geo_hub.surveys.load_failed', 'Could not load surveys.', err),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSurvey(id),
    onSuccess: (_d, id) => {
      if (selectedId === id) setSelectedId(null);
      queryClient.invalidateQueries({ queryKey: ['geo-hub', 'surveys', projectId] });
      refreshOverlays();
    },
    onError: (err) => fail('geo_hub.surveys.list.delete_failed', 'The survey was not deleted', err),
  });

  const observeMutation = useMutation({
    mutationFn: ({ activityId, value }: { activityId: string; value: number }) =>
      putSurveyObservation(selectedId as string, activityId, { observed_pct: value }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['geo-hub', 'survey-progress', selectedId] }),
    onError: (err) => fail('geo_hub.surveys.progress.save_failed', 'The observed progress could not be saved.', err),
  });

  // Compare slider: the two chosen overlays share the existing opacity control, so the blend is a pair of PATCHes.
  const earlier = surveys.find((s) => s.id === earlierId);
  const later = surveys.find((s) => s.id === laterId);
  useEffect(() => {
    if (!earlier?.overlay_id || !later?.overlay_id || earlier.id === later.id) return;
    const handle = window.setTimeout(() => {
      const { earlier: a, later: b } = compareOpacities(blend / 100);
      void Promise.all([
        updateRasterOverlay(earlier.overlay_id as string, { opacity: String(a), visible: true }),
        updateRasterOverlay(later.overlay_id as string, { opacity: String(b), visible: true }),
      ])
        .then(refreshOverlays)
        .catch((err) => fail('geo_hub.surveys.load_failed', 'Could not load surveys.', err));
    }, 300);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blend, earlier?.id, later?.id]);

  const submit = () => {
    const errors = validateUploadForm({ file, scanId: scanId || null, capturedOn }, todayIso());
    setFormErrors(errors);
    if (errors.length === 0) addMutation.mutate();
  };

  const toggleOverlay = (s: SurveyCapture) => {
    if (!s.overlay_id) return;
    const visible = overlayById.get(s.overlay_id)?.visible ?? false;
    visibilityMutation.mutate({ overlayId: s.overlay_id, visible: !visible });
  };

  const select = (s: SurveyCapture) => {
    setSelectedId(s.id);
    if (s.overlay_id && overlayById.get(s.overlay_id)?.visible === false) {
      visibilityMutation.mutate({ overlayId: s.overlay_id, visible: true });
    }
  };

  const scans = scansQuery.data?.items ?? [];

  return (
    <aside
      data-testid="geo-surveys-panel"
      className={[
        'absolute top-3 right-[21rem] z-20 flex max-h-[calc(100%-1.5rem)] w-[26rem] max-w-[calc(100vw-1.5rem)] flex-col',
        'rounded-xl border border-white/15 bg-white/95 dark:bg-slate-900/90',
        'shadow-lg shadow-black/20 ring-1 ring-black/5 backdrop-blur-md',
        'hidden md:flex',
      ].join(' ')}
      aria-label={t('geo_hub.surveys.title', { defaultValue: 'Site surveys' })}
    >
      <div className="flex items-center justify-between gap-2 border-b border-black/5 px-3 py-2.5 dark:border-white/10">
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-content-secondary">
          {t('geo_hub.surveys.title', { defaultValue: 'Site surveys' })}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('geo_hub.surveys.close', { defaultValue: 'Close surveys' })}
          className="rounded-md p-1 text-content-tertiary hover:bg-black/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 dark:hover:bg-white/10"
        >
          <X size={14} />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3 text-xs">
        {/* Upload card */}
        <section data-testid="geo-surveys-upload" className="space-y-2 rounded-lg border border-black/10 p-2.5 dark:border-white/10">
          <h3 className="font-semibold text-content-primary">
            {t('geo_hub.surveys.upload.title', { defaultValue: 'Add a survey' })}
          </h3>
          <label
            className="flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed border-black/20 px-3 py-3 text-center text-content-secondary hover:border-oe-blue dark:border-white/20"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) {
                setFile(dropped);
                setScanId('');
              }
            }}
          >
            <UploadCloud size={18} />
            <span>{file ? file.name : t('geo_hub.surveys.upload.drop', { defaultValue: 'Drop a GeoTIFF here or click to choose' })}</span>
            <span className="text-2xs text-content-tertiary">
              {t('geo_hub.surveys.upload.file_hint', { defaultValue: 'GeoTIFF (.tif, .tiff)' })}
            </span>
            <input
              ref={fileInput}
              type="file"
              accept=".tif,.tiff,image/tiff"
              className="sr-only"
              data-testid="geo-surveys-file"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                if (e.target.files?.[0]) setScanId('');
              }}
            />
          </label>
          {scans.length > 0 && (
            <label className="block">
              <span className="mb-0.5 flex items-center gap-1 text-content-secondary">
                <ScanLine size={12} />
                {t('geo_hub.surveys.upload.or_scan', { defaultValue: 'or link an existing scan' })}
              </span>
              <select
                value={scanId}
                onChange={(e) => {
                  setScanId(e.target.value);
                  if (e.target.value) {
                    setFile(null);
                    if (fileInput.current) fileInput.current.value = '';
                  }
                }}
                data-testid="geo-surveys-scan"
                className="w-full rounded-md border border-black/15 bg-transparent px-2 py-1 dark:border-white/20"
              >
                <option value="">{t('geo_hub.surveys.upload.scan_none', { defaultValue: 'No scan selected' })}</option>
                {scans.map((sc) => (
                  <option key={sc.id} value={sc.id}>
                    {sc.source_type} · {sc.original_format.toUpperCase()} · {sc.created_at.slice(0, 10)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-0.5 block text-content-secondary">
                {t('geo_hub.surveys.upload.date', { defaultValue: 'Flight date' })}
              </span>
              <input
                type="date"
                value={capturedOn}
                max={todayIso()}
                onChange={(e) => setCapturedOn(e.target.value)}
                data-testid="geo-surveys-date"
                className="w-full rounded-md border border-black/15 bg-transparent px-2 py-1 dark:border-white/20"
              />
            </label>
            <label className="block">
              <span className="mb-0.5 block text-content-secondary">
                {t('geo_hub.surveys.upload.platform', { defaultValue: 'Platform' })}
              </span>
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value as SurveyPlatform)}
                data-testid="geo-surveys-platform"
                className="w-full rounded-md border border-black/15 bg-transparent px-2 py-1 dark:border-white/20"
              >
                {SURVEY_PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {t(`geo_hub.surveys.platform.${p}`, { defaultValue: PLATFORM_DEFAULT[p] })}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {formErrors.length > 0 && (
            <ul role="alert" className="space-y-0.5 text-red-600 dark:text-red-400">
              {formErrors.map((code) => (
                <li key={code}>{t(`geo_hub.surveys.upload.error.${code}`, { defaultValue: UPLOAD_ERROR_DEFAULT[code] ?? code })}</li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={submit}
            disabled={addMutation.isPending}
            data-testid="geo-surveys-submit"
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 font-semibold text-white hover:bg-oe-blue/90 disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            {addMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <UploadCloud size={13} />}
            {addMutation.isPending
              ? t('geo_hub.surveys.upload.uploading', { defaultValue: 'Uploading...' })
              : t('geo_hub.surveys.upload.submit', { defaultValue: 'Add survey' })}
          </button>
          {lastAdded && (
            <div data-testid="geo-surveys-result" className="space-y-1">
              <div className="flex flex-wrap gap-1">
                {formatGsd(lastAdded.gsd_cm) && (
                  <Badge variant="neutral" size="sm">
                    {t('geo_hub.surveys.chip.gsd', { value: formatGsd(lastAdded.gsd_cm), defaultValue: 'GSD {{value}}' })}
                  </Badge>
                )}
                <Badge variant={lastAdded.crs_epsg ? 'neutral' : 'warning'} size="sm">
                  {lastAdded.crs_epsg
                    ? t('geo_hub.surveys.chip.crs', { code: lastAdded.crs_epsg, defaultValue: 'EPSG:{{code}}' })
                    : t('geo_hub.surveys.chip.no_crs', { defaultValue: 'Not georeferenced' })}
                </Badge>
                {formatSize(lastAdded.width_px, lastAdded.height_px) && (
                  <Badge variant="neutral" size="sm">
                    {formatSize(lastAdded.width_px, lastAdded.height_px)}
                  </Badge>
                )}
              </div>
              {lastAdded.warnings.map((w) => (
                <p key={w} className="text-amber-700 dark:text-amber-300">
                  {t(`geo_hub.surveys.warning.${w}`, { defaultValue: WARNING_DEFAULT[w] ?? w })}
                </p>
              ))}
              {lastAdded.findings.map((f) => (
                <p key={f.rule_id} className={f.severity === 'info' ? 'text-content-tertiary' : 'text-amber-700 dark:text-amber-300'}>
                  {f.message}
                </p>
              ))}
            </div>
          )}
        </section>

        {/* Survey list */}
        {surveysQuery.isLoading && (
          <div className="flex items-center gap-2 text-content-tertiary">
            <Loader2 size={13} className="animate-spin" />
            {t('geo_hub.surveys.loading', { defaultValue: 'Loading surveys...' })}
          </div>
        )}
        {surveysQuery.isError && (
          <p role="alert" className="text-red-600 dark:text-red-400">
            {t('geo_hub.surveys.load_failed', { defaultValue: 'Could not load surveys.' })}
          </p>
        )}
        {!surveysQuery.isLoading && !surveysQuery.isError && surveys.length === 0 && (
          <p data-testid="geo-surveys-empty" className="rounded-md bg-black/5 px-3 py-3 text-content-secondary dark:bg-white/5">
            {t('geo_hub.surveys.empty', { defaultValue: 'Upload a drone orthophoto, then record real progress per activity.' })}
          </p>
        )}
        {surveys.length > 0 && (
          <section className="space-y-1">
            <h3 className="font-semibold text-content-primary">
              {t('geo_hub.surveys.list.title', { defaultValue: 'Surveys by date' })}
            </h3>
            <ul className="space-y-1">
              {surveys.map((s) => {
                const visible = s.overlay_id ? (overlayById.get(s.overlay_id)?.visible ?? false) : false;
                return (
                  <li
                    key={s.id}
                    data-testid="geo-survey-row"
                    className={[
                      'flex items-center gap-1.5 rounded-md border px-2 py-1.5',
                      s.id === selectedId ? 'border-oe-blue bg-oe-blue/5' : 'border-black/10 dark:border-white/10',
                    ].join(' ')}
                  >
                    <button type="button" onClick={() => select(s)} className="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40">
                      <span className="block truncate font-medium text-content-primary">{s.captured_on} · {s.name || s.kind}</span>
                      <span className="block truncate text-2xs text-content-tertiary">
                        {t(`geo_hub.surveys.kind.${s.kind}`, { defaultValue: KIND_DEFAULT[s.kind] ?? s.kind })} ·{' '}
                        {t(`geo_hub.surveys.platform.${s.platform}`, { defaultValue: PLATFORM_DEFAULT[s.platform] ?? s.platform })}
                        {formatGsd(s.gsd_cm) ? ` · ${formatGsd(s.gsd_cm)}` : ''}
                      </span>
                    </button>
                    {s.overlay_id ? (
                      <button
                        type="button"
                        onClick={() => toggleOverlay(s)}
                        aria-pressed={visible}
                        aria-label={visible ? t('geo_hub.surveys.list.hide', { defaultValue: 'Hide from globe' }) : t('geo_hub.surveys.list.show', { defaultValue: 'Show on globe' })}
                        className="rounded-md p-1 text-content-secondary hover:bg-black/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 dark:hover:bg-white/10"
                      >
                        {visible ? <Eye size={14} /> : <EyeOff size={14} />}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      aria-label={t('geo_hub.surveys.list.delete', { defaultValue: 'Delete survey' })}
                      onClick={async () => {
                        const ok = await confirm({
                          title: t('geo_hub.surveys.list.delete', { defaultValue: 'Delete survey' }),
                          message: t('geo_hub.surveys.list.delete_confirm', {
                            defaultValue: 'Delete this survey and its recorded progress? A linked scan is kept.',
                          }),
                          confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                          variant: 'danger',
                        });
                        if (ok) deleteMutation.mutate(s.id);
                      }}
                      className="rounded-md p-1 text-red-600 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:text-red-300 dark:hover:bg-red-950/30"
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* Compare two dates */}
        {withImage.length >= 2 && (
          <section data-testid="geo-surveys-compare" className="space-y-1.5">
            <h3 className="font-semibold text-content-primary">
              {t('geo_hub.surveys.compare.title', { defaultValue: 'Compare two dates' })}
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {([['earlier', earlierId, setEarlierId], ['later', laterId, setLaterId]] as const).map(([which, value, set]) => (
                <label key={which} className="block">
                  <span className="mb-0.5 block text-content-secondary">
                    {t(`geo_hub.surveys.compare.${which}`, { defaultValue: which === 'earlier' ? 'Earlier survey' : 'Later survey' })}
                  </span>
                  <select
                    value={value}
                    onChange={(e) => set(e.target.value)}
                    className="w-full rounded-md border border-black/15 bg-transparent px-2 py-1 dark:border-white/20"
                  >
                    <option value="" />
                    {withImage.map((s) => (
                      <option key={s.id} value={s.id}>{s.captured_on}</option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={blend}
              onChange={(e) => setBlend(Number(e.target.value))}
              aria-label={t('geo_hub.surveys.compare.slider', { defaultValue: 'Blend between the two surveys' })}
              className="w-full"
            />
          </section>
        )}
        {withImage.length === 1 && (
          <p className="text-2xs text-content-tertiary">
            {t('geo_hub.surveys.compare.need_two', { defaultValue: 'Add a second survey with an image to compare dates.' })}
          </p>
        )}

        {/* Progress table */}
        {selected && (
          <ProgressTable
            title={t('geo_hub.surveys.progress.title', { date: selected.captured_on, defaultValue: 'Progress on {{date}}' })}
            rows={progressQuery.data}
            loading={progressQuery.isLoading}
            failed={progressQuery.isError}
            onSave={(activityId, value) => observeMutation.mutate({ activityId, value })}
          />
        )}
      </div>
      <ConfirmDialog {...confirmProps} />
    </aside>
  );
}

interface ProgressTableProps {
  title: string;
  rows: SurveyProgressRow[] | undefined;
  loading: boolean;
  failed: boolean;
  onSave: (activityId: string, value: number) => void;
}

function ProgressTable({ title, rows, loading, failed, onSave }: ProgressTableProps) {
  const { t } = useTranslation();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [invalid, setInvalid] = useState<Record<string, boolean>>({});

  const commit = (row: SurveyProgressRow) => {
    const raw = drafts[row.activity_id];
    if (raw === undefined) return;
    const parsed = parseObservedPct(raw);
    if (!parsed.ok) {
      setInvalid((s) => ({ ...s, [row.activity_id]: true }));
      return;
    }
    setInvalid((s) => ({ ...s, [row.activity_id]: false }));
    setDrafts((d) => {
      const { [row.activity_id]: _gone, ...rest } = d;
      return rest;
    });
    if (parsed.value !== row.observed_pct) onSave(row.activity_id, parsed.value);
  };

  return (
    <section data-testid="geo-surveys-progress" className="space-y-1.5">
      <h3 className="font-semibold text-content-primary">{title}</h3>
      <p className="text-2xs text-content-tertiary">
        {t('geo_hub.surveys.progress.hint', {
          defaultValue: 'Enter how far each activity really is on the survey date. The variance compares it with the schedule.',
        })}
      </p>
      {loading && <Loader2 size={14} className="animate-spin text-content-tertiary" />}
      {failed && (
        <p role="alert" className="text-red-600 dark:text-red-400">
          {t('geo_hub.surveys.progress.load_failed', { defaultValue: 'Could not load the progress table.' })}
        </p>
      )}
      {rows && rows.length === 0 && (
        <p className="text-content-secondary">
          {t('geo_hub.surveys.progress.none', {
            defaultValue: 'There are no schedule activities yet. Create a schedule to compare it with the site.',
          })}
        </p>
      )}
      {rows && rows.length > 0 && (
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="py-1 pr-1 font-medium">{t('geo_hub.surveys.progress.col_name', { defaultValue: 'Activity' })}</th>
              <th className="px-1 text-right font-medium">{t('geo_hub.surveys.progress.col_planned', { defaultValue: 'Planned %' })}</th>
              <th className="px-1 text-right font-medium">{t('geo_hub.surveys.progress.col_observed', { defaultValue: 'Observed %' })}</th>
              <th className="pl-1 font-medium">{t('geo_hub.surveys.progress.col_variance', { defaultValue: 'Variance' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const badge = varianceBadge(row.status);
              return (
                <tr key={row.activity_id} data-testid="geo-survey-progress-row" className="border-t border-black/5 dark:border-white/10">
                  <td className="max-w-[9rem] truncate py-1 pr-1" title={`${row.code} ${row.name}`}>
                    <span className="text-content-tertiary">{row.code}</span> {row.name}
                  </td>
                  <td className="px-1 text-right tabular-nums">{fmtFixed(row.planned_pct_on_date, 0)}</td>
                  <td className="px-1 text-right">
                    <input
                      type="text"
                      inputMode="decimal"
                      value={drafts[row.activity_id] ?? (row.observed_pct === null ? '' : String(row.observed_pct))}
                      onChange={(e) => setDrafts((d) => ({ ...d, [row.activity_id]: e.target.value }))}
                      onBlur={() => commit(row)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                      }}
                      aria-invalid={invalid[row.activity_id] || undefined}
                      title={invalid[row.activity_id] ? t('geo_hub.surveys.progress.invalid', { defaultValue: 'Enter a number from 0 to 100.' }) : undefined}
                      className={[
                        'w-14 rounded border bg-transparent px-1 py-0.5 text-right tabular-nums',
                        invalid[row.activity_id] ? 'border-red-500' : 'border-black/15 dark:border-white/20',
                      ].join(' ')}
                    />
                  </td>
                  <td className="pl-1">
                    <Badge variant={badge.variant} size="sm">
                      {formatVariance(row.variance_pct)} · {t(badge.labelKey, { defaultValue: badge.labelDefault })}
                    </Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default SurveysPanel;
