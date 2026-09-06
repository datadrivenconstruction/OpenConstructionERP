#!/usr/bin/env node
/* ================================================================
 * compose-case-layers.mjs
 *
 * Composes a family spine plus one country layer into the playbook
 * files the rest of the pipeline already reads, at
 * frontend/src/features/cases/data/<slug>.playbook.ts.
 *
 * The problem this exists for: a country case today is a whole page
 * written again. Nine countries means nine copies of the same workflow,
 * and the pack list is longer than that (fourteen countries as of
 * 2026-09-05, counted with the commands below rather than remembered). Here the workflow is written once as a
 * spine with slots, and a country is a small file that says which steps
 * it surfaces, in what order, and what its own words are for the things
 * the slots name.
 *
 * Nothing downstream changes. This writes a normal playbook, and then
 * generate-case-page.mjs, add_case_rail.py, put_case_face.py,
 * generate-cases.mjs, generate-gallery.mjs and generate-sitemap.mjs run
 * exactly as they do now.
 *
 * WHAT BELONGS WHERE
 *   spine  - the sentences. Written once, translated once, shared by
 *            every country in the family.
 *   layer  - slot values (proper nouns and numbers, the same in every
 *            language), which steps it surfaces and in what order, and
 *            the module each step routes to. Routing is a fact about
 *            our product, not prose, so it is layer-owned and costs no
 *            translation.
 *
 * THE RULE THAT KEEPS IT HONEST
 *   A layer may carry an `override` on a step, replacing a spine
 *   sentence outright. One is a country genuinely being different. Two
 *   layers overriding the SAME step is not: it means the spine sentence
 *   was written too narrowly, and the fix is to widen it with a slot
 *   rather than to let every country carry its own copy. So that case
 *   fails the build and names both countries and the step. This is a
 *   gate rather than a comment because a rule that lives only in prose
 *   gets broken by the fifth country, and by then it is thirty pages of
 *   overrides and the family has quietly become nine pages again.
 *
 *   A second gate came out of composing rather than out of designing. Two
 *   slots that a sentence contrasts must not resolve to the same value.
 *   The neutral page called both the valuation and the payment document
 *   an "interim application", so "raise the {payDoc} against the approved
 *   {valuationDoc}" composed to "raise the interim application against
 *   the approved interim application" and shipped. A hand-written page
 *   never says this, because a person reads it. A composed page says it
 *   because the whole point is that nobody reads every composition, so
 *   the things a reader would have caught have to be caught here.
 *
 *   The same reasoning, with a different remedy, covers the indefinite
 *   article: "A {valuationDoc}" is right for one country and wrong for
 *   the next, and which one is not knowable when the sentence is
 *   written. That one the composer simply fixes, because it is
 *   mechanical, and only for plain lowercase words, because "an RFI" is
 *   correct and a rule that rewrote it would be doing the damage.
 *
 * WHAT THE GATES CANNOT CATCH
 *   Two slots holding distinct but swapped values. The collapse gate sees
 *   two slots resolving to ONE value; it cannot see two slots resolving to
 *   the WRONG two. A layer that named the payment claim as the valuation
 *   document and the tax invoice as the payment document passed every gate
 *   and composed "Open a clock over the tax invoice starting from the day
 *   the payment claim is served", which is fluent and is not what the
 *   Construction Contracts Act says. It was found by reading the prose.
 *
 *   The obvious gate for it is wrong, and this is measured rather than
 *   assumed. "clockStart must reference payDoc" holds for AU ES HU NZ SA
 *   XX and fails for BR DE MX RU ZA, and those five are all correct:
 *   Brazil counts from the attestation of the boletim de medicao, Germany
 *   from the client receiving the verifiable statement, Mexico from the
 *   authorisation of the estimacion, Russia from the signing of the KS-2
 *   act, South Africa from the interim payment certificate. The rule would
 *   fail five correct layers on its first run. Worse, the broken NZ layer
 *   was structurally identical to the correct ZA one: a tax invoice in
 *   payDoc and a different document in clockStart. Only knowing which
 *   document the statute counts from separates them, and the composer does
 *   not have that and cannot derive it.
 *
 *   So a new layer needs its composed prose read once by somebody who knows
 *   the jurisdiction. The gates remove the failures a reader would not
 *   catch; they do not remove the reader.
 *
 * WHY IT IS WORTH DOING
 *   Not for the pages we already have. Rewriting the existing 72 country
 *   pages this way is about a 2.4x saving on prose that is already
 *   written, which is a real number and a weak argument.
 *
 *   The argument is the pages that do not exist. Page-per-country grows
 *   as workflows times countries, because every pair is a whole page
 *   written and then translated into every locale. The spine shape grows
 *   as workflows plus workflows times countries, where the second term
 *   is a small slot file and not prose. That is roughly an order of
 *   magnitude across the pack list, and more importantly it is the
 *   difference between a cost that scales with the product of two
 *   growing numbers and one that scales with their sum.
 *
 *   Count the inputs rather than trusting this comment. An earlier
 *   version of it said fifteen pack countries and the real number was
 *   fourteen:
 *     ls packs | wc -l                                    directories
 *     find packs -name manifest.py | grep -c /src/         loadable packs
 *     grep -rhoE '"country": "[A-Z]{2}"' packs --include=manifest.py
 *   Measured 2026-09-05: 21 directories, 20 loadable (aus-nzs has no
 *   manifest), 14 distinct countries, AU BR CA CN DE GB HU IN MX NZ RU
 *   SA US ZA. XX appears too and is the neutral pack, not a country.
 *
 *   None of the conclusion rested on the fifteenth country. We are not
 *   buying a discount on the pages we already have, we are buying the
 *   ability to add the remaining countries at all.
 *
 * WHAT THIS DOES NOT YET DO
 *   Translate once. Keys are still minted per page, so a spine sentence
 *   three countries share is still three keys and three translations,
 *   and `keyRoot` on the spine is declared and read by nothing. That was
 *   deliberate: keeping the existing per-page keys is what made the
 *   migration cost zero retranslations. Realising the saving needs the
 *   spine sentences translated under their own keys and expanded per
 *   page with slots filled at merge time, which is not built. Until it
 *   is, `--sharing` reports what is actually shared rather than what the
 *   design would allow, and the two numbers are not the same.
 *
 * Usage:
 *   node frontend/scripts/compose-case-layers.mjs --family f01-progress-payment
 *   node frontend/scripts/compose-case-layers.mjs --family f01-progress-payment --check
 *   node frontend/scripts/compose-case-layers.mjs --family f01-progress-payment --dry-run
 *   node frontend/scripts/compose-case-layers.mjs --all
 *
 *   --check    compose in memory and diff against what is on disk.
 *              Exits 1 on any drift. This is the gate that says the
 *              committed playbooks are still what the spine produces.
 *   --dry-run  report what would be written, write nothing.
 *   --only CC[,CC]  write only these countries' pages. The gates still run
 *              over the whole family, because they are about relationships
 *              between layers; this narrows the files touched, which is
 *              what you want when several people add layers to one family.
 *   --keys     print the locale key delta (added / orphaned) and exit.
 *   --sharing  of the spine fields more than one country uses, how many
 *              compose to identical English. That is the number that
 *              could be translated once; the rest carry slot values and
 *              differ per country by design.
 * ================================================================ */

import { readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = resolve(SCRIPT_DIR, '..');
const REPO_ROOT = resolve(FRONTEND_ROOT, '..');
const DEFAULT_INTL_DIR = join(REPO_ROOT, 'frontend/src/features/cases/intl');
const DEFAULT_DATA_DIR = join(REPO_ROOT, 'frontend/src/features/cases/data');

/* Rebound by --intl-dir / --data-dir so the gates can be tested against a
 * fixture family instead of against the real one. */
let INTL_DIR = DEFAULT_INTL_DIR;
let SPINE_DIR = join(INTL_DIR, 'spines');
let LAYER_DIR = join(INTL_DIR, 'layers');
let DATA_DIR = DEFAULT_DATA_DIR;

function rebind(intlDir, dataDir) {
  INTL_DIR = intlDir || DEFAULT_INTL_DIR;
  SPINE_DIR = join(INTL_DIR, 'spines');
  LAYER_DIR = join(INTL_DIR, 'layers');
  DATA_DIR = dataDir || DEFAULT_DATA_DIR;
}

/* ---------------------------------------------------------------- */
/* args                                                              */
/* ---------------------------------------------------------------- */

function parseArgs(argv) {
  const out = { families: [], all: false, check: false, dryRun: false, keys: false, sharing: false, only: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--family') out.families.push(argv[++i]);
    else if (a === '--all') out.all = true;
    else if (a === '--check') out.check = true;
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--keys') out.keys = true;
    else if (a === '--sharing') out.sharing = true;
    else if (a === '--only') out.only = new Set(argv[++i].split(',').map((c) => c.trim().toUpperCase()));
    else if (a === '--intl-dir') out.intlDir = resolve(argv[++i]);
    else if (a === '--data-dir') out.dataDir = resolve(argv[++i]);
    else if (a === '--help' || a === '-h') out.help = true;
    else {
      console.error(`compose-case-layers: unknown argument ${a}`);
      process.exit(2);
    }
  }
  return out;
}

/* ---------------------------------------------------------------- */
/* slots                                                             */
/* ---------------------------------------------------------------- */

const SLOT_RE = /\{([A-Za-z0-9_]+)\}/g;

function slotsUsed(text) {
  const found = new Set();
  let m;
  SLOT_RE.lastIndex = 0;
  while ((m = SLOT_RE.exec(text)) !== null) found.add(m[1]);
  return found;
}

function fill(text, slots, where, errors) {
  return text.replace(SLOT_RE, (whole, name) => {
    if (!(name in slots)) {
      errors.push(`${where}: no value for slot {${name}}`);
      return whole;
    }
    return slots[name];
  });
}

/* "a" or "an" depends on the sound of the word that follows, and after a
 * slot is filled that word is whatever the layer supplied. The spine cannot
 * know it: "A {valuationDoc}" is right for "certificacion" and wrong for
 * "interim valuation". Both spellings appeared on the neutral page.
 *
 * Sound rather than spelling, so the two classes the vowel rule gets wrong
 * are listed. Anything not listed follows the vowel. */
const AN_BEFORE_CONSONANT = /^(hour|honest|honor|honour|heir)/i;
const A_BEFORE_VOWEL = /^(uni|use|usu|util|euro|ubiquit|one|once)/i;

/* Only a plain lowercase word. An initialism takes its article from the name
 * of its first letter, so "an RFI" and "an SLA" are correct and rewriting them
 * would be the repair causing the damage. Slots hold common nouns, which is
 * where the defect was, so that is all this touches. */
function fixArticles(text) {
  return text.replace(/\b([Aa])(n?) ([a-z][a-z-]*)\b/g, (whole, a, n, word) => {
    const vowel = /^[aeiou]/.test(word);
    const needsAn = (vowel && !A_BEFORE_VOWEL.test(word)) || AN_BEFORE_CONSONANT.test(word);
    if (needsAn === (n === 'n')) return whole;
    return `${a}${needsAn ? 'n' : ''} ${word}`;
  });
}

/* Sentence-initial slots produce a lowercase first letter when the slot
 * value is a common noun. Capitalise what the sentence needs without
 * touching a proper noun that is already capitalised. */
function sentenceCase(text) {
  return text.replace(/(^|[.!?]\s+)([a-z])/g, (_, lead, ch) => lead + ch.toUpperCase());
}

/* ---------------------------------------------------------------- */
/* chips                                                             */
/* ---------------------------------------------------------------- */

/* A chip is written either as "Some label" or as { key, label }. The
 * explicit key form is what keeps an existing page's locale keys
 * unchanged; the bare string is for chips that have no history yet. */
function chipKey(chip) {
  if (typeof chip === 'object' && chip.key) return chip.key;
  const label = typeof chip === 'string' ? chip : chip.label;
  const word = label.replace(SLOT_RE, '').trim().split(/\s+/)[0] || 'item';
  return word.toLowerCase().replace(/[^a-z0-9]/g, '');
}

function chipLabel(chip) {
  return typeof chip === 'string' ? chip : chip.label;
}

/* ---------------------------------------------------------------- */
/* loading                                                           */
/* ---------------------------------------------------------------- */

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (err) {
    console.error(`compose-case-layers: cannot read ${path}\n  ${err.message}`);
    process.exit(2);
  }
}

