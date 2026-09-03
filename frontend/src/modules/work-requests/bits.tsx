// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The small pieces every Work Requests screen wears: the reference chip,
 * the stage and status pills, avatars, the ball-in-court pill, the
 * priority glyph, the hours bar and the foldable section. Each is a
 * plain component so a card, a table row and the drawer read the same.
 */

import { fmtList } from '@/shared/lib/formatters';
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import clsx from 'clsx';
import type { Department, Person, Priority, Status, WorkRequest } from './api';
import {
  NEUTRAL,
  PRIORITY_GLYPH,
  PRIORITY_LABEL,
  STATUS_COLOUR,
  STATUS_LABEL,
  atCompletion,
  ballWords,
  daysLate,
  fmtDay,
  fmtHours,
  hoursBar,
  initials,
  isLate,
  lateWords,
  stageOf,
  tintFor,
  tintStyle,
  typeLabelsOf,
  type Me,
} from './lib';

export function RefChip({
  reference,
  colour,
  title,
  onClick,
  onContextMenu,
  className,
}: {
  reference: string;
  colour?: string;
  title?: string;
  onClick?: (e: ReactMouseEvent) => void;
  onContextMenu?: (e: ReactMouseEvent) => void;
  className?: string;
}) {
  const c = colour || tintFor(reference.split('-')[1] ?? reference);
  return (
    <span
      className={clsx('wr-ref', className)}
      style={tintStyle(c)}
      title={title}
      onClick={onClick}
      onContextMenu={onContextMenu}
      role={onClick ? 'button' : undefined}
    >
      <span className="dot" aria-hidden />
      {reference}
    </span>
  );
}

export function StagePill({ dept, stage }: { dept: Department | undefined; stage: string }) {
  const s = stageOf(dept, stage);
  if (!stage) return <span className="wr-hint">—</span>;
  return (
    <span className="wr-pill" style={tintStyle(s?.colour ?? NEUTRAL)}>
      {s?.name ?? stage}
    </span>
  );
}

/**
 * A request's types where there is only room for one: the primary, and a
 * `+N` that says how many more it is. Both the chip and the counter carry
 * the full list as a tooltip, so "SCADA +2" never hides what the other
 * two were - a card is a summary, not a lie by omission.
 */
export function TypeChips({
  req,
  dept,
  className,
}: {
  req: Pick<WorkRequest, 'request_type' | 'request_types' | 'request_type_labels'>;
  dept: Department | undefined;
  className?: string;
}) {
  const { t } = useTranslation();
  const labels = typeLabelsOf(req, dept);
  const [first, ...rest] = labels;
  if (!first) return null;
  const all = labels.join(' · ');
  return (
    <span className={clsx('wr-types', className)}>
      <span className="t" title={all}>
        {first}
      </span>
      {rest.length > 0 && (
        <span
          className="more"
          title={t('wr.also_types', { defaultValue: 'Also: {{list}}', list: fmtList(rest) })}
          aria-label={t('wr.n_types', { defaultValue: '{{count}} request types: {{list}}', count: labels.length, list: all })}
        >
          +{rest.length}
        </span>
      )}
    </span>
  );
}

/**
 * The red "late" pill: this request is past the DEPARTMENT's own target
 * date, which is a different promise from the requester's due date (that
 * one is the `late` class on the due cell). Renders nothing at all when
 * the server has not said - see `isLate`.
 */
export function LatePill({ req, className }: { req: Pick<WorkRequest, 'is_late' | 'days_late' | 'target_date' | 'status'>; className?: string }) {
  const { t } = useTranslation();
  if (!isLate(req)) return null;
  const n = daysLate(req);
  const label =
    n === null
      ? t('wr.late', { defaultValue: 'late' })
      : t('wr.late_days', { defaultValue_one: '{{count}} day late', defaultValue_other: '{{count}} days late', defaultValue: '{{count}} days late', count: n });
  return (
    <span
      className={clsx('wr-late', className)}
      data-testid="wr-late-pill"
      title={
        req.target_date
          ? t('wr.late_hint_target', { defaultValue: 'Past the department target of {{d}} - {{words}}', d: fmtDay(req.target_date), words: lateWords(req) })
          : t('wr.late_hint', { defaultValue: 'Past the department’s own target date' })
      }
    >
      {label}
    </span>
  );
}

