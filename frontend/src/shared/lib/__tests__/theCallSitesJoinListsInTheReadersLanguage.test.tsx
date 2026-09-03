// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The companion to `aListIsJoinedInTheReadersLanguage`, and the reason there
// are two files rather than one.
//
// That file proves the HELPER is right: given a list, `fmtList` writes it the
// way the reader's language writes a list. It passes whether or not a single
// screen in the product ever calls it. A helper test cannot tell a sweep that
// converted a hundred call sites from a sweep that converted none, because the
// thing it measures - the helper - is identical in both worlds.
//
// This file measures the wiring instead. It drives two real call sites, one
// through the DOM and one as the pure function an AG Grid column calls, and
// asks whether the text a reader actually receives changes with the language.
//
// Two call sites do not earn the plural in the filename, though, and a green
// run that reads as a claim about all of them would be worse than no test: the
// reader would believe something stronger than what was checked. So the last
// describe block closes the gap from the other end. It censuses the whole
// product for the `join(', ')` this sweep replaced and pins what is left,
// which turns "these two work" into "these two work, and nothing else bypasses
// the helper without a recorded reason".
//
// Every assertion is written to FAIL against the `join(', ')` this replaced.
// That constraint is the whole point: `expect(text).toBe('Ada, Grace, Linus')`
// under English passes just as well against a hardcoded Latin comma, so an
// English-only assertion is not evidence of anything. English is asserted here
// only as an invariant - the change must be invisible to English readers - and
// it is always paired with a non-Latin language asserted on the same value.
//
// Following the house rule from `formatCompactCurrency.test.ts`: the exact
// glyphs belong to the engine's CLDR data and move between ICU versions, so
// what is pinned is the property that was broken, not today's byte string.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

import i18next from 'i18next';
import { render } from '@testing-library/react';
import { afterAll, afterEach, describe, expect, it } from 'vitest';

import { auditRowTooltip } from '@/features/boq/grid/auditMarkers';
import { PresenceAvatars } from '@/modules/collaboration/components/PresenceAvatars';
import { usePresenceStore, type PresenceUser } from '@/modules/collaboration/hooks/usePresence';

void i18next.init({ lng: 'en', resources: {}, initImmediate: false });
const original = i18next.language;
afterAll(() => {
  void i18next.changeLanguage(original);
});

/* ── Call site 1: a tooltip rendered into the DOM ──────────────────────── */

const NAMES = ['Ada', 'Grace', 'Linus'];

const user = (id: string, name: string): PresenceUser => ({
  id,
  name,
  email: `${id}@example.test`,
  color: '#336699',
  boqId: 'boq-1',
  lastSeen: 0,
});

function seedPresence(): void {
  usePresenceStore.setState({
    remoteUsers: Object.fromEntries(
      NAMES.map((name, i) => [`u${i}`, user(`u${i}`, name)] as const),
    ),
  });
}

/** The avatar stack's `title`, rendered in `lang`. */
async function stackTooltip(lang: string): Promise<string> {
  await i18next.changeLanguage(lang);
  seedPresence();
  const { container } = render(<PresenceAvatars boqId="boq-1" />);
  const stack = container.firstElementChild as HTMLElement | null;
  return stack?.getAttribute('title') ?? '';
}

afterEach(() => {
  usePresenceStore.setState({ remoteUsers: {} });
});

describe('PresenceAvatars tooltip', () => {
  it('leaves the English reader exactly where the hand-written join left them', async () => {
    // Asserted so a regression in the OTHER direction is caught too: this
    // sweep is meant to be invisible to English and Russian, and a helper
    // that started writing "Ada, Grace and Linus" into a tooltip would be a
    // new bug wearing the fix's clothes.
    expect(await stackTooltip('en')).toBe(NAMES.join(', '));
  });

  it('gives a Japanese reader their own enumeration mark', async () => {
    const text = await stackTooltip('ja');
    // The assertion that the replaced code could not have passed.
    expect(text).not.toBe(NAMES.join(', '));
    expect(text).not.toContain(', ');
    expect(text).toContain('、');
    for (const name of NAMES) expect(text).toContain(name);
  });

  it('gives an Arabic reader a separator from their own script', async () => {
    const text = await stackTooltip('ar');
    expect(text).not.toBe(NAMES.join(', '));
    expect(text).not.toContain(', ');
    for (const name of NAMES) expect(text).toContain(name);
  });

  it('separates the items in Chinese instead of running them together', async () => {
    // Kills `type: 'unit'` at the call site, not just in the helper. In CLDR
    // that type is a list of measurements and zh joins it with nothing at
    // all, so a tooltip would read "AdaGraceLinus" - a worse bug than the one
    // being fixed, and one no length-blind assertion would notice.
    const text = await stackTooltip('zh');
    expect(text.length).toBeGreaterThan(NAMES.join('').length);
  });
});

