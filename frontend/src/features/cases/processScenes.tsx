// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Process scenes - a richer, step-specific illustration of the WORK a case step
// actually does, drawn as a small before -> after progression rather than a
// single object. Where StepScene draws one recognisable object keyed off the
// step's lucide icon, a process scene shows the process itself: a punch list
// burned down to zero, an inspection checklist turned all-green, an open
// non-conformance closed shut, loose documents gathered into one as-built
// record, a handover certificate signed off.
//
// Keyed by an explicit `scene` id set on the PlaybookStep (see types.ts), so a
// case opts in step by step. The runner falls back to StepScene when a step has
// no `scene`, so every other case is untouched. Same visual language as
// StepScene / caseScenes: the shared `0 0 120 84` viewBox, the faint blueprint
// grid, the shared `C` palette (white sheets, blue headers, green = done, red =
// open) and the always-light tile so the artwork reads the same in light and
// dark. The one deliberate difference from the icon scenes: a process scene
// spends its single highlight as a SPARING AMBER accent on the one key element
// that IS the payoff of the transformation (the zero, the pass rosette, the
// closed padlock, the assembled folder, the signing pen), while the before ->
// after connector is drawn in a quiet dark slate, so the eye lands on the
// result of each step.
//
// This is the reference set for the "Hand over and close out" case; other cases
// adopt it by adding their own scenes here and pointing their steps at them.

import { type ReactElement } from "react";
import clsx from "clsx";
import {
  C,
  Sheet,
  HeaderBand,
  RowBar,
  Chip,
  Badge,
  Stamp,
  Signature,
  WarnTri,
} from "./stepSceneParts";
import { Grid, VB } from "./StepScene";

/** A scene takes the one accent colour and returns its artwork group. */
type Scene = (accent: string) => ReactElement;

/** The sparing amber accent spent on the one key element of every process
 *  scene (the payoff of the transformation). PlaybookRunner renders process
 *  scenes without passing an accent, so this is what they use. */
const ACCENT = "#E0A02E";

/** Dark slate-blue used for the quiet before -> after connector, so the amber
 *  accent stays reserved for the result rather than the arrow. */
const SLATE = "#37475A";