export function StatusPill({ status }: { status: Status }) {
  const { t } = useTranslation();
  return (
    <span className="wr-pill" style={tintStyle(STATUS_COLOUR[status] ?? NEUTRAL)}>
      {t(`wr.status.${status}`, { defaultValue: STATUS_LABEL[status] ?? status })}
    </span>
  );
}

export function PriorityGlyph({ priority }: { priority: Priority }) {
  const { t } = useTranslation();
  const g = PRIORITY_GLYPH[priority];
  if (!g) return null;
  return (
    <span className={clsx('wr-prio', priority)} title={t(`wr.priority.${priority}`, { defaultValue: PRIORITY_LABEL[priority] })} aria-label={PRIORITY_LABEL[priority]}>
      {g}
    </span>
  );
}

export function Avatar({ person, size = 22 }: { person: Person; size?: number }) {
  return (
    <span
      className="wr-av"
      style={{ ['--av' as string]: tintFor(person.id || person.name), width: size, height: size, fontSize: Math.round(size * 0.42) } as CSSProperties}
      title={person.name}
      aria-label={person.name}
    >
      {initials(person.name)}
    </span>
  );
}

export function Avatars({ people, max = 4 }: { people: Person[]; max?: number }) {
  if (!people.length) return <span className="wr-hint">—</span>;
  const shown = people.slice(0, max);
  const rest = people.length - shown.length;
  return (
    <span className="wr-avs" title={fmtList(people.map((p) => p.name))}>
      {shown.map((p) => (
        <Avatar key={p.id} person={p} />
      ))}
      {rest > 0 && (
        <span className="wr-av" style={{ ['--av' as string]: NEUTRAL } as CSSProperties}>
          +{rest}
        </span>
      )}
    </span>
  );
}

export function BallPill({ req, me, deptName }: { req: WorkRequest; me: Me | null; deptName: string }) {
  const { t } = useTranslation();
  const b = ballWords(req, me, deptName);
  const label = b.withYou ? t('wr.with_you', { defaultValue: 'with you' }) : b.label;
  return (
    <span className={clsx('wr-pill', b.withYou && 'you')} style={b.withYou ? undefined : tintStyle(NEUTRAL)} title={t('wr.ball_hint', { defaultValue: 'Whose move it is' })}>
      {label}
    </span>
  );
}

export function HoursBar({ req, withText = true }: { req: WorkRequest; withText?: boolean }) {
  const { t } = useTranslation();
  const bar = hoursBar(req);
  const ac = atCompletion(req);
  const hint = t('wr.hours_hint', {
    defaultValue: 'Logged {{logged}} · at completion {{ac}} · quoted {{quoted}}',
    logged: fmtHours(req.hours_logged),
    ac: fmtHours(ac),
    quoted: fmtHours(req.quoted_hours),
  });
  return (
    <span className="hrs" title={hint}>
      <span className={clsx('wr-bar', bar.over && 'over')} role="img" aria-label={hint}>
        <i className="fc" style={{ width: `${bar.forecast}%` }} />
        <i className="lg" style={{ width: `${bar.logged}%` }} />
      </span>
      {withText && (
        <span>
          {fmtHours(req.hours_logged)}
          {bar.quoted !== null ? ` / ${fmtHours(bar.quoted)}` : ''}
        </span>
      )}
    </span>
  );
}

/** A section that folds; the state is per section, remembered per user. */
export function Section({
  id,
  title,
  count,
  right,
  defaultOpen = true,
  onContextMenu,
  children,
}: {
  id: string;
  title: string;
  /** A number, a formatted total, or a small component (the checklist bar). */
  count?: ReactNode;
  right?: ReactNode;
  defaultOpen?: boolean;
  onContextMenu?: (e: ReactMouseEvent) => void;
  children: ReactNode;
}) {
  const key = `wr-sec:${id}`;
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? defaultOpen : raw === '1';
    } catch {
      return defaultOpen;
    }
  });
  const toggle = () => {
    setOpen((o) => {
      try {
        localStorage.setItem(key, o ? '0' : '1');
      } catch {
        /* forgets, still works */
      }
      return !o;
    });
  };
  return (
    <div className="wr-sec">
      <div
        className="wr-sechead"
        onClick={toggle}
        onContextMenu={onContextMenu}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggle();
          }
        }}
      >
        <ChevronRight className={clsx('chev', open && 'open')} aria-hidden />
        <h3>{title}</h3>
        {count !== undefined && count !== '' && <span className="n">{count}</span>}
        {right && (
          <span className="right" onClick={(e) => e.stopPropagation()}>
            {right}
          </span>
        )}
      </div>
      {open && <div className="wr-secbody">{children}</div>}
    </div>
  );
}

