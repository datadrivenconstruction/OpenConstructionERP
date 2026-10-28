// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// flowGlyphs - the little drawings beside a step's "Goes in" and "Comes out".
//
// WHY A PICTURE AT ALL. Those two lists are the answer to the only question a
// reader has in front of a step they have never done: what do I need to have,
// and what will I be holding afterwards. As two columns of identical bullets
// they answered it in prose only, and a reader skimming eleven steps read none
// of it. A drawing per row turns each column into an inventory that can be
// taken in at a glance: a plan and a price book go in, a priced bill and a
// validation report come out.
//
// DRAWN, NOT DECORATED. Every glyph is stroke-only on a 24 grid, in
// `currentColor`, with no fill, no plate and no background: it inherits the
// row's colour, so it is the same ink as the text beside it rather than an
// ornament sitting behind it. That is also why there is no rounded tile around
// them - a badge would make sixteen small boxes down a card and read as
// chrome.
//
// CHOSEN FROM THE ENGLISH LABEL, NEVER THE TRANSLATED ONE. `StepFlowItem`
// carries `label` (English) beside the optional `labelKey`, and the match runs
// on `label`. Matching the rendered string would give a German reader a
// different picture from an English one for the same artefact, which is the
// one thing a glyph must never do. Locale-independent by construction.
//
// A ROW WITH NO MATCH IS NOT A BROKEN ROW. The labels are a long tail - 1138
// distinct input labels across the case library - so an unmatched one falls
// back to the plain document rather than to nothing. A blank where its
// neighbours have drawings reads as a rendering fault; a generic document
// reads as "some artefact", which is true.

import type { ReactElement } from 'react';
import clsx from 'clsx';

/** The vocabulary. Every kind is a thing an estimator hands over or receives. */
export type FlowGlyphKind =
  | 'drawing'
  | 'model'
  | 'bill'
  | 'rates'
  | 'money'
  | 'programme'
  | 'report'
  | 'check'
  | 'issue'
  | 'contract'
  | 'photo'
  | 'site'
  | 'register'
  | 'file'
  | 'person'
  | 'message'
  | 'document';

/**
 * Keyword to kind, most specific first. Two things about how an entry matches,
 * and both exist because the naive reading of this table is wrong.
 *
 * ORDER IS THE RULE. `schedule of values` is a bill, a bare `schedule` is a
 * programme, so the compound is tested before the bare word. Same for the
 * handful of single words that belong to two kinds: `plant` is a site thing and
 * `plan` is a drawing, and `plan` is a prefix of `plant`, so `plant` is settled
 * first rather than left to the accident of which list came earlier.
 *
 * A NEEDLE MATCHES A WORD, NOT A SUBSTRING. A needle carrying a space or a
 * hyphen is matched against the whole label; a bare single word is matched
 * against the START OF A WORD in it. That is deliberate: plain `includes` finds
 * `lv` inside `involve` and `oz` inside `frozen`, which is exactly how a keyword
 * list ends up drawing a bill of quantities beside "Issues involved". Matching
 * word starts also lets a needle be a stem, so `federat` covers federated and
 * federation and `activit` covers activity and activities.
 */
