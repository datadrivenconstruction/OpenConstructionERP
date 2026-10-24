// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  __resetActionsForTests,
  getAction,
  listActions,
  registerActions,
  runAction,
  type ActionContext,
  type PaletteAction,
} from '../registry';
import { foldText, fuzzyScore, matchProject, splitProjectQuery, MIN_SCORE } from '../fuzzy';
import {
  checkShortcut,
  defaultConflicts,
  effectiveBindings,
  eventToChord,
  formatShortcut,
  normalizeShortcut,
} from '../shortcuts';
import { CORE_ACTIONS, buildNavActions, navActionId } from '@/app/actions/coreActions';
import { MODULE_REGISTRY } from '@/modules/_registry';

const a = (id: string, extra: Partial<PaletteAction> = {}): PaletteAction => ({
  id,
  titleKey: `t.${id}`,
  defaultTitle: id,
  group: 'create',
  ...extra,
});

function ctx(over: Partial<ActionContext> = {}): ActionContext {
  return { navigate: vi.fn(), projectId: null, projectName: '', setActiveProject: vi.fn(), ...over };
}

describe('action registry', () => {
  beforeEach(() => __resetActionsForTests());
  afterEach(() => __resetActionsForTests());

  it('registers per source, replaces on re-register and unregisters', () => {
    const off = registerActions('mod:a', [a('x.one'), a('x.two')]);
    expect(listActions().map((x) => x.id)).toEqual(['x.one', 'x.two']);
    registerActions('mod:a', [a('x.three')]);
    expect(listActions().map((x) => x.id)).toEqual(['x.three']);
    off(); // stale unregister of the replaced list does nothing
    expect(getAction('x.three')).toBeDefined();
  });

  it('keeps the first registration of an id, so a module cannot hijack a core action', () => {
    registerActions('core', [a('boq.new', { defaultTitle: 'core' })]);
    registerActions('module:evil', [a('boq.new', { defaultTitle: 'evil' })]);
    expect(getAction('boq.new')?.defaultTitle).toBe('core');
  });

  it('drops ids outside the id pattern', () => {
    registerActions('m', [a('Bad Id'), a('ok.id')]);
    expect(listActions().map((x) => x.id)).toEqual(['ok.id']);
  });

  it('runs a project action against the picked project and sends a project-less one to the list', () => {
    const scoped = a('project.boq', { scope: 'project', path: '/projects/:projectId/boq' });
    const c = ctx({ projectId: 'p1', projectName: 'Berlin' });
    runAction(scoped, c);
    expect(c.setActiveProject).toHaveBeenCalledWith('p1', 'Berlin');
    expect(c.navigate).toHaveBeenCalledWith('/projects/p1/boq');
    const none = ctx();
    runAction(scoped, none);
    expect(none.navigate).toHaveBeenCalledWith('/projects');
  });

  it('turns every plain menu row into a navigate action with a stable id', () => {
    const nav = buildNavActions();
    expect(nav.find((x) => x.id === navActionId('/finance'))?.path).toBe('/finance');
    expect(new Set(nav.map((x) => x.id)).size).toBe(nav.length);
  });

  it('takes actions from module manifests (GAEB import)', () => {
    const gaeb = MODULE_REGISTRY.find((m) => m.id === 'gaeb-exchange');
    const imp = gaeb?.actions?.find((x) => x.id === 'gaeb.import');
    expect(imp).toBeDefined();
    const c = ctx({ projectId: 'p 1' });
    imp!.run!(c);
    expect(c.navigate).toHaveBeenCalledWith('/gaeb-exchange?project_id=p%201&tab=import');
  });

  it('ships default shortcuts that clash with nothing', () => {
    const all = [
      ...CORE_ACTIONS,
      ...buildNavActions(),
      ...MODULE_REGISTRY.flatMap((m) => m.actions ?? []),
    ];
    expect(defaultConflicts(all)).toEqual([]);
  });
});

