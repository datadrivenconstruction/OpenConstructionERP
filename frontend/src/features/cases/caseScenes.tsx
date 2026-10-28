// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - bespoke line-art scenes for cases that have no generated picture yet.
//
// Each scene is a small concrete illustration of WHAT the case does, drawn in
// the exact same visual language as StepScene: the shared `0 0 120 84` viewBox,
// the faint blueprint grid, the shared colour palette (stepSceneParts `C`) and
// the same primitive kit (sheets, chips, cubes, badges, ...). That way a case
// without a webp illustration still reads like the detailed majority of the hub
// instead of a lone centred icon (the same idea as RoleArt falling back to a
// drawn avatar rather than a glyph).
//
// Keyed by case id. CaseArt renders the matching scene ahead of the picture, so
// only the cases listed here change; every other card is untouched.

import { type ReactElement } from 'react';
import clsx from 'clsx';
import {
  C,
  Badge,
  Bar,
  Chip,
  Cube,
  Cylinder,
  HeaderBand,
  Magnifier,
  RowBar,
  Sheet,
  Shield,
  Signature,
  Stamp,
  Star,
  WarnTri,
} from './stepSceneParts';
import { Grid, VB } from './StepScene';
import { CASE_SCENES_WAVE1 } from './caseScenesWave1';
import { CASE_SCENES_WAVE2 } from './caseScenesWave2';
import { CASE_SCENES_WAVE3 } from './caseScenesWave3';
import { CASE_SCENES_WAVE4 } from './caseScenesWave4';
import { CASE_SCENES_WAVE5 } from './caseScenesWave5';
import { CASE_SCENES_WAVE6 } from './caseScenesWave6';
import { type Accent, NEUTRAL_ACCENT } from './categories';

/** A scene takes its category accent ramp and returns its artwork group. */
type Scene = (a: Accent) => ReactElement;

/**
 * Bespoke case illustrations, keyed by case id. Every scene uses the shared `C`
 * palette for fills and one `accent` highlight, exactly like the StepScene set,
 * so the linework reads identically on the always-light card tile.
 */