/* ── Call site 2: the pure function an AG Grid column calls ────────────── */

/** Minimal i18next stand-in: resolve the default and interpolate. */
const t = (key: string, opts?: Record<string, unknown>): string => {
  let out = String(opts?.defaultValue ?? key);
  if (opts) {
    for (const [k, v] of Object.entries(opts)) {
      if (k === 'defaultValue') continue;
      out = out.replace(new RegExp(`{{${k}}}`, 'g'), String(v));
    }
  }
  return out;
};

const ROW = {
  metadata: { audit: { status: 'warnings', groups: ['missing_items', 'duplicates'], count: 2 } },
};

async function tooltipIn(lang: string): Promise<string> {
  await i18next.changeLanguage(lang);
  return auditRowTooltip(ROW, t) ?? '';
}

describe('auditRowTooltip', () => {
  it('joins the audit groups in the reader language, not in English', async () => {
    const en = await tooltipIn('en');
    const ja = await tooltipIn('ja');
    // Two languages compared on the SAME input. Either one alone is a claim
    // about that language; the inequality is the claim about the code.
    expect(ja).not.toBe(en);
    expect(en).toContain('Missing items, Duplicates');
    expect(ja).toContain('Missing items、Duplicates');
  });

  it('keeps working where the surrounding sentence is translated', async () => {
    // The separator is inside an interpolated `{{groups}}`, so the sentence
    // around it comes from the locale while the punctuation between the items
    // comes from CLDR. Both have to survive; a list that lost an item would
    // still read as a complete list, which is the silent failure worth
    // guarding.
    for (const lang of ['en', 'ja', 'ar', 'de']) {
      const text = await tooltipIn(lang);
      expect(text, `${lang} dropped a group`).toContain('Missing items');
      expect(text, `${lang} dropped a group`).toContain('Duplicates');
    }
  });
});

/* ── The population those two call sites stand for ─────────────────────── */

// A shrink list, not an allowlist, following `Header.titleKeys.test.ts`. Every
// entry names a file, how many literal comma-joins it still holds, and why it
// keeps them. A file that gets converted goes red because its count no longer
// matches, and it has to leave the list rather than sit at zero; a file that
// grows a new one goes red because the count moved. Nothing may be added
// without a reason on the same line, which is the only thing that stops this
// decaying into a list of things somebody once decided not to look at.
//
// The reasons are load-bearing, not decoration. `Intl.ListFormat` writes the
// reader's word for "and" into the string, so a separator that leaves the UI
// for a machine has to stay a plain comma: a CSS value list, a query sent to a
// geocoder, an RFC 5322 address header, or a value joined into a text input
// that gets split apart again on save. Converting one of those is not a
// cosmetic mistake, it is a data bug, and it is the main way this sweep could
// have done harm.
type Excluded = { file: string; sites: number; why: string };

const KEPT_AS_PLAIN_COMMAS: readonly Excluded[] = [
  // Joined to seed a text input, split back apart when the form is saved.
  { file: 'features/correspondence/CorrespondencePage.tsx', sites: 2, why: 'round-trip form field' },
  { file: 'features/forms/TemplateBuilder.tsx', sites: 4, why: 'round-trip form field' },
  { file: 'features/phonelog/PhoneLogEditDialog.tsx', sites: 1, why: 'round-trip form field' },
  { file: 'features/phonelog/RecordingProtocolCard.tsx', sites: 1, why: 'round-trip form field' },
  { file: 'features/subcontractors/SubcontractorsPage.tsx', sites: 1, why: 'round-trip form field' },
  { file: 'features/match-elements/StageAdjustSheet.tsx', sites: 2, why: 'round-trip form field' },
  // `formatList` there reads like a display helper and is not one: its own test
  // asserts that `parseList(formatList(x))` round-trips. The name is the trap.
  { file: 'features/cases/caseDraft.ts', sites: 1, why: 'serialiser paired with parseList' },

  // A localised separator in any of these is invalid CSS.
  { file: 'features/boq/CostBreakdownPanel.tsx', sites: 1, why: 'CSS value list' },
  { file: 'features/pointcloud/PointCloudViewer.tsx', sites: 1, why: 'CSS value list' },
  { file: 'shared/ui/BIMViewer/BIMViewer.tsx', sites: 4, why: 'CSS value list' },

  // Prompt text assembled for a model, not prose shown to a reader.
  { file: 'shared/ui/BIMViewer/elementQuestion.ts', sites: 7, why: 'LLM prompt construction' },

  // User-visible, and still wrong for this helper: CLDR formats an address as
  // an address, not as a list, so "Berlin and Germany" would be a new bug.
  { file: 'features/geo-hub/GeoModePicker.tsx', sites: 1, why: 'address line, not a list' },
  { file: 'features/geo-hub/ProjectGeoPage.tsx', sites: 1, why: 'address line, not a list' },
  { file: 'features/projects/ProjectDetailPage.tsx', sites: 1, why: 'address line, not a list' },
  { file: 'features/projects/ProjectsPage.tsx', sites: 1, why: 'address line, not a list' },
  { file: 'shared/ui/ProjectMap/geocode.ts', sites: 1, why: 'query string sent to a geocoder' },

  { file: 'features/inbound-email/InboundEmailPanel.tsx', sites: 2, why: 'RFC 5322 address header' },
  { file: 'features/eac/components/blocks/ConstraintBlock.tsx', sites: 1, why: 'set notation, {a, b}' },
  { file: 'features/pipelines/canvas/PipelineNode.tsx', sites: 1, why: 'arbitrary value stringify' },
  { file: 'features/smart_views/SmartViewRuleEditor.tsx', sites: 1, why: 'arbitrary value stringify' },
  // The labels around it are hardcoded English, so the document is English by
  // construction and one localised separator would read as an accident.
  { file: 'features/boq/pdfReport.ts', sites: 1, why: 'English-only generated PDF' },
  // A postal address writes its own separators; a list conjunction between
  // the lines of one address would read as two addresses.
  { file: 'features/projects/clients.ts', sites: 2, why: 'postal address line' },
  // Both of these fill a text INPUT that is parsed back on save, so the
  // separator is the field's syntax rather than prose the reader is meant
  // to read. Writing "a, b and c" into the box would round-trip as a value
  // called "b and c".
  { file: 'modules/team-standup/engine/engine.ts', sites: 1, why: 'editable comma-separated field' },
  { file: 'modules/work-requests/ManageDepartmentsPage.tsx', sites: 1, why: 'editable comma-separated field' },
];

