// The classic look strips gradients. A hero that paints white text on a dark
// gradient must keep a dark fill, or the text lands on the light page.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(__dirname, '../../index.css'), 'utf8');

describe('classic look gradients', () => {
  it('strips gradient images', () => {
    expect(css).toMatch(/html\[data-look='classic'\] \[class\*='bg-gradient-'\],[\s\S]*?background-image: none !important;/);
  });

  it('keeps the first gradient stop as a flat fill, but not behind gradient text', () => {
    const rule = css.match(
      /html\[data-look='classic'\] \[class\*='bg-gradient-'\]\[class\*='from-'\]:not\(\.bg-clip-text\) \{([^}]*)\}/,
    );
    expect(rule?.[1]).toContain('background-color: var(--tw-gradient-from) !important;');
  });
});
