// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The paths this client calls, and the ones it refuses to invent.
 *
 * The transport is mocked one layer lower than usual - `@/shared/lib/api`
 * rather than this module - precisely so the URL is visible. A test that mocks
 * `./api` can prove a component asked for records; only this one can prove it
 * asked the right server for them.
 *
 * The rule under test that matters most: a generated module's `base_path` is
 * whatever the server said it was. If any of these assertions ever has to be
 * loosened because the path is being reassembled from the key, the kebab rule
 * has been copied out of the loader and the two can now drift.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

import {
  createModuleRecord,
  deleteModuleRecord,
  draftSpec,
  fetchInstalledModules,
  fetchModuleRecord,
  fetchModuleRecords,
  fetchModuleUiSpec,
  fetchVocabulary,
  findingsFromError,
  installModule,
  lookupLabels,
  lookupRecords,
  moduleExportUrl,
  previewModule,
  previewUpgrade,
  suggestForSpec,
  supportsFeatures,
  supportsUpgrade,
  upgradeModule,
  upgradeRefusalFrom,
  uninstallModule,
  updateModuleRecord,
  type ModuleSpec,
  type Vocabulary,
} from './api';

const get = vi.mocked(apiGet);
const post = vi.mocked(apiPost);
const patch = vi.mocked(apiPatch);
const del = vi.mocked(apiDelete);

/** As the server hands it back: `/api/v1/` plus the hyphenated key. */
const BASE_PATH = '/api/v1/pour-register';

const SPEC = { key: 'pour_register' } as unknown as ModuleSpec;

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(undefined as never);
  post.mockResolvedValue(undefined as never);
  patch.mockResolvedValue(undefined as never);
  del.mockResolvedValue(undefined as never);
});

describe('the builder endpoints', () => {
  it('asks for the vocabulary rather than carrying its own copy', async () => {
    await fetchVocabulary();
    expect(get).toHaveBeenCalledWith('/v1/module-builder/vocabulary');
  });

  it('gives the assistant call a long budget, because it goes out to a provider', async () => {
    await draftSpec('a register of concrete pours');
    expect(post).toHaveBeenCalledWith(
      '/v1/module-builder/draft',
      { description: 'a register of concrete pours' },
      { longRunning: true },
    );
  });

  it('previews and installs through the spec, not through a key', async () => {
    await previewModule(SPEC);
    expect(post).toHaveBeenCalledWith('/v1/module-builder/preview', { spec: SPEC });

    // Install carries the token preview handed back, so the server can tell a
    // reviewed spec from one that was never rendered for anybody to read.
    await installModule(SPEC, 'review-token-from-preview');
    expect(post).toHaveBeenCalledWith(
      '/v1/module-builder',
      { spec: SPEC, review_token: 'review-token-from-preview' },
      { longRunning: true },
    );
  });

  it('lists what is installed with no trailing slash', async () => {
    await fetchInstalledModules();
    // Every route in module_builder/router.py is declared without one, and the
    // other spelling only works through a 307.
    expect(get).toHaveBeenCalledWith('/v1/module-builder');
  });

  it('leaves the data alone unless removal was asked to drop it', async () => {
    await uninstallModule('pour_register');
    expect(del).toHaveBeenCalledWith('/v1/module-builder/pour_register');

    await uninstallModule('pour_register', true);
    expect(del).toHaveBeenLastCalledWith('/v1/module-builder/pour_register?drop_data=true');
  });

  it('escapes a key rather than pasting it into a URL', async () => {
    await uninstallModule('a/b');
    expect(del).toHaveBeenCalledWith('/v1/module-builder/a%2Fb');
  });
});

describe('a generated module', () => {
  it('reads its screen description from the path the server gave', async () => {
    await fetchModuleUiSpec(BASE_PATH);
    expect(get).toHaveBeenCalledWith('/api/v1/pour-register/ui-spec');
  });

  it('passes the base path through untouched', async () => {
    // The API helper strips its own `/api` prefix; doing it here as well would
    // produce `/v1/...` and a 404. This asserts we do not.
    await fetchModuleRecords(BASE_PATH);
    expect(get).toHaveBeenCalledWith(BASE_PATH);
  });

  it('sends the project only when there is one', async () => {
    await fetchModuleRecords(BASE_PATH, { projectId: 'p1', limit: 50, offset: 100 });
    expect(get).toHaveBeenCalledWith(`${BASE_PATH}?project_id=p1&limit=50&offset=100`);

    get.mockClear();
    await fetchModuleRecords(BASE_PATH, { projectId: null });
    expect(get).toHaveBeenCalledWith(BASE_PATH);
  });

  it('reads, writes, corrects and removes one record under the same path', async () => {
    await fetchModuleRecord(BASE_PATH, 'r1');
    expect(get).toHaveBeenCalledWith(`${BASE_PATH}/r1`);

    await createModuleRecord(BASE_PATH, { reference: 'P-1' });
    expect(post).toHaveBeenCalledWith(BASE_PATH, { reference: 'P-1' });

    await updateModuleRecord(BASE_PATH, 'r1', { reference: 'P-2' });
    expect(patch).toHaveBeenCalledWith(`${BASE_PATH}/r1`, { reference: 'P-2' });

    await deleteModuleRecord(BASE_PATH, 'r1');
    expect(del).toHaveBeenCalledWith(`${BASE_PATH}/r1`);
  });
});

