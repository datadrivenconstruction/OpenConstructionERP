// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// `(12550880.81).toLocaleString()` does not read the language the reader chose
// in the header. It reads the BROWSER's locale, which is a different thing:
// a German estimator working on an English-locale laptop got `12,550,880.81`
// in a tile above rows reading `12.550.880,81`, and switching the app to
// German changed nothing, because nothing in that call ever asked what the app
// was set to. The same goes for `toLocaleDateString`, `toLocaleTimeString`,
// and any `Intl.*Format` built with `undefined` as the locale.
//
// 308 call sites were rewritten to pass `getIntlLocale()`, the app's own
// mapping from the i18next language to a BCP-47 tag. This gate stops the
// shape coming back.
//
// It then grew a second half for `toFixed`, which is the same defect by a
// different route: that method takes no locale at all, so no argument fixes it
// and 455 call sites had to move onto a formatter instead. The two halves are
// in one file because they are one question - is this number written in the
// reader's language - and a reviewer looking for the answer should not have to
// know which method the author happened to reach for.
//
// It is deliberately separate from `formattersReadTheLocalePerCall.test.ts`,
// which asks a different question of the same call: that one catches a
// formatter that reads the RIGHT locale but only once, at chunk load. A site
// can pass either gate and fail the other, so both run.
import { describe, it, expect, afterAll } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import i18next from 'i18next';
import { getIntlLocale, fmtFixed, fmtNumber } from '../formatters';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

const SRC = join(__dirname, '..', '..', '..');

// An absent locale argument, or a literal `undefined`, hands the decision to
// the browser. Anything else - `getIntlLocale()`, a variable, a string tag -
// is an explicit choice and is left alone. Global, because one line can carry
// two of them: the BIM header writes `{linked.toLocaleString()}/{total
// .toLocaleString()}` on a single line, and a per-line count reports that as
// one defect.
const SHAPES: ReadonlyArray<{ name: string; re: RegExp }> = [
  { name: 'toLocaleString', re: /\.toLocaleString\(\s*(?:\)|undefined\b)/g },
  { name: 'toLocaleDateString', re: /\.toLocaleDateString\(\s*(?:\)|undefined\b)/g },
  { name: 'toLocaleTimeString', re: /\.toLocaleTimeString\(\s*(?:\)|undefined\b)/g },
  { name: 'Intl.NumberFormat', re: /new Intl\.NumberFormat\(\s*(?:\)|undefined\b)/g },
  { name: 'Intl.DateTimeFormat', re: /new Intl\.DateTimeFormat\(\s*(?:\)|undefined\b)/g },
  { name: 'Intl.RelativeTimeFormat', re: /new Intl\.RelativeTimeFormat\(\s*(?:\)|undefined\b)/g },
  { name: 'Intl.ListFormat', re: /new Intl\.ListFormat\(\s*(?:\)|undefined\b)/g },
];

// A line that is entirely prose carries no call site. `formatters.ts`
// documents the very shape this scan looks for, and counting its docstring as
// a defect would leave a permanent finding with nothing to fix.
const COMMENT = /^\s*(?:\/\/|\*|\/\*)/;

/**
 * Sites that must NOT follow the reader's language, each pinned to the text
 * that makes it so. Matching on the snippet rather than the whole file keeps
 * the exemption to the one line it was argued for: a new bare call elsewhere
 * in the same file still fails.
 */
const ALLOWED: ReadonlyArray<{ file: string; snippet: string; why: string }> = [
  {
    file: 'features/match-elements/MatchWizardFlow.tsx',
    snippet: "?? 'Match'} - ${new Date().toLocaleDateString()}",
    why: 'Default session name posted to the API; teammates on other languages read it back.',
  },
  {
    file: 'features/reporting/ReportingPage.tsx',
    snippet: '${template.name} - ${new Date().toLocaleDateString()}',
    why: 'Report title posted to the API and stored, not a label rendered for one reader.',
  },
  {
    file: 'shared/lib/formatters.ts',
    snippet: 'return n.toLocaleString();',
    why: 'Catch path that only runs once Intl has already refused; asking it for that same locale again is not a fix.',
  },
  {
    file: 'shared/lib/numberFormat.ts',
    snippet: 'new Intl.NumberFormat(undefined, base)',
    why: 'Deliberate retry after Intl rejects a malformed locale tag arriving from i18next.',
  },
  {
    file: 'test/setup.ts',
    snippet: 'new Intl.DateTimeFormat().resolvedOptions().timeZone',
    why: 'A probe, not a rendering. It asks the host which timezone this worker resolved to, and no locale argument answers that.',
  },
];

