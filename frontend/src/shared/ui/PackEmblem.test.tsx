import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { CountryFlag } from './CountryFlag';
import { PackEmblem, packGlyphFor, type PackEmblemPack } from './PackEmblem';

function pack(over: Partial<PackEmblemPack> = {}): PackEmblemPack {
  return {
    slug: 'sample-pack',
    partner_name: 'Sample Pack',
    type: 'country',
    default_locale: 'en-US',
    metadata: { country: 'US' },
    branding: { primary_color: '#123456', accent_color: null },
    ...over,
  };
}

describe('PackEmblem', () => {
  it('draws the flag for a country pack and no logo beside it', () => {
    const { container } = render(<PackEmblem pack={pack()} size={48} />);

    const plate = container.querySelector('[data-pack-emblem]');
    expect(plate?.getAttribute('data-pack-emblem')).toBe('flag');
    expect(plate?.getAttribute('data-country')).toBe('us');
    // The point of the change: the pack's own mark is gone, not merely moved.
    expect(container.querySelector('img[alt$="logo"]')).toBeNull();
  });

  it('flies no flag for a pack that serves no single country', () => {
    // Cross-region packs declare XX. It is a real value meaning "no single
    // market", so it must not resolve to a flag of anything.
    const { container } = render(
      <PackEmblem
        pack={pack({ type: 'industry', slug: 'renewables-epc', metadata: { country: 'XX' } })}
        size={48}
      />,
    );
    expect(container.querySelector('[data-pack-emblem]')?.getAttribute('data-pack-emblem')).toBe(
      'monogram',
    );
  });

  it('flies no flag for an industry pack that carries a country anyway', () => {
    // The gate is the pack's type, not the presence of a country key. An
    // industry pack with a country would otherwise fly a flag for a market it
    // does not claim.
    const { container } = render(
      <PackEmblem pack={pack({ type: 'industry', metadata: { country: 'DE' } })} size={48} />,
    );
    expect(container.querySelector('[data-pack-emblem]')?.getAttribute('data-pack-emblem')).toBe(
      'monogram',
    );
  });

  it('draws a monogram, never a logo, for a pack with no country', () => {
    const { container } = render(<PackEmblem pack={pack({ type: 'partner' })} size={48} />);
    const plate = container.querySelector('[data-pack-emblem]');
    expect(plate?.getAttribute('data-pack-emblem')).toBe('monogram');
    expect(plate?.textContent).toBe('SP');
    expect(container.querySelector('img')).toBeNull();
  });

  it('tells the two packs apart that share one flag', () => {
    // us-california and us-texas both fly the same national flag, so the flag
    // alone cannot distinguish them and an assertion that each "renders a
    // flag" would pass on a build where they are indistinguishable. The
    // subdivision code is what carries the difference, so the test compares
    // the two renderings against each other rather than checking each alone.
    const california = render(
      <PackEmblem
        pack={pack({
          slug: 'us-california',
          metadata: { country: 'US', subdivision: 'US-CA' },
        })}
        size={48}
      />,
    );
    const texas = render(
      <PackEmblem
        pack={pack({ slug: 'us-texas', metadata: { country: 'US', subdivision: 'US-TX' } })}
        size={48}
      />,
    );

    const a = california.container.querySelector('[data-pack-emblem]')?.textContent ?? '';
    const b = texas.container.querySelector('[data-pack-emblem]')?.textContent ?? '';
    expect(a).toBe('CA');
    expect(b).toBe('TX');
    expect(a).not.toBe(b);
  });

  it('leaves the subdivision code off a plate too small to hold it', () => {
    const { container } = render(
      <PackEmblem
        pack={pack({ metadata: { country: 'US', subdivision: 'US-CA' } })}
        size={20}
      />,
    );
    expect(container.querySelector('[data-pack-emblem]')?.textContent).toBe('');
  });
});

/* Every country a shipped pack claims must have a flag that actually draws.
 *
 * This reads the packs on disk rather than a list kept here, because a list
 * would be a second register of the same fact: a pack added for a country with
 * no flag would leave the list unchanged and the plate empty, which is exactly
 * the failure the emblem was introduced to remove. The assertion is on an
 * ``<img>`` specifically, not on "something rendered": CountryFlag falls back
 * to an emoji for codes it has no drawing for, and Windows ships no glyphs for
 * regional-indicator pairs, so an emoji flag renders there as two letters -
 * silently, with no broken image and no error. */
describe('every shipped country pack has a flag that draws', () => {
  const packsDir = resolve(process.cwd(), '..', 'packs');

  const countries: Array<[string, string]> = [];
  if (existsSync(packsDir)) {
    for (const slug of readdirSync(packsDir)) {
      const srcDir = resolve(packsDir, slug, 'src');
      if (!existsSync(srcDir)) continue;
      for (const pkg of readdirSync(srcDir)) {
        const manifest = resolve(srcDir, pkg, 'manifest.py');
        if (!existsSync(manifest)) continue;
        const code = /"country":\s*"([A-Za-z]{2})"/.exec(readFileSync(manifest, 'utf-8'))?.[1];
        if (code && code.toUpperCase() !== 'XX') countries.push([slug, code.toLowerCase()]);
      }
    }
  }

  it('found the packs on disk', () => {
    // A loop over an empty list passes while checking nothing, and this one
    // reads a directory outside the frontend package, so it is the first thing
    // to break if the layout moves.
    expect(countries.length).toBeGreaterThan(8);
  });

  it.each(countries)('%s flies a drawn flag for %s', (_slug, code) => {
    const { container } = render(<CountryFlag code={code} size={24} />);
    expect(container.querySelector('img')).not.toBeNull();
  });
});

describe('PackEmblem glyph mode', () => {
  it('draws a bare flag with no plate for a country pack', () => {
    const { container } = render(<PackEmblem pack={pack()} size={48} bare glyph />);
    const plate = container.querySelector('[data-pack-emblem]');
    expect(plate?.getAttribute('data-pack-emblem')).toBe('flag');
    expect(plate?.getAttribute('data-pack-bare')).toBe('true');
  });

  it('draws a kind icon tile instead of a monogram for a pack without a flag', () => {
    const { container } = render(<PackEmblem pack={pack({ type: 'industry', metadata: {} })} size={48} glyph />);
    const plate = container.querySelector('[data-pack-emblem]');
    expect(plate?.getAttribute('data-pack-emblem')).toBe('glyph');
    expect(plate?.querySelector('svg')).not.toBeNull();
    expect(plate?.textContent).toBe('');
  });

  it('keeps the monogram when glyph mode is not requested', () => {
    const { container } = render(<PackEmblem pack={pack({ type: 'industry', metadata: {} })} size={16} bare />);
    expect(container.querySelector('[data-pack-emblem]')?.getAttribute('data-pack-emblem')).toBe('monogram');
  });

  it('maps industry keywords and types to distinct icons with a fallback', () => {
    const base = { type: 'industry', metadata: {} as Record<string, unknown> };
    const a = packGlyphFor({ ...base, slug: 'doker-formwork' });
    const b = packGlyphFor({ ...base, slug: 'renewables-epc' });
    const c = packGlyphFor({ ...base, slug: 'unknown-trade' });
    const d = packGlyphFor({ type: 'partner', slug: 'acme', metadata: {} });
    expect(new Set([a, b, c, d]).size).toBe(4);
    expect(packGlyphFor({ ...base, slug: 'x', metadata: { industry: 'formwork' } })).toBe(a);
  });
});
