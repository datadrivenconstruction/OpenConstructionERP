// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Every template is a module the server would build.
 *
 * A template that fails validation is worse than no template: it is the path
 * offered to the person with no AI and no idea what a column is, and it would
 * strand them on a problem they cannot read. So each one is held to the same
 * checks the wizard holds a hand-built spec to, against the server's real
 * reserved names rather than a fixture's three, and every word it shows has
 * to exist in en.ts.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

import type { Vocabulary } from './api';
import { IDENTIFIER_RE, PYTHON_KEYWORDS, RULE_CODE_RE, specProblems, toWireSpec } from './draft';
import { applyAll } from './suggestions';
import {
  MODULE_TEMPLATES,
  buildFromTemplate,
  templatePhrases,
  templateSuggestions,
  type Translate,
} from './templates';

/** `RESERVED_FIELD_NAMES` in spec.py, plus the column the status feature adds. */
const SERVER_RESERVED_FIELDS = [
  'id', 'project_id', 'created_at', 'updated_at', 'created_by', 'metadata', 'metadata_',
  'registry', 'query', 'self', 'class', 'schema', 'model_config', 'model_fields', 'status',
];

/** The shipped module directories, which `reserved_module_keys` refuses as keys. */
function shippedModuleKeys(): string[] {
  const dir = ['../backend/app/modules', 'backend/app/modules']
    .map((p) => resolve(process.cwd(), p))
    .find(existsSync);
  if (!dir) return [];
  return readdirSync(dir).filter((name) => statSync(resolve(dir, name)).isDirectory());
}

const SHIPPED = shippedModuleKeys();

const VOCABULARY: Vocabulary = {
  field_types: [],
  rule_kinds: [],
  reserved_field_names: SERVER_RESERVED_FIELDS,
  reserved_keys: ['core', 'modules', 'app', 'tests', 'migrations', 'admin', ...SHIPPED],
  max_fields: 40,
  assistant_available: false,
  link_targets: [],
  features: ['status', 'due', 'export', 'comments'],
};

function loadEnglish(): Record<string, string> {
  const file = ['src/app/locales/en.ts', 'frontend/src/app/locales/en.ts']
    .map((p) => resolve(process.cwd(), p))
    .find(existsSync);
  if (!file) throw new Error('en.ts not found: run from frontend or from the repository root');
  const src = readFileSync(file, 'utf8');
  const start = src.indexOf('{', src.indexOf('const resource'));
  const end = src.lastIndexOf('} as ');
  return (new Function(`return ${src.slice(start, end + 1)}`)() as { translation: Record<string, string> })
    .translation;
}

/** Renders the English default, as the real i18next does for a key it holds in en. */
const english: Translate = (_key, options) => String(options?.defaultValue ?? '');

describe('the templates', () => {
  it('are six, with distinct ids and keys', () => {
    expect(MODULE_TEMPLATES).toHaveLength(6);
    expect(new Set(MODULE_TEMPLATES.map((t) => t.id)).size).toBe(6);
    expect(new Set(MODULE_TEMPLATES.map((t) => t.key)).size).toBe(6);
  });

  it('found the shipped module tree to check the keys against', () => {
    // Without it the key check below would pass against nothing.
    expect(SHIPPED.length).toBeGreaterThan(50);
  });

  for (const template of MODULE_TEMPLATES) {
    describe(template.id, () => {
      const spec = buildFromTemplate(template, english);

      it('passes every check the wizard makes, against the real reserved names', () => {
        expect(specProblems(spec, VOCABULARY)).toEqual([]);
      });

      it('still passes with every one of its own suggestions applied', () => {
        const all = applyAll(spec, templateSuggestions(template, english), VOCABULARY);
        expect(specProblems(all, VOCABULARY)).toEqual([]);
      });

      it('checks at least one thing and belongs to a project', () => {
        expect(spec.rules.length).toBeGreaterThanOrEqual(1);
        expect(spec.entity.project_scoped).toBe(true);
      });

      it('keeps its identifiers English snake_case', () => {
        expect(spec.key).toMatch(IDENTIFIER_RE);
        expect(spec.entity.name).toMatch(IDENTIFIER_RE);
        for (const field of spec.entity.fields) {
          expect(field.name).toMatch(IDENTIFIER_RE);
          expect(PYTHON_KEYWORDS.has(field.name)).toBe(false);
        }
        for (const rule of spec.rules) expect(rule.code).toMatch(RULE_CODE_RE);
        for (const state of templateSuggestions(template, english).flatMap((s) => s.patch.status?.states ?? [])) {
          expect(state.code).toMatch(IDENTIFIER_RE);
        }
      });

      it('goes on the wire in the shape a current server accepts', () => {
        const wire = toWireSpec(spec, true);
        expect(wire.schema_version).toBe(2);
        for (const field of wire.entity.fields) expect(field).not.toHaveProperty('target');
      });
    });
  }

  it('has every word it shows in en.ts, with the same English', () => {
    const en = loadEnglish();
    const missing: string[] = [];
    const differ: string[] = [];
    for (const template of MODULE_TEMPLATES) {
      for (const phrase of templatePhrases(template)) {
        if (!(phrase.labelKey in en)) missing.push(phrase.labelKey);
        else if (en[phrase.labelKey] !== phrase.defaultLabel) differ.push(phrase.labelKey);
      }
    }
    expect(missing).toEqual([]);
    expect(differ).toEqual([]);
  });

  it('resolves its words through the translator, not the English default', () => {
    const shout: Translate = (key) => `[${key}]`;
    const spec = buildFromTemplate(MODULE_TEMPLATES[0]!, shout);
    expect(spec.display_name).toBe('[module_builder.tpl.concrete_pours.name]');
    expect(spec.entity.fields[0]?.label).toBe('[module_builder.tpl.concrete_pours.f.reference]');
    // Identifiers do not go through it.
    expect(spec.entity.fields[0]?.name).toBe('reference');
  });

  it('takes the next free key when the plain one is installed already', () => {
    const spec = buildFromTemplate(MODULE_TEMPLATES[0]!, english, ['concrete_pours', 'concrete_pours_2']);
    expect(spec.key).toBe('concrete_pours_3');
  });
});
