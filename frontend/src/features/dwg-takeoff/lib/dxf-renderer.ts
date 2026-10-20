// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Canvas2D rendering functions for DXF/DWG entities.
 *
 * Each entity type is rendered via a dedicated function that receives the
 * 2D context, the entity data, and the current viewport state.
 */

import type { DxfEntity } from '../api';
import type { BlockDefs } from './blocks';
import { isResolvedInsert } from './blocks';
import type { TextDisplayState } from './text-display-store';
import { DEFAULT_TEXT_DISPLAY } from './text-display-store';
import type { ViewportState } from './viewport';
import { ellipseSweep, worldToScreen } from './viewport';

/* ── CAD Color Index → CSS hex ─────────────────────────────────────── */

const ACI_TABLE: Record<number, string> = {
  0: '#000000', // ByBlock
  1: '#FF0000', // Red
  2: '#FFFF00', // Yellow
  3: '#00FF00', // Green
  4: '#00FFFF', // Cyan
  5: '#0000FF', // Blue
  6: '#FF00FF', // Magenta
  7: '#FFFFFF', // White / Black (display-dependent)
  8: '#808080', // Dark grey
  9: '#C0C0C0', // Light grey
};

/** Convert an entity color (ACI number or hex string) to a CSS hex color. */
export function resolveColor(color: string | number): string {
  if (typeof color === 'string') {
    // Already a hex color string
    if (color.startsWith('#')) return color;
    return '#CCCCCC';
  }
  return ACI_TABLE[color] ?? '#CCCCCC';
}

/** @deprecated Use resolveColor instead */
export function aciToHex(colorIndex: number | string): string {
  return resolveColor(colorIndex);
}

/* ── Scene selection ──────────────────────────────────────────────────── */

/**
 * Sheet names present in an entity list, model space first and the rest
 * alphabetical - the order the sheet strip shows them in, so "the first sheet"
 * means the same thing everywhere.
 *
 * Definition members carry `block` instead of `layout` and so belong to no
 * sheet; they are placed by the INSERTs that reference them and are counted
 * wherever those land.
 */
export function layoutNames(entities: DxfEntity[]): string[] {
  const set = new Set<string>();
  for (const e of entities) {
    if (e.layout) set.add(e.layout);
  }
  if (set.size === 0) return [];
  return Array.from(set).sort((a, b) => {
    const aIsModel = a === 'Model' || a === '*Model_Space';
    const bIsModel = b === 'Model' || b === '*Model_Space';
    if (aIsModel && !bIsModel) return -1;
    if (!aIsModel && bIsModel) return 1;
    return a.localeCompare(b);
  });
}

/**
 * Which sheet is on screen, given the one the reader picked.
 *
 * Derived, never latched. A drawing that has sheets is always showing one of
 * them, including on the frame that paints before the reader has picked
 * anything - so "nothing picked yet" resolves to the first sheet here rather
 * than being corrected afterwards by an effect. An effect runs after commit,
 * which means the first painted frame of every drawing would show whatever the
 * un-picked state renders as, and that used to be every sheet at once.
 *
 * A pick that names a sheet the current drawing does not have is treated as no
 * pick: switching drawings must not leave the viewer filtering by a name that
 * only existed in the previous file, which shows an empty canvas.
 */
export function effectiveLayout(layouts: string[], picked: string | null): string | null {
  if (picked !== null && layouts.includes(picked)) return picked;
  return layouts[0] ?? null;
}

/**
 * The entity set that makes up one rendered scene: what reaches
 * `renderEntities` and `computeExtents`.
 *
 * Exactly one sheet, whenever the drawing has sheets. Model space and paper
 * space are different coordinate systems sharing neither origin nor scale, so
 * a scene holding both cannot be framed: fitting an 18 m building and a 400 mm
 * title block into one window collapses the title block to a speck drawn over
 * the plan and pushes the plan to whatever is left. That is why the union is
 * not a fallback for "no sheet chosen" - `effectiveLayout` answers that
 * question instead, and answers it with a sheet.
 *
 * The union survives in one case only, and there it is correct: a drawing whose
 * entities carry no layout at all has a single implied sheet, and every entity
 * is on it.
 */
