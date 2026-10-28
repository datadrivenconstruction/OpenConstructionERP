// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CaseConstellation - the specialist and the modules they reach, as one comb.
//
// The case page used to say this in three places that never touched: a
// rectangular photo tile in the hero, a separate card lower down holding the
// module comb, and a meta row that listed the kinds of company as chips while
// a second comb below listed the same kinds of company again. A reader had to
// assemble "this person, working in these modules, for firms like mine" out of
// three blocks that shared no geometry and no adjacency.
//
// This is the hero half of the answer: the portrait becomes a cell, and the
// modules become the cells that TOUCH it. The drawing carries the claim - a
// module is attached to the case because it is attached to the face.
//
// SIX IS THE SHAPE, NOT A BUDGET. A flat-top hexagon has exactly six
// neighbours. Before this was written the catalogue was measured: the most
// modules any of the 202 cases walks through is six, and the spread is 1:2,
// 2:33, 3:86, 4:38, 5:34, 6:9. So the first ring holds every case there is,
// with nothing to truncate and no second ring to draw. `hiveRing` clamps at six
// rather than stacking a seventh cell on top of one of the first six, and the
// caption counts the modules the case actually declares, so a future seventh
// would show up as a caption that disagrees with the drawing instead of as a
// cell silently missing.
//
// WHY THE CELLS DO NOT QUITE TOUCH. Interlocking hexagons already read as
// adjacent, but adjacency alone is a weak claim: a comb of seven cells looks
// like a comb of seven cells, not like one subject and six things it reaches.
// Each cell is drawn slightly inside its slot and the gap that opens is where
// the spokes are drawn, from the middle of the face to the middle of every
// module. The connection is then something the page states rather than
// something the reader has to infer from packing.
//
// The portrait is cut to HEX_CELL_CLIP, not HEX_PORTRAIT_CLIP. Those are
// different hexagons and only the flat-top one tiles with the module cells; a
// pointy-top portrait dropped into this cluster would sit at a right angle to
// its own neighbours. That is a real cost - the portrait crop is the one this
// shape is worse at - so the face is positioned high in its box, the way the
// hero photo already was, and the cell is given the largest size on the page.

import type { ReactElement } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { Hexagon, type LucideProps } from 'lucide-react';
import type { ComponentType } from 'react';
import { getRouteIcon } from '@/app/layout/routeIcons';
import { HEX_CELL_CLIP, hiveRing } from '@/shared/lib/honeycomb';
import { accentFor, tintFor } from './categories';
import { CaseFacePhoto } from './CaseFacePhoto';
import type { CaseFace } from './caseFaces';
import { modulesForPlaybook } from './playbookModules';
import type { Playbook } from './types';

// The hub is drawn slightly PROUD of its slot and the spokes slightly inside
// theirs. Equal insets made a comb of seven equal cells, where the face read as
// one module among the modules; the subject of the drawing has to be the
// largest thing in it. The difference also opens the lane the spokes run in,
// so one number does both jobs.
/** How much of its slot a module cell fills. The rest is the spoke lane. */
const SPOKE_SCALE = 0.9;
/** How much of its slot the portrait fills. Over one, so it reads as the hub. */
const HUB_SCALE = 1.04;

export interface CaseConstellationProps {
  playbook: Playbook;
  /** The specialist portrait this case already wears in the catalogue. */
  face: CaseFace | null;
  /** Jump to the first step that opens this module. */
  onSelect?: (route: string) => void;
  /** Cell width in pixels. The hero uses a large cell; smaller callers can ask
   *  for less without the geometry changing shape. */
  cellWidth?: number;
}

/**
 * The case as a cluster: the person at the centre, the modules around them.
 *
 * Renders nothing when the case reaches no module, so a case with a face but no
 * route falls back to whatever the caller draws instead, rather than to a lone
 * hexagon that would read as a cluster which had failed to load.
 */