function loadFamily(family) {
  const spinePath = join(SPINE_DIR, `${family}.json`);
  if (!existsSync(spinePath)) {
    console.error(`compose-case-layers: no spine at ${spinePath}`);
    process.exit(2);
  }
  const spine = readJson(spinePath);
  const dir = join(LAYER_DIR, family);
  if (!existsSync(dir)) {
    console.error(`compose-case-layers: no layer directory at ${dir}`);
    process.exit(2);
  }
  const layers = readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((f) => ({ ...readJson(join(dir, f)), _file: join(dir, f) }));
  return { spine, layers };
}

function discoverFamilies() {
  if (!existsSync(SPINE_DIR)) return [];
  return readdirSync(SPINE_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => basename(f, '.json'))
    .sort();
}

/* ---------------------------------------------------------------- */
/* gates                                                             */
/* ---------------------------------------------------------------- */

/* THE OVERRIDE GATE.
 *
 * A step override is a spine bug. One layer overriding a step is a
 * country that is genuinely different and we accept it. Two layers
 * overriding the same step means the spine sentence is too narrow, and
 * the repair is to widen the sentence with a slot, not to keep adding
 * copies. Fails loudly with both jurisdictions and the step named,
 * because the person who trips this needs to know what to rewrite. */
function overrideGate(family, layers) {
  const byStep = new Map();
  for (const layer of layers) {
    for (const step of layer.steps || []) {
      if (!step.override) continue;
      const spineStep = step.spine || step.id;
      for (const field of Object.keys(step.override)) {
        const slot = `${spineStep}.${field}`;
        if (!byStep.has(slot)) byStep.set(slot, []);
        byStep.get(slot).push(layer.jurisdiction);
      }
    }
  }
  const clashes = [];
  for (const [slot, who] of byStep) {
    if (who.length > 1) clashes.push({ slot, who: who.sort() });
  }
  if (!clashes.length) return true;

  console.error('');
  console.error('  ================================================================');
  console.error('  SPINE BUG. The same step is overridden by more than one country.');
  console.error('  ================================================================');
  for (const c of clashes) {
    const [spineStep, field] = c.slot.split('.');
    console.error('');
    console.error(`    family ${family}`);
    console.error(`    step   ${spineStep}`);
    console.error(`    field  ${field}`);
    console.error(`    layers ${c.who.join(', ')}`);
  }
  console.error('');
  console.error('  Two countries needing the same sentence rewritten means the');
  console.error('  sentence is too narrow, not that the countries are special.');
  console.error(`  Widen it in spines/${family}.json with a slot both can fill,`);
  console.error('  then delete both overrides. Do not add a third.');
  console.error('');
  return false;
}

