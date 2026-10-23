// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The chip itself, loaded by VideoHint. It opens the player at the chapter
// that shows this section; the video plays in place.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { PlayCircle } from 'lucide-react';
import type { AcademyVideo } from './academyTypes';
import { VIDEOS, chapterStartingAt, formatClock } from './academy';
import { pickVideoHint, type VideoHintTopic } from './videoHints';
import { useVideoContext } from './useVideoContext';
import { useVideoLabels } from './videoLabels';
import { VideoPlayerDialog } from './VideoPlayerDialog';

export default function VideoHintButton({ topic, className }: { topic: VideoHintTopic; className?: string }) {
  const { t } = useTranslation();
  const labels = useVideoLabels();
  const ctx = useVideoContext();
  const [playing, setPlaying] = useState<{ video: AcademyVideo; start: number } | null>(null);
  const hint = pickVideoHint(topic, { market: ctx.market, language: ctx.language }, VIDEOS);
  if (!hint) return null;

  const chapter = chapterStartingAt(hint.video, hint.start);
  const tip = t('videos.hint.tooltip', {
    defaultValue: 'Video: {{title}}, from {{clock}} ({{chapter}})',
    title: hint.video.title,
    clock: formatClock(hint.start),
    chapter: chapter?.title ?? '',
  });

  return (
    <>
      <button
        type="button"
        onClick={() => setPlaying(hint)}
        title={tip}
        aria-label={tip}
        data-testid={`video-hint-${topic}`}
        className={clsx(
          'inline-flex h-6 shrink-0 items-center gap-1 rounded-full border border-oe-blue/30 bg-oe-blue/5 px-2 text-2xs font-medium text-oe-blue transition-colors',
          'hover:border-oe-blue/60 hover:bg-oe-blue/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
          className,
        )}
      >
        <PlayCircle size={12} aria-hidden />
        {t('videos.hint.watch', { defaultValue: 'Watch how' })}
      </button>
      {playing && (
        <VideoPlayerDialog
          key={playing.video.id}
          video={playing.video}
          start={playing.start}
          autoplay
          labels={labels}
          onClose={() => setPlaying(null)}
          onOpenVideo={(v, s = 0) => setPlaying({ video: v, start: s })}
        />
      )}
    </>
  );
}
