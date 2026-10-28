// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// The barrel re-exports the *lazy* wrapper, so a feature that imports
// ProjectMap from ``@/shared/ui`` does NOT eagerly pull maplibre-gl into
// its chunk. ``ProjectMap`` (1 MB transitively) only downloads when the
// component actually mounts on /projects or /projects/{id}.
export { ProjectMap } from './ProjectMapLazy';
// ``buildGeocodeQuery`` re-exported from the lightweight module so
// importing it doesn't transitively pull in maplibre + its CSS.
export { buildGeocodeQuery } from './geocode';
export type { LatLng } from './ProjectMap';