/* Every step a layer names has to exist in the spine, or the layer is
 * pointing at a sentence nobody wrote. */
function mappingGate(family, spine, layers) {
  const errors = [];
  for (const layer of layers) {
    const seen = new Set();
    for (const step of layer.steps || []) {
      const spineStep = step.spine || step.id;
      if (!spine.steps[spineStep]) {
        errors.push(`${layer.jurisdiction}: step "${step.id}" maps to spine step "${spineStep}", which the spine does not define`);
      }
      if (seen.has(step.id)) errors.push(`${layer.jurisdiction}: step id "${step.id}" appears twice`);
      seen.add(step.id);
    }
    if (!layer.slug) errors.push(`${layer.jurisdiction}: no slug`);
  }
  if (errors.length) {
    console.error(`\n  compose-case-layers: ${family} does not compose\n`);
    for (const e of errors) console.error(`    ${e}`);
    console.error('');
    return false;
  }
  return true;
}

/* ---------------------------------------------------------------- */
/* composition                                                       */
/* ---------------------------------------------------------------- */

function keyBase(slug) {
  return `cases.${slug.replace(/-/g, '_')}`;
}

function composeLayer(spine, layer, errors) {
  const base = keyBase(layer.slug);
  const slots = layer.slots || {};
  const steps = [];

  for (const mapped of layer.steps || []) {
    const spineStep = spine.steps[mapped.spine || mapped.id];
    const ov = mapped.override || {};
    const shared = {};
    const where = `${layer.jurisdiction}/${mapped.id}`;

    /* A field is either shared or it is not.
     *
     *   spine only          - one sentence serves every country in the family
     *                         and is translated once.
     *   spine + layer note  - the country has something to say that no slot
     *                         can carry, a paragraph of its own law. The note
     *                         is appended and the field stops being shared:
     *                         its key now holds national prose and has to be
     *                         translated per country.
     *   override            - the spine sentence is discarded outright. One
     *                         country doing this is tolerated; two doing it to
     *                         the same step fails the build, because that is
     *                         the spine sentence being wrong rather than the
     *                         countries being special.
     *
     * `shared` counts the first kind, and it is the number that decides
     * whether this design pays for itself. */
    /* Two placeholders meant to contrast, resolving to one value.
   * The spine sentence "raise the {payDoc} against the approved
   * {valuationDoc}" is about two documents. Where a country calls both by the
   * same name it composes to a tautology, which reads as a mistake because it
   * is one. Caught here rather than by a reader, because the whole point of a
   * spine is that nobody reads every composed page. */
  const collapseCheck = (field, template, where) => {
    const used = [...new Set([...String(template).matchAll(/\{(\w+)\}/g)].map((m) => m[1]))];
    for (let i = 0; i < used.length; i++) {
      for (let j = i + 1; j < used.length; j++) {
        const a = slots[used[i]];
        const b = slots[used[j]];
        if (a === undefined || b === undefined) continue;
        if (String(a).trim().toLowerCase() !== String(b).trim().toLowerCase()) continue;
        errors.push(
          `SLOT COLLAPSE  ${layer.jurisdiction}  ${where}.${field}\n` +
            `      {${used[i]}} and {${used[j]}} both resolve to "${a}"\n` +
            `      so the sentence contrasts a thing with itself:\n` +
            `        ${String(template).replace(/\{(\w+)\}/g, (mm, n) => slots[n] ?? mm)}\n` +
            `      Give the country distinct terms, or rewrite the spine sentence so it\n` +
            `      does not name both, or let this one country override the step.`
        );
      }
    }
  };

  const text = (field) => {
      const overridden = field in ov;
      const raw = overridden ? ov[field] : spineStep[field];
      const note = (mapped.note || {})[field];
      shared[field] = !overridden && !note;
      const joined = note ? `${raw} ${note}` : raw;
      collapseCheck(field, joined, where);
      return sentenceCase(fixArticles(fill(joined, slots, `${where}.${field}`, errors)));
    };

    const chips = (field) =>
      (mapped[field] || ov[field] || spineStep[field] || []).map((chip) => ({
        key: `${base}.step.${mapped.id}.${field}.${chipKey(chip)}`,
        label: sentenceCase(fill(chipLabel(chip), slots, `${where}.${field}`, errors)),
      }));

    /* Once each. text() reports collapses and unfilled slots as a side
     * effect, so calling it twice for the same field reports the same defect
     * twice. */
    const title = text('title');
    const what = text('what');
    const why = text('why');

    steps.push({
      id: mapped.id,
      icon: mapped.icon || spineStep.icon,
      inputs: chips('in'),
      outputs: chips('out'),
      titleKey: `${base}.step.${mapped.id}.title`,
      titleDefault: title,
      whatKey: `${base}.step.${mapped.id}.what`,
      whatDefault: what,
      whyKey: `${base}.step.${mapped.id}.why`,
      whyDefault: why,
      moduleLabel: mapped.module || spineStep.module,
      moduleLabelKey: mapped.moduleKey || spineStep.moduleKey,
      to: mapped.to || spineStep.to,
      /* which spine sentence this step is a rendering of. Carried so the
       * translation path can expand one spine template into every page
       * that uses it, and so a reader of the playbook can see the family
       * behind it. */
      _spine: mapped.spine || mapped.id,
      _shared: shared,
      _english: { title, what, why },
    });
  }

  return {
    id: layer.slug,
    order: layer.order,
    region: layer.region,
    category: layer.category,
    companyTypes: layer.companyTypes,
    roles: layer.roles,
    icon: layer.icon,
    titleKey: `${base}.title`,
    titleDefault: layer.title,
    descKey: `${base}.desc`,
    descDefault: layer.desc,
    longDescKey: layer.longDesc ? `${base}.longdesc` : undefined,
    longDescDefault: layer.longDesc,
    estMinutes: layer.estMinutes,
    steps,
  };
}

