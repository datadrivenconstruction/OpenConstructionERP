// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * A video cover steps down maxresdefault -> hqdefault -> a neutral local tile,
 * and never ends on a broken image or YouTube's grey placeholder.
 *
 * Run: npx vitest run src/features/videos/VideoCover.test.tsx
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { VideoCover, fallbackCover } from './VideoCover';

const MAXRES = 'https://i.ytimg.com/vi/abc/maxresdefault.jpg';
const HQ = 'https://i.ytimg.com/vi/abc/hqdefault.jpg';

function img(container: HTMLElement): HTMLImageElement | null {
  return container.querySelector('img');
}

/** A load event on an image with the given decoded width. */
function loadAt(el: HTMLImageElement, naturalWidth: number) {
  Object.defineProperty(el, 'naturalWidth', { value: naturalWidth, configurable: true });
  fireEvent.load(el);
}

describe('fallbackCover', () => {
  it('steps maxresdefault down to hqdefault and stops there', () => {
    expect(fallbackCover(MAXRES)).toBe(HQ);
    expect(fallbackCover(HQ)).toBeNull();
    expect(fallbackCover('/assets/videos/academy/intro.webp')).toBeNull();
  });
});

describe('VideoCover', () => {
  it('shows the full-size cover when it loads', () => {
    const { container } = render(<VideoCover src={MAXRES} />);
    loadAt(img(container)!, 1280);
    expect(img(container)!.getAttribute('src')).toBe(MAXRES);
    expect(screen.queryByTestId('video-cover-placeholder')).toBeNull();
  });

  it('steps down to hqdefault when maxresdefault errors', () => {
    const { container } = render(<VideoCover src={MAXRES} />);
    fireEvent.error(img(container)!);
    expect(img(container)!.getAttribute('src')).toBe(HQ);
  });

  it('shows the neutral tile when hqdefault errors too', () => {
    const { container } = render(<VideoCover src={MAXRES} className="h-full w-full" />);
    fireEvent.error(img(container)!);
    fireEvent.error(img(container)!);
    expect(img(container)).toBeNull();
    const tile = screen.getByTestId('video-cover-placeholder');
    expect(tile.className).toContain('h-full w-full');
  });

  it('treats the 120px grey placeholder at both sizes as missing', () => {
    const { container } = render(<VideoCover src={MAXRES} />);
    loadAt(img(container)!, 120);
    expect(img(container)!.getAttribute('src')).toBe(HQ);
    loadAt(img(container)!, 120);
    expect(screen.getByTestId('video-cover-placeholder')).toBeTruthy();
  });

  it('falls back straight to the tile when a local cover fails', () => {
    const { container } = render(<VideoCover src="/assets/videos/academy/intro.webp" />);
    fireEvent.error(img(container)!);
    expect(screen.getByTestId('video-cover-placeholder')).toBeTruthy();
  });

  it('tries again when handed a different video', () => {
    const { container, rerender } = render(<VideoCover src={HQ} />);
    fireEvent.error(img(container)!);
    expect(img(container)).toBeNull();
    rerender(<VideoCover src="https://i.ytimg.com/vi/def/maxresdefault.jpg" />);
    expect(img(container)!.getAttribute('src')).toBe('https://i.ytimg.com/vi/def/maxresdefault.jpg');
  });

  it('keeps the alt text on the tile when the cover carries meaning', () => {
    const { container } = render(<VideoCover src={HQ} alt="Intro to estimating" />);
    fireEvent.error(img(container)!);
    expect(screen.getByRole('img', { name: 'Intro to estimating' })).toBeTruthy();
  });
});
