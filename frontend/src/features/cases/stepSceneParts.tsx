// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shared building blocks for StepScene - a small kit of concrete, coloured SVG
// primitives (sheets, chips, bars, badges, a magnifier, a stamp, ...). Every
// scene composes these so the whole set reads as one cohesive illustration
// language: recognisable construction objects with a little real colour, soft
// depth from an offset shadow, on the faint blueprint grid.
//
// All primitives set their OWN fill and stroke - they do not rely on the parent
// <svg> defaults (stroke=currentColor / fill=none), which stay in place only for
// the blueprint grid. Coordinates target the StepScene viewBox `0 0 120 84`.

import { type ReactElement } from 'react';

/**
 * The fixed illustration palette. Scenes are driven by these hexes (not by the
 * per-step accent) so every picture looks intentional and belongs to one family.
 */
export const C = {
  blue: '#1a6c9c', // blueprint blue (primary)
  blueLight: '#4aa6d8', // light blue
  blueDeep: '#0d4d74', // deep blue / ink
  ochre: '#cf8320', // construction ochre
  white: '#ffffff',
  panel: '#eaf2f8', // panel tint
  grey1: '#9fb3c2',
  grey2: '#b7c6d2',
  grey3: '#cdd9e2',
  green: '#2e9c6a',
  amber: '#e0a23a',
  red: '#d1495b',
  ink: '#16232e',
  shadow: '#0d3550', // used at 0.08 opacity for soft depth
  highlight: '#fff4d6', // soft focus band
  amberPill: '#fbeacb', // amber verdict pill fill
  pink: '#f3d0d5', // flagged-row chip fill
} as const;

/** A rectangle with only its top two corners rounded (for header bands). */
function topRoundedPath(x: number, y: number, w: number, h: number, r: number): string {
  return (
    `M${x} ${y + h} V${y + r} a${r} ${r} 0 0 1 ${r} ${-r} ` +
    `H${x + w - r} a${r} ${r} 0 0 1 ${r} ${r} V${y + h} Z`
  );
}

interface SheetProps {
  x: number;
  y: number;
  w: number;
  h: number;
  r?: number;
  fill?: string;
  stroke?: string;
  sw?: number;
  /** Draw a soft offset drop shadow behind the sheet. */
  shadow?: boolean;
}

/** A paper sheet / card with an optional soft drop shadow. */
export function Sheet({
  x,
  y,
  w,
  h,
  r = 4,
  fill = C.white,
  stroke = C.grey1,
  sw = 1.6,
  shadow = true,
}: SheetProps): ReactElement {
  return (
    <>
      {shadow && (
        <rect
          x={x + 2}
          y={y + 3}
          width={w}
          height={h}
          rx={r}
          fill={C.shadow}
          opacity={0.08}
          stroke="none"
        />
      )}
      <rect x={x} y={y} width={w} height={h} rx={r} fill={fill} stroke={stroke} strokeWidth={sw} />
    </>
  );
}

interface HeaderBandProps {
  x: number;
  y: number;
  w: number;
  h?: number;
  r?: number;
  fill?: string;
}

/** A coloured header band that sits on the top edge of a sheet. */
export function HeaderBand({
  x,
  y,
  w,
  h = 9,
  r = 4,
  fill = C.blue,
}: HeaderBandProps): ReactElement {
  return <path d={topRoundedPath(x, y, w, h, r)} fill={fill} stroke="none" />;
}

interface RowBarProps {
  x: number;
  y: number;
  w: number;
  h?: number;
  fill?: string;
  opacity?: number;
}

/** A rounded bar standing in for a line of text / a table row. */
export function RowBar({
  x,
  y,
  w,
  h = 4.4,
  fill = C.grey2,
  opacity = 1,
}: RowBarProps): ReactElement {
  return (
    <rect x={x} y={y} width={w} height={h} rx={h / 2} fill={fill} opacity={opacity} stroke="none" />
  );
}

interface ChipProps {
  x: number;
  y: number;
  w?: number;
  h?: number;
  r?: number;
  fill?: string;
  label?: string;
  labelFill?: string;
}

