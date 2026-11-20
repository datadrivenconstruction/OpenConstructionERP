// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One route, one module chip.
//
// Every playbook step carries a chip: a visible label, the i18n key that label
// is translated through, and the route the chip walks to. The chip is a
// breadcrumb into the sidebar, so two cases sending a reader to the same screen
// have to name that screen the same way. They frequently do not, and the two
// ways that fails are not the same defect:
//
//   * Two different KEYS on one route. Invisible in English whenever both keys
//     happen to render the same word, and visible in every locale where they
//     do not. This is the one that reaches a user, and no English-language
//     review can see it, which is why it needs a machine.
//   * One key under two spellings of the LABEL ('Field Time' / 'Field time').
//     No locale effect at all, because the label is only a fallback for the
//     key. Untidy source, nothing more.
//
// They are reported separately on purpose. Printing an untidy capital letter
// next to a word that comes out wrong in forty-two languages teaches the reader
// to skim both.
//
// Where the right key is disputed, the tie-break is the LIVE NAVIGATION, not
// the playbook majority: the key the sidebar itself puts on that route wins,
// because that is the word the reader sees on arrival. A majority of playbooks
// is a count of authors, not a fact about the destination.
//
// What this file checks is narrower than that tie-break, and the difference
// matters. It enforces that the chips agree with EACH OTHER. It does not
// compare them against `navCatalog.ts`, so a route where every case unanimously
// uses a key the navigation never puts there passes cleanly. Measured
// 2026-08-17 against both live surfaces: 75 routes unanimous and matching, 16
// unanimous and contradicting, 23 split, 7 on routes neither surface carries.
// Those 16 are a separate piece of work with an owner; do not read a green run
// here as "the chips agree with the sidebar".
//
// A third way it fails was invisible to this file until 2026-08-18: a chip
// whose label is not the English value of the key beside it. The three checks
// compared chips with EACH OTHER, so nothing held a label to the thing it
// actually renders, and 170 of 645 chips drifted under a green suite. That one
// reaches a reader too, on the public case pages, which take `moduleLabel` raw.
//
// The baselines below are a shrink list, not an allowlist. They record the
// splits that predate this gate so the suite is not red on arrival, and they
// are compared by exact key set: a baselined route that grows a new variant
// goes red, and so does one that gets fixed, because a fixed route has to leave
// the list. Nothing may be added to any of the three.
//
// LABEL_VALUE_BASELINE goes further and demands a reason on every line, because
// the other two record accidents while that one records decisions, and a
// decision nobody wrote down becomes permission.

import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { PLAYBOOKS } from './playbooks';

/**
 * Routes already carrying more than one key when this gate landed, with the
 * exact keys each one carries. 23 routes across 140 of the 163 case files.
 * Owner: the case-catalogue maintainer. Shrinks only.
 */
const KEY_SPLIT_BASELINE: Record<string, string[]> = {
  '/assets': ['assets.title', 'nav.assets'],
  '/bim/federations': ['nav.bim_federations', 'nav.federations'],
  '/changeorders': ['nav.change_orders', 'nav.changeorders'],
  '/clash': ['clash.title', 'nav.clash'],
  '/closeout': ['closeout.title', 'nav.closeout'],
  '/projects/:projectId/bim': ['bim.title', 'nav.bim', 'nav.bim_viewer'],
  '/projects/:projectId/boq': ['boq.title', 'nav.boq'],
  '/projects/:projectId/contracts': [
    'contracts.title',
    'nav.contracts',
    'onboarding.mod_contracts',
  ],
  '/projects/:projectId/correspondence': ['correspondence.title', 'nav.correspondence'],
  '/projects/:projectId/daily-diary': ['nav.daily_diary', 'onboarding.mod_daily_diary'],
  '/projects/:projectId/finance': ['finance.title', 'nav.finance'],
  '/projects/:projectId/inspections': ['inspections.title', 'nav.inspections', 'nav.ncr'],
  '/projects/:projectId/ncr': ['nav.ncr', 'ncr.title'],
  '/projects/:projectId/procurement': ['nav.procurement', 'procurement.title'],
  '/projects/:projectId/safety': ['nav.safety', 'safety.title'],
  '/projects/:projectId/subcontractors': [
    'nav.subcontractors',
    'onboarding.mod_subcontractors',
    'subcontractors.title',
  ],
  '/projects/new': ['nav.projects', 'nav.projects_new'],
  '/quantities': ['nav.quantities', 'quantities.title'],
  '/reports': ['nav.reporting', 'nav.reports'],
  '/schedule': ['nav.schedule', 'schedule.title'],
  '/schedule-advanced': ['nav.schedule_advanced', 'onboarding.mod_schedule_advanced'],
  '/validation': ['nav.validation', 'validation.title'],
};

