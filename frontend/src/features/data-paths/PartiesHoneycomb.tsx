// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The people around the data: a honeycomb of the project's parties in three
// zones (client side, contractors and suppliers, specialists and consultants).
// One hex per organisation, coloured by its strongest role and clustered by
// role; the people who work for it sit next to it as round avatars. Every mark
// is a monogram from the app's own data, never a photo. Hovering or focusing a
// mark shows who it is, its roles and the records it has in the modules on
// screen; a module selected on the map lights its parties here. A list under
// the comb says the same thing in words.

import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import type { Party, PartyZone } from './api';
import { humanize, moduleLabel } from './flowModel';

const ZONES: PartyZone[] = ['client', 'delivery', 'specialist'];

const ZONE_KEYS: Record<PartyZone, [string, string]> = {
  client: ['data_paths.zone_client', 'Client side'],
  delivery: ['data_paths.zone_delivery', 'Contractors and suppliers'],
  specialist: ['data_paths.zone_specialist', 'Specialists and consultants'],
};

/** Hex colour by role, in the order clusters are drawn. */
export const CATEGORIES = ['client', 'contractor', 'subcontractor', 'supplier', 'bidder', 'consultant', 'person'] as const;
export type Category = (typeof CATEGORIES)[number];

export const CATEGORY_TONE: Record<Category, string> = {
  client: 'var(--oe-tone-0)',
  contractor: 'var(--oe-tone-4)',
  subcontractor: 'var(--oe-tone-3)',
  supplier: 'var(--oe-tone-5)',
  bidder: 'var(--oe-tone-2)',
  consultant: 'var(--oe-tone-6)',
  person: 'var(--oe-text-tertiary)',
};

const ROLE_CATEGORY: Record<string, Category> = {
  client: 'client',
  owner: 'client',
  contractor: 'contractor',
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

export function partyCategory(p: Party): Category {
  if (p.primary_role && (CATEGORIES as readonly string[]).includes(p.primary_role)) return p.primary_role as Category;
  if (p.kind === 'person') return 'person';
  for (const c of CATEGORIES) if (p.roles.some((r) => ROLE_CATEGORY[r] === c)) return c;
  return 'contractor';
}

const R = 26; // hex circumradius
const HW = Math.sqrt(3) * R; // hex width
const PER_ROW = 4;
const CLUSTER_GAP = 8;

function hexPoints(cx: number, cy: number, r: number): string {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 180) * (60 * i - 30);
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  }).join(' ');
}

interface Cell {
  party: Party;
  category: Category;
  x: number;
  y: number;
}

/** Clusters by role inside a zone, each starting on its own row; people follow their company. */
function placeZone(list: Party[]): { cells: Cell[]; height: number } {
  const ids = new Set(list.map((p) => p.id));
  const staff = new Map<string, Party[]>();
  const loose: Party[] = [];
  const orgs: Party[] = [];
  for (const p of list) {
    if (p.kind === 'person') {
      if (p.org && ids.has(p.org)) staff.set(p.org, [...(staff.get(p.org) ?? []), p]);
      else loose.push(p);
    } else orgs.push(p);
  }
  const clusters: Party[][] = [];
  for (const c of CATEGORIES) {
    const members = orgs.filter((p) => partyCategory(p) === c);
    if (members.length) clusters.push(members.flatMap((o) => [o, ...(staff.get(o.id) ?? [])]));
  }
  if (loose.length) clusters.push(loose);
  const cells: Cell[] = [];
  let row = -1;
  let y = R - R * 1.5;
  clusters.forEach((cluster, ci) => {
    cluster.forEach((party, i) => {
      if (i % PER_ROW === 0) {
        row += 1;
        y += R * 1.5 + (i === 0 && ci > 0 ? CLUSTER_GAP : 0);
      }
      const col = i % PER_ROW;
      cells.push({ party, category: partyCategory(party), x: HW / 2 + col * HW + (row % 2 ? HW / 2 : 0), y });
    });
  });
  return { cells, height: cells.length ? y + R + 2 : 0 };
}

export interface PartiesHoneycombProps {
  parties: Party[];
  /** Modules lit on the map; parties working in them light up. */
  litModules?: Set<string> | null;
  /** Modules on screen (a module and its neighbours); the hover card counts records in these. */
  pathModules?: Set<string> | null;
  onHoverParty?: (modules: string[] | null) => void;
  onSelectParty?: (party: Party) => void;
  compact?: boolean;
  /** Zones stacked with the name list in two columns (the drawer); otherwise zones sit side by side. */
  wideList?: boolean;
}

export function partyRoleText(t: (k: string, o?: Record<string, unknown>) => unknown, roles: string[]): string {
  return roles.map((r) => String(t(`data_paths.role_${r}`, { defaultValue: humanize(r) }))).join(', ');
}

