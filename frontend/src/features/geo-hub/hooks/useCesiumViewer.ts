// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Cesium viewer lifecycle hook.
 *
 * Wraps Cesium's ``Viewer`` constructor + ``destroy()`` cleanup so the
 * component code stays focused on event wiring + UI. The hook is
 * intentionally framework-light: a single ``useEffect`` body, no
 * external deps beyond React.
 */

import { useEffect, useRef, useState } from 'react';

import { fetchGlobeImagery } from '@/shared/ui/ProjectMap/basemap';

import type { MapConfig } from '../types';

type ViewerHandle = {
  destroy: () => void;
};

type CesiumLike = {
  Viewer: new (
    container: HTMLElement,
    options?: Record<string, unknown>,
  ) => ViewerHandle;
  EllipsoidTerrainProvider: new () => unknown;
  UrlTemplateImageryProvider: new (options: Record<string, unknown>) => unknown;
  ImageryLayer: new (provider: unknown) => unknown;
};

/**
 * Hook return:
 *
 * * ``ref`` — pass to the container ``<div ref={ref} />``.
 * * ``status`` — `'pending'` while Cesium loads, `'loaded'` once the
 *   viewer is constructed, `'absent'` when CesiumJS is not installed.
 */
export function useCesiumViewer(_mapConfig?: MapConfig) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<'pending' | 'loaded' | 'absent'>(
    'pending',
  );

  useEffect(() => {
    let disposed = false;
    let viewer: ViewerHandle | null = null;

    (async () => {
      let cesium: CesiumLike | null = null;
      const imageryPromise = fetchGlobeImagery();
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        cesium = (await import('cesium')) as any;
      } catch {
        cesium = null;
      }
      if (disposed) return;
      if (!cesium || !ref.current) {
        setStatus(cesium ? 'pending' : 'absent');
        return;
      }
      const imagery = await imageryPromise;
      if (disposed || !ref.current) return;
      try {
        viewer = new cesium.Viewer(ref.current, {
          terrainProvider: new cesium.EllipsoidTerrainProvider(),
          // Basemap tiles come from our own backend, not a public CDN.
          // Cesium >= 1.107 otherwise falls back to Ion-backed Bing Maps,
          // which silently 401s without a token. We must not hit the raw
          // OpenStreetMap servers (their policy forbids app use), and a
          // direct tile CDN is routinely blocked by browser ad/privacy
          // blockers. The imagery is public-domain shaded relief, or the
          // raster street tiles an operator configured with
          // OE_GLOBE_STREET_TILES_URL (see ``fetchGlobeImagery``).
          baseLayer: new cesium.ImageryLayer(
            new cesium.UrlTemplateImageryProvider({
              url: imagery.url,
              credit: imagery.credit,
              // The source has nothing deeper. Asking past it returns a
              // blank tile, so let Cesium stretch the last real level
              // instead of tiling holes over the site.
              maximumLevel: imagery.maxZoom,
            }),
          ),
          baseLayerPicker: false,
        });
        setStatus('loaded');
      } catch {
        setStatus('absent');
      }
    })();

    return () => {
      disposed = true;
      if (viewer) {
        try {
          viewer.destroy();
        } catch {
          /* viewer already gone — ignore */
        }
      }
    };
  }, []);

  return { ref, status };
}