/**
 * Routes whose chips agree on the key and disagree on the spelling of the
 * label. Source-only, no locale effect. Same shrink rule.
 *
 * Thirteen routes left this list at once on 2026-08-18, when every chip moved
 * onto the English value of its own key. Settling the value settles the
 * spelling with it: two chips that both render the key's value cannot disagree
 * about how it is written, so this list mostly empties as a side effect of the
 * check below rather than by anyone editing spellings by hand.
 * `/projects/:projectId/rfi` and `/catalog` had left the same way earlier.
 *
 * The one that remains is the one nobody is allowed to settle yet. "BOQ" and
 * "Bill of Quantities" are two names for one document, and which a chip should
 * carry depends on an unsettled question about what that document is called per
 * country. It is deferred by ruling rather than overlooked, which is why it can
 * sit here alone without reading as neglect.
 */
const LABEL_SPLIT_BASELINE: Record<string, string[]> = {
  '/projects/:projectId/boq': ['BOQ', 'Bill of Quantities'],
};

/**
 * Chips whose label is not the English value of the key beside it.
 *
 * The three checks above compare chips with each other. None of them compares a
 * chip with the thing it actually renders, so the trap documented on
 * `moduleLabelKey` in `types.ts` had nothing defending it, and 170 divergences
 * accumulated under a green suite.
 *
 * Why it matters that the label is not dead code: every one of these keys
 * exists in `en.ts`, so `defaultValue` never fires and the label never reaches
 * the app. It reaches the public case pages, which take `moduleLabel` raw from
 * `playbookModules`. So each entry here is one screen that the site and the
 * product call by different words, and a reader clicking through from one to the
 * other has to recognise where they landed.
 *
 * The key's value wins by default: it is what the product shows, and the site
 * describes the product rather than the other way round. An entry here is a
 * claim that this pair is the exception, so it carries its reason on the line.
 * A pair with no reason fails the suite rather than passing quietly, because a
 * baseline of opaque keys hardens into permission while a baseline of reasons
 * stays a worklist.
 *
 * 139 chips across 49 pairs moved onto their key's value on 2026-08-18, and
 * those rows left this list. What remains is five rows of three kinds, and the
 * kinds matter more than the count: one deferral, two approved exceptions where
 * the literal really is the better chip text, and two entries that are not
 * label defects at all.
 *
 * That last kind is here to stay visible, not to be fixed. Each one is a
 * finding about the chip's key or its route, and moving the label would settle
 * the wording while leaving the actual defect in place and no longer reported.
 * A defect that has been made to look tidy stops being counted.
 */
const LABEL_VALUE_BASELINE: readonly (readonly [key: string, label: string, reason: string])[] = [
  // Deferred by ruling, not an exception. The abbreviation sits on top of an
  // unsettled question about what this document is called per country, and a
  // chip alignment must not settle that by accident. `nav.boq`, these labels and
  // the `/projects/:projectId/boq` row of KEY_SPLIT_BASELINE all stay as they are.
  ['boq.title', 'BOQ', 'deferred by ruling: per-country naming of this document is unsettled'],

  // Approved exceptions. The literal is the better chip text, and both survive
  // the same question: what does the reader need at the moment they read it?
  [
    'nav.match_elements',
    'Match Elements',
    'approved exception: the key value carries an arrow, a nav affordance that reads as broken punctuation inline',
  ],
  [
    'nav.clash_detection',
    'Clash Profiles',
    'approved exception: the chip walks to /clash/profiles and the label names that sub-screen, not the module',
  ],

  // Not label defects. Both name something wrong with the chip's key or its
  // route, and aligning the label would tidy the words while leaving the defect
  // in place and unreported. They are stated here so they keep being counted.
  [
    'nav.ncr',
    'Non-conformances',
    'not a label defect: the chip walks to /inspections while keying the NCR module, so route and key disagree',
  ],
  [
    'onboarding.mod_schedule_advanced',
    'Advanced scheduling',
    'not a label defect: the chip keys the onboarding label, whose value is "Schedule Advanced", so aligning would put a second name on a route that already reads "Advanced Schedule"',
  ],
];

