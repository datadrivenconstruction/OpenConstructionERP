// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - bespoke line-art scenes, wave 5.
//
// Seventeen more cases that had no drawn picture: completion and the final
// account, a FIEBDC-3 import, deliveries at the gate, a drawing issue against
// its index, a supplier statement, a CCDC-family change, adjudication, source
// data blocking the programme, warranties at handover, provisional sums, AI
// takeoff review, a clash profile, a concrete pour, a supervision visit, soft
// landings, an authority review cycle and a statutory interim payment.
//
// Same language as `caseScenes.tsx`: the shared `0 0 120 84` viewBox, the fixed
// `C` palette for the furniture, the category accent for the one element that
// carries the case, and no letterforms anywhere - these ship in every locale.

import { type ReactElement } from 'react';
import {
  C,
  Badge,
  Bar,
  Chip,
  Cube,
  HeaderBand,
  RowBar,
  Sheet,
  Shield,
  Stamp,
  Star,
  WarnTri,
} from './stepSceneParts';
import { type Accent } from './categories';

/** A scene takes its category accent ramp and returns its artwork group. */
type Scene = (a: Accent) => ReactElement;

/** A map pin, for an observation logged at a place on a plan. */
function Pin({ cx, cy, fill }: { cx: number; cy: number; fill: string }): ReactElement {
  return (
    <>
      <path
        d={`M${cx} ${cy} c-4.2 -5.6 -6 -8.2 -6 -10.8 a6 6 0 1 1 12 0 c0 2.6 -1.8 5.2 -6 10.8 z`}
        fill={fill}
        stroke={C.white}
        strokeWidth={1}
      />
      <circle cx={cx} cy={cy - 11} r={2.2} fill={C.white} stroke="none" />
    </>
  );
}

/** One drawing sheet in the issued set, drawn as a tile in the field. */
function Tile({ x, y }: { x: number; y: number }): ReactElement {
  return (
    <>
      <rect x={x} y={y} width={20} height={18} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <RowBar x={x + 4} y={y + 11} w={12} h={3} fill={C.grey3} />
    </>
  );
}

/**
 * Wave 5 case illustrations, keyed by case id. Merged into the registry beside
 * `CASE_SCENES`, so every key here must be a case id that exists.
 */