const MATCHERS: ReadonlyArray<readonly [readonly string[], FlowGlyphKind]> = [
  // Compounds that would otherwise be caught by a broader word below. Each one
  // is here because the bare word belongs to a different kind: a schedule of
  // values is a bill and not a programme, a validation report is the outcome of
  // checking and not a page of figures.
  [['schedule of values', 'schedule of rates'], 'bill'],
  [['validation report', 'inspection report', 'audit report', 'compliance report'], 'check'],
  [['point cloud', 'pointcloud'], 'model'],
  [['site photo', 'progress photo'], 'photo'],
  [['drawing register', 'asset register', 'warranty register'], 'register'],
  [['cost database', 'cost book', 'cost library'], 'rates'],
  [['budget baseline', 'cost baseline'], 'money'],
  // Settled early because a needle further down is a PREFIX of these, and word
  // starts match: `plan` would otherwise claim `plant`, `sum` would claim
  // `summary`.
  [['plant'], 'site'],
  [['summary'], 'report'],

  [
    ['drawing', 'plan', 'dwg', 'dxf', 'sketch', 'layout', 'elevation', 'sheet', 'markup', 'design',
      'revision', 'as-built'],
    'drawing',
  ],
  [['model', 'bim', 'ifc', 'revit', '3d', 'federat', 'mesh', 'geometry', 'clash', 'element'], 'model'],
  [
    ['boq', 'bill', 'lv', 'oz', 'positions', 'position', 'breakdown', 'take-off', 'takeoff', 'quantities',
      'quantity', 'measure', 'estimate', 'numbering', 'cost code', 'aufma', 'area', 'm2', 'sqm'],
    'bill',
  ],
  [['rate', 'price', 'pricing', 'catalogue', 'catalog', 'cwicr', 'benchmark', 'index', 'tariff'], 'rates'],
  [
    ['payment', 'invoice', 'certificate', 'budget', 'cash', 'valuation', 'claim', 'sum', 'retention', 'margin',
      'fee', 'cost', 'total', 'account', 'earned', 'spend', 'commit', 'value', 'revenue', 'profit', 'return',
      'viability', 'turnover'],
    'money',
  ],
  [
    ['programme', 'program', 'schedule', 'gantt', 'timeline', 'lookahead', 'date', 'milestone', 'duration',
      'period', 'time', 'baseline', 'delay', 'float', 'deadline', 'frist', 'abgabe'],
    'programme',
  ],
  [['report', 'analysis', 'summary', 'forecast', 'dashboard', 'score', 'trend', 'outturn', 'variance'], 'report'],
  [
    ['validation', 'inspection', 'check', 'approval', 'approved', 'verified', 'sign-off', 'signed', 'audit', 'qa',
      'review', 'evidence', 'finding', 'confirmed', 'agreed', 'cleared', 'complete', 'flagged', 'gap', 'readiness',
      'status', 'action'],
    'check',
  ],
  [['defect', 'snag', 'punch', 'ncr', 'risk', 'issue', 'conformance', 'incident', 'hazard', 'hold'], 'issue'],
  [
    ['rfi', 'correspondence', 'letter', 'email', 'mail', 'message', 'thread', 'response', 'reply', 'query',
      'question', 'transmittal', 'submittal', 'circular'],
    'message',
  ],
  [
    ['contract', 'agreement', 'terms', 'award', 'order', 'tender', 'bid', 'quote', 'variation', 'change', 'scope',
      'requirement', 'qualification', 'exclusion', 'inclusion', 'instruction', 'notice', 'warrant', 'guarantee',
      'bond', 'insurance', 'liabilit', 'hauptangebot', 'nebenangebot', 'nachtrag', 'angebot'],
    'contract',
  ],
  [['photo', 'image', 'picture', 'scan', 'render'], 'photo'],
  // People before places. `Project team` and `Site team` are both a group of
  // people, and `project` and `site` sit in the group below, so a party named
  // in a label has to be settled first or it is drawn as a hard hat.
  [['team', 'role', 'client', 'stakeholder', 'contact', 'user', 'supplier', 'subcontractor', 'owner'], 'person'],
  [
    ['site', 'field', 'diary', 'daily', 'crew', 'labour', 'labor', 'plant', 'delivery', 'works', 'work',
      'trade', 'activit', 'resource', 'progress', 'method', 'project', 'scheme', 'system', 'installed',
      'equipment', 'material'],
    'site',
  ],
  [['register', 'log', 'inventory', 'list', 'record', 'item', 'asset', 'index'], 'register'],
  [
    ['file', 'export', 'import', 'gaeb', 'xml', 'csv', 'excel', 'spreadsheet', 'x81', 'x83', 'x84', 'x86',
      'x89', 'd83', 'p83', 'pdf', 'pack', 'data', 'document'],
    'file',
  ],
];

/**
 * The glyph for one flow item, chosen from its English label.
 *
 * @param englishLabel The `label` field of a `StepFlowItem`, never the string
 *   the reader sees.
 */
export function flowGlyphFor(englishLabel: string): FlowGlyphKind {
  const text = englishLabel.toLowerCase();
  // Split on anything that is not a letter or a digit, so `as-built`, `sign-off`
  // and `x83` all land where the table expects them. Unicode-aware on purpose:
  // several German cases name their artefacts in German, and an ASCII class
  // would tear `Aufmaß` in half and leave the stem unmatchable.
  const words = text.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  for (const [needles, kind] of MATCHERS) {
    for (const needle of needles) {
      // A needle carrying a space or a hyphen is a phrase and is matched
      // against the whole label: the split below would have torn `as-built`
      // and `sign-off` in half.
      const hit = /[ -]/.test(needle)
        ? text.includes(needle)
        : words.some((word) => word.startsWith(needle));
      if (hit) return kind;
    }
  }
  return 'document';
}

/** A sheet of paper. The base every document-shaped glyph is drawn on. */
const SHEET = 'M6 2.75h7.5L18 7.25v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-17.5a1 1 0 0 1 1-1Z';
/** The folded corner, drawn separately so the fold reads as a fold. */
const FOLD = 'M13.5 2.75v4.5H18';

