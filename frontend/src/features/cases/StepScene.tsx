// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// StepScene - a small concrete, colourful illustration of WHAT a case/how-to
// step does. Each scene depicts the real action (read the bill, sign it off,
// benchmark a rate, plant a milestone) with recognisable objects, a little real
// colour and soft depth, drawn from a shared kit of primitives (stepSceneParts).
//
// Keyed off the step's existing lucide `icon` name, so it needs no change to the
// playbook data files. Icons without a bespoke scene fall back to a framed
// version of the step's own glyph, so every step still gets a clean picture.
// The tile itself stays light in BOTH themes on purpose (like CaseArt / RoleArt)
// so the coloured artwork reads the same in light and dark.

import { type ReactElement } from "react";
import { type LucideIcon } from "lucide-react";
import clsx from "clsx";
import { iconFor } from "./icons";
import {
  C,
  Sheet,
  HeaderBand,
  RowBar,
  Chip,
  Bar,
  Cylinder,
  Pill,
  Badge,
  Shield,
  Magnifier,
  Stamp,
  WarnTri,
  Signature,
  Star,
  Cube,
} from "./stepSceneParts";

interface StepSceneProps {
  /** The step's lucide icon name; selects the scene. */
  icon?: string;
  /** Accent colour (hex) for the one highlight per scene. Defaults to oe-blue. */
  accent?: string;
  /** Extra classes for the tile (height / width). */
  className?: string;
  /** Tailwind rounding class for the tile. Defaults to a large radius; the
   *  process strip passes a smaller one for its filmstrip thumbnails. */
  rounded?: string;
  /** Fallback glyph when the icon has no bespoke scene (e.g. the how-to hub
   *  passes the module's own icon). Defaults to the cases icon resolver. */
  fallbackIcon?: LucideIcon;
  /** Accessible label; the scene is decorative when omitted. */
  title?: string;
}

/** Shared viewBox for every step/case scene (matches the primitive coordinates). */
export const VB = "0 0 120 84";

/** Faint blueprint grid, shared by every scene for a cohesive feel. */
export function Grid(): ReactElement {
  return (
    <g strokeWidth={0.6} opacity={0.16}>
      <path d="M0 21 H120 M0 42 H120 M0 63 H120" />
      <path d="M30 0 V84 M60 0 V84 M90 0 V84" />
    </g>
  );
}

type Scene = (accent: string) => ReactElement;