// `toFixed` is the same defect arriving by a different road. It takes no
// locale at all: it always writes `.` for the decimal mark and never groups
// the thousands, so `(1234.5).toFixed(2)` is `1234.50` for every reader on
// earth. There is no argument that fixes it - the call has to move onto a
// formatter. `toPrecision` and `toExponential` are counted with it, because
// they are locale-independent in exactly the same way and leaving them
// uncounted leaves the class a door to grow back through.
const FIXED_SHAPES: ReadonlyArray<{ name: string; re: RegExp }> = [
  { name: 'toFixed', re: /\.toFixed\s*\(/g },
  { name: 'toPrecision', re: /\.toPrecision\s*\(/g },
  { name: 'toExponential', re: /\.toExponential\s*\(/g },
];

/**
 * The categories where a locale-independent number is the REQUIREMENT rather
 * than the defect, as predicates over the call's line and the line above it.
 *
 * These are rules, not an allowlist, on purpose: there are far more
 * machine-facing sites than could be argued one at a time, and a list that
 * long stops being read. The trade is that a rule is coarser than an argument,
 * so each one is written to describe a structural fact about the call ("its
 * result is parsed back into a number") rather than a guess about the file.
 *
 * Kept as a plain array literal between the markers below because
 * `scripts`-side tooling reads and evaluates this exact text; a second copy of
 * these rules would be the copy that goes stale.
 */
const MACHINE: ReadonlyArray<{
  name: string;
  why: string;
  test: (line: string, prev: string, index: number, scope: string, inCatch: boolean) => boolean;
}> =
  /* MACHINE-RULES:START */
  [
    {
      name: 'round-trip',
      why: 'The string is parsed straight back into a number, so it is a rounding idiom and never reaches a reader.',
      // Which side of the parenthesis the call sits on is the whole question,
      // and no regex answers it. `Number(waste.toFixed(2))` rounds;
      // `Number(p.variance).toFixed(0)` formats for display, and one written
      // with `[^;]*` in between read those as the same shape and exempted 60
      // visible numbers. Tightening it to `[^()]*` then went too far the other
      // way and called `Number(fromMeters(real, 'm').toFixed(4))` a display
      // site. So this walks left from the call, counting parentheses, and asks
      // whether an enclosing one belongs to a parser.
      test: (line, _prev, index) => {
        let depth = 0;
        for (let i = index - 1; i >= 0; i--) {
          const char = line[i];
          if (char === ')') {
            depth++;
          } else if (char === '(') {
            if (depth > 0) {
              depth--;
              continue;
            }
            const head = line.slice(0, i).match(/([A-Za-z_$][\w$]*)\s*$/);
            if (head && (head[1] === 'Number' || head[1] === 'parseFloat' || head[1] === 'parseInt')) return true;
          }
        }
        // `+value.toFixed(2)` is the same idiom spelled shorter.
        return /[=(,:[?]\s*\+\s*[\w.[\]]*$/.test(line.slice(0, index));
      },
    },
    {
      name: 'string-surgery',
      why: 'The result is sliced, compared or keyed on, and every one of those operations assumes the separator is a dot.',
      // `[^()]` rather than `[^)]`, because a decimal count is often itself a
      // call or a ternary - `toFixed(Math.abs(v) < 10 ? 1 : 0)` - and the
      // looser form read that inner `< 10` as a comparison ON the result and
      // exempted a percentage a reader sees.
      test: (line) =>
        /\.to(?:Fixed|Precision|Exponential)\s*\([^()]*\)\s*\.(?:replace|split|padStart|padEnd|slice|substring|substr|endsWith|startsWith|includes|indexOf|charAt|concat|repeat|trim|match|localeCompare|length)\b/.test(
          line,
        ) ||
        /\.to(?:Fixed|Precision|Exponential)\s*\([^()]*\)\s*(?:===|!==|==(?!=)|!=(?!=)|<=|>=)/.test(line) ||
        /(?:===|!==|==(?!=)|!=(?!=))\s*[\w.[\]]*\.to(?:Fixed|Precision|Exponential)\s*\(/.test(line),
    },
    {
      name: 'css-geometry',
      why: 'A CSS length, an SVG path or a transform. The CSS grammar takes a dot and would reject a grouped number outright.',
      // The unit has to be welded to the number. CSS never writes a space
      // between the two, so `${n.toFixed(1)}deg` closing a gradient stop is a
      // length while `${n.toFixed(1)} px` is a unit shown to a person, and
      // reading those as one shape exempted a takeoff label. A bare `style=`
      // is not enough either: an exported HTML report styles a cell whose
      // number is still there to be read.
      test: (line, prev) =>
        /transform\s*[=:]|\btranslate\(|\brotate\(|\bmatrix\(|\bviewBox|\bstrokeDash|\bclipPath|\bpolyline\b|\bpolygon\b|linearGradient|\bpoints\s*=|\bd\s*=\s*[`"']/.test(
          line,
        ) ||
        /\b(?:width|height|left|top|right|bottom|opacity|cx|cy|rx|ry|x1|x2|y1|y2|dx|dy|fontSize|lineHeight|zIndex|offset|strokeWidth|maxWidth|minWidth|maxHeight|minHeight|flexBasis)\s*:\s*[^,;]*\.to(?:Fixed|Precision|Exponential)\s*\(/.test(
          line,
        ) ||
        /\$\{[^`{}]*\.to(?:Fixed|Precision|Exponential)[^`{}]*\}(?:px|em|rem|vh|vw|deg|fr|ch)\b/.test(line) ||
        // A template that is nothing but two numbers and a comma is an SVG
        // point. Both sparklines in this tree build their polyline that way.
        /^\s*return\s*`\$\{[^`]*\},\s*?\$\{[^`]*\}`\s*;?\s*$/.test(line) ||
        /style=\{\{\s*$|style\s*=\s*\{$/.test(prev),
    },
    {
      name: 'catch-fallback',
      why: 'A fallback that runs because Intl already refused. Asking Intl again in the handler is how a handled failure becomes an unhandled one.',
      // Twenty-two currency helpers have this shape, and converting them was
      // silently wrong until `fmtCurrency`'s own fallback was rewritten into a
      // call to `fmtFixed` and the recursion showed up as a stack overflow.
      test: (_line, _prev, _index, _scope, inCatch) => inCatch,
    },
    {
      name: 'css-color',
      why: 'A colour channel or an alpha inside rgba()/hsl(), parsed by the CSS engine.',
      test: (line) => /\b(?:rgba?|hsla?)\s*\(/.test(line),
    },
    {
      name: 'geo-coordinate',
      why: 'A latitude or longitude. The convention is universal and a decimal comma is genuinely ambiguous next to the comma that separates the pair.',
      // Stated as an assumption rather than discovered: `52,5200, 13,4050` has
      // four numbers in it as far as a reader can tell. Coordinates therefore
      // stay locale-independent everywhere, on screen as well as on the wire,
      // which is also what every mapping tool that might read them back
      // expects.
      test: (line) => /\b(?:lat|lon|lng|latitude|longitude)\b/i.test(line),
    },
    {
      name: 'export-document',
      why: 'A row of a CSV or spreadsheet export. A file whose separators follow whoever exported it cannot be read back.',
      // Judged by the enclosing function, because the line cannot show it: the
      // 14 rows of the risk export read `P50 (Median),${n.toFixed(2)}` and
      // look exactly like any other template until you notice the function
      // around them is called handleExportCSV.
      //
      // But "export" is not one thing. A CSV is parsed by whatever opens it, so
      // its separators cannot follow the reader's language. A PDF or an HTML
      // report is READ, and a German estimator reading one wants the number
      // written the German way. Both come out of a function called
      // handleExportSomething, so the scope alone would exempt the second along
      // with the first. The sinks that draw a document for a person are named
      // here and excluded, which is why `doc.text` in handleExportSummaryPdf is
      // localised while the CSV built beside it in the same file is not.
      //
      // The sink is matched on the scope as well as the line, because a
      // `doc.text(` call whose arguments span three lines puts the sink out of
      // reach of a line-local test. Only `pdf` and `html` are read off the
      // scope: `report` cannot be, because downloadCostReport and
      // downloadRiskRegisterReport write CSV.
      test: (line, _prev, _index, scope) =>
        /csv|xlsx|excel|clipboard|download|export/i.test(scope) &&
        !/\bdoc\.text\s*\(|\bhtmlParts\b|\bdoc\.splitTextToSize\s*\(/.test(line) &&
        !/pdf|html/i.test(scope),
    },
    {
      name: 'canvas-3d',
      why: 'A canvas or scene-graph coordinate consumed by a rendering API, not by a person.',
      test: (line) =>
        /\b(?:ctx|canvas|camera|mesh|geometry|scene|raycast|THREE|Vector3|position\.|rotation\.|quaternion|shader|uniform|gl_)\b/.test(
          line,
        ),
    },
    {
      name: 'wire-api',
      why: 'The value goes back over the wire, where the server and every other reader expect a dot and no grouping.',
      // Deliberately narrow. An earlier version exempted any `key: n.toFixed(1),`
      // line, which is the shape of an API payload AND the shape of the data
      // a chart tooltip is built from, so it hid 40-odd visible numbers behind
      // a rule nobody would think to question. An object literal now has to
      // name a request to be exempt here; the rest are argued one at a time.
      test: (line, prev) =>
        /\b(?:apiPost|apiPut|apiPatch|apiGet|apiDelete|fetch|JSON\.stringify|URLSearchParams|searchParams|mutateAsync)\s*\(/.test(
          line,
        ) ||
        /\b(?:body|payload|variables|requestBody)\s*[:.]/.test(line) ||
        /(?:apiPost|apiPut|apiPatch|apiDelete|mutateAsync)\s*\([^)]*(?:,\s*)?\{\s*$/.test(prev),
    },
    {
      name: 'react-key',
      why: 'A React key or a DOM id: an identity, and an identity that changes with the reader is a bug.',
      test: (line) => /\bkey\s*=|\bkey\s*:|\bid\s*=|\bid\s*:|data-testid|\bhtmlFor\b/.test(line),
    },
    {
      name: 'log-throw',
      why: 'A developer-facing string. Developers read the repository language, not the reader language.',
      test: (line) => /console\.|logger\.|throw new|new Error\(|\.warn\(|\.debug\(/.test(line),
    },
    {
      name: 'storage-file',
      why: 'Persisted or exported bytes. A file whose separators follow whoever happened to export it cannot be read back.',
      test: (line) =>
        /localStorage|sessionStorage|new Blob\(|download|filename|fileName|\.csv|\.xlsx|href\s*=|URL\.createObjectURL|toDataURL/.test(
          line,
        ),
    },
  ];
/* MACHINE-RULES:END */

/**
 * The names of the functions a line sits inside, outermost last, which is how a
 * rule asks what the surrounding code is FOR when the line itself will not say.
 *
 * Walked by indentation rather than by proximity. Taking simply the nearest
 * declaration above finds the closest local binding instead of the function:
 * the rows of the change-management CSV export reported their scope as `esc`
 * and `areaLabel`, two little helpers declared just above them, and the
 * `handleExport` around the whole thing was never seen.
 */
const scopeOf: (lines: readonly string[], index: number) => string =
  /* SCOPE-HELPER:START */
  (lines, index) => {
    const declaration =
      /\b(?:function|const|let)\s+([A-Za-z_$][\w$]*)\s*(?:=\s*(?:async\s*)?(?:\(|useCallback|useMemo|function)|\()/;
    const indentOf = (line: string) => (line.match(/^[ \t]*/)?.[0] ?? '').length;
    const names = [];
    let outermost = indentOf(lines[index] ?? '');
    for (let i = index - 1; i >= 0; i--) {
      const line = lines[i] ?? '';
      if (!line.trim()) continue;
      const lead = indentOf(line);
      if (lead >= outermost) continue;
      outermost = lead;
      const found = line.match(declaration);
      if (found) {
        names.push(found[1] ?? '');
        if (lead === 0) break;
      } else if (lead === 0) {
        // A function whose parameters are listed one per line closes with
        // `): Promise<void> {` in column zero, and stopping there finds the
        // end of the signature instead of the name in front of it. Step over
        // the closing line and keep going; anything else at column zero really
        // is the outside of the file.
        if (!/^\s*[)\]]/.test(line)) break;
        outermost = 1;
      }
    }
    return names.join(' ');
  };
/* SCOPE-HELPER:END */

/** Whether a line sits inside a `catch` block. */
const inCatchOf: (lines: readonly string[], index: number) => boolean =
  /* CATCH-HELPER:START */
  (lines, index) => {
    // Right to left, so the brace that opens the enclosing block is identified
    // rather than netted out. `} catch {` closes one block and opens another
    // on the same line, and counting the line as a whole cancels the two and
    // walks straight past the catch, which is what made a first attempt at
    // this report nothing at all.
    let depth = 0;
    for (let i = index - 1; i >= 0; i--) {
      const line = lines[i] ?? '';
      for (let k = line.length - 1; k >= 0; k--) {
        const char = line[k];
        if (char === '}') depth++;
        else if (char === '{') {
          depth--;
          if (depth < 0) return /\bcatch\b/.test(line.slice(0, k));
        }
      }
    }
    return false;
  };
/* CATCH-HELPER:END */

interface Hit {
  file: string;
  line: number;
  shape: string;
  text: string;
}

function browserLocaleSites(text: string, file = ''): Hit[] {
  const hits: Hit[] = [];
  text.split('\n').forEach((raw, index) => {
    const line = raw.replace(/\r$/, '');
    if (COMMENT.test(line)) return;
    for (const shape of SHAPES) {
      const found = line.match(shape.re);
      if (!found) continue;
      const exempt = ALLOWED.some((a) => a.file === file && line.includes(a.snippet));
      if (exempt) continue;
      for (let k = 0; k < found.length; k++) {
        hits.push({ file, line: index + 1, shape: shape.name, text: line.trim() });
      }
    }
  });
  return hits;
}

/**
 * Sites where a locale-independent number is right for a reason no rule above
 * expresses. Snippet-scoped like the list above, so an exemption covers the
 * one line it was argued for and not the file around it.
 */
const FIXED_ALLOWED: ReadonlyArray<{ file: string; snippet: string; why: string }> =
  /* FIXED-ALLOWED:START */
  [
  {
    file: 'features/finance/FinancePage.tsx',
    snippet: 'unit_rate: lineAmount.toFixed(2),',
    why: 'A field of the invoice line posted to the API, which parses it as a decimal.',
  },
  {
    file: 'features/finance/FinancePage.tsx',
    snippet: 'amount: lineAmount.toFixed(2),',
    why: 'The same invoice line, same request. Grouping it would reach the server as a different number.',
  },
  {
    file: 'features/procurement/ProcurementPage.tsx',
    snippet: 'amount_subtotal: String(poSubtotal.toFixed(2)),',
    why: 'Body of the purchase order POST, read by the server rather than by a person.',
  },
  {
    file: 'features/procurement/ProcurementPage.tsx',
    snippet: 'amount_total: String(poTotal.toFixed(2)),',
    why: 'Body of the purchase order POST, read by the server rather than by a person.',
  },
  {
    file: 'features/procurement/ProcurementPage.tsx',
    snippet: 'updated.amount = (qty * rate).toFixed(2);',
    why: 'Recalculates the amount field of the line being edited, which is submitted as typed.',
  },
  {
    file: 'features/property-dev/PropertyDevPage.tsx',
    snippet: 'amount: String(outstanding.toFixed(2)),',
    why: 'Seeds the payment form whose amount goes to markInstalmentPaid untouched.',
  },
  {
    file: 'features/bim/AddToBOQModal.tsx',
    snippet: 'setQuantity(quantitySuggestion.value.toFixed(3));',
    why: 'Fills a numeric input the submit handler parses back, so it has to stay parseable.',
  },
  {
    file: 'features/bim/AddToBOQModal.tsx',
    snippet: 'setQuantity(d.quantity.toFixed(3));',
    why: 'Fills a numeric input the submit handler parses back, so it has to stay parseable.',
  },
  {
    file: 'features/projects/CreateProjectPage.tsx',
    snippet: 'setRegionalFactorStr(clampFactor(regionalFactorStr).toFixed(2))',
    why: 'Normalises the text in a numeric field on blur; the same string is parsed on submit.',
  },
  {
    file: 'features/dashboard/components/DashboardBackdrop.tsx',
    snippet: 'const a1 = (0.2 * effIntensity).toFixed(3);',
    why: 'An alpha channel interpolated into rgba(), which the CSS parser reads.',
  },
  {
    file: 'features/dashboard/components/DashboardBackdrop.tsx',
    snippet: 'const a2 = (0.06 * effIntensity).toFixed(3);',
    why: 'An alpha channel interpolated into rgba(), which the CSS parser reads.',
  },
  {
    file: 'shared/lib/formatters.ts',
    snippet: 'if (!Number.isFinite(value)) return value.toFixed(decimals);',
    why: 'fmtFixed handing a non-finite value back rather than inventing a zero for it. This is the replacement.',
  },
  {
    file: 'shared/lib/formatters.ts',
    snippet: 'if (!Number.isFinite(value)) return value.toPrecision(digits);',
    why: 'fmtPrecision handing a non-finite value back rather than inventing a zero for it. This is the replacement.',
  },
  {
    file: 'shared/lib/formatters.ts',
    snippet: "return Number.isFinite(value) ? value.toFixed(decimals) : '';",
    why: 'fmtNumberForInput, the whole body of it. A field a person is editing takes one spelling and it is this one, so the absence of a locale here is the feature (#466).',
  },
  {
    file: 'modules/gaeb-exchange/data/gaebExport.ts',
    snippet: 'return value.toFixed(decimals);',
    why: 'Writes a decimal into GAEB XML 3.3, which is a data format with its own grammar, not a screen.',
  },
  {
    file: 'features/takeoff/lib/takeoff-export.ts',
    snippet: 'return n.toFixed(precision);',
    why: 'Formats the quantity column of the takeoff export file, which is read back by a spreadsheet.',
  },
  {
    file: 'features/geo-hub/utils.ts',
    snippet: 'return `${sign}${Math.abs(value).toFixed(4)}°`;',
    why: 'Renders a coordinate in degrees, which keeps the universal convention for the same reason latitudes do.',
  },
  ];
/* FIXED-ALLOWED:END */

function fixedDecimalSites(text: string, file = ''): Hit[] {
  const hits: Hit[] = [];
  const lines = text.split('\n').map((raw) => raw.replace(/\r$/, ''));
  lines.forEach((line, index) => {
    if (COMMENT.test(line)) return;
    // Cheap test first: `scopeOf` walks back up the file, so asking it about
    // every line of the tree turns the scan quadratic for no reason.
    if (!/\.to(?:Fixed|Precision|Exponential)\s*\(/.test(line)) return;
    const prev = index > 0 ? (lines[index - 1] ?? '') : '';
    const scope = scopeOf(lines, index);
    const inCatch = inCatchOf(lines, index);
    for (const shape of FIXED_SHAPES) {
      shape.re.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = shape.re.exec(line)) !== null) {
        if (MACHINE.some((rule) => rule.test(line, prev, match!.index, scope, inCatch))) continue;
        if (FIXED_ALLOWED.some((a) => a.file === file && line.includes(a.snippet))) continue;
        hits.push({ file, line: index + 1, shape: shape.name, text: line.trim() });
      }
    }
  });
  return hits;
}

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    // Locale files hold translated data, not formatting calls.
    if (name === 'node_modules' || name === 'locales' || name === '__tests__') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, found);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      found.push(full);
    }
  }
  return found;
}

describe('every number and date is written in the language the reader picked', () => {
  const original = i18next.language;
  afterAll(() => {
    void i18next.changeLanguage(original || 'en');
  });

  it('finds no call site that asks the browser instead', () => {
    const offenders = sourceFiles(SRC).flatMap((file) => {
      const rel = relative(SRC, file).replace(/\\/g, '/');
      return browserLocaleSites(readFileSync(file, 'utf8'), rel).map((h) => `${h.file}:${h.line}  ${h.text}`);
    });

    // 308 of these existed across 140 files. Pass `getIntlLocale()` from
    // `shared/lib/formatters` as the first argument, or call one of the
    // fmt* helpers in that module.
    expect(offenders).toEqual([]);
  }, 60_000);

  it('is looking at real files, so an empty result means something', () => {
    // A tree walk that visits nothing also finds no offenders, so the size of
    // the walk is asserted rather than logged: vitest's default reporter drops
    // console output from a passing file, so a printed count is visible only
    // in the run where it is already too late to matter. Failing here reports
    // the real number ("expected 0 to be greater than 500") in the one run
    // that needs it.
    expect(sourceFiles(SRC).length).toBeGreaterThan(500);
  }, 60_000);

  it('lists every deliberate exemption, so adding one shows up as a diff', () => {
    expect(ALLOWED.map((a) => `${a.file} :: ${a.snippet}`)).toEqual([
      "features/match-elements/MatchWizardFlow.tsx :: ?? 'Match'} - ${new Date().toLocaleDateString()}",
      'features/reporting/ReportingPage.tsx :: ${template.name} - ${new Date().toLocaleDateString()}',
      'shared/lib/formatters.ts :: return n.toLocaleString();',
      'shared/lib/numberFormat.ts :: new Intl.NumberFormat(undefined, base)',
      'test/setup.ts :: new Intl.DateTimeFormat().resolvedOptions().timeZone',
    ]);
    // Every exemption states why it is one.
    expect(ALLOWED.filter((a) => a.why.length < 20)).toEqual([]);
  });

  it('and each exemption still describes a line that is really there', () => {
    // An allowlist entry whose snippet has drifted out of the file is an
    // exemption nobody can see any more, and it would silently cover the next
    // bare call that happens to land on a line containing the same text.
    const stale = ALLOWED.filter(
      (a) => !readFileSync(join(SRC, a.file), 'utf8').includes(a.snippet),
    ).map((a) => a.file);
    expect(stale).toEqual([]);
  });

  it('still recognises a browser-locale read in each of the shapes it takes', () => {
    expect(browserLocaleSites('const s = n.toLocaleString();')).toHaveLength(1);
    expect(browserLocaleSites('const s = n.toLocaleString(undefined, { maximumFractionDigits: 2 });')).toHaveLength(1);
    expect(browserLocaleSites('const s = d.toLocaleDateString();')).toHaveLength(1);
    expect(browserLocaleSites("const s = d.toLocaleTimeString(undefined, { hour: '2-digit' });")).toHaveLength(1);
    expect(browserLocaleSites('const f = new Intl.NumberFormat();')).toHaveLength(1);
    expect(browserLocaleSites('const f = new Intl.NumberFormat(undefined, { style: "percent" });')).toHaveLength(1);
    expect(browserLocaleSites('const f = new Intl.DateTimeFormat(undefined, { year: "numeric" });')).toHaveLength(1);
    // A call broken across lines still starts a line with the method, and one
    // line can carry the shape twice.
    expect(browserLocaleSites(['const s = value', '  .toLocaleString();'].join('\n'))).toHaveLength(1);
    expect(browserLocaleSites('<>{a.toLocaleString()}/{b.toLocaleString()}</>')).toHaveLength(2);
  });

  it('and leaves a call that names its locale alone', () => {
    expect(browserLocaleSites('const s = n.toLocaleString(getIntlLocale());')).toEqual([]);
    expect(browserLocaleSites('const s = n.toLocaleString(getIntlLocale(), { maximumFractionDigits: 2 });')).toEqual([]);
    expect(browserLocaleSites("const s = n.toLocaleString('en-US');")).toEqual([]);
    expect(browserLocaleSites('const s = n.toLocaleString(locale, opts);')).toEqual([]);
    expect(browserLocaleSites('const f = new Intl.NumberFormat(getIntlLocale(), { style: "percent" });')).toEqual([]);
    // Prose describing the defect is not the defect.
    expect(browserLocaleSites(' * falls back to `n.toLocaleString()` so calls never throw')).toEqual([]);
    expect(browserLocaleSites('// never write n.toLocaleString() here')).toEqual([]);
  });

  it('and exempts an allowlisted line only in its own file', () => {
    const snippet = ALLOWED[3]!.snippet;
    expect(browserLocaleSites(`    return ${snippet};`, 'shared/lib/numberFormat.ts')).toEqual([]);
    expect(browserLocaleSites(`    return ${snippet};`, 'features/boq/BOQListPage.tsx')).toHaveLength(1);
  });

  it('finds no toFixed on a number a person reads', () => {
    const offenders = sourceFiles(SRC).flatMap((file) => {
      const rel = relative(SRC, file).replace(/\\/g, '/');
      return fixedDecimalSites(readFileSync(file, 'utf8'), rel).map((h) => `${h.file}:${h.line}  ${h.text}`);
    });

    // 508 of these existed across 178 files. Call `fmtFixed` from
    // `shared/lib/formatters` instead, or `fmtPercent` where the call is
    // followed by a literal `%`. If the number is genuinely not for reading,
    // it belongs to one of the MACHINE rules above or, failing those, to
    // FIXED_ALLOWED with the argument written down.
    expect(offenders).toEqual([]);
  }, 60_000);

  it('recognises a fixed-decimal number wherever it is written', () => {
    expect(fixedDecimalSites('<span>{row.qty.toFixed(2)}</span>')).toHaveLength(1);
    expect(fixedDecimalSites('return `${v.toFixed(1)} ${unit}`;')).toHaveLength(1);
    expect(fixedDecimalSites('const s = n.toPrecision(3);')).toHaveLength(1);
    expect(fixedDecimalSites('const s = n.toExponential(2);')).toHaveLength(1);
    // One line, two numbers, two findings.
    expect(fixedDecimalSites('<>{a.toFixed(2)} / {b.toFixed(2)}</>')).toHaveLength(2);
    // Prose about the defect is not the defect.
    expect(fixedDecimalSites(' * `${n.toFixed(1)}%` is the shape this replaces')).toEqual([]);
  });

  it('leaves the shapes where a locale-independent number is the requirement', () => {
    // Parsed straight back, so it is a rounding idiom.
    expect(fixedDecimalSites('const q = Number(waste.toFixed(2));')).toEqual([]);
    expect(fixedDecimalSites("const m = String(Number(fromMeters(real, 'm').toFixed(4)));")).toEqual([]);
    expect(fixedDecimalSites('const q = +value.toFixed(2);')).toEqual([]);
    // ...but coercing FIRST and formatting after is an ordinary display call,
    // and reading those two as one shape is what hid 60 visible numbers.
    expect(fixedDecimalSites('<td>{Number(row.total_score).toFixed(1)}</td>')).toHaveLength(1);
    // Downstream string surgery that assumes the separator is a dot.
    expect(fixedDecimalSites("const s = n.toFixed(2).replace(/\\.?0+$/, '');")).toEqual([]);
    expect(fixedDecimalSites('if (a.toFixed(2) === b.toFixed(2)) return;')).toEqual([]);
    // ...but a decimal count that is itself an expression is not a comparison.
    expect(fixedDecimalSites('return `${v.toFixed(Math.abs(v) < 10 ? 1 : 0)} kg`;')).toHaveLength(1);
    // CSS, SVG and colours.
    expect(fixedDecimalSites('<div style={{ width: `${pct.toFixed(1)}%` }} />')).toEqual([]);
    expect(fixedDecimalSites('stops.push(`${seg.color} ${angle.toFixed(1)}deg`);')).toEqual([]);
    expect(fixedDecimalSites('return `rgba(34,197,94,${alpha.toFixed(3)})`;')).toEqual([]);
    // ...but a unit with a space in front of it is a unit a person reads.
    expect(fixedDecimalSites('return `${pixels.toFixed(1)} px (uncal)`;')).toHaveLength(1);
    // Coordinates, keys and developer-facing strings.
    expect(fixedDecimalSites('const label = `${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}`;')).toEqual([]);
    expect(fixedDecimalSites('const key = `${p[0].toFixed(8)},${p[1].toFixed(8)}`;')).toEqual([]);
    expect(fixedDecimalSites('console.log(`took ${ms.toFixed(1)}ms`);')).toEqual([]);
  });

  it('reads the enclosing function when the line cannot say what it is for', () => {
    // The 14 rows of the risk export look like any other template until you
    // notice what they are inside, which is the whole reason a rule gets the
    // surrounding scope and not just the line.
    const asExport = ['  const handleExportCSV = useCallback(() => {', '    lines.push(`Mean,${r.mean.toFixed(2)}`);'].join(
      '\n',
    );
    const asLabel = ['  const MeanTile = () => {', '    lines.push(`Mean,${r.mean.toFixed(2)}`);'].join('\n');
    expect(fixedDecimalSites(asExport)).toEqual([]);
    expect(fixedDecimalSites(asLabel)).toHaveLength(1);
  });

  it('lists every argued toFixed exemption, so adding one shows up as a diff', () => {
    // Seventeen entries covering nineteen sites in ten files, against 139
    // exempted by a rule.
    // The ratio is the point: rules carry the categories that repeat, and
    // anything left over has to be argued in a sentence someone can disagree
    // with. A list long enough to skim is a list nobody reads.
    expect(FIXED_ALLOWED.map((a) => `${a.file} :: ${a.snippet}`)).toEqual([
      'features/finance/FinancePage.tsx :: unit_rate: lineAmount.toFixed(2),',
      'features/finance/FinancePage.tsx :: amount: lineAmount.toFixed(2),',
      'features/procurement/ProcurementPage.tsx :: amount_subtotal: String(poSubtotal.toFixed(2)),',
      'features/procurement/ProcurementPage.tsx :: amount_total: String(poTotal.toFixed(2)),',
      'features/procurement/ProcurementPage.tsx :: updated.amount = (qty * rate).toFixed(2);',
      'features/property-dev/PropertyDevPage.tsx :: amount: String(outstanding.toFixed(2)),',
      'features/bim/AddToBOQModal.tsx :: setQuantity(quantitySuggestion.value.toFixed(3));',
      'features/bim/AddToBOQModal.tsx :: setQuantity(d.quantity.toFixed(3));',
      'features/projects/CreateProjectPage.tsx :: setRegionalFactorStr(clampFactor(regionalFactorStr).toFixed(2))',
      'features/dashboard/components/DashboardBackdrop.tsx :: const a1 = (0.2 * effIntensity).toFixed(3);',
      'features/dashboard/components/DashboardBackdrop.tsx :: const a2 = (0.06 * effIntensity).toFixed(3);',
      'shared/lib/formatters.ts :: if (!Number.isFinite(value)) return value.toFixed(decimals);',
      'shared/lib/formatters.ts :: if (!Number.isFinite(value)) return value.toPrecision(digits);',
      "shared/lib/formatters.ts :: return Number.isFinite(value) ? value.toFixed(decimals) : '';",
      'modules/gaeb-exchange/data/gaebExport.ts :: return value.toFixed(decimals);',
      'features/takeoff/lib/takeoff-export.ts :: return n.toFixed(precision);',
      'features/geo-hub/utils.ts :: return `${sign}${Math.abs(value).toFixed(4)}°`;',
    ]);
    expect(FIXED_ALLOWED.filter((a) => a.why.length < 20)).toEqual([]);
    const stale = FIXED_ALLOWED.filter(
      (a) => !readFileSync(join(SRC, a.file), 'utf8').includes(a.snippet),
    ).map((a) => a.file);
    expect(stale).toEqual([]);
  });

  it('writes a fixed-decimal number in the reader language without inventing one', async () => {
    // A number follows the format preference, and `auto` is what hands that
    // decision back to the interface language. This asserts the `auto` half,
    // so it names the setting rather than inheriting it: the day the default
    // stops being `auto`, these lines go red at a change that broke nothing.
    usePreferencesStore.setState({ numberLocale: 'auto' });
    await i18next.init({ lng: 'en', resources: {}, initImmediate: false });
    await i18next.changeLanguage('en');
    expect(fmtFixed(12550880.81, 2)).toBe('12,550,880.81');
    await i18next.changeLanguage('de');
    expect(fmtFixed(12550880.81, 2)).toBe('12.550.880,81');

    // The reason this helper exists rather than `fmtNumber`. `fmtNumber` turns
    // anything it cannot read into 0, which is right for a value off the wire
    // and wrong for a sweep: `NaN.toFixed(2)` says NaN today, and rewriting
    // 500 call sites into a confident `0,00` would trade a formatting bug for
    // a costing one.
    expect(fmtFixed(NaN, 2)).toBe('NaN');
    expect(fmtFixed(Number.POSITIVE_INFINITY, 2)).toBe('Infinity');
    expect(fmtNumber(NaN, 2)).toBe('0,00');
  });

  it('resolves the tag a date is written with', async () => {
    await i18next.init({ lng: 'en', resources: {}, initImmediate: false });
    await i18next.changeLanguage('en');
    const inEnglish = (12550880.81).toLocaleString(getIntlLocale(), { minimumFractionDigits: 2 });
    await i18next.changeLanguage('de');
    const inGerman = (12550880.81).toLocaleString(getIntlLocale(), { minimumFractionDigits: 2 });

    // The literal is a probe of the tag, not the shape of a call site: a
    // number passes `getNumberLocale()` now and only a date still passes
    // this one. Separators are the sharpest thing a tag moves, which is why
    // a number reads it here.
    expect(inEnglish).toBe('12,550,880.81');
    expect(inGerman).toBe('12.550.880,81');
  });
});
