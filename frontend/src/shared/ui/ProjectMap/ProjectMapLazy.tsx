// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Lazy wrapper for ``ProjectMap``.
 *
 * The real implementation imports ``react-map-gl/maplibre`` and the
 * ``maplibre-gl/dist/maplibre-gl.css`` side-effect — together ~1 MB of JS
 * plus the CSS that the bundle bakes into the main chunk. Most pages never
 * render a map, so we lazy-load the implementation here and let the route
 * chunks (Projects, ProjectDetail, anything that uses <ProjectMap/>) pull
 * maplibre on demand.
 *
 * Suspense fallback is a tiny grey placeholder — the map area on the
 * project list / detail pages is fixed-height anyway, so layout doesn't
 * shift when the chunk arrives.
 */
import { Suspense, lazy } from 'react';
import type { LatLng } from './ProjectMap';

const ProjectMapImpl = lazy(() =>
  import('./ProjectMap').then((m) => ({ default: m.ProjectMap })),
);

interface ProjectMapProps {
  lat?: number | null;
  lng?: number | null;
  address?: string | null;
  city?: string | null;
  country?: string | null;
  variant?: 'card' | 'detail';
  className?: string;
  label?: string;
  onResolved?: (coords: LatLng) => void;
}

export function ProjectMap(props: ProjectMapProps) {
  return (
    <Suspense
      fallback={
        <div
          className={
            'w-full h-full bg-surface-2 dark:bg-surface-1 animate-pulse rounded ' +
            (props.className ?? '')
          }
        />
      }
    >
      <ProjectMapImpl {...props} />
    </Suspense>
  );
}

export type { LatLng };
