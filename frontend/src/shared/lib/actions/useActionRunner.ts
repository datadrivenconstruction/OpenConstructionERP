// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Running actions from React: the context they need, the recent list, and the
 * global keyboard dispatcher for their shortcuts.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { runAction, useActions, type ActionContext, type PaletteAction } from './registry';
import { SEQUENCE_TIMEOUT_MS, effectiveBindings, eventToChord, useShortcutStore } from './shortcuts';

/* ── Recent actions (per browser) ─────────────────────────────────────── */

export const RECENT_ACTIONS_KEY = 'oe_palette_recent_actions_v1';
export const MAX_RECENT_ACTIONS = 6;

export interface RecentAction {
  actionId: string;
  projectId?: string | null;
  projectName?: string;
}

export function loadRecentActions(): RecentAction[] {
  try {
    const raw = localStorage.getItem(RECENT_ACTIONS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed)
      ? parsed.filter((r): r is RecentAction => !!r && typeof (r as RecentAction).actionId === 'string')
      : [];
  } catch {
    return [];
  }
}

export function pushRecentAction(entry: RecentAction): void {
  try {
    const key = (r: RecentAction) => `${r.actionId}|${r.projectId ?? ''}`;
    const next = [entry, ...loadRecentActions().filter((r) => key(r) !== key(entry))].slice(0, MAX_RECENT_ACTIONS);
    localStorage.setItem(RECENT_ACTIONS_KEY, JSON.stringify(next));
  } catch {
    // Storage unavailable: the palette simply shows no recent row.
  }
}

/* ── Runner ───────────────────────────────────────────────────────────── */

export interface ProjectRef {
  id: string;
  name: string;
}

/** `run(action, project?)`: builds the context, runs, remembers it as recent. */
export function useActionRunner(): (action: PaletteAction, project?: ProjectRef | null) => void {
  const navigate = useNavigate();
  return useCallback(
    (action: PaletteAction, project?: ProjectRef | null) => {
      const active = useProjectContextStore.getState();
      const target = project ?? (active.activeProjectId ? { id: active.activeProjectId, name: active.activeProjectName } : null);
      const ctx: ActionContext = {
        navigate: (to) => navigate(to),
        projectId: target?.id ?? null,
        projectName: target?.name ?? '',
        setActiveProject: (id, name) => active.setActiveProject(id, name),
      };
      runAction(action, ctx);
      pushRecentAction({
        actionId: action.id,
        projectId: action.scope === 'project' && project ? project.id : null,
        projectName: action.scope === 'project' && project ? project.name : undefined,
      });
    },
    [navigate],
  );
}

/** Actions whose module is switched on. */
export function useAvailableActions(): readonly PaletteAction[] {
  const actions = useActions();
  const { isModuleEnabled } = useModuleStore();
  return useMemo(() => actions.filter((a) => !a.moduleKey || isModuleEnabled(a.moduleKey)), [actions, isModuleEnabled]);
}

/** actionId → binding in force (defaults plus the user's changes). */
export function useBindings(): Map<string, string> {
  const actions = useActions();
  const overrides = useShortcutStore((s) => s.overrides);
  return useMemo(() => effectiveBindings(actions, overrides), [actions, overrides]);
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable === true;
}

/**
 * Listen for action shortcuts anywhere in the app. Sequences and chords are
 * ignored while typing, while `paused` (the palette is recording a binding)
 * and when another handler already took the event.
 */
export function useActionShortcuts(paused = false): void {
  const actions = useAvailableActions();
  const bindings = useBindings();
  const run = useActionRunner();
  const pending = useRef<{ key: string; at: number } | null>(null);

  useEffect(() => {
    if (paused) return;
    const byShortcut = new Map<string, PaletteAction>();
    for (const a of actions) {
      const sc = bindings.get(a.id);
      if (sc) byShortcut.set(sc, a);
    }
    if (byShortcut.size === 0) return;

    const handler = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.repeat) return;
      if (isTypingTarget(e.target)) return;
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      const chord = eventToChord(e);
      if (!chord) return;
      if (chord.includes('+') || /^F\d+$/.test(chord)) {
        const hit = byShortcut.get(chord);
        pending.current = null;
        if (hit) {
          e.preventDefault();
          run(hit);
        }
        return;
      }
      if (!/^[A-Z0-9]$/.test(chord)) {
        pending.current = null;
        return;
      }
      const now = Date.now();
      const first = pending.current;
      if (first && now - first.at <= SEQUENCE_TIMEOUT_MS) {
        pending.current = null;
        const hit = byShortcut.get(`${first.key} ${chord}`);
        if (hit) {
          e.preventDefault();
          run(hit);
          return;
        }
      }
      pending.current = { key: chord, at: now };
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [actions, bindings, run, paused]);
}