/* ---------------------------------------------------------------- */
/* emission                                                          */
/* ---------------------------------------------------------------- */

function ts(value) {
  return JSON.stringify(value);
}

function emitChips(chips, indent) {
  if (!chips.length) return '[],';
  let out = '[\n';
  for (const chip of chips) {
    out += `${indent}  {\n`;
    out += `${indent}    labelKey: ${ts(chip.key)},\n`;
    out += `${indent}    label: ${ts(chip.label)},\n`;
    out += `${indent}  },\n`;
  }
  out += `${indent}],`;
  return out;
}

function emitPlaybook(family, spine, layer, pb) {
  const L = [];
  L.push('// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP');
  L.push('// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction');
  L.push('//');
  L.push(`// Case: "${pb.titleDefault}"${pb.region ? ` (${pb.region})` : ''}.`);
  L.push('//');
  L.push('// GENERATED. Do not edit this file by hand, the next compose run');
  L.push('// will overwrite it. The workflow lives once at');
  L.push(`//   frontend/src/features/cases/intl/spines/${family}.json`);
  L.push('// and this country\'s words and step order live at');
  L.push(`//   frontend/src/features/cases/intl/layers/${family}/${layer.jurisdiction}.json`);
  L.push('//');
  if (layer.note) {
    for (const line of wrap(layer.note, 68)) L.push(`// ${line}`);
    L.push('//');
  }
  L.push('// Rebuild with:');
  L.push(`//   node frontend/scripts/compose-case-layers.mjs --family ${family}`);
  L.push('');
  L.push('import type { Playbook } from "../types";');
  L.push('');
  L.push('const playbook: Playbook = {');
  L.push(`  id: ${ts(pb.id)},`);
  L.push(`  order: ${pb.order},`);
  if (pb.region) L.push(`  region: ${ts(pb.region)},`);
  L.push(`  category: ${ts(pb.category)},`);
  L.push(`  companyTypes: [${pb.companyTypes.map(ts).join(', ')}],`);
  L.push(`  roles: [${pb.roles.map(ts).join(', ')}],`);
  L.push(`  icon: ${ts(pb.icon)},`);
  L.push(`  titleKey: ${ts(pb.titleKey)},`);
  L.push(`  titleDefault: ${ts(pb.titleDefault)},`);
  L.push(`  descKey: ${ts(pb.descKey)},`);
  L.push(`  descDefault:`);
  L.push(`    ${ts(pb.descDefault)},`);
  if (pb.longDescKey) {
    L.push(`  longDescKey: ${ts(pb.longDescKey)},`);
    L.push(`  longDescDefault:`);
    L.push(`    ${ts(pb.longDescDefault)},`);
  }
  L.push(`  estMinutes: ${pb.estMinutes},`);
  L.push('  steps: [');
  for (const s of pb.steps) {
    L.push('    {');
    L.push(`      id: ${ts(s.id)},`);
    L.push(`      icon: ${ts(s.icon)},`);
    L.push(`      inputs: ${emitChips(s.inputs, '      ')}`);
    L.push(`      outputs: ${emitChips(s.outputs, '      ')}`);
    L.push(`      titleKey: ${ts(s.titleKey)},`);
    L.push(`      titleDefault: ${ts(s.titleDefault)},`);
    L.push(`      whatKey: ${ts(s.whatKey)},`);
    L.push(`      whatDefault:`);
    L.push(`        ${ts(s.whatDefault)},`);
    L.push(`      whyKey: ${ts(s.whyKey)},`);
    L.push(`      whyDefault:`);
    L.push(`        ${ts(s.whyDefault)},`);
    L.push(`      moduleLabel: ${ts(s.moduleLabel)},`);
    L.push(`      moduleLabelKey: ${ts(s.moduleLabelKey)},`);
    L.push(`      to: ${ts(s.to)},`);
    L.push('    },');
  }
  L.push('  ],');
  L.push('};');
  L.push('');
  L.push('export default playbook;');
  L.push('');
  /* The playbooks in this tree are CRLF. Build with \n throughout, since
   * the chip blocks are multi-line strings, then convert once at the end so
   * a diff against the committed file is content rather than line endings. */
  return L.join('\n').replace(/\r?\n/g, '\r\n');
}