export function sceneEntities(
  all: DxfEntity[],
  layouts: string[],
  picked: string | null,
): DxfEntity[] {
  if (layouts.length === 0) return all.filter((e) => !e.block);
  const layout = effectiveLayout(layouts, picked);
  return all.filter((e) => e.layout === layout && !e.block);
}

/* ── Viewport culling ─────────────────────────────────────────────────── */

/** Quick check whether an entity is likely within the visible canvas area. */
function isInViewport(
  entity: DxfEntity,
  vp: ViewportState,
  canvasW: number,
  canvasH: number,
): boolean {
  // Get a representative point for the entity
  let cx = 0;
  let cy = 0;
  let radius = 0;

  if (entity.start) {
    cx = entity.start.x;
    cy = entity.start.y;
    radius = entity.radius ?? 0;
  } else if (entity.vertices?.length) {
    cx = entity.vertices[0]!.x;
    cy = entity.vertices[0]!.y;
  } else {
    // Can't determine position — render to be safe
    return true;
  }

  const screen = worldToScreen(cx, cy, vp);
  const radiusPx = radius * vp.scale;
  const margin = 200 + radiusPx; // pixels margin

  // For polylines/hatches with many vertices, also check if any vertex is visible
  if (
    screen.x < -margin ||
    screen.x > canvasW + margin ||
    screen.y < -margin ||
    screen.y > canvasH + margin
  ) {
    // First vertex is off-screen; for multi-vertex entities check a few more
    if (entity.vertices && entity.vertices.length > 1) {
      // Check last vertex and a midpoint vertex for large polylines
      const checkIndices = [
        entity.vertices.length - 1,
        Math.floor(entity.vertices.length / 2),
      ];
      for (const idx of checkIndices) {
        const v = entity.vertices[idx]!;
        const s = worldToScreen(v.x, v.y, vp);
        if (s.x > -margin && s.x < canvasW + margin && s.y > -margin && s.y < canvasH + margin) {
          return true;
        }
      }
      // For LINE entities, also check end point
    } else if (entity.end) {
      const s = worldToScreen(entity.end.x, entity.end.y, vp);
      if (s.x > -margin && s.x < canvasW + margin && s.y > -margin && s.y < canvasH + margin) {
        return true;
      }
    }
    return false;
  }

  return true;
}

/* ── Entity rendering ──────────────────────────────────────────────────── */

