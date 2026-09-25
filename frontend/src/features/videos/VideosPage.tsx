// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// VideosPage - the OpenConstruction Academy on one page.
//
// Four parts, top to bottom: a hero that starts somebody new at the setup
// lesson; "Recommended for you", ranked by role and market; the series as
// ordered playlists with this browser's progress; and the whole library with
// filters and a search that reaches into chapter titles, so a hit can open the
// player at that second.
//
// All of it reads the generated catalogue through `academy.ts`. Titles,
// descriptions and chapters are data in the video's own language and are
// marked with `lang`; every label around them goes through i18n. Covers of
// published videos come from the YouTube image host; the player itself is
// created only when the reader presses play.
//
// State that is worth a link lives in the URL: the open video and second
// (`?v=&t=`) and the library filters, so `/videos?role=estimator&q=gaeb` is a
// shareable view and other screens can point into it.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  EyeOff,
  GraduationCap,
  ListVideo,
  MonitorPlay,
  Play,
  Route,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  X,
} from 'lucide-react';
import { navGroups } from '@/app/layout/navCatalog';
import { STAGE_META } from '@/features/cases/stages';
import { ROLE_META } from '@/features/cases/roles';
import { RoleAvatar } from '@/features/cases/RoleAvatar';
import type { LifecycleStage, ProfessionalRole } from '@/features/cases/types';
import type { AcademyVideo, ResultFamily } from './academyTypes';
import {
  CATALOG,
  RESULT_FAMILIES,
  SERIES,
  VIDEOS,
  activeFilterCount,
  catalogLanguages,
  catalogMarkets,
  channelUrl,
  formatClock,
  pathForRole,
  playlist,
  recommend,
  searchVideos,
  startHereVideo,
  videoById,
  type VideoFilters,
} from './academy';
import { VideoCard } from './VideoCard';
import { VideoCover } from './VideoCover';
import { VideoPlayerDialog } from './VideoPlayerDialog';
import { RolePicker } from './RolePicker';
import { useVideoContext } from './useVideoContext';
import { useVideosStore } from './useVideosStore';
import { useVideoLabels, type VideoLabels } from './videoLabels';
import { useVideoHintsStore } from './videoRoutes';

const ROLE_IDS = new Set<string>(ROLE_META.map((r) => r.id));
const STAGE_IDS = new Set<string>(STAGE_META.map((s) => s.id));

function filtersFromParams(params: URLSearchParams): VideoFilters {
  const role = params.get('role');
  const stage = params.get('stage');
  const market = params.get('market');
  const language = params.get('lang');
  const series = params.get('series');
  const result = params.get('result');
  const route = params.get('route');
  return {
    role: role && ROLE_IDS.has(role) ? (role as ProfessionalRole) : null,
    stage: stage && STAGE_IDS.has(stage) ? (stage as LifecycleStage) : null,
    market: market && (market === 'universal' || catalogMarkets().includes(market)) ? market : null,
    language: language && catalogLanguages().includes(language) ? language : null,
    series: series && SERIES.some((s) => s.id === series) ? series : null,
    result: result && (RESULT_FAMILIES as string[]).includes(result) ? (result as ResultFamily) : null,
    route: route && VIDEOS.some((v) => v.routes.includes(route)) ? route : null,
    query: params.get('q') ?? '',
  };
}

const PARAM_OF: Record<keyof VideoFilters, string> = {
  role: 'role',
  stage: 'stage',
  market: 'market',
  language: 'lang',
  series: 'series',
  result: 'result',
  route: 'route',
  query: 'q',
};

