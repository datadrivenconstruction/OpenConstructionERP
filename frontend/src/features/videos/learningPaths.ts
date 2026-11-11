// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Learning paths as a honeycomb: the courses set on one example project, in
// the order the work happens on it (take-off, estimate, tender, plan, build,
// handover), laid out as rings of flat-top hexagons around the path's goal.
// Pure data and geometry; CourseHive.tsx draws it.

import { useCallback, useEffect, useState } from 'react';
import type { LifecycleStage } from '@/features/cases/types';
import { STAGE_ORDER } from '@/features/cases/stages';
import type { AcademyItem } from './academyTypes';

/** Where in the project lifecycle a course's first screen sits. */
const ROUTE_STAGE: Record<string, LifecycleStage> = {
  '/documents': 'design',
  '/takeoff': 'design',
  '/bim': 'design',
  '/clash': 'design',
  '/requirements': 'design',
  '/bcf': 'design',
  '/boq': 'estimate',
  '/carbon': 'estimate',
  '/tendering': 'procure',
  '/bid-management': 'procure',
  '/contracts': 'procure',
  '/schedule': 'plan',
  '/risks': 'plan',
  '/safety': 'build',
  '/daily-diary': 'build',
  '/inspections': 'build',
  '/ncr': 'build',
  '/variations': 'build',
  '/changeorders': 'build',
  '/cvr': 'build',
  '/cost-control': 'build',
  '/full-evm': 'build',
  '/closeout': 'handover',
  '/punchlist': 'handover',
};

export function courseStage(item: AcademyItem): LifecycleStage {
  for (const r of item.routes) {
    const s = ROUTE_STAGE[r];
    if (s) return s;
  }
  return 'build';
}

export interface LearningPath {
  /** The example project's slug, e.g. `ashbrook`. */
  id: string;
  /** Display name of the project (a proper name, data). */
  name: string;
  country?: string;
  courses: AcademyItem[];
}

const MIN_PATH = 3;

function slugOf(item: AcademyItem): string {
  return item.id.split(':')[1] ?? item.id;
}

/** Courses grouped by the project they are set on, each group in lifecycle order. */
export function learningPaths(items: readonly AcademyItem[]): LearningPath[] {
  const groups = new Map<string, AcademyItem[]>();
  for (const i of items) {
    if (i.kind !== 'course') continue;
    const project = slugOf(i).split('-')[0];
    if (!project) continue;
    const list = groups.get(project) ?? [];
    list.push(i);
    groups.set(project, list);
  }
  const paths: LearningPath[] = [];
  for (const [id, list] of groups) {
    if (list.length < MIN_PATH) continue;
    const courses = list
      .map((c, n) => ({ c, n }))
      .sort((a, b) => STAGE_ORDER[courseStage(a.c)] - STAGE_ORDER[courseStage(b.c)] || a.n - b.n)
      .map((x) => x.c);
    const country = courses.find((c) => c.country)?.country ?? courses.find((c) => c.market)?.market;
    paths.push({ id, name: id.charAt(0).toUpperCase() + id.slice(1), country, courses });
  }
  return paths.sort((a, b) => b.courses.length - a.courses.length || a.id.localeCompare(b.id));
}

/** The path for the reader's market, else the longest. */
export function defaultPath(paths: readonly LearningPath[], market: string | null): LearningPath | undefined {
  return paths.find((p) => market && p.country === market) ?? paths[0];
}

// ── Geometry: axial coordinates of flat-top hexagons ─────────────────────────

export interface Axial {
  q: number;
  r: number;
}

const DIRS: Axial[] = [
  { q: 1, r: 0 },
  { q: 1, r: -1 },
  { q: 0, r: -1 },
  { q: -1, r: 0 },
  { q: -1, r: 1 },
  { q: 0, r: 1 },
];

export function hexDistance(a: Axial, b: Axial): number {
  const dq = a.q - b.q;
  const dr = a.r - b.r;
  return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2;
}

function ring(k: number): Axial[] {
  const out: Axial[] = [];
  let h = { q: DIRS[4]!.q * k, r: DIRS[4]!.r * k };
  for (let d = 0; d < 6; d++) {
    for (let s = 0; s < k; s++) {
      out.push(h);
      h = { q: h.q + DIRS[d]!.q, r: h.r + DIRS[d]!.r };
    }
  }
  return out;
}