export function renderEntities(
  ctx: CanvasRenderingContext2D,
  entities: DxfEntity[],
  vp: ViewportState,
  visibleLayers: Set<string>,
  selectedId?: string | null,
  canvasWidth?: number,
  canvasHeight?: number,
  blockDefs?: BlockDefs,
  textDisplay?: TextDisplayState,
): void {
  const cw = canvasWidth ?? ctx.canvas.width / (window.devicePixelRatio || 1);
  const ch = canvasHeight ?? ctx.canvas.height / (window.devicePixelRatio || 1);
  const td = textDisplay ?? DEFAULT_TEXT_DISPLAY;

  // Render hatches first (background fill)
  for (const entity of entities) {
    if (entity.block) continue;
    if (entity.type === 'HATCH' && visibleLayers.has(entity.layer)) {
      if (!isInViewport(entity, vp, cw, ch)) continue;
      applyStyle(ctx, entity, selectedId);
      renderHatch(ctx, entity, vp);
    }
  }

  // Render geometry entities.
  //
  // Consecutive entities that would be stroked with the same style go into one
  // path and are stroked once. A canvas charges for every `stroke()` and every
  // state change, and this loop used to issue both for each of thousands of
  // short segments that agreed about their colour anyway.
  //
  // Runs, not groups. Sorting the list by colour would batch far harder, and it
  // would also change which line lands on top of which where they cross. The
  // drawing has to keep looking like the drawing, so the order stays exactly as
  // it arrived and only neighbours are merged.
  //
  // How much that wins depends on how the file was written, and the honest
  // answer here is one measurement rather than a claim about DXF in general:
  // on `fixtures/bench-drawings.ts`, ten strokeable entities collapse to three
  // stroke calls. That fixture is small, and a file whose colours alternate
  // entity by entity would gain nothing at all - it would simply behave as
  // before, one path and one stroke each, which is why the run form is also the
  // safe form.
  let openBatch: string | null = null;
  const flush = (): void => {
    if (openBatch === null) return;
    ctx.stroke();
    openBatch = null;
  };

  for (const entity of entities) {
    // A definition member is drawn only through the INSERTs that place it -
    // see `expandBlockReferences`. Its own coordinates are in block space, so
    // drawing it here would scatter loose parts across the sheet.
    if (entity.block) continue;
    if (!visibleLayers.has(entity.layer)) continue;
    if (entity.type === 'HATCH') continue; // already rendered
    if (!isInViewport(entity, vp, cw, ch)) continue;

    const path = pathBuilderFor(entity.type);
    if (path) {
      const style = strokeStyleKey(entity, selectedId);
      if (style !== openBatch) {
        flush();
        applyStyle(ctx, entity, selectedId);
        ctx.beginPath();
        openBatch = style;
      }
      path(ctx, entity, vp);
      continue;
    }

    // Anything that fills, draws text, or opens a path of its own has to see a
    // finished batch, not a half-built one.
    flush();
    applyStyle(ctx, entity, selectedId);

    switch (entity.type) {
      case 'TEXT':
        // The one place text visibility is decided. Everything upstream - the
        // fit box, the hit test, the layer filter, the quantities - is handed
        // the same entity list either way, so this is painting and nothing
        // else.
        if (td.visible) renderText(ctx, entity, vp, td.scale);
        break;
      case 'POINT':
        renderPoint(ctx, entity, vp);
        break;
      case 'INSERT':
        renderInsert(ctx, entity, vp, blockDefs, td);
        break;
    }
  }

  flush();
}

/**
 * What makes two entities strokeable in the same pass.
 *
 * `applyStyle` derives everything it sets from the resolved colour, except for
 * the selected entity, which gets its own width and glow. So the colour is the
 * whole identity, and the selected one is deliberately given a key nothing else
 * can match: it must break the run on both sides rather than borrow a
 * neighbour's style or lend it its own.
 */
const SELECTED_STROKE_KEY = 'selected';

function strokeStyleKey(entity: DxfEntity, selectedId?: string | null): string {
  return entity.id === selectedId ? SELECTED_STROKE_KEY : resolveColor(entity.color);
}

function applyStyle(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  selectedId?: string | null,
): void {
  const isSelected = entity.id === selectedId;
  if (isSelected) {
    ctx.strokeStyle = '#60a5fa';
    ctx.fillStyle = '#60a5fa';
    ctx.lineWidth = 2.5;
    // Glow effect via shadow
    ctx.shadowColor = 'rgba(96, 165, 250, 0.5)';
    ctx.shadowBlur = 8;
  } else {
    const color = resolveColor(entity.color);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1;
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
  }
}

/* ── Path builders ──────────────────────────────────────────────────────────
 *
 * Each of these appends to whatever path is already open, instead of opening
 * and stroking one of its own. That is what lets `renderEntities` collect a run
 * of entities that share a style into a single path and stroke it once. A
 * canvas charges for every `stroke()` and every state change, and a drawing is
 * thousands of short segments that mostly agree about their colour, so the
 * per-entity `beginPath`/`stroke` pair was most of the cost of a frame.
 *
 * The exported `render*` wrappers below still open and stroke a path of their
 * own, so a caller that wants one entity drawn by itself keeps exactly that.
 *
 * The arc builders move to their own start point before curving. Inside a
 * shared path, `arc()` is joined to the previous subpath by a straight line,
 * which would draw a stray chord across the drawing. On a path of its own the
 * move is redundant and harmless, which is why one builder serves both callers.
 */

function pathLine(ctx: CanvasRenderingContext2D, entity: DxfEntity, vp: ViewportState): void {
  if (!entity.start || !entity.end) return;
  const s = worldToScreen(entity.start.x, entity.start.y, vp);
  const e = worldToScreen(entity.end.x, entity.end.y, vp);
  ctx.moveTo(s.x, s.y);
  ctx.lineTo(e.x, e.y);
}

