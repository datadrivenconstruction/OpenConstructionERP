// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - bespoke line-art scenes, wave 2.
//
// A second batch of hand-drawn case illustrations in exactly the language of
// `caseScenes.tsx`: the shared `0 0 120 84` viewBox, the faint blueprint grid
// behind, the fixed `C` palette from stepSceneParts for the structure and one
// category accent for the element that carries the case's meaning.
//
// This wave covers sixteen cases that still fell back to a lone icon: monthly
// certification, the overdue-date sweep, model checks against the information
// requirements, licence-and-parallel-taxes pricing, delivery-route classing,
// substantial-performance closeout, statutory approvals, the building book,
// tender-versus-settlement comparison, the tender control price, payment
// deductions at source, a cost plan by cost group, an approval-route dry run,
// index escalation, own-crew rates and norm expansion.
//
// No letterforms anywhere: these ship in every language the platform speaks, so
// meaning is carried by shape, arrangement and symbol only.

import { type ReactElement } from 'react';
import {
  C,
  Badge,
  Chip,
  Cube,
  HeaderBand,
  RowBar,
  Sheet,
  Shield,
  Signature,
  Stamp,
  WarnTri,
} from './stepSceneParts';
import { type Accent } from './categories';

/** A scene takes its category accent ramp and returns its artwork group. */
type Scene = (a: Accent) => ReactElement;

