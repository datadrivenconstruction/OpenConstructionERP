// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - bespoke line-art scenes, wave 4.
//
// Eighteen more cases that were still falling back to a single generic glyph,
// drawn in the same language as `caseScenes.tsx`: the shared `0 0 120 84`
// viewBox, the blueprint grid painted by the caller, the fixed `C` palette for
// everything except the one element that carries the case's meaning, and the
// primitive kit from `stepSceneParts`.
//
// This wave leans on registers, measurement and money, three families that
// collapse into the same picture if you are not careful, so each scene is built
// around a different concrete object: a limitation clock, a tabbed register, an
// interface node, a coin stack, a strongbox, falsework under load, an indented
// bill, a scanned point cloud, a coded tag, a hoarded site, a camera over an
// open trench, a treasury, a programme extension, three provincial tax caps, a
// site cabin on the programme, a banded cost column, an early-notice flag and a
// clipped subcontract order.
//
// Keyed by case id; the registry wires this record in alongside CASE_SCENES.

import { type ReactElement } from 'react';
import {
  C,
  Badge,
  Bar,
  Chip,
  Cube,
  Cylinder,
  HeaderBand,
  RowBar,
  Sheet,
  Signature,
  Stamp,
  WarnTri,
} from './stepSceneParts';
import { type Accent } from './categories';

/** A scene takes its category accent ramp and returns its artwork group. */
type Scene = (a: Accent) => ReactElement;

