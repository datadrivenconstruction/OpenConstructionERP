// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - wave 1 of the bespoke scenes for cases that still fall back to a
// single generic icon. Same visual language as `caseScenes.tsx`: the shared
// `0 0 120 84` viewBox, the faint blueprint grid behind, the fixed `C` palette
// from stepSceneParts plus one accent from the case's own category ramp.
//
// This wave covers eighteen cases across escalation and index adjustment (CN,
// ES), CDE approval routes, GAEB inquiries, safety plans, extension of time,
// pipelines, monthly billing (US, CA), 4D sequencing, unit-rate composition
// (CN, ES, DE) and labour-rate build-ups (generic, CA).
//
// No <text> anywhere: these cards ship in every supported language, so meaning
// is carried by shape and arrangement only, never by letterforms.

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
  Signature,
  Stamp,
  WarnTri,
} from './stepSceneParts';
import { type Accent } from './categories';

/** A scene takes its category accent ramp and returns its artwork group. */
type Scene = (a: Accent) => ReactElement;

/**
 * Wave 1 of the bespoke case illustrations, keyed by case id. Merged over
 * `CASE_SCENES` by the caller, so an id present in both keeps the older scene.
 */
export const CASE_SCENES_WAVE1: Record<string, Scene> = {
  // Adjust a material price with a cost index (CN): a published index series
  // read at two periods, and the movement between them is the adjustment.
  'adjust-a-material-price-with-a-cost-index': (a) => (
    <>
      <Cube cx={26} ty={16} w={11} hh={5.5} depth={12} top={C.grey3} left={C.grey2} right={C.grey1} />
      <path d="M26 41 V57" stroke={C.grey1} strokeWidth={1.2} strokeDasharray="2 2.5" fill="none" />
      <path d="M18 66 H104" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path
        d="M22 60 L40 56 L58 46 L76 38 L100 28"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M40 60 V66 M76 42 V66" stroke={C.grey1} strokeWidth={1.2} strokeDasharray="2 2.5" fill="none" />
      <circle cx={40} cy={56} r={4} fill={C.white} stroke={C.grey1} strokeWidth={1.8} />
      <circle cx={76} cy={38} r={4.5} fill={a.base} stroke={C.white} strokeWidth={1.4} />
      <path
        d="M90 38 V56 M87 41 l3 -3 l3 3 M87 53 l3 3 l3 -3"
        stroke={C.ochre}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Adopt a CDE approval preset: a ready-made review flow lifted off the shelf
  // and dropped in as a routed approval that ends at the go-live gate.
  'adopt-a-cde-approval-preset': (a) => (
    <>
      <rect x={14} y={32} width={26} height={18} rx={3} fill={C.grey3} stroke="none" />
      <rect x={16} y={26} width={26} height={18} rx={3} fill={C.grey2} stroke="none" />
      <Sheet x={18} y={20} w={26} h={18} r={3} fill={a.light} stroke={a.base} />
      <Badge cx={42} cy={23} r={4} fill={C.green} glyph="check" shadow={false} />
      <path
        d="M48 36 H56 M52.5 32.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.grey1}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={58} y={14} width={20} height={11} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <rect x={66} y={31} width={20} height={11} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <rect x={58} y={48} width={20} height={11} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <path
        d="M68 25 L76 31 M76 42 L68 48 M78 53 H88"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Shield cx={95} ty={44} w={13} h={15} fill={C.green} />
    </>
  ),

  // Answer a GAEB inquiry as a subcontractor (DE): the contractor's whole bill
  // forks - your own trade goes on to be priced, the rest is dropped, and the
  // priced answer travels back to where the inquiry came from.
  'answer-a-gaeb-inquiry-as-a-subcontractor': (a) => (
    <>
      <Sheet x={13} y={14} w={32} h={48} />
      <RowBar x={19} y={22} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={19} y={30} w={22} h={3.6} fill={a.base} />
      <RowBar x={19} y={38} w={18} h={3.6} fill={a.base} />
      <RowBar x={19} y={46} w={21} h={3.2} fill={C.grey3} />
      <path
        d="M48 34 H54 V24 H61 M58 21 l3 3 l-3 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M48 46 H54 V58 H61"
        stroke={C.grey2}
        strokeWidth={1.8}
        strokeDasharray="3 3"
        fill="none"
        strokeLinecap="round"
      />
      <Badge cx={67} cy={58} r={5} fill={C.grey2} glyph="x" shadow={false} />
      <Sheet x={64} y={12} w={42} h={26} />
      <HeaderBand x={64} y={12} w={42} h={8} fill={a.base} />
      <RowBar x={70} y={25} w={18} h={3.4} fill={C.grey3} />
      <RowBar x={94} y={25} w={8} h={3.4} fill={a.base} />
      <RowBar x={70} y={32} w={14} h={3.4} fill={C.grey3} />
      <RowBar x={92} y={32} w={10} h={3.4} fill={a.base} />
      <path
        d="M100 44 V66 H86 M89 63 l-3 3 l3 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Answer the estudio with a plan de seguridad (ES): every hazard the study
  // lists comes back as a control in the plan, and the plan is signed off.
  'answer-the-estudio-with-a-plan-de-seguridad': (a) => (
    <>
      <Sheet x={13} y={14} w={32} h={46} />
      <WarnTri cx={21} cy={32} w={9} fill={C.amber} shadow={false} />
      <RowBar x={28} y={30.5} w={13} h={3} fill={C.grey3} />
      <WarnTri cx={21} cy={46} w={9} fill={C.amber} shadow={false} />
      <RowBar x={28} y={44.5} w={11} h={3} fill={C.grey3} />
      <path
        d="M50 36 H58 M54.5 32.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.grey1}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={60} y={12} w={44} h={52} />
      <HeaderBand x={60} y={12} w={44} h={9} fill={a.base} />
      <Shield cx={70} ty={26} w={12} h={14} fill={a.base} shadow={false} />
      <Badge cx={84} cy={30} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={90} y={28.5} w={11} h={3} fill={C.grey3} />
      <Badge cx={84} cy={41} r={3.4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={90} y={39.5} w={9} h={3} fill={C.grey3} />
      <Stamp cx={70} cy={54} r={7} color={C.green} />
    </>
  ),

  // Apply revision de precios to a public contract (ES): the stamped contract
  // decides it, the revision rides on its own line, the indices are filed.
  'apply-revision-de-precios-to-a-public-contract': (a) => (
    <>
      <Sheet x={14} y={14} w={34} h={38} />
      <HeaderBand x={14} y={14} w={34} h={8} fill={C.blue} />
      <RowBar x={19} y={27} w={22} h={3} fill={C.grey3} />
      <Stamp cx={31} cy={42} r={7} color={C.blue} />
      <path
        d="M52 34 H60 M56.5 30.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.grey1}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={64} y={14} w={42} h={48} />
      <HeaderBand x={64} y={14} w={42} h={9} fill={C.grey1} />
      <RowBar x={70} y={29} w={24} h={3.4} fill={C.grey3} />
      <RowBar x={70} y={37} w={20} h={3.4} fill={C.grey3} />
      <path d="M70 45 H100" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={70} y={48} w={22} h={4.4} fill={a.base} />
      <Chip x={96} y={47.5} w={6} h={6} r={2} fill={a.light} />
      <Sheet x={14} y={58} w={22} h={13} r={2} shadow={false} />
      <path
        d="M20 60 v-3 a2.6 2.6 0 0 1 5.2 0 v6"
        stroke={C.grey1}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Assess an extension of time with programme impact: the delay event moves the
  // completion date by a measured amount, and a signed notice goes out for it.
  'assess-an-extension-of-time-with-programme-impact': (a) => (
    <>
      <path
        d="M22 20 V26 M34 20 V26 M74 20 V26 M86 20 V26"
        stroke={C.grey1}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
      />
      <Sheet x={16} y={24} w={26} h={24} />
      <HeaderBand x={16} y={24} w={26} h={7} fill={C.grey1} />
      <RowBar x={21} y={37} w={16} h={3} fill={C.grey3} />
      <WarnTri cx={54} cy={24} w={13} fill={C.amber} />
      <path d="M46 34 V31 H66 V34" stroke={a.base} strokeWidth={1.6} fill="none" strokeLinejoin="round" />
      <path
        d="M46 40 H64 M60.5 36.5 l3.5 3.5 l-3.5 3.5"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={68} y={24} w={26} h={24} />
      <HeaderBand x={68} y={24} w={26} h={7} fill={a.base} />
      <RowBar x={73} y={37} w={16} h={3} fill={C.grey3} />
      <Badge cx={88} cy={44} r={5} fill={C.green} glyph="check" shadow={false} />
      <Sheet x={30} y={54} w={30} h={18} r={2} shadow={false} />
      <Signature x={35} y={66} w={16} color={a.base} />
      <path
        d="M64 63 H74 M70.5 59.5 l3.5 3.5 l-3.5 3.5"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Automate a recurring check with a pipeline: the same steps run on a loop,
  // the lint catches a step wired to nothing, the run ends in a verdict.
  'automate-a-recurring-check-with-a-pipeline': (a) => (
    <>
      <circle cx={30} cy={44} r={9} fill={a.light} stroke={a.base} strokeWidth={2} />
      <rect x={26} y={40} width={8} height={8} rx={1.5} fill={a.base} stroke="none" />
      <circle cx={60} cy={44} r={9} fill={a.light} stroke={a.base} strokeWidth={2} />
      <circle cx={60} cy={44} r={3.6} fill={a.base} stroke="none" />
      <path
        d="M39 44 H49 M45.5 40.5 l3.5 3.5 l-3.5 3.5 M69 44 H79 M75.5 40.5 l3.5 3.5 l-3.5 3.5"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={90} cy={44} r={9} fill={C.green} glyph="check" />
      <path
        d="M90 33 C90 16 30 16 30 33"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M27 30 l3 3.5 l3 -3.5"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M60 53 V57" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <WarnTri cx={60} cy={63} w={12} fill={C.amber} />
    </>
  ),

  // Bill the month with a payment application (US): the contract sum is broken
  // into a schedule of values, each line is billed to the part actually earned,
  // the retainage is held back and the certificate is issued.
  'bill-the-month-with-a-payment-application': (a) => (
    <>
      <rect x={16} y={16} width={14} height={14} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={16} y={31} width={14} height={14} rx={1.5} fill={C.grey2} stroke="none" />
      <rect x={16} y={46} width={14} height={14} rx={1.5} fill={C.grey3} stroke="none" />
      <path d="M31 23 H37 M31 38 H37 M31 53 H37" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <RowBar x={38} y={20.5} w={40} h={5} fill={C.grey3} />
      <RowBar x={38} y={20.5} w={28} h={5} fill={a.base} />
      <RowBar x={38} y={35.5} w={40} h={5} fill={C.grey3} />
      <RowBar x={38} y={35.5} w={16} h={5} fill={a.base} />
      <RowBar x={38} y={50.5} w={40} h={5} fill={C.grey3} />
      <RowBar x={38} y={50.5} w={34} h={5} fill={a.base} />
      <path d="M80 53 H86" stroke={C.red} strokeWidth={1.6} strokeDasharray="2.5 2" fill="none" />
      <rect x={88} y={46} width={16} height={14} rx={2} fill={C.white} stroke={C.red} strokeWidth={1.8} />
      <RowBar x={92} y={51} w={8} h={3.4} fill={C.red} />
      <Stamp cx={96} cy={24} r={9} color={C.green} />
    </>
  ),

  // Bill the monthly draw with holdback and a declaration (CA): the draw splits
  // into four numbers, the holdback piles up as a balance, the package is sworn.
  'bill-the-monthly-draw-with-holdback-and-a-declaration': (a) => (
    <>
      <rect x={16} y={16} width={22} height={9} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={39} y={16} width={18} height={9} rx={1.5} fill={C.grey2} stroke="none" />
      <rect x={58} y={16} width={20} height={9} rx={1.5} fill={a.base} stroke="none" />
      <rect x={79} y={16} width={11} height={9} rx={1.5} fill={C.red} stroke="none" />
      <path d="M84.5 25 V36" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2.5" fill="none" />
      <rect x={79} y={56} width={12} height={8} rx={1.5} fill={C.pink} stroke="none" />
      <rect x={79} y={47} width={12} height={8} rx={1.5} fill={C.pink} stroke="none" />
      <rect x={79} y={38} width={12} height={8} rx={1.5} fill={C.red} stroke="none" />
      <Sheet x={16} y={36} w={52} h={34} />
      <RowBar x={22} y={44} w={28} h={3.2} fill={C.grey3} />
      <RowBar x={22} y={51} w={22} h={3.2} fill={C.grey3} />
      <Signature x={24} y={64} w={28} color={a.base} />
    </>
  ),

  // Build a 4D construction sequence: the model grows step by step along the
  // programme, and the whole thing plays back as one sequence.
  'build-a-4d-construction-sequence': (a) => (
    <>
      <Cube cx={26} ty={28} w={9} hh={4.5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={52} ty={28} w={9} hh={4.5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={52} ty={18} w={9} hh={4.5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={78} ty={28} w={9} hh={4.5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={78} ty={18} w={9} hh={4.5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={96} ty={28} w={9} hh={4.5} depth={10} top={C.grey3} left={C.grey2} right={C.grey1} />
      <path d="M16 62 H104" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path d="M26 59 V65 M52 59 V65 M82 59 V65" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <path d="M16 64 l7 4.5 l-7 4.5 z" fill={a.base} stroke="none" />
    </>
  ),

  // Build a comprehensive unit rate under GB 50500 (CN): pick the item out of
  // the coded bill, compose the rate from its parts, validate before issue.
  'build-a-comprehensive-unit-rate-under-gb-50500': (a) => (
    <>
      <Sheet x={13} y={12} w={44} h={52} />
      <HeaderBand x={13} y={12} w={44} h={9} fill={a.base} />
      <rect x={18} y={26} width={6} height={5} rx={1} fill={a.base} stroke="none" />
      <RowBar x={27} y={26.3} w={22} h={4} fill={C.grey3} />
      <rect x={17} y={33.5} width={36} height={8} rx={2} fill={C.highlight} stroke="none" />
      <rect x={22} y={35} width={6} height={5} rx={1} fill={a.light} stroke="none" />
      <RowBar x={31} y={35.3} w={18} h={4} fill={C.grey2} />
      <rect x={22} y={44} width={6} height={5} rx={1} fill={a.light} stroke="none" />
      <RowBar x={31} y={44.3} w={16} h={4} fill={C.grey3} />
      <path
        d="M60 42 H68 M64.5 38.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.grey1}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={72} y={38} width={10} height={8} rx={1.5} fill={C.grey2} stroke="none" />
      <rect x={83} y={38} width={9} height={8} rx={1.5} fill={C.grey3} stroke="none" />
      <rect x={93} y={38} width={6} height={8} rx={1.5} fill={C.ochre} stroke="none" />
      <rect x={100} y={38} width={5} height={8} rx={1.5} fill={a.base} stroke="none" />
      <Shield cx={88} ty={54} w={13} h={15} fill={C.green} />
    </>
  ),

  // Build a milestone payment schedule: payment tied to programme events, each
  // one valued, the whole schedule read back as a cash flow.
  'build-a-milestone-payment-schedule': (a) => (
    <>
      <path d="M16 62 H104" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <Bar x={24} baseY={54} w={9} h={12} fill={C.grey2} />
      <Bar x={46} baseY={54} w={9} h={18} fill={C.grey2} />
      <Bar x={68} baseY={54} w={9} h={14} fill={C.grey2} />
      <Bar x={90} baseY={54} w={9} h={22} fill={C.grey2} />
      <path
        d="M28 58 l5 4 l-5 4 l-5 -4 z M50 58 l5 4 l-5 4 l-5 -4 z M72 58 l5 4 l-5 4 l-5 -4 z M94 58 l5 4 l-5 4 l-5 -4 z"
        fill={a.base}
        stroke="none"
      />
      <path
        d="M20 30 C40 30 52 22 72 18 S92 15 100 14"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={100} cy={14} r={3} fill={a.base} stroke={C.white} strokeWidth={1} />
    </>
  ),

  // Build a parametric assembly: one named parameter is entered, and the
  // component quantities behind it are recomputed from formulas over it.
  'build-a-parametric-assembly': (a) => (
    <>
      <Sheet x={14} y={16} w={32} h={20} />
      <RowBar x={20} y={21} w={14} h={3} fill={C.grey3} />
      <path d="M20 30 H40" stroke={C.grey2} strokeWidth={3} fill="none" strokeLinecap="round" />
      <circle cx={33} cy={30} r={4} fill={a.base} stroke={C.white} strokeWidth={1.2} />
      <path d="M30 36 V44" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <rect x={22} y={44} width={16} height={12} rx={3} fill={a.light} stroke={a.base} strokeWidth={2} />
      <circle cx={30} cy={50} r={2.4} fill={a.base} stroke="none" />
      <path
        d="M38 50 H48 M48 32.5 V66.5 M48 32.5 H58 M48 50 H58 M48 66.5 H58"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <RowBar x={58} y={30} w={34} h={5} fill={C.grey2} />
      <RowBar x={58} y={47.5} w={24} h={5} fill={C.grey2} />
      <RowBar x={58} y={64} w={40} h={5} fill={C.grey2} />
    </>
  ),

  // Build a precio descompuesto (ES): the partida breaks down into resources,
  // and the auxiliary price in the middle breaks down again below it.
  'build-a-precio-descompuesto': (a) => (
    <>
      <Sheet x={38} y={10} w={44} h={14} />
      <RowBar x={44} y={15} w={22} h={4} fill={C.grey3} />
      <rect x={70} y={14} width={8} height={6} rx={1.5} fill={C.grey2} stroke="none" />
      <path
        d="M60 24 V30 M28 30 H92 M28 30 V36 M60 30 V36 M92 30 V36"
        stroke={C.grey1}
        strokeWidth={1.4}
        fill="none"
        strokeLinecap="round"
      />
      <rect x={18} y={36} width={20} height={12} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <rect x={50} y={36} width={20} height={12} rx={3} fill={a.light} stroke={a.base} strokeWidth={2} />
      <rect x={82} y={36} width={20} height={12} rx={3} fill={C.white} stroke={C.grey1} strokeWidth={1.6} />
      <path
        d="M60 48 V54 M50 54 H70 M50 54 V60 M70 54 V60"
        stroke={a.base}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
      <Chip x={44} y={60} w={13} h={8} r={2} fill={C.grey2} />
      <Chip x={64} y={60} w={13} h={8} r={2} fill={C.grey2} />
    </>
  ),

  // Build a Preisspiegel and award (DE): the offers stand side by side against
  // the same positions in one mirror table, and one column is awarded.
  'build-a-preisspiegel-and-award': (a) => (
    <>
      <Sheet x={14} y={14} w={72} h={48} />
      <HeaderBand x={14} y={14} w={72} h={9} fill={C.grey1} />
      <rect x={66} y={26} width={17} height={30} rx={2} fill={C.highlight} stroke="none" />
      <RowBar x={20} y={30} w={12} h={3.4} fill={C.grey3} />
      <RowBar x={20} y={40} w={12} h={3.4} fill={C.grey3} />
      <RowBar x={20} y={50} w={12} h={3.4} fill={C.grey3} />
      <RowBar x={38} y={30} w={12} h={3.4} fill={C.grey2} />
      <RowBar x={38} y={40} w={9} h={3.4} fill={C.grey2} />
      <RowBar x={38} y={50} w={11} h={3.4} fill={C.grey2} />
      <RowBar x={52} y={30} w={10} h={3.4} fill={C.grey2} />
      <RowBar x={52} y={40} w={12} h={3.4} fill={C.grey2} />
      <RowBar x={52} y={50} w={8} h={3.4} fill={C.grey2} />
      <RowBar x={68} y={30} w={11} h={3.4} fill={a.base} />
      <RowBar x={68} y={40} w={10} h={3.4} fill={a.base} />
      <RowBar x={68} y={50} w={12} h={3.4} fill={a.base} />
      <Stamp cx={98} cy={38} r={9} color={C.green} />
    </>
  ),

  // Build an all-in labour rate: the wage and its on-costs stack up, divided by
  // the hours that are actually productive, and that is the rate.
  'build-an-all-in-labour-rate': (a) => (
    <>
      <rect x={16} y={46} width={16} height={18} rx={1.5} fill={C.grey1} stroke="none" />
      <rect x={16} y={36} width={16} height={9} rx={1.5} fill={C.grey2} stroke="none" />
      <rect x={16} y={27} width={16} height={8} rx={1.5} fill={C.grey3} stroke="none" />
      <path d="M38 42 H46" stroke={C.grey1} strokeWidth={2.2} fill="none" strokeLinecap="round" />
      <circle cx={42} cy={36.5} r={1.8} fill={C.grey1} stroke="none" />
      <circle cx={42} cy={47.5} r={1.8} fill={C.grey1} stroke="none" />
      <circle cx={58} cy={42} r={9} fill={C.white} stroke={C.grey1} strokeWidth={2} />
      <path
        d="M58 36 V42 L63 45"
        stroke={C.grey1}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M72 38 H80 M72 46 H80"
        stroke={C.grey1}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
      />
      <rect x={84} y={34} width={20} height={16} rx={3} fill={a.base} stroke={C.white} strokeWidth={1} />
      <RowBar x={88} y={40.5} w={12} h={3.4} fill={C.white} opacity={0.85} />
    </>
  ),

  // Build an all-in labour rate with the Canadian burden (CA): each statutory
  // contribution is its own named line, and each line says where it came from.
  'build-an-all-in-labour-rate-with-the-canadian-burden': (a) => (
    <>
      <Sheet x={14} y={12} w={54} h={54} />
      <HeaderBand x={14} y={12} w={54} h={9} fill={a.base} />
      <rect x={20} y={26} width={5} height={5} rx={1} fill={C.grey1} stroke="none" />
      <RowBar x={28} y={26.2} w={30} h={4.4} fill={C.grey3} />
      <rect x={20} y={35} width={5} height={5} rx={1} fill={C.grey2} stroke="none" />
      <RowBar x={28} y={35.2} w={22} h={4.4} fill={C.grey3} />
      <rect x={20} y={44} width={5} height={5} rx={1} fill={C.ochre} stroke="none" />
      <RowBar x={28} y={44.2} w={26} h={4.4} fill={C.grey3} />
      <path d="M20 54 H62" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={28} y={57} w={30} h={5} fill={a.base} />
      <Sheet x={76} y={20} w={28} h={26} />
      <rect x={80} y={25} width={20} height={4} rx={1} fill={C.grey2} stroke="none" />
      <RowBar x={80} y={34} w={14} h={3} fill={C.grey3} />
      <path
        d="M74 33 H68 M71 30 l-3 3 l3 3"
        stroke={C.grey1}
        strokeWidth={1.6}
        strokeDasharray="2.5 2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Calculate with your own EFB rates (DE): the crew blends into one average
  // wage, and the material and plant rates stay your own master data beside it.
  'calculate-with-your-own-efb-rates': (a) => (
    <>
      <circle cx={22} cy={17} r={4} fill={C.grey1} stroke="none" />
      <path d="M15 29 c0 -6 3 -9 7 -9 s7 3 7 9 z" fill={C.grey1} stroke="none" />
      <circle cx={22} cy={37} r={4} fill={C.grey2} stroke="none" />
      <path d="M15 49 c0 -6 3 -9 7 -9 s7 3 7 9 z" fill={C.grey2} stroke="none" />
      <circle cx={22} cy={57} r={4} fill={C.grey1} stroke="none" />
      <path d="M15 69 c0 -6 3 -9 7 -9 s7 3 7 9 z" fill={C.grey1} stroke="none" />
      <path
        d="M31 25 H44 M31 45 H44 M31 65 H44 M44 25 V65 M44 45 H54"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M51 42 l3 3 l-3 3"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={56} y={37} width={22} height={16} rx={3} fill={a.base} stroke={C.white} strokeWidth={1} />
      <RowBar x={60} y={43.5} w={14} h={3.4} fill={C.white} opacity={0.85} />
      <path d="M80 45 H86" stroke={C.grey1} strokeWidth={1.6} strokeDasharray="2.5 2" fill="none" />
      <Cube cx={95} ty={36} w={9} hh={4.5} depth={11} top={C.grey3} left={C.grey2} right={C.grey1} />
    </>
  ),
};