export const CASE_SCENES_WAVE5: Record<string, Scene> = {
  // Reach practical completion and settle the final account: the certificate is
  // stamped, the retention held drains away and the account is struck.
  'reach-practical-completion-and-settle-the-final-account': (a) => (
    <>
      <Sheet x={16} y={14} w={44} h={50} />
      <HeaderBand x={16} y={14} w={44} h={10} fill={a.base} />
      <RowBar x={22} y={18} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={22} y={30} w={28} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={38} w={24} h={3.2} fill={C.grey3} />
      <path d="M22 48 H50" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={22} y={52} w={20} h={4} fill={a.deep} />
      <Stamp cx={54} cy={58} r={7} color={C.green} />
      <rect x={78} y={18} width={14} height={44} rx={4} fill={C.panel} stroke={C.grey1} strokeWidth={1.4} />
      <rect x={80.5} y={50} width={9} height={10} rx={2} fill={C.ochre} stroke="none" />
      <path
        d="M85 26 V40 M80 35 l5 5 l5 -5"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={100} cy={64} r={6.5} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Read a FIEBDC-3 presupuesto: the exchange file opens into chapters and items,
  // but the breakdown under the item comes through half empty.
  'read-a-fiebdc3-presupuesto': (a) => (
    <>
      <Sheet x={12} y={22} w={26} h={34} />
      <path d="M31 22 L38 29 H31 Z" fill={C.grey3} stroke="none" />
      <RowBar x={17} y={36} w={14} h={2.8} fill={C.grey3} />
      <RowBar x={17} y={43} w={11} h={2.8} fill={C.grey3} />
      <path
        d="M42 40 H54 M50 36 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <RowBar x={60} y={16} w={26} h={5} fill={a.base} />
      <path d="M64 21 V42 M64 30 H70 M64 42 H70" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <RowBar x={70} y={27.8} w={22} h={4.4} fill={C.grey2} />
      <RowBar x={70} y={39.8} w={18} h={4.4} fill={C.grey2} />
      <path d="M74 44 V52" stroke={C.grey1} strokeWidth={1.2} strokeDasharray="2 2" fill="none" />
      <rect x={68} y={52} width={9} height={9} rx={1.5} fill={C.ochre} stroke="none" />
      <rect x={80} y={52} width={9} height={9} rx={1.5} fill={a.light} stroke="none" />
      <rect
        x={92}
        y={52}
        width={9}
        height={9}
        rx={1.5}
        fill="none"
        stroke={C.grey1}
        strokeWidth={1.4}
        strokeDasharray="2.5 2"
      />
    </>
  ),

  // Receive and reconcile material deliveries: the load arrives at the gate, the
  // crates come off and one line on the ticket does not match the order.
  'receive-and-reconcile-material-deliveries': (a) => (
    <>
      <rect x={14} y={40} width={26} height={15} rx={2} fill={a.base} stroke="none" />
      <path d="M40 46 h9 l6 6 v3 h-15 z" fill={a.deep} stroke="none" />
      <circle cx={22} cy={57} r={3.4} fill={C.ink} stroke="none" />
      <circle cx={48} cy={57} r={3.4} fill={C.ink} stroke="none" />
      <path d="M12 61 H60" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <Cube cx={72} ty={42} w={8} hh={4} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={90} ty={46} w={7} hh={3.5} depth={9} top={C.grey3} left={C.grey2} right={C.grey1} />
      <Sheet x={70} y={10} w={34} h={26} />
      <RowBar x={75} y={15} w={18} h={3} fill={C.grey3} />
      <Badge cx={78} cy={22} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={84} y={20.5} w={15} h={3} fill={C.grey3} />
      <WarnTri cx={78} cy={31} w={9} fill={C.amber} shadow={false} />
      <RowBar x={84} y={29.5} w={11} h={3} fill={C.grey3} />
    </>
  ),

  // Reconcile a drawing issue against the index: the index rail expects a field
  // of sheets - one slot never arrived, one sheet is at an unexpected revision
  // and one turned up outside the index entirely.
  'reconcile-a-drawing-issue-against-the-index': (a) => (
    <>
      <rect x={12} y={10} width={68} height={6} rx={3} fill={a.base} stroke="none" />
      <path d="M22 16 V22 M46 16 V22 M70 16 V22" stroke={a.base} strokeWidth={1.6} fill="none" />
      <Tile x={12} y={24} />
      <Tile x={36} y={24} />
      <Tile x={60} y={24} />
      <path d="M74 24 L80 24 L80 30 Z" fill={C.ochre} stroke="none" />
      <Tile x={12} y={48} />
      <rect
        x={36}
        y={48}
        width={20}
        height={18}
        rx={2}
        fill="none"
        stroke={C.red}
        strokeWidth={1.6}
        strokeDasharray="3 2"
      />
      <Tile x={60} y={48} />
      <rect
        x={86}
        y={44}
        width={17}
        height={16}
        rx={2}
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.4}
        transform="rotate(-6 94.5 52)"
      />
      <WarnTri cx={95} cy={30} w={13} fill={C.amber} />
    </>
  ),

  // Reconcile a supplier statement: your ledger against theirs, line by line -
  // two tie, one does not, and the balance both sides sign off sits underneath.
  'reconcile-a-supplier-statement': (a) => (
    <>
      <Sheet x={12} y={14} w={36} h={44} />
      <HeaderBand x={12} y={14} w={36} h={9} fill={a.base} />
      <RowBar x={17} y={17} w={16} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={28} y={29} w={15} h={3.4} fill={C.grey3} />
      <RowBar x={31} y={38} w={12} h={3.4} fill={C.grey3} />
      <RowBar x={26} y={47} w={17} h={3.4} fill={C.grey3} />
      <Sheet x={68} y={14} w={36} h={44} />
      <HeaderBand x={68} y={14} w={36} h={9} fill={C.grey2} />
      <RowBar x={73} y={17} w={16} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={73} y={29} w={15} h={3.4} fill={C.grey3} />
      <RowBar x={73} y={38} w={12} h={3.4} fill={C.grey3} />
      <RowBar x={73} y={47} w={13} h={3.4} fill={C.grey3} />
      <path
        d="M53 29.5 h10 M53 33 h10 M53 38.5 h10 M53 42 h10"
        stroke={C.green}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M53 47.5 h10 M53 51 h10 M55 53.5 l6 -8.5"
        stroke={C.red}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
      <Chip x={40} y={63} w={36} h={9} r={3} fill={a.deep} />
      <Badge cx={86} cy={67.5} r={6} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Record a change under a CCDC-family contract: the change is raised against
  // the clause it lives under, valued by one of the routes the contract names,
  // and only then does the contract price move.
  'record-a-change-under-a-ccdc-family-contract': (a) => (
    <>
      <Sheet x={14} y={12} w={42} h={54} />
      <HeaderBand x={14} y={12} w={42} h={9} fill={C.grey2} />
      <RowBar x={20} y={15} w={18} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={20} y={26} w={28} h={3.2} fill={C.grey3} />
      <rect x={18} y={34} width={34} height={10} rx={2} fill={C.highlight} stroke="none" />
      <rect x={18} y={34} width={2.6} height={10} rx={1.3} fill={a.base} stroke="none" />
      <RowBar x={25} y={37.4} w={23} h={3.2} fill={a.deep} />
      <RowBar x={20} y={50} w={26} h={3.2} fill={C.grey3} />
      <path
        d="M56 39 C61 39 61 35 66 35"
        stroke={C.grey1}
        strokeWidth={1.4}
        strokeDasharray="1 3"
        fill="none"
      />
      <Chip x={66} y={16} w={26} h={10} r={3} fill={C.grey3} />
      <Chip x={66} y={30} w={26} h={10} r={3} fill={a.base} />
      <Chip x={66} y={44} w={26} h={10} r={3} fill={C.grey3} />
      <Badge cx={98} cy={35} r={5} fill={C.green} glyph="check" shadow={false} />
      <path d="M66 70 H102" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={70} baseY={70} w={10} h={8} fill={C.grey2} />
      <Bar x={88} baseY={70} w={10} h={14} fill={a.deep} />
    </>
  ),

  // Refer a payment dispute to adjudication: two irreconcilable valuations, one
  // pack of contemporaneous records behind the referral, and a decision.
  'refer-a-payment-dispute-to-adjudication': (a) => (
    <>
      <Sheet x={12} y={14} w={30} h={22} />
      <RowBar x={17} y={20} w={14} h={3} fill={C.grey3} />
      <RowBar x={17} y={27} w={18} h={4} fill={a.deep} />
      <Sheet x={12} y={42} w={30} h={22} />
      <RowBar x={17} y={48} w={14} h={3} fill={C.grey3} />
      <RowBar x={17} y={55} w={9} h={4} fill={C.red} />
      <path
        d="M46 36 h8 M46 39.5 h8 M47.5 42 l5 -8.5"
        stroke={C.red}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
      <Sheet x={54} y={30} w={24} h={30} fill={C.panel} />
      <Sheet x={58} y={34} w={24} h={30} />
      <HeaderBand x={58} y={34} w={24} h={8} fill={a.base} />
      <RowBar x={63} y={47} w={14} h={2.8} fill={C.grey3} />
      <Stamp cx={78} cy={59} r={6} color={C.green} />
      <rect
        x={84}
        y={16.5}
        width={16}
        height={7}
        rx={2.5}
        fill={C.ink}
        stroke="none"
        transform="rotate(-45 92 20)"
      />
      <path d="M95 23 L104 32" stroke={C.ink} strokeWidth={3} fill="none" strokeLinecap="round" />
      <rect x={86} y={52} width={20} height={6} rx={3} fill={C.grey2} stroke="none" />
    </>
  ),

  // Register source data before it blocks the schedule: the register holds what
  // the job depends on, and the item that lapsed is the one stopping a bar.
  'register-source-data-before-it-blocks-the-schedule': (a) => (
    <>
      <Sheet x={12} y={14} w={40} h={48} />
      <HeaderBand x={12} y={14} w={40} h={9} fill={a.base} />
      <RowBar x={17} y={17} w={18} h={3} fill={C.white} opacity={0.9} />
      <circle cx={20} cy={32} r={2.6} fill={C.green} stroke="none" />
      <RowBar x={26} y={30.5} w={20} h={3} fill={C.grey3} />
      <circle cx={20} cy={42} r={2.6} fill={C.green} stroke="none" />
      <RowBar x={26} y={40.5} w={16} h={3} fill={C.grey3} />
      <circle cx={20} cy={52} r={2.6} fill={C.red} stroke="none" />
      <RowBar x={26} y={50.5} w={18} h={3} fill={C.grey3} />
      <rect x={64} y={20} width={30} height={6} rx={3} fill={C.grey2} stroke="none" />
      <rect x={70} y={32} width={26} height={6} rx={3} fill={C.grey2} stroke="none" />
      <rect x={78} y={44} width={24} height={6} rx={3} fill={a.light} stroke="none" />
      <path d="M52 52 H74" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <path d="M75 38 V58" stroke={C.red} strokeWidth={3} fill="none" strokeLinecap="round" />
    </>
  ),

  // Register warranties and guarantees at handover: every asset in the register
  // carries its own cover, and the cover runs for a term with an end date.
  'register-warranties-and-guarantees-at-handover': (a) => (
    <>
      <Sheet x={14} y={12} w={52} h={52} />
      <HeaderBand x={14} y={12} w={52} h={9} fill={a.base} />
      <RowBar x={20} y={15} w={20} h={3} fill={C.white} opacity={0.9} />
      <rect x={20} y={26} width={7} height={7} rx={1.5} fill={C.grey2} stroke="none" />
      <RowBar x={31} y={28} w={16} h={3.2} fill={C.grey3} />
      <Shield cx={58} ty={25} w={9} h={10} fill={C.green} shadow={false} />
      <rect x={20} y={38} width={7} height={7} rx={1.5} fill={C.grey2} stroke="none" />
      <RowBar x={31} y={40} w={13} h={3.2} fill={C.grey3} />
      <Shield cx={58} ty={37} w={9} h={10} fill={C.green} shadow={false} />
      <rect x={20} y={50} width={7} height={7} rx={1.5} fill={C.grey2} stroke="none" />
      <RowBar x={31} y={52} w={15} h={3.2} fill={C.grey3} />
      <Shield cx={58} ty={49} w={9} h={10} fill={C.ochre} shadow={false} />
      <Shield cx={88} ty={22} w={28} h={32} fill={a.base} />
      <path
        d="M81 36 l5 5 l10 -12"
        stroke={C.white}
        strokeWidth={3}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M74 68 H104" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <RowBar x={74} y={61.5} w={22} h={5} fill={a.light} />
    </>
  ),

  // Release a provisional sum and charge the attendance fee: money held in the
  // pot is drawn down as the package is let, and a slice is charged on it.
  'release-a-provisional-sum-and-charge-the-attendance-fee': (a) => (
    <>
      <ellipse cx={28} cy={56} rx={14} ry={5} fill={C.ochre} stroke="none" />
      <ellipse cx={28} cy={49} rx={14} ry={5} fill={C.amber} stroke="none" />
      <ellipse cx={28} cy={42} rx={14} ry={5} fill={C.ochre} stroke="none" />
      <ellipse cx={28} cy={35} rx={14} ry={5} fill={C.amber} stroke={C.white} strokeWidth={0.8} />
      <path
        d="M46 44 H60 M56 40 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={64} y={26} w={30} h={34} />
      <HeaderBand x={64} y={26} w={30} h={8} fill={a.base} />
      <RowBar x={69} y={40} w={18} h={3} fill={C.grey3} />
      <RowBar x={69} y={47} w={14} h={3} fill={C.grey3} />
      <Badge cx={90} cy={56} r={5.5} fill={C.green} glyph="check" shadow={false} />
      <circle cx={98} cy={20} r={8} fill={C.grey3} stroke="none" />
      <path d="M98 20 L98 12 A8 8 0 0 1 103.14 13.87 Z" fill={C.ochre} stroke="none" />
    </>
  ),

  // Review what the AI read off the drawing: proposals sit on the sheet as
  // measured regions, each with the confidence it earned, and you accept or
  // throw each one out.
  'review-ai-takeoff-proposals': (a) => (
    <>
      <Sheet x={12} y={14} w={54} h={52} />
      <path
        d="M18 24 H60 V58 H18 Z M40 24 V58 M18 44 H40"
        stroke={C.grey3}
        strokeWidth={1.4}
        fill="none"
      />
      <rect
        x={20}
        y={28}
        width={16}
        height={12}
        rx={1.5}
        fill="none"
        stroke={C.green}
        strokeWidth={1.6}
        strokeDasharray="3 2"
      />
      <rect
        x={44}
        y={28}
        width={14}
        height={12}
        rx={1.5}
        fill="none"
        stroke={C.amber}
        strokeWidth={1.6}
        strokeDasharray="3 2"
      />
      <rect
        x={22}
        y={48}
        width={18}
        height={10}
        rx={1.5}
        fill="none"
        stroke={C.red}
        strokeWidth={1.6}
        strokeDasharray="3 2"
      />
      <RowBar x={74} y={26} w={30} h={4} fill={C.grey3} />
      <RowBar x={74} y={26} w={26} h={4} fill={C.green} />
      <RowBar x={74} y={38} w={30} h={4} fill={C.grey3} />
      <RowBar x={74} y={38} w={17} h={4} fill={C.amber} />
      <RowBar x={74} y={50} w={30} h={4} fill={C.grey3} />
      <RowBar x={74} y={50} w={8} h={4} fill={C.red} />
      <Badge cx={80} cy={63} r={6} fill={C.green} glyph="check" shadow={false} />
      <Badge cx={97} cy={63} r={6} fill={C.grey2} glyph="x" shadow={false} />
      <Star cx={88} cy={15} r={4.5} fill={a.base} />
      <Star cx={99} cy={13} r={3} fill={a.light} />
    </>
  ),

  // Run a clash profile audit: the profile is a matrix of which element sets are
  // tested against which and at what tolerance, then the hits are triaged.
  'run-a-clash-profile-audit': (a) => (
    <>
      <rect x={28} y={14} width={8} height={8} rx={1.5} fill={C.ochre} stroke="none" />
      <rect x={42} y={14} width={8} height={8} rx={1.5} fill={C.amber} stroke="none" />
      <rect x={14} y={28} width={8} height={8} rx={1.5} fill={a.base} stroke="none" />
      <rect x={14} y={42} width={8} height={8} rx={1.5} fill={a.deep} stroke="none" />
      <rect x={28} y={28} width={8} height={8} rx={1.5} fill={a.light} stroke="none" />
      <rect x={42} y={28} width={8} height={8} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={28} y={42} width={8} height={8} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={42} y={42} width={8} height={8} rx={1.5} fill={a.light} stroke="none" />
      <path d="M16 60 V70 M30 60 V70" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path
        d="M16 65 H30 M19.5 62 l-3.5 3 l3.5 3 M26.5 62 l3.5 3 l-3.5 3"
        stroke={a.deep}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={82} cy={34} r={12} fill="none" stroke={C.red} strokeWidth={1.8} />
      <path
        d="M82 18 V26 M82 42 V50 M66 34 H74 M90 34 H98"
        stroke={C.red}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={79} cy={31} r={2.8} fill={C.red} stroke="none" />
      <circle cx={86} cy={38} r={2.2} fill={C.red} stroke="none" />
      <circle cx={70} cy={58} r={2.4} fill={C.red} stroke="none" />
      <RowBar x={76} y={56.5} w={22} h={3} fill={C.grey3} />
      <circle cx={70} cy={66} r={2.4} fill={C.amber} stroke="none" />
      <RowBar x={76} y={64.5} w={17} h={3} fill={C.grey3} />
    </>
  ),

  // Run a concrete pour from request to record: the hold point is cleared, the
  // pour goes into the formwork, and cubes plus the result close the card.
  'run-a-concrete-pour-from-request-to-record': (a) => (
    <>
      <path d="M28 14 H52 L43 28 H37 Z" fill={a.base} stroke="none" />
      <path d="M40 28 V48" stroke={C.grey2} strokeWidth={4} fill="none" strokeLinecap="round" />
      <path
        d="M30 34 V64 H70 V34"
        stroke={C.ochre}
        strokeWidth={3}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={32} y={54} width={36} height={9} rx={1} fill={C.grey3} stroke="none" />
      <path
        d="M38 42 V62 M50 42 V62 M62 42 V62 M34 50 H66"
        stroke={C.grey2}
        strokeWidth={1.2}
        fill="none"
      />
      <Badge cx={19} cy={36} r={7} fill={C.green} glyph="check" />
      <rect x={78} y={54} width={9} height={9} rx={1} fill={C.grey2} stroke={C.grey1} strokeWidth={1.2} />
      <rect x={90} y={54} width={9} height={9} rx={1} fill={C.grey2} stroke={C.grey1} strokeWidth={1.2} />
      <rect x={84} y={44} width={9} height={9} rx={1} fill={C.grey2} stroke={C.grey1} strokeWidth={1.2} />
      <Sheet x={76} y={12} w={28} h={26} />
      <RowBar x={81} y={18} w={16} h={3} fill={C.grey3} />
      <Stamp cx={96} cy={30} r={6} color={C.green} />
    </>
  ),

  // Run a site supervision visit: observations pinned where they were seen, and
  // the work about to be covered flagged while it can still be looked at.
  'run-a-site-supervision-visit': (a) => (
    <>
      <Sheet x={14} y={14} w={52} h={50} />
      <path
        d="M20 22 H60 V56 H20 Z M40 22 V56 M20 40 H40"
        stroke={C.grey3}
        strokeWidth={1.4}
        fill="none"
      />
      <Pin cx={27} cy={42} fill={C.amber} />
      <Pin cx={50} cy={34} fill={C.green} />
      <Pin cx={36} cy={58} fill={a.base} />
      <rect x={76} y={52} width={26} height={9} rx={1.5} fill={a.light} stroke="none" />
      <rect
        x={76}
        y={40}
        width={26}
        height={8}
        rx={1.5}
        fill="none"
        stroke={C.grey1}
        strokeWidth={1.4}
        strokeDasharray="3 2"
      />
      <path d="M78 52 V34" stroke={C.red} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <path d="M78 33 L88 36 L78 39 Z" fill={C.red} stroke="none" />
    </>
  ),

  // Run a soft landings performance handover: the building is occupied, and what
  // it actually does is tuned down onto the target through the first year.
  'run-a-soft-landings-performance-handover': (a) => (
    <>
      <rect x={14} y={26} width={28} height={38} rx={2} fill={C.grey2} stroke="none" />
      <rect x={12} y={22} width={32} height={4} rx={1.5} fill={C.grey1} stroke="none" />
      <rect x={19} y={34} width={7} height={7} rx={1} fill={C.amber} stroke="none" />
      <rect x={30} y={34} width={7} height={7} rx={1} fill={C.grey3} stroke="none" />
      <rect x={19} y={48} width={7} height={7} rx={1} fill={C.amber} stroke="none" />
      <path d="M52 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M60 66 V70 M72 66 V70 M84 66 V70 M96 66 V70" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M52 40 H104" stroke={C.green} strokeWidth={1.6} strokeDasharray="3 2" fill="none" />
      <path
        d="M54 22 C64 24 70 34 80 38 C88 41 94 40 102 40"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={102} cy={40} r={2.8} fill={C.green} stroke="none" />
    </>
  ),

  // Run an authority design review cycle: the version goes out, remarks come
  // back one by one, and the cycle closes under the reviewing seal.
  'run-an-authority-design-review-cycle': (a) => (
    <>
      <Sheet x={16} y={14} w={42} h={52} />
      <HeaderBand x={16} y={14} w={42} h={9} fill={C.grey2} />
      <RowBar x={22} y={17} w={18} h={3} fill={C.white} opacity={0.9} />
      <path d="M20 28 L25 31 L20 34 Z" fill={C.red} stroke="none" />
      <RowBar x={29} y={29.5} w={23} h={3} fill={C.grey3} />
      <path d="M20 38 L25 41 L20 44 Z" fill={C.amber} stroke="none" />
      <RowBar x={29} y={39.5} w={19} h={3} fill={C.grey3} />
      <path d="M20 48 L25 51 L20 54 Z" fill={C.green} stroke="none" />
      <RowBar x={29} y={49.5} w={21} h={3} fill={C.grey3} />
      <circle
        cx={86}
        cy={30}
        r={16}
        fill="none"
        stroke={a.light}
        strokeWidth={2.6}
        strokeDasharray="2.5 3"
      />
      <circle cx={86} cy={30} r={12.5} fill={a.base} stroke={C.white} strokeWidth={1.2} />
      <circle cx={86} cy={30} r={8.5} fill="none" stroke={C.white} strokeWidth={1.2} opacity={0.75} />
      <path
        d="M81 30 l4 4 l7 -8"
        stroke={C.white}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M94 55 C93 65 77 69 64 62"
        stroke={a.base}
        strokeWidth={2}
        strokeDasharray="2 3"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M64 62 l7 -1.5 M64 62 l4.5 5"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Run an interim payment under the Construction Act: the due date starts a
  // clock, each notice lands on the timeline before the final date, and the
  // notified sum is what it is once the retention is taken off.
  'run-an-interim-payment-under-the-construction-act': (a) => (
    <>
      <circle cx={28} cy={32} r={13} fill={C.white} stroke={a.base} strokeWidth={2.4} />
      <path
        d="M28 23 V32 l7 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <RowBar x={54} y={14} w={44} h={8} fill={C.grey3} />
      <RowBar x={54} y={14} w={32} h={8} fill={a.deep} />
      <rect x={88} y={14.5} width={8} height={7} rx={2} fill={C.ochre} stroke="none" />
      <path d="M18 60 H104" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <path d="M50 54 l5 6 l-5 6 l-5 -6 z" fill={a.base} stroke={C.white} strokeWidth={1} />
      <rect x={60} y={38} width={14} height={10} rx={1.5} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M60.5 39.5 l6.5 4.5 l6.5 -4.5" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <rect x={78} y={38} width={14} height={10} rx={1.5} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M78.5 39.5 l6.5 4.5 l6.5 -4.5" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M67 48 V58 M85 48 V58" stroke={C.grey1} strokeWidth={1.2} strokeDasharray="2 2" fill="none" />
      <path d="M98 60 V46" stroke={C.green} strokeWidth={2} fill="none" strokeLinecap="round" />
      <path d="M98 46 L106 48.5 L98 51 Z" fill={C.green} stroke="none" />
    </>
  ),
};