function wrap(text, width) {
  const words = text.split(/\s+/);
  const lines = [];
  let line = '';
  for (const w of words) {
    if (line && line.length + 1 + w.length > width) {
      lines.push(line);
      line = w;
    } else line = line ? `${line} ${w}` : w;
  }
  if (line) lines.push(line);
  return lines;
}

/* ---------------------------------------------------------------- */
/* key accounting                                                    */
/* ---------------------------------------------------------------- */

/* Every key the composed pages reference. The deploy-day gate is that
 * this set does not shrink: a key that disappears is a translation in
 * four complete locales that stops being reachable, and nothing else in
 * the pipeline notices. */
function keysOf(pb) {
  const keys = new Set([pb.titleKey, pb.descKey]);
  if (pb.longDescKey) keys.add(pb.longDescKey);
  for (const s of pb.steps) {
    keys.add(s.titleKey);
    keys.add(s.whatKey);
    keys.add(s.whyKey);
    for (const c of s.inputs) keys.add(c.key);
    for (const c of s.outputs) keys.add(c.key);
  }
  return keys;
}

function keysOnDisk(slug) {
  const path = join(DATA_DIR, `${slug}.playbook.ts`);
  if (!existsSync(path)) return new Set();
  const src = readFileSync(path, 'utf8');
  const keys = new Set();
  const re = /"(cases\.[A-Za-z0-9_.]+)"/g;
  let m;
  while ((m = re.exec(src)) !== null) keys.add(m[1]);
  return keys;
}