function pathPolyline(ctx: CanvasRenderingContext2D, entity: DxfEntity, vp: ViewportState): void {
  if (!entity.vertices || entity.vertices.length < 2) return;
  const v0 = entity.vertices[0]!;
  const first = worldToScreen(v0.x, v0.y, vp);
  ctx.moveTo(first.x, first.y);
  for (let i = 1; i < entity.vertices.length; i++) {
    const v = entity.vertices[i]!;
    const p = worldToScreen(v.x, v.y, vp);
    ctx.lineTo(p.x, p.y);
  }
  if (entity.closed) {
    ctx.closePath();
  }
}

function pathArc(ctx: CanvasRenderingContext2D, entity: DxfEntity, vp: ViewportState): void {
  if (!entity.start || entity.radius == null) return;
  const center = worldToScreen(entity.start.x, entity.start.y, vp);
  const r = entity.radius * vp.scale;
  const startAngle = entity.start_angle ?? 0;
  const endAngle = entity.end_angle ?? Math.PI * 2;
  // DXF arcs run CCW in world space. worldToScreen flips Y, so the screen angles
  // are negated and the sweep runs from -start down to -end: anticlockwise on canvas.
  // Sweeping the other way drew the complement, a near-full circle for a short arc.
  ctx.moveTo(center.x + r * Math.cos(-startAngle), center.y + r * Math.sin(-startAngle));
  ctx.arc(center.x, center.y, r, -startAngle, -endAngle, true);
}

function pathCircle(ctx: CanvasRenderingContext2D, entity: DxfEntity, vp: ViewportState): void {
  if (!entity.start || entity.radius == null) return;
  const center = worldToScreen(entity.start.x, entity.start.y, vp);
  const r = entity.radius * vp.scale;
  ctx.moveTo(center.x + r, center.y);
  ctx.arc(center.x, center.y, r, 0, Math.PI * 2);
}

function pathEllipse(ctx: CanvasRenderingContext2D, entity: DxfEntity, vp: ViewportState): void {
  if (!entity.start) return;
  const center = worldToScreen(entity.start.x, entity.start.y, vp);

  let majorR: number;
  let minorR: number;
  let rotation: number;

  if (entity.major_radius != null && entity.minor_radius != null) {
    // DDC format: explicit radii
    majorR = entity.major_radius * vp.scale;
    minorR = entity.minor_radius * vp.scale;
    rotation = -(entity.rotation ?? 0); // negate for screen Y-flip
  } else if (entity.major_axis && entity.ratio != null) {
    // ezdxf format: major_axis vector + ratio
    const ax = entity.major_axis;
    majorR = Math.sqrt(ax.x * ax.x + ax.y * ax.y) * vp.scale;
    minorR = majorR * entity.ratio;
    rotation = -Math.atan2(ax.y, ax.x); // negate for screen Y-flip
  } else {
    return;
  }

  if (majorR < 0.5 || minorR < 0.5) return; // too small to draw

  // Parameters run CCW in world space; with Y flipped they are negated and the
  // sweep runs anticlockwise on the canvas, as for ARC.
  const { start, sweep } = ellipseSweep(entity);
  const t0 = -start;
  const cr = Math.cos(rotation);
  const sr = Math.sin(rotation);
  const x0 = majorR * Math.cos(t0);
  const y0 = minorR * Math.sin(t0);
  ctx.moveTo(center.x + x0 * cr - y0 * sr, center.y + x0 * sr + y0 * cr);
  ctx.ellipse(center.x, center.y, majorR, minorR, rotation, t0, t0 - sweep, true);
}

/**
 * The path builder for an entity type, or `null` when the type is not a plain
 * stroke and so cannot join a batch: text and points are filled, and a block
 * marker carries a label.
 */
function pathBuilderFor(
  type: string,
): ((ctx: CanvasRenderingContext2D, entity: DxfEntity, vp: ViewportState) => void) | null {
  switch (type) {
    case 'LINE':
      return pathLine;
    case 'LWPOLYLINE':
      return pathPolyline;
    case 'ARC':
      return pathArc;
    case 'CIRCLE':
      return pathCircle;
    case 'ELLIPSE':
      return pathEllipse;
    default:
      return null;
  }
}