describe('findingsFromError', () => {
  it('reads the findings a generated validator sends on a 422', () => {
    const body = {
      detail: [
        { code: 'VOLUME_POSITIVE', message: 'A pour of nothing is not a pour.', field: 'volume' },
      ],
    };
    expect(findingsFromError(body)).toEqual([
      { code: 'VOLUME_POSITIVE', message: 'A pour of nothing is not a pour.', field: 'volume' },
    ]);
  });

  it('does not mistake FastAPI own validation entries for module findings', () => {
    // Same envelope, different shape. Reading `msg` as a finding would show the
    // user a rule code that does not exist.
    const body = { detail: [{ loc: ['body', 'volume'], msg: 'field required', type: 'missing' }] };
    expect(findingsFromError(body)).toEqual([]);
  });

  it('says nothing about a body that is not one of those', () => {
    expect(findingsFromError({ detail: 'not found' })).toEqual([]);
    expect(findingsFromError('plain text')).toEqual([]);
    expect(findingsFromError(null)).toEqual([]);
    expect(findingsFromError(undefined)).toEqual([]);
  });

  it('keeps the module findings out of a mixed list rather than all of it', () => {
    const body = {
      detail: [
        { loc: ['body'], msg: 'nope', type: 'missing' },
        { code: 'REF_REQUIRED', message: 'Give it a reference.', field: 'reference' },
      ],
    };
    expect(findingsFromError(body)).toHaveLength(1);
    expect(findingsFromError(body)[0]?.code).toBe('REF_REQUIRED');
  });
});

describe('links and functions', () => {
  it("sends the reader's language with a draft only when asked to", async () => {
    await draftSpec('a register of concrete pours', 'de');
    expect(post).toHaveBeenCalledWith(
      '/v1/module-builder/draft',
      { description: 'a register of concrete pours', locale: 'de' },
      { longRunning: true },
    );
  });

  it('asks for suggestions on the spec as it stands', async () => {
    await suggestForSpec(SPEC);
    expect(post).toHaveBeenLastCalledWith('/v1/module-builder/suggest', { spec: SPEC });
    await suggestForSpec(SPEC, 'fr');
    expect(post).toHaveBeenLastCalledWith('/v1/module-builder/suggest', { spec: SPEC, locale: 'fr' });
  });

  it('searches the records a link can point at, inside the project', async () => {
    await lookupRecords('contract', { projectId: 'p1', q: 'frame' });
    expect(get).toHaveBeenCalledWith('/v1/module-builder/lookup/contract?project_id=p1&q=frame&limit=20');
    await lookupRecords('user');
    expect(get).toHaveBeenLastCalledWith('/v1/module-builder/lookup/user?limit=20');
  });

  it('asks for the names of stored links in one batch', async () => {
    await lookupLabels('document', ['a', 'b']);
    expect(get).toHaveBeenCalledWith('/v1/module-builder/lookup/document/labels?ids=a%2Cb');
  });

  it('splits a long list of ids into batches the server takes, and merges the answers', async () => {
    const ids = Array.from({ length: 501 }, (_, i) => `id-${i}`);
    get.mockImplementation(async (url: string) => {
      const asked = new URL(url, 'http://x').searchParams.get('ids')!.split(',');
      return { labels: Object.fromEntries(asked.map((id) => [id, id.toUpperCase()])) } as never;
    });
    const result = await lookupLabels('contract', ids);
    expect(get).toHaveBeenCalledTimes(2);
    expect(Object.keys(result.labels)).toHaveLength(501);
    expect(result.labels['id-500']).toBe('ID-500');
  });

  it("builds the export address on the module's own path", () => {
    expect(moduleExportUrl(BASE_PATH, 'xlsx')).toBe('/api/v1/pour-register/export?format=xlsx');
    expect(moduleExportUrl(BASE_PATH, 'csv', 'p1')).toBe('/api/v1/pour-register/export?format=csv&project_id=p1');
  });

  it('tells a server that knows links and functions from one that does not', () => {
    const old = { field_types: [], rule_kinds: [], reserved_field_names: [], reserved_keys: [], max_fields: 40, assistant_available: false } as Vocabulary;
    expect(supportsFeatures(undefined)).toBe(false);
    expect(supportsFeatures(old)).toBe(false);
    expect(supportsFeatures({ ...old, features: [] })).toBe(true);
    expect(supportsFeatures({ ...old, link_targets: [] })).toBe(true);
  });
});

