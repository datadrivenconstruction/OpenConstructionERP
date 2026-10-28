// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, type ComponentType } from 'react';
import clsx from 'clsx';
import { Building2, type LucideProps } from 'lucide-react';
import { companyThumbFor } from './caseFaces';

/**
 * Company-type ids that have a generated line-art emblem at
 * /cases-art/company/<id>.webp. Add ids here as emblems are produced; until a
 * type is listed it falls through to its photograph (and then to its lucide
 * glyph), so the selector never fires a wasted 404.
 */
const COMPANY_ART_IDS = new Set<string>([]);

interface CompanyArtProps {
  /** Company-type id; maps to /cases-art/company/<id>.webp. */
  id: string;
  /** Glyph shown until (or if) an emblem picture exists for this type. */
  fallbackIcon: ComponentType<LucideProps>;
  /** Colour class for the fallback glyph. */
  fallbackClass?: string;
  /**
   * Soft tint background for the tile (the company type's `tint.tile`). When
   * given, the tile carries the type's own colour instead of a plain light
   * plate, so a company type reads as a coloured chip like its role
   * counterpart. Omitted -> the historical always-light plate.
   */
  tileClass?: string;
  className?: string;
  title?: string;
  /**
   * Show the small "building" kind-badge in the corner. It marks this axis as a
   * company ("My company" = the firm you work for), the organisation
   * counterpart to the person-badged, circular role tiles (see ``RoleArt``).
   */
  withKindBadge?: boolean;
}

/**
 * The picture for a company type, in a rounded-SQUARE tile - the building /
 * app-icon shape reads as an organisation, deliberately unlike the circular,
 * person-badged role avatars (``RoleArt``). Three sources, in order: the
 * generated line-art emblem if this type has one, the photograph of a site
 * this kind of firm works on (``companyThumbFor``, the same picture the
 * marketing site puts on its company cards), and finally the type's lucide
 * glyph with no network request at all. At the selector / summary sizes it
 * carries a little building-badge so the "My company" axis is unmistakably
 * about a firm, not a person - which the photograph makes more necessary
 * rather than less, since a site photograph does not say "company" on its own.
 */
export function CompanyArt({
  id,
  fallbackIcon: Icon,
  fallbackClass,
  tileClass,
  className,
  title,
  withKindBadge = false,
}: CompanyArtProps) {
  const [broken, setBroken] = useState(false);
  const [lastId, setLastId] = useState(id);
  if (id !== lastId) {
    setLastId(id);
    setBroken(false);
  }

  const emblem = COMPANY_ART_IDS.has(id) ? `/cases-art/company/${id}.webp` : null;
  const photo = emblem ? null : companyThumbFor(id);
  const src = broken ? null : (emblem ?? photo);

  // A rounded-SQUARE badge (organisations are square) on an elevated plate so
  // the building mark stays legible over any tile colour or photograph, in the
  // type's own accent so it still belongs here.
  const badge = withKindBadge ? (
    <span
      className={clsx(
        'absolute -bottom-0.5 -right-0.5 inline-flex h-[40%] w-[40%] items-center justify-center rounded-md bg-surface-elevated ring-1 ring-inset ring-border-light',
        fallbackClass,
      )}
    >
      <Building2 className="h-3/5 w-3/5" strokeWidth={2.2} aria-hidden="true" />
    </span>
  ) : null;

  if (!src) {
    return (
      <span
        title={title}
        className={clsx(
          'relative inline-flex shrink-0 items-center justify-center rounded-xl ring-1 ring-inset',
          tileClass ?? 'bg-white ring-border-light dark:bg-slate-100',
          className,
        )}
      >
        <Icon size={26} strokeWidth={1.7} className={fallbackClass} aria-hidden="true" />
        {badge}
      </span>
    );
  }

  return (
    // The badge overhangs the tile, so the rounding and the clipping live on an
    // inner span - a single span would have to choose between clipping the
    // picture's corners and clipping the badge.
    <span title={title} className={clsx('relative inline-flex shrink-0', className)}>
      <span className="flex h-full w-full overflow-hidden rounded-xl bg-white ring-1 ring-inset ring-border-light dark:bg-slate-100">
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          width={emblem ? 384 : 128}
          height={emblem ? 384 : 128}
          draggable={false}
          onError={() => setBroken(true)}
          // The emblem is line art drawn to sit inside its frame; the
          // photograph is a photograph and fills it.
          className={clsx('h-full w-full', emblem ? 'object-contain p-1.5' : 'object-cover')}
        />
      </span>
      {badge}
    </span>
  );
}
