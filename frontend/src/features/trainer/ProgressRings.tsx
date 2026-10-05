// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Concentric progress rings on the course map: one ring per kind of checked
// work (Numbers, Trace, Explain today). The ring list comes from the API, so
// nothing here assumes three: a fourth id gets the next colour and a smaller
// ring, and an id without a known name shows the label the course sends.
//
// A ring closes only on checked work, never on watching or clicking, which is
// the note the course map prints under the legend.
//
// Motion: the fill sweeps in once on mount, and only when the user has not
// asked for reduced motion. Without `matchMedia` (tests, old engines) the
// rings are drawn filled straight away.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

export interface RingDatum {
  /** `numbers`, `trace`, `explain`, or any id a course adds. */
  id: string;
  done: number;
  total: number;
  /** The course's own name for an id this component has no name for. */
  label?: string;
}

export interface ProgressRingsProps {
  rings: RingDatum[];
  /** Outer diameter in px. */
  size?: number;
  strokeWidth?: number;
  /**
   * Id of a heading near the rings. It goes on `aria-describedby`, so the
   * figure keeps its own label (the per-ring summary) and gains the heading.
   */
  labelledById?: string;
  /** The legend beside the rings (name and count per ring). */
  showLegend?: boolean;
  className?: string;
}

interface RingTone {
  arc: string;
  track: string;
  dot: string;
}

// Full class strings, so Tailwind sees every one of them at build time.
const KNOWN_TONES: Record<string, RingTone> = {
  numbers: { arc: 'stroke-oe-blue', track: 'stroke-oe-blue/15', dot: 'bg-oe-blue' },
  trace: { arc: 'stroke-oe-purple', track: 'stroke-oe-purple/15', dot: 'bg-oe-purple' },
  explain: {
    arc: 'stroke-orange-700 dark:stroke-orange-400',
    track: 'stroke-orange-700/15 dark:stroke-orange-400/20',
    dot: 'bg-orange-700 dark:bg-orange-400',
  },
};

const EXTRA_TONES: RingTone[] = [
  {
    arc: 'stroke-teal-600 dark:stroke-teal-400',
    track: 'stroke-teal-600/15 dark:stroke-teal-400/20',
    dot: 'bg-teal-600 dark:bg-teal-400',
  },
  {
    arc: 'stroke-rose-600 dark:stroke-rose-400',
    track: 'stroke-rose-600/15 dark:stroke-rose-400/20',
    dot: 'bg-rose-600 dark:bg-rose-400',
  },
  {
    arc: 'stroke-amber-600 dark:stroke-amber-400',
    track: 'stroke-amber-600/15 dark:stroke-amber-400/20',
    dot: 'bg-amber-600 dark:bg-amber-400',
  },
];

/** Known ids first, in course order (Numbers, Trace, Explain), then the rest as sent. */
const KNOWN_ORDER = ['numbers', 'trace', 'explain'];

export function orderRings<T extends { id: string }>(rings: T[]): T[] {
  const known = KNOWN_ORDER.flatMap((id) => rings.filter((r) => r.id === id));
  const rest = rings.filter((r) => !KNOWN_ORDER.includes(r.id));
  return [...known, ...rest];
}

/** Share of the ring that is filled, 0..1. A ring with nothing to do is empty. */
export function ringFraction(done: number, total: number): number {
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.min(1, Math.max(0, done / total));
}

/** `stroke-dasharray` for a ring of radius `r` filled to `fraction`. */
export function ringDashArray(r: number, fraction: number): string {
  const c = 2 * Math.PI * r;
  return `${(c * fraction).toFixed(1)} ${c.toFixed(1)}`;
}

function prefersReducedMotion(): boolean {
  try {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return true;
  }
}