/** Resolve `frontend/src` whether vitest was started at `frontend/` or at the repo root. */
function findSrcRoot(): string {
  const root = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')].find((p) =>
    existsSync(join(p, 'app/App.tsx')),
  );
  expect(root, 'could not locate frontend/src from the test working directory').toBeTruthy();
  return root!;
}

/**
 * How many shipped locales render these keys as different words.
 *
 * Only ever called on the failure path. Reading forty-odd locale files costs
 * more than the rest of this suite put together, and a gate slow enough to
 * notice is a gate somebody deletes.
 *
 * A locale that is missing any of the keys is not counted either way: it cannot
 * disagree about a word it does not have, and counting it as agreement would
 * let an untranslated locale hide a real split.
 */
function localeDivergence(
  keys: string[],
  srcRoot: string,
): { diverged: string[]; checked: number } {
  const dir = join(srcRoot, 'app/locales');
  const diverged: string[] = [];
  let checked = 0;
  for (const file of readdirSync(dir)) {
    if (!file.endsWith('.ts') || file === 'index.ts') continue;
    const text = readFileSync(join(dir, file), 'utf8');
    const values = keys.map((k) => {
      const escaped = k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return new RegExp(`"${escaped}":\\s*"((?:[^"\\\\]|\\\\.)*)"`).exec(text)?.[1];
    });
    if (values.some((v) => v === undefined)) continue;
    checked += 1;
    if (new Set(values).size > 1) diverged.push(file.replace(/\.ts$/, ''));
  }
  return { diverged, checked };
}

/**
 * Every key/value pair in `en.ts`, parsed once.
 *
 * Parsed rather than imported because importing the locale drags i18next and the
 * app graph into a worker that needs a lookup table, which is what timed the
 * first version of `Header.titleKeys.test.ts` out.
 */
