// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The honeycomb, in the product: one renderer, and the adapters that feed it.
//
// The public case pages have drawn this for a while: the modules a case walks
// through, as interlocking hexagons rather than another list of chips. The
// product had the honeycomb only as a shape it cut portraits to. This is the
// component itself.
//
// ONE COMB, TWO SUBJECTS. `Hive` below knows about hexagons and nothing else:
// cells, a band, a tint, an optional activation. `ModuleHive` adapts a case's
// modules to it (routes, icons from the route map); `CaseCompanyHive` in
// CompanyHive.tsx adapts the kinds of company a case is written for. A second
// comb copied for the second subject would have drifted from this one within a
// release - the two are the same drawing with different cargo, so only the
// cargo differs here.
//
// WHAT IT SAYS. One cell per thing the case actually declares, in the order
// the case reaches them, named with the same words the rest of the page uses.
// The hive is CONTENT: it is the only place a reader can see the whole span of
// a case at once, so the names are real text in the accessible tree and only
// the drawing around them is hidden from it.
//
// WHAT IT DOES NOT SAY. The public pages surround a case's modules with ghost
// cells for "the platform's other modules" and print "6 of 117". We do not.
// There is no module census in this tree to count against - the sidebar
// catalogue is nav rows behind role and mode gating, not a list of modules -
// so any denominator here would be a number somebody chose. The count of a
// case's own modules is a fact; the fraction would be decoration wearing the
// costume of one. Company types are a closed union and DO have a census, but
// it buys a number for the caption, not a comb of greyed-out cells: a cell
// nobody can act on reads as disabled, which is a worse answer than absent.

import type { ComponentType, ReactElement } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { Hexagon, type LucideProps } from 'lucide-react';
import { getRouteIcon } from '@/app/layout/routeIcons';
import { HEX_CELL_CLIP, hiveBand } from '@/shared/lib/honeycomb';
import type { CategoryTint } from './categories';
import { NEUTRAL_TINT, tintFor } from './categories';
import { modulesForPlaybook } from './playbookModules';
import type { Playbook } from './types';

/** One hexagon, already translated by the caller. */
export interface HiveCell {
  /** Identity, React key, and what `onSelect` is handed. */
  id: string;
  /** The cell's name in the reader's language. */
  label: string;
  /** Glyph inside the cell. Falls back to the comb's own shape, so a cell
   *  whose subject has no glyph reads as a cell rather than as a fault. */
  icon?: ComponentType<LucideProps>;
  /** Overrides the hive's tint for this one cell. Modules share a case's
   *  discipline colour; company types each carry their own. */
  tint?: CategoryTint;
  /** Photograph washed behind the face. Decorative - the label carries the
   *  meaning - so it is hidden from the accessible tree. */
  image?: string;
  /** Draw the "there is work in flight here" mark. `markLabel` names it. */
  marked?: boolean;
  /** What activating this cell DOES, as a sentence, for the accessible name.
   *
   *  Only read when the hive is given an `onSelect`, because only then is
   *  there anything to do. The drawing still shows the name alone: a band of
   *  eight cells that each spelled out their own verb would read as eight
   *  sentences to the eye, and as eight bare nouns to a screen reader if the
   *  verb were dropped instead. This is the seam where those two want
   *  different words, so it is the one place they are allowed to differ. */
  actionLabel?: string;
}

export interface HiveProps {
  cells: HiveCell[];
  /** Accessible name for the hive, e.g. "Modules this case walks through". */
  label: string;
  /** Tint for every cell that does not carry its own. Defaults to neutral. */
  tint?: CategoryTint;
  /** Cell width in pixels. Bigger cells fit longer names. */
  cellWidth?: number;
  /** How many cells deep the band runs before starting a new column. */
  rows?: number;
  /** Activating a cell. When omitted the cells are inert text, not dead
   *  buttons: a hexagon that looks pressable and does nothing is worse than
   *  one that never claimed to be. */
  onSelect?: (id: string) => void;
  /** What the mark means, in words. Colour alone cannot carry it. */
  markLabel?: string;
  /** Draw the glyph alone, without the name under it.
   *
   *  For cells too small to hold a readable name. Nothing is lost to a screen
   *  reader or a pointer: the name still rides `title` on the cell and the
   *  hive still carries its own `label`, so this hides the name from the
   *  drawing and from nothing else. A name set at a size nobody can read is
   *  worse than no name, because it spends the room and reads as noise. */
  iconOnly?: boolean;
}