export function CaseConstellation({
  playbook,
  face,
  onSelect,
  cellWidth = 96,
}: CaseConstellationProps): ReactElement | null {
  const { t } = useTranslation();
  const modules = modulesForPlaybook(playbook);
  if (modules.length === 0) return null;

  const tint = tintFor(playbook.category);
  const accent = accentFor(playbook.category);
  const layout = hiveRing(modules.length, cellWidth);
  const spokeInset = Math.round((layout.cellWidth * (1 - SPOKE_SCALE)) / 2);
  const spokeWidth = layout.cellWidth - spokeInset * 2;
  const spokeHeight = layout.cellHeight - Math.round((layout.cellHeight * (1 - SPOKE_SCALE)));
  const hubWidth = Math.round(layout.cellWidth * HUB_SCALE);
  const hubHeight = Math.round(layout.cellHeight * HUB_SCALE);
  const hubInset = Math.round((layout.cellWidth - hubWidth) / 2);
  const hubInsetY = Math.round((layout.cellHeight - hubHeight) / 2);
  const iconSize = Math.max(13, Math.round(cellWidth * 0.19));

  const heading = t('cases.hive.title', {
    defaultValue: 'Modules this case walks through',
  });
  const count = t('cases.hive.count', {
    defaultValue: '{{count}} module',
    defaultValue_other: '{{count}} modules',
    count: modules.length,
  });

  // Centre of a slot, for the spoke geometry. Measured on the full slot rather
  // than the drawn cell, so the lines stay on the axis between two cells no
  // matter how the inset above is tuned.
  const centre = (p: { inlineStart: number; top: number }) => ({
    x: p.inlineStart + layout.cellWidth / 2,
    y: p.top + layout.cellHeight / 2,
  });
  const hub = centre(layout.hub);

  return (
    <figure className="m-0 flex flex-col items-center gap-2">
      <div
        className="relative"
        style={{ width: layout.width, height: layout.height }}
      >
        {/* The spokes. Decorative: the list below the drawing is what a screen
            reader is given, so this layer is out of the accessible tree. It is
            mirrored under rtl with the cluster, because the placements above
            are inline-start offsets and the SVG is not. */}
        <svg
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rtl:-scale-x-100"
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          fill="none"
        >
          {layout.spokes.map((slot, i) => {
            const end = centre(slot);
            return (
              <line
                key={modules[i]?.route ?? i}
                x1={hub.x}
                y1={hub.y}
                x2={end.x}
                y2={end.y}
                stroke={accent.base}
                strokeWidth={2}
                strokeLinecap="round"
                opacity={0.35}
              />
            );
          })}
          <circle cx={hub.x} cy={hub.y} r={3} fill={accent.base} opacity={0.55} />
        </svg>

        {/* The face. A cell, not a tile: same clip and same slot geometry as
            the modules, so the cluster is one drawing rather than a photo with
            hexagons arranged near it. */}
        <div
          className="absolute"
          style={{
            insetInlineStart: layout.hub.inlineStart + hubInset,
            top: layout.hub.top + hubInsetY,
            width: hubWidth,
            height: hubHeight,
          }}
        >
          <span
            className="relative block h-full w-full bg-slate-200"
            style={{ clipPath: HEX_CELL_CLIP }}
          >
            {face ? (
              <CaseFacePhoto
                face={face}
                className="h-full w-full object-cover object-[50%_24%] contrast-[1.06] saturate-[1.04]"
              />
            ) : (
              // No portrait dealt for this case: the cell keeps the cluster
              // whole in the discipline colour rather than opening a hole in
              // the middle of it.
              <span className={clsx('block h-full w-full', tint.tile)} />
            )}
            {/* The photograph was first tied to the drawing with a multiply
                wash in the case colour. On a dark portrait multiply has nothing
                to lighten and the face went to mud, which is the opposite of
                what the hub is for. The tie is now an edge instead of a film:
                a hairline of the case colour just inside the cut, which reads
                on a light photograph and on a dark one alike and takes nothing
                off the face. */}
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-0"
              style={{
                clipPath: HEX_CELL_CLIP,
                boxShadow: `inset 0 0 0 2px ${accent.base}`,
                opacity: 0.5,
              }}
            />
          </span>
        </div>

        {/* The modules. A list, because that is what it is, and the only place
            on the page where the whole reach of the case is visible at once. */}
        <ul aria-label={heading} className="contents">
          {layout.spokes.map((slot, i) => {
            const module = modules[i];
            if (!module) return null;
            const label = module.labelKey
              ? t(module.labelKey, { defaultValue: module.label })
              : module.label;
            const Icon: ComponentType<LucideProps> = getRouteIcon(module.route) ?? Hexagon;
            const face_ = (
              <span
                className={clsx(
                  'relative flex h-full w-full flex-col items-center justify-center gap-1 text-center',
                  tint.tile,
                  onSelect &&
                    'transition duration-150 group-hover:brightness-[1.04] group-hover:saturate-125',
                )}
                style={{ clipPath: HEX_CELL_CLIP, paddingInline: '15%' }}
              >
                {/* Depth without a shadow, which a clip path cuts off: a soft
                    highlight down from the top edge, so the cell reads as a
                    face catching light rather than as a flat patch of colour. */}
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 bg-gradient-to-b from-white/55 via-white/5 to-transparent"
                />
                <Icon size={iconSize} strokeWidth={1.9} aria-hidden="true" className="relative" />
                <span className="relative line-clamp-2 text-2xs font-semibold leading-tight">
                  {label}
                </span>
              </span>
            );
            return (
              <li
                key={module.route}
                className="absolute"
                style={{
                  insetInlineStart: slot.inlineStart + spokeInset,
                  top: slot.top + Math.round((layout.cellHeight - spokeHeight) / 2),
                  width: spokeWidth,
                  height: spokeHeight,
                }}
              >
                {onSelect ? (
                  <button
                    type="button"
                    onClick={() => onSelect(module.route)}
                    title={label}
                    className="group block h-full w-full rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60"
                  >
                    {face_}
                  </button>
                ) : (
                  <span className="block h-full w-full" title={label}>
                    {face_}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      <figcaption className="text-center">
        <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
          {heading}
        </p>
        <p className="text-xs text-content-tertiary">{count}</p>
      </figcaption>
    </figure>
  );
}
