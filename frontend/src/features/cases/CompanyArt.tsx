// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, type ComponentType } from 'react';
import clsx from 'clsx';
import { Building2, type LucideProps } from 'lucide-react';

/**
 * Company-type ids that have a generated line-art emblem at
 * /cases-art/company/<id>.webp. Add ids here as emblems are produced; until a
 * type is listed it renders its lucide glyph and no image request is attempted,
 * so the selector never fires a wasted 404.
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
 * The emblem for a company type, in a rounded-SQUARE tile - the building /
 * app-icon shape reads as an organisation, deliberately unlike the circular,
 * person-badged role avatars (``RoleArt``). Falls back to the type's lucide
 * glyph (with no network request) for any type that does not yet have an
 * emblem, so the selector always renders something distinguishable and fast.
 * At the selector / summary sizes it carries a little building-badge so the
 * "My company" axis is unmistakably about a firm, not a person.
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

  if (broken || !COMPANY_ART_IDS.has(id)) {
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
        {withKindBadge && (
          <span
            className={clsx(
              // A rounded-SQUARE badge (organisations are square) on an
              // elevated plate so the building mark stays legible over any tile
              // colour, in the type's own accent so it still belongs here.
              'absolute -bottom-0.5 -right-0.5 inline-flex h-[40%] w-[40%] items-center justify-center rounded-md bg-surface-elevated ring-1 ring-inset ring-border-light',
              fallbackClass,
            )}
          >
            <Building2 className="h-3/5 w-3/5" strokeWidth={2.2} aria-hidden="true" />
          </span>
        )}
      </span>
    );
  }

  return (
    <span
      title={title}
      className={clsx(
        'inline-flex shrink-0 overflow-hidden rounded-xl bg-white ring-1 ring-inset ring-border-light dark:bg-slate-100',
        className,
      )}
    >
      <img
        src={`/cases-art/company/${id}.webp`}
        alt=""
        loading="lazy"
        decoding="async"
        width={384}
        height={384}
        draggable={false}
        onError={() => setBroken(true)}
        className="h-full w-full object-contain p-1.5"
      />
    </span>
  );
}