describe('adding to an installed module', () => {
  it("previews and applies under the module's own key", async () => {
    await previewUpgrade('pour_register', SPEC);
    expect(post).toHaveBeenCalledWith('/v1/module-builder/pour_register/upgrade/preview', { spec: SPEC });
    await upgradeModule('pour_register', SPEC, 'tok');
    expect(post).toHaveBeenLastCalledWith(
      '/v1/module-builder/pour_register/upgrade',
      { spec: SPEC, review_token: 'tok' },
      { longRunning: true },
    );
  });

  it('is offered only by a server that says it can', () => {
    const v = { field_types: [], rule_kinds: [], reserved_field_names: [], reserved_keys: [], max_fields: 40, assistant_available: false, features: [] } as Vocabulary;
    expect(supportsUpgrade(v)).toBe(false);
    expect(supportsUpgrade({ ...v, upgrade: true })).toBe(true);
    expect(supportsUpgrade(undefined)).toBe(false);
  });

  it('reads the refusal of a change that is not an addition, and nothing else', () => {
    const refused = Object.assign(new Error('Conflict'), {
      status: 409,
      body: {
        detail: {
          code: 'upgrade_not_additive',
          message: 'Not additive.',
          params: {
            records: 3,
            problems: [
              { code: 'field_removed', field: 'notes', label: 'Notes' },
              { code: 'field_now_required', field: 'cast_on', empty: 2 },
              { nope: 1 },
            ],
          },
        },
      },
    });
    expect(upgradeRefusalFrom(refused)).toEqual({
      code: 'upgrade_not_additive',
      records: 3,
      problems: [
        { code: 'field_removed', field: 'notes', label: 'Notes' },
        { code: 'field_now_required', field: 'cast_on', empty: 2 },
      ],
      params: expect.objectContaining({ records: 3 }),
    });
    expect(upgradeRefusalFrom(Object.assign(new Error('x'), { status: 409, body: { detail: 'taken' } }))).toBeNull();
    expect(upgradeRefusalFrom(Object.assign(new Error('x'), { status: 422, body: { detail: { code: 'x' } } }))).toBeNull();
  });

  it('reads an install over kept entries in the same words as an upgrade, by field', () => {
    const refused = Object.assign(new Error('Conflict'), {
      status: 409,
      body: {
        detail: {
          code: 'layout_conflict',
          message: 'The table exists with a different layout.',
          params: {
            records: 5,
            fields: [
              { name: 'notes', label: 'Notes', problem: 'removed' },
              { name: 'poured_on', label: 'Poured on', problem: 'changed' },
              { name: 'volume', label: 'Volume', problem: 'now_required', empty: 4 },
            ],
          },
        },
      },
    });
    expect(upgradeRefusalFrom(refused)).toMatchObject({
      code: 'layout_conflict',
      records: 5,
      problems: [
        { code: 'field_removed', field: 'notes', label: 'Notes' },
        { code: 'field_retyped', field: 'poured_on', label: 'Poured on' },
        { code: 'field_now_required', field: 'volume', label: 'Volume', empty: 4 },
      ],
    });
  });

  it('reads a refusal that says only what happened, and an upgrade of a module no longer there', () => {
    const offline = Object.assign(new Error('Conflict'), {
      status: 409,
      body: { detail: { code: 'links_switched_off', message: 'x', params: { targets: ['contract'] } } },
    });
    expect(upgradeRefusalFrom(offline)).toEqual({
      code: 'links_switched_off',
      records: null,
      problems: [],
      params: { targets: ['contract'] },
    });
    const gone = Object.assign(new Error('Not Found'), {
      status: 404,
      body: { detail: { code: 'not_installed', message: 'x' } },
    });
    expect(upgradeRefusalFrom(gone)?.code).toBe('not_installed');
  });
});
