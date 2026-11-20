import { describe, expect, it } from 'vitest';
import { checkMessage } from '../bridge/protocol';
import type { EstimatePosition } from './estimate';
import type { RevisionView } from './revisions';
import type { BriefDoc } from './briefModel';
import { aiConfigured, aiServices, chainTip, changedLines, deviceMode, draftLinesFor, keepConfirmed, linesFor, openMessage, proposals, ruleMatch } from './workspace';
import type { DraftView } from '../draftApi';

const PID = '746402cb-14a8-430c-b3b9-9c6908fa75d7';
const rev = (n: number, status: RevisionView['status'], imported = false): RevisionView => ({
  revision_id: `9c1d2e3f-4a5b-4c6d-8e7f-0a1b2c3d4e5${n}`, project_id: PID, number: n, parent_revision_id: null, status,
  source_kind: imported ? 'imported' : 'generated', depth_level: 'D2', message: '', bim_model_id: 'm', decided_by: null,
  decided_at: null, decision_comment: null, created_at: '2026-11-15T10:00:00Z',
  manifest: imported ? { schema: 'ddc-import/1' } : ({ schema: 'ddc-revision/1', files: [{ path: 'geometry.glb', role: 'geometry', bytes: 9, sha256: 'a'.repeat(64) }] } as RevisionView['manifest']),
} as RevisionView);

describe('open message', () => {
  it('names the chain tip (never an import, never rejected) and passes the contract schema', () => {
    const revs = [rev(1, 'published'), rev(2, 'shared'), rev(3, 'rejected'), rev(4, 'shared', true)];
    expect(chainTip(revs)?.number).toBe(2);
    const msg = openMessage({ project: { id: PID, name: 'Haus' }, brief: null, revisions: revs, locale: 'de', theme: 'dark',
      draft: null, mode: 'edit', canEdit: true, canAccept: false, ai: true });
    expect(msg.revision).toMatchObject({ number: 2, status: 'shared',
      files: [{ path: 'geometry.glb', url: `/api/v1/design/revisions/${rev(2, 'shared').revision_id}/files/geometry.glb` }] });
    expect(checkMessage(msg, 'host')).toEqual([]);
    expect(openMessage({ project: { id: PID, name: '' }, brief: null, revisions: [], locale: 'en', theme: 'light',
      draft: null, mode: 'edit', canEdit: false, canAccept: false, ai: false }).revision).toBeNull();
  });

  it('without the edit right the editor opens for viewing, whatever the device', () => {
    const msg = openMessage({ project: { id: PID, name: 'Haus' }, brief: null, revisions: [], locale: 'en', theme: 'light',
      draft: null, mode: 'edit', canEdit: false, canAccept: false, ai: false });
    expect(msg.mode).toBe('view');
    expect(checkMessage(msg, 'host')).toEqual([]);
  });

  it('tablets and phones look and select; desktops edit', () => {
    expect(deviceMode({ finePointer: true, width: 1440 })).toBe('edit');
    expect(deviceMode({ finePointer: false, width: 1366 })).toBe('view'); // tablet in landscape
    expect(deviceMode({ finePointer: true, width: 400 })).toBe('view');
  });
});

describe('draft lines', () => {
  const line = (rule: string, keys: string[], q: string | null, cur: string | null) => ({
    rule, unit: 'm2', elements: keys.length, element_keys: keys, quantity: q, current_quantity: cur, unit_rate: '0',
    total: null, current_total: '0', position_id: rule, description: rule, flags: [] });
  const draft = { estimate: { estimate: true, model_total: '0', lines: [
    line('wall_ext', ['w1', 'w2'], '88.1', '82.5'), line('door', ['d1'], '1', '1'), line('roof', [], '0', '0')] } } as unknown as DraftView;

  it('are exact for the selection and list what the draft changes', () => {
    expect(draftLinesFor([{ element_key: 'w2' }], draft).map((l) => l.rule)).toEqual(['wall_ext']);
    expect(draftLinesFor([], draft)).toEqual([]);
    expect(draftLinesFor([{ element_key: 'w1' }], null)).toEqual([]);
    expect(changedLines(draft).map((l) => l.rule)).toEqual(['wall_ext']);
  });
});

const pos = (rule: string, select: unknown, kind: EstimatePosition['kind'] = 'model') => ({
  rule, kind, position_id: rule, ordinal: '1', description: rule, cost_group: '300', unit: 'm2', quantity: '10',
  unit_rate: '5', total: '50', model_quantity: '10', override: false, override_quantity: null, override_reason: null,
  flags: [], elements: 1, provenance: { select },
}) as EstimatePosition;