/** A small pill-shaped chip, optionally carrying a tiny mono label. */
export function Chip({
  x,
  y,
  w = 13,
  h = 7,
  r = 2,
  fill = C.blue,
  label,
  labelFill = C.white,
}: ChipProps): ReactElement {
  return (
    <>
      <rect x={x} y={y} width={w} height={h} rx={r} fill={fill} stroke="none" />
      {label && (
        <text
          x={x + w / 2}
          y={y + h / 2 + 0.2}
          fill={labelFill}
          fontSize={4.6}
          fontWeight={700}
          textAnchor="middle"
          dominantBaseline="central"
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          stroke="none"
        >
          {label}
        </text>
      )}
    </>
  );
}

interface BarProps {
  x: number;
  baseY: number;
  w: number;
  h: number;
  fill?: string;
  r?: number;
}

/** A vertical chart bar that grows upward from a baseline. */
export function Bar({ x, baseY, w, h, fill = C.blue, r = 1.2 }: BarProps): ReactElement {
  return <rect x={x} y={baseY - h} width={w} height={h} rx={r} fill={fill} stroke="none" />;
}

interface CylinderProps {
  cx: number;
  top: number;
  rx: number;
  ry: number;
  h: number;
  fill?: string;
  topFill?: string;
  shadow?: boolean;
}

/** A database cylinder: coloured body, lighter top disc, two faint bands. */
export function Cylinder({
  cx,
  top,
  rx,
  ry,
  h,
  fill = C.blue,
  topFill = C.blueLight,
  shadow = true,
}: CylinderProps): ReactElement {
  const bottom = top + h;
  return (
    <>
      {shadow && (
        <ellipse
          cx={cx + 2}
          cy={bottom + 3}
          rx={rx}
          ry={ry}
          fill={C.shadow}
          opacity={0.08}
          stroke="none"
        />
      )}
      <path
        d={`M${cx - rx} ${top} V${bottom} a${rx} ${ry} 0 0 0 ${2 * rx} 0 V${top} Z`}
        fill={fill}
        stroke="none"
      />
      <path
        d={`M${cx - rx} ${top + h * 0.36} a${rx} ${ry} 0 0 0 ${2 * rx} 0`}
        fill="none"
        stroke={C.white}
        strokeWidth={1}
        opacity={0.35}
      />
      <path
        d={`M${cx - rx} ${top + h * 0.68} a${rx} ${ry} 0 0 0 ${2 * rx} 0`}
        fill="none"
        stroke={C.white}
        strokeWidth={1}
        opacity={0.35}
      />
      <ellipse cx={cx} cy={top} rx={rx} ry={ry} fill={topFill} stroke={C.white} strokeWidth={0.8} />
    </>
  );
}

interface PillProps {
  x: number;
  y: number;
  w: number;
  h: number;
  fill?: string;
  stroke?: string;
  sw?: number;
}

/** A rounded status pill (outlined). */
export function Pill({
  x,
  y,
  w,
  h,
  fill = C.amberPill,
  stroke = C.amber,
  sw = 1.4,
}: PillProps): ReactElement {
  return (
    <rect x={x} y={y} width={w} height={h} rx={h / 2} fill={fill} stroke={stroke} strokeWidth={sw} />
  );
}

type GlyphKind = 'check' | 'plus' | 'warn' | 'x' | 'none';

function glyphPath(kind: GlyphKind, cx: number, cy: number, r: number, fill: string): ReactElement {
  if (kind === 'plus') {
    return (
      <path
        d={`M${cx} ${cy - r * 0.5} V${cy + r * 0.5} M${cx - r * 0.5} ${cy} H${cx + r * 0.5}`}
        stroke={fill}
        strokeWidth={r * 0.3}
        strokeLinecap="round"
        fill="none"
      />
    );
  }
  if (kind === 'x') {
    return (
      <path
        d={`M${cx - r * 0.38} ${cy - r * 0.38} l${r * 0.76} ${r * 0.76} M${cx + r * 0.38} ${
          cy - r * 0.38
        } l${-r * 0.76} ${r * 0.76}`}
        stroke={fill}
        strokeWidth={r * 0.28}
        strokeLinecap="round"
        fill="none"
      />
    );
  }
  if (kind === 'warn') {
    return (
      <>
        <path
          d={`M${cx} ${cy - r * 0.5} V${cy + r * 0.12}`}
          stroke={fill}
          strokeWidth={r * 0.28}
          strokeLinecap="round"
          fill="none"
        />
        <circle cx={cx} cy={cy + r * 0.42} r={r * 0.15} fill={fill} stroke="none" />
      </>
    );
  }
  // check
  return (
    <path
      d={`M${cx - r * 0.42} ${cy + r * 0.02} l${r * 0.28} ${r * 0.32} l${r * 0.56} ${-r * 0.62}`}
      stroke={fill}
      strokeWidth={r * 0.28}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  );
}