/**
 * `n` cells around the centre (0,0), ring after ring, every cell a neighbour
 * of the one before it so the path can be followed with the eye. Each outer
 * ring is rotated to begin next to where the inner one ended.
 */
export function spiralCells(n: number): Axial[] {
  const out: Axial[] = [];
  let k = 1;
  while (out.length < n) {
    let cells = ring(k);
    const last = out[out.length - 1];
    if (last) {
      const start = cells.findIndex((c) => hexDistance(c, last) === 1);
      cells = [...cells.slice(start), ...cells.slice(0, start)];
    }
    out.push(...cells.slice(0, n - out.length));
    k += 1;
  }
  return out;
}

export interface CellBox {
  /** Centre, in cell units (a cell is 2 wide and √3 tall). */
  cx: number;
  cy: number;
  /** Box as percentages of the comb. */
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface HiveLayout {
  centre: CellBox;
  cells: CellBox[];
  /** Comb size in cell units; the container keeps this aspect ratio. */
  width: number;
  height: number;
}

const SQRT3 = Math.sqrt(3);

export function hiveLayout(n: number): HiveLayout {
  const axial = [{ q: 0, r: 0 }, ...spiralCells(n)];
  const pts = axial.map((a) => ({ x: 1.5 * a.q, y: SQRT3 * (a.r + a.q / 2) }));
  const minX = Math.min(...pts.map((p) => p.x)) - 1;
  const maxX = Math.max(...pts.map((p) => p.x)) + 1;
  const minY = Math.min(...pts.map((p) => p.y)) - SQRT3 / 2;
  const maxY = Math.max(...pts.map((p) => p.y)) + SQRT3 / 2;
  const width = maxX - minX;
  const height = maxY - minY;
  const boxes = pts.map((p) => ({
    cx: p.x - minX,
    cy: p.y - minY,
    left: ((p.x - 1 - minX) / width) * 100,
    top: ((p.y - SQRT3 / 2 - minY) / height) * 100,
    width: (2 / width) * 100,
    height: (SQRT3 / height) * 100,
  }));
  return { centre: boxes[0]!, cells: boxes.slice(1), width, height };
}

// ── Progress ─────────────────────────────────────────────────────────────────

export type CourseStatus = 'done' | 'next' | 'ahead';

/** Done as marked; the first not-done course in order is next; the rest ahead. */
export function courseStatuses(courses: readonly AcademyItem[], done: Readonly<Record<string, true>>): CourseStatus[] {
  let nextGiven = false;
  return courses.map((c) => {
    if (done[c.id]) return 'done';
    if (!nextGiven) {
      nextGiven = true;
      return 'next';
    }
    return 'ahead';
  });
}

export function pathPercent(courses: readonly AcademyItem[], done: Readonly<Record<string, true>>): number {
  if (courses.length === 0) return 0;
  return Math.round((courses.filter((c) => done[c.id]).length / courses.length) * 100);
}

export const DONE_KEY = 'oe_courses_done';

function readDone(): Record<string, true> {
  try {
    const parsed = JSON.parse(localStorage.getItem(DONE_KEY) ?? '{}') as Record<string, unknown>;
    const out: Record<string, true> = {};
    for (const [k, v] of Object.entries(parsed)) if (v === true) out[k] = true;
    return out;
  } catch {
    return {};
  }
}

/** Courses the reader marked as done, kept in this browser only. */
export function useCoursesDone(): [Record<string, true>, (id: string) => void] {
  const [done, setDone] = useState<Record<string, true>>(readDone);
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === DONE_KEY) setDone(readDone());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);
  const toggle = useCallback((id: string) => {
    setDone((prev) => {
      const next = { ...prev };
      if (next[id]) delete next[id];
      else next[id] = true;
      try {
        localStorage.setItem(DONE_KEY, JSON.stringify(next));
      } catch {
        /* storage full or blocked: progress lives for this visit only */
      }
      return next;
    });
  }, []);
  return [done, toggle];
}

/** The photo every course ships with (`public/academy-courses/<slug>.webp`). */
export function coursePhoto(item: AcademyItem): string {
  return `${import.meta.env.BASE_URL}academy-courses/${slugOf(item)}.webp`;
}