export function renderLine(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  ctx.beginPath();
  pathLine(ctx, entity, vp);
  ctx.stroke();
}

export function renderPolyline(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  ctx.beginPath();
  pathPolyline(ctx, entity, vp);
  ctx.stroke();
}

export function renderArc(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  ctx.beginPath();
  pathArc(ctx, entity, vp);
  ctx.stroke();
}

export function renderCircle(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  ctx.beginPath();
  pathCircle(ctx, entity, vp);
  ctx.stroke();
}

export function renderEllipse(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  ctx.beginPath();
  pathEllipse(ctx, entity, vp);
  ctx.stroke();
}

/** Cache for hatch line patterns to avoid recreating each frame. */
const hatchPatternCache = new Map<string, CanvasPattern | null>();

/**
 * Hatch line spacing in screen px at zoom 1, and the range it may occupy once
 * the zoom has been applied.
 *
 * The spacing used to be the constant 8, and the cache keyed on the colour and
 * that constant, so the pattern never answered the zoom at all. A hatched region
 * drawn small received the same 8 px grid as one drawn large, which filled it in
 * and hid the linework underneath; the same region drawn large kept a grain far
 * finer than the drawing asked for. That is why zooming in appeared to cure the
 * overlap rather than merely postpone it. The spacing is now anchored in the
 * drawing and moves with the view like everything else on the sheet.
 *
 * Rounding to whole pixels is what keeps the cache bounded. Zoom is continuous,
 * so one entry per float would grow without limit, while 45 sizes per colour at
 * 48 px square costs nothing. The upper clamp does mean the pattern stops
 * growing at extreme zoom. That is a deliberate limit rather than an exact
 * rendering: by then the reader is inside a small area where 48 px reads fine,
 * and the thing it replaces is a pattern that never grew at all.
 */
const HATCH_SPACING_AT_UNIT_SCALE = 8;
const HATCH_MIN_SCREEN_PX = 4;
const HATCH_MAX_SCREEN_PX = 48;

/**
 * Screen size below which a hatched region is filled flat instead of patterned.
 *
 * Not a visibility cull. The region is still filled, so a field of small hatches
 * still reads as texture and nothing disappears. It only skips the pattern,
 * which at that size cannot be resolved and costs a tile lookup and a pattern
 * fill to produce a smudge.
 */
const HATCH_MIN_PATTERN_BOX_PX = 3;

/**
 * Screen spacing to draw a hatch pattern at, or `null` to fill the region flat.
 *
 * `null` is returned for the two cases where a pattern cannot say anything: the
 * lines would fall closer together than the screen can resolve, which is what
 * used to paint a solid block over the geometry beneath, and the region itself
 * is too small to hold a repeat.
 *
 * @param scale       viewport scale, screen px per drawing unit
 * @param screenBoxPx longest side of the region's screen bounding box
 */
export function hatchPatternSpacing(scale: number, screenBoxPx: number): number | null {
  const spacing = HATCH_SPACING_AT_UNIT_SCALE * scale;
  if (!(spacing >= HATCH_MIN_SCREEN_PX) || screenBoxPx < HATCH_MIN_PATTERN_BOX_PX) return null;
  return Math.round(Math.min(HATCH_MAX_SCREEN_PX, spacing));
}

/** Create a diagonal line pattern (ANSI31-style, 45-degree lines). */
function createDiagonalPattern(
  ctx: CanvasRenderingContext2D,
  color: string,
  spacing = 8,
): CanvasPattern | null {
  const cacheKey = `diagonal_${color}_${spacing}`;
  if (hatchPatternCache.has(cacheKey)) return hatchPatternCache.get(cacheKey)!;

  const size = spacing;
  const offscreen = document.createElement('canvas');
  offscreen.width = size;
  offscreen.height = size;
  const pctx = offscreen.getContext('2d');
  if (!pctx) return null;

  pctx.strokeStyle = color;
  pctx.lineWidth = 1;
  pctx.beginPath();
  // Draw diagonal line from bottom-left to top-right
  pctx.moveTo(0, size);
  pctx.lineTo(size, 0);
  // Extend for seamless tiling
  pctx.moveTo(-size, size);
  pctx.lineTo(size, -size);
  pctx.moveTo(0, size * 2);
  pctx.lineTo(size * 2, 0);
  pctx.stroke();

  const pattern = ctx.createPattern(offscreen, 'repeat');
  hatchPatternCache.set(cacheKey, pattern);
  return pattern;
}

