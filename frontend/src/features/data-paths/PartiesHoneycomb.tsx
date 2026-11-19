// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The people around the data: a honeycomb of the project's parties in three
// zones (client side, contractors and suppliers, specialists and consultants).
// Every hex is an initials monogram from the app's own data, never a photo.
// Hovering or focusing a hex reports its modules so the map can light them;
// a module selected on the map lights its parties here. Each hex is a button,
// and a list under the comb says the same thing in words.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import type { Party, PartyZone } from './api';
import { humanize, moduleLabel } from './flowModel';

const ZONES: PartyZone[] = ['client', 'delivery', 'specialist'];

const ZONE_TONE: Record<PartyZone, string> = {
  client: 'var(--oe-tone-1)',
  delivery: 'var(--oe-tone-4)',
  specialist: 'var(--oe-tone-6)',
};

const ZONE_KEYS: Record<PartyZone, [string, string]> = {
  client: ['data_paths.zone_client', 'Client side'],
  delivery: ['data_paths.zone_delivery', 'Contractors and suppliers'],
  specialist: ['data_paths.zone_specialist', 'Specialists and consultants'],
};

const R = 26; // hex circumradius
const HW = Math.sqrt(3) * R; // hex width
const PER_ROW = 4;

function hexPoints(cx: number, cy: number, r: number): string {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 180) * (60 * i - 30);
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  }).join(' ');
}

function cell(i: number): { x: number; y: number } {
  const row = Math.floor(i / PER_ROW);
  const col = i % PER_ROW;
  return { x: HW / 2 + col * HW + (row % 2 ? HW / 2 : 0), y: R + row * R * 1.5 };
}

export interface PartiesHoneycombProps {
  parties: Party[];
  /** Modules lit on the map; parties working in them light up. */
  litModules?: Set<string> | null;
  onHoverParty?: (modules: string[] | null) => void;
  onSelectParty?: (party: Party) => void;
  compact?: boolean;
  /** Room for the name list in two columns (the drawer); the map sidebar keeps one. */
  wideList?: boolean;
}

export function partyRoleText(t: (k: string, o?: Record<string, unknown>) => unknown, roles: string[]): string {
  return roles.map((r) => String(t(`data_paths.role_${r}`, { defaultValue: humanize(r) }))).join(', ');
}

export function PartiesHoneycomb({ parties, litModules, onHoverParty, onSelectParty, compact, wideList }: PartiesHoneycombProps) {
  const { t } = useTranslation();
  const byZone = useMemo(() => {
    const out: Record<PartyZone, Party[]> = { client: [], delivery: [], specialist: [] };
    for (const p of parties) (out[p.zone] ?? out.delivery).push(p);
    return out;
  }, [parties]);
  const onlyPlaceholders = parties.length > 0 && parties.every((p) => p.placeholder);

  return (
    <div className="space-y-3" data-testid="dp-honeycomb">
      {onlyPlaceholders && (
        <p className="text-xs text-content-tertiary">
          {t('data_paths.parties_placeholder_note', {
            defaultValue: 'No people or companies are linked to this project yet. These are the roles that usually work here.',
          })}
        </p>
      )}
      <div className={clsx('grid gap-4', compact ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-3')}>
        {ZONES.map((zone) => {
          const list = byZone[zone];
          const rows = Math.max(1, Math.ceil(list.length / PER_ROW));
          const w = HW * PER_ROW + HW / 2;
          const h = R * 2 + (rows - 1) * R * 1.5 + 2;
          const [zk, zdef] = ZONE_KEYS[zone];
          const zoneLabel = String(t(zk, { defaultValue: zdef }));
          return (
            <section key={zone} aria-label={zoneLabel} className="min-w-0">
              <h4 className="mb-1.5 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                <span className="h-2 w-2 rounded-full" style={{ background: ZONE_TONE[zone] }} aria-hidden />
                {zoneLabel}
                <span className="tabular-nums">· {list.filter((p) => !p.placeholder).length}</span>
              </h4>
              {list.length === 0 ? (
                <p className="text-xs text-content-quaternary">{t('data_paths.zone_empty', { defaultValue: 'Nobody here yet' })}</p>
              ) : (
                <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ maxWidth: w }} className="overflow-visible">
                  {list.map((p, i) => {
                    const { x, y } = cell(i);
                    const lit = !!litModules && p.modules.some((m) => litModules.has(m));
                    const dim = !!litModules && !lit;
                    const roleText = partyRoleText(t, p.roles);
                    const where = p.modules.map((m) => moduleLabel(t, m)).join(', ');
                    const aria = [p.placeholder ? roleText : p.name, p.placeholder ? '' : roleText, where].filter(Boolean).join('. ');
                    return (
                      <g
                        key={p.id}
                        role="button"
                        tabIndex={0}
                        aria-label={aria}
                        className="cursor-pointer outline-none transition-opacity duration-150 focus-visible:[&>polygon]:stroke-oe-blue"
                        opacity={dim ? 0.3 : 1}
                        onMouseEnter={() => onHoverParty?.(p.modules)}
                        onMouseLeave={() => onHoverParty?.(null)}
                        onFocus={() => onHoverParty?.(p.modules)}
                        onBlur={() => onHoverParty?.(null)}
                        onClick={() => onSelectParty?.(p)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onSelectParty?.(p);
                          }
                        }}
                        data-testid={p.placeholder ? 'dp-hex-placeholder' : 'dp-hex'}
                      >
                        <title>{aria}</title>
                        <polygon
                          points={hexPoints(x, y, R - 2)}
                          fill={p.placeholder ? 'transparent' : ZONE_TONE[zone]}
                          fillOpacity={p.placeholder ? 0 : lit ? 0.32 : 0.16}
                          stroke={ZONE_TONE[zone]}
                          strokeWidth={lit ? 2.5 : 1.25}
                          strokeDasharray={p.placeholder ? '4 3' : undefined}
                        />
                        <text
                          x={x}
                          y={y + 4}
                          textAnchor="middle"
                          className={clsx('select-none text-2xs font-semibold', p.placeholder ? 'fill-content-tertiary' : 'fill-content-primary')}
                        >
                          {p.initials}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
              {compact && list.some((p) => !p.placeholder) && (
                // In the drawer the initials alone do not say who someone is.
                <ul className={clsx('mt-2 grid grid-cols-1 gap-x-4 gap-y-1', wideList && 'sm:grid-cols-2')} aria-hidden>
                  {list
                    .filter((p) => !p.placeholder)
                    .map((p) => {
                      const lit = !!litModules && p.modules.some((m) => litModules.has(m));
                      return (
                        <li
                          key={p.id}
                          className={clsx('flex min-w-0 items-baseline gap-2 text-xs', litModules && !lit && 'opacity-50')}
                        >
                          <span className="w-6 shrink-0 font-semibold text-content-tertiary">{p.initials}</span>
                          <span className="min-w-0 flex-1 truncate text-content-primary" title={p.name}>
                            {p.name}
                          </span>
                          <span className="max-w-[45%] shrink-0 truncate text-content-tertiary">{partyRoleText(t, p.roles)}</span>
                        </li>
                      );
                    })}
                </ul>
              )}
            </section>
          );
        })}
      </div>
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
