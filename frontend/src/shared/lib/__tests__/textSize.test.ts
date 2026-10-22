import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  PLATFORM_APPEARANCE,
  TEXT_SCALE,
  TEXT_SIZES,
  applyAppearance,
  matchPreset,
  sanitizeAppearance,
} from '../appearance';

const CSS = readFileSync(resolve(__dirname, '../../../index.css'), 'utf8');

describe('text size axis', () => {
  it('has five steps, default 100%', () => {
    expect(TEXT_SIZES).toHaveLength(5);
    expect(TEXT_SCALE.default).toBe(1);
    expect(TEXT_SCALE.small).toBe(0.875);
    expect(TEXT_SCALE.largest).toBe(1.375);
  });

  it('sanitizes to known values only', () => {
    expect(sanitizeAppearance({ text: 'larger' })).toEqual({ text: 'larger' });
    expect(sanitizeAppearance({ text: 'huge' })).toBeNull();
  });

  it('applies to <html> as data-text', () => {
    const root = document.createElement('html');
    applyAppearance({ ...PLATFORM_APPEARANCE, text: 'large' }, root);
    expect(root.dataset.text).toBe('large');
  });

  it('does not turn a preset into a custom mix', () => {
    expect(matchPreset({ ...PLATFORM_APPEARANCE, text: 'largest' })).toBe('classic');
  });

  it('index.css scales the root by the same factors', () => {
    for (const size of TEXT_SIZES) {
      if (size === 'default') continue;
      const px = 15 * TEXT_SCALE[size];
      expect(CSS).toContain(`html[data-text='${size}'] { font-size: ${px}px; }`);
    }
  });
});