export function renderHatch(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.vertices || entity.vertices.length < 3) return;

  ctx.beginPath();
  const first = worldToScreen(entity.vertices[0]!.x, entity.vertices[0]!.y, vp);
  ctx.moveTo(first.x, first.y);
  // The screen extent comes out of the walk the path already does, so knowing
  // how big the region lands costs nothing beyond four comparisons a vertex.
  let minX = first.x;
  let maxX = first.x;
  let minY = first.y;
  let maxY = first.y;
  for (let i = 1; i < entity.vertices.length; i++) {
    const v = entity.vertices[i]!;
    const p = worldToScreen(v.x, v.y, vp);
    ctx.lineTo(p.x, p.y);
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  ctx.closePath();

  ctx.save();

  const patternName = (entity.pattern_name ?? '').toUpperCase();
  const spacing = hatchPatternSpacing(vp.scale, Math.max(maxX - minX, maxY - minY));

  if (entity.is_solid || patternName === 'SOLID') {
    // Solid fill
    ctx.globalAlpha = 0.15;
    ctx.fill();
  } else if (patternName === 'ANSI31' || patternName === 'ANSI32' || patternName === 'ANSI37') {
    // Diagonal line patterns
    const color = ctx.fillStyle as string;
    const pattern = spacing === null ? null : createDiagonalPattern(ctx, color, spacing);
    if (pattern) {
      ctx.globalAlpha = 0.35;
      ctx.fillStyle = pattern;
      ctx.fill();
    } else {
      ctx.globalAlpha = 0.1;
      ctx.fill();
    }
  } else if (patternName) {
    // Other named patterns — use slightly higher opacity fill as fallback
    ctx.globalAlpha = 0.1;
    ctx.fill();
  } else {
    // Unknown / default
    ctx.globalAlpha = 0.15;
    ctx.fill();
  }

  // Always stroke the boundary
  ctx.globalAlpha = 0.4;
  ctx.stroke();
  ctx.restore();
}

const SANS_STACK = 'Arial, Helvetica, sans-serif';

/**
 * Map a DXF text entity's SHX font / style name to a CSS font family.
 *
 * CAD annotation text is authored in single-stroke SHX fonts (romans, simplex,
 * isocp, txt, …) that have no direct web equivalent. The renderer used to draw
 * every string in `monospace`, which makes annotations look nothing like the
 * source sheet - the vast majority of CAD text is a proportional SANS face.
 * So we map the common technical fonts to a sans stack, keep a monospace
 * fallback only for the genuinely fixed-width / GD&T / symbol fonts, and treat
 * the script families as cursive. Anything empty or unrecognised falls back to
 * SANS on purpose: defaulting to sans (not monospace) is what fixes the common
 * "wrong font" complaint on its own.
 *
 * The name is lower-cased and any trailing `.shx` is stripped before matching,
 * and `entity.font` (the resolved file) is preferred over `entity.style` (the
 * style-table name). Fully defensive: `undefined` -> sans.
 */
export function resolveFontFamily(entity: DxfEntity): string {
  const raw = (entity.font || entity.style || '')
    .toLowerCase()
    .replace(/\.shx$/, '')
    .trim();
  if (!raw) return SANS_STACK;
  // Symbol / GD&T fonts: no sane proportional fallback, keep monospace so the
  // glyph cells stay aligned.
  if (raw.includes('gdt') || raw.includes('symap') || raw.includes('symbol')) {
    return 'monospace';
  }
  // Script / handwriting / slanted styles.
  if (raw.includes('script') || raw.includes('italic')) return 'cursive';
  // Fixed-width CAD faces (monotxt and any explicitly "mono" family). Checked
  // before the sans default so "monotxt" is not mistaken for the "txt" sans.
  if (raw.includes('mono')) return 'monospace';
  // Everything else - romans, simplex, romant, romand, isocp, iso, txt, … -
  // is a proportional sans face.
  return SANS_STACK;
}

