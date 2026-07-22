// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { UserRound } from 'lucide-react';
import { ROLE_BY_ID } from './roles';
import type { ProfessionalRole } from './types';

interface RoleArtProps {
  role: ProfessionalRole;
  /** Sizing classes (height + width). Rendered as a circular tile. */
  className?: string;
  title?: string;
  /**
   * Show the small "person" kind-badge in the corner. It marks this axis as a
   * human ("Your role" = you, a person) so a user never confuses a role with a
   * company type. Rendered at the selector / summary sizes; leave off for the
   * tiny stacked avatars where it would not fit.
   */
  withKindBadge?: boolean;
}

/**
 * The icon for a professional role: the role's own glyph centred in a soft
 * tinted disc, drawn in the role's accent colour. A flat, clear vector mark -
 * no raster portrait, no brand asset - in the same iconographic language as
 * the case tiles, so a role reads at a glance and resolves in both light and
 * dark themes.
 *
 * The shape is deliberately a CIRCLE (an avatar reads as a person) and, at the
 * larger selector sizes, it carries a little person-badge in the corner so the
 * "Your role" axis is unmistakably about you, a human - as opposed to the
 * rounded-SQUARE, building-badged company tiles (see ``CompanyArt``).
 */
export function RoleArt({ role, className, title, withKindBadge = false }: RoleArtProps) {
  const meta = ROLE_BY_ID[role];
  if (!meta) return null;
  const Glyph = meta.badge;
  return (
    <span
      title={title}
      aria-hidden="true"
      className={clsx(
        // `tint.tile` carries the soft background, the accent text colour the
        // glyph inherits through currentColor, and the ring - all theme-aware.
        // `relative` anchors the corner kind-badge.
        'relative inline-flex shrink-0 items-center justify-center rounded-full ring-1 ring-inset',
        meta.tint.tile,
        className,
      )}
    >
      <Glyph className="h-1/2 w-1/2" strokeWidth={2} aria-hidden="true" />
      {withKindBadge && (
        <span
          className={clsx(
            // A round badge (people are round) on an elevated plate so the
            // person mark stays legible over any tile colour, in the role's
            // own accent so it still belongs to this role.
            'absolute -bottom-0.5 -right-0.5 inline-flex h-[40%] w-[40%] items-center justify-center rounded-full bg-surface-elevated ring-1 ring-inset ring-border-light',
            meta.tint.text,
          )}
        >
          <UserRound className="h-3/5 w-3/5" strokeWidth={2.4} aria-hidden="true" />
        </span>
      )}
    </span>
  );
}