const SCENES: Record<string, Scene> = {
  // Report / analytics: a sheet with a coloured bar chart and one focus point.
  FileBarChart: (accent) => (
    <>
      <Sheet x={30} y={9} w={60} h={66} />
      <HeaderBand x={30} y={9} w={60} h={10} />
      <RowBar x={37} y={24} w={26} h={3.2} fill={C.grey3} />
      <Bar x={39} baseY={66} w={8} h={16} fill={C.blue} />
      <Bar x={51} baseY={66} w={8} h={28} fill={C.blueLight} />
      <Bar x={63} baseY={66} w={8} h={12} fill={C.grey2} />
      <Bar x={75} baseY={66} w={8} h={22} fill={C.ochre} />
      <path d="M37 66 H83" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <circle cx={55} cy={36} r={2.4} fill={accent} stroke="none" />
    </>
  ),

  // Validate / approve: a green shield with a white check.
  ShieldCheck: () => (
    <>
      <Shield cx={60} ty={12} w={44} h={54} fill={C.green} />
      <path
        d="M50 39 l7 7 l14 -16"
        stroke={C.white}
        strokeWidth={3.6}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Checklist: rows ticked off with green check badges, last still open.
  ListChecks: () => (
    <>
      <Sheet x={28} y={12} w={64} h={60} />
      <Badge
        cx={39}
        cy={27}
        r={5}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={49} y={25} w={34} h={4} fill={C.grey2} />
      <Badge
        cx={39}
        cy={43}
        r={5}
        fill={C.green}
        glyph="check"
        shadow={false}
      />
      <RowBar x={49} y={41} w={30} h={4} fill={C.grey2} />
      <rect
        x={34}
        y={54}
        width={10}
        height={10}
        rx={2.5}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <RowBar x={49} y={57} w={26} h={4} fill={C.grey3} />
    </>
  ),

  // Schedule: a calendar with a highlighted day and a due-date clock.
  CalendarClock: (accent) => (
    <>
      <Sheet x={20} y={16} w={54} h={52} />
      <HeaderBand x={20} y={16} w={54} h={11} fill={C.blue} />
      <rect
        x={31}
        y={12}
        width={4.5}
        height={8}
        rx={2}
        fill={C.blueDeep}
        stroke="none"
      />
      <rect
        x={59}
        y={12}
        width={4.5}
        height={8}
        rx={2}
        fill={C.blueDeep}
        stroke="none"
      />
      <circle cx={31} cy={38} r={2.4} fill={C.grey2} stroke="none" />
      <circle cx={43} cy={38} r={3.6} fill={accent} stroke="none" />
      <circle cx={55} cy={38} r={2.4} fill={C.grey2} stroke="none" />
      <circle cx={31} cy={50} r={2.4} fill={C.grey2} stroke="none" />
      <circle cx={43} cy={50} r={2.4} fill={C.grey2} stroke="none" />
      <circle cx={55} cy={50} r={2.4} fill={C.grey2} stroke="none" />
      <circle
        cx={83.5}
        cy={59}
        r={13}
        fill={C.shadow}
        opacity={0.08}
        stroke="none"
      />
      <circle
        cx={82}
        cy={57}
        r={13}
        fill={C.white}
        stroke={C.blue}
        strokeWidth={2.4}
      />
      <path
        d="M82 49 v8 l5 3"
        stroke={C.blue}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Inspection: a clipboard signed off with a big green check.
  ClipboardCheck: () => (
    <>
      <Sheet x={34} y={16} w={52} h={58} />
      <rect
        x={50}
        y={11}
        width={20}
        height={9}
        rx={3}
        fill={C.grey1}
        stroke="none"
      />
      <RowBar x={42} y={30} w={30} h={3.2} fill={C.grey3} />
      <RowBar x={42} y={39} w={24} h={3.2} fill={C.grey3} />
      <Badge cx={60} cy={55} r={13} fill={C.green} glyph="check" />
    </>
  ),

  // Models / layers: a stack of slabs, the top one highlighted.
  Layers: (accent) => (
    <>
      <path
        d="M60 51 L86 60 L60 69 L34 60 Z"
        fill={C.shadow}
        opacity={0.08}
        stroke="none"
      />
      <path
        d="M60 49 L86 58 L60 67 L34 58 Z"
        fill={C.grey2}
        stroke={C.white}
        strokeWidth={1}
      />
      <path
        d="M60 35 L86 44 L60 53 L34 44 Z"
        fill={C.blue}
        stroke={C.white}
        strokeWidth={1}
      />
      <path
        d="M60 21 L86 30 L60 39 L34 30 Z"
        fill={C.blueLight}
        stroke={accent}
        strokeWidth={1.6}
      />
    </>
  ),

  // Checklist to fill in: a clipboard with a bulleted list.
  ClipboardList: (accent) => (
    <>
      <Sheet x={34} y={16} w={52} h={58} />
      <rect
        x={50}
        y={11}
        width={20}
        height={9}
        rx={3}
        fill={C.grey1}
        stroke="none"
      />
      <circle cx={44} cy={32} r={2} fill={accent} stroke="none" />
      <RowBar x={50} y={30} w={28} h={3.6} fill={C.grey2} />
      <circle cx={44} cy={44} r={2} fill={C.grey1} stroke="none" />
      <RowBar x={50} y={42} w={24} h={3.6} fill={C.grey3} />
      <circle cx={44} cy={56} r={2} fill={C.grey1} stroke="none" />
      <RowBar x={50} y={54} w={20} h={3.6} fill={C.grey3} />
    </>
  ),

  // Compare / adjudicate: a balance with a weight in each pan.
  Scale: (accent) => (
    <>
      <path d="M60 16 V58" stroke={C.blueDeep} strokeWidth={3} fill="none" />
      <circle cx={60} cy={15} r={3} fill={C.blue} stroke="none" />
      <path
        d="M34 26 H86"
        stroke={C.blue}
        strokeWidth={2.6}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M34 26 V31 M86 26 V31"
        stroke={C.grey1}
        strokeWidth={1.4}
        fill="none"
      />
      <path d="M25 31 H43 L34 42 Z" fill={C.blueLight} stroke="none" />
      <path d="M77 31 H95 L86 42 Z" fill={C.grey2} stroke="none" />
      <circle cx={34} cy={29} r={2.4} fill={accent} stroke="none" />
      <circle cx={86} cy={29} r={2.4} fill={C.grey1} stroke="none" />
      <path
        d="M48 60 H72 M60 58 V60"
        stroke={C.blueDeep}
        strokeWidth={3}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Sign a document: a sheet with a signature, an ochre pen and a stamp.
  FileSignature: () => (
    <>
      <Sheet x={30} y={10} w={56} h={64} />
      <HeaderBand x={30} y={10} w={56} h={10} fill={C.blue} />
      <RowBar x={38} y={26} w={34} h={3.2} fill={C.grey3} />
      <RowBar x={38} y={34} w={30} h={3.2} fill={C.grey3} />
      <Signature x={38} y={54} w={30} color={C.blue} />
      <Stamp cx={74} cy={30} r={7} />
      <g transform="rotate(40 72 54)">
        <rect
          x={69}
          y={40}
          width={6}
          height={20}
          rx={2}
          fill={C.ochre}
          stroke="none"
        />
        <path d="M69 60 L72 66 L75 60 Z" fill={C.blueDeep} stroke="none" />
        <rect
          x={69}
          y={39}
          width={6}
          height={4}
          rx={1}
          fill={C.blueDeep}
          stroke="none"
        />
      </g>
    </>
  ),

  // Route and chase it: an envelope on a flight path to a due clock.
  Send: (accent) => (
    <>
      <rect
        x={16}
        y={30}
        width={40}
        height={28}
        rx={3}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <path d="M18 31 h36 l-18 13 z" fill={C.blueLight} stroke="none" />
      <path
        d="M16 32 l20 15 l20 -15"
        fill="none"
        stroke={C.blue}
        strokeWidth={1.6}
      />
      <path
        d="M58 36 C74 26 84 26 96 34"
        fill="none"
        stroke={accent}
        strokeWidth={2.2}
        strokeDasharray="1 5"
        strokeLinecap="round"
      />
      <path
        d="M91 29 l6 5 l-6 4"
        fill="none"
        stroke={accent}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={98}
        cy={52}
        r={11}
        fill={C.white}
        stroke={C.blue}
        strokeWidth={2.2}
      />
      <path
        d="M98 45 v7 l5 3"
        stroke={C.blue}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Cost database: a data cylinder feeding rate chips.
  Database: () => (
    <>
      <Cylinder cx={50} top={20} rx={20} ry={6.5} h={40} />
      <Chip x={78} y={30} w={18} h={7} fill={C.ochre} />
      <Chip x={78} y={42} w={18} h={7} fill={C.blueLight} />
      <Chip x={78} y={54} w={18} h={7} fill={C.grey2} />
    </>
  ),

  // Grid / BOQ table: a table with a highlighted total cell.
  Table2: (accent) => (
    <>
      <Sheet x={24} y={16} w={72} h={52} />
      <HeaderBand x={24} y={16} w={72} h={11} fill={C.blue} />
      <path
        d="M48 27 V68 M72 27 V68"
        stroke={C.grey3}
        strokeWidth={1.2}
        fill="none"
      />
      <path
        d="M24 40 H96 M24 54 H96"
        stroke={C.grey3}
        strokeWidth={1.2}
        fill="none"
      />
      <RowBar x={29} y={20} w={14} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={53} y={20} w={14} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={77} y={20} w={14} h={3} fill={C.white} opacity={0.9} />
      <Chip x={28} y={44} w={14} h={5} r={1.5} fill={C.grey2} />
      <Chip x={52} y={44} w={14} h={5} r={1.5} fill={C.ochre} />
      <Chip x={76} y={44} w={14} h={5} r={1.5} fill={accent} />
    </>
  ),

  // File the answer: a document dropping into an open folder, with a check.
  FolderOpen: (accent) => (
    <>
      <Sheet x={44} y={8} w={34} h={26} shadow={false} />
      <RowBar x={50} y={16} w={22} h={3} fill={C.grey3} />
      <RowBar x={50} y={23} w={18} h={3} fill={C.grey3} />
      <path
        d="M61 36 v6 M57 39 l4 4 l4 -4"
        stroke={accent}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M20 48 h18 l5 -6 h30 a3 3 0 0 1 3 3 v6 H20 z"
        fill={C.ochre}
        stroke="none"
      />
      <path
        d="M17 52 h72 l-8 22 a3 3 0 0 1 -3 2 H25 a3 3 0 0 1 -3 -2 z"
        fill={C.amber}
        stroke="none"
      />
      <Badge cx={86} cy={45} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Materials / components: a small stack of crates, top one highlighted.
  Boxes: (accent) => (
    <>
      <Cube cx={40} ty={44} w={16} hh={8} depth={16} />
      <Cube cx={72} ty={44} w={16} hh={8} depth={16} />
      <Cube cx={56} ty={22} w={16} hh={8} depth={16} top={accent} />
    </>
  ),

  // People / team: three figures, the lead one highlighted.
  Users: () => (
    <>
      <circle cx={40} cy={34} r={9} fill={C.grey2} stroke="none" />
      <path
        d="M28 62 c0 -10 5 -16 12 -16 s12 6 12 16 z"
        fill={C.grey2}
        stroke="none"
      />
      <circle cx={80} cy={34} r={9} fill={C.grey2} stroke="none" />
      <path
        d="M68 62 c0 -10 5 -16 12 -16 s12 6 12 16 z"
        fill={C.grey2}
        stroke="none"
      />
      <circle
        cx={60}
        cy={30}
        r={10.5}
        fill={C.blue}
        stroke={C.white}
        strokeWidth={1}
      />
      <path
        d="M45 65 c0 -12 6 -19 15 -19 s15 7 15 19 z"
        fill={C.blue}
        stroke={C.white}
        strokeWidth={1}
      />
    </>
  ),

  // Payment / rate: a green banknote with an ochre coin.
  Banknote: () => (
    <>
      <rect
        x={18}
        y={26}
        width={58}
        height={32}
        rx={4}
        fill={C.green}
        stroke="none"
      />
      <rect
        x={22}
        y={30}
        width={50}
        height={24}
        rx={2.5}
        fill="none"
        stroke={C.white}
        strokeWidth={1.2}
        opacity={0.7}
      />
      <circle
        cx={47}
        cy={42}
        r={8}
        fill="none"
        stroke={C.white}
        strokeWidth={1.6}
        opacity={0.85}
      />
      <circle
        cx={85}
        cy={53}
        r={13}
        fill={C.shadow}
        opacity={0.08}
        stroke="none"
      />
      <circle
        cx={84}
        cy={52}
        r={13}
        fill={C.ochre}
        stroke={C.white}
        strokeWidth={1.2}
      />
      <circle
        cx={84}
        cy={52}
        r={9}
        fill="none"
        stroke={C.white}
        strokeWidth={1.4}
        opacity={0.7}
      />
      <circle cx={84} cy={52} r={2.6} fill={C.white} stroke="none" />
    </>
  ),

  // Risk / warning: an amber shield with a white exclamation.
  ShieldAlert: () => (
    <>
      <Shield cx={60} ty={12} w={44} h={54} fill={C.amber} />
      <path
        d="M60 28 V45"
        stroke={C.white}
        strokeWidth={4}
        strokeLinecap="round"
        fill="none"
      />
      <circle cx={60} cy={53} r={2.6} fill={C.white} stroke="none" />
    </>
  ),

  // Invoice / receipt: a torn-edge receipt read under a magnifier.
  ReceiptText: (accent) => (
    <>
      <path
        d="M36 12 H80 V60 l-5.5 4 l-5.5 -4 l-5.5 4 l-5.5 -4 l-5.5 4 l-5.5 -4 l-5.5 4 l-5.5 -4 z"
        transform="translate(2,3)"
        fill={C.shadow}
        opacity={0.08}
        stroke="none"
      />
      <path
        d="M36 12 H80 V60 l-5.5 4 l-5.5 -4 l-5.5 4 l-5.5 -4 l-5.5 4 l-5.5 -4 l-5.5 4 l-5.5 -4 z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <rect x={36} y={12} width={44} height={8} fill={C.blue} stroke="none" />
      <RowBar x={42} y={27} w={30} h={3} fill={C.grey3} />
      <RowBar x={42} y={34} w={26} h={3} fill={C.grey3} />
      <RowBar x={42} y={45} w={16} h={4} fill={C.ochre} />
      <RowBar x={62} y={45} w={10} h={4} fill={accent} />
      <Magnifier cx={82} cy={52} r={11} />
    </>
  ),

  // Trend line: a line graph with a translucent area fill.
  LineChart: (accent) => (
    <>
      <Sheet x={26} y={12} w={68} h={58} />
      <path d="M34 22 V60 H88" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path
        d="M34 52 L46 44 L58 48 L70 34 L82 28 L82 60 L34 60 Z"
        fill={C.blueLight}
        opacity={0.22}
        stroke="none"
      />
      <path
        d="M34 52 L46 44 L58 48 L70 34 L82 28"
        fill="none"
        stroke={C.blue}
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={46} cy={44} r={2} fill={C.blue} stroke="none" />
      <circle cx={58} cy={48} r={2} fill={C.blue} stroke="none" />
      <circle cx={70} cy={34} r={2} fill={C.blue} stroke="none" />
      <circle cx={82} cy={28} r={2.6} fill={accent} stroke="none" />
    </>
  ),

  // Merge / combine: two sheets converging into one, signed off.
  Combine: () => (
    <>
      <Sheet x={16} y={14} w={30} h={26} shadow={false} />
      <HeaderBand x={16} y={14} w={30} h={7} fill={C.blue} />
      <Sheet x={16} y={46} w={30} h={26} shadow={false} />
      <HeaderBand x={16} y={46} w={30} h={7} fill={C.grey1} />
      <path
        d="M50 27 C62 30 64 38 72 42"
        fill="none"
        stroke={C.blue}
        strokeWidth={2}
        strokeLinecap="round"
      />
      <path
        d="M50 59 C62 56 64 48 72 44"
        fill="none"
        stroke={C.grey1}
        strokeWidth={2}
        strokeLinecap="round"
      />
      <path
        d="M69 38 l6 5 l-6 4"
        fill="none"
        stroke={C.blue}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={78} y={30} w={30} h={28} />
      <HeaderBand x={78} y={30} w={30} h={7} fill={C.blue} />
      <Badge cx={104} cy={34} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Estimate / calculate: a calculator with a highlighted equals key.
  Calculator: (accent) => (
    <>
      <rect
        x={40}
        y={10}
        width={40}
        height={64}
        rx={6}
        fill={C.blue}
        stroke="none"
      />
      <rect
        x={46}
        y={16}
        width={28}
        height={12}
        rx={2}
        fill={C.blueDeep}
        stroke="none"
      />
      <RowBar x={49} y={20} w={16} h={3.5} fill={C.blueLight} />
      <rect
        x={46}
        y={35}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={57}
        y={35}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={68}
        y={35}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={46}
        y={47}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={57}
        y={47}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={68}
        y={47}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={46}
        y={59}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={57}
        y={59}
        width={8}
        height={8}
        rx={1.6}
        fill={C.white}
        opacity={0.85}
        stroke="none"
      />
      <rect
        x={68}
        y={59}
        width={8}
        height={8}
        rx={1.6}
        fill={accent}
        stroke="none"
      />
    </>
  ),

  // Forecast / growth: a rising line breaking upward with an accent arrow.
  TrendingUp: (accent) => (
    <>
      <path d="M28 20 V62 H92" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path
        d="M34 54 L50 42 L62 48 L84 26 L84 62 L34 62 Z"
        fill={C.green}
        opacity={0.16}
        stroke="none"
      />
      <path
        d="M34 54 L50 42 L62 48 L84 26"
        fill="none"
        stroke={C.blue}
        strokeWidth={2.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M77 26 h8 v8"
        fill="none"
        stroke={accent}
        strokeWidth={2.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={50} cy={42} r={2.4} fill={C.blue} stroke="none" />
      <circle cx={62} cy={48} r={2.4} fill={C.blue} stroke="none" />
    </>
  ),

  // Measure / takeoff: an ochre ruler over a dimension line.
  Ruler: (accent) => (
    <>
      <rect
        x={18}
        y={30}
        width={84}
        height={16}
        rx={2.5}
        fill={C.ochre}
        stroke="none"
      />
      <rect
        x={18}
        y={30}
        width={84}
        height={16}
        rx={2.5}
        fill="none"
        stroke={C.white}
        strokeWidth={1}
        opacity={0.5}
      />
      <path
        d="M28 30 V40 M38 30 V36 M48 30 V40 M58 30 V36 M68 30 V40 M78 30 V36 M88 30 V40"
        stroke={C.white}
        strokeWidth={1.4}
        opacity={0.85}
        fill="none"
      />
      <path
        d="M18 58 H102 M18 54 V62 M102 54 V62"
        stroke={accent}
        strokeWidth={2}
        fill="none"
      />
      <path
        d="M22 58 l4 -3 M22 58 l4 3 M98 58 l-4 -3 M98 58 l-4 3"
        stroke={accent}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Delivery accepted: a crate with a green check badge.
  PackageCheck: () => (
    <>
      <Cube
        cx={50}
        ty={20}
        w={18}
        hh={9}
        depth={20}
        top={C.grey3}
        left={C.grey2}
        right={C.grey1}
      />
      <path
        d="M50 38 V58"
        stroke={C.ochre}
        strokeWidth={1.8}
        fill="none"
        opacity={0.85}
      />
      <Badge cx={82} cy={50} r={11} fill={C.green} glyph="check" />
    </>
  ),

  // Discuss / comment: a speech bubble with a reply.
  MessageSquare: (accent) => (
    <>
      <path
        d="M22 16 h58 a5 5 0 0 1 5 5 v22 a5 5 0 0 1 -5 5 H44 l-12 10 v-10 h-5 a5 5 0 0 1 -5 -5 V21 a5 5 0 0 1 5 -5 z"
        fill={C.white}
        stroke={C.blue}
        strokeWidth={1.8}
      />
      <RowBar x={30} y={25} w={44} h={3.4} fill={C.blue} opacity={0.75} />
      <RowBar x={30} y={33} w={34} h={3.4} fill={C.grey3} />
      <path
        d="M80 50 h20 a4 4 0 0 1 4 4 v9 a4 4 0 0 1 -4 4 h-9 l-7 5 v-5 h-4 a4 4 0 0 1 -4 -4 V54 a4 4 0 0 1 4 -4 z"
        fill={accent}
        stroke="none"
      />
    </>
  ),

  // Site / safety: an ochre hard hat with a badge on the front.
  HardHat: (accent) => (
    <>
      <path d="M30 50 a30 24 0 0 1 60 0 z" fill={C.ochre} stroke="none" />
      <path
        d="M48 50 V32 M60 50 V29 M72 50 V32"
        stroke={C.white}
        strokeWidth={2}
        opacity={0.7}
        fill="none"
      />
      <rect
        x={54}
        y={42}
        width={12}
        height={8}
        rx={1.5}
        fill={accent}
        stroke="none"
      />
      <path
        d="M20 50 h80 a3 3 0 0 1 0 6 H20 a3 3 0 0 1 0 -6 z"
        fill={C.amber}
        stroke="none"
      />
    </>
  ),

  // Document: a sheet with a folded corner and a titled body.
  FileText: (accent) => (
    <>
      <path
        d="M40 8 h22 l16 16 v48 a2 2 0 0 1 -2 2 H40 a2 2 0 0 1 -2 -2 V10 a2 2 0 0 1 2 -2 z"
        transform="translate(2,3)"
        fill={C.shadow}
        opacity={0.08}
        stroke="none"
      />
      <path
        d="M40 8 h22 l16 16 v48 a2 2 0 0 1 -2 2 H40 a2 2 0 0 1 -2 -2 V10 a2 2 0 0 1 2 -2 z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <path
        d="M62 8 l16 16 h-16 z"
        fill={C.panel}
        stroke={C.grey1}
        strokeWidth={1}
      />
      <RowBar x={46} y={34} w={26} h={4} fill={accent} />
      <RowBar x={46} y={44} w={26} h={3} fill={C.grey3} />
      <RowBar x={46} y={52} w={22} h={3} fill={C.grey3} />
      <RowBar x={46} y={60} w={24} h={3} fill={C.grey3} />
    </>
  ),

  // Locate / pinpoint: a target crosshair on a faint drawing.
  Crosshair: (accent) => (
    <>
      <Sheet x={24} y={12} w={72} h={60} fill={C.panel} shadow={false} />
      <path
        d="M32 24 H72 M32 60 H88 M42 20 V64"
        stroke={C.grey3}
        strokeWidth={1.2}
        fill="none"
      />
      <circle
        cx={66}
        cy={44}
        r={18}
        fill="none"
        stroke={accent}
        strokeWidth={2.2}
      />
      <circle
        cx={66}
        cy={44}
        r={9}
        fill="none"
        stroke={C.blue}
        strokeWidth={2}
      />
      <path
        d="M66 20 V34 M66 54 V68 M42 44 H56 M76 44 H90"
        stroke={C.blue}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={66} cy={44} r={3} fill={C.red} stroke="none" />
    </>
  ),

  // Time / deadline: a clock face with an accent hand.
  Clock: (accent) => (
    <>
      <circle
        cx={62}
        cy={44}
        r={26}
        fill={C.shadow}
        opacity={0.08}
        stroke="none"
      />
      <circle
        cx={60}
        cy={42}
        r={26}
        fill={C.white}
        stroke={C.blue}
        strokeWidth={2.6}
      />
      <path
        d="M60 20 v4 M60 60 v4 M38 42 h4 M78 42 h4"
        stroke={C.grey1}
        strokeWidth={2}
        fill="none"
      />
      <path
        d="M60 42 V26"
        stroke={C.blueDeep}
        strokeWidth={2.6}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M60 42 l12 6"
        stroke={accent}
        strokeWidth={2.6}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={60} cy={42} r={2.4} fill={C.blueDeep} stroke="none" />
    </>
  ),

  // Project / company: two buildings with windows, one lit.
  Building2: (accent) => (
    <>
      <rect
        x={30}
        y={16}
        width={34}
        height={56}
        rx={2}
        fill={C.blue}
        stroke="none"
      />
      <rect
        x={64}
        y={34}
        width={24}
        height={38}
        rx={2}
        fill={C.grey2}
        stroke="none"
      />
      <path
        d="M37 25 h6 M48 25 h6 M37 35 h6 M48 35 h6 M37 45 h6 M48 45 h6 M37 55 h6 M48 55 h6"
        stroke={C.blueLight}
        strokeWidth={3.4}
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M37 25 h6"
        stroke={accent}
        strokeWidth={3.4}
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M69 44 h5 M79 44 h5 M69 54 h5 M79 54 h5 M69 64 h5 M79 64 h5"
        stroke={C.white}
        strokeWidth={3}
        strokeLinecap="round"
        fill="none"
        opacity={0.8}
      />
      <path
        d="M24 72 H96"
        stroke={C.grey1}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Compare versions / diff: two sheets with -/+ lines and crossing arrows.
  GitCompareArrows: (accent) => (
    <>
      <Sheet x={16} y={14} w={32} h={54} shadow={false} />
      <Sheet x={72} y={14} w={32} h={54} shadow={false} />
      <path
        d="M22 27 h6"
        stroke={C.red}
        strokeWidth={2.2}
        strokeLinecap="round"
        fill="none"
      />
      <RowBar x={31} y={25.5} w={12} h={3.2} fill={C.pink} />
      <path
        d="M22 37 h6"
        stroke={C.red}
        strokeWidth={2.2}
        strokeLinecap="round"
        fill="none"
      />
      <RowBar x={31} y={35.5} w={10} h={3.2} fill={C.pink} />
      <RowBar x={22} y={47} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={55} w={16} h={3.2} fill={C.grey3} />
      <path
        d="M78 27 h6 M81 24 v6"
        stroke={C.green}
        strokeWidth={2.2}
        strokeLinecap="round"
        fill="none"
      />
      <RowBar x={88} y={25.5} w={11} h={3.2} fill={C.green} opacity={0.3} />
      <path
        d="M78 37 h6 M81 34 v6"
        stroke={C.green}
        strokeWidth={2.2}
        strokeLinecap="round"
        fill="none"
      />
      <RowBar x={88} y={35.5} w={9} h={3.2} fill={C.green} opacity={0.3} />
      <RowBar x={78} y={47} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={78} y={55} w={16} h={3.2} fill={C.grey3} />
      <path
        d="M51 34 H68 M64 30 l5 4 l-5 4"
        stroke={C.blue}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M69 50 H52 M56 46 l-5 4 l5 4"
        stroke={accent}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Single unit / item: one highlighted crate.
  Box: (accent) => (
    <>
      <Cube cx={60} ty={26} w={20} hh={10} depth={22} top={accent} />
    </>
  ),

  // AI suggestion: a card with a suggestion chip and sparkles.
  Sparkles: (accent) => (
    <>
      <Sheet x={28} y={20} w={52} h={44} />
      <RowBar x={36} y={30} w={30} h={3.4} fill={C.grey3} />
      <RowBar x={36} y={38} w={24} h={3.4} fill={C.grey3} />
      <Chip x={36} y={48} w={22} h={9} fill={C.blueLight} label="AI" />
      <Star cx={88} cy={22} r={7} fill={C.ochre} />
      <Star cx={99} cy={37} r={4.5} fill={C.blueLight} />
      <Star cx={82} cy={54} r={4} fill={accent} />
    </>
  ),

  // Site diary: a spiral notebook written up with an ochre pen.
  NotebookPen: (accent) => (
    <>
      <Sheet x={32} y={16} w={54} h={56} />
      <HeaderBand x={32} y={16} w={54} h={9} fill={C.blue} />
      <path
        d="M40 14 v8 M50 14 v8 M60 14 v8 M70 14 v8"
        stroke={C.grey1}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <RowBar x={40} y={34} w={30} h={3} fill={C.grey3} />
      <RowBar x={40} y={42} w={26} h={3} fill={C.grey3} />
      <path
        d="M40 54 c4 -3 8 3 12 0 c4 -3 8 2 11 0"
        stroke={accent}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <g transform="rotate(38 70 52)">
        <rect
          x={67}
          y={38}
          width={6}
          height={20}
          rx={2}
          fill={C.ochre}
          stroke="none"
        />
        <path d="M67 58 L70 64 L73 58 Z" fill={C.blueDeep} stroke="none" />
        <rect
          x={67}
          y={37}
          width={6}
          height={4}
          rx={1}
          fill={C.blueDeep}
          stroke="none"
        />
      </g>
    </>
  ),

  // Raise the request: an RFI sheet with a question bubble.
  HelpCircle: (accent) => (
    <>
      <Sheet x={20} y={20} w={48} h={50} />
      <HeaderBand x={20} y={20} w={48} h={9} fill={C.blue} />
      <RowBar x={27} y={36} w={30} h={3.2} fill={C.grey3} />
      <RowBar x={27} y={44} w={24} h={3.2} fill={C.grey3} />
      <circle cx={57} cy={54} r={2} fill={accent} stroke="none" />
      <path
        d="M72 16 h26 a6 6 0 0 1 6 6 v16 a6 6 0 0 1 -6 6 h-10 l-8 7 v-7 h-2 a6 6 0 0 1 -6 -6 V22 a6 6 0 0 1 6 -6 z"
        fill={C.blue}
        stroke="none"
      />
      <path
        d="M83 26 a4.5 4.5 0 1 1 6.5 4 c-1.6 1 -2.2 2 -2.2 3.6"
        stroke={C.white}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={87.3} cy={38} r={1.7} fill={C.white} stroke="none" />
    </>
  ),

  // Agreement / award: two sleeves meeting under a signed-off seal.
  Handshake: (accent) => (
    <>
      <path d="M14 47 h22 l8 6 -8 6 H14 z" fill={C.blue} stroke="none" />
      <path d="M106 47 h-22 l-8 6 8 6 h22 z" fill={C.ochre} stroke="none" />
      <rect
        x={46}
        y={45}
        width={28}
        height={16}
        rx={6}
        fill={C.grey3}
        stroke={C.grey1}
        strokeWidth={1.2}
      />
      <path
        d="M53 49 v8 M59 49 v8 M65 49 v8 M71 49 v8"
        stroke={accent}
        strokeWidth={1.4}
        fill="none"
      />
      <Badge cx={60} cy={26} r={9} fill={C.green} glyph="check" />
    </>
  ),

  // Milestone / flag: a planted flag with a milestone star.
  Flag: (accent) => (
    <>
      <path
        d="M46 16 V70"
        stroke={C.blueDeep}
        strokeWidth={3}
        fill="none"
        strokeLinecap="round"
      />
      <path d="M46 18 h32 l-7 8 7 8 H46 z" fill={C.red} stroke="none" />
      <Star cx={56} cy={26} r={4} fill={accent} />
      <path
        d="M30 70 H74"
        stroke={C.grey1}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Spreadsheet: a green-headed sheet grid with a highlighted cell.
  FileSpreadsheet: (accent) => (
    <>
      <Sheet x={26} y={12} w={68} h={60} />
      <HeaderBand x={26} y={12} w={68} h={10} fill={C.green} />
      <path
        d="M26 34 H94 M26 46 H94 M26 58 H94"
        stroke={C.grey3}
        strokeWidth={1.2}
        fill="none"
      />
      <path
        d="M48 22 V72 M72 22 V72"
        stroke={C.grey3}
        strokeWidth={1.2}
        fill="none"
      />
      <RowBar x={31} y={16} w={12} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={54} y={16} w={12} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={77} y={16} w={12} h={3} fill={C.white} opacity={0.9} />
      <rect
        x={74}
        y={35}
        width={18}
        height={10}
        fill={C.green}
        opacity={0.22}
        stroke="none"
      />
      <Chip x={30} y={38} w={12} h={5} r={1.5} fill={C.grey2} />
      <Chip x={52} y={38} w={12} h={5} r={1.5} fill={C.grey2} />
      <Chip x={76} y={49} w={14} h={5} r={1.5} fill={accent} />
    </>
  ),

  // Approved document: a verdict sheet with a status pill and a stamp.
  FileCheck: () => (
    <>
      <Sheet x={30} y={10} w={58} h={64} />
      <HeaderBand x={30} y={10} w={58} h={10} fill={C.blue} />
      <Pill x={44} y={24} w={30} h={10} />
      <Badge
        cx={49}
        cy={29}
        r={3.6}
        fill={C.amber}
        glyph="warn"
        glyphFill={C.white}
        shadow={false}
      />
      <circle cx={40} cy={45} r={2.2} fill={C.red} stroke="none" />
      <RowBar x={46} y={43.5} w={22} h={3.2} fill={C.pink} />
      <circle cx={40} cy={54} r={2.2} fill={C.green} stroke="none" />
      <RowBar x={46} y={52.5} w={26} h={3.2} fill={C.green} opacity={0.3} />
      <circle cx={40} cy={63} r={2.2} fill={C.green} stroke="none" />
      <RowBar x={46} y={61.5} w={20} h={3.2} fill={C.green} opacity={0.3} />
      <Stamp cx={76} cy={62} r={7} />
    </>
  ),

  // Certificate: a rosette seal with a white check and ribbon tails.
  BadgeCheck: (accent) => (
    <>
      <path d="M52 54 L46 74 L56 68 Z" fill={C.ochre} stroke="none" />
      <path d="M68 54 L74 74 L64 68 Z" fill={C.ochre} stroke="none" />
      <circle cx={60} cy={38} r={22} fill={C.blue} stroke="none" />
      <circle
        cx={60}
        cy={38}
        r={22}
        fill="none"
        stroke={C.blueLight}
        strokeWidth={2}
        strokeDasharray="2 3"
      />
      <circle cx={60} cy={38} r={15} fill={C.blueLight} stroke="none" />
      <path
        d="M52 38 l5 5 l11 -12"
        stroke={C.white}
        strokeWidth={3.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Star cx={60} cy={15} r={4} fill={accent} />
    </>
  ),

  // Warning / anomaly: a bold amber warning triangle.
  AlertTriangle: () => <WarnTri cx={60} cy={44} w={52} fill={C.amber} />,

  // Adjudication / decision: a gavel striking a sound block.
  Gavel: (accent) => (
    <>
      <rect
        x={30}
        y={62}
        width={38}
        height={7}
        rx={2}
        fill={C.blueDeep}
        stroke="none"
      />
      <g transform="rotate(-38 66 40)">
        <rect
          x={56}
          y={30}
          width={22}
          height={16}
          rx={3}
          fill={C.blue}
          stroke="none"
        />
        <rect
          x={53}
          y={31}
          width={4}
          height={14}
          rx={1.5}
          fill={C.blueDeep}
          stroke="none"
        />
        <rect
          x={77}
          y={31}
          width={4}
          height={14}
          rx={1.5}
          fill={C.blueDeep}
          stroke="none"
        />
        <rect
          x={65}
          y={44}
          width={5}
          height={30}
          rx={2.5}
          fill={C.ochre}
          stroke="none"
        />
      </g>
      <path
        d="M40 50 l-5 -4 M48 46 l-3 -6 M56 48 l0 -7"
        stroke={accent}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Document set: a stack of offset sheets, front one titled.
  FileStack: () => (
    <>
      <rect
        x={30}
        y={16}
        width={46}
        height={50}
        rx={4}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.4}
      />
      <rect
        x={36}
        y={20}
        width={46}
        height={50}
        rx={4}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.4}
      />
      <Sheet x={42} y={24} w={46} h={50} />
      <HeaderBand x={42} y={24} w={46} h={9} fill={C.blue} />
      <RowBar x={49} y={42} w={30} h={3.2} fill={C.grey3} />
      <RowBar x={49} y={50} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={49} y={58} w={28} h={3.2} fill={C.grey3} />
    </>
  ),

  // New document: a fresh sheet with a green plus badge.
  FilePlus2: () => (
    <>
      <Sheet x={32} y={10} w={54} h={64} />
      <HeaderBand x={32} y={10} w={54} h={10} fill={C.blue} />
      <RowBar x={40} y={28} w={30} h={3.2} fill={C.grey3} />
      <RowBar x={40} y={36} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={40} y={44} w={28} h={3.2} fill={C.grey3} />
      <Badge cx={78} cy={60} r={12} fill={C.green} glyph="plus" />
    </>
  ),

  // Risk / probability: a die showing five with a probability curve.
  Dice5: (accent) => (
    <>
      <rect
        x={32}
        y={29}
        width={38}
        height={38}
        rx={7}
        fill={C.shadow}
        opacity={0.08}
        stroke="none"
      />
      <rect
        x={30}
        y={26}
        width={38}
        height={38}
        rx={7}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.8}
      />
      <circle cx={40} cy={36} r={3} fill={C.blue} stroke="none" />
      <circle cx={58} cy={36} r={3} fill={C.blue} stroke="none" />
      <circle cx={49} cy={45} r={3} fill={accent} stroke="none" />
      <circle cx={40} cy={54} r={3} fill={C.blue} stroke="none" />
      <circle cx={58} cy={54} r={3} fill={C.blue} stroke="none" />
      <path
        d="M74 60 q8 -34 16 0"
        fill={C.blueLight}
        opacity={0.25}
        stroke="none"
      />
      <path
        d="M74 60 q8 -34 16 0"
        fill="none"
        stroke={C.blue}
        strokeWidth={1.8}
      />
      <path d="M72 60 H94" stroke={C.grey1} strokeWidth={1.2} fill="none" />
    </>
  ),

  // Reference / knowledge: an open book with a bookmark.
  BookOpen: (accent) => (
    <>
      <path
        d="M60 22 C50 16 34 16 24 20 V64 C34 60 50 60 60 66 Z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <path
        d="M60 22 C70 16 86 16 96 20 V64 C86 60 70 60 60 66 Z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <path d="M60 22 V66" stroke={C.blue} strokeWidth={2.4} fill="none" />
      <path
        d="M30 30 h22 M30 38 h22 M30 46 h18 M68 30 h22 M68 38 h22 M68 46 h18"
        stroke={C.grey3}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <path d="M84 18 v14 l3 -3 3 3 V19 z" fill={accent} stroke="none" />
    </>
  ),

  // Import / upload: a document lifted up into a tray.
  Upload: (accent) => (
    <>
      <path
        d="M30 60 h60 a4 4 0 0 1 4 4 v2 a4 4 0 0 1 -4 4 H30 a4 4 0 0 1 -4 -4 v-2 a4 4 0 0 1 4 -4 z"
        fill={C.grey2}
        stroke="none"
      />
      <Sheet x={44} y={30} w={32} h={26} shadow={false} />
      <RowBar x={50} y={38} w={20} h={3} fill={C.grey3} />
      <RowBar x={50} y={45} w={16} h={3} fill={C.grey3} />
      <path
        d="M60 12 V30 M50 22 l10 -10 l10 10"
        stroke={accent}
        strokeWidth={3}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Won bid: an ochre trophy with a star.
  Trophy: (accent) => (
    <>
      <path
        d="M44 20 h-8 a6 6 0 0 0 0 12 h5"
        fill="none"
        stroke={C.ochre}
        strokeWidth={3}
      />
      <path
        d="M76 20 h8 a6 6 0 0 1 0 12 h-5"
        fill="none"
        stroke={C.ochre}
        strokeWidth={3}
      />
      <path
        d="M44 18 h32 v10 a16 16 0 0 1 -32 0 z"
        fill={C.ochre}
        stroke="none"
      />
      <path d="M60 44 V54" stroke={C.ochre} strokeWidth={4} fill="none" />
      <path d="M48 60 h24 l-3 -6 H51 z" fill={C.amber} stroke="none" />
      <rect
        x={44}
        y={60}
        width={32}
        height={5}
        rx={2}
        fill={C.blueDeep}
        stroke="none"
      />
      <Star cx={60} cy={28} r={5} fill={accent} />
    </>
  ),

  // Attachment: a paperclip over a document corner.
  Paperclip: (accent) => (
    <>
      <Sheet x={34} y={14} w={48} h={58} />
      <RowBar x={42} y={30} w={30} h={3.2} fill={C.grey3} />
      <RowBar x={42} y={38} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={42} y={46} w={28} h={3.2} fill={C.grey3} />
      <path
        d="M74 8 v22 a6 6 0 0 1 -12 0 V14 a3.5 3.5 0 0 1 7 0 v14"
        fill="none"
        stroke={accent}
        strokeWidth={2.6}
        strokeLinecap="round"
      />
    </>
  ),

  // Site location: a red map pin on a faint map with a route.
  MapPin: (accent) => (
    <>
      <Sheet x={22} y={14} w={76} h={58} fill={C.panel} shadow={false} />
      <path
        d="M30 62 C44 50 40 34 60 34"
        fill="none"
        stroke={accent}
        strokeWidth={2}
        strokeDasharray="1 4"
        strokeLinecap="round"
      />
      <ellipse
        cx={66}
        cy={54}
        rx={7}
        ry={2.4}
        fill={C.shadow}
        opacity={0.12}
        stroke="none"
      />
      <path d="M55 30 L66 52 L77 30 Z" fill={C.red} stroke="none" />
      <circle cx={66} cy={26} r={13} fill={C.red} stroke="none" />
      <circle cx={66} cy={26} r={5.5} fill={C.white} stroke="none" />
    </>
  ),

  // Site photo: a camera with a lens and flash.
  Camera: (accent) => (
    <>
      <path
        d="M24 30 h14 l4 -6 h20 l4 6 h14 a4 4 0 0 1 4 4 v28 a4 4 0 0 1 -4 4 H24 a4 4 0 0 1 -4 -4 V34 a4 4 0 0 1 4 -4 z"
        fill={C.blue}
        stroke="none"
      />
      <circle cx={60} cy={48} r={13} fill={C.blueDeep} stroke="none" />
      <circle cx={60} cy={48} r={9} fill={C.blueLight} stroke="none" />
      <circle
        cx={60}
        cy={48}
        r={4}
        fill={C.white}
        stroke="none"
        opacity={0.85}
      />
      <rect
        x={78}
        y={34}
        width={8}
        height={4}
        rx={1.5}
        fill={accent}
        stroke="none"
      />
    </>
  ),
};

// Semantic aliases: closely related icons reuse an existing bespoke scene.
SCENES.Receipt = SCENES.ReceiptText!;
SCENES.GitCompare = SCENES.GitCompareArrows!;

/**
 * Concrete illustration for a step. Renders a bespoke coloured scene when one
 * exists for the step icon, otherwise a framed version of the step's own glyph
 * on the grid. The tile stays light in both themes on purpose.
 */
export function StepScene({
  icon,
  accent = "#2563eb",
  className,
  rounded = "rounded-2xl",
  title,
  fallbackIcon,
}: StepSceneProps): ReactElement {
  const scene = icon ? SCENES[icon] : undefined;
  const Glyph = fallbackIcon ?? iconFor(icon);

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
      {scene ? (
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
      ) : (
        <>
          <svg
            viewBox={VB}
            className="absolute inset-0 h-full w-full text-slate-400"
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <Grid />
          </svg>
          <Glyph
            size={38}
            strokeWidth={1.5}
            className="relative text-slate-400"
          />
        </>
      )}
    </div>
  );
}