/** `.join(', ')` and `.join(", ")`, and neither `.join('; ')` nor `.join(',')`. */
const COMMA_JOIN = /\.join\((['"]), \1\)/g;

/** `frontend/src`, whether vitest was started from the repo root or `frontend`. */
function sourceRoot(): string {
  const root = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')].find((p) =>
    existsSync(p),
  );
  if (!root) throw new Error(`cannot locate frontend/src from ${process.cwd()}`);
  return root;
}

/** Product code only. Tests and fixtures may join however they like, and the
 *  helper's own module holds the fallback this whole sweep routes through. */
function productFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry !== '__tests__' && entry !== 'node_modules') productFiles(full, out);
    } else if (/\.tsx?$/.test(entry) && !/\.(test|spec)\.tsx?$/.test(entry) && entry !== 'formatters.ts') {
      out.push(full);
    }
  }
  return out;
}

describe('the rest of the product', () => {
  const root = sourceRoot();
  const files = productFiles(root);
  const found = new Map<string, number>();
  for (const file of files) {
    const n = (readFileSync(file, 'utf8').match(COMMA_JOIN) ?? []).length;
    if (n > 0) found.set(file.slice(root.length + 1).replace(/\\/g, '/'), n);
  }

  it('measures a population big enough for the three assertions below to mean anything', () => {
    // Guards the instrument, not the product. A walk that resolved the wrong
    // root, or a regex that quietly stopped matching, returns an empty map and
    // every assertion after this one passes while checking nothing at all.
    expect(files.length).toBeGreaterThan(2000);
    expect([...found.values()].reduce((a, b) => a + b, 0)).toBe(40);
  });

  it('routes every list a reader sees through the helper, except the recorded ones', () => {
    const recorded = new Set(KEPT_AS_PLAIN_COMMAS.map((e) => e.file));
    const unrecorded = [...found.keys()].filter((f) => !recorded.has(f)).sort();
    expect(
      unrecorded,
      'These join a list with a hardcoded ", ", which is wrong in Arabic and ' +
        'in Chinese and Japanese. Use `fmtList` from @/shared/lib/formatters. ' +
        'If the string is read by a machine rather than by a person, add it to ' +
        'KEPT_AS_PLAIN_COMMAS with the reason.',
    ).toEqual([]);
  });

  it('holds each recorded exclusion at exactly the count it was recorded with', () => {
    const moved = KEPT_AS_PLAIN_COMMAS.filter((e) => (found.get(e.file) ?? 0) !== e.sites).map(
      (e) => `${e.file}: recorded ${e.sites} (${e.why}), found ${found.get(e.file) ?? 0}`,
    );
    expect(
      moved,
      'A count moved. If you converted one, lower the count or drop the entry: ' +
        'this list may only shrink.',
    ).toEqual([]);
  });

  it('holds no entry that has already been fixed', () => {
    // A shrink list decays into an allowlist the moment a dead entry is allowed
    // to sit in it, so a file at zero has to leave rather than be tolerated.
    const dead = KEPT_AS_PLAIN_COMMAS.filter((e) => !found.has(e.file)).map((e) => e.file);
    expect(dead, 'Already fixed. Remove from KEPT_AS_PLAIN_COMMAS.').toEqual([]);
  });
});