function englishValues(srcRoot: string): Map<string, string> {
  const text = readFileSync(join(srcRoot, 'app/locales/en.ts'), 'utf8');
  const out = new Map<string, string>();
  // The key half accepts a capital: `approvalRoutes.title` is a real chip key,
  // and a lowercase-only pattern reported it as absent from a file that holds
  // it. A parser that cannot see a key is indistinguishable from a missing key,
  // so it has to be the wider of the two.
  // Both groups are mandatory in these patterns, so a match carries both.
  // The assertions say so to a compiler that reads an index as possibly absent.
  const dq = /["']([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)["']\s*:\s*"((?:[^"\\]|\\.)*)"/g;
  for (let m = dq.exec(text); m; m = dq.exec(text)) out.set(m[1]!, m[2]!.replace(/\\"/g, '"'));
  const sq = /["']([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)["']\s*:\s*'((?:[^'\\]|\\.)*)'/g;
  for (let m = sq.exec(text); m; m = sq.exec(text)) {
    if (!out.has(m[1]!)) out.set(m[1]!, m[2]!.replace(/\\'/g, "'"));
  }
  return out;
}

/** Every chip as it ships, one entry per step so counts are chips and not pairs. */
function chips(): { label: string; key: string; to: string }[] {
  const out: { label: string; key: string; to: string }[] = [];
  for (const pb of PLAYBOOKS) {
    for (const step of pb.steps) {
      if (!step.moduleLabelKey) continue;
      out.push({ label: step.moduleLabel, key: step.moduleLabelKey, to: step.to });
    }
  }
  return out;
}

/** Group every shipped chip by the route it walks to. */
function chipsByRoute(): Map<string, Map<string, Set<string>>> {
  // route -> label -> keys, so both failure shapes fall out of one pass.
  const byRoute = new Map<string, Map<string, Set<string>>>();
  for (const pb of PLAYBOOKS) {
    for (const step of pb.steps) {
      if (!step.moduleLabelKey) continue;
      const labels = byRoute.get(step.to) ?? new Map<string, Set<string>>();
      const keys = labels.get(step.moduleLabel) ?? new Set<string>();
      keys.add(step.moduleLabelKey);
      labels.set(step.moduleLabel, keys);
      byRoute.set(step.to, labels);
    }
  }
  return byRoute;
}

const keysOn = (labels: Map<string, Set<string>>): string[] =>
  [...new Set([...labels.values()].flatMap((s) => [...s]))].sort();

const sameSet = (a: string[], b: string[]): boolean =>
  a.length === b.length && a.every((v, i) => v === b[i]);

describe('module chips name one route one way', () => {
  it('reads every case file the directory holds', () => {
    // The gate is only as wide as its input. Enumerate the directory rather
    // than trusting a list written by hand: a case file added tomorrow has to
    // be inside this check without anybody remembering to add it, and a file
    // that silently fails to register has to be visible as a shortfall rather
    // than as one fewer thing to check.
    const dir = join(findSrcRoot(), 'features/cases/data');
    const onDisk = readdirSync(dir).filter((f) => f.endsWith('.playbook.ts'));
    expect(onDisk.length, 'no case files found, the directory scan is broken').toBeGreaterThan(100);
    expect(
      PLAYBOOKS.length,
      `${onDisk.length} case files on disk but ${PLAYBOOKS.length} registered playbooks: ` +
        'a file is failing to load, and the checks below would pass by not looking at it',
    ).toBe(onDisk.length);
  });

  it('never sends two cases to the same screen under two different keys', () => {
    const srcRoot = findSrcRoot();
    const failures: string[] = [];

    for (const [route, labels] of chipsByRoute()) {
      const keys = keysOn(labels);
      const baseline = KEY_SPLIT_BASELINE[route];

      if (keys.length > 1) {
        if (baseline && sameSet(keys, baseline)) continue;
        const { diverged, checked } = localeDivergence(keys, srcRoot);
        const shown = diverged.slice(0, 8).join(', ');
        const more = diverged.length > 8 ? `, +${diverged.length - 8} more` : '';
        failures.push(
          `${route} is labelled with ${keys.length} different keys: ${keys.join(', ')}. ` +
            `They render different words in ${diverged.length} of ${checked} locales` +
            (diverged.length ? ` (${shown}${more})` : '') +
            '. Pick the key the sidebar puts on this route (navCatalog.ts) and move the ' +
            'others onto it.' +
            (baseline ? ` This route is baselined as [${baseline.join(', ')}]; a new variant appeared.` : ''),
        );
      } else if (baseline) {
        failures.push(
          `${route} now uses one key (${keys[0]}) but is still listed in KEY_SPLIT_BASELINE ` +
            `as [${baseline.join(', ')}]. The split is fixed: delete the entry. The baseline ` +
            'is a shrink list and stale entries make it read as permission.',
        );
      }
    }

    expect(failures, `\n  - ${failures.join('\n  - ')}\n`).toEqual([]);
  });

  it('spells one screen name one way', () => {
    // Label-only disagreement, split out from the check above because it has no
    // effect on any locale: the label is the fallback shown when the key has no
    // translation. Still wrong, still worth one line, not worth alarm.
    //
    // This used to `continue` on any route whose key was split, on the grounds
    // that the key split was already reported. That handed every row of
    // KEY_SPLIT_BASELINE a silent exemption from this check as well, which is
    // how `/projects/:projectId/boq` carried both "BOQ" and "Bill of Quantities"
    // under a green suite. One condition must not disarm another, so the
    // comparison now runs inside each key instead of skipping the route.
    const failures: string[] = [];

    for (const [route, labels] of chipsByRoute()) {
      const byKey = new Map<string, Set<string>>();
      for (const [label, keys] of labels) {
        for (const k of keys) {
          const seen = byKey.get(k) ?? new Set<string>();
          seen.add(label);
          byKey.set(k, seen);
        }
      }
      const spellings = [
        ...new Set([...byKey.values()].filter((s) => s.size > 1).flatMap((s) => [...s])),
      ].sort();
      const baseline = LABEL_SPLIT_BASELINE[route];

      if (spellings.length > 1) {
        if (baseline && sameSet(spellings, baseline)) continue;
        failures.push(
          `${route} is written as ${spellings.map((s) => `"${s}"`).join(' and ')}. ` +
            'No locale is affected, the key is shared. Settle on one spelling.' +
            (baseline ? ` Baselined as [${baseline.join(', ')}]; a new spelling appeared.` : ''),
        );
      } else if (baseline) {
        // Report the labels the route actually carries rather than `spellings[0]`.
        // When a route collapses completely, `spellings` is empty and that index
        // is undefined: the message then read `one spelling ("undefined")`, which
        // looks like a broken check rather than a route that got fixed. Thirteen
        // routes hit exactly that on 2026-08-18.
        const now = [...labels.keys()]
          .sort()
          .map((s) => `"${s}"`)
          .join(' and ');
        failures.push(
          `${route} is no longer written two ways under one key (it now reads ${now}) but is ` +
            'still listed in LABEL_SPLIT_BASELINE. Delete the entry.',
        );
      }
    }

    expect(failures, `\n  - ${failures.join('\n  - ')}\n`).toEqual([]);
  });

  it('states a reason on every baselined label, in a shape that cannot go blank', () => {
    // A reason checked by "is this string non-empty" degrades to '' or 'known'
    // on the next pass. The shape has to carry it: three elements, and a third
    // long enough to be a sentence rather than a placeholder.
    const malformed: string[] = [];
    for (const entry of LABEL_VALUE_BASELINE) {
      const [key, label, reason] = entry;
      if (entry.length !== 3 || typeof reason !== 'string' || reason.trim().length < 12) {
        malformed.push(`[${key}, ${label}] carries no usable reason (got ${JSON.stringify(reason)})`);
      }
    }
    expect(malformed, `\n  - ${malformed.join('\n  - ')}\n`).toEqual([]);

    const seen = new Set(LABEL_VALUE_BASELINE.map(([k, l]) => `${k}\u0000${l}`));
    expect(seen.size, 'LABEL_VALUE_BASELINE lists the same key and label twice').toBe(
      LABEL_VALUE_BASELINE.length,
    );

    // The baseline was drawn against 645 shipped chips. If the population
    // collapses, the check below goes green by having little left to compare
    // and every stale entry then reads as progress.
    expect(
      chips().length,
      'chip population collapsed, the baseline was drawn against 645',
    ).toBeGreaterThan(600);
  });

  it('gives every chip the words its own key renders', () => {
    // The chips reach the reader twice. In the app the key wins, because all of
    // these keys exist in en.ts and a defaultValue is only consulted for a key
    // that resolves to nothing. On the public case pages the label wins, because
    // playbookModules hands moduleLabel to them raw. So a pair that disagrees is
    // one screen called two things, and the reader crossing from the site to the
    // product is the one who pays for it.
    const srcRoot = findSrcRoot();
    const english = englishValues(srcRoot);
    expect(english.size, 'en.ts parsed to almost nothing, the regex is wrong').toBeGreaterThan(5000);

    const allowed = new Map(LABEL_VALUE_BASELINE.map(([k, l, r]) => [`${k}\u0000${l}`, r]));
    const counts = new Map<string, number>();
    const failures: string[] = [];
    const missingKeys: string[] = [];

    for (const { label, key } of chips()) {
      const value = english.get(key);
      if (value === undefined) {
        missingKeys.push(key);
        continue;
      }
      if (value === label) continue;
      const pair = `${key}\u0000${label}`;
      counts.set(pair, (counts.get(pair) ?? 0) + 1);
      if (!allowed.has(pair)) {
        failures.push(
          `${key} renders "${value}" but a chip is labelled "${label}". The key's value wins by ` +
            'default: it is what the product shows. Move the label onto it, or add the pair to ' +
            'LABEL_VALUE_BASELINE with the reason it is the exception.',
        );
      }
    }

    // A key a chip names but en.ts does not hold would make the check above pass
    // by having nothing to compare, and would also mean the chip really does
    // fall back to its label. Neither is true today and both should be loud.
    expect([...new Set(missingKeys)].sort(), 'chip keys absent from en.ts').toEqual([]);

    const stale = [...allowed.keys()]
      .filter((pair) => !counts.has(pair))
      .map((pair) => {
        const [key, label] = pair.split('\u0000');
        return (
          `LABEL_VALUE_BASELINE still allows ${key} to be labelled "${label}", but no chip does ` +
          'that any more. Delete the entry: the list is a worklist and only shrinks.'
        );
      });

    expect([...failures, ...stale], `\n  - ${[...failures, ...stale].join('\n  - ')}\n`).toEqual([]);
  });

  it('keeps both baselines pointed at routes that still exist', () => {
    // A baseline entry for a route no chip walks to any more is dead weight
    // that makes the list look larger than the debt it records.
    const live = new Set(chipsByRoute().keys());
    const dead = [...Object.keys(KEY_SPLIT_BASELINE), ...Object.keys(LABEL_SPLIT_BASELINE)].filter(
      (r) => !live.has(r),
    );
    expect(dead, `baselined routes no chip uses any more: ${dead.join(', ')}`).toEqual([]);
  });
});
