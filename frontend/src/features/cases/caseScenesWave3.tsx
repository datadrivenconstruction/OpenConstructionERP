// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - bespoke line-art scenes, wave 3.
//
// Nineteen more cases that used to fall back to a lone centred glyph, drawn in
// exactly the language of `caseScenes.tsx`: the shared `0 0 120 84` viewBox, the
// blueprint grid supplied by the frame, the fixed `C` palette for structure and
// the category accent ramp for the one shape that carries the case's meaning.
//
// This wave covers the bill interchange formats (FIEBDC-3, GAEB, XRechnung and
// the Spanish reverse charge), model federation and the golden thread, the three
// kinds of site record that must not be confused with one another (the German
// diary, the claim-grade daily report and the Spanish order book), the three
// distinct flavours of bid levelling, and the documents that get signed, based
// or handed over.
//
// No <text> anywhere: these ship in every locale we support, so meaning is
// carried by shape, arrangement and colour instead of letterforms. That rules
// out `Chip`'s labelled form, which is why chips here are pure colour cells.

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

/** Bespoke case illustrations for wave 3, keyed by case id. */
export const CASE_SCENES_WAVE3: Record<string, Scene> = {
  // Send a bill to Spain in FIEBDC-3: the bill leaves in the exchange container
  // and comes back matching, which is what proving the round trip means.
  'export-a-boq-to-fiebdc3': (a) => (
    <>
      <Sheet x={12} y={12} w={32} h={42} />
      <HeaderBand x={12} y={12} w={32} h={9} fill={a.base} />
      <RowBar x={18} y={15.5} w={14} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={18} y={27} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={18} y={35} w={16} h={3.2} fill={C.grey3} />
      <RowBar x={18} y={43} w={18} h={3.2} fill={C.grey3} />
      <path
        d="M46 26 H58 M54 22 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={60} y={12} w={32} h={42} />
      <HeaderBand x={60} y={12} w={32} h={9} fill={a.deep} />
      <RowBar x={66} y={15.5} w={14} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={66} y={27} w={20} h={3.2} fill={a.light} />
      <RowBar x={66} y={35} w={16} h={3.2} fill={a.light} />
      <RowBar x={66} y={43} w={18} h={3.2} fill={a.light} />
      <path
        d="M76 54 V65 H63"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M49 65 H28 V54 M24 58 l4 -4 l4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={56} cy={65} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Federate discipline models: three separately authored volumes converge into
  // one combined model, and the review that follows raises its first issue.
  'federate-discipline-models-for-coordination': (a) => (
    <>
      <Cube cx={25} ty={12} w={10} hh={5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={25} ty={32} w={10} hh={5} depth={10} top={C.grey3} left={C.grey2} right={C.grey1} />
      <Cube cx={25} ty={52} w={10} hh={5} depth={10} top={C.amber} left={C.ochre} right={C.ochre} />
      <path
        d="M38 22 C48 22 48 42 56 42"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M38 42 H56 M52 38 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M38 62 C48 62 48 42 56 42"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <Cube cx={82} ty={22} w={18} hh={9} depth={20} top={a.light} left={a.base} right={a.deep} />
      <Badge cx={98} cy={30} r={6} fill={C.amber} glyph="warn" />
    </>
  ),

  // Get a key document signed off: one document, several attestations collected
  // in a session, sealed into a manifest that is the record afterwards.
  'get-a-key-document-signed-off': (a) => (
    <>
      <Sheet x={24} y={12} w={52} h={52} />
      <HeaderBand x={24} y={12} w={52} h={10} fill={a.base} />
      <RowBar x={30} y={16} w={22} h={3} fill={C.white} opacity={0.9} />
      <Signature x={32} y={32} w={20} color={a.base} />
      <Badge cx={64} cy={31} r={4} fill={C.green} glyph="check" shadow={false} />
      <Signature x={32} y={44} w={20} color={a.base} />
      <Badge cx={64} cy={43} r={4} fill={C.green} glyph="check" shadow={false} />
      <Signature x={32} y={56} w={20} color={a.base} />
      <Badge cx={64} cy={55} r={4} fill={C.green} glyph="check" shadow={false} />
      <Stamp cx={92} cy={44} r={9} color={a.deep} />
    </>
  ),

  // Get paid on time on a private job: bill the milestone, run the clock the law
  // gives you, and see which payers actually keep to it.
  'get-paid-on-time-on-a-private-job': (a) => (
    <>
      <Sheet x={12} y={14} w={34} h={44} />
      <HeaderBand x={12} y={14} w={34} h={9} fill={a.base} />
      <RowBar x={18} y={17.5} w={16} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={18} y={28} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={18} y={36} w={16} h={3.2} fill={C.grey3} />
      <path d="M18 44 H40" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={18} y={47} w={18} h={4} fill={a.deep} />
      <circle cx={62} cy={30} r={11} fill={C.white} stroke={a.base} strokeWidth={2.2} />
      <path
        d="M62 30 V22 M62 30 h6"
        stroke={a.deep}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <circle cx={62} cy={30} r={1.6} fill={a.deep} stroke="none" />
      <path d="M74 66 H106" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={76} baseY={66} w={8} h={14} fill={C.green} />
      <Bar x={87} baseY={66} w={8} h={22} fill={C.amber} />
      <Bar x={98} baseY={66} w={8} h={32} fill={C.red} />
    </>
  ),

  // Hand over a COBie facility export: the asset register becomes the tabbed
  // workbook of rows and columns the operator is entitled to receive.
  'hand-over-a-cobie-facility-export': (a) => (
    <>
      <Cube cx={24} ty={18} w={9} hh={4.5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <Cube cx={24} ty={42} w={9} hh={4.5} depth={10} top={a.light} left={a.base} right={a.deep} />
      <path
        d="M34 40 H42 M38 36 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={46} y={10} width={12} height={6} rx={2} fill={a.light} stroke="none" />
      <rect x={59} y={10} width={12} height={6} rx={2} fill={C.grey3} stroke="none" />
      <rect x={72} y={10} width={12} height={6} rx={2} fill={C.grey3} stroke="none" />
      <Sheet x={46} y={16} w={42} h={42} r={2} />
      <HeaderBand x={46} y={16} w={42} h={7} r={2} fill={a.base} />
      <path d="M56 23 V58 M66 23 V58 M76 23 V58" stroke={C.grey2} strokeWidth={1} fill="none" />
      <path d="M46 31 H88 M46 39 H88 M46 47 H88" stroke={C.grey2} strokeWidth={1} fill="none" />
      <Badge cx={98} cy={38} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Hold the design estimate to the approved budget: the approved number is a
  // stamped ceiling, and every gate re-tests the estimate against it.
  'hold-the-design-estimate-to-the-approved-budget': (a) => (
    <>
      <path d="M18 26 H102" stroke={C.green} strokeWidth={2.4} fill="none" strokeLinecap="round" />
      <Stamp cx={26} cy={17} r={7} color={C.green} />
      <path
        d="M46 26 V68 M68 26 V68 M90 26 V68"
        stroke={C.grey2}
        strokeWidth={1.2}
        strokeDasharray="2 3"
        fill="none"
      />
      <path
        d="M22 58 H46 V46 H68 V52 H90 V40 H92"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={46} cy={46} r={2.6} fill={a.deep} stroke="none" />
      <circle cx={68} cy={52} r={2.6} fill={a.deep} stroke="none" />
      <circle cx={90} cy={40} r={2.6} fill={a.deep} stroke="none" />
      <Badge cx={99} cy={40} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Import a GAEB tender into a priced BOQ: the structured positions arrive
  // empty, and the job is filling the rate column until nothing is blank.
  'import-a-gaeb-tender-into-a-priced-boq': (a) => (
    <>
      <Sheet x={12} y={24} w={24} h={30} r={3} fill={C.panel} />
      <path
        d="M19 31 V47 M19 35 H28 M19 41 H28 M19 47 H28"
        stroke={C.grey1}
        strokeWidth={1.4}
        fill="none"
      />
      <path
        d="M40 39 H50 M46 35 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={52} y={12} w={54} h={52} />
      <HeaderBand x={52} y={12} w={54} h={10} fill={a.base} />
      <RowBar x={58} y={16} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={58} y={28} w={22} h={3.2} fill={C.grey3} />
      <RowBar x={86} y={28} w={14} h={3.4} fill={a.base} />
      <RowBar x={58} y={37} w={18} h={3.2} fill={C.grey3} />
      <RowBar x={86} y={37} w={11} h={3.4} fill={a.base} />
      <RowBar x={58} y={46} w={20} h={3.2} fill={C.grey3} />
      <rect
        x={85}
        y={44}
        width={16}
        height={6}
        rx={2}
        fill="none"
        stroke={C.grey2}
        strokeWidth={1.2}
        strokeDasharray="2 2"
      />
      <path d="M58 55 H100" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={58} y={58} w={20} h={4} fill={a.deep} />
    </>
  ),

  // Import a programme and set the baseline: the imported bars each get a frozen
  // copy underneath them, and the baseline is planted on the plan.
  'import-a-programme-and-set-the-baseline': (a) => (
    <>
      <Sheet x={12} y={26} w={20} h={26} r={3} fill={C.panel} />
      <RowBar x={16} y={34} w={12} h={2.6} fill={C.grey2} />
      <RowBar x={19} y={41} w={9} h={2.6} fill={C.grey2} />
      <path
        d="M36 39 H44 M40 35 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={46} y={12} w={58} h={52} />
      <HeaderBand x={46} y={12} w={58} h={9} fill={a.base} />
      <RowBar x={52} y={15.5} w={18} h={3} fill={C.white} opacity={0.9} />
      <rect x={52} y={26} width={22} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={52} y={32} width={22} height={2.6} rx={1.3} fill={C.grey3} stroke="none" />
      <rect x={64} y={40} width={26} height={5} rx={2.5} fill={a.base} stroke="none" />
      <rect x={64} y={46} width={26} height={2.6} rx={1.3} fill={C.grey3} stroke="none" />
      <path d="M96 22 V58" stroke={C.ochre} strokeWidth={2.2} fill="none" strokeLinecap="round" />
      <path d="M96 22 h9 l-3 4 l3 4 h-9 z" fill={C.ochre} stroke="none" />
    </>
  ),

  // Invoice under inversion del sujeto pasivo: the tax comes off the seller's
  // invoice and the duty to account for it travels across to the buyer.
  'invoice-with-inversion-del-sujeto-pasivo': (a) => (
    <>
      <Sheet x={12} y={14} w={40} h={46} />
      <HeaderBand x={12} y={14} w={40} h={9} fill={a.base} />
      <RowBar x={18} y={17.5} w={18} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={18} y={30} w={24} h={3.2} fill={C.grey3} />
      <path d="M18 40 H46" stroke={C.grey1} strokeWidth={1} fill="none" />
      <RowBar x={18} y={44} w={18} h={3.4} fill={C.grey3} />
      <path d="M16 45.7 H40" stroke={C.red} strokeWidth={2} fill="none" strokeLinecap="round" />
      <Badge cx={45} cy={45.7} r={4.4} fill={C.red} glyph="x" shadow={false} />
      <circle cx={72} cy={30} r={6} fill={C.grey2} stroke="none" />
      <circle cx={98} cy={30} r={6} fill={C.grey2} stroke="none" />
      <path
        d="M72 22 C72 12 98 12 98 22"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M94 18 l4 4 l4 -4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={98} cy={48} r={7} fill={C.green} glyph="check" />
    </>
  ),

  // Issue a compliant XRechnung: both party blocks completed, then the schema
  // check driven green before the XML is allowed out.
  'issue-a-compliant-xrechnung': (a) => (
    <>
      <Sheet x={12} y={12} w={40} h={48} />
      <HeaderBand x={12} y={12} w={40} h={9} fill={a.base} />
      <RowBar x={18} y={15.5} w={18} h={3} fill={C.white} opacity={0.9} />
      <rect
        x={18}
        y={26}
        width={14}
        height={11}
        rx={2}
        fill={C.panel}
        stroke={C.grey2}
        strokeWidth={1.2}
      />
      <rect
        x={34}
        y={26}
        width={14}
        height={11}
        rx={2}
        fill={C.panel}
        stroke={C.grey2}
        strokeWidth={1.2}
      />
      <path d="M21 31.5 h8 M37 31.5 h8" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <RowBar x={18} y={43} w={22} h={3} fill={C.grey3} />
      <RowBar x={18} y={50} w={18} h={3} fill={C.grey3} />
      <Shield cx={70} ty={24} w={22} h={30} fill={C.green} />
      <path
        d="M64 37 l4 4 l8 -9"
        stroke={C.white}
        strokeWidth={2.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={86} y={26} w={20} h={26} r={3} />
      <path
        d="M96 32 V42 M92 38 l4 4 l4 -4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Issue a tender addendum and reissue: one extra page joins the pack, goes out
  // to every bidder at once, and each return receipt is chased down.
  'issue-a-tender-addendum-and-reissue': (a) => (
    <>
      <Sheet x={12} y={22} w={32} h={40} />
      <RowBar x={17} y={52} w={20} h={3} fill={C.grey3} />
      <RowBar x={17} y={57} w={16} h={3} fill={C.grey3} />
      <Sheet x={24} y={12} w={32} h={38} />
      <HeaderBand x={24} y={12} w={32} h={9} fill={a.base} />
      <RowBar x={30} y={15.5} w={16} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={30} y={30} w={18} h={3} fill={C.grey3} />
      <path
        d="M60 41 C70 41 72 20 80 20"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <path d="M60 41 H80" stroke={a.base} strokeWidth={1.8} fill="none" strokeLinecap="round" />
      <path
        d="M60 41 C70 41 72 62 80 62"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <Sheet x={82} y={12} w={22} h={16} r={2} />
      <Sheet x={82} y={33} w={22} h={16} r={2} />
      <Sheet x={82} y={54} w={22} h={16} r={2} />
      <Badge cx={100} cy={20} r={4} fill={C.green} glyph="check" shadow={false} />
      <Badge cx={100} cy={41} r={4} fill={C.green} glyph="check" shadow={false} />
      <Badge cx={100} cy={62} r={4} fill={C.green} glyph="check" shadow={false} />
    </>
  ),

  // Keep a court-proof Bautagebuch: the day written while it happens, with the
  // weather from outside your own hand, then closed under a seal.
  'keep-a-court-proof-bautagebuch': (a) => (
    <>
      <rect x={26} y={14} width={48} height={54} rx={4} fill={C.grey3} stroke="none" />
      <rect x={42} y={11} width={16} height={7} rx={2.5} fill={C.grey1} stroke="none" />
      <Sheet x={30} y={18} w={40} h={46} r={2} shadow={false} />
      <path
        d="M35 30 a4.5 4.5 0 0 1 4.5 -4.5 a6 6 0 0 1 11 1.5 a3.5 3.5 0 0 1 -0.5 7 H39 a4 4 0 0 1 -4 -4 z"
        fill={C.grey2}
        stroke="none"
      />
      <path
        d="M40 36 l-1.5 4 M45 36 l-1.5 4 M50 36 l-1.5 4"
        stroke={C.blueLight}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <RowBar x={36} y={45} w={16} h={3} fill={C.grey3} />
      <Chip x={56} y={43.5} w={9} h={6} fill={a.base} />
      <RowBar x={36} y={53} w={12} h={3} fill={C.grey3} />
      <Chip x={56} y={51.5} w={9} h={6} fill={a.light} />
      <Signature x={36} y={61} w={20} color={C.blueDeep} />
      <circle
        cx={90}
        cy={42}
        r={13}
        fill="none"
        stroke={C.blueDeep}
        strokeWidth={1.2}
        strokeDasharray="2 3"
      />
      <Stamp cx={90} cy={42} r={9} color={C.blueDeep} />
    </>
  ),

  // Keep a daily report that survives a claim: no day left without an answer,
  // plant in three states, and the run of days bound to the event it proves.
  'keep-a-daily-report-that-survives-a-claim': (a) => (
    <>
      <Sheet x={12} y={14} w={52} h={50} />
      <HeaderBand x={12} y={14} w={52} h={9} fill={a.base} />
      <RowBar x={18} y={17.5} w={18} h={3} fill={C.white} opacity={0.9} />
      <path
        d="M18 28 h9 v9 h-9 z M29 28 h9 v9 h-9 z M51 28 h9 v9 h-9 z M18 40 h9 v9 h-9 z M40 40 h9 v9 h-9 z M51 40 h9 v9 h-9 z"
        fill={a.light}
        stroke="none"
      />
      <path d="M40 28 h9 v9 h-9 z M29 40 h9 v9 h-9 z" fill={a.base} stroke="none" />
      <circle cx={20} cy={56} r={3.2} fill={C.green} stroke="none" />
      <circle cx={31} cy={56} r={3.2} fill={C.amber} stroke="none" />
      <circle cx={42} cy={56} r={3.2} fill={C.red} stroke="none" />
      <path
        d="M68 38 a4 4 0 0 0 0 8 h4 M80 46 a4 4 0 0 0 0 -8 h-4 M70 42 h8"
        stroke={C.grey1}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M86 26 h9 l3 4 h10 v26 h-22 z"
        fill={C.panel}
        stroke={C.grey1}
        strokeWidth={1.6}
        strokeLinejoin="round"
      />
      <RowBar x={90} y={38} w={14} h={3} fill={C.grey2} />
      <RowBar x={90} y={45} w={11} h={3} fill={C.grey2} />
      <WarnTri cx={97} cy={64} w={12} fill={C.amber} />
    </>
  ),

  // Keep changes, site confirmations and claims apart: one event on the day, then
  // three different instruments - priced, signed but unpriced, or noticed.
  'keep-changes-site-confirmations-and-claims-apart': (a) => (
    <>
      <Sheet x={12} y={32} w={26} h={22} r={3} fill={C.highlight} stroke={C.amber} />
      <RowBar x={17} y={40} w={16} h={2.8} fill={C.amber} />
      <path
        d="M42 43 C50 43 50 19 58 19"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <path d="M42 43 H58" stroke={a.base} strokeWidth={1.8} fill="none" strokeLinecap="round" />
      <path
        d="M42 43 C50 43 50 62 58 62"
        stroke={a.base}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
      />
      <Sheet x={60} y={10} w={46} h={18} r={3} />
      <Chip x={65} y={16} w={9} h={6} fill={a.base} />
      <RowBar x={78} y={17.5} w={12} h={3} fill={C.grey3} />
      <RowBar x={93} y={17} w={10} h={4} fill={C.green} />
      <Sheet x={60} y={32} w={46} h={18} r={3} />
      <Signature x={65} y={44} w={20} color={a.base} />
      <rect
        x={92}
        y={38}
        width={11}
        height={5}
        rx={2.5}
        fill="none"
        stroke={C.grey2}
        strokeWidth={1.2}
        strokeDasharray="2 2"
      />
      <Sheet x={60} y={54} w={46} h={16} r={3} />
      <WarnTri cx={69} cy={62} w={12} fill={C.amber} />
      <RowBar x={79} y={60.5} w={11} h={3} fill={C.grey3} />
      <path
        d="M97 60 V68"
        stroke={C.red}
        strokeWidth={1.4}
        strokeDasharray="2 2"
        fill="none"
      />
      <path d="M97 60 l-3 -5 h6 z" fill={C.red} stroke="none" />
    </>
  ),

  // Keep the golden thread on a higher-risk building: one unbroken run of
  // information from the building itself into the register that will be read.
  'keep-the-golden-thread-on-a-higher-risk-building': (a) => (
    <>
      <rect x={18} y={12} width={32} height={58} rx={2} fill={a.base} stroke="none" />
      <path
        d="M18 26 H50 M18 38 H50 M18 50 H50 M18 62 H50"
        stroke={C.white}
        strokeWidth={1.2}
        opacity={0.45}
        fill="none"
      />
      <path
        d="M23 17 h6 v5 h-6 z M39 17 h6 v5 h-6 z M23 30 h6 v5 h-6 z M39 30 h6 v5 h-6 z M23 42 h6 v5 h-6 z M39 42 h6 v5 h-6 z"
        fill={a.light}
        opacity={0.6}
        stroke="none"
      />
      <path
        d="M34 16 C25 22 43 28 34 34 C25 40 43 46 34 52 C29 58 40 62 48 63 H70"
        stroke={C.ochre}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
      />
      <Sheet x={70} y={26} w={36} h={40} />
      <HeaderBand x={70} y={26} w={36} h={9} fill={a.deep} />
      <RowBar x={75} y={29.5} w={16} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={75} y={42} w={15} h={3} fill={C.grey3} />
      <Chip x={93} y={40.5} w={9} h={6} fill={C.green} />
      <RowBar x={75} y={52} w={12} h={3} fill={C.grey3} />
      <Chip x={93} y={50.5} w={9} h={6} fill={C.amber} />
    </>
  ),

  // Keep the libro de ordenes on site: the visit is opened, each order is written
  // as the kind of thing it is, and the ones that change the work get priced.
  'keep-the-libro-de-ordenes-on-site': (a) => (
    <>
      <path
        d="M14 20 C22 17 32 17 39 21 V62 C32 58 22 58 14 61 Z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
        strokeLinejoin="round"
      />
      <path
        d="M39 21 C46 17 56 17 64 20 V61 C56 58 46 58 39 62 Z"
        fill={C.white}
        stroke={C.grey1}
        strokeWidth={1.6}
        strokeLinejoin="round"
      />
      <path d="M39 21 V62" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <RowBar x={19} y={34} w={13} h={2.8} fill={C.grey2} />
      <Chip x={44} y={28} w={7} h={5.5} fill={a.base} />
      <RowBar x={53} y={29.5} w={8} h={2.8} fill={C.grey3} />
      <Chip x={44} y={38} w={7} h={5.5} fill={C.green} />
      <RowBar x={53} y={39.5} w={9} h={2.8} fill={C.grey3} />
      <Chip x={44} y={48} w={7} h={5.5} fill={C.red} />
      <RowBar x={53} y={49.5} w={7} h={2.8} fill={C.grey3} />
      <path
        d="M66 16 a4.6 4.6 0 0 1 9.2 0 c0 3.7 -4.6 8.6 -4.6 8.6 s-4.6 -4.9 -4.6 -8.6 z"
        fill={a.deep}
        stroke="none"
      />
      <circle cx={70.6} cy={16} r={1.8} fill={C.white} stroke="none" />
      <path
        d="M66 46 H76 M72 42 l4 4 l-4 4"
        stroke={a.base}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={78} y={30} w={28} h={34} />
      <HeaderBand x={78} y={30} w={28} h={8} fill={a.base} />
      <RowBar x={83} y={44} w={14} h={2.8} fill={C.grey3} />
      <RowBar x={83} y={53} w={12} h={3.6} fill={C.green} />
    </>
  ),

  // Level bids to a common scope: every offer set against the same rows, so the
  // holes in each one show up as holes rather than as a cheaper price.
  'level-bids-to-a-common-scope': (a) => (
    <>
      <Sheet x={12} y={14} w={26} h={50} />
      <HeaderBand x={12} y={14} w={26} h={8} fill={a.base} />
      <RowBar x={17} y={17} w={13} h={2.8} fill={C.white} opacity={0.9} />
      <RowBar x={17} y={30} w={16} h={3} fill={C.grey3} />
      <RowBar x={17} y={42} w={13} h={3} fill={C.grey3} />
      <RowBar x={17} y={54} w={15} h={3} fill={C.grey3} />
      <path
        d="M40 31.5 H104 M40 43.5 H104 M40 55.5 H104"
        stroke={C.grey3}
        strokeWidth={0.9}
        fill="none"
      />
      <rect x={48} y={14} width={16} height={50} rx={3} fill={C.panel} stroke={C.grey2} strokeWidth={1.2} />
      <rect x={68} y={14} width={16} height={50} rx={3} fill={C.panel} stroke={C.grey2} strokeWidth={1.2} />
      <rect x={88} y={14} width={16} height={50} rx={3} fill={C.panel} stroke={C.grey2} strokeWidth={1.2} />
      <path
        d="M51 29 h10 v5 h-10 z M51 41 h10 v5 h-10 z M71 29 h10 v5 h-10 z M71 53 h10 v5 h-10 z M91 29 h10 v5 h-10 z M91 41 h10 v5 h-10 z M91 53 h10 v5 h-10 z"
        fill={a.light}
        stroke="none"
      />
      <path
        d="M50 51 h12 v7 h-12 z M70 39 h12 v7 h-12 z"
        fill="none"
        stroke={C.grey1}
        strokeWidth={1.2}
        strokeDasharray="2 2"
      />
      <Badge cx={56} cy={54.5} r={3.6} fill={C.amber} glyph="plus" shadow={false} />
      <Badge cx={76} cy={42.5} r={3.6} fill={C.amber} glyph="plus" shadow={false} />
    </>
  ),

  // Level subcontract bids and flow the terms down: the terms of the contract
  // above are copied into the subcontract, and the winner's papers must be live
  // on the day you award.
  'level-subcontract-bids-and-flow-the-terms-down': (a) => (
    <>
      <Sheet x={26} y={10} w={48} h={26} r={3} />
      <HeaderBand x={26} y={10} w={48} h={8} r={3} fill={a.deep} />
      <RowBar x={31} y={23} w={18} h={3} fill={C.grey3} />
      <Chip x={54} y={21} w={14} h={6} fill={a.base} />
      <Chip x={54} y={29} w={14} h={5} fill={a.base} />
      <path
        d="M50 38 V46 M46 42 l4 4 l4 -4"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={26} y={48} w={48} h={22} r={3} />
      <HeaderBand x={26} y={48} w={48} h={7} r={3} fill={a.base} />
      <RowBar x={31} y={59.5} w={10} h={3} fill={C.grey3} />
      <Chip x={44} y={58} w={13} h={6} fill={a.base} />
      <Chip x={59} y={58} w={13} h={6} fill={a.base} />
      <Sheet x={80} y={20} w={26} h={30} r={3} />
      <HeaderBand x={80} y={20} w={26} h={7} r={3} fill={C.green} />
      <RowBar x={85} y={32} w={14} h={2.8} fill={C.grey3} />
      <path d="M99 38 V47" stroke={C.red} strokeWidth={1.4} strokeDasharray="2 2" fill="none" />
      <path d="M99 38 l-3 -5 h6 z" fill={C.red} stroke="none" />
      <Badge cx={94} cy={60} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Level the bids and buy out the job: bids arrive in whatever shape the subs
  // send them, get weighed on one basis, and the winner becomes a commitment.
  'level-the-bids-and-buy-out-the-job': (a) => (
    <>
      <Sheet x={12} y={14} w={22} h={26} r={2} shadow={false} />
      <Sheet x={16} y={22} w={22} h={26} r={2} shadow={false} />
      <Sheet x={20} y={30} w={22} h={26} r={2} />
      <RowBar x={25} y={38} w={12} h={2.6} fill={C.grey3} />
      <RowBar x={25} y={45} w={9} h={2.6} fill={C.grey3} />
      <path
        d="M48 34 H72 M60 34 V52 M54 52 H66"
        stroke={a.base}
        strokeWidth={2.4}
        fill="none"
        strokeLinecap="round"
      />
      <path d="M50 34 V39 M70 34 V39" stroke={a.base} strokeWidth={1.4} fill="none" />
      <path d="M46 39 h8 l-2 5 h-4 z M66 39 h8 l-2 5 h-4 z" fill={a.light} stroke="none" />
      <Cube cx={90} ty={24} w={14} hh={7} depth={16} top={a.light} left={a.base} right={a.deep} />
      <Badge cx={98} cy={60} r={7} fill={C.green} glyph="check" />
    </>
  ),
};