describe('side panel lines', () => {
  const rules = [
    pos('foundation', { any_of: [{ ifc_class: ['IfcFooting'] }, { ifc_class: ['IfcSlab'], type_key_prefix: ['slab/foundation'] }] }),
    pos('wall_ext', { ifc_class: ['IfcWall'], type_key_prefix: ['wall/ext'] }),
    pos('wall_int', { ifc_class: ['IfcWall'], type_key_not_prefix: ['wall/ext'] }),
    pos('window', { ifc_class: ['IfcWindow'] }),
    pos('finishes', undefined, 'derived'),
  ];

  it('decides what it can and says maybe where the type is unknown', () => {
    expect(ruleMatch({ element_key: 'k', ifc_class: 'IfcWindow' }, { ifc_class: ['IfcWindow'] })).toBe('yes');
    expect(ruleMatch({ element_key: 'k', ifc_class: 'IfcWall' }, { ifc_class: ['IfcWall'], type_key_prefix: ['wall/ext'] })).toBe('maybe');
    expect(ruleMatch({ element_key: 'k', ifc_class: 'IfcWall', type_key: 'wall/int/1' }, { ifc_class: ['IfcWall'], type_key_prefix: ['wall/ext'] })).toBe('no');
    expect(ruleMatch({ element_key: 'k', ifc_class: 'IfcDoor' }, { ifc_class: ['IfcWall'], storey: 'L01' })).toBe('no');
    expect(ruleMatch({ element_key: 'k', ifc_class: 'IfcWall' }, { ifc_class: ['IfcWall'], storey: 'L01' })).toBe('maybe');
  });

  it('lists model lines only, decided ones first', () => {
    expect(linesFor([{ element_key: 'k', ifc_class: 'IfcWall', type_key: 'wall/ext/240' }], rules).map((l) => [l.position.rule, l.match]))
      .toEqual([['wall_ext', 'yes']]);
    expect(linesFor([{ element_key: 'k', ifc_class: 'IfcWall' }], rules).map((l) => l.position.rule)).toEqual(['wall_ext', 'wall_int']);
    expect(linesFor([{ element_key: 'k', ifc_class: 'IfcSlab' }], rules).map((l) => [l.position.rule, l.match])).toEqual([['foundation', 'maybe']]);
    expect(linesFor([], rules)).toEqual([]);
  });
});

describe('AI draft', () => {
  const draft = {
    schema: 'ddc-brief/1', brief_id: 'b', project_id: PID, version: 1,
    use: { primary: 'residential' }, massing: { floors_above: 4, floor_height_m: 3 }, country: 'DE',
    provenance: {
      '/use/primary': { status: 'proposed', sources: [{ kind: 'text', quote: 'Wohnhaus' }] },
      '/massing/floors_above': { status: 'proposed', sources: [{ kind: 'text', quote: '4 Geschosse' }] },
      '/massing/floor_height_m': { status: 'proposed', sources: [{ kind: 'text', quote: '3 m' }] },
      '/country': { status: 'default' },
    },
  } as unknown as BriefDoc;
  const proposed = ['/massing/floor_height_m', '/massing/floors_above', '/use/primary'];

  it('keeps only the values the person ticked; defaults untouched', () => {
    const out = keepConfirmed(draft, proposed, ['/massing/floors_above']) as unknown as Record<string, unknown>;
    expect(out.massing).toEqual({ floors_above: 4 });
    expect(out.use).toEqual({}); // the brief keeps its top-level sections
    expect(out.country).toBe('DE');
    expect(Object.keys((out as unknown as BriefDoc).provenance!).sort()).toEqual(['/country', '/massing/floors_above']);
  });

  it('shows each proposal with its quote', () => {
    expect(proposals(draft, ['/massing/floors_above'])).toEqual([{ pointer: '/massing/floors_above', value: 4, quote: '4 Geschosse', page: null }]);
  });

  it('AI counts as set up only with a key or an endpoint', () => {
    expect(aiConfigured(null)).toBe(false);
    expect(aiConfigured({ a_api_key_set: false, b_base_url: null })).toBe(false);
    expect(aiConfigured({ a_api_key_set: true })).toBe(true);
    expect(aiConfigured({ b_base_url: 'http://localhost:11434' })).toBe(true);
    expect(aiServices({ b_base_url: 'http://localhost:11434', a_api_key_set: true, c_api_key_set: false })).toEqual(['a', 'b']);
  });
});