/* ---------------------------------------------------------------- */
/* main                                                              */
/* ---------------------------------------------------------------- */

function run(family, args) {
  const { spine, layers } = loadFamily(family);

  if (!mappingGate(family, spine, layers)) return { ok: false };
  if (!overrideGate(family, layers)) return { ok: false };

  const errors = [];
  const results = [];
  for (const layer of layers) {
    const pb = composeLayer(spine, layer, errors);
    results.push({ layer, pb, text: emitPlaybook(family, spine, layer, pb) });
  }

  /* No sentence may reach a reader with a slot still in it. A key that
   * resolves is not enough; the value has to be a sentence. */
  for (const r of results) {
    const leftover = slotsUsed(r.text);
    if (leftover.size) {
      errors.push(`${r.layer.jurisdiction}: unfilled slots reach the page: ${[...leftover].map((s) => `{${s}}`).join(', ')}`);
    }
  }

  if (errors.length) {
    console.error(`\n  compose-case-layers: ${family} does not compose\n`);
    for (const e of errors) console.error(`    ${e}`);
    console.error('');
    return { ok: false };
  }

  /* key accounting, before anything is written */
  let added = 0;
  let orphaned = 0;
  const orphanList = [];
  for (const r of results) {
    const now = keysOnDisk(r.layer.slug);
    const next = keysOf(r.pb);
    for (const k of next) if (!now.has(k)) added++;
    for (const k of now) if (!next.has(k)) { orphaned++; orphanList.push(k); }
  }

  if (args.sharing) {
    /* Of the spine sentences more than one country uses, how many compose to
     * the SAME English? Only those can be translated once and reused. A
     * sentence carrying a slot composes differently per country, so it still
     * costs one translation per page per language until the spine templates
     * are translated under their own keys and expanded per page. */
    const groups = new Map();
    for (const r of results) {
      for (const st of r.pb.steps) {
        for (const field of ['title', 'what', 'why']) {
          const id = `${st._spine}.${field}`;
          if (!groups.has(id)) groups.set(id, []);
          groups.get(id).push({ jur: r.layer.jurisdiction, english: st._english[field] });
        }
      }
    }
    let multi = 0;
    let identical = 0;
    let divergent = 0;
    const divergentList = [];
    for (const [id, uses] of [...groups].sort()) {
      if (uses.length < 2) continue;
      multi++;
      const same = uses.every((u) => u.english === uses[0].english);
      if (same) identical++;
      else {
        divergent++;
        divergentList.push(`${id}  [${uses.map((u) => u.jur).join(' ')}]`);
      }
    }
    console.log(`\n  ${family} sharing`);
    console.log(`    spine fields used by 2+ countries : ${multi}`);
    console.log(`    composing to identical English    : ${identical}  <- translatable once`);
    console.log(`    composing differently per country : ${divergent}  <- still one key per page`);
    console.log('');
    for (const d of divergentList) console.log(`      ${d}`);
    console.log('');
    console.log('    A slot makes a sentence country-specific in English, which is correct');
    console.log('    for the reader and is also why it cannot yet be translated once. That');
    console.log('    needs the spine template translated under its own key and expanded per');
    console.log('    page with slots filled, which is not built.');
    console.log('');
    return { ok: true };
  }

  if (args.keys) {
    console.log(`\n  ${family} key delta`);
    console.log(`    added:    ${added}`);
    console.log(`    orphaned: ${orphaned}`);
    for (const k of orphanList) console.log(`      - ${k}`);
    console.log('');
    return { ok: true, added, orphaned };
  }

  /* --check: the committed playbooks must still be what the spine says */
  if (args.check) {
    let drift = 0;
    for (const r of results) {
      const path = join(DATA_DIR, `${r.layer.slug}.playbook.ts`);
      const disk = existsSync(path) ? readFileSync(path, 'utf8') : '';
      if (disk !== r.text) {
        drift++;
        console.error(`  drift: ${r.layer.slug}.playbook.ts differs from what ${family} composes`);
      }
    }
    if (drift) {
      console.error(`\n  ${drift} playbook(s) drifted. Run without --check to rebuild.\n`);
      return { ok: false };
    }
    console.log(`  ${family}: ${results.length} playbook(s) match the spine`);
    return { ok: true };
  }

  for (const r of results) {
    /* --only narrows what is WRITTEN. Everything above this line already ran
     * for the whole family, because the override and collapse gates are about
     * relationships BETWEEN layers and scoping them to one country would turn
     * them off rather than narrow them. */
    if (args.only && !args.only.has(String(r.layer.jurisdiction).toUpperCase())) continue;
    const path = join(DATA_DIR, `${r.layer.slug}.playbook.ts`);
    const before = existsSync(path) ? readFileSync(path, 'utf8') : '';
    const changed = before !== r.text;
    if (!args.dryRun && changed) writeFileSync(path, r.text, 'utf8');
    const steps = r.pb.steps.length;
    let sharedFields = 0;
    let ownFields = 0;
    for (const s of r.pb.steps) {
      for (const f of ['title', 'what', 'why']) {
        if (s._shared[f]) sharedFields++;
        else ownFields++;
      }
    }
    console.log(
      `  ${args.dryRun ? '[dry-run] ' : ''}${r.layer.jurisdiction.padEnd(3)} ${r.layer.slug}` +
        `  ${steps} steps, ${sharedFields} shared / ${ownFields} national` +
        `${changed ? '' : ' (unchanged)'}`
    );
  }
  console.log(`    keys added ${added}, orphaned ${orphaned}`);
  return { ok: true, added, orphaned };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  rebind(args.intlDir, args.dataDir);
  if (args.help) {
    console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8').split('*/')[0]);
    return;
  }
  const families = args.all ? discoverFamilies() : args.families;
  if (!families.length) {
    console.error('compose-case-layers: name a family with --family, or --all');
    process.exit(2);
  }
  console.log(`${args.dryRun ? '[dry-run] ' : ''}compose-case-layers`);
  let bad = 0;
  for (const family of families) {
    const res = run(family, args);
    if (!res.ok) bad++;
  }
  if (bad) process.exit(1);
}

main();
