// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A video's cover. A published video shows the channel's own thumbnail from
// the YouTube image host; one that is not out yet shows the local WebP the
// catalogue ships for it.
//
// `maxresdefault` exists only for uploads of at least 720p. A missing one comes
// back either as an error or as a 120x90 grey placeholder that loads fine, so
// both cases step down to `hqdefault`, which every upload has.
//
// When the last source fails too (a thumbnail YouTube has not generated yet,
// a blocked image host, a local file that did not ship), the cover becomes a
// neutral local tile instead of the browser's broken-image glyph or a grey
// YouTube placeholder.

import { useState, type ImgHTMLAttributes } from 'react';
import { PlayCircle } from 'lucide-react';

export function fallbackCover(src: string): string | null {
  return src.includes('/maxresdefault.jpg') ? src.replace('/maxresdefault.jpg', '/hqdefault.jpg') : null;
}

export interface VideoCoverProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  src: string;
  /** Above the fold: fetch now instead of when scrolled near. */
  eager?: boolean;
}

export function VideoCover({ src, eager, alt = '', ...rest }: VideoCoverProps) {
  const [current, setCurrent] = useState(src);
  const [failed, setFailed] = useState(false);
  const [prevSrc, setPrevSrc] = useState(src);
  if (src !== prevSrc) {
    setPrevSrc(src);
    setCurrent(src);
    setFailed(false);
  }
  const stepDown = () => {
    const next = fallbackCover(current);
    if (next) setCurrent(next);
    else setFailed(true);
  };
  if (failed) {
    return (
      <div
        data-testid="video-cover-placeholder"
        className={`${rest.className ?? ''} flex items-center justify-center bg-gradient-to-br from-slate-700 to-slate-900 text-white/60`}
        style={rest.style}
        {...(alt ? { role: 'img', 'aria-label': alt } : { 'aria-hidden': true })}
      >
        <PlayCircle className="h-8 w-8" strokeWidth={1.5} aria-hidden />
      </div>
    );
  }
  return (
    <img
      {...rest}
      src={current}
      alt={alt}
      width={rest.width ?? 480}
      height={rest.height ?? 270}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      referrerPolicy="no-referrer"
      onError={stepDown}
      onLoad={(e) => {
        if (e.currentTarget.naturalWidth > 0 && e.currentTarget.naturalWidth <= 120) stepDown();
      }}
    />
  );
}
