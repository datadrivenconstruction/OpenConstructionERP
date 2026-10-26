// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import {
  G_CHORDS,
  chordConflict,
  chordForRoute,
  chordKey,
  chordRoutes,
  gChordPref,
  setChordKey,
} from '../gChords';

const chord = (id: string) => G_CHORDS.find((c) => c.id === id)!;

beforeEach(() => {
  localStorage.clear();
  gChordPref.reset();
});

describe('G chords', () => {
  it('keep today\'s keys when nothing is remapped', () => {
    expect(chordRoutes('menu')).toEqual({
      d: '/', p: '/projects', b: '/boq', c: '/costs', m: '/bim', a: '/ai-estimate', ',': '/settings',
    });
    expect(chordRoutes('global')).toEqual({
      d: '/', p: '/projects', b: '/boq', c: '/costs', a: '/assemblies', v: '/validation', s: '/schedule',
      f: '/finance', '5': '/5d', r: '/reports', t: '/tendering', m: '/meetings', i: '/rfi', o: '/contacts',
    });
  });

  it('remaps one chord for every handler that reads it', () => {
    expect(setChordKey(chord('boq'), 'x')).toBe(true);
    expect(chordRoutes('menu').x).toBe('/boq');
    expect(chordRoutes('global').x).toBe('/boq');
    expect(chordRoutes('menu').b).toBeUndefined();
    expect(chordKey(chordForRoute('/boq')!)).toBe('x');
  });

  it('refuses a key another chord of the same handler already uses', () => {
    expect(chordConflict(chord('boq'), 'p')?.id).toBe('projects');
    expect(setChordKey(chord('boq'), 'p')).toBe(false);
    expect(chordKey(chord('boq'))).toBe('b');
    // The menu and global handlers have always shared m and a for different pages.
    expect(chordConflict(chord('rfi'), 'm')?.id).toBe('meetings');
    expect(chordConflict(chord('bim'), 'm')).toBeNull();
  });

  it('refuses keys that are not a single letter, digit or comma, and G itself', () => {
    for (const bad of ['g', 'ab', '', ' ', '/', 'É']) expect(setChordKey(chord('rfi'), bad)).toBe(false);
  });

  it('forgets a choice that goes back to the default and frees the old key', () => {
    setChordKey(chord('finance'), 'x');
    expect(setChordKey(chord('reports'), 'f')).toBe(true);
    expect(setChordKey(chord('reports'), 'r')).toBe(true);
    expect(setChordKey(chord('finance'), 'f')).toBe(true);
    expect(gChordPref.read()).toEqual({});
  });

  it('ignores stored junk', () => {
    const stop = gChordPref.subscribe(() => {});
    localStorage.setItem('oe_g_chords_v1', JSON.stringify({ boq: 'q', nope: 'z', rfi: 'gg', costs: 'c', schedule: 7 }));
    window.dispatchEvent(new StorageEvent('storage', { key: 'oe_g_chords_v1' }));
    stop();
    expect(gChordPref.read()).toEqual({ boq: 'q' });
  });
});