/** Below this a glyph is a smudge; drawing it adds noise, not information. */
const MIN_TEXT_PX = 0.5;

/**
 * On-screen size in px of a text entity's glyphs at the current viewport.
 *
 * The authored height, scaled. Nothing else - no readable band, no floor, no
 * ceiling.
 *
 * DO NOT REINTRODUCE A READABLE BAND HERE. It has been added twice and reverted
 * once, and it is the defect behind issue 426. `f936eace4` removed an 8..72px
 * band; `14aef60d5`, the next commit to touch this file and the last one before
 * v14.4.0 shipped, put it back with a docstring arguing it was intended - so
 * the release advertised the fix and shipped without it, and a reviewer reading
 * only HEAD found nothing wrong.
 *
 * The argument for a band is easy to make and wrong. It goes: a label too small
 * to read carries no information, so lift it to something legible. What that
 * misses is that annotation size is *authored*. A drafter sets a room tag at
 * 25 mm and a sheet title at 20000 mm, and the 800:1 between them is how the
 * sheet says which is which. Bounding both ends converts that 800:1 into a 9:1
 * - measured, on a bench drawing, fitted to an ordinary window - so the room
 * tag comes out 1.7x too big, the title 53x too small, and the two land at
 * nearly the same size. The drawing stops reading as a drawing. Small labels
 * are also the majority of a real floor plan's annotation, so lifting them to a
 * floor is exactly the reported "labels are much bigger".
 *
 * The band also hides itself. On a drawing small enough that it never binds,
 * the render is correct, which is how it passed review twice and why the
 * fixture that catches it (`fixtures/bench-drawings.ts`) had to be built with a
 * wide authored range on purpose.
 *
 * A label too small to read is handled where it belongs, in `renderText`, by
 * not drawing it: below half a pixel a glyph is a smudge, and the reader who
 * wants it zooms in - which is what zoom is for. A label so large it covers the
 * geometry is a true report of a drawing that says so, and the reader has a
 * size control for that.
 *
 * `textScale` is that control, and it multiplies the authored height, inside
 * everything else. That is the only place it works at every zoom and on every
 * label at once while leaving the proportions between labels alone. Multiplied
 * onto a banded result it could only slide a flattened sheet up and down,
 * giving the reader a way to make the wrongness smaller rather than a way to
 * make it right. Its own range is bounded at the control, in `clampTextScale`.
 */
export function textFontSize(entity: DxfEntity, vp: ViewportState, textScale = 1): number {
  return (entity.height ?? 2.5) * textScale * vp.scale;
}

export function renderText(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
  textScale = 1,
): void {
  if (!entity.start || !entity.text) return;
  const pos = worldToScreen(entity.start.x, entity.start.y, vp);
  const fontSize = textFontSize(entity, vp, textScale);
  // Sub-pixel: a glyph this small is a smudge, so drawing it adds noise rather
  // than information. Omitting it is also the cheapest cull the renderer has -
  // a zoomed-out plan otherwise lays out and fills every label in the drawing,
  // once per frame, for nothing anyone can read.
  if (fontSize < MIN_TEXT_PX) return;
  // MTEXT keeps its newlines (the backend maps MTEXT -> TEXT but preserves the
  // string), and canvas fillText ignores "\n", so render each line stacked.
  const lines = entity.text.split('\n');
  const lineH = fontSize * 1.25;

  ctx.save();
  ctx.font = `${fontSize}px ${resolveFontFamily(entity)}`;
  ctx.textBaseline = 'bottom';
  if (entity.rotation) {
    ctx.translate(pos.x, pos.y);
    ctx.rotate(-entity.rotation); // negate for screen Y-flip
    lines.forEach((ln, i) => ctx.fillText(ln, 0, i * lineH));
  } else {
    lines.forEach((ln, i) => ctx.fillText(ln, pos.x, pos.y + i * lineH));
  }
  ctx.restore();
}