interface BadgeProps {
  cx: number;
  cy: number;
  r?: number;
  fill?: string;
  glyph?: GlyphKind;
  glyphFill?: string;
  shadow?: boolean;
}

/** A round status badge carrying a small white glyph (check / plus / warn / x). */
export function Badge({
  cx,
  cy,
  r = 8,
  fill = C.green,
  glyph = 'check',
  glyphFill = C.white,
  shadow = true,
}: BadgeProps): ReactElement {
  return (
    <>
      {shadow && (
        <circle cx={cx + 1.5} cy={cy + 2} r={r} fill={C.shadow} opacity={0.08} stroke="none" />
      )}
      <circle cx={cx} cy={cy} r={r} fill={fill} stroke={C.white} strokeWidth={1} />
      {glyph !== 'none' && glyphPath(glyph, cx, cy, r, glyphFill)}
    </>
  );
}

interface ShieldProps {
  cx: number;
  ty: number;
  w: number;
  h: number;
  fill?: string;
  stroke?: string;
  sw?: number;
  shadow?: boolean;
}

/** A security shield (flat top, curved point at the bottom). */
export function Shield({
  cx,
  ty,
  w,
  h,
  fill = C.green,
  stroke = 'none',
  sw = 0,
  shadow = true,
}: ShieldProps): ReactElement {
  const d =
    `M${cx - w / 2} ${ty} H${cx + w / 2} V${ty + h * 0.42} ` +
    `Q${cx + w / 2} ${ty + h * 0.82} ${cx} ${ty + h} ` +
    `Q${cx - w / 2} ${ty + h * 0.82} ${cx - w / 2} ${ty + h * 0.42} Z`;
  return (
    <>
      {shadow && <path d={d} transform="translate(2,3)" fill={C.shadow} opacity={0.08} stroke="none" />}
      <path d={d} fill={fill} stroke={stroke} strokeWidth={sw} strokeLinejoin="round" />
    </>
  );
}

interface MagnifierProps {
  cx: number;
  cy: number;
  r?: number;
  ring?: string;
  lens?: string;
}

/** A magnifier: tinted lens, white inner ring, a stubby handle. */
export function Magnifier({
  cx,
  cy,
  r = 10,
  ring = C.blue,
  lens = C.blueLight,
}: MagnifierProps): ReactElement {
  const hx = cx + r * 0.72;
  const hy = cy + r * 0.72;
  return (
    <>
      <circle cx={cx} cy={cy} r={r} fill={lens} fillOpacity={0.18} stroke={ring} strokeWidth={2.2} />
      <circle cx={cx} cy={cy} r={r * 0.6} fill="none" stroke={C.white} strokeWidth={1.4} />
      <path
        d={`M${hx} ${hy} l${r * 0.72} ${r * 0.72}`}
        stroke={ring}
        strokeWidth={3}
        strokeLinecap="round"
        fill="none"
      />
    </>
  );
}

interface StampProps {
  cx: number;
  cy: number;
  r?: number;
  color?: string;
}

/** An approval stamp: a coloured ring around a solid disc with a white check. */
export function Stamp({ cx, cy, r = 7, color = C.blue }: StampProps): ReactElement {
  return (
    <>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={1.8} />
      <circle cx={cx} cy={cy} r={r - 2} fill={color} stroke="none" />
      <path
        d={`M${cx - r * 0.4} ${cy + r * 0.02} l${r * 0.26} ${r * 0.3} l${r * 0.52} ${-r * 0.58}`}
        fill="none"
        stroke={C.white}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  );
}