/** The drawings themselves, on a 24 grid. Stroke only: no path here is filled. */
const PATHS: Record<FlowGlyphKind, readonly string[]> = {
  // A sheet with a floor plan on it: two rooms and a door opening.
  drawing: [SHEET, FOLD, 'M7.5 11h4v4h-4z', 'M11.5 11h4.5', 'M15.5 11v8.5H7.5V15', 'M11.5 15v4.5'],
  // An isometric box: the one shape that says "this is three-dimensional".
  model: ['M12 2.75 21 7.5v9L12 21.25 3 16.5v-9Z', 'M3 7.5l9 4.75 9-4.75', 'M12 12.25v9'],
  // A bill: ruled rows and a rule above the total, which is what makes it a
  // bill rather than a page of writing.
  bill: [SHEET, FOLD, 'M7.5 10.5h6', 'M7.5 13.5h7', 'M7.5 16.5h7', 'M11.5 19.5h4'],
  // A price tag with its eyelet.
  rates: ['M12.5 2.75H21v8.5l-9.25 9.25a1.5 1.5 0 0 1-2.1 0l-6.4-6.4a1.5 1.5 0 0 1 0-2.1Z', 'M17.25 6.75h.01'],
  // A note with a coin on it.
  money: ['M2.75 6.25h13.5v8H2.75z', 'M9.5 8.75a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z', 'M21.25 9v8.75H7.5'],
  // Three gantt bars, offset the way a programme offsets them.
  programme: ['M3 4.75h18v15.5H3z', 'M3 8.75h18', 'M6 11.75h7', 'M9 15h8', 'M6 18.25h5'],
  // A sheet with a bar chart: the report is the one that carries numbers.
  report: [SHEET, FOLD, 'M8 19.5v-4', 'M11.5 19.5v-7', 'M15 19.5v-2.5'],
  // A clipboard with a tick. Checked, not merely written on.
  check: ['M8 4.25H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-16a1 1 0 0 0-1-1h-2', 'M9 2.25h6v4H9z', 'M8.75 14.5l2.5 2.5 4.5-5'],
  // A warning triangle with its bar and dot.
  issue: ['M12 3.25 22 20.75H2Z', 'M12 10v4.5', 'M12 17.5h.01'],
  // A sheet with a signature line and a seal.
  contract: [SHEET, FOLD, 'M7.5 11h7', 'M7.5 14h4.5', 'M13.5 18.5c1 -1.5 2.5 -1.5 3.5 0', 'M9.5 18.5h2'],
  // A frame with a horizon and a sun: the universal "this is a picture".
  photo: ['M3.25 5.25h17.5v13.5H3.25z', 'M8 10.25a1.25 1.25 0 1 0 0-2.5 1.25 1.25 0 0 0 0 2.5Z', 'M3.25 16l5-4.5 4.5 4 3-2.5 5 4.25'],
  // A hard hat. The only glyph in the set that means a place rather than a
  // document, and it has to be readable at 18 pixels, so it is the silhouette
  // and the brim, nothing else.
  site: ['M4 16.25a8 8 0 0 1 16 0', 'M9.5 16.25V7.5a2.5 2.5 0 0 1 5 0v8.75', 'M2.75 16.25h18.5v2.5H2.75z'],
  // A list: three rows, each with its bullet, inside a bracket.
  register: ['M5 3.5h14a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1Z', 'M7.75 8h.01', 'M7.75 12h.01', 'M7.75 16h.01', 'M10.5 8h6', 'M10.5 12h6', 'M10.5 16h4'],
  // A file with a grid on it: a spreadsheet or an exchange format, the two
  // things that arrive as a file rather than as a document.
  file: [SHEET, FOLD, 'M7.5 11.5h8', 'M7.5 15h8', 'M7.5 18.5h8', 'M11.5 11.5v7'],
  // A person: head and shoulders.
  person: ['M12 3.75a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z', 'M4.75 20.75a7.25 7.25 0 0 1 14.5 0'],
  // An envelope: sent, and waiting to be answered.
  message: ['M2.75 5.75h18.5v12.5H2.75z', 'M2.75 6.5 12 13l9.25-6.5'],
  // The fallback. A sheet with writing on it and nothing claimed about what
  // kind of artefact it is.
  document: [SHEET, FOLD, 'M7.5 12h7', 'M7.5 15.5h7', 'M7.5 19h4'],
};

export interface FlowGlyphProps {
  kind: FlowGlyphKind;
  /** Edge length in pixels. The grid is square, so width and height are equal. */
  size?: number;
  className?: string;
}

/**
 * One glyph. Decorative by design: the row's own text names the artefact, so
 * the drawing is hidden from the accessible tree rather than repeating it in
 * words that would be a second, worse label.
 */
export function FlowGlyph({ kind, size = 18, className }: FlowGlyphProps): ReactElement {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={clsx('shrink-0', className)}
    >
      {PATHS[kind].map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}