/** Bespoke case illustrations for wave 2, keyed by case id. */
export const CASE_SCENES_WAVE2: Record<string, Scene> = {
  // Certify the month against the mediciones: each bill position carries its own
  // measured percent complete, and the certificacion is stamped and signed
  // before the payment clock starts.
  'certify-the-month-against-the-mediciones': (a) => (
    <>
      <Sheet x={16} y={14} w={62} h={54} />
      <HeaderBand x={16} y={14} w={62} h={10} fill={a.base} />
      <RowBar x={22} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={22} y={32} w={14} h={3.2} fill={C.grey3} />
      <rect x={40} y={30.5} width={30} height={5.5} rx={2.75} fill="none" stroke={C.grey1} strokeWidth={1.2} />
      <rect x={40} y={30.5} width={21} height={5.5} rx={2.75} fill={a.base} stroke="none" />
      <RowBar x={22} y={42} w={12} h={3.2} fill={C.grey3} />
      <rect x={40} y={40.5} width={30} height={5.5} rx={2.75} fill="none" stroke={C.grey1} strokeWidth={1.2} />
      <rect x={40} y={40.5} width={13} height={5.5} rx={2.75} fill={a.base} stroke="none" />
      <RowBar x={22} y={52} w={15} h={3.2} fill={C.grey3} />
      <rect x={40} y={50.5} width={30} height={5.5} rx={2.75} fill="none" stroke={C.grey1} strokeWidth={1.2} />
      <rect x={40} y={50.5} width={25} height={5.5} rx={2.75} fill={a.base} stroke="none" />
      <Stamp cx={90} cy={26} r={8} color={C.green} />
      <Signature x={78} y={48} w={24} color={a.base} />
      <circle cx={90} cy={64} r={7} fill={C.white} stroke={a.base} strokeWidth={1.8} />
      <path d="M90 60 v4 l3 2" stroke={a.base} strokeWidth={1.6} fill="none" strokeLinecap="round" />
    </>
  ),

  // Chase every overdue date in one place: one calendar of the dates the platform
  // tracks, the genuinely late ones flagged red, and a sweep that mails the
  // owners so the worst one gets picked up.
  'chase-every-overdue-date-across-the-project': (a) => (
    <>
      <path d="M24 10 V17 M50 10 V17" stroke={a.deep} strokeWidth={2} fill="none" strokeLinecap="round" />
      <Sheet x={14} y={14} w={46} h={52} />
      <HeaderBand x={14} y={14} w={46} h={10} fill={a.base} />
      <rect x={18} y={30} width={9} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={29} y={30} width={9} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={40} y={30} width={9} height={9} rx={1.5} fill={C.red} stroke="none" />
      <rect x={51} y={30} width={9} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={18} y={44} width={9} height={9} rx={1.5} fill={C.red} stroke="none" />
      <rect x={29} y={44} width={9} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={40} y={44} width={9} height={9} rx={1.5} fill={C.amber} stroke="none" />
      <rect x={51} y={44} width={9} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <path
        d="M62 34 H72 M69 31 l3 3 l-3 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={74} y={24} width={30} height={20} rx={2.5} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <path d="M74 26 L89 36 L104 26" fill="none" stroke={C.grey1} strokeWidth={1.4} />
      <Badge cx={101} cy={23} r={5.5} fill={C.red} glyph="warn" shadow={false} />
      <path
        d="M82 46 V54 M96 46 V54"
        stroke={C.grey1}
        strokeWidth={1.2}
        strokeDasharray="2 2"
        fill="none"
      />
      <circle cx={82} cy={59} r={4.6} fill={C.grey2} stroke="none" />
      <path d="M75 71 c0 -6 3 -9 7 -9 s7 3 7 9 z" fill={C.grey2} stroke="none" />
      <circle cx={96} cy={59} r={4.6} fill={C.grey2} stroke="none" />
      <path d="M89 71 c0 -6 3 -9 7 -9 s7 3 7 9 z" fill={C.grey2} stroke="none" />
      <Badge cx={103} cy={68} r={4.4} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Check a model against the EIR and raise issues: the delivered model read
  // against the requirement list, two requirements passing, one failing, and the
  // gap raised back on the model as an issue.
  'check-a-model-against-the-eir-and-raise-issues': (a) => (
    <>
      <Cube cx={36} ty={20} w={17} hh={8.5} depth={20} top={a.light} left={a.base} right={a.deep} />
      <Sheet x={66} y={14} w={40} h={54} />
      <HeaderBand x={66} y={14} w={40} h={9} fill={a.base} />
      <Badge cx={73} cy={34} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={79} y={32.5} w={20} h={3} fill={C.grey3} />
      <Badge cx={73} cy={44} r={3.6} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={79} y={42.5} w={16} h={3} fill={C.grey3} />
      <Badge cx={73} cy={55} r={3.6} fill={C.red} glyph="x" shadow={false} />
      <RowBar x={79} y={53.5} w={18} h={3} fill={C.grey3} />
      <WarnTri cx={30} cy={64} w={15} fill={C.red} />
      <path
        d="M38 64 C50 64 54 57 64 56"
        stroke={C.red}
        strokeWidth={1.4}
        strokeDasharray="2 3"
        fill="none"
      />
    </>
  ),

  // Check the RBQ subclass and price GST and QST in parallel: the licence is on
  // record with the subclass it actually carries, and the two taxes branch off
  // one and the same pre-tax base rather than stacking on each other.
  'check-the-rbq-subclass-and-price-gst-and-qst': (a) => (
    <>
      <Sheet x={14} y={12} w={44} h={26} />
      <rect x={19} y={17} width={12} height={12} rx={2} fill={C.grey3} stroke="none" />
      <RowBar x={35} y={18} w={18} h={3} fill={C.grey2} />
      <Chip x={35} y={25} w={14} h={7} r={2} fill={a.base} />
      <Badge cx={54} cy={16} r={5.5} fill={C.green} glyph="check" shadow={false} />
      <rect x={14} y={48} width={40} height={8} rx={2.5} fill={C.grey2} stroke="none" />
      <path d="M56 51 C64 51 64 42 72 42" stroke={a.base} strokeWidth={2} fill="none" />
      <path
        d="M69 39 l3 3 l-3 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M56 53 C64 53 64 62 72 62" stroke={a.base} strokeWidth={2} fill="none" />
      <path
        d="M69 59 l3 3 l-3 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={74} y={38} width={28} height={8} rx={2.5} fill={a.base} stroke="none" />
      <rect x={74} y={58} width={28} height={8} rx={2.5} fill={C.ochre} stroke="none" />
    </>
  ),

  // Classify the delivery route for a work package: the package meets a decision
  // point, two candidate routes stay greyed out and the one it belongs on is
  // taken and confirmed.
  'classify-the-delivery-route-for-a-work-package': (a) => (
    <>
      <Cube cx={24} ty={26} w={11} hh={5.5} depth={13} top={C.panel} left={C.grey3} right={C.grey2} />
      <path d="M35 40 H42" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <circle cx={48} cy={40} r={5.5} fill={a.base} stroke={C.white} strokeWidth={1} />
      <path
        d="M54 37 C62 32 64 21 68 21"
        stroke={C.grey2}
        strokeWidth={1.8}
        strokeDasharray="2 3"
        fill="none"
      />
      <path d="M54 40 H68" stroke={a.base} strokeWidth={2.6} fill="none" strokeLinecap="round" />
      <path
        d="M54 43 C62 48 64 61 68 61"
        stroke={C.grey2}
        strokeWidth={1.8}
        strokeDasharray="2 3"
        fill="none"
      />
      <rect x={70} y={16} width={18} height={9} rx={4.5} fill="none" stroke={C.grey2} strokeWidth={1.6} />
      <rect x={70} y={36} width={18} height={9} rx={4.5} fill={a.base} stroke="none" />
      <rect x={70} y={56} width={18} height={9} rx={4.5} fill="none" stroke={C.grey2} strokeWidth={1.6} />
      <path d="M88 40.5 H91" stroke={a.base} strokeWidth={2} fill="none" strokeLinecap="round" />
      <Badge cx={98} cy={40.5} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Close out from substantial performance to the final account: the date is
  // certified once on the programme, then the holdback is released except for
  // the priced deficiency reserve, and the final account is agreed.
  'close-out-from-substantial-performance-to-the-final-account': (a) => (
    <>
      <path d="M14 26 H106" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path d="M40 26 V12" stroke={a.base} strokeWidth={2.2} fill="none" />
      <path d="M40 12 H58 L54 17 L58 22 H40 Z" fill={a.base} stroke="none" />
      <circle cx={40} cy={26} r={3.2} fill={a.deep} stroke="none" />
      <rect x={18} y={40} width={84} height={14} rx={4} fill={C.panel} stroke={C.grey1} strokeWidth={1.4} />
      <rect x={21} y={43} width={58} height={8} rx={4} fill={C.green} stroke="none" />
      <rect x={82} y={43} width={17} height={8} rx={4} fill={C.amber} stroke="none" />
      <Sheet x={16} y={58} w={40} h={14} />
      <RowBar x={21} y={61} w={20} h={3} fill={C.grey3} />
      <RowBar x={21} y={66} w={14} h={3} fill={C.grey3} />
      <Badge cx={88} cy={64} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Close out permits and statutory approvals: the authority inspects, the
  // completion certificates come back stamped, and every planning condition is
  // ticked off as discharged.
  'close-out-permits-and-statutory-approvals': (a) => (
    <>
      <path d="M16 30 L34 20 L52 30 Z" fill={a.deep} stroke="none" />
      <rect x={18} y={30} width={32} height={26} fill={a.base} stroke="none" />
      <path
        d="M24 34 V52 M34 34 V52 M44 34 V52"
        stroke={a.light}
        strokeWidth={3.4}
        fill="none"
        strokeLinecap="round"
      />
      <rect x={14} y={56} width={40} height={4} rx={1} fill={a.deep} stroke="none" />
      <rect x={62} y={16} width={38} height={26} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <Sheet x={66} y={22} w={38} h={26} />
      <RowBar x={71} y={29} w={20} h={3} fill={C.grey3} />
      <RowBar x={71} y={35} w={16} h={3} fill={C.grey3} />
      <Stamp cx={96} cy={40} r={6} color={C.green} />
      <Badge cx={66} cy={58} r={4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={73} y={56.5} w={20} h={3} fill={C.grey3} />
      <Badge cx={66} cy={68} r={4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={73} y={66.5} w={15} h={3} fill={C.grey3} />
    </>
  ),

  // Close the works and hand over the libro del edificio: the final works
  // certificate is signed, the building book is assembled open on the table, and
  // the guarantee periods start running from that date.
  'close-the-works-and-hand-over-the-libro-del-edificio': (a) => (
    <>
      <Sheet x={72} y={10} w={34} h={22} />
      <RowBar x={77} y={15} w={16} h={2.8} fill={C.grey3} />
      <Signature x={77} y={25} w={24} color={a.base} />
      <path
        d="M16 34 C26 30 36 30 46 34 V64 C36 60 26 60 16 64 Z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <path
        d="M46 34 C56 30 66 30 76 34 V64 C66 60 56 60 46 64 Z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
      />
      <path d="M46 34 V64" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <path
        d="M22 42 H40 M22 48 H38 M22 54 H36"
        stroke={C.grey3}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M52 42 H70 M52 48 H68 M52 54 H66"
        stroke={C.grey3}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <Shield cx={92} ty={40} w={20} h={26} fill={a.base} />
    </>
  ),

  // Compare the tender bill against the settlement: the awarded bill and the
  // settlement bill set side by side, every line that moved marked in the gutter
  // as added, removed or changed.
  'compare-the-tender-bill-against-the-settlement': (a) => (
    <>
      <Sheet x={14} y={14} w={38} h={56} />
      <HeaderBand x={14} y={14} w={38} h={9} fill={a.base} />
      <RowBar x={19} y={32} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={19} y={44} w={22} h={3.2} fill={C.grey3} />
      <RowBar x={19} y={56} w={24} h={3.2} fill={C.grey3} />
      <Sheet x={68} y={14} w={38} h={56} />
      <HeaderBand x={68} y={14} w={38} h={9} fill={a.deep} />
      <RowBar x={73} y={32} w={24} h={3.2} fill={C.grey3} />
      <RowBar x={73} y={44} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={73} y={56} w={18} h={3.2} fill={C.grey3} />
      <Badge cx={60} cy={33.5} r={4.6} fill={C.green} glyph="plus" shadow={false} />
      <Badge cx={60} cy={45.5} r={4.6} fill={C.red} glyph="x" shadow={false} />
      <Badge cx={60} cy={57.5} r={4.6} fill={C.amber} glyph="warn" shadow={false} />
    </>
  ),

  // Compile the tender control price and price a bid: the control price is
  // compiled and sealed as the published ceiling, and the sealed bids underneath
  // are read back against it.
  'compile-the-tender-control-price-and-price-a-bid': (a) => (
    <>
      <Sheet x={36} y={10} w={48} h={30} />
      <HeaderBand x={36} y={10} w={48} h={8} fill={a.base} />
      <RowBar x={42} y={24} w={22} h={3.2} fill={C.grey3} />
      <rect x={42} y={31} width={26} height={4.6} rx={2.3} fill={a.deep} stroke="none" />
      <Stamp cx={90} cy={30} r={8} color={C.red} />
      <path
        d="M60 42 V48"
        stroke={a.base}
        strokeWidth={1.6}
        strokeDasharray="2 2"
        fill="none"
      />
      <rect x={16} y={50} width={26} height={18} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M16 51 L29 60 L42 51" fill="none" stroke={C.grey1} strokeWidth={1.3} />
      <rect x={47} y={50} width={26} height={18} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M47 51 L60 60 L73 51" fill="none" stroke={C.grey1} strokeWidth={1.3} />
      <rect x={78} y={50} width={26} height={18} rx={2} fill={C.white} stroke={C.grey1} strokeWidth={1.4} />
      <path d="M78 51 L91 60 L104 51" fill="none" stroke={C.grey1} strokeWidth={1.3} />
      <Badge cx={73} cy={68} r={5} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Deduct CIS when you pay a subcontractor: the payee is verified first, the
  // deduction is a slice taken out of the gross before the money leaves, and the
  // payment splits into what is withheld and what is actually paid.
  'deduct-cis-when-you-pay-a-subcontractor': (a) => (
    <>
      <circle cx={22} cy={22} r={6.5} fill={C.grey2} stroke="none" />
      <path d="M13 40 c0 -8 4 -12 9 -12 s9 4 9 12 z" fill={C.grey2} stroke="none" />
      <Badge cx={33} cy={32} r={4.8} fill={C.green} glyph="check" shadow={false} />
      <circle cx={82} cy={30} r={13} fill="none" stroke={C.grey3} strokeWidth={7} />
      <path
        d="M82 17 A13 13 0 0 1 94.8 27.5"
        fill="none"
        stroke={C.red}
        strokeWidth={7}
        strokeLinecap="butt"
      />
      <path
        d="M79 43 C76 50 74 54 70 61"
        stroke={C.red}
        strokeWidth={1.4}
        strokeDasharray="2 3"
        fill="none"
      />
      <Sheet x={16} y={54} w={88} h={18} />
      <HeaderBand x={16} y={54} w={88} h={7} r={3} fill={a.base} />
      <RowBar x={22} y={64} w={30} h={3.4} fill={C.grey3} />
      <RowBar x={58} y={64} w={16} h={3.4} fill={C.red} />
      <RowBar x={80} y={64} w={18} h={3.4} fill={C.green} />
    </>
  ),

  // Report a DIN 276 cost plan to the client: every position hangs off its cost
  // group in the hierarchy, each group is read as a deviation either side of the
  // agreed frame, and the plan goes to the client with nothing unclassified.
  'din-276-cost-plan-for-the-client': (a) => (
    <>
      <rect x={14} y={14} width={24} height={10} rx={2} fill={a.base} stroke="none" />
      <path d="M20 24 V62" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M20 32 H28 M20 46 H28 M20 60 H28" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <rect x={28} y={27.5} width={20} height={9} rx={2} fill={a.light} stroke="none" />
      <rect x={28} y={41.5} width={20} height={9} rx={2} fill={a.light} stroke="none" />
      <rect x={28} y={55.5} width={20} height={9} rx={2} fill={a.light} stroke="none" />
      <path
        d="M48 32 H70 M48 46 H70 M48 60 H70"
        stroke={C.grey2}
        strokeWidth={1}
        strokeDasharray="1 3"
        fill="none"
      />
      <path d="M70 24 V70" stroke={C.grey1} strokeWidth={1.2} strokeDasharray="3 3" fill="none" />
      <rect x={70} y={29} width={16} height={6} rx={3} fill={C.red} stroke="none" />
      <rect x={58} y={43} width={12} height={6} rx={3} fill={C.green} stroke="none" />
      <rect x={70} y={57} width={9} height={6} rx={3} fill={C.amber} stroke="none" />
      <Badge cx={96} cy={18} r={8} fill={C.green} glyph="check" />
      <circle cx={96} cy={56} r={5.5} fill={C.grey2} stroke="none" />
      <path d="M87 70 c0 -7 4 -11 9 -11 s9 4 9 11 z" fill={C.grey2} stroke="none" />
    </>
  ),

  // Dry-run an approval route before committing it: the route is played through
  // before it is live, each step shows the role it lands on, and the simulation
  // exposes the step it can never actually reach.
  'dry-run-an-approval-route-before-committing-it': (a) => (
    <>
      <path d="M14 24 L25 30 L14 36 Z" fill={a.base} stroke="none" />
      <path d="M25 30 H29 M47 30 H53 M71 30 H77" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <rect x={29} y={23} width={18} height={14} rx={3} fill={a.base} stroke="none" />
      <rect x={53} y={23} width={18} height={14} rx={3} fill={a.base} stroke="none" />
      <rect
        x={77}
        y={23}
        width={18}
        height={14}
        rx={3}
        fill={C.white}
        stroke={a.base}
        strokeWidth={1.8}
        strokeDasharray="4 3"
      />
      <circle cx={38} cy={48} r={3.6} fill={C.grey2} stroke="none" />
      <circle cx={62} cy={48} r={3.6} fill={C.grey2} stroke="none" />
      <circle cx={86} cy={48} r={3.6} fill={C.grey2} stroke="none" />
      <Badge cx={38} cy={64} r={5} fill={C.green} glyph="check" shadow={false} />
      <Badge cx={62} cy={64} r={5} fill={C.green} glyph="check" shadow={false} />
      <WarnTri cx={86} cy={64} w={15} fill={C.amber} />
    </>
  ),

  // Escalate an estimate with price indices: the published index is read at the
  // base date and again at the midpoint of construction, and the difference
  // lifts the total on the bill.
  'escalate-an-estimate-with-price-indices': (a) => (
    <>
      <path d="M16 66 H64 M16 66 V20" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M18 60 C30 57 40 48 52 40 C56 37 59 34 62 31"
        fill="none"
        stroke={a.base}
        strokeWidth={2.4}
        strokeLinecap="round"
      />
      <path d="M28 66 V57" stroke={C.grey2} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <circle cx={28} cy={57} r={2.6} fill={C.grey2} stroke="none" />
      <path d="M52 66 V40" stroke={a.base} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <circle cx={52} cy={40} r={2.8} fill={a.base} stroke="none" />
      <path
        d="M66 44 H74 M71 41 l3 3 l-3 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={76} y={22} w={30} h={42} />
      <HeaderBand x={76} y={22} w={30} h={8} fill={a.base} />
      <RowBar x={81} y={36} w={16} h={3} fill={C.grey3} />
      <RowBar x={81} y={44} w={13} h={3} fill={C.grey3} />
      <rect x={81} y={52} width={20} height={5} rx={2.5} fill={C.ochre} stroke="none" />
      <path
        d="M103 58 V50 M100.5 52.5 l2.5 -2.5 l2.5 2.5"
        stroke={C.ochre}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Estimate with your own crew rates: what an hour of your own crew really
  // costs is what the unit rate is assembled from, labour beside material and
  // plant, instead of a borrowed published rate.
  'estimate-with-your-own-crew-rates': (a) => (
    <>
      <circle cx={20} cy={24} r={5} fill={C.ochre} stroke="none" />
      <path d="M13 42 c0 -8 3 -12 7 -12 s7 4 7 12 z" fill={C.grey2} stroke="none" />
      <circle cx={36} cy={24} r={5} fill={C.ochre} stroke="none" />
      <path d="M29 42 c0 -8 3 -12 7 -12 s7 4 7 12 z" fill={C.grey2} stroke="none" />
      <circle cx={52} cy={24} r={5} fill={C.ochre} stroke="none" />
      <path d="M45 42 c0 -8 3 -12 7 -12 s7 4 7 12 z" fill={C.grey2} stroke="none" />
      <circle cx={72} cy={24} r={7} fill={C.white} stroke={a.base} strokeWidth={1.8} />
      <path d="M72 19 v5 l4 2" stroke={a.base} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <path
        d="M40 46 V52 M36.5 49.5 l3.5 3 l3.5 -3"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={14} y={56} width={92} height={14} rx={4} fill={C.panel} stroke={C.grey1} strokeWidth={1.2} />
      <rect x={17} y={59} width={40} height={8} rx={4} fill={a.base} stroke="none" />
      <rect x={59} y={59} width={26} height={8} rx={4} fill={C.ochre} stroke="none" />
      <rect x={87} y={59} width={16} height={8} rx={4} fill={C.grey2} stroke="none" />
    </>
  ),

  // Expand production norms into resource quantities: one norm per unit fans out
  // across the takeoff quantity into the crew hours, the plant time and the
  // material it actually consumes.
  'expand-production-norms-into-resource-quantities': (a) => (
    <>
      <Sheet x={14} y={28} w={28} h={28} />
      <HeaderBand x={14} y={28} w={28} h={8} fill={a.base} />
      <RowBar x={19} y={41} w={16} h={3} fill={C.grey3} />
      <RowBar x={19} y={48} w={11} h={3} fill={C.grey3} />
      <path d="M44 42 C52 42 52 24 60 24" stroke={a.base} strokeWidth={1.8} fill="none" />
      <path d="M44 42 H60" stroke={a.base} strokeWidth={1.8} fill="none" />
      <path d="M44 42 C52 42 52 62 60 62" stroke={a.base} strokeWidth={1.8} fill="none" />
      <circle cx={66} cy={24} r={3.6} fill={C.grey2} stroke="none" />
      <circle cx={76} cy={24} r={3.6} fill={C.grey2} stroke="none" />
      <circle cx={86} cy={24} r={3.6} fill={C.grey2} stroke="none" />
      <rect x={64} y={37} width={13} height={8} rx={1.5} fill={C.ochre} stroke="none" />
      <circle cx={67.5} cy={46.5} r={2} fill={a.deep} stroke="none" />
      <circle cx={73.5} cy={46.5} r={2} fill={a.deep} stroke="none" />
      <rect x={84} y={37} width={13} height={8} rx={1.5} fill={C.ochre} stroke="none" />
      <circle cx={87.5} cy={46.5} r={2} fill={a.deep} stroke="none" />
      <circle cx={93.5} cy={46.5} r={2} fill={a.deep} stroke="none" />
      <Cube cx={68} ty={56} w={6} hh={3} depth={7} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={82} ty={56} w={6} hh={3} depth={7} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={96} ty={56} w={6} hh={3} depth={7} top={a.light} left={a.base} right={a.deep} />
    </>
  ),
};
