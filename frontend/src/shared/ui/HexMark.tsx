// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// HexMark - a honeycomb badge pinned to a card's top-start corner, slightly
// over its edge. Shows a photo cropped to the hexagon, a building drawing when
// there is no photo, or an icon. Always decorative (alt=""): the card names it.

import type { ReactNode } from 'react';
import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';

export type HexBuildingKind = 'tower' | 'residential' | 'hospital' | 'bridge' | 'warehouse';

const HEX = 'polygon(25% 3%, 75% 3%, 100% 50%, 75% 97%, 25% 97%, 0% 50%)';

/** Line drawings in currentColor; no text, no faces, no logos. */
function BuildingGlyph({ kind }: { kind: HexBuildingKind }) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  let body: ReactNode;
  switch (kind) {
    case 'tower':
      body = (
        <>
          <path d="M9 28V8l7-3v23M16 28V11l7 2v15M6 28h20" />
          <path d="M11 12h2M11 16h2M11 20h2M19 16h2M19 20h2M19 24h2" />
        </>
      );
      break;
    case 'residential':
      body = (
        <>
          <path d="M5 15l11-9 11 9M8 13v15h16V13M5 28h22" />
          <path d="M13 28v-6h6v6M11 16h3M18 16h3" />
        </>
      );
      break;
    case 'hospital':
      body = (
        <>
          <path d="M6 28V11h20v17M4 28h24M13 28v-5h6v5" />
          <path d="M16 13v6M13 16h6" />
        </>
      );
      break;
    case 'bridge':
      body = (
        <>
          <path d="M3 20h26M3 24h26M9 20V8M23 20V8M9 9l-6 11M9 9l7 11M23 9l-7 11M23 9l6 11" />
        </>
      );
      break;
    default:
      body = (
        <>
          <path d="M4 28V14l12-7 12 7v14M2 28h28" />
          <path d="M9 28v-9h14v9M9 22h14M9 25h14" />
        </>
      );
  }
  return (
    <svg viewBox="0 0 32 32" width="60%" height="60%" aria-hidden="true" {...common}>
      {body}
    </svg>
  );
}

export interface HexMarkProps {
  /** Raster to crop into the hexagon; wins over `kind` and `icon`. */
  src?: string | null;
  /** Building drawing used when there is no photo. */
  kind?: HexBuildingKind;
  /** Icon used when there is neither a photo nor a building kind. */
  icon?: LucideIcon;
  /** Ring in the accent colour at full strength. */
  active?: boolean;
  /** CSS colour of the ring; defaults to the theme accent. */
  accent?: string;
  /** Pixel size of the badge (width; height follows the hex ratio). */
  size?: number;
  /** Position classes; defaults to `-top-3 -start-3`. */
  className?: string;
}

/**
 * Hexagonal badge for the top-start corner of a `relative group` card.
 * Hover lift comes from the card's `group`; reduced motion turns it off.
 */
export function HexMark({
  src,
  kind,
  icon: Icon,
  active = false,
  accent,
  size = 56,
  className,
}: HexMarkProps) {
  const height = Math.round(size * 0.9);
  return (
    <span
      aria-hidden="true"
      data-testid="hex-mark"
      className={clsx(
        'pointer-events-none absolute z-10 block',
        'drop-shadow-[0_4px_10px_rgba(15,23,42,0.18)] dark:drop-shadow-[0_4px_12px_rgba(0,0,0,0.5)]',
        'transition-transform duration-300 ease-oe group-hover:-translate-y-0.5 group-hover:scale-105',
        'motion-reduce:transition-none motion-reduce:group-hover:translate-y-0 motion-reduce:group-hover:scale-100',
        className ?? '-top-3 -start-3',
      )}
      style={{ width: size, height }}
    >
      {/* Outer hex is the ring; the inner hex is inset by 2px. */}
      <span
        className={clsx(
          'absolute inset-0 transition-colors',
          accent ? 'opacity-80 group-hover:opacity-100' : active ? 'bg-oe-blue' : 'bg-oe-blue/45 group-hover:bg-oe-blue/70',
          accent && active && 'opacity-100',
        )}
        style={{ clipPath: HEX, backgroundColor: accent }}
      />
      <span
        className="absolute inset-[2.5px] flex items-center justify-center overflow-hidden bg-gradient-to-br from-oe-blue-subtle to-surface-elevated text-oe-blue dark:from-oe-blue/25 dark:to-surface-secondary"
        style={{ clipPath: HEX }}
      >
        {src ? (
          <img
            src={src}
            alt=""
            loading="lazy"
            decoding="async"
            width={128}
            height={128}
            draggable={false}
            className="h-full w-full object-cover"
          />
        ) : kind ? (
          <BuildingGlyph kind={kind} />
        ) : Icon ? (
          <Icon size={Math.round(size * 0.38)} strokeWidth={1.8} />
        ) : null}
      </span>
    </span>
  );
}
