// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Videos for this case", under the case header. The case runner checks the
// light count index first and loads this (and the catalogue) only for a case
// that has videos. The pairing is editorial and the strip says so.

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowRight, MonitorPlay } from 'lucide-react';
import type { AcademyVideo } from './academyTypes';
import { videosForCase } from './academy';
import { VideoCard } from './VideoCard';
import { VideoPlayerDialog } from './VideoPlayerDialog';
import { useVideoLabels } from './videoLabels';

export default function CaseVideos({ caseId }: { caseId: string }) {
  const { t } = useTranslation();
  const labels = useVideoLabels();
  const [playing, setPlaying] = useState<{ video: AcademyVideo; start: number } | null>(null);
  // Videos that play now first; the catalogue order otherwise.
  const videos = videosForCase(caseId)
    .map((v, i) => ({ v, i }))
    .sort((a, b) => Number(b.v.status === 'published') - Number(a.v.status === 'published') || a.i - b.i)
    .map((x) => x.v);
  if (videos.length === 0) return null;

  return (
    <section
      aria-labelledby={`case-videos-${caseId}`}
      data-testid="case-videos"
      className="rounded-2xl border border-border-light bg-surface-primary p-4"
    >
      <div className="mb-3 flex flex-wrap items-start gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <MonitorPlay size={16} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id={`case-videos-${caseId}`} className="text-sm font-semibold text-content-primary">
            {t('videos.for_case', { defaultValue: 'Videos for this case' })}
          </h2>
          <p className="text-2xs text-content-tertiary">
            {t('videos.for_case_note', {
              defaultValue: 'Suggested by our editors. A video may cover more or less than this case.',
            })}
          </p>
        </div>
        <Link to="/videos" className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline">
          {t('videos.library_title', { defaultValue: 'All videos' })}
          <ArrowRight size={12} aria-hidden />
        </Link>
      </div>
      <div className="-mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
        <div className="flex snap-x gap-3">
          {videos.map((video) => (
            <VideoCard
              key={video.id}
              video={video}
              labels={labels}
              compact
              onOpen={(v, start = 0) => setPlaying({ video: v, start })}
              className="w-60 shrink-0 snap-start"
            />
          ))}
        </div>
      </div>
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
    </section>
  );
}
