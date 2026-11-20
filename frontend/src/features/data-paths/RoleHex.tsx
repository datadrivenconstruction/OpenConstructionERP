// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A role as a small shaded hex (lit top face, darker sides) with its
// abbreviation, coloured like the role's category in the parties honeycomb.
// The abbreviation is taken from the translated role name, so it reads right
// in every language without a second set of keys.

import { useTranslation } from 'react-i18next';

import { CATEGORY_TONE, type Category } from './PartiesHoneycomb';
import { humanize } from './flowModel';

const ROLE_CATEGORY: Record<string, Category> = {
  client: 'client',
  owner: 'client',
  contractor: 'contractor',
  project_manager: 'contractor',
  estimator: 'contractor',
  buyer: 'contractor',
  site_manager: 'contractor',
  planner: 'contractor',
  quantity_surveyor: 'contractor',
  accountant: 'contractor',
  subcontractor: 'subcontractor',
  supplier: 'supplier',
  bidder: 'bidder',
  engineer: 'consultant',
  architect: 'consultant',
  inspector: 'consultant',
  surveyor: 'consultant',
  consultant: 'consultant',
  authority: 'consultant',
};

export function roleTone(role: string): string {
  return CATEGORY_TONE[ROLE_CATEGORY[role] ?? 'person'];
}

/** First letters of the first two words, or the first two letters of one word. */
export function abbreviate(name: string): string {
  const words = name.trim().split(/[\s/_-]+/u).filter(Boolean);
  if (words.length >= 2) return `${[...words[0]!][0] ?? ''}${[...words[1]!][0] ?? ''}`.toUpperCase();
  return [...(words[0] ?? '')].slice(0, 2).join('').toUpperCase();
}

export function roleName(t: (k: string, o?: Record<string, unknown>) => unknown, role: string): string {
  return String(t(`data_paths.role_${role}`, { defaultValue: humanize(role) }));
}

export function RoleHex({ role, size = 20, onClick }: { role: string; size?: number; onClick?: () => void }) {
  const { t } = useTranslation();
  const name = roleName(t, role);
  const tone = roleTone(role);
  const w = size;
  const h = size * 1.08;
  const hex = `${w / 2},0 ${w},${h * 0.25} ${w},${h * 0.75} ${w / 2},${h} 0,${h * 0.75} 0,${h * 0.25}`;
  const top = `${w / 2},0 ${w},${h * 0.25} ${w / 2},${h * 0.5} 0,${h * 0.25}`;
  const right = `${w},${h * 0.25} ${w},${h * 0.75} ${w / 2},${h} ${w / 2},${h * 0.5}`;
  const body = (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden className="block drop-shadow-sm">
      <polygon points={hex} fill={tone} />
      <polygon points={top} fill="white" opacity={0.28} />
      <polygon points={right} fill="black" opacity={0.16} />
      <text
        x={w / 2}
        y={h * 0.68}
        textAnchor="middle"
        fontSize={size * 0.38}
        fontWeight={600}
        fill="white"
        style={{ fontFamily: 'inherit' }}
      >
        {abbreviate(name)}
      </text>
    </svg>
  );
  if (!onClick) {
    return (
      <span title={name} className="inline-flex" data-testid="dp-role-hex">
        {body}
        <span className="sr-only">{name}</span>
      </span>
    );
  }
  return (
    <button
      type="button"
      title={name}
      aria-label={name}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="nodrag inline-flex rounded transition-transform duration-150 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue motion-reduce:transition-none"
      data-testid="dp-role-hex"
    >
      {body}
    </button>
  );
}
