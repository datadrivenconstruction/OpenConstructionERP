// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The "no project selected" panel for Find Records.
//
// This is a member of the same family as <RequiresProject> (shared/auth): the
// same start-edge arrow, the same card, the same "Open Projects" exit. It is
// richer only because search is often the first surface a new reader opens, so
// it carries a drawn scene instead of a lone icon chip.
//
// The cue is gated on `sm:` because that is the breakpoint the target itself
// uses: the header ProjectSwitcher is `hidden sm:block` (app/layout/Header.tsx),
// and in the compiled stylesheet `.sm:block` and `.sm:flex` are governed by the
// identical condition `(min-width: 640px)`. So the arrow is on screen exactly
// when the control it points at is on screen - no offset math, and nothing to
// drift when the header is re-laid-out. Below that width the picker is
// `display:none` and there is nothing in the header to point at, so the arrow
// and its sentence are withheld and the button carries the whole job.
//
// The illustration follows the house line-art language from
// features/cases/stepSceneParts.tsx: concrete objects, own fill and stroke on
// every primitive, a soft offset shadow for depth, on a faint blueprint grid.
// The kit itself is not imported - its coordinates are bound to StepScene's own
// viewBox and nothing outside features/cases depends on it - so the palette
// hexes are restated here and the scene is drawn to its own viewBox.

import { ArrowUp, FolderOpen } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

/** House illustration palette, mirroring `C` in features/cases/stepSceneParts.tsx. */
const C = {
  blue: '#1a6c9c',
  blueLight: '#4aa6d8',
  blueDeep: '#0d4d74',
  ochre: '#cf8320',
  white: '#ffffff',
  panel: '#eaf2f8',
  grey1: '#9fb3c2',
  grey3: '#cdd9e2',
  shadow: '#0d3550',
} as const;

/** A rectangle with only its top two corners rounded (header bands). */
function topRoundedPath(x: number, y: number, w: number, h: number, r: number): string {
  return (
    `M${x} ${y + h} V${y + r} a${r} ${r} 0 0 1 ${r} ${-r} ` +
    `H${x + w - r} a${r} ${r} 0 0 1 ${r} ${r} V${y + h} Z`
  );
}

/**
 * Records under a magnifier: a stack of project sheets with one row picked out
 * in ochre under the lens. Decorative - the heading and sentence beside it carry
 * the meaning, so it is hidden from assistive technology.
 */
function RecordsScene() {
  return (
    <svg
      viewBox="0 0 120 84"
      className="h-auto w-full"
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <pattern id="oe-retrieval-empty-grid" width="8" height="8" patternUnits="userSpaceOnUse">
          <path d="M8 0 H0 V8" fill="none" stroke={C.blue} strokeWidth="0.4" opacity="0.13" />
        </pattern>
      </defs>

      {/* Blueprint ground */}
      <rect x="0" y="0" width="120" height="84" rx="6" fill="url(#oe-retrieval-empty-grid)" />

      {/* Back sheet, offset to read as a stack of records */}
      <rect x="42" y="9" width="42" height="52" rx="4" fill={C.shadow} opacity="0.08" />
      <rect
        x="40"
        y="7"
        width="42"
        height="52"
        rx="4"
        fill={C.panel}
        stroke={C.grey1}
        strokeWidth="1.6"
      />

      {/* Front sheet */}
      <rect x="26" y="19" width="44" height="54" rx="4" fill={C.shadow} opacity="0.08" />
      <rect
        x="24"
        y="17"
        width="44"
        height="54"
        rx="4"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth="1.6"
      />
      <path d={topRoundedPath(24, 17, 44, 9, 4)} fill={C.blue} />
      <rect x="28.5" y="20.5" width="15" height="2.4" rx="1.2" fill={C.white} opacity="0.85" />

      {/* Record rows; the third is the hit, picked out in ochre under the lens */}
      <rect x="30" y="33" width="32" height="3.2" rx="1.6" fill={C.grey3} />
      <rect x="30" y="41" width="26" height="3.2" rx="1.6" fill={C.grey3} />
      <rect x="30" y="49" width="30" height="3.2" rx="1.6" fill={C.ochre} />
      <rect x="30" y="57" width="21" height="3.2" rx="1.6" fill={C.grey3} />

      {/* Magnifier over the matched row */}
      <line
        x1="76"
        y1="66"
        x2="88"
        y2="78"
        stroke={C.blueDeep}
        strokeWidth="4.4"
        strokeLinecap="round"
      />
      <circle cx="66" cy="56" r="15" fill={C.blueLight} opacity="0.16" />
      <circle cx="66" cy="56" r="15" fill="none" stroke={C.blueDeep} strokeWidth="2.6" />
      <path
        d="M58 50 a11 11 0 0 1 7-4"
        fill="none"
        stroke={C.white}
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.75"
      />
    </svg>
  );
}

export function NoProjectState() {
  const { t } = useTranslation();

  return (
    <div className="flex w-full justify-center px-4 py-10">
      <div className="w-full max-w-xl">
        {/* Directional cue. Present only at the widths where the header picker
            is, per the breakpoint note at the top of this file. The arrow leans
            up and towards the start edge, where the switcher sits as the first
            item of the header's workspace zone, and mirrors under rtl with the
            rotation rather than a second icon. */}
        <div className="mb-3 ms-2 hidden items-center gap-2.5 sm:flex">
          {/* The bounce and the tilt live on different elements on purpose.
              `animate-bounce` animates `transform`, so its keyframes replace a
              `-rotate-45` set on the same node and the arrow ends up pointing
              straight up instead of up-and-towards-the-start-edge. Bouncing the
              wrapper and rotating the icon lets both survive. */}
          <span className="inline-flex animate-bounce motion-reduce:animate-none" aria-hidden="true">
            <ArrowUp size={30} strokeWidth={1.75} className="-rotate-45 text-oe-blue rtl:rotate-45" />
          </span>
          <span className="text-sm font-medium text-oe-blue">
            {t('retrieval.no_project_picker_hint', {
              defaultValue: 'The project switcher is up here, in the header.',
            })}
          </span>
        </div>

        <div className="rounded-2xl border border-border-light bg-surface-primary p-6 shadow-sm sm:p-8">
          <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-start sm:gap-7">
            <div className="w-40 shrink-0 sm:w-44">
              <RecordsScene />
            </div>

            <div className="min-w-0 text-center sm:text-start">
              <h2 className="text-xl font-semibold text-content-primary">
                {t('retrieval.no_project_title', { defaultValue: 'No project selected' })}
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-content-secondary">
                {t('retrieval.no_project_desc', {
                  defaultValue: 'Select a project to search across its records.',
                })}
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-content-tertiary">
                {t('retrieval.no_project_scope', {
                  defaultValue:
                    'Find Records searches the documents, correspondence and change orders of one project at a time.',
                })}
              </p>

              <div className="mt-6 flex justify-center sm:justify-start">
                <Link
                  to="/projects"
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-oe-blue px-4 text-sm font-medium text-white transition-colors hover:bg-oe-blue/90"
                >
                  <FolderOpen size={16} strokeWidth={1.75} aria-hidden="true" />
                  {/* Shared with <RequiresProject>: same label, same destination,
                      and already translated everywhere. */}
                  {t('requiresProject.cta', { defaultValue: 'Open Projects' })}
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