export function ProgressRings({
  rings,
  size = 132,
  strokeWidth = 12,
  labelledById,
  showLegend = true,
  className,
}: ProgressRingsProps) {
  const { t, i18n } = useTranslation();
  const ordered = orderRings(rings);

  // Sweep in once. With reduced motion (or no matchMedia) start filled.
  const [drawn, setDrawn] = useState(prefersReducedMotion);
  useEffect(() => {
    if (drawn) return undefined;
    const id = window.requestAnimationFrame(() => setDrawn(true));
    return () => window.cancelAnimationFrame(id);
  }, [drawn]);

  // Literal keys only: no key is ever built from a ring id.
  const names: Record<string, string> = {
    numbers: t('trainer.rings.numbers', { defaultValue: 'Numbers' }),
    trace: t('trainer.rings.trace', { defaultValue: 'Trace' }),
    explain: t('trainer.rings.explain', { defaultValue: 'Explain' }),
  };
  const nameOf = (ring: RingDatum) => names[ring.id] ?? ring.label ?? ring.id;

  let extra = 0;
  const tones = ordered.map((ring) => KNOWN_TONES[ring.id] ?? EXTRA_TONES[extra++ % EXTRA_TONES.length]!);

  // Rings shrink to fit when a course sends more than three.
  const count = Math.max(1, ordered.length);
  const gap = 4;
  const fit = (size / 2 - 4) / count - gap;
  const stroke = Math.max(4, Math.min(strokeWidth, fit));
  const center = size / 2;

  const items = ordered.map((ring) =>
    t('trainer.rings.aria_item', {
      defaultValue: '{{name}} {{done}} of {{total}}',
      name: nameOf(ring),
      done: ring.done,
      total: ring.total,
    }),
  );
  let summary = items.join(', ');
  try {
    summary = new Intl.ListFormat(i18n.language || 'en', { type: 'conjunction' }).format(items);
  } catch {
    /* ListFormat missing or the locale tag refused: the comma list stands */
  }
  const ariaLabel = t('trainer.rings.aria_label', { defaultValue: 'Progress rings: {{summary}}', summary });

  return (
    <div className={clsx('flex flex-wrap items-center gap-5', className)}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={ariaLabel}
        aria-describedby={labelledById}
        className="shrink-0"
        data-testid="trainer-rings"
      >
        {ordered.map((ring, i) => {
          const r = center - stroke / 2 - i * (stroke + gap);
          if (r <= stroke / 2) return null;
          const fraction = ringFraction(ring.done, ring.total);
          const tone = tones[i]!;
          return (
            <g key={ring.id} data-ring={ring.id}>
              <circle
                cx={center}
                cy={center}
                r={r}
                fill="none"
                strokeWidth={stroke}
                className={ring.total > 0 ? tone.track : 'stroke-border'}
              />
              {ring.total > 0 && fraction > 0 && (
                <circle
                  cx={center}
                  cy={center}
                  r={r}
                  fill="none"
                  strokeWidth={stroke}
                  strokeLinecap="round"
                  strokeDasharray={ringDashArray(r, drawn ? fraction : 0)}
                  transform={`rotate(-90 ${center} ${center})`}
                  className={clsx(tone.arc, 'motion-safe:transition-[stroke-dasharray] motion-safe:duration-700 motion-safe:ease-out')}
                  data-testid={`trainer-ring-arc-${ring.id}`}
                />
              )}
            </g>
          );
        })}
      </svg>
      {showLegend && (
        <ul className="flex min-w-[150px] flex-col gap-2.5 text-sm" aria-hidden="true">
          {ordered.map((ring, i) => (
            <li key={ring.id} className="flex items-center gap-2">
              <span className={clsx('h-2.5 w-2.5 shrink-0 rounded-full', tones[i]!.dot)} />
              <strong className="min-w-[70px] font-semibold text-content-primary">{nameOf(ring)}</strong>
              <span className="font-mono tabular-nums text-content-secondary">
                {t('trainer.rings.count', { defaultValue: '{{done}}/{{total}}', done: ring.done, total: ring.total })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