export const CASE_SCENES_WAVE4: Record<string, Scene> = {
  // DE handover - the defects walked off the building, the acceptance protocol
  // signed, and the limitation clock that the protocol starts running.
  'maengel-abnahme-and-verjaehrung': (a) => (
    <>
      <rect x={16} y={26} width={30} height={42} rx={2} fill={C.panel} stroke={C.grey1} strokeWidth={1.6} />
      <path
        d="M22 34 h7 v7 h-7 z M34 34 h7 v7 h-7 z M22 46 h7 v7 h-7 z M34 46 h7 v7 h-7 z"
        fill={C.grey3}
        stroke="none"
      />
      <circle cx={44} cy={38} r={2.8} fill={C.red} stroke={C.white} strokeWidth={1} />
      <circle cx={19} cy={58} r={2.8} fill={C.red} stroke={C.white} strokeWidth={1} />
      <Sheet x={52} y={20} w={30} h={42} />
      <HeaderBand x={52} y={20} w={30} h={9} fill={a.base} />
      <RowBar x={57} y={34} w={20} h={3.2} fill={C.grey3} />
      <Signature x={57} y={50} w={20} color={a.base} />
      <circle cx={96} cy={44} r={11} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M96 44 V33 A11 11 0 0 1 105.5 49.5 Z" fill={a.light} stroke="none" />
      <circle cx={96} cy={44} r={11} fill="none" stroke={a.base} strokeWidth={2.2} />
      <path d="M96 44 V36 M96 44 l5.5 3" stroke={a.deep} strokeWidth={2} fill="none" strokeLinecap="round" />
    </>
  ),

  // The statutory registers kept current behind coloured tabs, one incident
  // logged inside them, and the indicator trend they are read against.
  'manage-hse-performance-and-statutory-registers': (a) => (
    <>
      <Sheet x={14} y={16} w={34} h={48} />
      <HeaderBand x={14} y={16} w={34} h={9} fill={a.base} />
      <rect x={44} y={28} width={9} height={7} rx={1.5} fill={C.green} stroke="none" />
      <rect x={44} y={39} width={9} height={7} rx={1.5} fill={C.amber} stroke="none" />
      <rect x={44} y={50} width={9} height={7} rx={1.5} fill={a.light} stroke="none" />
      <WarnTri cx={24} cy={38} w={13} fill={C.amber} />
      <RowBar x={33} y={36.5} w={9} h={3} fill={C.grey3} />
      <RowBar x={20} y={52} w={20} h={3} fill={C.grey3} />
      <path d="M62 24 V66 H106" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M67 34 L77 41 L87 48 L100 58"
        stroke={a.base}
        strokeWidth={2.6}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={100} cy={58} r={3.6} fill={a.base} stroke={C.white} strokeWidth={1} />
    </>
  ),

  // Two work packages that meet at a boundary: an owner on each side, the
  // information exchanged across it, one node closed when both sides agree.
  'manage-interfaces-between-work-packages': (a) => (
    <>
      <rect x={14} y={26} width={30} height={32} rx={3} fill={a.light} stroke={C.white} strokeWidth={1.4} />
      <rect x={76} y={26} width={30} height={32} rx={3} fill={C.grey2} stroke={C.white} strokeWidth={1.4} />
      <circle cx={20} cy={26} r={5} fill={a.deep} stroke={C.white} strokeWidth={1.4} />
      <circle cx={100} cy={26} r={5} fill={C.grey1} stroke={C.white} strokeWidth={1.4} />
      <path d="M60 16 V68" stroke={C.grey1} strokeWidth={1.6} strokeDasharray="4 3" fill="none" />
      <path
        d="M48 22 H72 M52 18 l-4 4 l4 4 M68 18 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M44 42 H52 M68 42 H76" stroke={C.grey1} strokeWidth={2} fill="none" strokeLinecap="round" />
      <path d="M60 32 L68 37 V47 L60 52 L52 47 V37 Z" fill={a.base} stroke={C.white} strokeWidth={1.2} />
      <Badge cx={60} cy={64} r={6} fill={C.green} glyph="check" />
    </>
  ),

  // The bill split in two: measured work above the line, and below it the sums
  // the design cannot fix yet, held open against a pot of money to draw down.
  'manage-provisional-sums-and-allowances': (a) => (
    <>
      <Sheet x={16} y={14} w={48} h={56} />
      <HeaderBand x={16} y={14} w={48} h={10} fill={a.base} />
      <RowBar x={22} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={22} y={30} w={32} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={37} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={44} w={30} h={3.2} fill={C.grey3} />
      <path d="M22 51 H58" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <rect
        x={22}
        y={54}
        width={28}
        height={5.5}
        rx={2.75}
        fill="none"
        stroke={a.base}
        strokeWidth={1.4}
        strokeDasharray="3 2.5"
      />
      <rect
        x={22}
        y={62}
        width={22}
        height={5.5}
        rx={2.75}
        fill="none"
        stroke={a.base}
        strokeWidth={1.4}
        strokeDasharray="3 2.5"
      />
      <path
        d="M66 50 H74 M70 46 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Cylinder cx={88} top={38} rx={12} ry={4.5} h={20} fill={C.ochre} topFill={C.amber} />
    </>
  ),

  // A slice held back off every subcontractor payment, locked away as one
  // balance, and let out again at the milestone that releases it.
  'manage-retention-across-the-supply-chain': (a) => (
    <>
      <rect x={14} y={20} width={34} height={8} rx={2} fill={C.grey3} stroke="none" />
      <rect x={48} y={20} width={9} height={8} rx={2} fill={a.base} stroke="none" />
      <rect x={14} y={32} width={28} height={8} rx={2} fill={C.grey3} stroke="none" />
      <rect x={42} y={32} width={9} height={8} rx={2} fill={a.base} stroke="none" />
      <rect x={14} y={44} width={32} height={8} rx={2} fill={C.grey3} stroke="none" />
      <rect x={46} y={44} width={9} height={8} rx={2} fill={a.base} stroke="none" />
      <path
        d="M60 36 H70 M66 32 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={72} y={20} width={32} height={28} rx={3} fill={a.deep} stroke={C.white} strokeWidth={1.4} />
      <circle cx={88} cy={34} r={6} fill="none" stroke={C.white} strokeWidth={2.2} />
      <path
        d="M88 25 V29 M88 39 V43 M79 34 H83 M93 34 H97"
        stroke={C.white}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <path d="M88 50 V58" stroke={C.green} strokeWidth={2.4} fill="none" strokeLinecap="round" />
      <path d="M88 58 l6 6 l-6 6 l-6 -6 z" fill={C.green} stroke={C.white} strokeWidth={1.2} />
    </>
  ),

  // Falsework carrying a real load: props and braces registered, the design
  // check stamped, and the periodic inspections ticked off until it is struck.
  'manage-temporary-works-and-inspections': (a) => (
    <>
      <path
        d="M28 13 V25 M24 21 l4 4 l4 -4 M45 13 V25 M41 21 l4 4 l4 -4 M62 13 V25 M58 21 l4 4 l4 -4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={18} y={28} width={54} height={7} rx={1.5} fill={C.grey2} stroke="none" />
      <path d="M26 35 V62 M64 35 V62" stroke={C.ochre} strokeWidth={3.4} fill="none" strokeLinecap="round" />
      <path
        d="M26 35 L64 62 M64 35 L26 62"
        stroke={C.ochre}
        strokeWidth={2}
        opacity={0.85}
        fill="none"
        strokeLinecap="round"
      />
      <path d="M14 64 H76" stroke={C.grey1} strokeWidth={1.8} fill="none" strokeLinecap="round" />
      <Stamp cx={84} cy={20} r={8} color={a.base} />
      <path d="M96 30 V66" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="3 3" fill="none" />
      <Badge cx={96} cy={36} r={5} fill={C.green} glyph="check" shadow={false} />
      <Badge cx={96} cy={48} r={5} fill={C.green} glyph="check" shadow={false} />
      <Badge cx={96} cy={60} r={5} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // GB - the rules give the bill its shape: sections over items over sub-items,
  // each level indented, the quantities rolling up into one measured total.
  'measure-a-bill-of-quantities-to-nrm2': (a) => (
    <>
      <Sheet x={20} y={12} w={64} h={58} />
      <HeaderBand x={20} y={12} w={64} h={10} fill={a.base} />
      <RowBar x={26} y={16} w={26} h={3.4} fill={C.white} opacity={0.9} />
      <RowBar x={26} y={28} w={30} h={4} fill={a.deep} />
      <path
        d="M28 33 V44.6 M28 37.6 H32 M28 44.6 H32 M34 46 V58.5 M34 51.5 H38 M34 58.5 H38"
        stroke={C.grey1}
        strokeWidth={1.2}
        fill="none"
      />
      <RowBar x={32} y={36} w={26} h={3.2} fill={C.grey2} />
      <RowBar x={32} y={43} w={22} h={3.2} fill={C.grey2} />
      <RowBar x={38} y={50} w={20} h={3} fill={C.grey3} />
      <RowBar x={38} y={57} w={17} h={3} fill={C.grey3} />
      <Chip x={62} y={49} w={14} h={6} fill={C.green} />
      <Chip x={62} y={56} w={14} h={6} fill={C.green} />
      <path d="M88 28 h5 V60 h-5" stroke={a.base} strokeWidth={2} fill="none" strokeLinecap="round" />
      <RowBar x={95} y={41} w={9} h={5} fill={a.base} />
    </>
  ),

  // The existing conditions arrive as scanned points, not as lines: a scanner
  // sweeping the space and a solid quantity lifted straight out of the cloud.
  'measure-from-a-point-cloud-survey': (a) => (
    <>
      <path d="M18 66 L26 48 L34 66" stroke={C.ink} strokeWidth={2.2} fill="none" strokeLinecap="round" />
      <rect x={21} y={38} width={10} height={10} rx={1.5} fill={a.deep} stroke="none" />
      <circle cx={26} cy={43} r={2.6} fill={a.light} stroke={C.white} strokeWidth={1} />
      <path
        d="M32 42 L48 24 M32 43 L48 42 M32 44 L48 58"
        stroke={a.light}
        strokeWidth={1.4}
        opacity={0.8}
        fill="none"
      />
      <path
        d="M48 20 H94 V60 H64 V44 H48 Z"
        fill="none"
        stroke={C.blueDeep}
        strokeWidth={3}
        strokeDasharray="0.1 3.4"
        strokeLinecap="round"
      />
      <path
        d="M53 25 H89 V55 H68 V40 H53 Z"
        fill="none"
        stroke={C.blueDeep}
        strokeWidth={2.4}
        strokeDasharray="0.1 3.6"
        strokeLinecap="round"
        opacity={0.55}
      />
      <Cube cx={78} ty={28} w={11} hh={5.5} depth={14} top={a.light} left={a.base} right={a.deep} />
      <path d="M48 66 H94 M48 63 V69 M94 63 V69" stroke={C.ochre} strokeWidth={1.6} fill="none" />
    </>
  ),

  // CN - the measured section leaves the drawing and lands on a coded bill item:
  // the code blocks are the point, the characteristics follow underneath.
  'measure-the-drawing-into-a-coded-bill-item': (a) => (
    <>
      <Sheet x={14} y={16} w={32} h={40} fill={C.panel} />
      <rect
        x={20}
        y={24}
        width={20}
        height={18}
        fill={a.light}
        fillOpacity={0.3}
        stroke={a.base}
        strokeWidth={1.4}
      />
      <path
        d="M22 40 L36 26 M28 42 L40 30 M20 32 L28 24"
        stroke={a.base}
        strokeWidth={1}
        opacity={0.6}
        fill="none"
      />
      <path
        d="M48 34 H54 M50 30 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M58 34 L66 22 H98 A4 4 0 0 1 102 26 V42 A4 4 0 0 1 98 46 H66 Z"
        fill={C.white}
        stroke={a.base}
        strokeWidth={1.8}
        strokeLinejoin="round"
      />
      <circle cx={65} cy={34} r={2.2} fill="none" stroke={a.base} strokeWidth={1.4} />
      <path d="M70 30 h5 v8 h-5 z M76 30 h5 v8 h-5 z M82 30 h5 v8 h-5 z" fill={a.base} stroke="none" />
      <path d="M88 30 h5 v8 h-5 z M94 30 h5 v8 h-5 z" fill={C.ochre} stroke="none" />
      <RowBar x={62} y={54} w={28} h={3.2} fill={C.grey3} />
      <RowBar x={62} y={61} w={22} h={3.2} fill={C.grey3} />
    </>
  ),

  // The site before the work: hoarding round the plot with one gate to control,
  // the crane up, the cabins in and the laydown marked out.
  'mobilise-the-site-and-set-up-logistics': (a) => (
    <>
      <path
        d="M16 50 V22 H92 V68 H16 V58"
        stroke={C.ochre}
        strokeWidth={2.6}
        fill="none"
        strokeLinejoin="round"
      />
      <path d="M16 58 L26 64" stroke={a.base} strokeWidth={3} fill="none" strokeLinecap="round" />
      <path
        d="M12 54 H26 M22 50 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M56 64 V26" stroke={a.deep} strokeWidth={3} fill="none" strokeLinecap="round" />
      <path d="M40 26 H80" stroke={a.deep} strokeWidth={2.6} fill="none" strokeLinecap="round" />
      <path d="M72 26 V38 M69 38 H75" stroke={C.grey1} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <rect x={22} y={32} width={18} height={12} rx={1.5} fill={C.grey3} stroke={C.white} strokeWidth={1.2} />
      <rect
        x={64}
        y={48}
        width={26}
        height={16}
        rx={1.5}
        fill={a.light}
        fillOpacity={0.3}
        stroke={a.base}
        strokeWidth={1.4}
        strokeDasharray="3 2"
      />
      <Cube cx={76} ty={42} w={8} hh={4} depth={10} top={a.light} left={a.base} right={a.deep} />
    </>
  ),

  // DE - the changed condition photographed while the trench is still open, and
  // the Nachtrag flagged before the work is covered up and only argued about.
  'nachtrag-with-evidence-not-argument': (a) => (
    <>
      <path
        d="M14 44 H40 L46 62 H60 L66 44 H80"
        stroke={C.ink}
        strokeWidth={2.4}
        fill="none"
        strokeLinejoin="round"
      />
      <circle cx={53} cy={55} r={5.5} fill={C.ochre} stroke={C.white} strokeWidth={1.2} />
      <path d="M36 44 V26" stroke={a.deep} strokeWidth={2.4} fill="none" strokeLinecap="round" />
      <path d="M36 26 H50 L46 31 L50 36 H36 Z" fill={a.base} stroke="none" />
      <rect x={66} y={14} width={28} height={18} rx={3} fill={a.deep} stroke="none" />
      <path d="M72 14 h9 v-3.5 h-9 z" fill={a.deep} stroke="none" />
      <circle cx={80} cy={23} r={6} fill={a.light} stroke={C.white} strokeWidth={1.4} />
      <path d="M72 34 L58 48" stroke={a.base} strokeWidth={1.4} strokeDasharray="3 2.5" fill="none" />
      <rect x={82} y={40} width={24} height={20} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <path d="M85 58 l6 -7 l4 4 l4 -5 l5 8 z" fill={a.light} stroke="none" />
    </>
  ),

  // US - the certificate dates come to you off a calendar, the deduction is
  // taken off the right base, and only that slice goes to the revenue office.
  'pay-a-sub-without-inheriting-their-tax-bill': (a) => (
    <>
      <path d="M22 10 V16 M36 10 V16" stroke={C.ink} strokeWidth={2.2} fill="none" strokeLinecap="round" />
      <rect x={16} y={14} width={28} height={24} rx={2.5} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <HeaderBand x={16} y={14} w={28} h={7} fill={C.ochre} />
      <RowBar x={21} y={26} w={16} h={2.6} fill={C.grey3} />
      <circle cx={36} cy={31} r={3.4} fill={C.red} stroke={C.white} strokeWidth={1} />
      <rect x={14} y={46} width={38} height={10} rx={2} fill={C.green} stroke="none" />
      <rect x={54} y={46} width={14} height={10} rx={2} fill={a.base} stroke="none" />
      <path
        d="M70 51 H78 M74 47 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M78 30 L92 20 L106 30 Z" fill={a.deep} stroke="none" strokeLinejoin="round" />
      <path
        d="M83 32 V46 M89 32 V46 M95 32 V46 M101 32 V46"
        stroke={a.base}
        strokeWidth={3.2}
        fill="none"
      />
      <rect x={78} y={46} width={28} height={6} rx={1.5} fill={a.deep} stroke="none" />
    </>
  ),

  // GB - a variation moves two things at once: the programme runs on past the
  // old completion date, and the contract sum grows by the priced amount.
  'price-a-variation-and-agree-the-extension-of-time': (a) => (
    <>
      <rect x={16} y={20} width={30} height={6} rx={2} fill={C.grey2} stroke="none" />
      <rect x={24} y={30} width={32} height={6} rx={2} fill={C.grey2} stroke="none" />
      <rect x={34} y={40} width={26} height={6} rx={2} fill={a.base} stroke="none" />
      <rect
        x={60}
        y={40}
        width={18}
        height={6}
        rx={2}
        fill={a.light}
        stroke={a.base}
        strokeWidth={1.4}
        strokeDasharray="3 2.4"
      />
      <path d="M14 54 H106" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M74 49 l5 5 l-5 5 l-5 -5 z" fill="none" stroke={C.grey1} strokeWidth={1.8} strokeLinejoin="round" />
      <path
        d="M84 54 H92 M88.5 50.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.green}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M98 49 l5 5 l-5 5 l-5 -5 z" fill={C.green} stroke={C.white} strokeWidth={1.2} />
      <rect x={16} y={64} width={52} height={8} rx={2} fill={C.grey3} stroke="none" />
      <rect x={70} y={64} width={14} height={8} rx={2} fill={C.ochre} stroke="none" />
    </>
  ),

  // CA - one priced bill read out under three provincial tax regimes: the work
  // underneath is identical, only the cap on top of each column changes.
  'price-one-bill-for-hst-pst-and-qst': (a) => (
    <>
      <Sheet x={14} y={26} w={26} h={32} />
      <HeaderBand x={14} y={26} w={26} h={8} fill={a.base} />
      <RowBar x={19} y={42} w={16} h={3.4} fill={C.grey3} />
      <path
        d="M46 42 H54 M50 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M60 70 H106" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={64} baseY={70} w={11} h={24} fill={C.grey2} />
      <Bar x={78} baseY={70} w={11} h={24} fill={C.grey2} />
      <Bar x={92} baseY={70} w={11} h={24} fill={C.grey2} />
      <Bar x={64} baseY={46} w={11} h={8} fill={a.base} />
      <Bar x={78} baseY={46} w={11} h={5} fill={C.ochre} />
      <Bar x={92} baseY={46} w={11} h={12} fill={a.deep} />
    </>
  ),

  // The cost of running the job itself: cabin, scaffold and site staff, priced
  // as one bar that runs the length of the programme plus fixed lumps each end.
  'price-the-preliminaries-and-general-conditions': (a) => (
    <>
      <rect x={16} y={24} width={34} height={20} rx={2} fill={a.base} stroke={C.white} strokeWidth={1.2} />
      <path
        d="M23 26 V42 M30 26 V42 M37 26 V42 M44 26 V42"
        stroke={C.white}
        strokeWidth={1}
        opacity={0.45}
        fill="none"
      />
      <rect x={30} y={32} width={8} height={12} rx={1} fill={C.white} stroke="none" />
      <path
        d="M56 44 V24 M68 44 V24 M56 34 H68 M56 24 H68 M56 44 H68 M56 24 L68 34"
        stroke={C.ochre}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={84} cy={26} r={5} fill={a.deep} stroke="none" />
      <path d="M74 44 c0 -8 4.5 -13 10 -13 s10 5 10 13 z" fill={a.deep} stroke="none" />
      <rect x={14} y={52} width={8} height={9} rx={2} fill={C.ochre} stroke="none" />
      <rect
        x={24}
        y={52}
        width={70}
        height={9}
        rx={2}
        fill={a.light}
        stroke={a.base}
        strokeWidth={1.4}
      />
      <rect x={96} y={52} width={9} height={9} rx={2} fill={C.ochre} stroke="none" />
      <path d="M14 68 H106" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M24 64 V70 M42 64 V70 M60 64 V70 M78 64 V70 M96 64 V70"
        stroke={C.grey1}
        strokeWidth={1.2}
        fill="none"
      />
    </>
  ),

  // GB - the building sized before it is priced, and the order of cost carried
  // as three bands: the works, the risk allowances, the move to the spend date.
  'produce-an-nrm1-order-of-cost-estimate': (a) => (
    <>
      <rect x={16} y={28} width={32} height={30} rx={1.5} fill={C.grey3} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M16 38 H48 M16 48 H48" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M16 64 H48 M16 61 V67 M48 61 V67" stroke={C.ochre} strokeWidth={1.6} fill="none" />
      <path
        d="M54 44 H62 M58 40 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M64 68 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={68} baseY={68} w={20} h={26} fill={a.base} />
      <Bar x={68} baseY={42} w={20} h={10} fill={C.amber} />
      <Bar x={68} baseY={32} w={20} h={8} fill={C.ochre} />
      <path d="M92 24 h5 V68 h-5" stroke={a.base} strokeWidth={2} fill="none" strokeLinecap="round" />
    </>
  ),

  // US - the notice flag goes in early, well before the deadline, and the
  // change is carried by a folder of records rather than by argument.
  'raise-a-change-order-with-proof': (a) => (
    <>
      <path d="M14 62 H52" stroke={C.grey1} strokeWidth={1.8} fill="none" strokeLinecap="round" />
      <path d="M22 62 V36" stroke={a.deep} strokeWidth={2.4} fill="none" strokeLinecap="round" />
      <path d="M22 36 H40 L35 42 L40 48 H22 Z" fill={a.base} stroke="none" />
      <path d="M46 56 V68" stroke={C.red} strokeWidth={2.4} fill="none" strokeLinecap="round" />
      <rect x={62} y={15} width={14} height={9} rx={1} fill={C.white} stroke={C.grey1} strokeWidth={1.2} />
      <rect x={78} y={17} width={14} height={8} rx={1} fill={C.white} stroke={C.grey1} strokeWidth={1.2} />
      <path
        d="M56 20 h12 l3.5 4.5 h22 a3 3 0 0 1 3 3 v18 a3 3 0 0 1 -3 3 H56 a3 3 0 0 1 -3 -3 V23 a3 3 0 0 1 3 -3 z"
        fill={C.ochre}
        stroke="none"
      />
      <RowBar x={56} y={58} w={18} h={5.5} fill={a.deep} />
      <Stamp cx={86} cy={60} r={8} color={C.green} />
    </>
  ),

  // The winning bid becomes a live order: the award marked, the programme and
  // the payment terms clipped to it, and the whole thing sent to be signed.
  'raise-a-subcontract-order-from-the-award': (a) => (
    <>
      <circle cx={20} cy={26} r={7} fill={C.ochre} stroke={C.white} strokeWidth={1.4} />
      <path d="M15 31 l-2.5 11 l7.5 -4 l7.5 4 l-2.5 -11 z" fill={C.ochre} stroke="none" strokeLinejoin="round" />
      <Sheet x={32} y={14} w={40} h={54} />
      <HeaderBand x={32} y={14} w={40} h={10} fill={a.base} />
      <RowBar x={38} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={38} y={34} w={26} h={3.2} fill={C.grey3} />
      <Signature x={38} y={58} w={24} color={a.base} />
      <path
        d="M58 10 v13 a4 4 0 0 0 8 0 V12.5 a2.3 2.3 0 0 0 -4.6 0 v11.5"
        stroke={C.grey1}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <rect x={78} y={20} width={26} height={20} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path
        d="M82 26 h10 M85 31 h12 M89 36 h9"
        stroke={a.light}
        strokeWidth={2.6}
        fill="none"
        strokeLinecap="round"
      />
      <rect x={78} y={46} width={26} height={20} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path
        d="M82 52 h18 M82 57 h14 M82 62 h16"
        stroke={C.grey2}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),
};
