// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - the specialist's photograph on a case tile, and the one place the
// country-variant fallback happens.
//
// `caseFaceFor` decides which portrait to ask for by reading the generated
// manifest of country art (see the header of caseFaces.ts), so `face.src`
// names a file that was on disk when the commit was made. This component is
// the second line, not the first: a deploy can ship the manifest without the
// webp beside it, a webp can be pulled after the fact, and a proxy can serve a
// 200 with the wrong bytes. When the request fails for any of those reasons
// the pooled portrait goes in on the error event, so the reader sees the
// picture the case wore before any market had one rather than an empty tile or
// a broken-image glyph.
//
// The photograph is decorative on every surface: `alt=""` maps the <img> out
// of the accessibility tree, and the role and the market are both stated in
// words on the same tile. The `aria-hidden="true"` that the constellation cell
// used to carry alongside its own `alt=""` is not reproduced here. It changed
// nothing - an empty alt already removes the element - and reinstating it on
// one of five call sites would read as though the other four were different.
//
// The five places a face is shown - the Cases hub card, the case page hero
// column and its catalogue band, the constellation cell on the case page, and
// the dashboard gallery - all come through here. That is five <img> sites in
// four files; PlaybookRunner holds two of them. The dashboard forces the
// shared component: its <img> is rendered inside a `.map()` in the parent's
// body, where a per-tile `useState` is not something you can write. One
// component is the answer for the other four too, since a fallback that four
// of five surfaces implement is a fallback one surface is missing.

import { useState, type CSSProperties } from 'react';
import type { CaseFace } from './caseFaces';

interface CaseFacePhotoProps {
  /** The requested portrait and its pooled fallback, from `dealCaseFaces`. */
  face: CaseFace;
  /** Classes for the <img> itself. Every caller frames it differently - a hex
   *  crop, a masked band, a masked column - so the shape stays with them. */
  className?: string;
  /** Inline style for the <img>, for the clip-path the hex tiles carry. */
  style?: CSSProperties;
  /** Intrinsic size, passed through rather than hardcoded: the three 340x480
   *  callers give it and the dashboard deliberately does not, and pinning a
   *  size on that one would move its layout. */
  width?: number;
  height?: number;
}

/**
 * The photograph of the specialist a case is written for.
 *
 * Decorative everywhere it is used (`alt=""`): the role and the market are
 * stated in words on the same tile, so nothing is said only in a picture.
 *
 * Falls back from the country portrait to the pooled one when the former does
 * not load. That is now a guard against a deploy going wrong rather than the
 * routine path it was before the manifest, and it stays because the cost of
 * being wrong about it is a broken-image glyph on a marketing surface. When
 * the two are equal - a universal case, a market with no art, or a bespoke
 * `pbk-*` photo - the fallback is a no-op and a genuinely missing file leaves
 * the browser's own placeholder, which is the behaviour these tiles always
 * had.
 */
export function CaseFacePhoto({ face, className, style, width, height }: CaseFacePhotoProps) {
  const [broken, setBroken] = useState(false);
  // A card can be handed a different case without unmounting - the hub filters
  // in place and the case page navigates between cases - so a `broken` flag
  // left over from the previous src would pin the tile to the pooled portrait
  // for the rest of the session. Same reset CompanyArt does on its `id`.
  const [lastSrc, setLastSrc] = useState(face.src);
  if (face.src !== lastSrc) {
    setLastSrc(face.src);
    setBroken(false);
  }

  return (
    <img
      src={broken ? face.pooled : face.src}
      alt=""
      loading="lazy"
      decoding="async"
      width={width}
      height={height}
      draggable={false}
      // Firing again on the pooled portrait is harmless: the state is already
      // true, React bails out, and there is no second source to loop between.
      onError={() => setBroken(true)}
      className={className}
      style={style}
    />
  );
}
