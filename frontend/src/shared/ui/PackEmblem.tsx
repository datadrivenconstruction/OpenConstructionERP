// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PackEmblem — the mark that identifies a pack wherever a pack is shown.
 *
 * A country pack is identified by its country. It used to be identified by a
 * logo, and that logo was ours: we author these packs, so `us-texas` and
 * `brazil-sinapi` shipped a mark drawn in-house, which told a reader nothing
 * except that the pack existed. A flag answers the question the reader
 * actually has, which is "whose rules is this", and it answers it before the
 * name is read.
 *
 * The choice is made by the pack's own type rather than by a list kept here.
 * ``type === 'country'`` is inferred on the backend from country metadata and
 * already beats partner co-branding in that inference, so a partner pack
 * written for one country - a Canadian or a German one - is a country pack by
 * the system's own reckoning and gets its flag. A list in this file would be a
 * second register of the same fact and would drift from the first.
 *
 * A pack with no country to draw - an industry or cross-region pack, or a
 * country pack whose ISO code has no flag in the table - gets a monogram in
 * its own colours. It does not get its logo back. The packs ship wide wordmark
 * logos drawn for a co-brand strip, and one squeezed into a 48px square was an
 * illegible sliver that also flashed raw alt text on a slow first paint, so
 * the logo was never the better of the two even before the flags arrived.
 *
 * Sub-national packs are the case the flag alone cannot carry. California and
 * Texas both fly the same national flag, so the plate adds the subdivision
 * code beneath it. Drawing the state flags instead was the alternative and was
 * not taken: the Texas flag is two bands and a star, the California flag is a
 * bear, and a hand-reduced bear reads as a mistake rather than as a flag.
 */

import { packCountryCode } from '@/shared/lib/regionalPack';
import { CountryFlag } from '@/shared/ui/CountryFlag';

/** The pack fields an emblem needs. Structural on purpose: the packs page and
 *  the co-brand badge hold the manifest under two different interfaces. */
export interface PackEmblemPack {
  slug: string;
  partner_name: string;
  type?: string;
  /** Read by ``packCountryCode`` as the fallback when metadata is silent. */
  default_locale: string;
  metadata: Record<string, unknown>;
  branding: {
    primary_color: string;
    accent_color: string | null;
  };
}

interface PackEmblemProps {
  pack: PackEmblemPack;
  /** Plate edge in pixels. Sizes are passed as inline style rather than as
   *  Tailwind classes: a composed class name is not a literal in the source
   *  and the JIT never emits it. */
  size: number;
  className?: string;
}

/** Two-letter monogram from the pack's name, for a pack with no flag and no
 *  logo. Kept identical to what the two call sites drew before. */
export function packMonogram(name: string): string {
  const words = name.trim().split(/[\s._-]+/).filter(Boolean);
  const letters =
    words.length >= 2 ? `${words[0]?.[0] ?? ''}${words[1]?.[0] ?? ''}` : name.trim().slice(0, 2);
  return letters.toUpperCase() || '?';
}

/** The flag a pack should fly, or null for one that should not fly any.
 *
 *  The country itself is resolved by ``packCountryCode`` in
 *  ``shared/lib/regionalPack`` and not again here, because a second reading of
 *  ``metadata.country`` would be a second register of one fact and would drift
 *  from the first. This adds only the two conditions that are about the
 *  emblem: the pack must be a country pack, and ``XX`` is a declaration that
 *  there is no single market rather than a country. */
function flagCodeFor(pack: PackEmblemPack): string | null {
  if ((pack.type ?? 'partner') !== 'country') return null;
  const iso = packCountryCode(pack);
  if (!iso || iso === 'xx') return null;
  return iso;
}

/** The part of ``US-CA`` that the national flag cannot say, or null. */
function subdivisionCode(pack: PackEmblemPack): string | null {
  const raw = pack.metadata.subdivision;
  if (typeof raw !== 'string') return null;
  const tail = raw.trim().toUpperCase().split('-').slice(1).join('-');
  return tail || null;
}

export function PackEmblem({ pack, size, className = '' }: PackEmblemProps) {
  const radius = size <= 24 ? 'rounded-[5px]' : 'rounded-xl';
  const country = flagCodeFor(pack);
  const subdivision = country ? subdivisionCode(pack) : null;
  // Below this the plate is too small to hold a legible code, and the pack's
  // name is beside it in every place that draws one this small.
  const showSubdivision = Boolean(subdivision) && size >= 36;

  if (country) {
    // The flag keeps its own 10:7 proportion inside a square plate rather than
    // being cropped to fill it. A cover-cropped flag loses the shape that makes
    // it recognisable, which is the whole reason it is here.
    const flagWidth = Math.round(size * (showSubdivision ? 0.66 : 0.74));
    return (
      <span
        className={`relative flex shrink-0 items-center justify-center overflow-hidden bg-surface-secondary shadow-sm ring-1 ring-border ${radius} ${className}`}
        style={{ width: size, height: size }}
        data-testid={`pack-emblem-${pack.slug}`}
        data-pack-emblem="flag"
        data-country={country}
      >
        <span
          className="flex flex-col items-center"
          style={{ gap: showSubdivision ? Math.round(size * 0.06) : 0 }}
        >
          <CountryFlag code={country} size={flagWidth} className="shadow-sm ring-1 ring-black/10" />
          {showSubdivision && (
            <span
              className="font-mono font-semibold leading-none tracking-wide text-content-secondary"
              style={{ fontSize: Math.max(8, Math.round(size * 0.2)) }}
            >
              {subdivision}
            </span>
          )}
        </span>
      </span>
    );
  }

  const accent = pack.branding.accent_color ?? pack.branding.primary_color;

  return (
    <span
      className={`flex shrink-0 items-center justify-center font-bold tracking-tight text-white shadow-sm ${radius} ${className}`}
      style={{
        width: size,
        height: size,
        fontSize: Math.max(9, Math.round(size * 0.34)),
        background: `linear-gradient(135deg, ${pack.branding.primary_color}, ${accent})`,
      }}
      data-testid={`pack-emblem-${pack.slug}`}
      data-pack-emblem="monogram"
    >
      {packMonogram(pack.partner_name)}
    </span>
  );
}