function renderPoint(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
): void {
  if (!entity.start) return;
  const pos = worldToScreen(entity.start.x, entity.start.y, vp);
  ctx.beginPath();
  ctx.arc(pos.x, pos.y, 2, 0, Math.PI * 2);
  ctx.fill();
}

/** Half-diagonal in px of the placeholder marker drawn for a block reference. */
const INSERT_MARKER_PX = 5;

/**
 * Size in px of the block name drawn beside that marker, before the reader's
 * text multiplier.
 *
 * This is the file's second decision about how big text is drawn, and it is
 * deliberately not the one `textFontSize` makes. That one renders annotation
 * the drafter authored, so it follows `entity.height` and the zoom and nothing
 * else. This renders a caption on a placeholder the drafter never drew - a
 * marker standing in for geometry the client could not resolve - so it is
 * screen furniture, fixed in screen px like the marker it labels, and reading
 * `entity.height` here would size a label the drawing never asked for. It
 * follows `textDisplay` because it is still text on the sheet and a reader who
 * hid the labels meant this one too.
 */
const INSERT_LABEL_PX = 9;

/**
 * Render a block reference as a diamond marker, when there is nothing better.
 *
 * The marker is the fallback, not the block. When `blockDefs` holds the
 * definition, the reference's real geometry is drawn instead - placed by
 * `expandBlockReferences` and appended to the render list by the caller - and
 * this draws nothing, because a diamond on top of the door it stands for is
 * worse than either alone.
 *
 * A definition can be genuinely absent: filtered away, not exported, or named
 * by an INSERT whose block never arrived. Drawing nothing there would hide a
 * real object, so the marker stays. It cannot be given a world-space footprint
 * - `x_scale = 50` says the block was scaled fifty-fold but not what it was
 * scaled from - so its size stays fixed in screen pixels, while its aspect and
 * rotation follow the reference's transform. A point-symmetric marker still
 * cannot show mirroring, and no marker can show geometry it does not have.
 *
 * The name beside the marker is text, so it answers to `textDisplay` like the
 * rest: hidden when the reader hides text, scaled when they scale it. The
 * marker itself does not, because it stands for geometry rather than for a
 * label, and a reader who hid the labels still needs to see that something is
 * placed here.
 */
export function renderInsert(
  ctx: CanvasRenderingContext2D,
  entity: DxfEntity,
  vp: ViewportState,
  blockDefs?: BlockDefs,
  textDisplay?: TextDisplayState,
): void {
  if (!entity.start) return;
  if (blockDefs && isResolvedInsert(entity, blockDefs)) return;
  const pos = worldToScreen(entity.start.x, entity.start.y, vp);
  const norm = Math.max(Math.abs(entity.x_scale ?? 1), Math.abs(entity.y_scale ?? 1)) || 1;
  const rx = (INSERT_MARKER_PX * (entity.x_scale ?? 1)) / norm;
  const ry = (INSERT_MARKER_PX * (entity.y_scale ?? 1)) / norm;
  const rot = -(entity.rotation ?? 0); // negate for screen Y-flip
  const cos = Math.cos(rot);
  const sin = Math.sin(rot);
  // Top, right, bottom, left in the block's own axes, mapped through the
  // insert transform.
  const corners: [number, number][] = [
    [0, -ry],
    [rx, 0],
    [0, ry],
    [-rx, 0],
  ];

  ctx.save();
  ctx.beginPath();
  corners.forEach(([cx, cy], i) => {
    const x = pos.x + cx * cos - cy * sin;
    const y = pos.y + cx * sin + cy * cos;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.stroke();
  const td = textDisplay ?? DEFAULT_TEXT_DISPLAY;
  if (entity.block_name && td.visible) {
    ctx.font = `${INSERT_LABEL_PX * td.scale}px monospace`;
    ctx.textBaseline = 'top';
    ctx.fillText(
      entity.block_name,
      pos.x + INSERT_MARKER_PX + 2,
      pos.y - INSERT_MARKER_PX,
    );
  }
  ctx.restore();
}