/**
 * A horizontal scroller that ADMITS it scrolls.
 *
 * The eight-stage stepper and the eight-column board both ran off the
 * right at 1280 with nothing to say so: measured on the live seed, the
 * board was 1682px inside a 980px viewport and the stepper 768 inside
 * 682, so stages five to eight simply did not exist until somebody
 * happened to two-finger swipe. A fade over each overflowing edge and a
 * button on that side make the rest discoverable, and both are hidden
 * the moment the content fits so nothing decorates a board of three.
 *
 * The measuring is deliberately defensive: `ResizeObserver` and
 * `Element.scrollBy` are both absent under jsdom, so the component has
 * to work without either or it takes every test that renders a board
 * down with it.
 */
export function HScroll({
  className,
  innerClassName,
  label,
  step,
  children,
}: {
  className?: string;
  innerClassName?: string;
  label: string;
  /** How far one arrow press travels; defaults to 80% of the viewport. */
  step?: number;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const [edge, setEdge] = useState<{ left: boolean; right: boolean }>({ left: false, right: false });
  /**
   * The last measurement, as a ref rather than read back off state.
   *
   * The layout effect below has no dependency array on purpose - the
   * columns' width is not something React can express as a dep, so the
   * only honest answer is to re-measure after every commit. That makes
   * the guard load-bearing: returning the same object from `setEdge` is
   * NOT enough, because React still re-renders once before it bails, and
   * a re-render runs the layout effect again - "Maximum update depth
   * exceeded", which is exactly what the board did. Comparing here means
   * a measurement that has not changed calls no setter at all.
   */
  const lastRef = useRef('');

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const left = el.scrollLeft > 2;
    const right = max > 2 && el.scrollLeft < max - 2;
    const sig = `${left}:${right}`;
    if (sig === lastRef.current) return;
    lastRef.current = sig;
    setEdge({ left, right });
  }, []);

  useLayoutEffect(measure);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    window.addEventListener('resize', measure);
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(measure);
      ro.observe(el);
      // The columns themselves change width; watching only the viewport
      // misses a card that grows and pushes the last column out of sight.
      for (const child of Array.from(el.children)) ro.observe(child);
    }
    return () => {
      window.removeEventListener('resize', measure);
      ro?.disconnect();
    };
  }, [measure]);

  /**
   * `scrollBy({behavior: 'smooth'})` is a NO-OP on these scrollers in at
   * least one browser - measured live on the planner grid, an arrow press
   * left `scrollLeft` at 0 with 474px of range to go, while an instant
   * scroll landed exactly. So the position is assigned outright: an
   * affordance that visibly does nothing is worse than no affordance.
   */
  const nudge = (dir: 1 | -1) => {
    const el = ref.current;
    if (!el) return;
    const by = dir * (step ?? Math.max(240, Math.round(el.clientWidth * 0.8)));
    const max = el.scrollWidth - el.clientWidth;
    el.scrollLeft = Math.max(0, Math.min(max, el.scrollLeft + by));
    measure();
  };

  return (
    <div className={clsx('wr-hs', edge.left && 'l', edge.right && 'r', className)}>
      <div ref={ref} className={clsx('wr-hs-in', innerClassName)} onScroll={measure}>
        {children}
      </div>
      <button
        type="button"
        className="wr-hs-btn prev"
        tabIndex={-1}
        aria-hidden={!edge.left}
        aria-label={t('wr.scroll_left', { defaultValue: 'Scroll {{what}} left', what: label })}
        onClick={() => nudge(-1)}
      >
        <ChevronLeft size={16} aria-hidden />
      </button>
      <button
        type="button"
        className="wr-hs-btn next"
        tabIndex={-1}
        aria-hidden={!edge.right}
        aria-label={t('wr.scroll_right', { defaultValue: 'Scroll {{what}} right', what: label })}
        onClick={() => nudge(1)}
      >
        <ChevronRight size={16} aria-hidden />
      </button>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="wr-empty">
      <b>{title}</b>
      {children}
    </div>
  );
}
