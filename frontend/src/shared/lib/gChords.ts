// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "G then a key" navigation chords, in one table. The menu and the global
 * shortcut hook both read their keys from here, so a key a person remaps in
 * Settings > General applies to both, to the hint beside the menu row and to
 * the shortcuts dialog. Kept on this device; with nothing chosen every chord is
 * the one it always was.
 */
import { createLocalPref } from './localPref';

export type ChordHandler = 'menu' | 'global';

export interface GChord {
  id: string;
  route: string;
  /** The key after G when nothing is remapped. */
  key: string;
  labelKey: string;
  fallback: string;
  /** Which keyboard handlers act on this chord. */
  handlers: readonly ChordHandler[];
}

const BOTH = ['menu', 'global'] as const;

export const G_CHORDS: readonly GChord[] = [
  { id: 'dashboard', route: '/', key: 'd', labelKey: 'nav.dashboard', fallback: 'Dashboard', handlers: BOTH },
  { id: 'projects', route: '/projects', key: 'p', labelKey: 'projects.title', fallback: 'Projects', handlers: BOTH },
  { id: 'boq', route: '/boq', key: 'b', labelKey: 'boq.title', fallback: 'Bills of quantities', handlers: BOTH },
  { id: 'costs', route: '/costs', key: 'c', labelKey: 'costs.title', fallback: 'Cost database', handlers: BOTH },
  { id: 'bim', route: '/bim', key: 'm', labelKey: 'nav.bim_viewer', fallback: 'BIM viewer', handlers: ['menu'] },
  { id: 'ai_estimate', route: '/ai-estimate', key: 'a', labelKey: 'nav.ai_estimate', fallback: 'AI estimate', handlers: ['menu'] },
  { id: 'settings', route: '/settings', key: ',', labelKey: 'sidebar.admin_grid.settings', fallback: 'Settings', handlers: ['menu'] },
  { id: 'assemblies', route: '/assemblies', key: 'a', labelKey: 'nav.assemblies', fallback: 'Assemblies', handlers: ['global'] },
  { id: 'validation', route: '/validation', key: 'v', labelKey: 'validation.title', fallback: 'Validation', handlers: ['global'] },
  { id: 'schedule', route: '/schedule', key: 's', labelKey: 'schedule.title', fallback: 'Schedule', handlers: ['global'] },
  { id: 'finance', route: '/finance', key: 'f', labelKey: 'finance.title', fallback: 'Finance', handlers: ['global'] },
  { id: 'cost_model_5d', route: '/5d', key: '5', labelKey: 'nav.5d_cost_model', fallback: '5D cost model', handlers: ['global'] },
  { id: 'reports', route: '/reports', key: 'r', labelKey: 'nav.reports', fallback: 'Reports', handlers: ['global'] },
  { id: 'tendering', route: '/tendering', key: 't', labelKey: 'tendering.title', fallback: 'Tendering', handlers: ['global'] },
  { id: 'meetings', route: '/meetings', key: 'm', labelKey: 'meetings.title', fallback: 'Meetings', handlers: ['global'] },
  { id: 'rfi', route: '/rfi', key: 'i', labelKey: 'rfi.title', fallback: 'RFIs', handlers: ['global'] },
  { id: 'contacts', route: '/contacts', key: 'o', labelKey: 'contacts.title', fallback: 'Contacts', handlers: ['global'] },
];

/** A key a chord can use: one letter, digit or comma. G itself would start a new chord. */
export const isChordKey = (k: string): boolean => /^[a-z0-9,]$/.test(k) && k !== 'g';

/** Chord id to the key the person chose; only keys that differ from the default are stored. */
export const gChordPref = createLocalPref<Record<string, string>>('oe_g_chords_v1', (raw) => {
  const out: Record<string, string> = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const chord of G_CHORDS) {
    const k = (raw as Record<string, unknown>)[chord.id];
    if (typeof k === 'string' && isChordKey(k) && k !== chord.key) out[chord.id] = k;
  }
  return out;
});

export const chordKey = (chord: GChord, chosen: Record<string, string> = gChordPref.read()): string =>
  chosen[chord.id] ?? chord.key;

/** Key to route for one handler, with the person's choices applied. */
export function chordRoutes(handler: ChordHandler): Record<string, string> {
  const chosen = gChordPref.read();
  const out: Record<string, string> = {};
  for (const chord of G_CHORDS) {
    if (chord.handlers.includes(handler)) out[chordKey(chord, chosen)] = chord.route;
  }
  return out;
}

/** The chord for a menu row, if it has one. */
export function chordForRoute(route: string): GChord | undefined {
  return G_CHORDS.find((c) => c.route === route && c.handlers.includes('menu'));
}

/**
 * The chord that would clash if `chord` took `key`: another chord read by the
 * same handler that already uses it. Null when the key is free.
 */
export function chordConflict(
  chord: GChord,
  key: string,
  chosen: Record<string, string> = gChordPref.read(),
): GChord | null {
  for (const other of G_CHORDS) {
    if (other.id === chord.id || chordKey(other, chosen) !== key) continue;
    if (other.handlers.some((h) => chord.handlers.includes(h))) return other;
  }
  return null;
}

/** Store one chord's key (or drop it when it is the default again). */
export function setChordKey(chord: GChord, key: string): boolean {
  if (!isChordKey(key) || chordConflict(chord, key)) return false;
  const next = { ...gChordPref.read() };
  if (key === chord.key) delete next[chord.id];
  else next[chord.id] = key;
  gChordPref.write(next);
  return true;
}
