// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

// MapLibre 6 derives its default URL from import.meta.url. Vite relocates
// that module during optimization/build, so its sibling worker disappears.
// A worker import also bundles its shared-module dependency and emits a
// fingerprinted worker respecting Vite's base URL in production.
setWorkerUrl(workerUrl);

export * from 'maplibre-gl';