export const CASE_SCENES: Record<string, Scene> = {
  // The six drawing waves that closed the catalogue. Before them 96 of the
  // 202 cases had a scene and the other 106 fell back to their discipline
  // icon, so half the hub was a drawing and half was a glyph. The waves are
  // separate modules rather than more entries below because six of them were
  // written at once and one file cannot take six concurrent authors; the key
  // sets were checked disjoint before merging, and their union is exactly the
  // 106 that were missing, so nothing here shadows anything below.
  ...CASE_SCENES_WAVE1,
  ...CASE_SCENES_WAVE2,
  ...CASE_SCENES_WAVE3,
  ...CASE_SCENES_WAVE4,
  ...CASE_SCENES_WAVE5,
  ...CASE_SCENES_WAVE6,
  // 10 - Set up the common data environment: one shared store two people write
  // to and read from, kept under control (single source of truth).
  'set-up-the-common-data-environment': (a) => (
    <>
      <Sheet x={38} y={16} w={44} h={52} />
      <HeaderBand x={38} y={16} w={44} h={10} fill={a.base} />
      <RowBar x={45} y={20} w={18} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={45} y={34} w={30} h={3.4} fill={C.grey3} />
      <RowBar x={45} y={43} w={26} h={3.4} fill={C.grey3} />
      <RowBar x={45} y={52} w={28} h={3.4} fill={C.grey3} />
      <circle cx={16} cy={30} r={6} fill={C.grey2} stroke="none" />
      <path d="M24 33 H37" stroke={a.base} strokeWidth={2} fill="none" strokeLinecap="round" />
      <path
        d="M33 30 l4 3 l-4 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={104} cy={54} r={6} fill={C.grey2} stroke="none" />
      <path d="M83 51 H96" stroke={a.base} strokeWidth={2} fill="none" strokeLinecap="round" />
      <path
        d="M92 48 l4 3 l-4 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={78} cy={22} r={6} fill={C.green} glyph="check" />
    </>
  ),

  // 11 - Set up BIM requirements and coordination: a requirements checklist
  // that governs the model it is linked to.
  'set-up-bim-requirements-and-coordination': (a) => (
    <>
      <Sheet x={20} y={14} w={44} h={56} />
      <HeaderBand x={20} y={14} w={44} h={10} fill={a.base} />
      <RowBar x={27} y={18} w={20} h={3} fill={C.white} opacity={0.9} />
      <Badge cx={30} cy={34} r={4.5} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={38} y={32} w={20} h={3.4} fill={C.grey3} />
      <Badge cx={30} cy={46} r={4.5} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={38} y={44} w={16} h={3.4} fill={C.grey3} />
      <rect x={26} y={56} width={9} height={9} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <RowBar x={38} y={59} w={18} h={3.4} fill={C.grey3} />
      <path d="M64 40 H76" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="1 3" fill="none" />
      <Cube cx={88} ty={30} w={16} hh={8} depth={16} top={a.base} />
    </>
  ),

  // 12 - Verify as-built against the model with a scan: a point cloud sweeps the
  // built model and the two are confirmed to match.
  'verify-as-built-against-the-model-with-a-scan': (a) => (
    <>
      <Cube cx={54} ty={24} w={18} hh={9} depth={20} top={C.panel} left={C.grey3} right={C.grey2} />
      <circle cx={46} cy={34} r={1.5} fill={a.base} stroke="none" />
      <circle cx={54} cy={40} r={1.5} fill={a.base} stroke="none" />
      <circle cx={62} cy={36} r={1.5} fill={a.base} stroke="none" />
      <circle cx={50} cy={48} r={1.5} fill={a.base} stroke="none" />
      <circle cx={60} cy={50} r={1.5} fill={a.base} stroke="none" />
      <circle cx={56} cy={30} r={1.5} fill={a.base} stroke="none" />
      <rect x={12} y={62} width={11} height={8} rx={2} fill={C.ochre} stroke="none" />
      <path d="M23 64 L42 42" stroke={C.ochre} strokeWidth={1.6} strokeDasharray="2 3" fill="none" />
      <Badge cx={88} cy={26} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // 22 - Draft an estimate with AI element matching: a bill whose rows get rates
  // suggested by an AI match, one highlighted.
  'draft-an-estimate-with-ai-element-matching': (a) => (
    <>
      <Sheet x={22} y={14} w={54} h={56} />
      <HeaderBand x={22} y={14} w={54} h={10} fill={a.base} />
      <RowBar x={28} y={18} w={16} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={28} y={30} w={26} h={3.6} fill={C.grey3} />
      <Chip x={58} y={28} w={12} h={6} r={1.5} fill={C.grey2} />
      <RowBar x={28} y={40} w={22} h={3.6} fill={C.grey3} />
      <Chip x={58} y={38} w={12} h={6} r={1.5} fill={C.ochre} />
      <RowBar x={28} y={50} w={24} h={3.6} fill={C.grey3} />
      <Chip x={58} y={48} w={12} h={6} r={1.5} fill={C.grey2} />
      <Chip x={80} y={40} w={20} h={11} fill={a.light} label="AI" />
      <path
        d="M80 45 C74 45 74 41 70 41"
        stroke={a.base}
        strokeWidth={1.6}
        strokeDasharray="1 3"
        fill="none"
      />
      <Star cx={92} cy={22} r={6.5} fill={C.ochre} />
      <Star cx={103} cy={34} r={4} fill={a.light} />
      <Star cx={84} cy={30} r={3.5} fill={a.base} />
    </>
  ),

  // 23 - Build the resource library and rates: a catalogue of labour, plant and
  // material, each carrying its rate.
  'build-the-resource-library-and-rates': (a) => (
    <>
      <Sheet x={24} y={12} w={72} h={60} />
      <HeaderBand x={24} y={12} w={72} h={11} fill={a.base} />
      <RowBar x={30} y={16} w={24} h={3.4} fill={C.white} opacity={0.9} />
      <circle cx={34} cy={33} r={4} fill={C.grey2} stroke="none" />
      <path d="M30 40 c0 -4 2 -6 4 -6 s4 2 4 6 z" fill={C.grey2} stroke="none" />
      <RowBar x={44} y={33} w={24} h={3.4} fill={C.grey3} />
      <Chip x={76} y={31} w={14} h={7} fill={C.green} />
      <rect x={30} y={46} width={9} height={6} rx={1.5} fill={C.ochre} stroke="none" />
      <circle cx={32} cy={53} r={1.8} fill={a.deep} stroke="none" />
      <circle cx={37} cy={53} r={1.8} fill={a.deep} stroke="none" />
      <RowBar x={44} y={47} w={20} h={3.4} fill={C.grey3} />
      <Chip x={76} y={45} w={14} h={7} fill={a.base} />
      <rect x={30} y={60} width={8} height={8} rx={1} fill={a.light} stroke="none" />
      <RowBar x={44} y={62} w={22} h={3.4} fill={C.grey3} />
      <Chip x={76} y={60} w={14} h={7} fill={C.grey2} />
    </>
  ),

  // 24 - Build a 5D cost-loaded model: the 3D model carries a cost tag and rolls
  // up into a cost-over-time curve.
  'build-a-5d-cost-loaded-model': (a) => (
    <>
      <Cube cx={40} ty={22} w={18} hh={9} depth={20} top={a.light} left={a.base} right={a.deep} />
      <path d="M58 34 H70" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="1 3" fill="none" />
      <Chip x={70} y={28} w={22} h={11} fill={C.green} />
      <circle cx={81} cy={33.5} r={3.2} fill="none" stroke={C.white} strokeWidth={1.4} />
      <path d="M24 68 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M28 66 L48 60 L66 62 L86 50 L100 46"
        fill="none"
        stroke={a.base}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={100} cy={46} r={2.6} fill={a.base} stroke="none" />
    </>
  ),

  // 25 - Appraise a development scheme: does the scheme stack up, a building
  // weighed against the return it makes.
  'appraise-a-development-scheme': (a) => (
    <>
      <rect x={26} y={24} width={26} height={44} rx={2} fill={a.base} stroke="none" />
      <path
        d="M31 32 h4 M42 32 h4 M31 40 h4 M42 40 h4 M31 48 h4 M42 48 h4 M31 56 h4 M42 56 h4"
        stroke={a.light}
        strokeWidth={3}
        strokeLinecap="round"
        fill="none"
      />
      <circle cx={70} cy={30} r={9} fill={C.ochre} stroke={C.white} strokeWidth={1.2} />
      <circle cx={70} cy={30} r={5.5} fill="none" stroke={C.white} strokeWidth={1.3} opacity={0.7} />
      <path
        d="M60 62 L72 54 L82 58 L96 42"
        fill="none"
        stroke={C.green}
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M90 42 h6 v6"
        fill="none"
        stroke={a.base}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M24 68 H100" stroke={C.grey1} strokeWidth={1.6} strokeLinecap="round" fill="none" />
    </>
  ),

  // 71 - Run the submittals register: a stack of submittals tracked through their
  // review statuses and stamped off.
  'run-the-submittals-register': (a) => (
    <>
      <rect x={30} y={16} width={44} height={52} rx={4} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <rect x={36} y={20} width={44} height={52} rx={4} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <Sheet x={42} y={24} w={44} h={52} />
      <HeaderBand x={42} y={24} w={44} h={9} fill={a.base} />
      <circle cx={49} cy={42} r={2.4} fill={C.green} stroke="none" />
      <RowBar x={54} y={40.5} w={24} h={3.2} fill={C.grey3} />
      <circle cx={49} cy={52} r={2.4} fill={C.amber} stroke="none" />
      <RowBar x={54} y={50.5} w={20} h={3.2} fill={C.grey3} />
      <circle cx={49} cy={62} r={2.4} fill={a.base} stroke="none" />
      <RowBar x={54} y={60.5} w={22} h={3.2} fill={C.grey3} />
      <Stamp cx={80} cy={62} r={7} />
    </>
  ),

  // 72 - Turn field time into payroll and labour cost: a timesheet with hours
  // becomes paid labour cost.
  'turn-field-time-into-payroll-and-labour-cost': (a) => (
    <>
      <Sheet x={18} y={18} w={38} h={48} />
      <HeaderBand x={18} y={18} w={38} h={9} fill={a.base} />
      <RowBar x={24} y={34} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={42} w={22} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={50} w={24} h={3.2} fill={C.grey3} />
      <circle cx={49} cy={23} r={6.5} fill={C.white} stroke={a.base} strokeWidth={1.8} />
      <path d="M49 19 v4 l3 2" stroke={a.base} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <path
        d="M60 44 H74 M70 40 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={78} y={34} width={30} height={20} rx={3} fill={C.green} stroke="none" />
      <circle cx={93} cy={44} r={5} fill="none" stroke={C.white} strokeWidth={1.4} opacity={0.85} />
    </>
  ),

  // 73 - Build a delay and disruption claim with evidence: a slipped programme
  // bar, backed by an evidence record.
  'build-a-delay-and-disruption-claim-with-evidence': (a) => (
    <>
      <Sheet x={14} y={14} w={64} h={40} />
      <path d="M22 26 h30" stroke={a.base} strokeWidth={5} strokeLinecap="round" fill="none" />
      <path d="M22 36 h18" stroke={C.grey2} strokeWidth={5} strokeLinecap="round" fill="none" />
      <path d="M40 36 h20" stroke={C.red} strokeWidth={5} strokeLinecap="round" fill="none" />
      <path d="M22 46 h14" stroke={C.grey2} strokeWidth={5} strokeLinecap="round" fill="none" />
      <path d="M52 20 V50" stroke={a.base} strokeWidth={1.6} strokeDasharray="2 2" fill="none" />
      <Sheet x={78} y={48} w={24} h={24} />
      <RowBar x={83} y={55} w={13} h={2.8} fill={C.grey3} />
      <RowBar x={83} y={61} w={10} h={2.8} fill={C.grey3} />
      <WarnTri cx={28} cy={64} w={16} fill={C.amber} />
    </>
  ),

  // 74 - Mark up and compare a drawing revision: a red mark-up on one revision,
  // resolved on the next, compared side by side.
  'mark-up-and-compare-a-drawing-revision': (a) => (
    <>
      <Sheet x={14} y={16} w={38} h={52} fill={C.panel} />
      <path d="M20 30 H46 M20 44 H40 M28 24 V60" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <circle cx={34} cy={39} r={7} fill="none" stroke={C.red} strokeWidth={1.8} />
      <path d="M30 54 h12" stroke={C.red} strokeWidth={1.8} strokeLinecap="round" fill="none" />
      <Sheet x={68} y={16} w={38} h={52} fill={C.panel} />
      <path d="M74 30 H100 M74 44 H94 M82 24 V60" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <circle cx={88} cy={39} r={7} fill="none" stroke={C.green} strokeWidth={1.8} />
      <path
        d="M53 34 H66 M62 30 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M67 50 H54 M58 46 l-4 4 l4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // 75 - Give the client a project portal: the client sees the project's numbers
  // on their own screen.
  'give-the-client-a-project-portal': (a) => (
    <>
      <rect x={22} y={16} width={62} height={44} rx={4} fill={C.white} stroke={C.grey1} strokeWidth={1.8} />
      <HeaderBand x={22} y={16} w={62} h={10} fill={a.base} />
      <RowBar x={28} y={32} w={22} h={3.4} fill={C.grey3} />
      <RowBar x={28} y={40} w={18} h={3.4} fill={C.grey3} />
      <Bar x={56} baseY={52} w={5} h={10} fill={a.light} />
      <Bar x={64} baseY={52} w={5} h={16} fill={a.base} />
      <Bar x={72} baseY={52} w={5} h={8} fill={C.ochre} />
      <path d="M46 60 h16 l3 8 h-22 z" fill={C.grey2} stroke="none" />
      <path d="M36 68 H72" stroke={C.grey1} strokeWidth={2} strokeLinecap="round" fill="none" />
      <circle cx={96} cy={40} r={7} fill={a.base} stroke={C.white} strokeWidth={1} />
      <path d="M86 62 c0 -8 4 -13 10 -13 s10 5 10 13 z" fill={a.base} stroke={C.white} strokeWidth={1} />
    </>
  ),

  // 76 - Manage an engineering change: a part is revised under a controlled
  // change and approved.
  'manage-an-engineering-change': (a) => (
    <>
      <circle cx={40} cy={42} r={14} fill={a.base} stroke="none" />
      <path
        d="M40 22 V32 M40 52 V62 M20 42 H30 M50 42 H60 M30 32 l-6 -6 M50 32 l6 -6 M30 52 l-6 6 M50 52 l6 6"
        stroke={a.base}
        strokeWidth={3.6}
        strokeLinecap="round"
        fill="none"
      />
      <circle cx={40} cy={42} r={6} fill={C.white} stroke="none" />
      <Chip x={64} y={16} w={16} h={8} fill={C.ochre} label="B" />
      <path
        d="M66 36 a12 12 0 0 1 24 3"
        fill="none"
        stroke={a.base}
        strokeWidth={2.2}
        strokeLinecap="round"
      />
      <path
        d="M90 32 l0 8 l-8 -1"
        fill="none"
        stroke={a.base}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={86} cy={58} r={9} fill={C.green} glyph="check" />
    </>
  ),

  // 77 - Record a verbal instruction for the record: something said on site is
  // captured in a written, signed note.
  'record-a-verbal-instruction-for-the-record': (a) => (
    <>
      <path
        d="M16 16 h40 a5 5 0 0 1 5 5 v16 a5 5 0 0 1 -5 5 H34 l-10 8 v-8 h-8 a5 5 0 0 1 -5 -5 V21 a5 5 0 0 1 5 -5 z"
        fill={a.light}
        stroke="none"
      />
      <RowBar x={22} y={24} w={28} h={3.2} fill={C.white} opacity={0.85} />
      <RowBar x={22} y={31} w={20} h={3.2} fill={C.white} opacity={0.65} />
      <path
        d="M50 52 C58 56 62 56 70 54"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M66 50 l5 4 l-6 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={72} y={40} w={34} h={34} />
      <RowBar x={78} y={48} w={20} h={3} fill={C.grey3} />
      <RowBar x={78} y={55} w={16} h={3} fill={C.grey3} />
      <Signature x={78} y={64} w={20} color={a.base} />
    </>
  ),

  // 78 - Handover and closeout: the finished building is handed over, with the
  // keys passed and the works signed off.
  'handover-and-closeout': (a) => (
    <>
      <rect x={22} y={30} width={30} height={38} rx={2} fill={a.base} stroke="none" />
      <path d="M20 30 L37 20 L54 30 Z" fill={a.deep} stroke="none" />
      <rect x={28} y={38} width={7} height={7} rx={1} fill={a.light} stroke="none" />
      <rect x={39} y={38} width={7} height={7} rx={1} fill={a.light} stroke="none" />
      <rect x={33} y={54} width={8} height={14} rx={1} fill={C.white} stroke="none" />
      <circle cx={68} cy={40} r={6} fill="none" stroke={C.ochre} strokeWidth={3} />
      <path
        d="M73 43 l12 12 M80 50 l4 -4 M84 54 l4 -4"
        stroke={C.ochre}
        strokeWidth={3}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={92} cy={26} r={9} fill={C.green} glyph="check" />
      <Star cx={37} cy={16} r={4} fill={a.base} />
      <path d="M20 68 H98" stroke={C.grey1} strokeWidth={1.6} strokeLinecap="round" fill="none" />
    </>
  ),

  // ---- BIM & takeoff ----

  // Get 6D carbon from a BIM model: quantities off the geometry paired with
  // emission factors, then a reduction target.
  'carbon-from-bim-6d': (a) => (
    <>
      <Cube cx={34} ty={18} w={15} hh={7.5} depth={17} top={C.grey3} left={C.grey2} right={C.grey1} />
      <path d="M52 30 H62" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="1 3" fill="none" />
      <Chip x={62} y={22} w={26} h={13} r={3} fill={C.green} label="CO2" />
      <path d="M24 70 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M30 52 L50 55 L70 61 L88 66 L100 68"
        fill="none"
        stroke={a.base}
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={100} cy={68} r={4.5} fill="none" stroke={a.base} strokeWidth={1.4} />
      <circle cx={100} cy={68} r={1.8} fill={a.base} stroke="none" />
    </>
  ),

  // Coordinate and resolve model clashes: two models overlap, a clash flares,
  // it is driven to a resolved check.
  'coordinate-and-resolve-model-clashes': (a) => (
    <>
      <Cube cx={40} ty={22} w={16} hh={8} depth={18} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={56} ty={30} w={13} hh={6.5} depth={15} top={C.grey3} left={C.grey2} right={C.grey1} />
      <circle cx={53} cy={40} r={3} fill={C.red} stroke="none" />
      <path
        d="M53 40 L46 33 M53 40 L61 34 M53 40 L62 45 M53 40 L47 48"
        stroke={C.red}
        strokeWidth={1.6}
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M74 40 H86 M82 36 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={98} cy={40} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Coordinate models and resolve clashes: federate, magnify to detect, triage
  // the real ones in a status list.
  'coordinate-models-and-clashes': (a) => (
    <>
      <Cube cx={38} ty={24} w={18} hh={9} depth={20} top={a.light} left={a.base} right={a.deep} />
      <circle cx={40} cy={40} r={2} fill={C.red} stroke="none" />
      <circle cx={33} cy={47} r={1.6} fill={C.amber} stroke="none" />
      <Magnifier cx={47} cy={38} r={9} />
      <Sheet x={74} y={22} w={32} h={42} />
      <circle cx={80} cy={33} r={2.4} fill={C.red} stroke="none" />
      <RowBar x={85} y={31.5} w={16} h={3} fill={C.grey3} />
      <circle cx={80} cy={43} r={2.4} fill={C.amber} stroke="none" />
      <RowBar x={85} y={41.5} w={13} h={3} fill={C.grey3} />
      <circle cx={80} cy={53} r={2.4} fill={C.green} stroke="none" />
      <RowBar x={85} y={51.5} w={15} h={3} fill={C.grey3} />
    </>
  ),

  // Raise a design query from BIM coordination: a conflict in the model becomes
  // a question, answered and fed back.
  'design-query-from-bim-coordination': (a) => (
    <>
      <Cube cx={34} ty={28} w={15} hh={7.5} depth={17} top={C.grey3} left={C.grey2} right={C.grey1} />
      <circle cx={40} cy={44} r={2} fill={C.red} stroke="none" />
      <path
        d="M56 20 h34 a5 5 0 0 1 5 5 v16 a5 5 0 0 1 -5 5 H74 l-8 7 v-7 h-10 a5 5 0 0 1 -5 -5 V25 a5 5 0 0 1 5 -5 z"
        fill={a.light}
        stroke="none"
      />
      <path
        d="M69 28 a4 4 0 0 1 8 0 c0 3 -4 3 -4 6"
        stroke={C.white}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={73} cy={38} r={1.5} fill={C.white} stroke="none" />
      <Badge cx={92} cy={58} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Audit a model before it goes out: magnify the model against a checklist of
  // coordinate base, clashes and classification.
  'model-quality-audit-before-issue': (a) => (
    <>
      <Cube cx={34} ty={24} w={16} hh={8} depth={18} top={a.light} left={a.base} right={a.deep} />
      <Magnifier cx={42} cy={38} r={9} />
      <Sheet x={72} y={18} w={34} h={48} />
      <HeaderBand x={72} y={18} w={34} h={9} fill={a.base} />
      <Badge cx={79} cy={38} r={4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={86} y={36.5} w={15} h={3} fill={C.grey3} />
      <Badge cx={79} cy={48} r={4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={86} y={46.5} w={12} h={3} fill={C.grey3} />
      <Badge cx={79} cy={58} r={4} fill={C.amber} glyph="warn" shadow={false} />
      <RowBar x={86} y={56.5} w={14} h={3} fill={C.grey3} />
    </>
  ),

  // Get quantities from a BIM model: read them off the geometry straight into a
  // priced bill.
  'quantities-from-bim': (a) => (
    <>
      <Cube cx={32} ty={24} w={15} hh={7.5} depth={17} top={a.light} left={a.base} right={a.deep} />
      <path
        d="M50 38 H60 M56 34 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={62} y={20} w={44} h={46} />
      <HeaderBand x={62} y={20} w={44} h={9} fill={a.base} />
      <RowBar x={68} y={35} w={20} h={3.2} fill={C.grey3} />
      <Chip x={92} y={33} w={10} h={6} fill={C.green} />
      <RowBar x={68} y={44} w={16} h={3.2} fill={C.grey3} />
      <Chip x={92} y={42} w={10} h={6} fill={C.green} />
      <RowBar x={68} y={53} w={22} h={3.2} fill={C.grey3} />
      <Chip x={92} y={51} w={10} h={6} fill={C.green} />
    </>
  ),

  // Measure quantities from a DWG: scale the drawing, measure an area, read out
  // the quantities.
  'takeoff-from-dwg': (a) => (
    <>
      <Sheet x={18} y={16} w={56} h={52} fill={C.panel} />
      <path d="M26 26 H66 V58 H26 Z" fill="none" stroke={C.grey1} strokeWidth={1.4} />
      <path d="M26 40 H48 M48 26 V58" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <rect x={48} y={40} width={18} height={18} fill={a.base} fillOpacity={0.18} stroke={a.base} strokeWidth={1.2} />
      <path d="M26 64 H66 M26 62 v4 M66 62 v4" stroke={C.ochre} strokeWidth={1.4} fill="none" />
      <Chip x={82} y={30} w={22} h={11} r={2.5} fill={C.green} label="m2" />
      <Chip x={82} y={46} w={22} h={11} r={2.5} fill={a.light} label="12" />
    </>
  ),

  // ---- Estimating & costing ----

  // Build an assembly (recipe rate): component items combine into one composite
  // rate that drives bill lines.
  'build-an-assembly-recipe-rate': (a) => (
    <>
      <Chip x={20} y={22} w={34} h={10} r={2} fill={a.base} label="concrete" />
      <Chip x={20} y={36} w={34} h={10} r={2} fill={C.ochre} label="rebar" />
      <Chip x={20} y={50} w={34} h={10} r={2} fill={C.grey2} label="formwork" labelFill={C.ink} />
      <path
        d="M56 41 H70 M66 37 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Chip x={74} y={33} w={30} h={16} r={3} fill={C.green} label="1 rate" />
    </>
  ),

  // Set contingency from cost risk: a Monte Carlo spreads the estimate into a
  // curve, and a defensible P-value sets the contingency.
  'cost-risk-and-contingency': (a) => (
    <>
      <path d="M18 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M22 66 C40 66 44 26 60 26 C76 26 80 66 100 66"
        fill={a.light}
        fillOpacity={0.18}
        stroke={a.base}
        strokeWidth={2}
        strokeLinejoin="round"
      />
      <path d="M60 26 V66" stroke={C.grey1} strokeWidth={1.2} strokeDasharray="2 2" fill="none" />
      <path d="M82 42 V66" stroke={a.base} strokeWidth={1.8} fill="none" />
      <circle cx={82} cy={42} r={2.6} fill={a.base} stroke="none" />
      <rect x={20} y={20} width={14} height={14} rx={2.5} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <circle cx={24} cy={24} r={1.3} fill={a.deep} stroke="none" />
      <circle cx={30} cy={24} r={1.3} fill={a.deep} stroke="none" />
      <circle cx={27} cy={27} r={1.3} fill={a.deep} stroke="none" />
      <circle cx={24} cy={30} r={1.3} fill={a.deep} stroke="none" />
      <circle cx={30} cy={30} r={1.3} fill={a.deep} stroke="none" />
    </>
  ),

  // Build an elemental cost plan: a building split into classified elements,
  // each carrying its cost, tagged by cost group.
  'elemental-cost-plan-and-classification': (a) => (
    <>
      <rect x={26} y={20} width={34} height={48} rx={2} fill="none" stroke={C.grey1} strokeWidth={1.4} />
      <rect x={26} y={20} width={34} height={12} fill={a.light} stroke="none" />
      <rect x={26} y={32} width={34} height={12} fill={a.base} stroke="none" />
      <rect x={26} y={44} width={34} height={12} fill={a.deep} stroke="none" />
      <rect x={26} y={56} width={34} height={12} fill={C.grey2} stroke="none" />
      <Chip x={68} y={22} w={24} h={8} fill={C.green} />
      <Chip x={68} y={34} w={18} h={8} fill={C.green} />
      <Chip x={68} y={46} w={22} h={8} fill={C.green} />
      <Chip x={68} y={58} w={16} h={8} fill={C.green} />
      <Chip x={94} y={34} w={12} h={9} fill={a.base} label="KG" />
    </>
  ),

  // Estimate from a cost database: pull priced items from the database into a
  // built-up bill.
  'estimate-from-cost-database': (a) => (
    <>
      <Cylinder cx={34} top={26} rx={14} ry={5} h={30} fill={a.base} topFill={a.light} />
      <path
        d="M50 42 H60 M56 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={62} y={18} w={44} h={48} />
      <HeaderBand x={62} y={18} w={44} h={9} fill={a.base} />
      <RowBar x={68} y={33} w={22} h={3.2} fill={C.grey3} />
      <Chip x={92} y={31} w={10} h={6} fill={C.green} />
      <RowBar x={68} y={42} w={18} h={3.2} fill={C.grey3} />
      <Chip x={92} y={40} w={10} h={6} fill={C.green} />
      <RowBar x={68} y={51} w={20} h={3.2} fill={C.grey3} />
      <Chip x={92} y={49} w={10} h={6} fill={C.green} />
    </>
  ),

  // Estimate a feasibility budget before design: a per-square-metre benchmark
  // and an order-of-magnitude range while the building is still a dashed idea.
  'feasibility-budget-before-design': (a) => (
    <>
      <path
        d="M22 68 V36 L40 22 L58 36 V68 Z"
        fill={C.panel}
        stroke={C.grey1}
        strokeWidth={1.6}
        strokeDasharray="3 3"
      />
      <Chip x={28} y={46} w={24} h={12} r={2.5} fill={a.base} label="/m2" />
      <path d="M68 44 H104 M68 40 v8 M104 40 v8" stroke={C.grey1} strokeWidth={1.6} strokeLinecap="round" fill="none" />
      <rect x={78} y={41} width={16} height={6} rx={3} fill={C.green} stroke="none" />
      <circle cx={86} cy={44} r={3.2} fill={a.base} stroke={C.white} strokeWidth={1} />
      <RowBar x={70} y={56} w={30} h={3} fill={C.grey3} />
    </>
  ),

  // Provide an independent cost check on a design: weigh a price you did not set
  // against the benchmark under a second-opinion lens.
  'independent-cost-check-on-a-design': (a) => (
    <>
      <Sheet x={18} y={18} w={38} h={50} />
      <HeaderBand x={18} y={18} w={38} h={9} fill={a.base} />
      <RowBar x={24} y={33} w={22} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={41} w={18} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={49} w={24} h={3.2} fill={C.grey3} />
      <Magnifier cx={50} cy={50} r={9} />
      <path d="M80 24 V52" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <path d="M68 32 H92" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <path d="M68 32 l-4 8 h8 z" fill={a.light} stroke="none" />
      <path d="M92 32 l-4 8 h8 z" fill={C.ochre} stroke="none" />
      <Badge cx={80} cy={60} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Localize an estimate to a region: apply a regional factor and pin the
  // priced bill to its place.
  'localize-an-estimate-to-a-region': (a) => (
    <>
      <Sheet x={18} y={18} w={38} h={50} />
      <HeaderBand x={18} y={18} w={38} h={9} fill={a.base} />
      <RowBar x={24} y={33} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={42} w={16} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={51} w={22} h={3.2} fill={C.grey3} />
      <Chip x={58} y={40} w={18} h={9} fill={C.ochre} label="x1.1" />
      <path
        d="M92 24 c-7 0 -12 5 -12 12 c0 8 12 20 12 20 c0 0 12 -12 12 -20 c0 -7 -5 -12 -12 -12 z"
        fill={a.base}
        stroke={C.white}
        strokeWidth={1.2}
      />
      <circle cx={92} cy={36} r={4.5} fill={C.white} stroke="none" />
    </>
  ),

  // Sense-check an estimate against benchmarks: compare priced rates to the
  // reference bars and flag the outlier.
  'sense-check-an-estimate-with-benchmarks': (a) => (
    <>
      <Sheet x={18} y={18} w={34} h={50} />
      <HeaderBand x={18} y={18} w={34} h={9} fill={a.base} />
      <RowBar x={24} y={33} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={42} w={16} h={3.2} fill={C.pink} />
      <RowBar x={24} y={51} w={22} h={3.2} fill={C.grey3} />
      <path d="M62 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={66} baseY={66} w={7} h={20} fill={a.base} />
      <Bar x={76} baseY={66} w={7} h={22} fill={C.grey2} />
      <Bar x={88} baseY={66} w={7} h={34} fill={C.red} />
      <Bar x={98} baseY={66} w={7} h={20} fill={C.grey2} />
      <WarnTri cx={91} cy={26} w={13} fill={C.amber} />
    </>
  ),

  // Check an estimate before you send it: the priced bill against the validation
  // traffic light of pass, warning and error.
  'validate-estimate': (a) => (
    <>
      <Sheet x={22} y={16} w={44} h={54} />
      <HeaderBand x={22} y={16} w={44} h={10} fill={a.base} />
      <RowBar x={28} y={20} w={18} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={28} y={34} w={30} h={3.4} fill={C.grey3} />
      <RowBar x={28} y={43} w={26} h={3.4} fill={C.grey3} />
      <RowBar x={28} y={52} w={28} h={3.4} fill={C.grey3} />
      <rect x={74} y={22} width={16} height={40} rx={8} fill={C.ink} stroke="none" />
      <circle cx={82} cy={30} r={4.5} fill={C.green} stroke="none" />
      <circle cx={82} cy={42} r={4.5} fill={C.amber} stroke="none" />
      <circle cx={82} cy={54} r={4.5} fill={C.red} stroke="none" />
      <Badge cx={99} cy={30} r={6} fill={C.green} glyph="check" />
    </>
  ),

  // Value engineer a design to the target cost: bring the tall cost bar down
  // under the target line and book the saving.
  'value-engineer-a-design-to-the-target-cost': (a) => (
    <>
      <path d="M20 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={30} baseY={66} w={16} h={44} fill={C.grey2} />
      <Bar x={30} baseY={66} w={16} h={30} fill={a.base} />
      <path d="M22 36 H104" stroke={C.green} strokeWidth={1.6} strokeDasharray="3 2" fill="none" />
      <path
        d="M54 26 V44 M50 40 l4 4 l4 -4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Chip x={68} y={46} w={32} h={13} r={3} fill={C.green} label="saved" />
    </>
  ),

  // ---- Tendering & procurement ----

  // Compare bids and award: level the returned tenders on one scale and award
  // the winner.
  'compare-bids-and-award': () => (
    <>
      <path d="M20 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={28} baseY={66} w={14} h={34} fill={C.grey2} />
      <Bar x={50} baseY={66} w={14} h={42} fill={C.grey2} />
      <Bar x={72} baseY={66} w={14} h={26} fill={C.green} />
      <Star cx={79} cy={34} r={6} fill={C.ochre} />
      <Badge cx={98} cy={40} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Issue a procurement and buying schedule: buying packages on a timeline with
  // a need-by deadline and an order placed.
  'issue-a-procurement-and-buying-schedule': (a) => (
    <>
      <Sheet x={16} y={16} w={90} h={54} />
      <HeaderBand x={16} y={16} w={90} h={9} fill={a.base} />
      <RowBar x={22} y={20} w={20} h={3} fill={C.white} opacity={0.9} />
      <rect x={24} y={32} width={30} height={5} rx={2.5} fill={a.light} stroke="none" />
      <rect x={40} y={41} width={34} height={5} rx={2.5} fill={C.ochre} stroke="none" />
      <rect x={30} y={50} width={26} height={5} rx={2.5} fill={a.light} stroke="none" />
      <path d="M84 28 V60" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <path d="M84 28 l-3 -5 h6 z" fill={C.red} stroke="none" />
      <Chip x={80} y={49} w={22} h={9} fill={C.green} label="order" />
    </>
  ),

  // Maintain supplier catalogs and buy from them: a price list kept current, and
  // committed spend held under the allowance.
  'maintain-supplier-catalogs-and-buy-from-them': (a) => (
    <>
      <Sheet x={18} y={16} w={42} h={54} />
      <HeaderBand x={18} y={16} w={42} h={10} fill={a.base} />
      <RowBar x={24} y={20} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={24} y={34} w={22} h={3.2} fill={C.grey3} />
      <Chip x={48} y={32} w={8} h={6} fill={C.green} />
      <RowBar x={24} y={43} w={18} h={3.2} fill={C.grey3} />
      <Chip x={48} y={41} w={8} h={6} fill={C.green} />
      <RowBar x={24} y={52} w={20} h={3.2} fill={C.grey3} />
      <Chip x={48} y={50} w={8} h={6} fill={C.green} />
      <path
        d="M78 26 a11 11 0 1 0 4 -8"
        fill="none"
        stroke={a.base}
        strokeWidth={2}
        strokeLinecap="round"
      />
      <path d="M82 14 l-1 6 l6 -1" fill="none" stroke={a.base} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <path d="M70 56 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <rect x={70} y={50} width={22} height={5} rx={2.5} fill={C.green} stroke="none" />
      <path d="M96 46 V60" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
    </>
  ),

  // Procure materials from the BOQ: a requisition off the bill becomes an order
  // and goods received on site.
  'procure-from-boq': (a) => (
    <>
      <Sheet x={16} y={18} w={34} h={48} />
      <HeaderBand x={16} y={18} w={34} h={9} fill={a.base} />
      <RowBar x={22} y={32} w={18} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={41} w={14} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={50} w={20} h={3.2} fill={C.grey3} />
      <path
        d="M52 42 H62 M58 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Chip x={64} y={24} w={22} h={11} r={2.5} fill={C.ochre} label="order" />
      <Cube cx={78} ty={44} w={12} hh={6} depth={12} top={a.light} left={a.base} right={a.deep} />
      <Badge cx={96} cy={58} r={6.5} fill={C.green} glyph="check" />
    </>
  ),

  // Respond to an invitation to tender as a subcontractor: price the package off
  // the bill and submit on time.
  'respond-to-an-invitation-to-tender-as-a-subcontractor': (a) => (
    <>
      <rect x={18} y={22} width={34} height={24} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <path d="M18 24 L35 36 L52 24" fill="none" stroke={C.grey1} strokeWidth={1.4} />
      <Chip x={22} y={48} w={20} h={8} r={2} fill={a.light} label="ITT" />
      <Sheet x={58} y={18} w={32} h={44} />
      <HeaderBand x={58} y={18} w={32} h={9} fill={a.base} />
      <RowBar x={63} y={32} w={14} h={3} fill={C.grey3} />
      <Chip x={80} y={30} w={7} h={6} fill={C.green} />
      <RowBar x={63} y={41} w={16} h={3} fill={C.grey3} />
      <Chip x={80} y={39} w={7} h={6} fill={C.green} />
      <path d="M94 46 l12 -5 l-4 12 l-3 -4 z" fill={a.base} stroke="none" />
      <circle cx={98} cy={24} r={6} fill={C.white} stroke={a.base} strokeWidth={1.6} />
      <path d="M98 20 v4 l3 2" stroke={a.base} strokeWidth={1.4} fill="none" strokeLinecap="round" />
    </>
  ),

  // Run a tender from a BOQ: the priced bill goes out to several subcontractors
  // and the winner is picked.
  'tender-from-boq': (a) => (
    <>
      <Sheet x={16} y={18} w={34} h={48} />
      <HeaderBand x={16} y={18} w={34} h={9} fill={a.base} />
      <RowBar x={22} y={32} w={18} h={3} fill={C.grey3} />
      <Chip x={40} y={30} w={7} h={6} fill={C.green} />
      <RowBar x={22} y={41} w={14} h={3} fill={C.grey3} />
      <Chip x={40} y={39} w={7} h={6} fill={C.green} />
      <RowBar x={22} y={50} w={16} h={3} fill={C.grey3} />
      <Chip x={40} y={48} w={7} h={6} fill={C.green} />
      <path d="M52 42 C62 42 62 28 72 28" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="1 3" fill="none" />
      <path d="M52 42 H72" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="1 3" fill="none" />
      <path d="M52 42 C62 42 62 56 72 56" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="1 3" fill="none" />
      <circle cx={78} cy={28} r={5} fill={C.grey2} stroke="none" />
      <circle cx={78} cy={42} r={5} fill={C.green} stroke="none" />
      <circle cx={78} cy={56} r={5} fill={C.grey2} stroke="none" />
      <Star cx={92} cy={42} r={6} fill={C.ochre} />
    </>
  ),

  // ---- Commercial & contracts ----

  // Agree the final account and release retention: settle the total and release
  // the retention that is due.
  'agree-the-final-account-and-release-retention': (a) => (
    <>
      <Sheet x={18} y={14} w={42} h={56} />
      <HeaderBand x={18} y={14} w={42} h={10} fill={a.base} />
      <RowBar x={24} y={18} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={24} y={32} w={28} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={40} w={24} h={3.2} fill={C.grey3} />
      <RowBar x={24} y={48} w={26} h={3.2} fill={C.grey3} />
      <path d="M24 56 H54" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={24} y={59} w={20} h={4.2} fill={a.deep} />
      <circle cx={82} cy={34} r={11} fill={C.ochre} stroke={C.white} strokeWidth={1.4} />
      <circle cx={82} cy={34} r={6} fill="none" stroke={C.white} strokeWidth={1.4} opacity={0.7} />
      <path
        d="M74 54 H96 M90 50 l6 4 l-6 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={98} cy={22} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Assess and price a variation: added and omitted work priced off the rates,
  // then issued for agreement.
  'assess-and-price-a-variation': () => (
    <>
      <Sheet x={22} y={16} w={44} h={54} />
      <HeaderBand x={22} y={16} w={44} h={10} fill={C.ochre} />
      <RowBar x={28} y={20} w={22} h={3} fill={C.white} opacity={0.9} />
      <Badge cx={32} cy={36} r={4} fill={C.green} glyph="plus" shadow={false} />
      <RowBar x={39} y={34.5} w={18} h={3.2} fill={C.grey3} />
      <Chip x={59} y={33} w={5} h={6} fill={C.green} />
      <Badge cx={32} cy={48} r={4} fill={C.red} glyph="x" shadow={false} />
      <RowBar x={39} y={46.5} w={14} h={3.2} fill={C.grey3} />
      <Chip x={55} y={45} w={5} h={6} fill={C.red} />
      <Badge cx={82} cy={40} r={9} fill={C.green} glyph="check" />
    </>
  ),

  // Change register and impact: every change logged, with its time and cost
  // impact and the rising trend.
  'change-register-and-impact': (a) => (
    <>
      <Sheet x={16} y={16} w={40} h={54} />
      <HeaderBand x={16} y={16} w={40} h={10} fill={a.base} />
      <RowBar x={22} y={20} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={22} y={32} w={26} h={3} fill={C.grey3} />
      <RowBar x={22} y={40} w={22} h={3} fill={C.grey3} />
      <RowBar x={22} y={48} w={24} h={3} fill={C.grey3} />
      <RowBar x={22} y={56} w={20} h={3} fill={C.grey3} />
      <path d="M66 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={70} baseY={66} w={9} h={16} fill={C.amber} />
      <Bar x={84} baseY={66} w={9} h={30} fill={a.base} />
      <path
        d="M96 30 l8 -8 M104 22 h-6 M104 22 v6"
        stroke={C.red}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Turn a change into a paid variation: price the change and bill it in the
  // next progress claim.
  'change-to-paid-variation': (a) => (
    <>
      <Sheet x={16} y={20} w={30} h={42} fill={C.highlight} stroke={C.amber} />
      <RowBar x={21} y={28} w={18} h={3} fill={C.amber} />
      <RowBar x={21} y={36} w={14} h={3} fill={C.grey3} />
      <RowBar x={21} y={44} w={16} h={3} fill={C.grey3} />
      <path
        d="M48 42 H60 M56 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={62} y={16} w={40} h={52} />
      <HeaderBand x={62} y={16} w={40} h={10} fill={a.base} />
      <RowBar x={68} y={32} w={22} h={3.2} fill={C.grey3} />
      <RowBar x={68} y={40} w={18} h={3.2} fill={C.grey3} />
      <path d="M68 50 H96" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={68} y={53} w={20} h={4} fill={C.green} />
      <Badge cx={94} cy={58} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Control cost against budget: actual spend per trade against the budget line,
  // with the overspend flagged.
  'control-cost-against-budget': (a) => (
    <>
      <path d="M20 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M20 34 H104" stroke={C.green} strokeWidth={1.6} strokeDasharray="3 2" fill="none" />
      <Bar x={26} baseY={66} w={12} h={26} fill={a.base} />
      <Bar x={44} baseY={66} w={12} h={30} fill={a.base} />
      <Bar x={62} baseY={66} w={12} h={38} fill={C.red} />
      <Bar x={80} baseY={66} w={12} h={24} fill={a.base} />
      <WarnTri cx={68} cy={22} w={12} fill={C.amber} />
    </>
  ),

  // Run the cost-value reconciliation: committed cost against value earned, and
  // the margin between them.
  'cost-value-reconciliation': (a) => (
    <>
      <path d="M26 66 H100" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={36} baseY={66} w={20} h={32} fill={a.base} />
      <Bar x={64} baseY={66} w={20} h={44} fill={C.green} />
      <path d="M56 34 H64" stroke={a.base} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <path
        d="M90 22 V34 M87 25 l3 -3 l3 3 M87 31 l3 3 l3 -3"
        stroke={a.base}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Chip x={34} y={69} w={22} h={9} fill={a.base} label="cost" />
      <Chip x={62} y={69} w={24} h={9} fill={C.green} label="value" />
    </>
  ),

  // Forecast project cash flow: the cash curve dips below zero and climbs back,
  // so the dip is seen early.
  'forecast-project-cash-flow': (a) => (
    <>
      <path d="M22 46 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M24 22 V70" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M24 44 C38 40 46 58 60 60 C74 62 82 40 102 26"
        fill="none"
        stroke={a.base}
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M52 66 h16" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <circle cx={60} cy={60} r={3} fill={C.red} stroke={C.white} strokeWidth={1} />
      <circle cx={102} cy={26} r={2.6} fill={C.green} stroke="none" />
    </>
  ),

  // Issue an electronic invoice: a certified total issued in a structured format
  // and tracked to paid.
  'issue-an-electronic-invoice': (a) => (
    <>
      <Sheet x={26} y={14} w={44} h={56} />
      <HeaderBand x={26} y={14} w={44} h={10} fill={a.base} />
      <RowBar x={32} y={18} w={20} h={3} fill={C.white} opacity={0.9} />
      <Chip x={54} y={16} w={16} h={7} fill={C.green} label="XML" />
      <RowBar x={32} y={32} w={28} h={3.2} fill={C.grey3} />
      <RowBar x={32} y={40} w={24} h={3.2} fill={C.grey3} />
      <path d="M32 50 H60" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={32} y={53} w={20} h={4} fill={a.deep} />
      <path d="M74 40 l14 -6 l-4 14 l-4 -5 z" fill={a.base} stroke="none" />
      <Badge cx={92} cy={58} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Check milestone progress before a valuation: the milestone is reached and
  // verified, then the drawdown is released.
  'milestone-progress-before-drawdown': (a) => (
    <>
      <path d="M18 32 H98" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <rect x={20} y={29} width={24} height={6} rx={3} fill={a.base} stroke="none" />
      <rect x={48} y={29} width={22} height={6} rx={3} fill={a.base} stroke="none" />
      <path d="M86 24 l7 8 l-7 8 l-7 -8 z" fill={a.base} stroke={C.white} strokeWidth={1.2} />
      <Badge cx={40} cy={56} r={8} fill={C.green} glyph="check" />
      <path
        d="M52 56 H62 M58 52 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={78} cy={56} r={11} fill={C.ochre} stroke={C.white} strokeWidth={1.4} />
      <circle cx={78} cy={56} r={6} fill="none" stroke={C.white} strokeWidth={1.2} opacity={0.7} />
    </>
  ),

  // Payment application and reconciliation: the certified amount reconciled
  // against what was actually paid.
  'payment-application-and-reconciliation': (a) => (
    <>
      <Sheet x={16} y={16} w={38} h={54} />
      <HeaderBand x={16} y={16} w={38} h={10} fill={a.base} />
      <RowBar x={22} y={20} w={18} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={22} y={34} w={24} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={42} w={20} h={3.2} fill={C.grey3} />
      <path d="M22 52 H46" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={22} y={55} w={18} h={4} fill={a.deep} />
      <Chip x={62} y={30} w={22} h={10} fill={a.light} label="cert" />
      <path d="M67 46 h10 M67 49 h10" stroke={C.grey1} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <Chip x={62} y={53} w={22} h={10} fill={C.green} label="paid" />
      <Badge cx={96} cy={40} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Prepare an interim payment application: value the work to date, take the
  // retention slice, issue it with its backup.
  'prepare-an-interim-payment-application': (a) => (
    <>
      <Sheet x={24} y={14} w={44} h={56} />
      <HeaderBand x={24} y={14} w={44} h={10} fill={a.base} />
      <RowBar x={30} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={30} y={32} w={30} h={3.2} fill={C.grey3} />
      <RowBar x={30} y={40} w={26} h={3.2} fill={C.grey3} />
      <rect x={30} y={48} width={32} height={6} rx={2} fill={C.grey3} stroke="none" />
      <rect x={54} y={48} width={8} height={6} rx={2} fill={C.ochre} stroke="none" />
      <path d="M30 60 H62" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={30} y={62} w={24} h={4} fill={a.deep} />
      <Sheet x={74} y={22} w={28} h={36} fill={C.panel} />
      <Sheet x={78} y={26} w={28} h={36} />
      <RowBar x={83} y={34} w={16} h={2.8} fill={C.grey3} />
      <RowBar x={83} y={40} w={13} h={2.8} fill={C.grey3} />
      <Badge cx={98} cy={54} r={5.5} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Run a three-way match before paying a supplier: the order, the receipt and
  // the invoice all agree before payment is released.
  'run-a-three-way-match-before-paying-a-supplier': (a) => (
    <>
      <Sheet x={14} y={12} w={28} h={18} />
      <Chip x={17} y={15} w={14} h={7} fill={a.base} label="PO" />
      <Sheet x={14} y={33} w={28} h={18} />
      <Chip x={17} y={36} w={16} h={7} fill={a.light} label="GRN" />
      <Sheet x={14} y={54} w={28} h={18} />
      <Chip x={17} y={57} w={18} h={7} fill={C.ochre} label="INV" />
      <path d="M44 21 C56 21 56 42 66 42" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path d="M44 42 H66" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path d="M44 63 C56 63 56 42 66 42" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <Badge cx={78} cy={42} r={9} fill={C.green} glyph="check" />
      <path
        d="M89 42 H100 M96 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Run a subcontractor package: place the trade on a subcontract with a
  // schedule of values and pay it down claim by claim.
  'subcontractor-package': (a) => (
    <>
      <Sheet x={20} y={14} w={44} h={56} />
      <HeaderBand x={20} y={14} w={44} h={10} fill={a.base} />
      <RowBar x={26} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={26} y={32} w={22} h={3.2} fill={C.grey3} />
      <Chip x={52} y={30} w={7} h={6} fill={C.green} />
      <RowBar x={26} y={40} w={18} h={3.2} fill={C.grey3} />
      <Chip x={52} y={38} w={7} h={6} fill={C.green} />
      <RowBar x={26} y={48} w={20} h={3.2} fill={C.grey3} />
      <Chip x={52} y={46} w={7} h={6} fill={C.amber} />
      <Signature x={26} y={61} w={24} color={a.base} />
      <circle cx={86} cy={40} r={12} fill={C.ochre} stroke={C.white} strokeWidth={1.4} />
      <circle cx={86} cy={40} r={6.5} fill="none" stroke={C.white} strokeWidth={1.3} opacity={0.7} />
    </>
  ),

  // Submit a subcontractor valuation and get paid: value your own work, submit
  // it, track it to cash.
  'subcontractor-self-billed-valuation': (a) => (
    <>
      <Sheet x={22} y={16} w={40} h={54} />
      <HeaderBand x={22} y={16} w={40} h={10} fill={a.base} />
      <RowBar x={28} y={20} w={18} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={28} y={32} w={24} h={3.2} fill={C.grey3} />
      <RowBar x={28} y={40} w={20} h={3.2} fill={C.grey3} />
      <path d="M28 50 H54" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={28} y={53} w={18} h={4} fill={a.deep} />
      <path d="M68 38 l14 -6 l-4 14 l-4 -5 z" fill={a.base} stroke="none" />
      <Badge cx={90} cy={56} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Track an opportunity from enquiry to tender: move it along the pipeline and
  // convert the win into a project.
  'track-an-opportunity-from-enquiry-to-tender': (a) => (
    <>
      <rect x={16} y={24} width={22} height={16} rx={2.5} fill={C.grey3} stroke="none" />
      <rect x={44} y={24} width={22} height={16} rx={2.5} fill={a.light} stroke="none" />
      <rect x={72} y={24} width={22} height={16} rx={2.5} fill={a.base} stroke="none" />
      <path d="M40 30 l4 2 l-4 2 M68 30 l4 2 l-4 2" fill={C.grey1} stroke="none" />
      <Star cx={83} cy={32} r={5} fill={C.ochre} />
      <Badge cx={55} cy={58} r={8} fill={C.green} glyph="check" />
      <Chip x={70} y={53} w={26} h={11} fill={C.green} label="project" />
    </>
  ),

  // ---- Handover & lifecycle ----

  // As-built and O and M handover: the finished building handed over with the
  // operation and maintenance package.
  'as-built-and-om-handover': (a) => (
    <>
      <rect x={20} y={30} width={30} height={38} rx={2} fill={a.base} stroke="none" />
      <path d="M18 30 L35 20 L52 30 Z" fill={a.deep} stroke="none" />
      <rect x={26} y={38} width={7} height={7} rx={1} fill={a.light} stroke="none" />
      <rect x={37} y={38} width={7} height={7} rx={1} fill={a.light} stroke="none" />
      <rect x={31} y={54} width={8} height={14} rx={1} fill={C.white} stroke="none" />
      <Sheet x={64} y={22} w={30} h={40} />
      <HeaderBand x={64} y={22} w={30} h={9} fill={C.ochre} />
      <RowBar x={70} y={36} w={18} h={3} fill={C.grey3} />
      <RowBar x={70} y={43} w={14} h={3} fill={C.grey3} />
      <RowBar x={70} y={50} w={16} h={3} fill={C.grey3} />
      <Badge cx={94} cy={58} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Assemble the O&M handover manual: as-builts, certificates and warranties
  // gathered into tabbed sections and checked against the index.
  'assemble-the-om-handover-manual': (a) => (
    <>
      <Sheet x={30} y={14} w={48} h={58} />
      <HeaderBand x={30} y={14} w={48} h={11} fill={C.ochre} />
      <RowBar x={36} y={18} w={24} h={3.4} fill={C.white} opacity={0.9} />
      <rect x={78} y={26} width={9} height={9} rx={1.5} fill={a.base} stroke="none" />
      <rect x={78} y={38} width={9} height={9} rx={1.5} fill={C.green} stroke="none" />
      <rect x={78} y={50} width={9} height={9} rx={1.5} fill={a.light} stroke="none" />
      <Badge cx={40} cy={34} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={46} y={32.5} w={22} h={3} fill={C.grey3} />
      <Badge cx={40} cy={44} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={46} y={42.5} w={18} h={3} fill={C.grey3} />
      <Badge cx={40} cy={54} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={46} y={52.5} w={20} h={3} fill={C.grey3} />
    </>
  ),

  // Check the asset data drop before handover: read what the model carries and
  // check it against the requirements.
  'check-the-asset-data-drop-before-handover': (a) => (
    <>
      <Cube cx={30} ty={26} w={14} hh={7} depth={16} top={a.light} left={a.base} right={a.deep} />
      <path
        d="M46 40 H56 M52 36 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={58} y={18} w={46} h={48} />
      <HeaderBand x={58} y={18} w={46} h={9} fill={a.base} />
      <Badge cx={65} cy={36} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={71} y={34.5} w={26} h={3} fill={C.grey3} />
      <Badge cx={65} cy={45} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={71} y={43.5} w={22} h={3} fill={C.grey3} />
      <Badge cx={65} cy={54} r={3.6} fill={C.red} glyph="x" shadow={false} />
      <RowBar x={71} y={52.5} w={24} h={3} fill={C.grey3} />
    </>
  ),

  // Manage the defects liability period: reported defects driven to zero before
  // the liability period closes.
  'defects-liability-period-tracking': (a) => (
    <>
      <Sheet x={18} y={16} w={40} h={54} />
      <HeaderBand x={18} y={16} w={40} h={10} fill={a.base} />
      <RowBar x={24} y={20} w={20} h={3} fill={C.white} opacity={0.9} />
      <circle cx={28} cy={34} r={2.4} fill={C.green} stroke="none" />
      <RowBar x={33} y={32.5} w={22} h={3} fill={C.grey3} />
      <circle cx={28} cy={43} r={2.4} fill={C.green} stroke="none" />
      <RowBar x={33} y={41.5} w={18} h={3} fill={C.grey3} />
      <circle cx={28} cy={52} r={2.4} fill={C.amber} stroke="none" />
      <RowBar x={33} y={50.5} w={20} h={3} fill={C.grey3} />
      <rect x={70} y={26} width={30} height={30} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <rect x={70} y={26} width={30} height={8} rx={3} fill={a.base} stroke="none" />
      <path d="M76 23 v5 M94 23 v5" stroke={a.deep} strokeWidth={2} strokeLinecap="round" />
      <circle cx={85} cy={44} r={7} fill="none" stroke={a.base} strokeWidth={1.6} />
      <path d="M85 40 v4 l3 2" stroke={a.base} strokeWidth={1.8} fill="none" strokeLinecap="round" />
    </>
  ),

  // Draft the first year maintenance budget: assets priced for planned and
  // reactive work into a first-year number.
  'draft-the-first-year-maintenance-budget': (a) => (
    <>
      <Sheet x={18} y={16} w={40} h={54} />
      <HeaderBand x={18} y={16} w={40} h={10} fill={a.base} />
      <RowBar x={24} y={20} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={24} y={32} w={20} h={3.2} fill={C.grey3} />
      <Chip x={46} y={30} w={8} h={6} fill={C.green} />
      <RowBar x={24} y={40} w={16} h={3.2} fill={C.grey3} />
      <Chip x={46} y={38} w={8} h={6} fill={C.green} />
      <RowBar x={24} y={48} w={18} h={3.2} fill={C.grey3} />
      <Chip x={46} y={46} w={8} h={6} fill={C.green} />
      <path d="M24 58 H52" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={24} y={61} w={18} h={4} fill={a.deep} />
      <circle cx={82} cy={34} r={13} fill={a.base} stroke={C.white} strokeWidth={1.4} />
      <path d="M82 26 v8 l6 3" stroke={C.white} strokeWidth={2} fill="none" strokeLinecap="round" />
      <Chip x={71} y={52} w={22} h={11} fill={C.green} label="yr 1" />
    </>
  ),

  // Manage the drawing register and transmittals: current revisions tracked and
  // issued by formal transmittal.
  'manage-the-drawing-register-and-transmittals': (a) => (
    <>
      <Sheet x={16} y={16} w={46} h={54} />
      <HeaderBand x={16} y={16} w={46} h={10} fill={a.base} />
      <RowBar x={22} y={20} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={22} y={32} w={20} h={3.2} fill={C.grey3} />
      <Chip x={46} y={30} w={12} h={6} fill={C.green} label="C" />
      <RowBar x={22} y={40} w={18} h={3.2} fill={C.grey3} />
      <Chip x={46} y={38} w={12} h={6} fill={C.grey2} label="B" labelFill={C.ink} />
      <RowBar x={22} y={48} w={20} h={3.2} fill={C.grey3} />
      <Chip x={46} y={46} w={12} h={6} fill={C.grey2} label="A" labelFill={C.ink} />
      <path
        d="M64 39 H72 M68 35 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={74} y={28} width={30} height={22} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <path d="M74 30 L89 40 L104 30" fill="none" stroke={C.grey1} strokeWidth={1.4} />
      <Chip x={80} y={54} w={20} h={8} fill={a.base} label="issued" />
    </>
  ),

  // Plan preventive maintenance from the asset register: recurring service tasks
  // scheduled across the year.
  'plan-preventive-maintenance-from-the-asset-register': (a) => (
    <>
      <rect x={18} y={30} width={26} height={26} rx={3} fill={a.base} stroke="none" />
      <circle cx={31} cy={43} r={7} fill="none" stroke={C.white} strokeWidth={2} />
      <path d="M31 37 v6 l4 2" stroke={C.white} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <path
        d="M50 43 H60 M56 39 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={64} y={22} width={40} height={40} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <rect x={64} y={22} width={40} height={9} rx={3} fill={a.base} stroke="none" />
      <circle cx={73} cy={41} r={2.4} fill={C.green} stroke="none" />
      <circle cx={84} cy={41} r={2.4} fill={C.grey3} stroke="none" />
      <circle cx={95} cy={41} r={2.4} fill={C.green} stroke="none" />
      <circle cx={73} cy={52} r={2.4} fill={C.grey3} stroke="none" />
      <circle cx={84} cy={52} r={2.4} fill={C.green} stroke="none" />
      <circle cx={95} cy={52} r={2.4} fill={C.grey3} stroke="none" />
    </>
  ),

  // Raise and close a warranty claim: an in-warranty asset, the claim, and a
  // clean closeout.
  'raise-and-close-a-warranty-claim': (a) => (
    <>
      <rect x={16} y={34} width={28} height={26} rx={3} fill={a.base} stroke="none" />
      <circle cx={27} cy={47} r={6} fill="none" stroke={C.white} strokeWidth={2} />
      <path d="M27 43 v4 l3 2" stroke={C.white} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <Shield cx={42} ty={28} w={16} h={18} fill={C.green} shadow={false} />
      <path
        d="M38 36 l2.5 2.5 l4.5 -4.5"
        stroke={C.white}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M52 44 H62 M58 40 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={64} y={22} w={30} h={40} />
      <RowBar x={70} y={32} w={18} h={3} fill={C.grey3} />
      <RowBar x={70} y={40} w={14} h={3} fill={C.grey3} />
      <Badge cx={90} cy={56} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Run a handover acceptance inspection: walk the finished works, clear the
  // defects, sign the acceptance.
  'run-a-handover-acceptance-inspection': (a) => (
    <>
      <rect x={18} y={34} width={26} height={34} rx={2} fill={a.base} stroke="none" />
      <path d="M16 34 L31 24 L46 34 Z" fill={a.deep} stroke="none" />
      <rect x={23} y={41} width={6} height={6} rx={1} fill={a.light} stroke="none" />
      <rect x={33} y={41} width={6} height={6} rx={1} fill={a.light} stroke="none" />
      <Sheet x={58} y={16} w={40} h={54} />
      <rect x={72} y={12} width={12} height={7} rx={2} fill={C.grey2} stroke="none" />
      <Badge cx={66} cy={34} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={72} y={32.5} w={22} h={3} fill={C.grey3} />
      <Badge cx={66} cy={44} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={72} y={42.5} w={18} h={3} fill={C.grey3} />
      <Signature x={66} y={58} w={24} color={a.base} />
    </>
  ),

  // Run reactive FM service after handover: a reactive request worked with the
  // asset data and closed out.
  'run-reactive-fm-service-after-handover': (a) => (
    <>
      <Sheet x={18} y={18} w={36} h={50} />
      <HeaderBand x={18} y={18} w={36} h={9} fill={C.red} />
      <RowBar x={24} y={22} w={16} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={24} y={34} w={22} h={3} fill={C.grey3} />
      <RowBar x={24} y={42} w={18} h={3} fill={C.grey3} />
      <RowBar x={24} y={50} w={20} h={3} fill={C.grey3} />
      <circle cx={70} cy={42} r={10} fill={a.base} stroke="none" />
      <path
        d="M70 27 V34 M70 50 V57 M55 42 H62 M78 42 H85 M60 32 l-5 -5 M80 52 l5 5 M60 52 l-5 5 M80 32 l5 -5"
        stroke={a.base}
        strokeWidth={3.2}
        strokeLinecap="round"
        fill="none"
      />
      <circle cx={70} cy={42} r={4.5} fill={C.white} stroke="none" />
      <Badge cx={92} cy={58} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Set up the asset register for FM: installed assets captured with location
  // and key data, manuals attached.
  'set-up-the-asset-register-for-fm': (a) => (
    <>
      <Sheet x={16} y={16} w={46} h={54} />
      <HeaderBand x={16} y={16} w={46} h={10} fill={a.base} />
      <RowBar x={22} y={20} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={22} y={32} w={18} h={3.2} fill={C.grey3} />
      <Chip x={44} y={30} w={12} h={6} fill={a.light} label="A1" />
      <RowBar x={22} y={40} w={20} h={3.2} fill={C.grey3} />
      <Chip x={44} y={38} w={12} h={6} fill={a.light} label="A2" />
      <RowBar x={22} y={48} w={16} h={3.2} fill={C.grey3} />
      <Chip x={44} y={46} w={12} h={6} fill={a.light} label="A3" />
      <path
        d="M84 22 c-6 0 -10 4 -10 10 c0 7 10 16 10 16 c0 0 10 -9 10 -16 c0 -6 -4 -10 -10 -10 z"
        fill={a.base}
        stroke={C.white}
        strokeWidth={1.2}
      />
      <circle cx={84} cy={32} r={3.6} fill={C.white} stroke="none" />
      <Sheet x={76} y={52} w={22} h={16} />
      <RowBar x={80} y={58} w={12} h={2.6} fill={C.grey3} />
    </>
  ),

  // ---- Planning & controls ----

  // Balance the portfolio and level resources: demand across projects held under
  // the capacity line, with the peak flagged.
  'balance-the-portfolio-and-level-resources': (a) => (
    <>
      <rect x={16} y={24} width={26} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={16} y={33} width={34} height={5} rx={2.5} fill={a.light} stroke="none" />
      <rect x={16} y={42} width={20} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={16} y={51} width={30} height={5} rx={2.5} fill={a.light} stroke="none" />
      <path d="M60 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M58 36 H104" stroke={C.green} strokeWidth={1.6} strokeDasharray="3 2" fill="none" />
      <Bar x={64} baseY={66} w={10} h={24} fill={a.light} />
      <Bar x={80} baseY={66} w={10} h={42} fill={C.red} />
      <Bar x={94} baseY={66} w={10} h={20} fill={a.light} />
      <WarnTri cx={85} cy={20} w={11} fill={C.amber} />
    </>
  ),

  // Build the baseline programme: linked activities on the critical path with a
  // milestone.
  'build-the-baseline-programme': (a) => (
    <>
      <Sheet x={16} y={16} w={90} h={54} />
      <HeaderBand x={16} y={16} w={90} h={9} fill={a.base} />
      <RowBar x={22} y={20} w={20} h={3} fill={C.white} opacity={0.9} />
      <rect x={24} y={32} width={24} height={5} rx={2.5} fill={C.red} stroke="none" />
      <rect x={40} y={41} width={28} height={5} rx={2.5} fill={C.red} stroke="none" />
      <rect x={60} y={50} width={22} height={5} rx={2.5} fill={a.light} stroke="none" />
      <path d="M48 34.5 h4 v6.5" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M68 43.5 h4 v6.5" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M92 47 l4 5 l-4 5 l-4 -5 z" fill={a.base} stroke={C.white} strokeWidth={1} />
    </>
  ),

  // Compile the weekly progress report: the marked-up programme, a week of
  // evidence and the published report.
  'compile-weekly-progress-report': (a) => (
    <>
      <Sheet x={14} y={16} w={54} h={40} />
      <rect x={20} y={24} width={30} height={5} rx={2.5} fill={C.grey3} stroke="none" />
      <rect x={20} y={24} width={20} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={20} y={33} width={36} height={5} rx={2.5} fill={C.grey3} stroke="none" />
      <rect x={20} y={33} width={22} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={20} y={42} width={26} height={5} rx={2.5} fill={C.grey3} stroke="none" />
      <rect x={20} y={42} width={12} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={16} y={58} width={22} height={16} rx={2} fill={a.light} stroke={C.white} strokeWidth={1.2} />
      <circle cx={22} cy={63} r={2} fill={C.white} stroke="none" />
      <path d="M18 72 l6 -5 l4 3 l4 -4 l4 6 z" fill={a.deep} stroke="none" />
      <Sheet x={76} y={20} w={30} h={44} />
      <HeaderBand x={76} y={20} w={30} h={9} fill={a.base} />
      <RowBar x={82} y={34} w={18} h={3} fill={C.grey3} />
      <RowBar x={82} y={41} w={14} h={3} fill={C.grey3} />
      <Badge cx={101} cy={58} r={6} fill={C.green} glyph="check" />
    </>
  ),

  // Balance crews and plant across the programme: the near-term demand set
  // against what is booked, for crew and for plant.
  'crew-and-plant-lookahead-balance': (a) => (
    <>
      <path d="M20 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={28} baseY={66} w={12} h={34} fill={a.base} />
      <Bar x={42} baseY={66} w={12} h={24} fill={C.grey2} />
      <Bar x={68} baseY={66} w={12} h={28} fill={a.base} />
      <Bar x={82} baseY={66} w={12} h={30} fill={C.grey2} />
      <circle cx={34} cy={20} r={4} fill={a.base} stroke="none" />
      <path d="M28 30 c0 -5 3 -8 6 -8 s6 3 6 8 z" fill={a.base} stroke="none" />
      <rect x={74} y={16} width={14} height={12} rx={2} fill={C.ochre} stroke="none" />
      <circle cx={77} cy={30} r={2.4} fill={a.deep} stroke="none" />
      <circle cx={85} cy={30} r={2.4} fill={a.deep} stroke="none" />
    </>
  ),

  // Earned value and forecast: planned against earned value, extended to a
  // forecast outturn.
  'earned-value-and-forecast': (a) => (
    <>
      <path d="M18 68 H104 M18 68 V18" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M18 66 C40 60 60 40 96 22" fill="none" stroke={C.grey2} strokeWidth={2} strokeLinecap="round" />
      <path d="M18 66 C36 62 52 50 70 44" fill="none" stroke={a.base} strokeWidth={2.4} strokeLinecap="round" />
      <path
        d="M70 44 C82 40 90 34 100 30"
        fill="none"
        stroke={a.base}
        strokeWidth={2.2}
        strokeDasharray="3 3"
        strokeLinecap="round"
      />
      <circle cx={70} cy={44} r={2.6} fill={a.base} stroke="none" />
      <circle cx={100} cy={30} r={2.6} fill={a.base} stroke="none" />
    </>
  ),

  // Plan repetitive work with takt and line of balance: parallel trade lines
  // marching through the zones at a steady beat.
  'plan-repetitive-work-with-takt-and-line-of-balance': (a) => (
    <>
      <path d="M20 68 H104 M20 68 V16" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M20 30 H104 M20 44 H104 M20 58 H104" stroke={C.grey3} strokeWidth={0.8} fill="none" />
      <path d="M24 64 L60 20" stroke={a.base} strokeWidth={2.2} strokeLinecap="round" fill="none" />
      <path d="M36 64 L72 20" stroke={C.green} strokeWidth={2.2} strokeLinecap="round" fill="none" />
      <path d="M48 64 L84 20" stroke={C.ochre} strokeWidth={2.2} strokeLinecap="round" fill="none" />
      <path d="M60 64 L96 20" stroke={a.base} strokeWidth={2.2} strokeLinecap="round" fill="none" />
    </>
  ),

  // Produce a short-interval lookahead: the next weeks pulled off the programme
  // with the constraints cleared.
  'produce-a-short-interval-lookahead': (a) => (
    <>
      <rect x={16} y={20} width={44} height={44} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <rect x={16} y={20} width={44} height={9} rx={3} fill={a.base} stroke="none" />
      <rect x={22} y={34} width={9} height={9} rx={1.5} fill={a.base} stroke="none" />
      <rect x={34} y={34} width={9} height={9} rx={1.5} fill={a.light} stroke="none" />
      <rect x={46} y={34} width={9} height={9} rx={1.5} fill={a.light} stroke="none" />
      <rect x={22} y={48} width={9} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={34} y={48} width={9} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <Badge cx={72} cy={30} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={78} y={28.5} w={22} h={3} fill={C.grey3} />
      <Badge cx={72} cy={40} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={78} y={38.5} w={18} h={3} fill={C.grey3} />
      <Badge cx={72} cy={50} r={3.6} fill={C.amber} glyph="warn" shadow={false} />
      <RowBar x={78} y={48.5} w={20} h={3} fill={C.grey3} />
    </>
  ),

  // Set up a project and hand it over: the full lifecycle from creation to a
  // handed-over building.
  'project-end-to-end': (a) => (
    <>
      <circle cx={20} cy={34} r={6} fill={a.light} stroke="none" />
      <circle cx={40} cy={34} r={6} fill={a.base} stroke="none" />
      <circle cx={60} cy={34} r={6} fill={a.base} stroke="none" />
      <circle cx={80} cy={34} r={6} fill={a.base} stroke="none" />
      <path d="M26 34 H34 M46 34 H54 M66 34 H74" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <rect x={92} y={26} width={14} height={18} rx={1} fill={a.deep} stroke="none" />
      <path d="M91 26 L99 20 L107 26 Z" fill={a.deep} stroke="none" />
      <path d="M18 54 H98" stroke={C.grey3} strokeWidth={4} strokeLinecap="round" />
      <path d="M18 54 H78" stroke={a.base} strokeWidth={4} strokeLinecap="round" />
      <Badge cx={100} cy={54} r={5.5} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Protect the programme from a long-lead item: a long delivery bar tied back
  // to the need-by date on the programme.
  'protect-the-programme-from-a-long-lead-item': (a) => (
    <>
      <Sheet x={14} y={16} w={92} h={40} />
      <HeaderBand x={14} y={16} w={92} h={9} fill={a.base} />
      <rect x={20} y={30} width={26} height={5} rx={2.5} fill={a.light} stroke="none" />
      <rect x={40} y={39} width={30} height={5} rx={2.5} fill={a.light} stroke="none" />
      <rect x={20} y={48} width={64} height={5} rx={2.5} fill={C.ochre} stroke="none" />
      <path d="M84 26 V58" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <circle cx={92} cy={64} r={7} fill={C.white} stroke={a.base} strokeWidth={1.8} />
      <path d="M92 60 v4 l3 2" stroke={a.base} strokeWidth={1.6} fill="none" strokeLinecap="round" />
    </>
  ),

  // Review and mitigate the risk register: a risk moved from the red corner down
  // to green by its mitigation.
  'review-and-mitigate-project-risks': (a) => (
    <>
      <rect x={20} y={18} width={48} height={48} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <rect x={20} y={18} width={16} height={16} fill={C.green} opacity={0.5} stroke="none" />
      <rect x={36} y={18} width={16} height={16} fill={C.amber} opacity={0.5} stroke="none" />
      <rect x={52} y={18} width={16} height={16} fill={C.red} opacity={0.5} stroke="none" />
      <rect x={20} y={34} width={16} height={16} fill={C.green} opacity={0.5} stroke="none" />
      <rect x={36} y={34} width={16} height={16} fill={C.amber} opacity={0.5} stroke="none" />
      <rect x={52} y={34} width={16} height={16} fill={C.amber} opacity={0.5} stroke="none" />
      <rect x={20} y={50} width={16} height={16} fill={C.green} opacity={0.5} stroke="none" />
      <rect x={36} y={50} width={16} height={16} fill={C.green} opacity={0.5} stroke="none" />
      <rect x={52} y={50} width={16} height={16} fill={C.amber} opacity={0.5} stroke="none" />
      <path d="M36 18 V66 M52 18 V66 M20 34 H68 M20 50 H68" stroke={C.white} strokeWidth={1} fill="none" />
      <circle cx={60} cy={26} r={3.2} fill={C.red} stroke={C.white} strokeWidth={1} />
      <path d="M57 30 L45 46" stroke={a.base} strokeWidth={1.8} strokeDasharray="2 2" fill="none" />
      <circle cx={44} cy={48} r={3.2} fill={C.green} stroke={C.white} strokeWidth={1} />
    </>
  ),

  // Run a progress meeting and drive the actions: the meeting turned into an
  // owned action list.
  'run-a-progress-meeting-and-drive-the-actions': (a) => (
    <>
      <ellipse cx={38} cy={44} rx={22} ry={12} fill={C.panel} stroke={C.grey1} strokeWidth={1.4} />
      <circle cx={24} cy={36} r={4} fill={a.base} stroke="none" />
      <circle cx={38} cy={32} r={4} fill={a.light} stroke="none" />
      <circle cx={52} cy={36} r={4} fill={a.base} stroke="none" />
      <circle cx={24} cy={52} r={4} fill={a.light} stroke="none" />
      <circle cx={52} cy={52} r={4} fill={a.light} stroke="none" />
      <Sheet x={72} y={18} w={32} h={48} />
      <HeaderBand x={72} y={18} w={32} h={9} fill={a.base} />
      <Badge cx={79} cy={36} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={85} y={34.5} w={16} h={3} fill={C.grey3} />
      <Badge cx={79} cy={45} r={3.4} fill={C.amber} glyph="none" shadow={false} />
      <RowBar x={85} y={43.5} w={13} h={3} fill={C.grey3} />
      <Badge cx={79} cy={54} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={85} y={52.5} w={15} h={3} fill={C.grey3} />
    </>
  ),

  // Build a baseline and track progress: progress filling against the frozen
  // baseline bars, read at the cut-off.
  'schedule-and-track': (a) => (
    <>
      <Sheet x={16} y={16} w={90} h={54} />
      <HeaderBand x={16} y={16} w={90} h={9} fill={a.base} />
      <RowBar x={22} y={20} w={20} h={3} fill={C.white} opacity={0.9} />
      <rect x={24} y={32} width={40} height={5} rx={2.5} fill="none" stroke={C.grey1} strokeWidth={1.2} />
      <rect x={24} y={32} width={30} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={24} y={42} width={50} height={5} rx={2.5} fill="none" stroke={C.grey1} strokeWidth={1.2} />
      <rect x={24} y={42} width={34} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={24} y={52} width={30} height={5} rx={2.5} fill="none" stroke={C.grey1} strokeWidth={1.2} />
      <rect x={24} y={52} width={22} height={5} rx={2.5} fill={a.base} stroke="none" />
      <path d="M64 28 V62" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
    </>
  ),

  // Set up a new project: a new record seeded with its bill of quantities and a
  // first programme.
  'set-up-a-new-project': (a) => (
    <>
      <Sheet x={20} y={16} w={40} h={54} />
      <HeaderBand x={20} y={16} w={40} h={10} fill={a.base} />
      <RowBar x={26} y={20} w={18} h={3} fill={C.white} opacity={0.9} />
      <Badge cx={40} cy={46} r={11} fill={a.base} glyph="plus" />
      <Sheet x={70} y={20} w={34} h={22} />
      <RowBar x={75} y={27} w={18} h={2.8} fill={C.grey3} />
      <RowBar x={75} y={33} w={14} h={2.8} fill={C.grey3} />
      <rect x={70} y={48} width={34} height={20} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <rect x={74} y={54} width={18} height={4} rx={2} fill={a.light} stroke="none" />
      <rect x={80} y={61} width={20} height={4} rx={2} fill={a.base} stroke="none" />
    </>
  ),

  // Update the programme and reforecast: real progress marked in, the finish
  // date reforecast and slipping to the right.
  'update-the-programme-and-reforecast': (a) => (
    <>
      <Sheet x={14} y={16} w={92} h={54} />
      <HeaderBand x={14} y={16} w={92} h={9} fill={a.base} />
      <rect x={22} y={30} width={30} height={5} rx={2.5} fill={C.grey3} stroke="none" />
      <rect x={22} y={30} width={22} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={22} y={39} width={38} height={5} rx={2.5} fill={C.grey3} stroke="none" />
      <rect x={22} y={39} width={20} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={22} y={48} width={28} height={5} rx={2.5} fill={C.grey3} stroke="none" />
      <rect x={22} y={48} width={10} height={5} rx={2.5} fill={a.base} stroke="none" />
      <path d="M74 26 V60" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <path d="M88 26 V60" stroke={C.red} strokeWidth={1.6} fill="none" />
      <path
        d="M76 22 H88 M84 19 l4 3 l-4 3"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // ---- Quality & safety ----

  // Build and run an inspection and test plan: hold and witness points inspected
  // and signed off as the work reaches them.
  'build-and-run-an-itp': (a) => (
    <>
      <Sheet x={22} y={16} w={44} h={54} />
      <HeaderBand x={22} y={16} w={44} h={10} fill={a.base} />
      <RowBar x={28} y={20} w={22} h={3} fill={C.white} opacity={0.9} />
      <Chip x={28} y={32} w={9} h={7} fill={C.red} label="H" />
      <RowBar x={40} y={33.5} w={18} h={3} fill={C.grey3} />
      <Badge cx={62} cy={35} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <Chip x={28} y={44} w={9} h={7} fill={C.amber} label="W" />
      <RowBar x={40} y={45.5} w={15} h={3} fill={C.grey3} />
      <Badge cx={62} cy={47} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <Chip x={28} y={56} w={9} h={7} fill={C.red} label="H" />
      <RowBar x={40} y={57.5} w={16} h={3} fill={C.grey3} />
      <Stamp cx={86} cy={30} r={7} color={C.green} />
      <Signature x={76} y={50} w={22} color={a.base} />
    </>
  ),

  // Clear the snag list before handover: every snag worked down and re-inspected
  // to a clean list.
  'clear-the-snag-list-before-handover': (a) => (
    <>
      <Sheet x={22} y={14} w={44} h={56} />
      <HeaderBand x={22} y={14} w={44} h={10} fill={a.base} />
      <RowBar x={28} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <Badge cx={32} cy={32} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={38} y={30.5} w={22} h={3} fill={C.grey3} />
      <Badge cx={32} cy={42} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={38} y={40.5} w={18} h={3} fill={C.grey3} />
      <Badge cx={32} cy={52} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={38} y={50.5} w={20} h={3} fill={C.grey3} />
      <circle cx={88} cy={40} r={13} fill="none" stroke={C.green} strokeWidth={3} />
      <path
        d="M81 40 l5 6 l9 -11"
        stroke={C.green}
        strokeWidth={3}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Inspect work and close a non-conformance: work inspected, an NCR raised and
  // driven to a re-inspected close.
  'inspect-and-close-ncr': (a) => (
    <>
      <rect x={18} y={30} width={30} height={28} rx={2} fill={C.panel} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M24 40 H42 M24 48 H38" stroke={C.grey2} strokeWidth={2} strokeLinecap="round" fill="none" />
      <Magnifier cx={44} cy={48} r={9} />
      <Chip x={58} y={24} w={22} h={11} fill={C.red} label="NCR" />
      <path
        d="M64 40 V50 M60 46 l4 4 l4 -4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={72} cy={58} r={9} fill={C.green} glyph="check" />
    </>
  ),

  // Get a material submittal approved: the product and its data checked against
  // the spec and stamped for order.
  'material-submittal-and-approval': (a) => (
    <>
      <rect x={18} y={30} width={22} height={26} rx={3} fill={C.ochre} stroke={C.white} strokeWidth={1.4} />
      <rect x={22} y={34} width={14} height={8} rx={1.5} fill={C.white} opacity={0.5} stroke="none" />
      <path
        d="M44 42 H54 M50 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={56} y={18} w={34} h={48} />
      <HeaderBand x={56} y={18} w={34} h={9} fill={a.base} />
      <RowBar x={62} y={32} w={20} h={3} fill={C.grey3} />
      <RowBar x={62} y={40} w={16} h={3} fill={C.grey3} />
      <Stamp cx={82} cy={54} r={9} color={C.green} />
    </>
  ),

  // Run a safety walk and log observations: walk the site against a checklist
  // and raise the unsafe conditions.
  'run-a-safety-walk-and-log-observations': (a) => (
    <>
      <path d="M20 46 a16 16 0 0 1 32 0 z" fill={C.amber} stroke="none" />
      <rect x={16} y={46} width={40} height={5} rx={2.5} fill={C.ochre} stroke="none" />
      <rect x={33} y={26} width={6} height={8} rx={2} fill={C.ochre} stroke="none" />
      <Sheet x={64} y={16} w={40} h={54} />
      <HeaderBand x={64} y={16} w={40} h={9} fill={a.base} />
      <Badge cx={71} cy={34} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={77} y={32.5} w={22} h={3} fill={C.grey3} />
      <Badge cx={71} cy={44} r={3.4} fill={C.red} glyph="warn" shadow={false} />
      <RowBar x={77} y={42.5} w={18} h={3} fill={C.grey3} />
      <Badge cx={71} cy={54} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={77} y={52.5} w={20} h={3} fill={C.grey3} />
    </>
  ),

  // Get prequalified and onboarded as a subcontractor: insurance and safety
  // record approved onto the invited list.
  'subcontractor-prequalification-and-onboarding': (a) => (
    <>
      <Sheet x={16} y={20} w={26} h={20} />
      <Shield cx={29} ty={22} w={12} h={14} fill={C.green} />
      <Sheet x={16} y={44} w={26} h={20} />
      <Stamp cx={29} cy={54} r={6} color={a.base} />
      <path
        d="M46 42 H56 M52 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={58} y={18} w={46} h={48} />
      <HeaderBand x={58} y={18} w={46} h={9} fill={a.base} />
      <Badge cx={65} cy={36} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={71} y={34.5} w={26} h={3} fill={C.grey3} />
      <Badge cx={65} cy={45} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={71} y={43.5} w={22} h={3} fill={C.grey3} />
      <Badge cx={65} cy={54} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={71} y={52.5} w={24} h={3} fill={C.grey3} />
    </>
  ),

  // Toolbox talk and safety check: brief the crew on the hazard and verify the
  // controls are up.
  'toolbox-talk-and-safety': (a) => (
    <>
      <circle cx={28} cy={30} r={6} fill={a.base} stroke="none" />
      <path d="M18 50 c0 -8 5 -12 10 -12 s10 4 10 12 z" fill={a.base} stroke="none" />
      <WarnTri cx={46} cy={26} w={12} fill={C.amber} />
      <Sheet x={60} y={18} w={44} h={50} />
      <HeaderBand x={60} y={18} w={44} h={9} fill={a.base} />
      <Badge cx={67} cy={34} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={73} y={32.5} w={24} h={3} fill={C.grey3} />
      <Badge cx={67} cy={44} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={73} y={42.5} w={20} h={3} fill={C.grey3} />
      <Badge cx={67} cy={54} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={73} y={52.5} w={22} h={3} fill={C.grey3} />
    </>
  ),

  // Witness and record MEP commissioning: each system witnessed live and the
  // certificate filed.
  'witness-and-record-mep-commissioning': (a) => (
    <>
      <path d="M16 40 H40 M28 40 V56" stroke={a.base} strokeWidth={4} fill="none" strokeLinecap="round" />
      <circle cx={40} cy={30} r={10} fill={C.white} stroke={a.base} strokeWidth={2} />
      <path d="M40 30 L45 25" stroke={C.red} strokeWidth={2} strokeLinecap="round" fill="none" />
      <circle cx={40} cy={30} r={1.6} fill={a.deep} stroke="none" />
      <Badge cx={58} cy={44} r={7} fill={C.green} glyph="check" />
      <Sheet x={70} y={20} w={34} h={44} />
      <HeaderBand x={70} y={20} w={34} h={9} fill={C.ochre} />
      <RowBar x={76} y={34} w={20} h={3} fill={C.grey3} />
      <RowBar x={76} y={42} w={16} h={3} fill={C.grey3} />
      <Stamp cx={92} cy={54} r={7} color={C.green} />
    </>
  ),

  // ---- Site & field ----

  // Answer an RFI: a site question routed to the owner and filed as the answer.
  'answer-an-rfi': (a) => (
    <>
      <path
        d="M14 18 h30 a5 5 0 0 1 5 5 v14 a5 5 0 0 1 -5 5 H30 l-8 7 v-7 h-8 a5 5 0 0 1 -5 -5 V23 a5 5 0 0 1 5 -5 z"
        fill={a.light}
        stroke="none"
      />
      <path
        d="M25 26 a4 4 0 0 1 8 0 c0 3 -4 3 -4 6"
        stroke={C.white}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={29} cy={36} r={1.5} fill={C.white} stroke="none" />
      <path
        d="M54 34 H66 M62 30 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={68} y={20} w={36} h={46} />
      <HeaderBand x={68} y={20} w={36} h={9} fill={a.base} />
      <RowBar x={74} y={34} w={20} h={3} fill={C.grey3} />
      <RowBar x={74} y={42} w={16} h={3} fill={C.grey3} />
      <Badge cx={96} cy={58} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Capture daywork and time and materials: labour, plant and materials recorded
  // and signed on the day.
  'capture-daywork-and-time-and-materials': (a) => (
    <>
      <Sheet x={26} y={14} w={44} h={56} />
      <HeaderBand x={26} y={14} w={44} h={10} fill={C.ochre} />
      <RowBar x={32} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <Chip x={32} y={30} w={9} h={7} fill={a.base} label="L" />
      <RowBar x={44} y={31.5} w={20} h={3} fill={C.grey3} />
      <Chip x={32} y={42} w={9} h={7} fill={a.light} label="P" />
      <RowBar x={44} y={43.5} w={16} h={3} fill={C.grey3} />
      <Chip x={32} y={54} w={9} h={7} fill={C.green} label="M" />
      <RowBar x={44} y={55.5} w={18} h={3} fill={C.grey3} />
      <Signature x={78} y={40} w={22} color={a.base} />
      <Badge cx={88} cy={26} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Issue a controlled drawing revision: the old revision superseded and the new
  // one made current.
  'issue-a-controlled-drawing-revision': (a) => (
    <>
      <Sheet x={16} y={22} w={34} h={44} fill={C.panel} />
      <path d="M22 32 H44 M22 42 H38" stroke={C.grey2} strokeWidth={1.4} fill="none" />
      <path d="M18 60 l30 -34" stroke={C.red} strokeWidth={2} strokeLinecap="round" opacity={0.7} fill="none" />
      <Chip x={20} y={53} w={22} h={8} fill={C.grey2} label="Rev A" labelFill={C.ink} />
      <path d="M52 40 H58" stroke={a.base} strokeWidth={2} fill="none" />
      <Sheet x={58} y={16} w={40} h={50} />
      <path d="M64 28 H90 M64 40 H84" stroke={C.grey2} strokeWidth={1.4} fill="none" />
      <Chip x={64} y={52} w={22} h={9} fill={C.green} label="Rev B" />
      <Badge cx={96} cy={22} r={6} fill={C.green} glyph="check" />
    </>
  ),

  // Issue a permit to work: the permit tied to its safe system of work.
  'issue-a-permit-to-work': (a) => (
    <>
      <Sheet x={24} y={14} w={40} h={56} />
      <HeaderBand x={24} y={14} w={40} h={10} fill={C.green} />
      <RowBar x={30} y={18} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={30} y={32} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={30} y={40} w={22} h={3.2} fill={C.grey3} />
      <Signature x={30} y={54} w={22} color={a.base} />
      <path
        d="M65 38 a3 3 0 0 0 0 6 h3 M75 44 a3 3 0 0 0 0 -6 h-3 M67 41 h6"
        stroke={a.base}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
      <Sheet x={76} y={24} w={28} h={36} />
      <HeaderBand x={76} y={24} w={28} h={7} fill={C.amber} />
      <RowBar x={81} y={36} w={16} h={2.8} fill={C.grey3} />
      <RowBar x={81} y={42} w={12} h={2.8} fill={C.grey3} />
      <WarnTri cx={90} cy={52} w={10} fill={C.amber} />
    </>
  ),

  // Manage the plant and equipment register: owned and hired plant tracked with
  // its hours and utilization.
  'manage-the-plant-and-equipment-register': (a) => (
    <>
      <path d="M14 40 l4 -8 h12 l3 8 z" fill={C.ochre} stroke="none" />
      <rect x={14} y={40} width={30} height={9} rx={1.5} fill={a.deep} stroke="none" />
      <rect x={40} y={34} width={8} height={9} rx={1.5} fill={a.base} stroke="none" />
      <circle cx={22} cy={52} r={4} fill={C.ink} stroke="none" />
      <circle cx={38} cy={52} r={4} fill={C.ink} stroke="none" />
      <Sheet x={56} y={16} w={48} h={40} />
      <HeaderBand x={56} y={16} w={48} h={9} fill={a.base} />
      <RowBar x={62} y={30} w={20} h={3} fill={C.grey3} />
      <Chip x={86} y={28} w={12} h={6} fill={C.green} />
      <RowBar x={62} y={38} w={16} h={3} fill={C.grey3} />
      <Chip x={86} y={36} w={12} h={6} fill={C.amber} />
      <RowBar x={62} y={46} w={18} h={3} fill={C.grey3} />
      <Chip x={86} y={44} w={12} h={6} fill={C.green} />
      <path d="M62 64 a10 10 0 0 1 20 0" fill="none" stroke={C.grey3} strokeWidth={3} />
      <path d="M62 64 a10 10 0 0 1 14 -7" fill="none" stroke={a.base} strokeWidth={3} strokeLinecap="round" />
    </>
  ),

  // Prepare a method statement and risk assessment: the safe method with hazards
  // and controls, available on site.
  'prepare-a-method-statement-and-risk-assessment': (a) => (
    <>
      <Sheet x={20} y={14} w={44} h={56} />
      <HeaderBand x={20} y={14} w={44} h={10} fill={a.base} />
      <RowBar x={26} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={26} y={32} w={30} h={3} fill={C.grey3} />
      <RowBar x={26} y={40} w={26} h={3} fill={C.grey3} />
      <WarnTri cx={32} cy={54} w={12} fill={C.amber} />
      <Badge cx={48} cy={54} r={4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={54} y={52.5} w={6} h={3} fill={C.grey3} />
      <rect x={76} y={26} width={24} height={34} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <RowBar x={80} y={34} w={15} h={2.6} fill={C.grey3} />
      <RowBar x={80} y={40} w={12} h={2.6} fill={C.grey3} />
      <Badge cx={88} cy={52} r={4} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Report and action a near-miss: the near-miss logged, actioned and verified
  // on the walk.
  'report-and-action-a-near-miss': (a) => (
    <>
      <WarnTri cx={32} cy={36} w={30} fill={C.amber} />
      <path
        d="M52 44 H62 M58 40 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={64} y={18} w={40} h={48} />
      <HeaderBand x={64} y={18} w={40} h={9} fill={a.base} />
      <RowBar x={70} y={32} w={22} h={3} fill={C.grey3} />
      <RowBar x={70} y={40} w={18} h={3} fill={C.grey3} />
      <Badge cx={94} cy={56} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Run a toolbox talk and record attendance: the crew briefed and everyone
  // signed in.
  'run-a-toolbox-talk-and-record-attendance': (a) => (
    <>
      <circle cx={26} cy={26} r={5} fill={a.base} stroke="none" />
      <path d="M17 44 c0 -7 4 -11 9 -11 s9 4 9 11 z" fill={a.base} stroke="none" />
      <circle cx={44} cy={30} r={3.4} fill={a.light} stroke="none" />
      <circle cx={44} cy={42} r={3.4} fill={a.light} stroke="none" />
      <circle cx={44} cy={54} r={3.4} fill={a.light} stroke="none" />
      <Sheet x={58} y={16} w={46} h={54} />
      <HeaderBand x={58} y={16} w={46} h={9} fill={a.base} />
      <Signature x={64} y={32} w={20} color={a.base} />
      <Signature x={64} y={44} w={18} color={a.base} />
      <Signature x={64} y={56} w={22} color={a.base} />
    </>
  ),

  // Run the site day: the diary closed out with hours, photos and a safety
  // observation.
  'run-the-site-day': (a) => (
    <>
      <Sheet x={20} y={14} w={80} h={58} />
      <HeaderBand x={20} y={14} w={80} h={11} fill={a.base} />
      <RowBar x={26} y={18} w={24} h={3.4} fill={C.white} opacity={0.9} />
      <circle cx={90} cy={19.5} r={4} fill={C.amber} stroke="none" />
      <Chip x={26} y={32} w={16} h={8} fill={a.light} label="hrs" />
      <RowBar x={46} y={34} w={26} h={3} fill={C.grey3} />
      <rect x={26} y={44} width={22} height={16} rx={2} fill={a.light} stroke={C.white} strokeWidth={1.2} />
      <circle cx={31} cy={49} r={1.8} fill={C.white} stroke="none" />
      <path d="M28 60 l6 -5 l4 3 l4 -4 l4 6 z" fill={a.deep} stroke="none" />
      <WarnTri cx={62} cy={52} w={12} fill={C.amber} />
      <RowBar x={72} y={50} w={22} h={3} fill={C.grey3} />
      <Signature x={72} y={62} w={22} color={a.base} />
    </>
  ),

  // Track a design change through to the site record: the revised drawing and
  // instruction verified as built.
  'track-a-design-change-to-site-record': (a) => (
    <>
      <Sheet x={14} y={18} w={30} h={44} fill={C.panel} />
      <path d="M20 30 H38 M20 40 H34" stroke={C.grey2} strokeWidth={1.4} fill="none" />
      <Chip x={18} y={50} w={22} h={8} fill={a.base} label="Rev B" />
      <path
        d="M46 40 H54 M50 36 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={56} y={22} w={26} h={38} />
      <HeaderBand x={56} y={22} w={26} h={8} fill={C.ochre} />
      <RowBar x={61} y={34} w={14} h={2.8} fill={C.grey3} />
      <RowBar x={61} y={40} w={11} h={2.8} fill={C.grey3} />
      <path d="M84 40 H92" stroke={a.base} strokeWidth={2} fill="none" />
      <Badge cx={96} cy={40} r={8} fill={C.green} glyph="check" />
    </>
  ),
};

interface CaseSceneProps {
  /** Case id; selects the bespoke scene from {@link CASE_SCENES}. */
  id: string;
  /** Category accent ramp the scene paints its hero shapes in. Defaults to the
   *  neutral blue ramp so a scene rendered without a category still reads. */
  accent?: Accent;
  /** Extra classes for the svg (sizing). */
  className?: string;
  /** Accessible label; the scene is decorative when omitted. */
  title?: string;
}

/**
 * Renders the bespoke line-art scene for a case in the exact StepScene frame
 * (same viewBox, blueprint grid and slate linework), sized to fill its tile.
 * Returns `null` when the case has no bespoke scene, so callers can fall back.
 */
export function CaseScene({
  id,
  accent = NEUTRAL_ACCENT,
  className,
  title,
}: CaseSceneProps): ReactElement | null {
  const scene = CASE_SCENES[id];
  if (!scene) return null;
  return (
    <svg
      viewBox={VB}
      className={clsx('h-full w-full p-3 text-slate-400', className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? 'img' : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
    >
      <Grid />
      {scene(accent)}
    </svg>
  );
}
