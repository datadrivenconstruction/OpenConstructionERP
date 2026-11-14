// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The player for one project-journey step, loaded lazily so the academy
// catalogue stays out of the app-shell chunk. It plays the best video for the
// step's module routes: a published one first, then catalogue order.

import { useEffect, useState } from 'react';
import type { AcademyVideo } from './academyTypes';
import { videosForRoute } from './academy';
import { useVideoLabels } from './videoLabels';
import { VideoPlayerDialog } from './VideoPlayerDialog';

/** The video a journey step opens on, or undefined when no catalogue video walks its routes. */
function videoForRoutes(routes: readonly string[]): AcademyVideo | undefined {
  const seen = new Set<string>();
  const list: AcademyVideo[] = [];
  routes.forEach((route) => {
    videosForRoute(route).forEach((v) => {
      if (!seen.has(v.id)) {
        seen.add(v.id);
        list.push(v);
      }
    });
  });
  return list.find((v) => v.status === 'published') ?? list[0];
}

export default function JourneyStepVideo({ routes, onClose }: { routes: readonly string[]; onClose: () => void }) {
  const labels = useVideoLabels();
  const [playing, setPlaying] = useState<{ video: AcademyVideo; start: number } | null>(() => {
    const first = videoForRoutes(routes);
    return first ? { video: first, start: 0 } : null;
  });
  useEffect(() => {
    if (!playing) onClose();
  }, [playing, onClose]);
  if (!playing) return null;
  return (
    <VideoPlayerDialog
      key={playing.video.id}
      video={playing.video}
      start={playing.start}
      autoplay
      labels={labels}
      onClose={() => setPlaying(null)}
      onOpenVideo={(v, st = 0) => setPlaying({ video: v, start: st })}
    />
  );
}
