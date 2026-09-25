// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// VideosPage - tutorial and training videos, grouped by topic.
//
// The list is data (`videoCatalog.ts`); this file only lays it out. Each video
// renders as a local poster, and the player iframe is created only when the
// reader presses play, from the privacy-enhanced host. One player at a time:
// starting a second video unmounts the first, so two soundtracks never overlap.
//
// Topics without a video yet are gathered into one "on the way" strip at the
// foot of the page rather than drawn as empty sections, so the page reads as a
// library and not as a list of gaps.

import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  MonitorPlay,
  Play,
  ExternalLink,
  ShieldCheck,
  Clock,
  Route,
  ArrowRight,
  Hourglass,
} from 'lucide-react';
import {
  TUTORIAL_VIDEOS,
  VIDEO_CATEGORIES,
  VIDEO_CHANNEL_URL,
  embedUrl,
  videosInCategory,
  watchUrl,
  type TutorialVideo,
  type VideoCategoryId,
} from './videoCatalog';

type Filter = 'all' | VideoCategoryId;

function isCategoryId(value: string | null): value is VideoCategoryId {
  return VIDEO_CATEGORIES.some((c) => c.id === value);
}

export function VideosPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const topicParam = params.get('topic');
  const filter: Filter = isCategoryId(topicParam) ? topicParam : 'all';
  const [playingId, setPlayingId] = useState<string | null>(null);

  const filled = useMemo(
    () => VIDEO_CATEGORIES.filter((c) => videosInCategory(c.id).length > 0),
    [],
  );
  const upcoming = useMemo(
    () => VIDEO_CATEGORIES.filter((c) => videosInCategory(c.id).length === 0),
    [],
  );
  const shown = filter === 'all' ? filled : filled.filter((c) => c.id === filter);

  // A deep link to one video (`/videos?v=<id>`) scrolls it into view. It does
  // not start playback: autoplay without a gesture is blocked anyway, and a
  // page that makes noise on arrival is worse than one more click.
  const deepLinked = params.get('v');
  useEffect(() => {
    if (!deepLinked) return;
    const el = document.getElementById(`video-${deepLinked}`);
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  }, [deepLinked]);

  const pickFilter = (next: Filter) => {
    const nextParams = new URLSearchParams(params);
    if (next === 'all') nextParams.delete('topic');
    else nextParams.set('topic', next);
    setParams(nextParams, { replace: true });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden rounded-2xl border border-border-light bg-gradient-to-br from-oe-blue/[0.08] via-oe-blue/[0.03] to-transparent p-5">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-8 -top-10 h-40 w-40 rounded-full bg-oe-blue/10 blur-3xl"
        />
        <div className="relative flex flex-wrap items-start gap-3 sm:flex-nowrap">
          <span className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue/15 text-oe-blue ring-1 ring-inset ring-oe-blue/25">
            <MonitorPlay size={22} strokeWidth={1.9} />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold tracking-tight text-content-primary">
              {t('videos.page_title', { defaultValue: 'Videos' })}
            </h1>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-content-secondary">
              {t('videos.page_subtitle', {
                defaultValue:
                  'Short walkthroughs and talks from the team that builds the platform. Watch one before you start, or come back when you reach a new part of the work.',
              })}
            </p>
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-content-tertiary">
              <ShieldCheck size={13} strokeWidth={2} className="shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
              {t('videos.privacy_note', {
                defaultValue: 'Nothing loads from the video host until you press play.',
              })}
            </p>
          </div>
          <a
            href={VIDEO_CHANNEL_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-full shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm font-medium text-content-primary shadow-sm transition-colors hover:border-oe-blue/40 hover:text-oe-blue sm:w-auto"
          >
            {t('videos.subscribe', { defaultValue: 'All videos on the channel' })}
            <ExternalLink size={14} strokeWidth={2} aria-hidden />
          </a>
        </div>
      </div>

      {/* ── Topic filter ────────────────────────────────────────────────── */}
      <div
        role="tablist"
        aria-label={t('videos.topics', { defaultValue: 'Topics' })}
        className="flex flex-wrap gap-2"
      >
        <FilterChip active={filter === 'all'} onClick={() => pickFilter('all')}>
          {t('videos.filter_all', { defaultValue: 'All' })}
          <span className="tabular-nums opacity-70">{TUTORIAL_VIDEOS.length}</span>
        </FilterChip>
        {filled.map((category) => {
          const Icon = category.icon;
          return (
            <FilterChip
              key={category.id}
              active={filter === category.id}
              onClick={() => pickFilter(category.id)}
            >
              <Icon size={13} strokeWidth={2} aria-hidden />
              {t(category.labelKey, { defaultValue: category.defaultLabel })}
              <span className="tabular-nums opacity-70">{videosInCategory(category.id).length}</span>
            </FilterChip>
          );
        })}
      </div>

      {/* ── Topics with videos ──────────────────────────────────────────── */}
      {shown.map((category) => {
        const Icon = category.icon;
        return (
          <section key={category.id} aria-labelledby={`videos-topic-${category.id}`} className="space-y-3">
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-content-secondary ring-1 ring-inset ring-border-light">
                <Icon size={16} strokeWidth={2} aria-hidden />
              </span>
              <div className="min-w-0">
                <h2 id={`videos-topic-${category.id}`} className="text-base font-semibold text-content-primary">
                  {t(category.labelKey, { defaultValue: category.defaultLabel })}
                </h2>
                <p className="text-sm text-content-secondary">
                  {t(category.descriptionKey, { defaultValue: category.defaultDescription })}
                </p>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
              {videosInCategory(category.id).map((video) => (
                <VideoCard
                  key={video.id}
                  video={video}
                  playing={playingId === video.id}
                  highlighted={deepLinked === video.id}
                  onPlay={() => setPlayingId(video.id)}
                />
              ))}
            </div>
          </section>
        );
      })}

      {/* ── Topics still to come ────────────────────────────────────────── */}
      {filter === 'all' && upcoming.length > 0 && (
        <section aria-labelledby="videos-upcoming" className="space-y-3">
          <div>
            <h2 id="videos-upcoming" className="text-base font-semibold text-content-primary">
              {t('videos.more_topics', { defaultValue: 'More topics on the way' })}
            </h2>
            <p className="text-sm text-content-secondary">
              {t('videos.more_topics_body', {
                defaultValue: 'Tutorials for these topics are in production. New videos appear on the channel first.',
              })}
            </p>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {upcoming.map((category) => {
              const Icon = category.icon;
              return (
                <li
                  key={category.id}
                  data-testid={`videos-upcoming-${category.id}`}
                  className="flex flex-col gap-2 rounded-xl border border-dashed border-border-light bg-surface-secondary/30 p-4"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-primary text-content-tertiary ring-1 ring-inset ring-border-light">
                      <Icon size={16} strokeWidth={2} aria-hidden />
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-2xs font-semibold text-amber-700 ring-1 ring-inset ring-amber-500/20 dark:text-amber-300">
                      <Hourglass size={10} strokeWidth={2.25} aria-hidden />
                      {t('videos.coming_soon', { defaultValue: 'Coming soon' })}
                    </span>
                  </div>
                  <p className="text-sm font-semibold text-content-primary">
                    {t(category.labelKey, { defaultValue: category.defaultLabel })}
                  </p>
                  <p className="text-xs leading-relaxed text-content-tertiary">
                    {t(category.descriptionKey, { defaultValue: category.defaultDescription })}
                  </p>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {/* ── Learn by doing ──────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-border-light bg-surface-primary p-5 sm:flex-nowrap">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
          <Route size={20} strokeWidth={1.9} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary">
            {t('videos.cases_cta_title', { defaultValue: 'Rather learn by doing?' })}
          </p>
          <p className="text-sm text-content-secondary">
            {t('videos.cases_cta_body', {
              defaultValue: 'Cases walk you through real workflows step by step, inside the app, on a sample project.',
            })}
          </p>
        </div>
        <Link
          to="/cases"
          className="inline-flex w-full shrink-0 items-center justify-center gap-1.5 rounded-lg bg-oe-blue px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-oe-blue/90 sm:w-auto"
        >
          {t('videos.cases_cta_button', { defaultValue: 'Open Cases' })}
          <ArrowRight size={14} strokeWidth={2} className="rtl:rotate-180" aria-hidden />
        </Link>
      </div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        active
          ? 'border-oe-blue bg-oe-blue text-white shadow-sm'
          : 'border-border-light bg-surface-primary text-content-secondary hover:border-content-tertiary hover:text-content-primary',
      )}
    >
      {children}
    </button>
  );
}

function VideoCard({
  video,
  playing,
  highlighted,
  onPlay,
}: {
  video: TutorialVideo;
  playing: boolean;
  highlighted: boolean;
  onPlay: () => void;
}) {
  const { t } = useTranslation();
  const title = t(video.titleKey, { defaultValue: video.defaultTitle });

  return (
    <article
      id={`video-${video.id}`}
      data-testid={`video-card-${video.id}`}
      className={clsx(
        'group/card flex flex-col overflow-hidden rounded-xl border bg-surface-primary shadow-sm transition-shadow hover:shadow-md',
        highlighted ? 'border-oe-blue ring-2 ring-oe-blue/30' : 'border-border-light',
      )}
    >
      <div className="relative aspect-video w-full overflow-hidden bg-slate-900">
        {playing ? (
          <iframe
            src={embedUrl(video.youtubeId)}
            title={title}
            className="absolute inset-0 h-full w-full border-0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            // The app sends `Referrer-Policy: same-origin`, which would strip
            // the referrer from this cross-origin request, and the player
            // refuses to start without one.
            referrerPolicy="strict-origin-when-cross-origin"
            allowFullScreen
          />
        ) : (
          <button
            type="button"
            onClick={onPlay}
            aria-label={t('videos.play', { defaultValue: 'Play: {{title}}', title })}
            className="absolute inset-0 h-full w-full focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-oe-blue/60"
          >
            <img
              src={video.thumbnail}
              alt=""
              loading="lazy"
              decoding="async"
              width={960}
              height={540}
              className="h-full w-full object-cover transition-transform duration-300 ease-oe group-hover/card:scale-[1.03]"
            />
            <span
              aria-hidden
              className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/10 to-transparent transition-opacity group-hover/card:from-black/65"
            />
            <span
              aria-hidden
              className="absolute left-1/2 top-1/2 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white/95 text-oe-blue shadow-lg ring-4 ring-white/25 transition-transform duration-200 group-hover/card:scale-110"
            >
              <Play size={24} strokeWidth={2} className="translate-x-0.5 fill-current" />
            </span>
            {video.recordedOn && (
              <span
                className="absolute start-2.5 top-2.5 rounded-md bg-black/60 px-1.5 py-0.5 text-2xs font-semibold text-white backdrop-blur-sm"
                title={t('videos.recorded_on', {
                  defaultValue: 'Recorded on version {{version}}',
                  version: video.recordedOn,
                })}
              >
                v{video.recordedOn}
              </span>
            )}
            {video.minutes !== undefined && (
              <span className="absolute bottom-2.5 end-2.5 inline-flex items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 text-2xs font-semibold tabular-nums text-white backdrop-blur-sm">
                <Clock size={10} strokeWidth={2.5} aria-hidden />
                {t('videos.minutes', { defaultValue: '{{minutes}} min', minutes: video.minutes })}
              </span>
            )}
          </button>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-4">
        <h3 className="text-sm font-semibold leading-snug text-content-primary">{title}</h3>
        <p className="text-sm leading-relaxed text-content-secondary">
          {t(video.descriptionKey, { defaultValue: video.defaultDescription })}
        </p>
        <div className="mt-auto flex items-center gap-3 pt-2">
          {!playing && (
            <button
              type="button"
              onClick={onPlay}
              className="inline-flex items-center gap-1 text-xs font-semibold text-oe-blue hover:underline"
            >
              <Play size={12} strokeWidth={2.25} className="fill-current" aria-hidden />
              {t('videos.watch', { defaultValue: 'Watch' })}
            </button>
          )}
          <a
            href={watchUrl(video.youtubeId)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-content-tertiary hover:text-content-primary"
          >
            {t('videos.open_external', { defaultValue: 'Open on YouTube' })}
            <ExternalLink size={11} strokeWidth={2} aria-hidden />
          </a>
        </div>
      </div>
    </article>
  );
}
