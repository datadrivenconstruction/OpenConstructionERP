// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the 360-degree panorama viewer.
 *
 * The daily-diary photo gallery flags equirectangular captures with the
 * ``is_360`` boolean (already exposed by the backend DiaryPhotoResponse).
 * These helpers decide when the spherical viewer applies and which URL to
 * texture the sphere with - kept free of three.js / React so they can be
 * unit-tested in isolation (no WebGL, no DOM).
 */

/** The shape this module needs from a diary photo - a structural subset of
 * the full ``DiaryPhoto`` type so the helpers stay decoupled from the API. */
export interface Panorama360Photo {
  is_360?: boolean | null;
  file_url?: string | null;
  thumbnail_url?: string | null;
}

/**
 * True when a photo should offer the spherical 360 viewer.
 *
 * A photo qualifies only when it is explicitly flagged ``is_360`` AND has a
 * usable full-resolution ``file_url`` to texture the sphere with. The
 * thumbnail is deliberately NOT enough on its own: a low-res thumb wrapped on
 * a sphere looks broken, and a flag with no source URL cannot be rendered.
 */
export function is360Photo(photo: Panorama360Photo | null | undefined): boolean {
  if (!photo) return false;
  if (photo.is_360 !== true) return false;
  const url = photo.file_url;
  return typeof url === 'string' && url.trim().length > 0;
}

/**
 * The URL to texture the equirectangular sphere with.
 *
 * Always the full-resolution ``file_url`` - the sphere wraps the whole image,
 * so a thumbnail would look pixelated. Returns ``null`` when there is no
 * usable source (the caller then keeps the flat thumbnail and skips the
 * viewer). Reuses the already-served photo URL; no new endpoint.
 */
export function panoramaImageUrl(
  photo: Panorama360Photo | null | undefined,
): string | null {
  if (!photo) return null;
  const url = photo.file_url;
  if (typeof url !== 'string') return null;
  const trimmed = url.trim();
  return trimmed.length > 0 ? trimmed : null;
}
