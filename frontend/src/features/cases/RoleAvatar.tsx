// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RoleAvatar - an illustrated persona avatar for a professional role.
//
// Every avatar is the same head-and-shoulders bust drawn as inline SVG (no
// external image, no brand asset), painted in the role's own colour through
// `currentColor`, sitting on a soft tinted disc. What tells the roles apart is
// the head-gear the persona wears (a hard hat for field roles, a headset for
// coordinators, safety glasses for technical roles, a bare head for office
// roles) plus a small role badge in the corner. The whole thing is theme-aware:
// the disc, silhouette and badge all resolve against light or dark tokens, so
// the same component reads on either background.
//
// The recipe (colour, head-gear, badge glyph) lives in `roles.ts` so this file
// is pure presentation. Reusable anywhere a role needs a face, not just the
// Cases hub.

import { useId } from 'react';
import clsx from 'clsx';
import type { ProfessionalRole } from './types';
import { ROLE_BY_ID, type RoleHeadgear } from './roles';

/** The head-gear overlay drawn on the persona, in the role's `currentColor`. */
function Headgear({ kind }: { kind: RoleHeadgear }) {
  switch (kind) {
    case 'hardhat':
      return (
        <g>
          {/* dome + wide brim: the brim reaching past the head is what reads
              as a hard hat even in a single flat colour. */}
          <path d="M14.7 15.6 A9.3 8.4 0 0 1 33.3 15.6 Z" className="fill-current" />
          <rect x="12" y="14.3" width="24" height="2.6" rx="1.3" className="fill-current" />
          <rect x="23" y="8.6" width="2" height="6" rx="1" className="fill-current opacity-70" />
        </g>
      );
    case 'headset':
      return (
        <g fill="none" stroke="currentColor" strokeLinecap="round">
          <path d="M15 16 A9.4 9.4 0 0 1 33 16" strokeWidth="2.4" />
          <path d="M15.4 20.4 Q14.6 27 21 26.2" strokeWidth="1.8" />
          <circle cx="15.2" cy="19.4" r="2.4" className="fill-current" stroke="none" />
          <circle cx="32.8" cy="19.4" r="2.4" className="fill-current" stroke="none" />
        </g>
      );
    case 'glasses':
      return (
        <g>
          <rect x="16.2" y="17.6" width="6" height="4.4" rx="2" className="fill-black opacity-30" />
          <rect x="25.8" y="17.6" width="6" height="4.4" rx="2" className="fill-black opacity-30" />
          <path d="M22.2 19.8 h3.6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </g>
      );
    default:
      return null;
  }
}

export interface RoleAvatarProps {
  role: ProfessionalRole;
  /** Sizing classes for the outer square (default `h-11 w-11`). */
  className?: string;
  /** Optional tooltip / accessible title. */
  title?: string;
}

/** A round, colour-coded persona avatar for a professional role. */
export function RoleAvatar({ role, className, title }: RoleAvatarProps) {
  const clipId = useId();
  const meta = ROLE_BY_ID[role];
  if (!meta) return null;
  const Badge = meta.badge;
  return (
    <span
      className={clsx('relative inline-flex shrink-0', className ?? 'h-11 w-11')}
      title={title}
      aria-hidden="true"
    >
      <svg viewBox="0 0 48 48" className={clsx('h-full w-full', meta.avatarText)}>
        <defs>
          <clipPath id={clipId}>
            <circle cx="24" cy="24" r="24" />
          </clipPath>
        </defs>
        <circle cx="24" cy="24" r="24" className="fill-current opacity-[0.14]" />
        <g clipPath={`url(#${clipId})`}>
          {/* shoulders + head bust */}
          <path
            d="M11 46 C11 35 16.5 31 24 31 C31.5 31 37 35 37 46 Z"
            className="fill-current opacity-90"
          />
          <circle cx="24" cy="20" r="8.4" className="fill-current opacity-90" />
          <Headgear kind={meta.headgear} />
        </g>
      </svg>
      {/* role badge: a small glyph that names the role at a glance */}
      <span className="absolute -bottom-0.5 -right-0.5 flex h-[44%] w-[44%] items-center justify-center rounded-full bg-surface-primary shadow-sm ring-1 ring-border-light">
        <Badge className={clsx('h-[62%] w-[62%]', meta.avatarText)} strokeWidth={2.2} />
      </span>
    </span>
  );
}