export function VideosPage() {
  const { t } = useTranslation();
  const labels = useVideoLabels();
  const [params, setParams] = useSearchParams();

  // ── Player state, mirrored in the URL ──────────────────────────────────
  const openId = params.get('v');
  const openVideo = videoById(openId);
  const openAt = Math.max(0, Number.parseInt(params.get('t') ?? '0', 10) || 0);
  // A click is a gesture and plays at once; a pasted link waits for play.
  const [autoplayId, setAutoplayId] = useState<string | null>(null);

  const patchParams = useCallback(
    (patch: Record<string, string | null>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === '') next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const openPlayer = useCallback(
    (video: AcademyVideo, start = 0) => {
      setAutoplayId(video.id);
      patchParams({ v: video.id, t: start > 0 ? String(Math.floor(start)) : null });
    },
    [patchParams],
  );
  const closePlayer = useCallback(() => patchParams({ v: null, t: null }), [patchParams]);
  const onSeek = useCallback((s: number) => patchParams({ t: s > 0 ? String(s) : null }), [patchParams]);

  // ── Library filters, in the URL ─────────────────────────────────────────
  const filters = useMemo(() => filtersFromParams(params), [params]);
  const setFilter = useCallback(
    <K extends keyof VideoFilters>(key: K, value: VideoFilters[K]) => {
      patchParams({ [PARAM_OF[key]]: value === null ? null : String(value) });
    },
    [patchParams],
  );
  const clearFilters = useCallback(() => {
    patchParams(Object.fromEntries(Object.values(PARAM_OF).map((p) => [p, null])));
  }, [patchParams]);

  return (
    <div className="space-y-8 animate-fade-in">
      <Hero labels={labels} onPlay={openPlayer} />
      <Recommended labels={labels} onOpen={openPlayer} />
      <LearningPath labels={labels} onOpen={openPlayer} />
      <SeriesShelves labels={labels} onOpen={openPlayer} />
      <Library
        labels={labels}
        filters={filters}
        setFilter={setFilter}
        clearFilters={clearFilters}
        onOpen={openPlayer}
      />
      <HintsRestore />
      <CasesCta />

      {openVideo && (
        <VideoPlayerDialog
          key={openVideo.id}
          video={openVideo}
          start={openAt}
          autoplay={autoplayId === openVideo.id}
          labels={labels}
          onClose={closePlayer}
          onOpenVideo={openPlayer}
          onSeek={onSeek}
        />
      )}
      <span className="sr-only" aria-live="polite">
        {openVideo ? t('videos.now_open', { defaultValue: 'Opened: {{title}}', title: openVideo.title }) : ''}
      </span>
    </div>
  );
}

// ── Hero ─────────────────────────────────────────────────────────────────────

function Hero({ labels, onPlay }: { labels: VideoLabels; onPlay: (v: AcademyVideo, s?: number) => void }) {
  const { t } = useTranslation();
  const start = startHereVideo();
  const published = VIDEOS.filter((v) => v.status === 'published').length;
  const chapters = VIDEOS.reduce((n, v) => n + v.chapters.length, 0);
  const stats: { value: number; label: string }[] = [
    { value: VIDEOS.length, label: t('videos.stat_videos', { defaultValue: 'Videos' }) },
    { value: published, label: t('videos.stat_published', { defaultValue: 'Out now' }) },
    { value: SERIES.length, label: t('videos.stat_series', { defaultValue: 'Series' }) },
    { value: chapters, label: t('videos.stat_chapters', { defaultValue: 'Chapters to jump to' }) },
  ];

  return (
    <section
      data-testid="videos-hero"
      className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-slate-900 via-[#0b2447] to-[#0a3d62] text-white shadow-lg ring-1 ring-white/10"
    >
      <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-sky-400/20 blur-3xl" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-32 left-10 h-72 w-72 rounded-full bg-indigo-500/20 blur-3xl" />
      <div className="relative grid gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-center">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-2xs font-semibold uppercase tracking-wider text-sky-200 ring-1 ring-inset ring-white/15">
            <GraduationCap size={13} aria-hidden />
            {CATALOG.channelName}
          </p>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">
            {t('videos.hero_title', { defaultValue: 'Learn the platform by watching real work' })}
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-white/75">
            {t('videos.hero_subtitle', {
              defaultValue:
                'Short lessons on real projects, by country and by role: set up, price, buy, build and get paid. Every chapter is a place you can jump straight to.',
            })}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            {start && (
              <button
                type="button"
                onClick={() => onPlay(start)}
                data-testid="videos-start-here"
                className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-slate-900 shadow-md transition-transform hover:-translate-y-px focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300/60"
              >
                <Play size={15} fill="currentColor" aria-hidden />
                {t('videos.start_here', { defaultValue: 'Start here' })}
                {start.duration ? (
                  <span className="font-mono text-xs tabular-nums text-slate-500">{formatClock(start.duration)}</span>
                ) : null}
              </button>
            )}
            <a
              href={channelUrl()}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="videos-channel"
              className="inline-flex items-center gap-2 rounded-xl border border-white/25 bg-white/5 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-white/15 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300/60"
            >
              <MonitorPlay size={15} aria-hidden />
              {t('videos.channel_button', { defaultValue: 'Open the channel' })}
              <ExternalLink size={13} className="opacity-70" aria-hidden />
            </a>
          </div>
          <dl className="mt-6 grid max-w-lg grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
            {stats.map((s) => (
              <div key={s.label} className="flex min-w-0 flex-col-reverse">
                <dt className="text-2xs leading-tight text-white/60">{s.label}</dt>
                <dd className="text-xl font-semibold tabular-nums">{s.value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 inline-flex items-center gap-1.5 text-2xs text-white/55">
            <ShieldCheck size={12} className="shrink-0 text-emerald-300" aria-hidden />
            {t('videos.player_note', { defaultValue: 'The player loads only when you press play, from the privacy-enhanced YouTube host.' })}
          </p>
        </div>

        {start && (
          <button
            type="button"
            onClick={() => onPlay(start)}
            aria-label={t('videos.play', { defaultValue: 'Play: {{title}}', title: start.title })}
            className="group relative block overflow-hidden rounded-xl shadow-2xl ring-1 ring-white/15 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300/60"
          >
            <VideoCover src={start.cover} eager className="aspect-video w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]" />
            <span aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
            <span aria-hidden="true" className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white/95 text-slate-900 shadow-xl transition-transform group-hover:scale-105">
              <Play size={26} className="translate-x-0.5" fill="currentColor" />
            </span>
            <span className="absolute inset-x-0 bottom-0 p-3 text-left">
              <span className="block text-2xs font-semibold uppercase tracking-wider text-sky-200">
                {t('videos.start_here', { defaultValue: 'Start here' })}
              </span>
              <span lang={start.language} className="line-clamp-2 block text-sm font-semibold">
                {start.title}
              </span>
              <span className="mt-0.5 block text-2xs text-white/70">
                {labels.series(start.series)}
              </span>
            </span>
          </button>
        )}
      </div>
    </section>
  );
}

// ── Recommended for you ─────────────────────────────────────────────────────

function Recommended({ labels, onOpen }: { labels: VideoLabels; onOpen: (v: AcademyVideo, s?: number) => void }) {
  const { t } = useTranslation();
  const ctx = useVideoContext();
  const setRole = useVideosStore((s) => s.setRole);
  const marketChoice = useVideosStore((s) => s.market);
  const setMarket = useVideosStore((s) => s.setMarket);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const showPicker = pickerOpen || (!ctx.role && !skipped);

  const list = useMemo(
    () => recommend({ role: ctx.role, market: ctx.market, language: ctx.language }),
    [ctx.role, ctx.market, ctx.language],
  );

  const marketNote: Record<string, string> = {
    project: t('videos.market_from_project', { defaultValue: 'from your active project' }),
    cases: t('videos.market_from_cases', { defaultValue: 'from your Cases filter' }),
    language: t('videos.market_from_language', { defaultValue: 'from the interface language' }),
  };

  return (
    <section aria-labelledby="videos-rec-title" data-testid="videos-recommended" className="space-y-3">
      <SectionHeader
        id="videos-rec-title"
        icon={<Sparkles size={16} aria-hidden />}
        title={t('videos.recommended_title', { defaultValue: 'Recommended for you' })}
        subtitle={t('videos.recommended_note', {
          defaultValue: 'Picked by role, country and language. The pairing is our editors’ suggestion, so browse the library too.',
        })}
      />

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button
          type="button"
          onClick={() => setPickerOpen((o) => !o)}
          aria-expanded={showPicker}
          data-testid="videos-role-button"
          className="inline-flex items-center gap-2 rounded-full border border-border-light bg-surface-primary py-1 pl-1 pr-3 font-medium text-content-primary shadow-sm hover:border-oe-blue/40"
        >
          {ctx.role ? (
            <RoleAvatar role={ctx.role} className="h-6 w-6" />
          ) : (
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-secondary text-content-tertiary">
              <UserRound size={13} aria-hidden />
            </span>
          )}
          {ctx.role ? labels.role(ctx.role) : t('videos.any_role', { defaultValue: 'Any role' })}
          <span className="text-content-tertiary">{t('videos.change', { defaultValue: 'Change' })}</span>
        </button>

        <label className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-primary px-3 py-1 font-medium text-content-primary shadow-sm focus-within:border-oe-blue/50">
          <span className="text-content-tertiary">{t('videos.country', { defaultValue: 'Country' })}</span>
          <select
            value={marketChoice}
            onChange={(e) => setMarket(e.target.value)}
            data-testid="videos-market-select"
            className="max-w-[12rem] cursor-pointer bg-transparent pr-1 font-medium focus:outline-none"
          >
            <option value="auto">
              {ctx.marketSource && ctx.marketSource !== 'chosen' && ctx.marketSource !== 'any' && ctx.market
                ? `${labels.country(ctx.market)} (${marketNote[ctx.marketSource]})`
                : t('videos.market_auto', { defaultValue: 'Automatic' })}
            </option>
            <option value="any">{t('videos.market_any', { defaultValue: 'Any country' })}</option>
            {catalogMarkets().map((m) => (
              <option key={m} value={m}>
                {labels.country(m)}
              </option>
            ))}
          </select>
        </label>
        {ctx.marketUncovered && ctx.market && (
          <p className="basis-full text-2xs text-content-tertiary sm:basis-auto">
            {t('videos.market_uncovered', {
              defaultValue: 'No video teaches the rules of {{country}} yet, so these apply in any country.',
              country: labels.country(ctx.market),
            })}
          </p>
        )}
      </div>

      {showPicker && (
        <div className="rounded-2xl border border-oe-blue/20 bg-gradient-to-br from-oe-blue/[0.06] to-transparent p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-content-primary">
                {t('videos.role_prompt', { defaultValue: 'What do you do on a project?' })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('videos.role_prompt_body', {
                  defaultValue: 'Pick a role and the videos for it come first. This browser remembers it, and you can change it here at any time.',
                })}
              </p>
            </div>
            <div className="flex gap-1.5">
              {ctx.roleSource === 'chosen' && (
                <button
                  type="button"
                  onClick={() => {
                    setRole(null);
                    setPickerOpen(false);
                    setSkipped(true);
                  }}
                  className="rounded-lg px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
                >
                  {t('videos.any_role', { defaultValue: 'Any role' })}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setPickerOpen(false);
                  setSkipped(true);
                }}
                className="rounded-lg px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
              >
                {ctx.role ? t('common.close', { defaultValue: 'Close' }) : t('videos.skip_role', { defaultValue: 'Show everything' })}
              </button>
            </div>
          </div>
          <RolePicker
            value={ctx.role}
            onPick={(role) => {
              setRole(role);
              setPickerOpen(false);
            }}
          />
        </div>
      )}

      {list.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border-light p-6 text-center text-sm text-content-secondary">
          {t('videos.recommended_empty', { defaultValue: 'Nothing matches this role and country yet. The library below has every video.' })}
        </p>
      ) : (
        <Rail>
          {list.map((video) => (
            <VideoCard key={video.id} video={video} labels={labels} onOpen={onOpen} compact className="w-64 shrink-0 snap-start sm:w-72" />
          ))}
        </Rail>
      )}
    </section>
  );
}

// ── Learning path ────────────────────────────────────────────────────────────

const PATH_SHOWN = 3;

function LearningPath({ labels, onOpen }: { labels: VideoLabels; onOpen: (v: AcademyVideo, s?: number) => void }) {
  const { t } = useTranslation();
  const ctx = useVideoContext();
  const watched = useVideosStore((s) => s.watched);
  const path = useMemo(() => (ctx.role ? pathForRole(ctx.role, ctx.market, STAGE_META.map((s) => s.id)) : null), [ctx.role, ctx.market]);
  if (!ctx.role || !path) return null;
  const role = ctx.role;

  return (
    <section aria-labelledby="videos-path-title" data-testid="videos-path" className="space-y-3">
      <SectionHeader
        id="videos-path-title"
        icon={<RoleAvatar role={role} className="h-6 w-6" />}
        title={t('videos.path_title', { defaultValue: 'Your path as {{role}}', role: labels.role(role) })}
        subtitle={t('videos.path_note', {
          defaultValue: 'Videos across the project stages, in the order the work happens.',
        })}
      />
      <Rail>
        {STAGE_META.map((stage) => {
          const list = path.get(stage.id) ?? [];
          const Icon = stage.icon;
          return (
            <div
              key={stage.id}
              data-testid="videos-path-stage"
              data-stage={stage.id}
              className={clsx(
                'flex w-56 shrink-0 snap-start flex-col rounded-xl border border-border-light border-l-[3px] bg-surface-primary p-2.5',
                stage.tint.accent,
                list.length === 0 && 'opacity-70',
              )}
            >
              <div className="mb-2 flex items-center gap-1.5">
                <span className={clsx('flex h-6 w-6 items-center justify-center rounded-md ring-1 ring-inset', stage.tint.tile)}>
                  <Icon size={13} aria-hidden />
                </span>
                <span className="min-w-0 flex-1 truncate text-xs font-semibold text-content-primary">
                  <span className="mr-1 tabular-nums text-content-tertiary">{stage.num}</span>
                  {labels.stageShort(stage.id)}
                </span>
                <span className="text-2xs tabular-nums text-content-tertiary">{list.length}</span>
              </div>
              {list.length === 0 ? (
                <p className="text-2xs text-content-tertiary">
                  {t('videos.path_empty', { defaultValue: 'No video for this stage yet.' })}
                </p>
              ) : (
                <ul className="space-y-1">
                  {list.slice(0, PATH_SHOWN).map((video) => (
                    <li key={video.id}>
                      <button
                        type="button"
                        onClick={() => onOpen(video)}
                        className="flex w-full items-start gap-2 rounded-lg p-1 text-left hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                      >
                        <span className="relative block h-9 w-16 shrink-0 overflow-hidden rounded bg-slate-900">
                          <VideoCover src={video.cover} width={64} height={36} className="h-full w-full object-cover" />
                          {watched[video.id] && (
                            <span className="absolute inset-0 flex items-center justify-center bg-emerald-600/60 text-white">
                              <CheckCircle2 size={14} aria-hidden />
                            </span>
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span lang={video.language} className="line-clamp-2 text-2xs font-medium leading-snug text-content-primary">
                            {video.title}
                          </span>
                          {video.status !== 'published' && (
                            <span className="text-[9px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
                              {t('videos.coming_soon', { defaultValue: 'Coming soon' })}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {list.length > PATH_SHOWN && (
                <Link
                  to={`/videos?role=${role}&stage=${stage.id}`}
                  className="mt-auto pt-1.5 text-2xs font-medium text-oe-blue hover:underline"
                >
                  {t('videos.path_more', { defaultValue: '{{more}} more in the library', more: list.length - PATH_SHOWN })}
                </Link>
              )}
            </div>
          );
        })}
      </Rail>
    </section>
  );
}

// ── Series ───────────────────────────────────────────────────────────────────

function SeriesShelves({ labels, onOpen }: { labels: VideoLabels; onOpen: (v: AcademyVideo, s?: number) => void }) {
  const { t } = useTranslation();
  const watched = useVideosStore((s) => s.watched);
  const shelves = SERIES.map((s) => ({ series: s, videos: playlist(s.id) })).filter((x) => x.videos.length > 1);

  return (
    <section aria-labelledby="videos-series-title" className="space-y-5">
      <SectionHeader
        id="videos-series-title"
        icon={<ListVideo size={16} aria-hidden />}
        title={t('videos.series_title', { defaultValue: 'Series' })}
        subtitle={t('videos.series_note', {
          defaultValue: 'Courses meant to be watched in order. Progress is kept in this browser, and "Watched" is your own mark.',
        })}
      />
      {shelves.map(({ series, videos }) => {
        const done = videos.filter((v) => watched[v.id]).length;
        const out = videos.filter((v) => v.status === 'published');
        const nextUp = out.find((v) => !watched[v.id]) ?? out[0];
        const pct = Math.round((done / videos.length) * 100);
        return (
          <div key={series.id} data-testid="videos-series" data-series-id={series.id} className="space-y-2">
            <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
              <div className="min-w-0 flex-1">
                <h3 lang={series.titleKey ? undefined : series.language} className="text-sm font-semibold text-content-primary">
                  {labels.series(series)}
                </h3>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-2xs text-content-tertiary">
                  <span>{labels.language(series.language)}</span>
                  {series.market && <span>· {labels.country(series.market)}</span>}
                  <span>
                    ·{' '}
                    {t('videos.series_out', {
                      defaultValue: '{{out}} of {{total}} out now',
                      out: out.length,
                      total: videos.length,
                    })}
                  </span>
                </p>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-32" title={t('videos.series_watched', { defaultValue: '{{done}} of {{total}} watched', done, total: videos.length })}>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-secondary">
                    <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
                  </div>
                  <p className="mt-0.5 text-2xs tabular-nums text-content-tertiary">
                    {t('videos.series_watched', { defaultValue: '{{done}} of {{total}} watched', done, total: videos.length })}
                  </p>
                </div>
                {nextUp && (
                  <button
                    type="button"
                    onClick={() => onOpen(nextUp)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-oe-blue-hover"
                  >
                    {done > 0 ? <ArrowRight size={13} aria-hidden /> : <Play size={12} fill="currentColor" aria-hidden />}
                    {done > 0
                      ? t('videos.continue', { defaultValue: 'Continue' })
                      : t('videos.start_series', { defaultValue: 'Start the series' })}
                  </button>
                )}
              </div>
            </div>
            <Rail>
              {videos.map((video) => (
                <div key={video.id} className="relative w-56 shrink-0 snap-start sm:w-60">
                  <span className="absolute -left-1 -top-1 z-10 flex h-6 min-w-6 items-center justify-center rounded-full bg-slate-900 px-1.5 text-2xs font-bold tabular-nums text-white ring-2 ring-surface-primary">
                    {video.seriesOrder}
                  </span>
                  <VideoCard video={video} labels={labels} onOpen={onOpen} compact />
                </div>
              ))}
            </Rail>
          </div>
        );
      })}
    </section>
  );
}

// ── Library ──────────────────────────────────────────────────────────────────

interface LibraryProps {
  labels: VideoLabels;
  filters: VideoFilters;
  setFilter: <K extends keyof VideoFilters>(key: K, value: VideoFilters[K]) => void;
  clearFilters: () => void;
  onOpen: (v: AcademyVideo, s?: number) => void;
}

function Library({ labels, filters, setFilter, clearFilters, onOpen }: LibraryProps) {
  const { t } = useTranslation();
  const hits = useMemo(() => searchVideos(filters), [filters]);
  const count = activeFilterCount(filters);
  const any = t('common.all', { defaultValue: 'All' });
  const moduleName = (route: string) => {
    for (const group of navGroups) {
      const item = group.items.find((i) => i.to === route);
      if (item) return t(item.labelKey, { defaultValue: item.defaultLabel ?? route });
    }
    return route;
  };
  // Arriving from a module screen's "All on the Videos page" lands on the list.
  const sectionRef = useRef<HTMLElement>(null);
  const arrivedWithRoute = useRef(Boolean(filters.route));
  useEffect(() => {
    if (arrivedWithRoute.current) sectionRef.current?.scrollIntoView?.({ block: 'start' });
  }, []);

  const selects: { key: Exclude<keyof VideoFilters, 'query'>; label: string; options: { value: string; label: string }[] }[] = [
    {
      key: 'role',
      label: t('videos.filter_role', { defaultValue: 'Role' }),
      options: ROLE_META.map((r) => ({ value: r.id, label: labels.role(r.id) })),
    },
    {
      key: 'stage',
      label: t('videos.filter_stage', { defaultValue: 'Stage' }),
      options: STAGE_META.map((s) => ({ value: s.id, label: labels.stage(s.id) })),
    },
    {
      key: 'market',
      label: t('videos.country', { defaultValue: 'Country' }),
      options: [
        { value: 'universal', label: t('videos.market_any', { defaultValue: 'Any country' }) },
        ...catalogMarkets().map((m) => ({ value: m, label: labels.country(m) })),
      ],
    },
    {
      key: 'language',
      label: t('videos.filter_language', { defaultValue: 'Language' }),
      options: catalogLanguages().map((l) => ({ value: l, label: labels.language(l) })),
    },
    {
      key: 'series',
      label: t('videos.filter_series', { defaultValue: 'Series' }),
      options: SERIES.map((s) => ({ value: s.id, label: labels.series(s) })),
    },
    {
      key: 'result',
      label: t('videos.filter_result', { defaultValue: 'Result' }),
      options: RESULT_FAMILIES.filter((r) => VIDEOS.some((v) => v.result === r)).map((r) => ({
        value: r,
        label: labels.result(r),
      })),
    },
  ];

  return (
    <section ref={sectionRef} aria-labelledby="videos-library-title" data-testid="videos-library" className="scroll-mt-4 space-y-3">
      <SectionHeader
        id="videos-library-title"
        icon={<SlidersHorizontal size={16} aria-hidden />}
        title={t('videos.library_title', { defaultValue: 'All videos' })}
        subtitle={t('videos.library_note', {
          defaultValue: 'Search finds titles and chapters. A chapter hit opens the video at that moment.',
        })}
      />

      <div className="space-y-2 rounded-2xl border border-border-light bg-surface-primary p-3 shadow-sm">
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" aria-hidden />
          <input
            type="search"
            value={filters.query}
            onChange={(e) => setFilter('query', e.target.value)}
            placeholder={t('videos.search_placeholder', { defaultValue: 'Search titles and chapters, for example "GAEB" or "invoice"' })}
            aria-label={t('common.search', { defaultValue: 'Search' })}
            data-testid="videos-search"
            className="w-full rounded-xl border border-border-light bg-surface-secondary/50 py-2 pl-9 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue/50 focus:bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
          />
        </div>
        {filters.route && (
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-content-secondary">
            {t('videos.for_screen', { defaultValue: 'For the screen' })}
            <span
              data-testid="videos-route-chip"
              className="inline-flex items-center gap-1 rounded-full border border-oe-blue/40 bg-oe-blue/[0.06] py-0.5 pl-2.5 pr-1 font-medium text-oe-blue"
            >
              {moduleName(filters.route)}
              <button
                type="button"
                onClick={() => setFilter('route', null)}
                aria-label={t('common.clear', { defaultValue: 'Clear' })}
                className="rounded-full p-0.5 hover:bg-oe-blue/15"
              >
                <X size={11} aria-hidden />
              </button>
            </span>
          </p>
        )}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {selects.map((s) => (
            <label key={s.key} className="min-w-0">
              <span className="mb-0.5 block text-2xs font-medium text-content-tertiary">{s.label}</span>
              <select
                value={(filters[s.key] as string | null) ?? ''}
                onChange={(e) => setFilter(s.key, (e.target.value || null) as never)}
                data-testid={`videos-filter-${s.key}`}
                className={clsx(
                  'w-full truncate rounded-lg border bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/20',
                  filters[s.key] ? 'border-oe-blue/50' : 'border-border-light',
                )}
              >
                <option value="">{any}</option>
                {s.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <div className="flex items-center justify-between gap-2 text-2xs text-content-tertiary">
          <span aria-live="polite" data-testid="videos-result-count">
            {t('videos.showing', { defaultValue: '{{shown}} of {{total}} videos', shown: hits.length, total: VIDEOS.length })}
          </span>
          {count > 0 && (
            <button type="button" onClick={clearFilters} className="inline-flex items-center gap-1 font-medium text-oe-blue hover:underline">
              <X size={12} aria-hidden />
              {t('common.clear_filters', { defaultValue: 'Clear filters' })}
            </button>
          )}
        </div>
      </div>

      {hits.length === 0 ? (
        <div data-testid="videos-empty" className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border-light px-4 py-10 text-center">
          <Search size={22} className="text-content-tertiary" aria-hidden />
          <p className="text-sm font-medium text-content-primary">
            {t('videos.empty_title', { defaultValue: 'No video matches' })}
          </p>
          <p className="max-w-sm text-xs text-content-secondary">
            {t('videos.empty_body', { defaultValue: 'Try fewer words or loosen a filter. The Cases hub may cover it step by step.' })}
          </p>
          <div className="mt-1 flex flex-wrap justify-center gap-2">
            <button type="button" onClick={clearFilters} className="rounded-lg border border-border-light px-3 py-1.5 text-xs font-medium hover:border-oe-blue/40">
              {t('common.clear_filters', { defaultValue: 'Clear filters' })}
            </button>
            <Link to="/cases" className="rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-semibold text-white hover:bg-oe-blue-hover">
              {t('videos.cases_cta_button', { defaultValue: 'Open Cases' })}
            </Link>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 min-[520px]:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {hits.map((hit) => (
            <VideoCard key={hit.video.id} video={hit.video} labels={labels} onOpen={onOpen} chapterHits={hit.chapters} />
          ))}
        </div>
      )}
    </section>
  );
}

// ── Pieces ───────────────────────────────────────────────────────────────────

function SectionHeader({ id, icon, title, subtitle }: { id: string; icon: ReactNode; title: string; subtitle?: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">{icon}</span>
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold tracking-tight text-content-primary">
          {title}
        </h2>
        {subtitle && <p className="text-xs text-content-secondary">{subtitle}</p>}
      </div>
    </div>
  );
}

/** A horizontal, snap-scrolling row that bleeds to the page edge on phones. */
function Rail({ children }: { children: ReactNode }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0">
      <div className="flex snap-x snap-mandatory gap-3 pt-1">{children}</div>
    </div>
  );
}

/** Brings back "Videos for this step" once it was hidden anywhere. */
function HintsRestore() {
  const { t } = useTranslation();
  const hidden = useVideoHintsStore((s) => s.off || s.hidden.length > 0);
  const showAgain = useVideoHintsStore((s) => s.showAgain);
  if (!hidden) return null;
  return (
    <div
      data-testid="videos-hints-restore"
      className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-border-light px-4 py-3 text-xs text-content-secondary"
    >
      <EyeOff size={14} className="shrink-0 text-content-tertiary" aria-hidden />
      <span className="min-w-0 flex-1">
        {t('videos.hints_hidden', { defaultValue: 'Video tips on module screens are hidden.' })}
      </span>
      <button type="button" onClick={showAgain} className="font-medium text-oe-blue hover:underline">
        {t('videos.hints_show', { defaultValue: 'Show them again' })}
      </button>
    </div>
  );
}

function CasesCta() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border-light bg-surface-secondary/40 p-5 sm:flex-row sm:items-center">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
        <Route size={20} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-content-primary">
          {t('videos.cases_cta_title', { defaultValue: 'Rather learn by doing?' })}
        </p>
        <p className="text-xs text-content-secondary">
          {t('videos.cases_cta_body', {
            defaultValue: 'Cases walk you through real workflows step by step, inside the app, on a sample project.',
          })}
        </p>
      </div>
      <Link
        to="/cases"
        className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-oe-blue px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-oe-blue-hover"
      >
        {t('videos.cases_cta_button', { defaultValue: 'Open Cases' })}
        <ArrowRight size={14} aria-hidden />
      </Link>
    </div>
  );
}