interface WarnTriProps {
  cx: number;
  cy: number;
  w?: number;
  fill?: string;
  glyphFill?: string;
  shadow?: boolean;
}

/** A warning triangle with an exclamation, used for flags and anomalies. */
export function WarnTri({
  cx,
  cy,
  w = 16,
  fill = C.amber,
  glyphFill = C.white,
  shadow = true,
}: WarnTriProps): ReactElement {
  const h = w * 0.9;
  const d = `M${cx} ${cy - h / 2} L${cx + w / 2} ${cy + h / 2} L${cx - w / 2} ${cy + h / 2} Z`;
  return (
    <>
      {shadow && <path d={d} transform="translate(1.5,2)" fill={C.shadow} opacity={0.08} stroke="none" />}
      <path d={d} fill={fill} stroke="none" strokeLinejoin="round" />
      <path
        d={`M${cx} ${cy - h * 0.14} V${cy + h * 0.1}`}
        stroke={glyphFill}
        strokeWidth={w * 0.11}
        strokeLinecap="round"
        fill="none"
      />
      <circle cx={cx} cy={cy + h * 0.26} r={w * 0.06} fill={glyphFill} stroke="none" />
    </>
  );
}

interface SignatureProps {
  x: number;
  y: number;
  w: number;
  color?: string;
}

/** A hand-written signature squiggle. */
export function Signature({ x, y, w, color = C.blue }: SignatureProps): ReactElement {
  return (
    <path
      d={
        `M${x} ${y} c${w * 0.12} ${-6} ${w * 0.2} ${6} ${w * 0.3} 0 ` +
        `c${w * 0.08} ${-4.5} ${w * 0.16} ${3.5} ${w * 0.24} 0 ` +
        `c${w * 0.06} ${-2.5} ${w * 0.14} ${2.5} ${w * 0.22} ${0.5}`
      }
      fill="none"
      stroke={color}
      strokeWidth={1.8}
      strokeLinecap="round"
    />
  );
}

interface CubeProps {
  /** Centre x of the top face. */
  cx: number;
  /** Y of the top vertex of the top face. */
  ty: number;
  /** Half-width of the top rhombus. */
  w: number;
  /** Half-height of the top rhombus. */
  hh: number;
  /** Height of the vertical side faces. */
  depth: number;
  top?: string;
  left?: string;
  right?: string;
}

/** An isometric crate / material unit (three shaded faces for depth). */
export function Cube({
  cx,
  ty,
  w,
  hh,
  depth,
  top = C.blueLight,
  left = C.blue,
  right = C.blueDeep,
}: CubeProps): ReactElement {
  const my = ty + hh;
  const by = ty + 2 * hh;
  return (
    <>
      <path
        d={`M${cx - w} ${my} L${cx} ${by} L${cx} ${by + depth} L${cx - w} ${my + depth} Z`}
        fill={left}
        stroke="none"
      />
      <path
        d={`M${cx} ${by} L${cx + w} ${my} L${cx + w} ${my + depth} L${cx} ${by + depth} Z`}
        fill={right}
        stroke="none"
      />
      <path
        d={`M${cx} ${ty} L${cx + w} ${my} L${cx} ${by} L${cx - w} ${my} Z`}
        fill={top}
        stroke={C.white}
        strokeWidth={0.8}
      />
    </>
  );
}

interface StarProps {
  cx: number;
  cy: number;
  r: number;
  fill?: string;
}

/** A four-point sparkle star (for AI / suggestions / trophies). */
export function Star({ cx, cy, r, fill = C.ochre }: StarProps): ReactElement {
  const t = r * 0.34;
  return (
    <path
      d={
        `M${cx} ${cy - r} Q${cx + t} ${cy - t} ${cx + r} ${cy} ` +
        `Q${cx + t} ${cy + t} ${cx} ${cy + r} ` +
        `Q${cx - t} ${cy + t} ${cx - r} ${cy} ` +
        `Q${cx - t} ${cy - t} ${cx} ${cy - r} Z`
      }
      fill={fill}
      stroke="none"
    />
  );
}