describe('fuzzy match', () => {
  it('folds accents and case in the UI locale', () => {
    expect(foldText('Kostenschätzung', 'de')).toBe('kostenschatzung');
    expect(foldText('İSTANBUL', 'tr')).toBe('istanbul');
  });

  it('matches substrings, word starts and subsequences, in any script', () => {
    expect(fuzzyScore('neue kost', ['Neue Kostenschätzung'], 'de')).toBeGreaterThan(0.85);
    expect(fuzzyScore('смет', ['Новая смета'], 'ru')).toBeGreaterThan(0.85);
    expect(fuzzyScore('nwest', ['New estimate'], 'en')).toBeGreaterThan(MIN_SCORE);
    expect(fuzzyScore('見積', ['新しい見積'], 'ja')).toBeGreaterThan(0.7);
    expect(fuzzyScore('zebra', ['New estimate'], 'en')).toBe(0);
  });

  it('ranks a word-start hit above a hit inside a word', () => {
    expect(fuzzyScore('est', ['New estimate'])).toBeGreaterThan(fuzzyScore('est', ['Contest list']));
  });

  it('reads "project Berlin > quantities"', () => {
    expect(splitProjectQuery('project Berlin > quantities')).toEqual({ project: 'project Berlin', action: 'quantities' });
    expect(splitProjectQuery('quantities')).toBeNull();
    const projects = [{ name: 'Berlin Office Tower' }, { name: 'Munich Depot' }];
    expect(matchProject('project Berlin', projects)?.name).toBe('Berlin Office Tower');
    expect(matchProject('Projekt münch', projects, 'de')?.name).toBe('Munich Depot');
    expect(matchProject('Paris', projects)).toBeNull();
  });
});

describe('shortcuts', () => {
  it('normalizes chords and sequences', () => {
    expect(normalizeShortcut('ctrl+shift+e')).toBe('Mod+Shift+E');
    expect(normalizeShortcut('cmd+alt+1')).toBe('Mod+Alt+1');
    expect(normalizeShortcut('g b')).toBe('G B');
    expect(normalizeShortcut('g b c')).toBe('');
    expect(normalizeShortcut('Hyper+X')).toBe('');
  });

  it('refuses browser and OS chords and the app launchers', () => {
    const none = new Map<string, string>();
    for (const sc of ['Mod+T', 'Mod+W', 'Mod+N', 'Mod+Shift+N', 'Mod+L', 'Mod+R', 'Mod+P', 'Mod+S', 'Mod+K', 'Mod+Shift+K', 'Alt+F4', 'F5', 'Mod+1', 'Alt+E']) {
      expect(checkShortcut(sc, 'x', none)?.problem, sc).toBe('reserved');
    }
    expect(checkShortcut('E', 'x', none)?.problem).toBe('needs_modifier');
    expect(checkShortcut('Shift+E', 'x', none)?.problem).toBe('needs_modifier');
    expect(checkShortcut('Mod+Alt+E', 'x', none)).toBeNull();
    expect(checkShortcut('G B', 'x', none)).toBeNull();
  });

  it('reports which action already holds a binding', () => {
    const taken = new Map([['G B', 'nav./boq']]);
    expect(checkShortcut('g b', 'theme.dark', taken)).toEqual({ problem: 'conflict', holder: 'nav./boq' });
    expect(checkShortcut('G B', 'nav./boq', taken)).toBeNull();
  });

  it("lets the user's binding win over a default, which then steps aside", () => {
    const actions = [
      { id: 'nav./boq', defaultShortcut: 'G B' },
      { id: 'theme.dark' },
      { id: 'ai.open', defaultShortcut: 'A I' },
    ];
    const b = effectiveBindings(actions, { 'theme.dark': 'G B', 'ai.open': null });
    expect(b.get('theme.dark')).toBe('G B');
    expect(b.has('nav./boq')).toBe(false);
    expect(b.has('ai.open')).toBe(false);
  });

  it('reads chords off key events by physical key', () => {
    expect(eventToChord({ key: 'é', code: 'KeyE', ctrlKey: true, metaKey: false, altKey: true, shiftKey: false })).toBe('Mod+Alt+E');
    expect(eventToChord({ key: 'g', code: 'KeyG', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false })).toBe('G');
    expect(eventToChord({ key: 'Shift', code: 'ShiftLeft', ctrlKey: false, metaKey: false, altKey: false, shiftKey: true })).toBe('');
  });

  it('formats for the platform', () => {
    expect(formatShortcut('Mod+Shift+E', false)).toBe('Ctrl+Shift+E');
    expect(formatShortcut('Mod+Shift+E', true)).toBe('⌘⇧E');
    expect(formatShortcut('G B', true)).toBe('G B');
  });
});