/** Reusable rightward sequence arrow (before -> after), in quiet slate. */
function FlowArrow({ x, y }: { x: number; y: number }): ReactElement {
  return (
    <path
      d={`M${x} ${y} h13 M${x + 9} ${y - 4} l5 4 l-5 4`}
      stroke={SLATE}
      strokeWidth={2.4}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
}

/**
 * Bespoke per-step process scenes, keyed by the step's `scene` id. Every scene
 * uses the shared `C` palette for fills, the slate connector for the before ->
 * after flow, and exactly one amber `accent` element for the payoff, so the
 * linework matches the StepScene / CaseScene sets while the result stands out.
 */
export const PROCESS_SCENES: Record<string, Scene> = {
  // Clear the punch list: a list carrying open snags (red pins) is worked down
  // until it reads zero open - the amber "0" is the payoff.
  "punchlist-to-zero": (accent) => (
    <>
      {/* Before: punch list with three snags still open */}
      <Sheet x={8} y={12} w={44} h={60} />
      <HeaderBand x={8} y={12} w={44} h={10} fill={C.blue} />
      <RowBar x={14} y={15.5} w={18} h={3} fill={C.white} opacity={0.9} />
      <Chip
        x={35}
        y={14.5}
        w={12}
        h={7}
        r={2}
        fill={C.red}
        label="3"
        labelFill={C.white}
      />
      <Badge
        cx={15}
        cy={32}
        r={4}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={23} y={30.5} w={22} h={3.2} fill={C.grey3} />
      <circle
        cx={15}
        cy={44}
        r={3.4}
        fill={C.red}
        stroke={C.white}
        strokeWidth={1}
      />
      <RowBar x={23} y={42.5} w={22} h={3.2} fill={C.grey3} />
      <circle
        cx={15}
        cy={56}
        r={3.4}
        fill={C.red}
        stroke={C.white}
        strokeWidth={1}
      />
      <RowBar x={23} y={54.5} w={19} h={3.2} fill={C.grey3} />
      <circle
        cx={15}
        cy={67}
        r={3.4}
        fill={C.red}
        stroke={C.white}
        strokeWidth={1}
      />
      <RowBar x={23} y={65.5} w={16} h={3.2} fill={C.grey3} />
      <FlowArrow x={56} y={42} />
      {/* After: the list closed out, zero open (amber hero) */}
      <Sheet x={74} y={12} w={40} h={60} />
      <HeaderBand x={74} y={12} w={40} h={10} fill={C.green} />
      <RowBar x={80} y={15.5} w={16} h={3} fill={C.white} opacity={0.9} />
      <Badge cx={94} cy={44} r={15} fill={accent} glyph="none" />
      <text
        x={94}
        y={45}
        fill={C.white}
        fontSize={17}
        fontWeight={800}
        textAnchor="middle"
        dominantBaseline="central"
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        stroke="none"
      >
        0
      </text>
      <RowBar x={84} y={66} w={20} h={3} fill={C.grey3} />
    </>
  ),

  // Confirm the inspections passed: a part-signed checklist (two done, two still
  // to sign) turned all-green, crowned with an amber "passed" rosette.
  "inspections-all-green": (accent) => (
    <>
      {/* Before: inspection checklist, two points still pending */}
      <Sheet x={8} y={12} w={44} h={60} />
      <HeaderBand x={8} y={12} w={44} h={10} fill={C.blue} />
      <RowBar x={14} y={15.5} w={18} h={3} fill={C.white} opacity={0.9} />
      <Badge
        cx={15}
        cy={31}
        r={4}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={23} y={29.5} w={22} h={3.2} fill={C.grey3} />
      <Badge
        cx={15}
        cy={42}
        r={4}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={23} y={40.5} w={19} h={3.2} fill={C.grey3} />
      <rect
        x={11}
        y={49}
        width={8}
        height={8}
        rx={2}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <RowBar x={23} y={51.5} w={21} h={3.2} fill={C.grey3} />
      <rect
        x={11}
        y={61}
        width={8}
        height={8}
        rx={2}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <RowBar x={23} y={63.5} w={17} h={3.2} fill={C.grey3} />
      <FlowArrow x={56} y={42} />
      {/* After: every point signed off, an amber pass rosette below */}
      <Sheet x={74} y={12} w={40} h={60} />
      <HeaderBand x={74} y={12} w={40} h={10} fill={C.green} />
      <RowBar x={80} y={15.5} w={16} h={3} fill={C.white} opacity={0.9} />
      <Badge
        cx={82}
        cy={30}
        r={3.4}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={89} y={28.5} w={19} h={3} fill={C.grey3} />
      <Badge
        cx={82}
        cy={40}
        r={3.4}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={89} y={38.5} w={16} h={3} fill={C.grey3} />
      <Badge
        cx={82}
        cy={50}
        r={3.4}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={89} y={48.5} w={18} h={3} fill={C.grey3} />
      <path d="M90 62 L87 71 L93.5 68 Z" fill={accent} stroke="none" />
      <path d="M98 62 L101 71 L94.5 68 Z" fill={accent} stroke="none" />
      <Badge
        cx={94}
        cy={60}
        r={7}
        fill={accent}
        glyph="check"
        glyphFill={C.white}
      />
    </>
  ),

  // Close the non-conformances: an open NCR ticket (red, flagged OPEN) is
  // resolved and locked shut - the amber padlock is the payoff.
  "nonconformance-closing": (accent) => (
    <>
      {/* Before: an open non-conformance report */}
      <Sheet x={8} y={14} w={44} h={56} />
      <HeaderBand x={8} y={14} w={44} h={10} fill={C.red} />
      <RowBar x={14} y={17.5} w={16} h={3} fill={C.white} opacity={0.9} />
      <WarnTri
        cx={18}
        cy={40}
        w={15}
        fill={C.red}
        glyphFill={C.white}
        shadow={false}
      />
      <RowBar x={30} y={36} w={16} h={3} fill={C.grey3} />
      <RowBar x={30} y={44} w={13} h={3} fill={C.grey3} />
      <Chip
        x={14}
        y={58}
        w={24}
        h={8}
        r={2}
        fill={C.red}
        label="OPEN"
        labelFill={C.white}
      />
      <FlowArrow x={56} y={42} />
      {/* After: verified resolved (green check) and closed shut (amber padlock) */}
      <Sheet x={74} y={14} w={40} h={56} />
      <HeaderBand x={74} y={14} w={40} h={10} fill={C.green} />
      <RowBar x={80} y={17.5} w={16} h={3} fill={C.white} opacity={0.9} />
      <Badge cx={84} cy={39} r={7} fill={C.green} glyph="check" />
      <RowBar x={95} y={35} w={13} h={3} fill={C.grey3} />
      <RowBar x={95} y={43} w={10} h={3} fill={C.grey3} />
      <path
        d="M89 57 v-4 a5 5 0 0 1 10 0 v4"
        stroke={accent}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
      />
      <rect
        x={85}
        y={57}
        width={18}
        height={12}
        rx={2.5}
        fill={accent}
        stroke={C.white}
        strokeWidth={1}
      />
      <circle cx={94} cy={62} r={1.7} fill={C.white} stroke="none" />
      <rect
        x={93.2}
        y={62.6}
        width={1.6}
        height={3.6}
        rx={0.8}
        fill={C.white}
        stroke="none"
      />
    </>
  ),

  // Assemble the documents: loose as-built drawings, certificates and manuals
  // (distinct coloured headers) gathered into one indexed as-built record - the
  // amber folder is the payoff.
  "gather-handover-docs": (accent) => (
    <>
      {/* Before: loose documents of different kinds, scattered */}
      <Sheet x={8} y={12} w={24} h={19} shadow={false} />
      <HeaderBand x={8} y={12} w={24} h={6} fill={C.blueLight} />
      <RowBar x={12} y={22} w={15} h={2.6} fill={C.grey3} />
      <Sheet x={13} y={37} w={24} h={19} shadow={false} />
      <HeaderBand x={13} y={37} w={24} h={6} fill={C.ochre} />
      <RowBar x={17} y={47} w={15} h={2.6} fill={C.grey3} />
      <Sheet x={36} y={26} w={24} h={19} shadow={false} />
      <HeaderBand x={36} y={26} w={24} h={6} fill={C.green} />
      <RowBar x={40} y={36} w={15} h={2.6} fill={C.grey3} />
      <FlowArrow x={64} y={42} />
      {/* After: one indexed as-built record (amber folder), complete */}
      <path
        d="M78 35 h12 l3 -4 h16 a2 2 0 0 1 2 2 v4 H78 z"
        fill={C.ochre}
        stroke="none"
      />
      <path
        d="M76 40 h40 l-5 23 a2.5 2.5 0 0 1 -2.4 1.8 H83.4 a2.5 2.5 0 0 1 -2.4 -1.8 z"
        fill={accent}
        stroke="none"
      />
      <RowBar x={86} y={48} w={22} h={2.6} fill={C.white} opacity={0.9} />
      <RowBar x={86} y={54} w={16} h={2.6} fill={C.white} opacity={0.72} />
      <RowBar x={86} y={60} w={19} h={2.6} fill={C.white} opacity={0.58} />
      <Badge cx={110} cy={39} r={6} fill={C.green} glyph="check" />
    </>
  ),

  // Issue the handover: an unsigned certificate becomes a signed, sealed
  // handover - the amber pen doing the signing is the payoff.
  "issue-signed-handover": (accent) => (
    <>
      {/* Before: the certificate, still unsigned (empty dashed line) */}
      <Sheet x={8} y={12} w={42} h={60} />
      <HeaderBand x={8} y={12} w={42} h={11} fill={C.blue} />
      <RowBar x={14} y={16} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={15} y={32} w={28} h={3} fill={C.grey3} />
      <RowBar x={15} y={40} w={24} h={3} fill={C.grey3} />
      <path
        d="M15 58 H37"
        stroke={C.grey1}
        strokeWidth={1.8}
        strokeDasharray="2 3"
        fill="none"
        strokeLinecap="round"
      />
      <FlowArrow x={54} y={40} />
      {/* After: signed and sealed, the amber pen mid-signature */}
      <Sheet x={72} y={12} w={42} h={60} />
      <HeaderBand x={72} y={12} w={42} h={11} fill={C.blue} />
      <RowBar x={78} y={16} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={79} y={32} w={28} h={3} fill={C.grey3} />
      <RowBar x={79} y={40} w={24} h={3} fill={C.grey3} />
      <Stamp cx={104} cy={34} r={7} color={C.green} />
      <Signature x={79} y={56} w={22} color={C.blue} />
      <g transform="rotate(40 100 56)">
        <rect
          x={97}
          y={42}
          width={6}
          height={20}
          rx={2}
          fill={accent}
          stroke="none"
        />
        <path d="M97 62 L100 68 L103 62 Z" fill={C.blueDeep} stroke="none" />
        <rect
          x={97}
          y={41}
          width={6}
          height={4}
          rx={1}
          fill={C.blueDeep}
          stroke="none"
        />
      </g>
    </>
  ),
};

/** True when a step's `scene` id has a bespoke process scene to render. */
export function hasProcessScene(sceneId: string | undefined): boolean {
  return Boolean(sceneId && PROCESS_SCENES[sceneId]);
}

interface StepProcessSceneProps {
  /** The step's `scene` id; selects the bespoke process scene. */
  sceneId: string;
  /** Accent colour (hex) for the one key element per scene. Defaults to the
   *  sparing amber process accent. */
  accent?: string;
  /** Extra classes for the tile (height / width). */
  className?: string;
  /** Tailwind rounding class for the tile. Defaults to a large radius; the
   *  process strip passes a smaller one for its filmstrip thumbnails. */
  rounded?: string;
  /** Accessible label; the scene is decorative when omitted. */
  title?: string;
}

/**
 * Renders the bespoke process scene for a step in the same tile frame as
 * StepScene (same viewBox, blueprint grid and slate linework). Returns `null`
 * when the id has no scene, so callers fall back to StepScene.
 */
export function StepProcessScene({
  sceneId,
  accent = ACCENT,
  className,
  rounded = "rounded-2xl",
  title,
}: StepProcessSceneProps): ReactElement | null {
  const scene = PROCESS_SCENES[sceneId];
  if (!scene) return null;
  return (
    <div
      className={clsx(
        "relative flex items-center justify-center overflow-hidden bg-gradient-to-br from-white to-slate-50 ring-1 ring-inset ring-slate-900/[0.06]",
        rounded,
        className,
      )}
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
    >
      <svg
        viewBox={VB}
        className="h-full w-full p-3 text-slate-400"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <Grid />
        {scene(accent)}
      </svg>
    </div>
  );
}