function categoryLabel(t: (k: string, o?: Record<string, unknown>) => unknown, c: Category): string {
  if (c === 'person') return String(t('data_paths.legend_people', { defaultValue: 'People' }));
  return String(t(`data_paths.role_${c}`, { defaultValue: humanize(c) }));
}

function RoleChips({ party }: { party: Party }) {
  const { t } = useTranslation();
  return (
    <span className="flex flex-wrap gap-1">
      {party.roles.map((r) => {
        const tone = CATEGORY_TONE[ROLE_CATEGORY[r] ?? (party.kind === 'person' ? 'person' : 'contractor')];
        return (
          <span
            key={r}
            className="rounded-full px-1.5 py-px text-2xs font-medium text-content-secondary"
            style={{ background: `color-mix(in srgb, ${tone} 18%, transparent)` }}
          >
            {String(t(`data_paths.role_${r}`, { defaultValue: humanize(r) }))}
          </span>
        );
      })}
    </span>
  );
}

export function PartiesHoneycomb({
  parties,
  litModules,
  pathModules,
  onHoverParty,
  onSelectParty,
  compact,
  wideList,
}: PartiesHoneycombProps) {
  const { t } = useTranslation();
  const wrap = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ party: Party; x: number; y: number } | null>(null);
  const byZone = useMemo(() => {
    const out: Record<PartyZone, Party[]> = { client: [], delivery: [], specialist: [] };
    for (const p of parties) (out[p.zone] ?? out.delivery).push(p);
    return out;
  }, [parties]);
  const onlyPlaceholders = parties.length > 0 && parties.every((p) => p.placeholder);
  const legend = useMemo(() => {
    const n = new Map<Category, number>();
    for (const p of parties) if (!p.placeholder) n.set(partyCategory(p), (n.get(partyCategory(p)) ?? 0) + 1);
    return CATEGORIES.filter((c) => n.has(c)).map((c) => ({ c, n: n.get(c) ?? 0 }));
  }, [parties]);
  const nameOf = useMemo(() => new Map(parties.map((p) => [p.id, p.name])), [parties]);

  const show = (party: Party, el: Element) => {
    onHoverParty?.(party.modules);
    const box = wrap.current?.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (box) setTip({ party, x: r.left - box.left + r.width / 2, y: r.bottom - box.top + 4 });
  };
  const hide = () => {
    onHoverParty?.(null);
    setTip(null);
  };

  return (
    <div ref={wrap} className="relative space-y-3" data-testid="dp-honeycomb">
      {onlyPlaceholders && (
        <p className="text-xs text-content-tertiary">
          {t('data_paths.parties_placeholder_note', {
            defaultValue: 'No people or companies are linked to this project yet. These are the roles that usually work here.',
          })}
        </p>
      )}
      {legend.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-2xs text-content-secondary" aria-label={t('data_paths.legend_aria', { defaultValue: 'Colours by role' })}>
          {legend.map(({ c, n }) => (
            <li key={c} className="flex items-center gap-1">
              <span
                className={clsx('h-2.5 w-2.5', c === 'person' ? 'rounded-full' : 'rounded-sm')}
                style={{ background: CATEGORY_TONE[c] }}
                aria-hidden
              />
              {categoryLabel(t, c)}
              <span className="tabular-nums text-content-tertiary">{n}</span>
            </li>
          ))}
        </ul>
      )}
      <div className={clsx('grid gap-4', wideList ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-3')}>
        {ZONES.map((zone) => {
          const list = byZone[zone];
          const { cells, height } = placeZone(list);
          const w = HW * PER_ROW + HW / 2;
          const [zk, zdef] = ZONE_KEYS[zone];
          const zoneLabel = String(t(zk, { defaultValue: zdef }));
          const real = list.filter((p) => !p.placeholder);
          return (
            <section key={zone} aria-label={zoneLabel} className="min-w-0">
              <h4 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                {zoneLabel} <span className="tabular-nums">· {real.length}</span>
              </h4>
              {list.length === 0 ? (
                <p className="text-xs text-content-quaternary">{t('data_paths.zone_empty', { defaultValue: 'Nobody here yet' })}</p>
              ) : (
                <svg viewBox={`0 0 ${w} ${height}`} width="100%" style={{ maxWidth: w }} className="overflow-visible">
                  {cells.map(({ party: p, category, x, y }) => {
                    const lit = !!litModules && p.modules.some((m) => litModules.has(m));
                    const dim = !!litModules && !lit;
                    const tone = CATEGORY_TONE[category];
                    const person = p.kind === 'person';
                    const roleText = partyRoleText(t, p.roles);
                    const aria = [p.placeholder ? roleText : p.name, p.placeholder ? '' : roleText].filter(Boolean).join('. ');
                    return (
                      <g
                        key={p.id}
                        role="button"
                        tabIndex={0}
                        aria-label={aria}
                        className="cursor-pointer outline-none transition-opacity duration-150 focus-visible:[&>*:first-child]:stroke-oe-blue"
                        opacity={dim ? 0.3 : 1}
                        onMouseEnter={(e) => show(p, e.currentTarget)}
                        onMouseLeave={hide}
                        onFocus={(e) => show(p, e.currentTarget)}
                        onBlur={hide}
                        onClick={() => onSelectParty?.(p)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onSelectParty?.(p);
                          }
                        }}
                        data-testid={p.placeholder ? 'dp-hex-placeholder' : person ? 'dp-avatar' : 'dp-hex'}
                      >
                        {person ? (
                          <circle
                            cx={x}
                            cy={y}
                            r={R * 0.66}
                            fill={tone}
                            fillOpacity={lit ? 0.3 : 0.12}
                            stroke={p.org ? CATEGORY_TONE[partyCategory(parties.find((o) => o.id === p.org) ?? p)] : tone}
                            strokeWidth={lit ? 2.5 : 1.5}
                          />
                        ) : (
                          <polygon
                            points={hexPoints(x, y, R - 2)}
                            fill={p.placeholder ? 'transparent' : tone}
                            fillOpacity={p.placeholder ? 0 : lit ? 0.42 : 0.24}
                            stroke={tone}
                            strokeWidth={lit ? 2.5 : 1.25}
                            strokeDasharray={p.placeholder ? '4 3' : undefined}
                          />
                        )}
                        <text
                          x={x}
                          y={y + 3.5}
                          textAnchor="middle"
                          className={clsx(
                            'select-none font-semibold',
                            p.initials.length > 2 ? 'text-[9px]' : 'text-2xs',
                            p.placeholder ? 'fill-content-tertiary' : 'fill-content-primary',
                          )}
                        >
                          {p.initials}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
              {compact && real.length > 0 && (
                // In a side panel the monograms alone do not say who someone is.
                <ul className={clsx('mt-2 grid grid-cols-1 gap-x-4 gap-y-1.5', wideList && 'sm:grid-cols-2')} aria-hidden>
                  {real.map((p) => {
                    const lit = !!litModules && p.modules.some((m) => litModules.has(m));
                    return (
                      <li key={p.id} className={clsx('flex min-w-0 items-start gap-2 text-xs', litModules && !lit && 'opacity-50')}>
                        <span className="w-8 shrink-0 pt-px font-semibold text-content-tertiary">{p.initials}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-content-primary" title={p.name}>
                            {p.name}
                            {p.org && nameOf.get(p.org) ? <span className="text-content-tertiary"> · {nameOf.get(p.org)}</span> : null}
                          </span>
                          <RoleChips party={p} />
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      {tip && <PartyCard party={tip.party} x={tip.x} y={tip.y} pathModules={pathModules ?? null} width={wrap.current?.clientWidth ?? 0} />}
      <ul className="sr-only">
        {parties.map((p) => (
          <li key={p.id}>
            {p.placeholder ? partyRoleText(t, p.roles) : `${p.name}: ${partyRoleText(t, p.roles)}`}
            {p.modules.length ? ` (${p.modules.map((m) => moduleLabel(t, m)).join(', ')})` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PartyCard({ party, x, y, pathModules, width }: { party: Party; x: number; y: number; pathModules: Set<string> | null; width: number }) {
  const { t } = useTranslation();
  const CARD_W = 240;
  const touches = Object.entries(party.touches ?? {})
    .filter(([m]) => !pathModules || pathModules.has(m))
    .sort((a, b) => b[1] - a[1]);
  const left = Math.max(0, Math.min(x - CARD_W / 2, width - CARD_W));
  return (
    <div
      className="pointer-events-none absolute z-20 rounded-lg border border-border-light bg-surface-primary p-2.5 text-xs shadow-lg"
      style={{ left, top: y, width: CARD_W }}
      role="tooltip"
      data-testid="dp-party-card"
    >
      <p className="font-semibold text-content-primary">{party.placeholder ? partyRoleText(t, party.roles) : party.name}</p>
      {!party.placeholder && (
        <div className="mt-1">
          <RoleChips party={party} />
        </div>
      )}
      {touches.length > 0 ? (
        <>
          <p className="mt-2 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {pathModules
              ? t('data_paths.party_touches_path', { defaultValue: 'Records on this path' })
              : t('data_paths.party_touches', { defaultValue: 'Records on this project' })}
          </p>
          <ul className="mt-0.5 space-y-0.5">
            {touches.map(([m, n]) => (
              <li key={m} className="flex justify-between gap-2">
                <span className="truncate text-content-secondary">{moduleLabel(t, m)}</span>
                <span className="tabular-nums font-medium text-content-primary">{n}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        !party.placeholder && (
          <p className="mt-2 text-content-tertiary">
            {pathModules
              ? t('data_paths.party_no_touches_path', { defaultValue: 'No records on this path' })
              : t('data_paths.party_no_touches', { defaultValue: 'No records yet' })}
          </p>
        )
      )}
    </div>
  );
}
