// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - bespoke line-art scenes, wave 6.
//
// Eighteen more case ids that still fell back to a single generic icon get a
// drawn scene here, in exactly the same language as caseScenes.tsx: the shared
// `0 0 120 84` viewBox, the blueprint grid supplied by the wrapper, the fixed
// `C` palette for structure and the category accent ramp for the one element
// that carries the case's meaning.
//
// The wave covers site quality forms, two statutory payment clocks (Ontario and
// VOB/B), field marks on a drawing, contract setup and period settlement, German
// Soll-Ist control, the Spanish acta de replanteo, permit submission, three
// different takeoff cases, lien waivers, document-to-task, monthly valuation and
// certification, the Class D to Class A estimate ladder, a GAEB tender round
// trip and the basis of estimate.
//
// No <text> anywhere: these ship in every locale, so meaning is carried by shape
// and arrangement only, never by a letterform. That also rules out the `label`
// prop on Chip, which is the one primitive that would emit a glyph.

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

/**
 * Wave 6 of the bespoke case illustrations, keyed by case id. Merged into the
 * registry alongside CASE_SCENES, so the lookup and the fallback are unchanged.
 */
export const CASE_SCENES_WAVE6: Record<string, Scene> = {
  // Run site quality checks with digital forms: a tablet carrying the checklist,
  // two items passed, one failed and flagged on, a photo and the sign-off.
  'run-site-quality-checks-with-digital-forms': (a) => (
    <>
      <Sheet x={18} y={12} w={48} h={60} />
      <HeaderBand x={18} y={12} w={48} h={10} fill={a.base} />
      <RowBar x={24} y={16} w={22} h={3} fill={C.white} opacity={0.9} />
      <Badge cx={28} cy={32} r={4.4} fill={C.blueDeep} glyph="check" shadow={false} />
      <RowBar x={36} y={30.4} w={22} h={3.2} fill={C.grey3} />
      <Badge cx={28} cy={44} r={4.4} fill={C.blueDeep} glyph="check" shadow={false} />
      <RowBar x={36} y={42.4} w={18} h={3.2} fill={C.grey3} />
      <Badge cx={28} cy={56} r={4.4} fill={C.red} glyph="x" shadow={false} />
      <RowBar x={36} y={54.4} w={21} h={3.2} fill={C.grey3} />
      <Signature x={26} y={68} w={30} color={C.blueDeep} />
      <Sheet x={76} y={16} w={28} h={22} />
      <path d="M79 34 l6 -7 l4.5 4.5 l4 -4 l7.5 6.5 z" fill={C.grey2} stroke="none" />
      <WarnTri cx={90} cy={56} w={16} fill={C.amber} />
    </>
  ),

  // Run the Ontario prompt-payment clock down the chain: one statutory clock at
  // the top, then the same event stepping down tier by tier below it.
  'run-the-ontario-prompt-payment-clock-down-the-chain': (a) => (
    <>
      <circle cx={24} cy={22} r={11} fill={C.white} stroke={a.base} strokeWidth={2.4} />
      <path
        d="M24 15 V22 L29 25"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M37 22 H45 M41.5 18.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.grey1}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={48} y={15} width={40} height={13} rx={3} fill={C.blue} stroke="none" />
      <RowBar x={53} y={19.5} w={20} h={4} fill={C.white} opacity={0.85} />
      <path
        d="M56 28 V32 M52.5 29.5 l3.5 3.5 l3.5 -3.5"
        stroke={C.grey1}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={56} y={35} width={40} height={13} rx={3} fill={C.blueLight} stroke="none" />
      <RowBar x={61} y={39.5} w={17} h={4} fill={C.white} opacity={0.9} />
      <path
        d="M64 48 V52 M60.5 49.5 l3.5 3.5 l3.5 -3.5"
        stroke={C.grey1}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={64} y={55} width={40} height={13} rx={3} fill={C.grey2} stroke="none" />
      <RowBar x={69} y={59.5} w={14} h={4} fill={C.white} opacity={0.9} />
    </>
  ),

  // Run the VOB/B payment clock: one invoice, two regimes, and the deadline the
  // module counts is simply a longer run of days for the final account.
  'run-the-vob-payment-clock': (a) => (
    <>
      <Sheet x={14} y={14} w={36} h={44} />
      <HeaderBand x={14} y={14} w={36} h={9} fill={C.blue} />
      <RowBar x={19} y={28} w={20} h={3.2} fill={C.grey3} />
      <RowBar x={19} y={36} w={16} h={3.2} fill={C.grey3} />
      <RowBar x={19} y={46} w={24} h={3.6} fill={C.blueDeep} />
      <path d="M56 20 V64" stroke={C.grey1} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <rect x={56} y={26} width={26} height={7} rx={3.5} fill={a.base} stroke="none" />
      <path d="M82 30 V18" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path d="M82 18 h11 l-3 3.4 l3 3.4 h-11 z" fill={C.amber} stroke="none" />
      <rect x={56} y={48} width={38} height={7} rx={3.5} fill={a.deep} stroke="none" />
      <path d="M94 52 V40" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path d="M94 40 h11 l-3 3.4 l3 3.4 h-11 z" fill={C.amber} stroke="none" />
    </>
  ),

  // See every field mark on one sheet: one drawing carrying a markup, a
  // measurement and a photo, each on its own toggle, plus a pin just dropped.
  'see-every-field-mark-on-one-sheet': (a) => (
    <>
      <Sheet x={28} y={12} w={78} h={58} />
      <path
        d="M36 22 H98 V60 H36 Z M36 42 H66 M66 22 V60"
        stroke={C.grey2}
        strokeWidth={1.3}
        fill="none"
      />
      <path
        d="M44 30 c4 -5 8 5 12 0 c3 -3 6 2 9 0"
        stroke={C.red}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M42 54 H60 M42 51 V57 M60 51 V57"
        stroke={C.blueDeep}
        strokeWidth={1.4}
        fill="none"
      />
      <rect x={76} y={26} width={14} height={10} rx={1.5} fill={C.blueLight} stroke={C.white} strokeWidth={1.2} />
      <path
        d="M85 50 c-4.6 0 -7.8 3.2 -7.8 7.5 c0 5.4 7.8 11 7.8 11 s7.8 -5.6 7.8 -11 c0 -4.3 -3.2 -7.5 -7.8 -7.5 z"
        fill={a.base}
        stroke={C.white}
        strokeWidth={1.2}
      />
      <circle cx={85} cy={57} r={2.8} fill={C.white} stroke="none" />
      <rect x={12} y={24} width={14} height={7.5} rx={3.75} fill={C.red} stroke="none" />
      <circle cx={22.2} cy={27.75} r={2.6} fill={C.white} stroke="none" />
      <rect x={12} y={38} width={14} height={7.5} rx={3.75} fill={C.blueDeep} stroke="none" />
      <circle cx={22.2} cy={41.75} r={2.6} fill={C.white} stroke="none" />
      <rect x={12} y={52} width={14} height={7.5} rx={3.75} fill={C.grey2} stroke="none" />
      <circle cx={15.8} cy={55.75} r={2.6} fill={C.white} stroke="none" />
    </>
  ),

  // Set the project up on a JCT or NEC4 contract: two standard forms on the desk,
  // the one the job is really run under drawn, executed, and put on a clock.
  'set-the-project-up-on-a-jct-or-nec4-contract': (a) => (
    <>
      <Sheet x={14} y={20} w={32} h={42} />
      <HeaderBand x={14} y={20} w={32} h={9} fill={C.grey2} />
      <RowBar x={19} y={34} w={18} h={3.2} fill={C.grey3} />
      <RowBar x={19} y={42} w={14} h={3.2} fill={C.grey3} />
      <Sheet x={52} y={12} w={36} h={54} />
      <HeaderBand x={52} y={12} w={36} h={10} fill={a.base} />
      <RowBar x={58} y={16} w={20} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={58} y={30} w={23} h={3.2} fill={C.grey3} />
      <RowBar x={58} y={38} w={18} h={3.2} fill={C.grey3} />
      <Signature x={57} y={54} w={26} color={C.blueDeep} />
      <Stamp cx={92} cy={58} r={9} color={a.deep} />
      <circle cx={98} cy={24} r={8} fill={C.white} stroke={C.blue} strokeWidth={2.2} />
      <path
        d="M98 19 V24 L102 27"
        stroke={C.blue}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),

  // Settle a period in process and get it signed: the bill frozen as a named
  // version, and the statement carrying both parties' signatures.
  'settle-a-period-in-process-and-get-it-signed': (a) => (
    <>
      <Sheet x={26} y={10} w={58} h={54} />
      <HeaderBand x={26} y={10} w={58} h={10} fill={a.base} />
      <RowBar x={32} y={14} w={22} h={3} fill={C.white} opacity={0.9} />
      <RowBar x={32} y={28} w={26} h={3.2} fill={C.grey3} />
      <RowBar x={64} y={28} w={13} h={3.2} fill={C.blue} />
      <RowBar x={32} y={36} w={21} h={3.2} fill={C.grey3} />
      <RowBar x={64} y={36} w={13} h={3.2} fill={C.blue} />
      <path d="M32 45 H78" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Signature x={31} y={56} w={20} color={C.blueDeep} />
      <Signature x={59} y={56} w={20} color={C.blueDeep} />
      <path d="M30 61 H52 M58 61 H80" stroke={C.grey2} strokeWidth={1.2} fill="none" />
      <path d="M90 18 h14 v22 l-7 -5 l-7 5 z" fill={a.deep} stroke={C.white} strokeWidth={1.2} />
      <Badge cx={97} cy={56} r={8} fill={C.green} glyph="check" />
    </>
  ),

  // Soll-Ist control on a running site: each period's actual read against the
  // Soll behind it, up to the cut-off, with the rest of the job forecast.
  'soll-ist-control-on-a-running-site': (a) => (
    <>
      <path d="M18 66 H106" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <Bar x={24} baseY={66} w={14} h={30} fill={C.grey3} />
      <Bar x={27} baseY={66} w={8} h={24} fill={a.base} />
      <Bar x={46} baseY={66} w={14} h={38} fill={C.grey3} />
      <Bar x={49} baseY={66} w={8} h={44} fill={a.base} />
      <Bar x={68} baseY={66} w={14} h={32} fill={C.grey3} />
      <Bar x={71} baseY={66} w={8} h={28} fill={a.base} />
      <WarnTri cx={53} cy={16} w={12} fill={C.amber} />
      <path d="M88 18 V70" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="3 2" fill="none" />
      <Bar x={92} baseY={66} w={14} h={34} fill={C.grey3} />
      <path
        d="M99 66 V38"
        stroke={a.deep}
        strokeWidth={2.4}
        strokeDasharray="3 3"
        strokeLinecap="round"
        fill="none"
      />
    </>
  ),

  // Start the works with the acta de comprobacion del replanteo: the site set out
  // and proved, the acta signed by both sides, and the plazo starting from it.
  'start-the-works-with-an-acta-de-replanteo': (a) => (
    <>
      <path d="M14 62 H50" stroke={C.grey1} strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <path
        d="M26 62 L32 40 L38 62"
        stroke={C.blueDeep}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M32 62 V42" stroke={C.blueDeep} strokeWidth={1.6} fill="none" />
      <rect x={25} y={30} width={14} height={8} rx={2} fill={C.blueLight} stroke={C.white} strokeWidth={1} />
      <Sheet x={56} y={12} w={38} h={38} />
      <RowBar x={61} y={20} w={22} h={3.2} fill={C.grey3} />
      <RowBar x={61} y={27} w={17} h={3.2} fill={C.grey3} />
      <Signature x={60} y={41} w={14} color={C.blueDeep} />
      <Signature x={78} y={41} w={14} color={C.blueDeep} />
      <path d="M58 68 H104" stroke={C.grey1} strokeWidth={1.4} fill="none" />
      <path d="M62 68 V56" stroke={a.deep} strokeWidth={1.8} fill="none" />
      <path d="M62 56 h11 l-3 3.4 l3 3.4 h-11 z" fill={a.base} stroke="none" />
      <circle cx={88} cy={68} r={2.6} fill={C.grey2} stroke="none" />
    </>
  ),

  // Submit a permit package to the authority: loose documents bound into one
  // package, handed to the authority, and a decision coming back on it.
  'submit-a-permit-package-to-the-authority': (a) => (
    <>
      <Sheet x={12} y={20} w={22} h={30} />
      <Sheet x={16} y={16} w={22} h={30} />
      <Sheet x={20} y={12} w={22} h={30} />
      <RowBar x={25} y={22} w={13} h={3} fill={C.grey3} />
      <path
        d="M44 40 H52 M48.5 36.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.grey1}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={54} y={30} width={26} height={18} rx={3} fill={a.base} stroke="none" />
      <path d="M54 32 L67 41 L80 32" fill="none" stroke={C.white} strokeWidth={1.6} strokeLinejoin="round" />
      <path d="M82 30 L94 22 L106 30 Z" fill={C.grey2} stroke="none" />
      <rect x={84} y={30} width={20} height={18} rx={1} fill={C.grey3} stroke="none" />
      <path d="M89 32 V46 M94 32 V46 M99 32 V46" stroke={C.white} strokeWidth={2} fill="none" />
      <path d="M82 50 H106" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <Stamp cx={94} cy={62} r={8} color={C.blue} />
    </>
  ),

  // Take off a plan in feet and inches: the sheet's own printed dimension held
  // against a rule that halves down to eighths instead of running in tens.
  'take-off-a-plan-in-feet-and-inches': (a) => (
    <>
      <Sheet x={14} y={12} w={56} h={42} />
      <path
        d="M22 18 H62 V44 H22 Z M22 32 H44 M44 18 V44"
        stroke={C.grey2}
        strokeWidth={1.3}
        fill="none"
      />
      <path d="M22 49 H62 M22 46.5 V51.5 M62 46.5 V51.5" stroke={C.ochre} strokeWidth={1.4} fill="none" />
      <path d="M22 54 V60 M62 54 V60" stroke={C.grey1} strokeWidth={1.2} strokeDasharray="2 2" fill="none" />
      <rect x={14} y={60} width={92} height={12} rx={2} fill={a.base} stroke="none" />
      <path d="M38 60 V70 M62 60 V70 M86 60 V70" stroke={C.white} strokeWidth={1.8} fill="none" />
      <path
        d="M26 60 V67.5 M50 60 V67.5 M74 60 V67.5 M98 60 V67.5"
        stroke={C.white}
        strokeWidth={1.4}
        opacity={0.85}
        fill="none"
      />
      <path
        d="M20 60 V65 M32 60 V65 M44 60 V65 M56 60 V65 M68 60 V65 M80 60 V65 M92 60 V65 M104 60 V65"
        stroke={C.white}
        strokeWidth={1.1}
        opacity={0.6}
        fill="none"
      />
      <Cube cx={88} ty={16} w={12} hh={6} depth={16} top={C.grey3} left={C.grey2} right={C.grey1} />
    </>
  ),

  // Take off in metric and buy in imperial: one row holds both, the metric
  // quantity locked away as stored and exported, the trade name going to the yard.
  'take-off-in-metric-and-buy-in-imperial': (a) => (
    <>
      <Sheet x={40} y={28} w={40} h={26} />
      <RowBar x={45} y={34} w={16} h={3.2} fill={C.grey3} />
      <RowBar x={45} y={43} w={22} h={3.6} fill={a.base} />
      <Chip x={68} y={41.5} w={9} h={7} r={2} fill={C.ochre} />
      <path
        d="M37 41 H28 M32 37.5 l-4 3.5 l4 3.5"
        stroke={C.grey1}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Cylinder cx={20} top={30} rx={7} ry={3} h={16} fill={a.base} topFill={a.light} />
      <rect x={15.5} y={57} width={9} height={7} rx={1.5} fill={C.blueDeep} stroke="none" />
      <path
        d="M17.5 57 V54.5 a2.5 2.5 0 0 1 5 0 V57"
        stroke={C.blueDeep}
        strokeWidth={1.4}
        fill="none"
      />
      <path
        d="M83 41 H92 M88 37.5 l4 3.5 l-4 3.5"
        stroke={C.grey1}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Cube cx={97} ty={26} w={8} hh={4} depth={12} top={C.grey3} left={C.grey2} right={C.grey1} />
    </>
  ),

  // Take off quantities from a PDF plan: no model behind it, so the area is
  // traced on screen handle by handle, scaled, and landed as bill positions.
  'takeoff-quantities-from-a-pdf-plan': (a) => (
    <>
      <Sheet x={14} y={12} w={54} h={56} />
      <path
        d="M22 22 H60 V40 H44 V58 H22 Z M22 40 H44"
        stroke={C.grey2}
        strokeWidth={1.3}
        fill="none"
      />
      <path d="M24 44 H40 V56 H24 Z" fill={a.base} fillOpacity={0.18} stroke={a.base} strokeWidth={1.8} />
      <circle cx={24} cy={44} r={2.2} fill={C.white} stroke={a.base} strokeWidth={1.4} />
      <circle cx={40} cy={44} r={2.2} fill={C.white} stroke={a.base} strokeWidth={1.4} />
      <circle cx={40} cy={56} r={2.2} fill={C.white} stroke={a.base} strokeWidth={1.4} />
      <circle cx={24} cy={56} r={2.2} fill={C.white} stroke={a.base} strokeWidth={1.4} />
      <rect x={22} y={62} width={24} height={5} rx={1} fill="none" stroke={C.ochre} strokeWidth={1.3} />
      <path d="M28 62 h6 v5 h-6 z M40 62 h6 v5 h-6 z" fill={C.ochre} stroke="none" />
      <path
        d="M70 40 H78 M74.5 36.5 l3.5 3.5 l-3.5 3.5"
        stroke={C.grey1}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={80} y={18} w={26} h={44} />
      <HeaderBand x={80} y={18} w={26} h={8} fill={C.blue} />
      <RowBar x={85} y={34} w={15} h={3} fill={C.grey3} />
      <RowBar x={85} y={44} w={12} h={3} fill={C.grey3} />
    </>
  ),

  // Trade payment for lien rights: the money only leaves against the signed
  // waiver coming back, and the retainage is released by the agreed event.
  'trade-payment-for-lien-rights': (a) => (
    <>
      <Cylinder cx={24} top={40} rx={11} ry={4} h={14} fill={C.ochre} topFill={C.amber} />
      <path
        d="M38 32 C50 22 60 22 70 28 M65 24 l5 4 l-5 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M70 58 C60 66 48 66 38 60 M43 56 l-5 4 l5 4"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={47} y={40} width={15} height={12} rx={2} fill={C.green} stroke="none" />
      <path d="M50 40 V36 a4 4 0 0 1 8 0" stroke={C.green} strokeWidth={1.8} fill="none" strokeLinecap="round" />
      <circle cx={54.5} cy={46} r={2} fill={C.white} stroke="none" />
      <Sheet x={72} y={20} w={34} h={42} />
      <RowBar x={77} y={28} w={18} h={3} fill={C.grey3} />
      <RowBar x={77} y={35} w={14} h={3} fill={C.grey3} />
      <Signature x={76} y={50} w={22} color={C.blueDeep} />
      <path d="M76 55 H98" stroke={C.grey2} strokeWidth={1.2} fill="none" />
    </>
  ),

  // Turn a document into a tracked action: the one line in the letter that is
  // asking for something becomes a task, with the source still clipped to it.
  'turn-a-document-into-a-tracked-action': (a) => (
    <>
      <Sheet x={12} y={12} w={36} h={48} />
      <RowBar x={17} y={20} w={22} h={3.2} fill={C.grey3} />
      <RowBar x={17} y={27} w={26} h={3.2} fill={C.grey3} />
      <rect x={16} y={35} width={28} height={7} rx={2} fill={a.light} stroke="none" />
      <RowBar x={19} y={37} w={20} h={3} fill={C.ink} opacity={0.55} />
      <path
        d="M52 36 H62 M58 32.5 l3.5 3.5 l-3.5 3.5"
        stroke={a.base}
        strokeWidth={2.2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={66} y={18} w={40} h={34} />
      <rect x={71} y={25} width={7} height={7} rx={1.6} fill="none" stroke={C.grey1} strokeWidth={1.4} />
      <RowBar x={82} y={27} w={17} h={3} fill={C.grey3} />
      <Badge cx={74.5} cy={41.5} r={4} fill={C.green} glyph="check" shadow={false} />
      <RowBar x={82} y={40} w={13} h={3} fill={C.grey3} />
      <path d="M70 56 C58 66 40 62 34 54" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="3 2" fill="none" />
      <path
        d="M52 62 v-4 a3 3 0 0 1 6 0 v7 a4.5 4.5 0 0 1 -9 0 v-6"
        stroke={C.blueDeep}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
      />
    </>
  ),

  // Value the month and certify the progress payment: the period valued line by
  // line, retention held off the total, and a second person certifying it.
  'value-the-month-and-certify-the-progress-payment': (a) => (
    <>
      <Sheet x={14} y={14} w={58} h={52} />
      <HeaderBand x={14} y={14} w={58} h={10} fill={C.blue} />
      <RowBar x={20} y={18} w={22} h={3} fill={C.white} opacity={0.9} />
      <rect x={20} y={30} width={44} height={5.5} rx={2.75} fill={C.grey3} stroke="none" />
      <rect x={20} y={30} width={30} height={5.5} rx={2.75} fill={a.base} stroke="none" />
      <rect x={20} y={40} width={44} height={5.5} rx={2.75} fill={C.grey3} stroke="none" />
      <rect x={20} y={40} width={18} height={5.5} rx={2.75} fill={a.base} stroke="none" />
      <path d="M20 52 H64" stroke={C.grey1} strokeWidth={1.2} fill="none" />
      <rect x={20} y={56} width={35} height={5} rx={2.5} fill={a.deep} stroke="none" />
      <rect x={57} y={56} width={7} height={5} rx={2.5} fill={C.amber} stroke="none" />
      <Stamp cx={92} cy={26} r={9} color={C.green} />
      <circle cx={92} cy={48} r={5.5} fill={C.grey2} stroke="none" />
      <path d="M82 68 c0 -7.5 4.5 -11 10 -11 s10 3.5 10 11 z" fill={C.grey2} stroke="none" />
    </>
  ),

  // Walk the estimate from Class D to Class A: the same number each time, but the
  // range it could land in closing on it as the design firms up.
  'walk-the-estimate-from-class-d-to-class-a': (a) => (
    <>
      <path d="M60 14 V72" stroke={C.grey1} strokeWidth={1.4} strokeDasharray="3 2" fill="none" />
      <path
        d="M16 20 V64 M12.5 60 l3.5 4 l3.5 -4"
        stroke={C.grey1}
        strokeWidth={1.6}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect x={22} y={20} width={76} height={6} rx={3} fill={C.grey3} stroke="none" />
      <circle cx={60} cy={23} r={2.4} fill={C.white} stroke={C.grey1} strokeWidth={1.2} />
      <rect x={32} y={34} width={56} height={6} rx={3} fill={C.grey2} stroke="none" />
      <circle cx={60} cy={37} r={2.4} fill={C.white} stroke={C.grey1} strokeWidth={1.2} />
      <rect x={44} y={48} width={32} height={6} rx={3} fill={a.light} stroke="none" />
      <circle cx={60} cy={51} r={2.4} fill={C.white} stroke={C.grey1} strokeWidth={1.2} />
      <rect x={52} y={62} width={16} height={6} rx={3} fill={a.base} stroke="none" />
      <circle cx={60} cy={65} r={2.4} fill={C.white} stroke={C.grey1} strokeWidth={1.2} />
    </>
  ),

  // Win a GAEB tender from the LV to the Angebot: the client's file read straight
  // in, every position priced, and the offer handed back out the same way.
  'win-a-gaeb-tender-from-lv-to-angebot': (a) => (
    <>
      <Sheet x={12} y={28} w={22} h={28} />
      <path
        d="M23 36 V44 M19 40 l4 4 l4 -4"
        stroke={C.blueDeep}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Sheet x={44} y={14} w={34} h={56} />
      <HeaderBand x={44} y={14} w={34} h={9} fill={a.base} />
      <RowBar x={49} y={30} w={15} h={3.2} fill={C.grey3} />
      <Chip x={66} y={28.5} w={8} h={6} r={2} fill={a.light} />
      <RowBar x={49} y={40} w={12} h={3.2} fill={C.grey3} />
      <Chip x={66} y={38.5} w={8} h={6} r={2} fill={a.light} />
      <rect x={49} y={56} width={25} height={5} rx={2.5} fill={a.deep} stroke="none" />
      <Sheet x={84} y={28} w={22} h={28} />
      <path
        d="M95 46 V38 M91 42 l4 -4 l4 4"
        stroke={a.deep}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Badge cx={101} cy={24} r={6} fill={C.green} glyph="check" />
    </>
  ),

  // Write the basis of estimate: what the price includes, what it does not, the
  // assumptions behind it, all issued attached to the number itself.
  'write-the-basis-of-estimate': (a) => (
    <>
      <Sheet x={16} y={12} w={62} h={56} />
      <HeaderBand x={16} y={12} w={62} h={10} fill={a.base} />
      <RowBar x={22} y={16} w={24} h={3} fill={C.white} opacity={0.9} />
      <path
        d="M23 31 l2.4 2.6 l4.6 -5.2"
        stroke={C.blue}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <RowBar x={33} y={29.5} w={16} h={3} fill={C.grey3} />
      <path
        d="M23 41 l2.4 2.6 l4.6 -5.2"
        stroke={C.blue}
        strokeWidth={1.8}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <RowBar x={33} y={39.5} w={13} h={3} fill={C.grey3} />
      <path d="M55 28.5 l5 5 M60 28.5 l-5 5" stroke={C.red} strokeWidth={1.8} fill="none" strokeLinecap="round" />
      <RowBar x={64} y={29.5} w={10} h={3} fill={C.grey3} />
      <path d="M55 38.5 l5 5 M60 38.5 l-5 5" stroke={C.red} strokeWidth={1.8} fill="none" strokeLinecap="round" />
      <RowBar x={64} y={39.5} w={9} h={3} fill={C.grey3} />
      <RowBar x={22} y={54} w={44} h={3.4} fill={C.grey3} />
      <path d="M78 34 H84" stroke={C.grey1} strokeWidth={1.6} fill="none" />
      <path
        d="M86 30 L93 22 H104 a2 2 0 0 1 2 2 v12 a2 2 0 0 1 -2 2 H93 Z"
        fill={C.ochre}
        stroke="none"
      />
      <circle cx={96} cy={30} r={2.4} fill={C.white} stroke="none" />
    </>
  ),
};