/**
 * The honeycomb itself. Positions are baked from {@link hiveBand} at render
 * time, so there is no measurement pass and nothing recomputes on resize; the
 * stage scrolls inside its own box rather than pushing the page sideways.
 */
export function Hive({
  cells,
  label,
  tint = NEUTRAL_TINT,
  cellWidth = 82,
  rows = 2,
  onSelect,
  markLabel,
  iconOnly = false,
}: HiveProps): ReactElement | null {
  if (cells.length === 0) return null;
  const layout = hiveBand(cells.length, cellWidth, rows);
  // The glyph carries the whole cell when the name is not drawn, so it takes
  // the room the name would have used rather than floating in an empty hexagon.
  const iconSize = Math.max(12, Math.round(cellWidth * (iconOnly ? 0.42 : 0.2)));
  // The label rides the cell, not a fixed step. At the small dashboard size the
  // smallest type is the only one that fits two lines inside the hexagon; at the
  // case-page size it looks starved, and a name a reader has to lean in for is
  // the reason the block was a list of chips before it was a comb.
  const labelClass = cellWidth >= 96 ? 'text-xs' : 'text-2xs';

  return (
    <div className="max-w-full overflow-x-auto pb-1">
      <ul
        aria-label={label}
        className="relative"
        style={{ width: layout.width, height: layout.height }}
      >
        {cells.map((cell, i) => {
          const place = layout.placements[i]!;
          const Icon = cell.icon ?? Hexagon;
          const cellTint = cell.tint ?? tint;
          const face = (
            <span
              className={clsx(
                'relative flex h-full w-full flex-col items-center justify-center gap-0.5 text-center',
                cellTint.tile,
                onSelect && 'transition-transform duration-150 group-hover:scale-105',
              )}
              // The face is the hexagon. Everything inside it is upright text,
              // so the label never rides the angled edge.
              style={{ clipPath: HEX_CELL_CLIP, paddingInline: '16%' }}
            >
              {/* The subject's own photograph, washed back far enough that the
                  glyph and the name still carry. Positioned, and drawn before
                  the content, so the two lines below paint over it. */}
              {cell.image && (
                <img
                  src={cell.image}
                  alt=""
                  aria-hidden="true"
                  loading="lazy"
                  decoding="async"
                  draggable={false}
                  className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-25"
                />
              )}
              <Icon size={iconSize} strokeWidth={1.9} aria-hidden="true" className="relative" />
              {/* Clamped for the drawing, whole in the DOM: a long German or
                  Finnish module name is cut visually but still read out in
                  full, and `title` gives it back to a pointer. */}
              {!iconOnly && (
                <span
                  className={clsx('relative line-clamp-2 font-semibold leading-tight', labelClass)}
                >
                  {cell.label}
                </span>
              )}
            </span>
          );
          return (
            <li
              key={cell.id}
              className="absolute"
              style={{
                // Inline-start, never left. Arabic, Hebrew, Persian and Urdu
                // read the band from the other edge and the whole comb has to
                // mirror with them.
                insetInlineStart: place.inlineStart,
                top: place.top,
                width: layout.cellWidth,
                height: layout.cellHeight,
              }}
            >
              <span className="relative block h-full w-full">
                {onSelect ? (
                  <button
                    type="button"
                    onClick={() => onSelect(cell.id)}
                    aria-label={cell.actionLabel}
                    title={cell.actionLabel ?? cell.label}
                    className="group block h-full w-full rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/60"
                  >
                    {face}
                  </button>
                ) : (
                  <span className="block h-full w-full" title={cell.label}>
                    {face}
                  </span>
                )}
                {cell.marked && (
                  <>
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute end-[18%] top-[6%] h-2 w-2 rounded-full bg-oe-blue ring-2 ring-surface-primary"
                    />
                    {markLabel && <span className="sr-only">{markLabel}</span>}
                  </>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** One hexagon: a module, already translated by the caller. */
export interface ModuleHiveCell {
  /** Unscoped route base for the module. Identity and React key. */
  route: string;
  /** The module's name in the reader's language. */
  label: string;
  /** Draw the "there is work in flight here" mark. `markLabel` names it. */
  marked?: boolean;
}

export interface ModuleHiveProps {
  cells: ModuleHiveCell[];
  /** Accessible name for the hive, e.g. "Modules this case walks through". */
  label: string;
  /** Discipline tint. Defaults to the neutral blue. */
  tint?: CategoryTint;
  /** Cell width in pixels. Bigger cells fit longer module names. */
  cellWidth?: number;
  /** How many cells deep the band runs before starting a new column. */
  rows?: number;
  /** Activating a cell hands back the module's route. */
  onSelect?: (route: string) => void;
  /** What the mark means, in words. Colour alone cannot carry it. */
  markLabel?: string;
}

/**
 * The comb of modules: {@link Hive} with the route map wired in.
 *
 * Icon resolution lives here rather than in `Hive` because it is the one thing
 * about these cells that is specifically about modules. Measured over the real
 * data: 3 of the 110 module routes the playbooks reach resolve to no icon, two
 * because they are alias routes that redirect to a canonical path the map is
 * keyed by, one because it has no route at all. A bare cell beside iconed
 * neighbours reads as a rendering fault rather than as a module nobody gave a
 * glyph, so an unmatched route falls back to the comb's own shape.
 */
export function ModuleHive({ cells, onSelect, ...rest }: ModuleHiveProps): ReactElement | null {
  return (
    <Hive
      cells={cells.map((cell) => ({
        id: cell.route,
        label: cell.label,
        icon: getRouteIcon(cell.route) ?? Hexagon,
        marked: cell.marked,
      }))}
      onSelect={onSelect}
      {...rest}
    />
  );
}

export interface CaseModuleHiveProps {
  playbook: Playbook;
  /** Jump to the first step that opens this module. */
  onSelect?: (route: string) => void;
}

/**
 * The hive for one case, on the case's own page: its modules, its discipline
 * tint, its count. One case per view, in flow, positions baked.
 */
export function CaseModuleHive({ playbook, onSelect }: CaseModuleHiveProps): ReactElement | null {
  const { t } = useTranslation();
  const modules = modulesForPlaybook(playbook);
  if (modules.length === 0) return null;
  const cells: ModuleHiveCell[] = modules.map((m) => ({
    route: m.route,
    label: m.labelKey ? t(m.labelKey, { defaultValue: m.label }) : m.label,
  }));
  const heading = t('cases.hive.title', {
    defaultValue: 'Modules this case walks through',
  });

  // The card hugs the comb instead of spanning the column. A band of four or
  // five cells left nine tenths of a full-width panel empty, which read as a
  // block that had failed to load rather than as a small, complete drawing.
  // Same reason the heading sits beside the comb on a wide screen rather than
  // above it: stacked, the two short lines were most of the panel's height.
  const rows = cells.length > 6 ? 2 : 1;

  return (
    <section
      aria-label={heading}
      className="w-fit max-w-full rounded-xl border border-border-light bg-surface-primary p-4"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
        <div className="min-w-0 sm:w-36 sm:shrink-0">
          <p className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            {heading}
          </p>
          <p className="text-xs text-content-tertiary">
            {t('cases.hive.count', {
              defaultValue: '{{count}} module',
              defaultValue_other: '{{count}} modules',
              count: cells.length,
            })}
          </p>
        </div>
        <ModuleHive
          cells={cells}
          label={heading}
          tint={tintFor(playbook.category)}
          onSelect={onSelect}
          cellWidth={104}
          rows={rows}
        />
      </div>
    </section>
  );
}
