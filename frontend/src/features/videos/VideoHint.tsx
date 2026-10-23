// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A small "Watch how" chip beside one section of a screen. It loads the
// catalogue lazily and renders nothing until it has a video that fits the
// reader, or at all when video tips are turned off.

import { lazy, Suspense } from 'react';
import type { VideoHintTopic } from './videoHints';
import { useVideoHintsStore } from './videoRoutes';

const VideoHintButton = lazy(() => import('./VideoHintButton'));

export function VideoHint({ topic, className }: { topic: VideoHintTopic; className?: string }) {
  const off = useVideoHintsStore((s) => s.off);
  if (off) return null;
  return (
    <Suspense fallback={null}>
      <VideoHintButton topic={topic} className={className} />
    </Suspense>
  );
}
